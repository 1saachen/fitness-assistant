"""Validate and apply model-proposed updates to explicit profile fields."""

import re
import unicodedata

from pydantic import ValidationError

from .agent_contracts import ValidationIssue
from .memory_lifecycle import ENDURING, TEMPORAL
from .models import Profile
from .storage import decode, encode, now

PROFILE_FIELD_LABELS = {
    'nutrition.primary_meal_source': '主要饮食来源',
    'nutrition.food_budget.amount': '饮食预算',
    'nutrition.food_budget.period': '饮食预算',
    'nutrition.food_allergy_status': '食物过敏情况',
    'nutrition.food_allergy_details': '食物过敏说明',
    'nutrition.food_intolerances': '食物不耐受',
    'nutrition.other_dietary_restrictions': '饮食限制',
    'nutrition.food_preferences': '长期饮食偏好',
    'nutrition.disliked_foods': '长期不喜欢的食物',
    'health.exercise_limiting_conditions_status': '影响运动的问题',
    'health.exercise_limiting_conditions_details': '健康问题说明',
    'health.medications_status': '用药状态',
    'health.medications': '用药情况',
    'training.usual_training_time': '通常训练时间',
}

_NEGATIVE = re.compile(r'无|没有|没(?:有|在|服用|吃)|未(?:发现|服用|使用)|不(?:是|有|会|服用|吃药|用药)|否|不过敏')
_UNCERTAIN = re.compile(r'不确定|不知道|不清楚|说不准|忘了')
_DURABLE_HEALTH_FIELDS = (
    'nutrition.food_allergy_', 'nutrition.food_intolerances', 'nutrition.other_dietary_restrictions',
    'health.exercise_limiting_conditions_', 'health.medications',
)


def _normalized(value):
    return unicodedata.normalize('NFKC', str(value)).casefold()


def _set_path(data, path, value):
    parts = path.split('.')
    current = data
    for part in parts[:-1]:
        current = current[part]
    current[parts[-1]] = value


def _get_path(data, path):
    current = data
    for part in path.split('.'):
        current = current[part]
    return current


def _group(path):
    if path.startswith('nutrition.food_budget.'):
        return 'nutrition.food_budget'
    if path.startswith('nutrition.food_allergy_'):
        return 'nutrition.food_allergy'
    if path.startswith('health.exercise_limiting_conditions_'):
        return 'health.exercise_limiting_conditions'
    if path.startswith('health.medications'):
        return 'health.medications'
    return path


def _supported_by_quote(path, value, quote):
    text = _normalized(quote)
    if value is None:
        return bool(_NEGATIVE.search(text))
    if path in {'nutrition.food_budget.amount'}:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        return any(float(token) == float(value) for token in re.findall(r'\d+(?:\.\d+)?', text))
    if path == 'nutrition.food_budget.period':
        markers = {'day': r'天|日', 'week': r'周|星期', 'month': r'月'}
        return isinstance(value, str) and value in markers and bool(re.search(markers[value], text))
    if path in {'nutrition.food_allergy_status', 'health.exercise_limiting_conditions_status',
                'health.medications_status'}:
        uncertain = bool(_UNCERTAIN.search(text))
        negative = bool(_NEGATIVE.search(text)) and not uncertain
        if value == 'unknown':
            return uncertain
        if value == 'none_known_self_reported':
            anchors = {
                'nutrition.food_allergy_status': r'过敏',
                'health.exercise_limiting_conditions_status': r'疾病|问题|运动限制|损伤|受伤|疼|痛',
                'health.medications_status': r'药|服用|服药|用药',
            }
            return negative and bool(re.search(anchors[path], text))
        if value == 'has_allergies':
            return '过敏' in text and not negative and not uncertain
        if value == 'has_conditions':
            return any(word in text for word in ('疾病', '受伤', '疼', '痛', '哮喘', '高血压', '糖尿病')) \
                and not negative and not uncertain
        if value == 'taking':
            return any(word in text for word in ('服用', '用药', '服药', '吃药')) and not negative and not uncertain
        return False
    if not isinstance(value, str):
        return False
    return _normalized(value) in text


def _has_temporary_scope(raw_text, quote):
    clauses = [clause for clause in re.split(r'[。！？；;\n，,]', raw_text) if quote in clause]
    return bool(clauses) and all(TEMPORAL.search(clause) and not ENDURING.search(clause) for clause in clauses)


