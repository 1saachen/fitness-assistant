from datetime import date

import pytest
from test_training_live import task


def test_tools_limit_history_to_snapshot_date(profile_data):
    from fitness.training_tools import TrainingTools
    history = [{'id': str(n), 'date': day, 'status': 'confirmed', 'data': {
                    'exercise_results': [{'exercise_id': 'dumbbell_row', 'weight_kg': 20, 'rpe': 8}]},
                'created_at': day} for n, day in enumerate(['2026-10-19', '2026-10-21'])]
    tools = TrainingTools(task(profile_data, history=history), None)
    result = tools.call('get_training_history', {'days': 7})
    assert [r['date'] for r in result['records']] == ['2026-10-19']
    assert result['records'][0]['data']['exercise_results'][0] == {
        'exercise_id': 'dumbbell_row', 'weight_kg': 20, 'rpe': 8}
    with pytest.raises(ValueError):
        tools.call('write_sql', {})
    with pytest.raises(ValueError):
        tools.call('get_training_history', {'days': 365})
    assert tools.call('search_training_knowledge', {'query': '训练', 'limit': 3})['status'] == 'unavailable'


def test_time_and_equipment_and_sources_are_verified(profile_data):
    from test_training_live import day_candidate

    from fitness.training_validation import validate_training_candidate
    candidate = day_candidate()
    candidate['training']['exercises'][0]['exercise_id'] = 'squat'
    candidate['source_ids'] = ['invented']
    issues = validate_training_candidate(candidate, task(profile_data, time_limit_minutes=5), {})
    assert {'equipment', 'time_limit', 'unknown_source'} <= {i.code for i in issues}


def test_restrictions_cannot_be_bypassed_by_different_action(profile_data):
    from test_training_live import day_candidate

    from fitness.training_validation import validate_training_candidate
    candidate = day_candidate()
    issues = validate_training_candidate(candidate, task(profile_data,
        state={'active_restrictions': [{'area': 'shoulder', 'active': True}]}), {})
    assert any(i.code == 'restriction' for i in issues)
    candidate['action'] = 'skip'
    candidate['training'] = {'label': '跳过', 'kind': 'rest', 'exercises': [], 'estimated_minutes': 0}
    assert any(i.code == 'skip_unconfirmed' for i in validate_training_candidate(candidate, task(profile_data), {}))


def test_training_state_keeps_release_and_new_report_semantics(profile_data):
    from fitness.models import Profile
    from fitness.training_state import resolve_training_state
    old = {'area': 'shoulder', 'active': False, 'resolved_at': '2026-10-20T10:00:00Z'}
    history = [{'date': '2026-10-19', 'status': 'confirmed', 'raw_text': '肩膀疼',
                'created_at': '2026-10-19T10:00:00Z', 'data': {}}]
    arguments = {'profile': Profile.model_validate(profile_data), 'day': date(2026,10,20),
        'history': history, 'restrictions': [old], 'conditions': '', 'conditions_recorded_at': None}
    state = resolve_training_state(**arguments)
    assert not state['active_restrictions']
    history.append({'date': '2026-10-20', 'status': 'confirmed', 'raw_text': '肩膀再次疼',
                    'created_at': '2026-10-20T11:00:00Z', 'data': {}})
    assert resolve_training_state(**arguments)['active_restrictions'][0]['area'] == 'shoulder'
