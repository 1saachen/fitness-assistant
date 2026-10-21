"""Persistent training facts and restriction events, independent from prescriptions."""

import re
from copy import deepcopy
from datetime import UTC, datetime

from .feedback_facts import merge_feedback_days
from .safety import has_urgent_symptoms

AREA_TERMS = {
    'shoulder': ('肩', 'shoulder'), 'knee': ('膝', 'knee'),
    'back': ('腰', '背', 'back'), 'wrist': ('腕', 'wrist'),
    'elbow': ('肘', 'elbow'), 'hip': ('髋', 'hip'),
}
INJURY = re.compile(r'受伤|损伤|疼|痛|扭伤|拉伤|不适|injur|pain|hurt', re.IGNORECASE)
SKIP = re.compile(r'跳过|不用补|不补这次|skip', re.IGNORECASE)
DEFER = re.compile(r'很累|太累|疲劳|没时间|没有时间|不想练|不练了|休息一天|改.*明天|明天再练|tired|exhausted|no time|postpone', re.IGNORECASE)
FATIGUE_CUE = re.compile(r'很累|太累|疲劳|tired|exhausted', re.IGNORECASE)
FATIGUE_CLEAR = re.compile(r'不累|不疲劳|没有疲劳|已经恢复|恢复好了|状态恢复|精神恢复|recovered|not tired|feeling better', re.IGNORECASE)
NO_TIME = re.compile(r'没时间|没有时间|no\s+time', re.IGNORECASE)
RECOVERED = re.compile(r'已经好了|恢复好了|已经恢复|康复了|痊愈|recovered', re.IGNORECASE)


def _rest(label='恢复 / 待评估'):
    return {'label': label, 'kind': 'rest', 'exercises': [], 'estimated_minutes': 0}


def _equipment(profile):
    # Unknown access never means all equipment is available.
    return set(profile.training.available_equipment or []) | {'bodyweight'}


def _text(row):
    data = row.get('data') or {}
    return ' '.join(str(value) for value in [row.get('raw_text', ''),
        data.get('training_summary', ''), data.get('fatigue', '')] if value)


def _positive_text(text):
    # Remove explicitly negated symptom phrases without removing inability to train.
    text = re.sub(r'但是|不过|可是|然而|\bbut\b', '，', text, flags=re.IGNORECASE)
    return re.sub(r'(?:没有|没|无|不再|no\s+|without\s+)[^，,。；;!！?？]{0,12}?'
                  r'(?:疼痛|疼|痛|受伤|疲劳|很累|injury|pain|fatigue|tired)', '', text, flags=re.IGNORECASE)


def _injury_restrictions(text, source_date):
    text = _positive_text(text)
    # Urgent symptoms have their own persistent restriction and release history.
    if has_urgent_symptoms(text):
        text = re.sub(r'胸痛|胸闷|晕厥|呼吸困难|剧痛|chest pain|fainting|shortness of breath|severe pain',
                      '', text, flags=re.IGNORECASE)
    if not INJURY.search(text):
        return []
    areas = [area for area, terms in AREA_TERMS.items() if any(term in text.lower() for term in terms)]
    return [{'area': area, 'reason': text[:500], 'source_date': source_date, 'active': True}
            for area in areas or ['unspecified']]


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
    except (TypeError, ValueError):
        return None


def _released(restrictions, area, text, source_date, source_kind, recorded_at=None):
    for restriction in restrictions:
        if restriction.get('area') != area or restriction.get('active', True):
            continue
        recorded = _timestamp(recorded_at)
        resolved = _timestamp(restriction.get('resolved_at'))
        if recorded is None or resolved is None or recorded > resolved:
            continue
        if source_kind == 'conditions' and any(
                item.get('date') == source_date and item.get('text') == text
                for item in restriction.get('released_conditions', [])):
            return True
        if source_kind == 'feedback':
            return True
    return False


