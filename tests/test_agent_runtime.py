import json

import pytest

from fitness.provider import ProviderError, ProviderReply


class ScriptProvider:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.messages = []

    def complete(self, messages, tools=None, **kwargs):
        self.messages.append(json.loads(json.dumps(messages)))
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply


def final(candidate=None, status='draft_ready', questions=None):
    return ProviderReply(content=json.dumps({'status': status, 'candidate': candidate,
        'questions': questions or []}), usage={'total_tokens': 7})


class Tools:
    def __init__(self):
        self.retrieved_sources = {}

    def schemas(self):
        return [{'type': 'function', 'function': {'name': 'read', 'parameters': {
            'type': 'object', 'properties': {}, 'additionalProperties': False}}}]

    def call(self, name, arguments):
        assert name == 'read' and arguments == {}
        return {'value': 1}


def runtime(provider, **limits):
    from fitness.agent_contracts import RunLimits
    from fitness.agent_runtime import AgentRuntime
    return AgentRuntime(provider, RunLimits(**limits), clock=lambda: 0)


def test_tool_then_invalid_candidate_is_repaired_and_usage_counted():
    from fitness.agent_contracts import ValidationIssue
    provider = ScriptProvider([ProviderReply(tool_calls=[{'id': 'call_1', 'name': 'read',
        'arguments': {}}], usage={'total_tokens': 3}), final({'sets': 99}), final({'sets': 4})])
    result = runtime(provider).run(role='training', task={}, tools=Tools(),
        validate=lambda candidate, sources: [] if candidate['sets'] == 4 else [
            ValidationIssue('sets', 'range', 'too many sets')])
    assert result.status == 'draft_ready'
    assert result.candidate == {'sets': 4}
    assert result.trace['calls'] == 3
    assert result.trace['usage'] == {'total_tokens': 17}
    assert provider.messages[1][-1]['tool_call_id'] == 'call_1'
    assert 'too many sets' in provider.messages[2][-1]['content']


def test_needs_input_does_not_invent_a_candidate():
    result = runtime(ScriptProvider([final(status='needs_input', questions=['今天可以训练多久？'])])).run(
        role='training', task={}, tools=Tools(), validate=lambda c, s: [])
    assert result.status == 'needs_input' and result.candidate is None
    assert result.questions == ['今天可以训练多久？']


def test_draft_ready_defaults_omitted_optional_questions():
    provider = ScriptProvider([ProviderReply(content=json.dumps({
        "status": "draft_ready", "candidate": {"sets": 4}}))])
    result = runtime(provider).run(role="training", task={}, tools=Tools(), validate=lambda c, s: [])
    assert result.status == "draft_ready" and result.questions == []


def test_needs_input_still_requires_nonempty_questions():
    provider = ScriptProvider([ProviderReply(content=json.dumps({
        "status": "needs_input", "candidate": None}))])
    result = runtime(provider, max_revisions=0).run(
        role="training", task={}, tools=Tools(), validate=lambda c, s: [])
    assert result.reason_code == "output_invalid" and result.candidate is None


def test_timeout_is_failed_without_baseline():
    result = runtime(ScriptProvider([ProviderError('timeout')])).run(
        role='training', task={}, tools=Tools(), validate=lambda c, s: [])
    assert result.status == 'failed' and result.reason_code == 'timeout'
    assert result.candidate is None and result.trace['calls'] == 1


def test_unknown_tool_is_not_executed():
    result = runtime(ScriptProvider([ProviderReply(tool_calls=[{
        'id': 'bad', 'name': 'write_sql', 'arguments': {}}])])).run(
        role='training', task={}, tools=Tools(), validate=lambda c, s: [])
    assert result.status == 'failed' and result.reason_code == 'tool_invalid'


def test_batched_tools_execute_sequentially_and_return_all_results():
    calls = [{"id": f"batch_{i}", "name": "read", "arguments": {}} for i in range(2)]
    provider = ScriptProvider([ProviderReply(tool_calls=calls), final({"sets": 4})])
    result = runtime(provider).run(role="training", task={}, tools=Tools(), validate=lambda c, s: [])
    assert result.status == "draft_ready"
    assert len(result.trace["tool_calls"]) == 2
    assert [m["tool_call_id"] for m in provider.messages[1] if m["role"] == "tool"] == ["batch_0", "batch_1"]


def test_batch_is_checked_before_any_tool_executes():
    class NoExecutionTools(Tools):
        def call(self, name, arguments):
            pytest.fail("invalid or over-budget batch must not execute")
    calls = [{"id": f"batch_{i}", "name": "read", "arguments": {}} for i in range(2)]
    result = runtime(ScriptProvider([ProviderReply(tool_calls=calls)]), max_tools=1).run(
        role="training", task={}, tools=NoExecutionTools(), validate=lambda c, s: [])
    assert result.reason_code == "tool_limit"
    calls[1]["name"] = "write_sql"
    result = runtime(ScriptProvider([ProviderReply(tool_calls=calls)])).run(
        role="training", task={}, tools=NoExecutionTools(), validate=lambda c, s: [])
    assert result.reason_code == "tool_invalid"


