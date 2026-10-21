"""Check proposals without replacing them with a rule prescription."""

import math

from pydantic import ValidationError

from .agent_contracts import ValidationIssue
from .training_contracts import CycleCandidate, DayCandidate, TrainingStep
from .training_state import SKIP


def exercise_catalog():
    # Import lazily to avoid a role / validator import cycle.
    from .training_agent import EXERCISES
    return EXERCISES


def estimated_step_minutes(step):
    # Planning estimate: 4 s per repetition, prescribed rests, 3 min warm-up.
    # This is explicitly an estimate, not measured execution time.
    seconds = 180 + sum(e['sets'] * e['reps_max'] * 4 +
                        max(0, e['sets'] - 1) * e['rest_seconds']
                        for e in step['exercises'])
    return math.ceil(seconds / 60) if step['exercises'] else 0


def validate_training_candidate(candidate, task, retrieved_sources):
    model = CycleCandidate if task.kind == 'cycle' else DayCandidate
    try:
        parsed = model.model_validate(candidate).model_dump(mode='json')
    except ValidationError as exc:
        return [ValidationIssue('.'.join(map(str, e['loc'])), 'schema', e['msg']) for e in exc.errors()]
    issues = []
    catalog = exercise_catalog()
    equipment = set(task.profile.training.available_equipment or []) | {'bodyweight'}
    limits = [n for n in (task.time_limit_minutes, task.profile.training.session_duration_minutes) if n is not None]
    limit = min(limits) if limits else 30
    steps = parsed['cycle'] if task.kind == 'cycle' else [parsed['training']]
    if task.kind == 'day' and SKIP.search(task.state.get('current_intent', task.conditions)) and parsed['action'] != 'skip':
        issues.append(ValidationIssue('action', 'explicit_skip', '用户明确跳过本次训练，不能改成待执行训练。'))
    if task.kind == 'day' and parsed['action'] == 'skip' and not SKIP.search(task.state.get('current_intent', task.conditions)):
        issues.append(ValidationIssue('action', 'skip_unconfirmed', '没有明确跳过本次的指令，不得自行推进进度。'))
    for index, step in enumerate(steps):
        prefix = f'cycle.{index}' if task.kind == 'cycle' else 'training'
        if step['kind'] == 'training':
            if max(step['estimated_minutes'], estimated_step_minutes(step)) > limit:
                issues.append(ValidationIssue(prefix + '.estimated_minutes', 'time_limit',
                    f'按每次重复4秒、组间休息和3分钟热身估算，超过{limit}分钟限制。'))
            health = task.profile.health
            if (task.state.get('active_restrictions') or health.exercise_limiting_conditions_status == 'has_conditions'
                    or health.exercise_limiting_conditions_details):
                issues.append(ValidationIssue(prefix, 'restriction', '活动限制尚未核实，不能证明本次训练适用；请澄清或暂停受影响训练。'))
        for n, exercise in enumerate(step['exercises']):
            item = catalog.get(exercise['exercise_id'])
            if item is None and not exercise['name']:
                issues.append(ValidationIssue(f'{prefix}.exercises.{n}.name', 'exercise_name', '新动作需提供清楚的名称。'))
            if item is None and not exercise.get('equipment'):
                issues.append(ValidationIssue(f'{prefix}.exercises.{n}.equipment', 'equipment_unknown',
                    '新动作请声明所需器械；徒手填写["bodyweight"]，不需要查询动作库。'))
            required_equipment = set(exercise.get('equipment') or [])
            if item:
                required_equipment.add(item['equipment'])
            if required_equipment - equipment:
                issues.append(ValidationIssue(f'{prefix}.exercises.{n}.exercise_id', 'equipment', '该动作所需器械未确认可用。'))
    for source in parsed['source_ids']:
        if source not in retrieved_sources:
            issues.append(ValidationIssue('source_ids', 'unknown_source', '只能引用本次实际返回的知识ID。'))
    if task.completed_training and task.kind == 'day':
        completed = TrainingStep.model_validate(task.completed_training).model_dump(mode='json')
        if parsed['training'] != completed:
            issues.append(ValidationIssue('training', 'completed_immutable', '已完成训练不能修改。'))
    return issues