def _current_fatigue_deferral(texts):
    pending_fatigue = False
    pending_other = False
    recovered = False
    for text in texts:
        clear = FATIGUE_CLEAR.search(text)
        fatigue = FATIGUE_CUE.search(text)
        deferred = DEFER.search(_positive_text(text))
        if clear and (not fatigue or clear.start() > fatigue.start()):
            pending_fatigue = False
            recovered = True
        if deferred:
            if NO_TIME.search(text):
                pending_other = True
            elif fatigue:
                # A later explicit recovery in this same report corrects its earlier fatigue.
                if not clear or clear.start() <= deferred.start():
                    pending_fatigue = True
            else:
                pending_other = True
    return pending_fatigue or pending_other, recovered


def resolve_training_state(*, profile, day, history, restrictions, conditions, conditions_recorded_at):
    resolved_restrictions = deepcopy(restrictions)
    health = profile.health
    health_text = health.exercise_limiting_conditions_details or ''
    urgent = False
    sources = [(health_text, day.isoformat(), 'profile', None)]
    current_events = []
    recent = {}
    for row in merge_feedback_days(history).values():
        if row.get('status') not in {None, 'confirmed'}:
            continue
        row_date = str(row.get('date') or (row.get('data') or {}).get('date') or '')
        if not row_date or row_date > day.isoformat():
            continue
        recent[row_date] = row.get('data') or {}
    # Scan every confirmed symptom report independently. Daily fact merging must
    # not let a later food-only report erase an earlier raw injury report.
    for row in history:
        if row.get('status') not in {None, 'confirmed'}:
            continue
        row_date = str(row.get('date') or (row.get('data') or {}).get('date') or '')
        if not row_date or row_date > day.isoformat():
            continue
        source_kind = 'conditions' if row.get('source_kind') == 'conditions' else 'feedback'
        if row.get('raw_text'):
            sources.append((str(row['raw_text']), row_date, source_kind, row.get('created_at')))
            if row_date == day.isoformat() and row.get('include_in_current', True):
                current_events.append((row.get('created_at'), str(row['raw_text'])))
        data = row.get('data') or {}
        for field in ('training_summary', 'fatigue'):
            fact = data.get(field)
            if fact:
                fact_time = (row.get('field_updated_at', {}).get(field)
                             or row.get('fact_updated_at') or row.get('created_at'))
                sources.append((str(fact), row_date, 'feedback',
                    fact_time))
                if row_date == day.isoformat():
                    current_events.append((fact_time, str(fact)))
    sources.append((conditions, day.isoformat(), 'conditions', conditions_recorded_at))
    if conditions:
        current_events.append((conditions_recorded_at, conditions))
    for text, source_date, source_kind, recorded_at in sources:
        if (has_urgent_symptoms(_positive_text(text))
                and not _released(restrictions, 'urgent_symptoms', text,
                                  source_date, source_kind, recorded_at)):
            urgent = True
        for restriction in _injury_restrictions(text, source_date):
            if _released(restrictions, restriction['area'], text, source_date, source_kind, recorded_at):
                continue
            if not any(r.get('area') == restriction['area'] and r.get('active', True)
                       for r in resolved_restrictions):
                resolved_restrictions.append(restriction)
    active = [r for r in resolved_restrictions if r.get('active', True)]
    urgent = urgent or any(r.get('area') == 'urgent_symptoms' for r in active)
    current_events.sort(key=lambda item: _timestamp(item[0]) or datetime.max.replace(tzinfo=UTC))
    current_text = [text for _, text in current_events]
    current = _positive_text(' '.join(current_text))
    current_fatigue_defer, fatigue_recovered = _current_fatigue_deferral(current_text)
    if urgent and not any(r.get('area') == 'urgent_symptoms' for r in active):
        resolved_restrictions.append({'area': 'urgent_symptoms', 'active': True,
            'reason': '报告异常症状，恢复训练前需专业评估', 'source_date': day.isoformat()})
    return {'confirmed_facts': recent, 'restrictions': resolved_restrictions,
        'active_restrictions': [r for r in resolved_restrictions if r.get('active', True)],
        'release_events': [r for r in restrictions if not r.get('active', True)],
        'urgent_stop': urgent, 'current_intent': current,
        'current_fatigue_defer': current_fatigue_defer, 'fatigue_recovered': fatigue_recovered,
        'recovery_signals': recent}
