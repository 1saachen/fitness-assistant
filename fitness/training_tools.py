"""Snapshot-only training queries and candidate previews."""

from dataclasses import asdict
from typing import Literal

from pydantic import Field

from .history import get_recent_feedback, summarize_exercise_history, summarize_recent_trend
from .knowledge import search_knowledge
from .models import Contract
from .provider import _json_loads
from .training_validation import exercise_catalog, validate_training_candidate


class Empty(Contract):
    pass


class Window(Contract):
    days: Literal[7, 14, 21] = 7


class TrainingHistoryQuery(Window):
    exercise_id: str | None = Field(default=None, min_length=1, max_length=200)
    session_limit: int = Field(default=3, ge=1, le=8, strict=True)


class Search(Contract):
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=3, ge=1, le=5, strict=True)


class Exercises(Contract):
    equipment: list[str] = Field(default_factory=list, max_length=4)
    query: str = Field(default='', max_length=200)


class Preview(Contract):
    candidate_json: str = Field(min_length=2, max_length=16000)


INPUTS = {'get_training_profile': Empty, 'get_training_history': TrainingHistoryQuery,
          'get_training_trend': Window, 'search_training_knowledge': Search,
          'list_training_exercises': Exercises, 'preview_training_candidate': Preview}

DESCRIPTIONS = {
    'get_training_profile': '读取本次档案快照；已有完整profile时无需重复查询。',
    'get_training_history': '读取7/14/21天实际训练；可用exercise_id查询同动作最近场次、逐组次数、重量和RPE。',
    'get_training_trend': '查看已确认反馈趋势；无历史时无需反复查询。',
    'search_training_knowledge': '按需补充本地知识引用；可用专业知识直接规划，不强制检索。',
    'list_training_exercises': '可选的旧动作目录参考，不是允许动作名单；可直接提出目录外动作并省略ID。',
    'preview_training_candidate': '可选预检；最终提交会自动校验。通过一次后直接提交，勿重复预检。',
}


class TrainingTools:
    def __init__(self, task, knowledge):
        self.task, self.knowledge = task, knowledge
        self.retrieved_sources = {}

    def schemas(self):
        return [{'type': 'function', 'function': {'name': name,
            'description': DESCRIPTIONS[name],
            'parameters': model.model_json_schema()}} for name, model in INPUTS.items()]

    def call(self, name, arguments):
        if name not in INPUTS:
            raise ValueError('tool_invalid')
        params = INPUTS[name].model_validate(arguments).model_dump()
        if name == 'get_training_profile':
            return {'version': self.task.profile_version, 'profile': self.task.profile.model_dump(mode='json')}
        if name in {'get_training_history', 'get_training_trend'}:
            rows = [{**r, 'status': r.get('status', 'confirmed')} for r in self.task.history
                    if r.get('source_kind') != 'conditions']
            if name == 'get_training_trend':
                return summarize_recent_trend(rows, end_date=self.task.date, **params)
            data = get_recent_feedback(rows, end_date=self.task.date, days=params['days'])
            data['exercise_history'] = summarize_exercise_history(data['records'],
                exercise_id=params['exercise_id'], limit=params['session_limit'])
            data['records'] = [{k: r.get(k) for k in ('id', 'date', 'data', 'raw_text')}
                               for r in data['records'][:30]]
            return data
        if name == 'list_training_exercises':
            rows = [{'exercise_id': k, **{field: value for field, value in v.items() if field != 'loads'}}
                    for k, v in exercise_catalog().items()
                    if (not params['equipment'] or v['equipment'] in params['equipment'])
                    and (not params['query'] or params['query'] in k or params['query'] in v['name'])]
            return {'exercises': rows, 'time_method': '每次重复4秒 + 组间休息 + 3分钟热身，均为估算'}
        if name == 'preview_training_candidate':
            return {'issues': [asdict(i) for i in validate_training_candidate(
                _json_loads(params['candidate_json']), self.task, self.retrieved_sources)]}
        if self.knowledge is None:
            return {'status': 'unavailable', 'citations': []}
        try:
            root = self.knowledge.knowledge_root
            rows = search_knowledge(root, **params)
        except (OSError, ValueError):
            return {'status': 'unavailable', 'citations': []}
        rows = [r for r in rows if r['metadata']['review_status'] == 'approved']
        for row in rows:
            self.retrieved_sources[row['id']] = row
        return {'status': 'ok', 'citations': rows}
