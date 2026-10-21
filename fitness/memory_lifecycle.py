"""Evidence and dates for personal memory, independent of model prompting."""

import re
from copy import deepcopy
from datetime import date, timedelta

from .agent_contracts import ValidationIssue

TEMPORARY_DAYS = {'fact': 14, 'pattern': 21}
LONG_TERM = re.compile(r'以后|今后|长期|平时|一直|通常|习惯|每次|每天|每周|主要|偏好|不喜欢|喜欢|不爱', re.IGNORECASE)
ENDURING = re.compile(r'以后|今后|长期|平时|一直|通常|习惯|每次|每天|每周')
TEMPORAL = re.compile(r'今天|明天|后天|这次|本次|今晚|明晚')
CORRECTION = re.compile(r'更正|纠正|说错|不再|取消|改为|改成|替换|不用|不要|撤回|解除|恢复')


def dated_entry(entry, fallback):
    entry = deepcopy(entry)
    entry['event_date'] = entry.get('event_date') or str(fallback)
    window = TEMPORARY_DAYS.get(entry['category'])
    if entry['category'] == 'fact' and entry.get('retention') == 'long_term':
        window = None
    if window:
        cutoff = str(date.fromisoformat(entry['event_date']) + timedelta(days=window - 1))
        entry['expires_on'] = min(entry.get('expires_on') or cutoff, cutoff)
    return entry


def validate_memory_updates(parsed, row, sources, current):
    issues = []
    def issue(path, message):
        issues.append(ValidationIssue(path, 'memory_evidence', message))
    known = {e['key']: e for e in current}
    new_keys = {e.key for e in parsed.memory_updates}
    replaced = set(parsed.retire_keys)
    for entry in parsed.memory_updates:
        if entry.retention == 'long_term' and entry.category not in {'fact', 'preference', 'restriction'}:
            issue('memory_updates.retention', '临时模式和待确认问题不能声明为长期事实。')
        if entry.retention == 'long_term' and entry.expires_on is not None:
            issue('memory_updates.expires_on', '长期信息不设自动到期日；临时信息使用temporary。')
        if entry.retention == 'long_term' and entry.evidence and all(
                TEMPORAL.search(e.quote) and not ENDURING.search(e.quote) for e in entry.evidence):
            issue('memory_updates.retention', '当天、本次或今晚的临时信息不能仅凭长期问题永久保存。')
        if entry.confirmed_at is not None:
            issue('memory_updates.confirmed_at', '用户确认时间由显式确认操作记录，模型不能自行声明。')
        refs = {(s.feedback_id, s.revision) for s in entry.sources}
        evidence = {(e.feedback_id, e.revision) for e in entry.evidence}
        if evidence != refs or not entry.evidence or any(
            (e.feedback_id, e.revision) not in sources
            or e.quote not in sources[(e.feedback_id, e.revision)]['raw_text'] for e in entry.evidence
        ):
            issue('memory_updates.evidence', '每个来源必须有对应原文逐字引文，不得编造或省略。')
        if entry.category == 'pattern' and len({sources[s]['date'] for s in refs if s in sources}) < 2:
            issue('memory_updates.sources', '多次模式至少需要两个不同日期的原文；单日观察请使用临时fact。')
        plan_questions = row.get('trace', {}).get('source_context', {}).get('answered_questions', [])
        question_is_enduring = any(LONG_TERM.search(question) and not TEMPORAL.search(question)
                                   for question in plan_questions)
        if entry.category == 'preference' and not (question_is_enduring or any(
                LONG_TERM.search(e.quote) and (not TEMPORAL.search(e.quote) or ENDURING.search(e.quote))
                for e in entry.evidence)):
            issue('memory_updates.category', '持续偏好必须有长期、平时或明确喜欢/不喜欢的表达；单日意愿用fact。')
        if (entry.event_date and entry.event_date > date.fromisoformat(row['date']) and (
                entry.category != 'fact' or not any(re.search(r'明天|后天|下周|\d{4}-\d{2}-\d{2}', e.quote)
                                                    for e in entry.evidence))):
            issue('memory_updates.event_date', '未来事件日期必须有明确的未来意愿原文依据。')
        if entry.key in entry.supersedes or any(key not in known or key in new_keys for key in entry.supersedes):
            issue('memory_updates.supersedes', '只能替代已存在的其他记忆，不允许循环或本批新条目。')
        if entry.supersedes and not any(e.feedback_id == row['id'] and CORRECTION.search(e.quote)
                                        for e in entry.evidence):
            issue('memory_updates.supersedes', '替代旧记忆需要本次原话明确更正或停止采用，新增偏好不自动删除旧偏好。')
        replaced.update(entry.supersedes)
    if any(key not in known for key in parsed.retire_keys):
        issue('retire_keys', '只能移除已经存在的记忆。')
    # All replacement paths, including new keys, are checked by the restriction guard.
    return issues, replaced


def merge_memory_updates(entries, understanding, day):
    replaced = set(understanding['retire_keys'])
    for entry in understanding['memory_updates']:
        replaced.update(entry.get('supersedes', []))
    result = {e['key']: e for e in entries if e['key'] not in replaced}
    result.update({e['key']: dated_entry(e, day) for e in understanding['memory_updates']})
    return list(result.values())
