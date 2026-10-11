"""Validated read tools and a preview-only adjustment tool for one fitness agent."""

from copy import deepcopy
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field

from .history import explain_similar_feedback, get_recent_feedback, summarize_recent_trend
from .models import Contract, FeedbackData, Profile
from .planning import context_persistence_status
from .storage import Conflict


class EmptyInput(Contract):
    pass


class HistoryInput(Contract):
    days: Literal[7, 14, 21] = 7
    issue: str | None = Field(default=None, max_length=200)
    metric: Literal['sleep_hours', 'weight_kg', 'fatigue', 'training_completed', 'diet_followed_plan'] | None = None


class TrendInput(Contract):
    days: Literal[7, 14, 21] = 7


class SimilarInput(Contract):
    limit: int = Field(default=3, ge=1, le=5)


class ToolResult(Contract):
    name: str
    status: Literal['ok', 'unavailable', 'capacity_exceeded', 'no_plan', 'not_applicable'] = 'ok'
    payload: dict


INPUTS = {
    'get_profile': EmptyInput, 'get_current_plan': EmptyInput,
    'retrieve_knowledge': EmptyInput, 'get_recent_feedback': HistoryInput,
    'summarize_recent_trend': TrendInput, 'find_similar_feedback': SimilarInput,
    'adjust_today_training': EmptyInput,
}


class LocalTools:
    def __init__(self, store, knowledge, current, *, today=None, plan_task=False):
        self.store, self.knowledge, self.current = store, knowledge, current
        self.today = today or datetime.now(ZoneInfo('Asia/Shanghai')).date()
        self.plan_task = plan_task
        self.profile_record = store.profile()
        if self.profile_record is None:
            raise Conflict('请先保存档案。')
        self.profile = Profile.model_validate(self.profile_record['data'])
        self.feedback = FeedbackData.model_validate(current['data'])
        self.history = store.feedback(limit=None)
        self.context = None
        self.trace = []

    def schemas(self):
        return [{'type': 'function', 'function': {
            'name': name, 'description': f'本地工具 {name}；只读或仅预览，不能提交写入。',
            'parameters': model.model_json_schema(),
        }} for name, model in self.inputs().items()]

    def inputs(self):
        if self.plan_task:
            return {**{key:INPUTS[key] for key in ('get_profile', 'get_current_plan',
                'get_recent_feedback', 'summarize_recent_trend')}, 'retrieve_baseline_strategies':EmptyInput}
        return INPUTS

    def current_plan(self):
        day = self.feedback.date
        return next((p for p in self.store.plans()
                     if p['status'] == 'confirmed' and p['profile_version'] == self.profile_record['version']
                     and 0 <= (day - date.fromisoformat(p['start_date'])).days < 7), None)

    def call(self, name, arguments):
        if name not in self.inputs():
            self.trace.append({'name':str(name)[:64], 'input':{}, 'status':'invalid',
                               'sequence':len(self.trace) + 1})
            raise ValueError('tool_invalid')
        try:
            params = self.inputs()[name].model_validate(arguments).model_dump()
        except ValueError:
            self.trace.append({'name':name, 'input':{}, 'status':'invalid', 'sequence':len(self.trace) + 1})
            raise
        status = 'ok'
        if name == 'get_profile':
            payload = {'version': self.profile_record['version'], 'data': self.profile.model_dump(mode='json')}
        elif name == 'get_current_plan':
            payload = {'plan': self.current_plan()}
            if not payload['plan']:
                status = 'no_plan'
        elif name == 'retrieve_baseline_strategies':
            self.context = self.knowledge.for_plan(self.profile)
            status = context_persistence_status(self.context)
            payload = {'strategies':[s.model_dump(mode='json') for s in self.context.strategies]
                       if status == 'ok' else []}
        elif name == 'retrieve_knowledge':
            self.context = self.knowledge.for_feedback(self.profile, self.feedback,
                                                       self.current['raw_text'], self.history)
            status = context_persistence_status(self.context)
            payload = {'issues': [{'id': i.id, 'label': i.label,
                                  'knowledge_ids': list(i.knowledge_item_ids)} for i in self.context.issues],
                       'citations': [c.model_dump(mode='json') for c in self.context.citations]
                       if status == 'ok' else []}
        elif name == 'get_recent_feedback':
            payload = get_recent_feedback(self.history, end_date=self.feedback.date, **params)
            payload['records'] = [{'id': r['id'], 'date': r['date'], 'data': r['data']} for r in payload['records']]
        elif name == 'summarize_recent_trend':
            payload = summarize_recent_trend(self.history, end_date=self.feedback.date, **params)
        elif name == 'find_similar_feedback':
            payload = explain_similar_feedback(self.history, self.current, **params)
        else:
            payload = self.training_preview()
            status = 'ok' if payload.get('changes') else 'not_applicable'
        output = ToolResult(name=name, status=status, payload=payload)
        self.trace.append({'name': name, 'input': params, 'status': status,
                           'output_keys': list(payload), 'sequence': len(self.trace) + 1})
        return output

    def training_preview(self):
        from .safety import has_urgent_symptoms
        plan = self.current_plan()
        if (not plan or self.feedback.date != self.today or not self.feedback.fatigue
                or self.feedback.training_completed is True
                or has_urgent_symptoms(self.current['raw_text'] + self.feedback.model_dump_json()
                                      + self.profile.model_dump_json())):
            return {'changes': [], 'reason': '只为当日疲劳且尚未完成的训练提供局部预览。'}
        index = (self.feedback.date - date.fromisoformat(plan['start_date'])).days
        day = deepcopy(plan['data']['days'][index])
        prior = self.store.plan_changes(plan['id'])
        for record in prior:
            for change in record['changes']:
                parts = change['path'].split('.')
                if int(parts[1]) == index:
                    day['exercises'][int(parts[3])]['sets'] = change['new_value']
        changes = [{'path': f'days.{index}.exercises.{i}.sets', 'old_value': e['sets'],
                    'new_value': e['sets'] - 1} for i, e in enumerate(day['exercises']) if e['sets'] > 1]
        return {'plan_id': plan['id'], 'feedback_id': self.current['id'],
                'day_date': self.feedback.date.isoformat(), 'changes': changes,
                'expected_profile_version': self.profile_record['version'],
                'expected_feedback_revision': self.current['revision'],
                'expected_feedback_updated_at': self.current['updated_at'],
                'expected_plan_change_count': len(prior), 'trigger_issues': ['training_fatigue'],
                'evidence': {'fatigue': self.feedback.fatigue},
                'reason': '当日疲劳时少做一组，保留动作、次数和基础周计划；确认后才记录。'}