def test_revision_budget_is_bounded():
    from fitness.agent_contracts import ValidationIssue
    result = runtime(ScriptProvider([final({}), final({})]), max_revisions=1).run(
        role='training', task={}, tools=Tools(),
        validate=lambda c, s: [ValidationIssue('candidate', 'invalid', 'revise')])
    assert result.reason_code == 'output_invalid' and result.trace['calls'] == 2


def test_failed_run_records_stage_and_logs_only_validation_codes(caplog):
    from fitness.agent_contracts import ValidationIssue
    private_text = 'private-user-fact-never-log'
    with caplog.at_level('WARNING', logger='fitness.agent_runtime'):
        result = runtime(ScriptProvider([final({'summary': private_text})]), max_revisions=0).run(
            role='你是补剂规划 Agent', task={'private': private_text}, tools=Tools(),
            validate=lambda c, s: [ValidationIssue('summary', 'unsafe_content', private_text)])
    assert result.trace['stage'] == 'supplements'
    assert 'supplements' in caplog.text and result.run_id in caplog.text
    assert 'summary:unsafe_content' in caplog.text
    assert private_text not in caplog.text


def test_deadline_rejects_a_late_success():
    from fitness.agent_contracts import RunLimits
    from fitness.agent_runtime import AgentRuntime
    now = [0]
    class LateProvider:
        def complete(self, *args, **kwargs):
            now[0] = 181
            return final({'sets': 4})
    result = AgentRuntime(LateProvider(), RunLimits(), clock=lambda: now[0]).run(
        role='training', task={}, tools=Tools(), validate=lambda c, s: [])
    assert result.status == 'failed' and result.reason_code == 'run_timeout'
    assert result.trace['usage'] == {'total_tokens': 7}


def test_deadline_includes_final_validation():
    from fitness.agent_contracts import RunLimits
    from fitness.agent_runtime import AgentRuntime
    now = [0]
    def slow_validate(candidate, sources):
        now[0] = 181
        return []
    result = AgentRuntime(ScriptProvider([final({})]), RunLimits(), clock=lambda: now[0]).run(
        role='training', task={}, tools=Tools(), validate=slow_validate)
    assert result.reason_code == 'run_timeout' and result.candidate is None


def test_call_budget_stops_after_tool_without_another_provider_call():
    provider = ScriptProvider([ProviderReply(tool_calls=[{'id': 'one', 'name': 'read', 'arguments': {}}])])
    result = runtime(provider, max_calls=1).run(
        role='training', task={}, tools=Tools(), validate=lambda c, s: [])
    assert result.reason_code == 'call_limit' and len(provider.messages) == 1


def test_tool_budget_prevents_second_execution():
    class CountedTools(Tools):
        def __init__(self):
            super().__init__()
            self.executions = 0
        def call(self, name, arguments):
            self.executions += 1
            return super().call(name, arguments)
    tools = CountedTools()
    reply = ProviderReply(tool_calls=[{'id': 'one', 'name': 'read', 'arguments': {}}])
    result = runtime(ScriptProvider([reply, reply]), max_tools=1).run(
        role='training', task={}, tools=tools, validate=lambda c, s: [])
    assert result.reason_code == 'tool_limit' and tools.executions == 1


def test_oversized_tool_result_never_enters_another_prompt():
    class LargeTools(Tools):
        def call(self, name, arguments):
            return {'value': 'x' * 32001}
    provider = ScriptProvider([ProviderReply(tool_calls=[{'id': 'one', 'name': 'read', 'arguments': {}}])])
    result = runtime(provider).run(role='training', task={}, tools=LargeTools(), validate=lambda c, s: [])
    assert result.reason_code == 'tool_result_too_large' and len(provider.messages) == 1


@pytest.mark.parametrize('content', [
    '{"status":"draft_ready","status":"needs_input","candidate":{},"questions":[]}',
    '{"status":"draft_ready","candidate":{"sets":NaN},"questions":[]}',
    '{"status":"needs_input","candidate":null,"questions":[]}',
    'x' * 128001,
], ids=['duplicate_keys', 'nonfinite', 'empty_questions', 'oversized'])
def test_malformed_final_output_fails_without_candidate(content):
    result = runtime(ScriptProvider([ProviderReply(content=content)]), max_revisions=0).run(
        role='training', task={}, tools=Tools(), validate=lambda c, s: [])
    assert result.reason_code == 'output_invalid' and result.candidate is None