def validate_profile_updates(parsed, row, profile_record):
    issues = []
    updates = parsed.profile_updates
    if not updates:
        return issues
    source_context = row.get('trace', {}).get('source_context') or {}
    enduring_question = any(ENDURING.search(question) and not TEMPORAL.search(question)
                            for question in source_context.get('answered_questions', []))
    if source_context.get('kind') not in {'long_term_conditions', 'daily_conditions'}:
        issues.append(ValidationIssue('profile_updates', 'profile_update_scope',
                                      '只有回答长期习惯类问题时才可以更新个人档案。'))
    paths = [item.path for item in updates]
    if len(set(paths)) != len(paths):
        issues.append(ValidationIssue('profile_updates.path', 'profile_update_path',
                                      '同一档案字段只能更新一次。'))
    raw_text = row['raw_text']
    for item in updates:
        clauses = [clause for clause in re.split(r'[。！？；;\n，,]', raw_text) if item.quote in clause]
        durable_answer = enduring_question or any(ENDURING.search(clause) for clause in clauses)
        if (source_context.get('kind') == 'daily_conditions' and not durable_answer
                and not item.path.startswith(_DURABLE_HEALTH_FIELDS)):
            issues.append(ValidationIssue('profile_updates.scope', 'profile_update_scope',
                                          '当天补充只有明确回答长期问题或健康与饮食限制时才更新档案。'))
        if _has_temporary_scope(raw_text, item.quote):
            issues.append(ValidationIssue('profile_updates.value', 'profile_update_scope',
                                          '本次或当天的回答不能改为长期档案字段。'))
        if item.value != 'unknown' and clauses and all(_UNCERTAIN.search(clause) for clause in clauses):
            issues.append(ValidationIssue('profile_updates.value', 'profile_update_evidence',
                                          '不确定的回答不能写成确定的档案事实。'))
        if item.quote not in raw_text:
            issues.append(ValidationIssue('profile_updates.evidence', 'profile_update_evidence',
                                          '档案更新必须引用本次用户原话中的逐字内容。'))
        elif not _supported_by_quote(item.path, item.value, item.quote):
            issues.append(ValidationIssue('profile_updates.value', 'profile_update_evidence',
                                          '档案字段值必须能由对应原话直接支持。'))
    try:
        data = Profile.model_validate(profile_record['data'] if profile_record else {}).model_dump(mode='json')
        for item in updates:
            _set_path(data, item.path, item.value)
        Profile.model_validate(data)
    except (KeyError, TypeError, ValidationError, ValueError) as exc:
        issues.append(ValidationIssue('profile_updates.value', 'profile_update_schema',
                                      f'档案更新不符合字段格式：{exc}'))
    return issues


def apply_profile_updates(db, profile_record, updates):
    if not updates:
        return profile_record, [], []
    if profile_record is None:
        raise ValueError('没有可更新的个人档案。')
    data = Profile.model_validate(profile_record['data']).model_dump(mode='json')
    blocked = {_group(item['path']) for item in updates
               if _get_path(data, item['path']) not in (None, '', 'unknown', item['value'])}
    related = {
        'nutrition.food_allergy_status': 'nutrition.food_allergy_details',
        'health.exercise_limiting_conditions_status': 'health.exercise_limiting_conditions_details',
        'health.medications_status': 'health.medications',
    }
    blocked.update(_group(item['path']) for item in updates
                   if item['value'] == 'none_known_self_reported' and item['path'] in related
                   and _get_path(data, related[item['path']]))
    updated, conflicts = [], []
    for item in updates:
        current = _get_path(data, item['path'])
        if current == item['value']:
            continue
        if _group(item['path']) in blocked:
            conflicts.append(item['path'])
            continue
        _set_path(data, item['path'], item['value'])
        if item['path'] not in updated:
            updated.append(item['path'])
    if not updated:
        return profile_record, [], list(dict.fromkeys(PROFILE_FIELD_LABELS[path] for path in conflicts))
    validated = Profile.model_validate(data).model_dump(mode='json')
    version = profile_record['version'] + 1
    db.execute('INSERT INTO profiles VALUES (?,?,?)', (version, encode(validated), now()))
    saved = decode(db.execute('SELECT * FROM profiles WHERE version=?', (version,)).fetchone())
    return (saved, list(dict.fromkeys(PROFILE_FIELD_LABELS[path] for path in updated)),
            list(dict.fromkeys(PROFILE_FIELD_LABELS[path] for path in conflicts)))
