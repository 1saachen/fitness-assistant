"""Save user planning answers through the shared, evidenced memory pipeline."""

from datetime import datetime
from zoneinfo import ZoneInfo

from .feedback_memory import FeedbackMemory
from .plan_store import fingerprint
from .plan_streaming import emit_plan_event
from .storage import Conflict


def remember_conditions(service, snapshot, day, text, kind, answered_questions=None):
    # Import here because the coach also uses DailyPlanningService for explicit plan actions.
    from .feedback_coach import FeedbackCoach

    today = datetime.now(ZoneInfo(service.settings.timezone)).date()
    source_day = min(day, today)
    context = {'kind': kind, 'target_date': str(day), 'answered_questions': answered_questions or []}
    key = 'conditions:' + fingerprint([kind, str(source_day), text, context])
    memory = FeedbackMemory(service.store)
    row = memory.record(text, source_day, request_key=key, source_context=context)
    emit_plan_event('status', {'message': '补充原文已保存，正在判断哪些信息需要记住…'})
    coach = FeedbackCoach(service.store, service.settings, provider=service.training.provider,
                          today=lambda: today)
    retry_memory = row['coaching']['status'] == 'ready' and row['coaching']['memory_status'] == 'failed'
    result = coach.analyze(row['id'], force=retry_memory)
    coaching = result['coaching']
    if coaching.get('error') == 'input_changed':
        raise Conflict('补充原文已保存，但资料在理解期间有变化，请刷新后重试。')
    refreshed = service.repo.snapshot(day)
    def other_inputs(value):
        return [value['profile'], value['long_term'], value['days'],
                [r for r in value['feedback'] if r['id'] != row['id']]]
    if fingerprint(other_inputs(snapshot)) != fingerprint(other_inputs(refreshed)):
        raise Conflict('补充原文已保存，但档案、反馈或计划已有变化，请刷新后重试。')
    status = coaching.get('memory_status') if coaching['status'] == 'ready' else 'failed'
    messages = {'failed': '补充原文已保存，但个人记忆未更新；可在原文记录中重试理解。',
                'unchanged': '补充原文已保存，模型判断本次无需新增或修改个人记忆。'}
    notice = {'feedback_id': row['id'], 'status': status,
              'message': messages.get(status, '补充原文已保存，个人记忆已整理；长期信息会持续用于后续计划。')}
    emit_plan_event('memory', notice)
    return refreshed, notice
