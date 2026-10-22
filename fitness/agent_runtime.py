"""Reusable read-tool / candidate / repair loop without persistence authority."""

import json
from dataclasses import asdict
from uuid import uuid4

from pydantic import ValidationError

from .agent_contracts import RunResult, ValidationIssue
from .plan_streaming import emit_plan_event, plan_events
from .provider import ProviderError, _json_loads, _matches_schema


class AgentRuntime:
    def __init__(self, provider, limits, *, clock):
        self.provider, self.limits, self.clock = provider, limits, clock

    def run(self, *, role, task, tools, validate):
        started = self.clock()
        deadline = started + self.limits.timeout_seconds
        trace = {'status': 'running', 'calls': 0, 'usage': {}, 'tool_calls': [],
                 'revisions': 0, 'validation': [], 'model': getattr(
                     getattr(self.provider, 'settings', None), 'model', None)}
        run_id = str(uuid4())

        def finish(status, candidate=None, questions=None, reason=None):
            trace.update(status='ok' if status == 'draft_ready' else status,
                         elapsed_ms=round((self.clock() - started) * 1000))
            trace['run_id'] = run_id
            if reason:
                trace['reason'] = reason
            return RunResult(run_id, status, candidate, questions or [], reason, trace)

        role += (f'\n本次最多{self.limits.max_tools}次工具调用、{self.limits.max_calls}轮模型响应。'
                 '直接利用已有信息，避免重复查询；最终候选会自动校验，无须反复预检。')
        messages = [{'role': 'system', 'content': role},
                    {'role': 'user', 'content': json.dumps(task, ensure_ascii=False, allow_nan=False)}]
        schemas = tools.schemas()
        allowed = {t['function']['name']: t['function']['parameters'] for t in schemas}
        if plan_events.get() is not None:
            phase = '补剂建议' if '补剂规划 Agent' in role else '训练安排' if '训练规划' in role else '饮食安排'
            emit_plan_event('phase', {'message': phase})
            trace['calls'] += 1
            try:
                remaining = deadline - self.clock()
                if remaining <= 0:
                    return finish('failed', reason='run_timeout')
                preview = self.provider.complete(messages + [{'role': 'system', 'content':
                    '本轮先输出供用户直接阅读的中文计划草稿，稍后另行整理数据。'
                    '本轮覆盖前文只输出JSON的格式要求：不要输出JSON、字段名或代码块，'
                    '不要描述内部思考过程。遵守前文全部用户事实、健康限制和规划规则。'
                    '用简洁自然的段落或列表写出实际安排、必要的假设和注意事项；'
                    '资料不足时保守处理，存在无法安全处理的风险时明确提出问题。'
                    '这是尚待校验的草稿，不声称已经保存或确认。'}],
                    timeout_seconds=min(getattr(getattr(self.provider, 'settings', None),
                        'timeout_seconds', 60), remaining),
                    max_output_tokens=self.limits.max_output_tokens,
                    on_text=lambda text: emit_plan_event('text', {'text': text}))
            except ProviderError as exc:
                return finish('failed', reason=exc.reason_code)
            for key, value in preview.usage.items():
                if type(value) is int and value >= 0:
                    trace['usage'][key] = trace['usage'].get(key, 0) + value
            messages.extend([{'role': 'assistant', 'content': preview.content},
                {'role': 'user', 'content': '现在将刚才的可读草稿整理为前文契约要求的JSON。'
                    '沿用草稿的安排，不另起一份不同的计划；必要时根据事实和校验结果修正。'
                    '仅输出JSON，仍须遵守安全限制和字段契约。'}])
            emit_plan_event('status', {'message': '可读建议已生成，正在整理和校验计划…'})
        while trace['calls'] < self.limits.max_calls:
            if self.clock() >= deadline:
                return finish('failed', reason='run_timeout')
            trace['calls'] += 1
            emit_plan_event('status', {'message': '正在整理和校验计划…'})
            try:
                reply = self.provider.complete(messages, schemas,
                    timeout_seconds=min(getattr(getattr(self.provider, 'settings', None),
                        'timeout_seconds', 60), deadline - self.clock()),
                    max_output_tokens=self.limits.max_output_tokens)
            except ProviderError as exc:
                return finish('failed', reason=exc.reason_code)
            for key, value in reply.usage.items():
                if type(value) is int and value >= 0:
                    trace['usage'][key] = trace['usage'].get(key, 0) + value
            if self.clock() >= deadline:
                return finish('failed', reason='run_timeout')
            if reply.tool_calls:
                calls = reply.tool_calls
                if (not isinstance(calls, list) or len(calls) > 8
                        or any(not isinstance(call, dict) or call.get('name') not in allowed
                               or not isinstance(call.get('id'), str) or not call['id'] for call in calls)
                        or len({call['id'] for call in calls}) != len(calls)):
                    return finish('failed', reason='tool_invalid')
                if len(trace['tool_calls']) + len(calls) > self.limits.max_tools:
                    return finish('failed', reason='tool_limit')
                messages.append({'role': 'assistant', 'content': reply.content, 'tool_calls': [{
                    'id': call['id'], 'type': 'function', 'function': {'name': call['name'],
                        'arguments': json.dumps(call.get('arguments'), ensure_ascii=False)}} for call in calls]})
                # Multiple requested tools are executed sequentially within the root budget.
                for call in calls:
                    if self.clock() >= deadline:
                        return finish('failed', reason='run_timeout')
                    name, arguments = call['name'], call.get('arguments')
                    item = {'name': name, 'status': 'ok', 'sequence': len(trace['tool_calls']) + 1}
                    try:
                        if not _matches_schema(arguments, allowed[name]):
                            raise ValueError('invalid_arguments')
                        output = tools.call(name, arguments)
                        encoded = json.dumps(output, ensure_ascii=False, allow_nan=False)
                        if len(encoded.encode('utf-8')) > 32000:
                            return finish('failed', reason='tool_result_too_large')
                    except (ValueError, TypeError, KeyError):
                        item['status'] = 'invalid_arguments'
                        encoded = json.dumps({'status': 'invalid_arguments',
                            'message': '参数不符合工具契约，请检查字段、类型和范围。'}, ensure_ascii=False)
                    trace['tool_calls'].append(item)
                    messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': encoded})
                continue
            try:
                if not isinstance(reply.content, str) or len(reply.content.encode('utf-8')) > 128000:
                    raise ValueError('output_invalid')
                parsed = _json_loads(reply.content)
                if (not isinstance(parsed, dict) or not {'status', 'candidate'} <= parsed.keys()
                        or not parsed.keys() <= {'status', 'candidate', 'questions'}):
                    raise ValueError('output_invalid')
                questions = parsed.get('questions', [])
                if (not isinstance(questions, list) or len(questions) > 10
                        or any(not isinstance(q, str) or not q.strip() or len(q) > 2000 for q in questions)):
                    raise ValueError('output_invalid')
                if parsed['status'] == 'needs_input' and parsed['candidate'] is None and questions:
                    return finish('needs_input', questions=questions, reason='planning_needs_input')
                if parsed['status'] != 'draft_ready' or not isinstance(parsed['candidate'], dict):
                    raise ValueError('output_invalid')
                candidate = parsed['candidate']
                issues = validate(candidate, tools.retrieved_sources)
                if self.clock() >= deadline:
                    return finish('failed', reason='run_timeout')
                if not issues:
                    return finish('draft_ready', candidate=candidate, questions=questions)
            except (ValueError, TypeError, KeyError, ValidationError):
                issues = [ValidationIssue('output', 'schema', '请输出符合契约的完整 JSON，不要省略字段。')]
            trace['validation'].append([asdict(issue) for issue in issues])
            if trace['revisions'] >= self.limits.max_revisions:
                return finish('failed', reason='output_invalid')
            trace['revisions'] += 1
            messages.extend([{'role': 'assistant', 'content': reply.content},
                {'role': 'user', 'content': json.dumps({'validation_errors': [asdict(i) for i in issues],
                    'instruction': '修订候选并重新提交；缺少关键条件时返回 needs_input。'}, ensure_ascii=False)}])
        return finish('failed', reason='call_limit')
