"""Synthetic training harness evaluation; network access requires explicit --live."""

import argparse
import json
from copy import deepcopy
from datetime import date
from pathlib import Path

from .config import ROOT, Settings
from .models import Profile
from .provider import OpenAICompatibleProvider, ProviderReply
from .training_agent import TrainingPlannerAgent
from .training_contracts import TrainingTask
from .training_state import resolve_training_state
from .training_validation import validate_training_candidate

CASES = ROOT / 'data/evaluation/training-agent-cases.json'


def synthetic_step():
    return {'label': '拉', 'kind': 'training', 'estimated_minutes': 15, 'exercises': [
        {'exercise_id': 'dumbbell_row', 'name': '哑铃划船', 'sets': 4,
         'reps_min': 8, 'reps_max': 12, 'rest_seconds': 90}]}


class ScriptedProvider:
    """Fixed responses exercise the harness, never measure model quality."""

    def __init__(self, case):
        self.case, self.calls = case, 0

    def complete(self, messages, tools=None, **kwargs):
        self.calls += 1
        if self.case['id'] == 'knowledge_unavailable' and self.calls == 1:
            return ProviderReply(tool_calls=[{'id': 'lookup', 'name': 'search_training_knowledge',
                'arguments': {'query': '训练恢复', 'limit': 3}}])
        if self.case.get('must_not_train'):
            result = {'status': 'needs_input', 'candidate': None, 'questions': ['是否已评估肩部活动限制？']}
        else:
            candidate = {'summary': '合成受控候选，用于验证工程管线',
                'assumptions': ['时长仅为估算'], 'source_ids': [], 'questions': []}
            if self.case['kind'] == 'cycle':
                candidate['cycle'] = [synthetic_step(),
                    {'label': '恢复', 'kind': 'rest', 'exercises': [], 'estimated_minutes': 0}]
            else:
                candidate.update(action='train', training=synthetic_step(), reasons=['合成样例'])
            result = {'status': 'draft_ready', 'candidate': candidate, 'questions': []}
        # Scripted usage is deliberately absent: it is not billable model usage.
        return ProviderReply(content=json.dumps(result, ensure_ascii=False))


def evaluate(*, live=False, settings=None):
    dataset = json.loads(CASES.read_text(encoding='utf-8'))
    settings = settings or (Settings.from_env() if live else Settings(live_enabled=True))
    rows = []
    day = date(2026, 10, 20)
    for case in dataset['cases']:
        data = deepcopy(dataset['profile'])
        if 'equipment' in case:
            data['training']['available_equipment'] = case['equipment']
        profile = Profile.model_validate(data)
        state = resolve_training_state(profile=profile, day=day, history=[], restrictions=[],
            conditions=case['conditions'], conditions_recorded_at=None)
        task = TrainingTask(kind=case['kind'], date=day, profile=profile, profile_version=1,
            conditions=case['conditions'], state=state, cycle=[synthetic_step()],
            time_limit_minutes=case.get('time_limit_minutes'),
            completed_training=synthetic_step() if case.get('completed') else None)
        provider = OpenAICompatibleProvider(settings) if live else ScriptedProvider(case)
        agent = TrainingPlannerAgent(settings, provider)
        result = agent.plan_cycle_live(task) if task.kind == 'cycle' else agent.plan_day_live(task)
        sources = {source['id']: source for source in result.trace.get('source_snapshots', [])}
        issues = validate_training_candidate(result.candidate, task, sources) if result.candidate else []
        constraints_ok = not issues and (not case.get('must_not_train') or
            not result.candidate or result.candidate.get('action') != 'train')
        rows.append({'id': case['id'], 'status': result.status, 'reason': result.reason_code,
            'engineering_pass': result.status in case['expected'] and constraints_ok,
            'constraints_satisfied': constraints_ok if result.candidate else None,
            'constraint_errors': [issue.code for issue in issues],
            'source_support': 'validated' if sources else 'no_sources_claimed' if
                not result.candidate or not result.candidate.get('source_ids') else 'unsupported',
            'calls': result.trace.get('calls', 0), 'tools': len(result.trace.get('tool_calls', [])),
            'revisions': result.trace.get('revisions', 0), 'usage': result.trace.get('usage', {}),
            'elapsed_ms': result.trace.get('elapsed_ms', 0), 'candidate': result.candidate,
            'questions': result.questions,
            'human_review': {'status': 'pending', 'question': case['review']}})
    return {'mode': 'live' if live else 'scripted', 'synthetic_profiles_only': True,
        'model_quality': 'requires_independent_review' if live else 'not_evaluated',
        'cases': rows}


def markdown(report):
    lines = ['# Training agent evaluation', '', f"Mode: {report['mode']}", '',
        '真实模型输出须独立人工评审。' if report['mode'] == 'live' else
        '未执行真实模型质量评估；受控响应仅验证工程管线。', '',
        '| Case | Status | Constraints | Calls / tools / repairs | Usage | ms | Reason |',
        '| --- | --- | --- | --- | --- | --- | --- |']
    for row in report['cases']:
        lines.append(f"| {row['id']} | {row['status']} | {row['constraints_satisfied']} | "
            f"{row['calls']} / {row['tools']} / {row['revisions']} | {row['usage']} | "
            f"{row['elapsed_ms']} | {row['reason'] or ''} |")
    lines += ['', '## Pending independent review', '']
    lines += [f"- {row['id']}: {row['human_review']['question']}" for row in report['cases']]
    lines += ['', '工程约束通过不证明处方适用、真实用时或模型质量；计时动作和单侧动作仍需人工核验。', '']
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'data/evaluation/reports/training-agent')
    args = parser.parse_args(argv)
    report = evaluate(live=args.live)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (args.output_dir / 'report.md').write_text(markdown(report), encoding='utf-8')
    return 0 if all(row['engineering_pass'] for row in report['cases']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
