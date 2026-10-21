from datetime import date

from fitness.feedback_facts import merge_feedback_days
from fitness.feedback_memory import compact_feedback_reports
from fitness.history import summarize_recent_trend

DAY = date(2026, 10, 21)


def row(ident, day='2026-10-21', **facts):
    return {'id': ident, 'revision': 1, 'date': day, 'status': 'confirmed',
            'created_at': ident, 'raw_text': ident, 'data': {'date': day, **facts}}


def test_same_day_reports_are_one_sample_and_keep_raw_count():
    rows = [row(str(n), weight_kg=80, fatigue='累') for n in range(3)]
    trend = summarize_recent_trend(rows, end_date=DAY, days=14)
    assert trend['record_count'] == 1
    assert trend['raw_record_count'] == 3
    assert trend['metrics']['weight_kg']['valid_count'] == 1
    assert trend['metrics']['weight_kg']['insufficient_data']
    assert trend['metrics']['fatigue_reports']['reported_count'] == 1


def test_food_supplement_does_not_erase_exercises_and_corrections_preserve_other_actions():
    bench = {'exercise_id': 'bench_press', 'weight_kg': 45, 'rpe': 9}
    squat = {'exercise_id': 'squat', 'weight_kg': 60}
    merged = merge_feedback_days([
        row('1', exercise_results=[bench], training_completed=False),
        row('2', exercise_results=[squat]),
        row('3', exercise_results=[], food_summary='午饭米饭'),
        row('4', exercise_results=[{**bench, 'weight_kg': 40}], training_completed=True),
    ])['2026-10-21']
    assert {x['exercise_id']: x['weight_kg'] for x in merged['data']['exercise_results']} == {
        'bench_press': 40, 'squat': 60}
    assert merged['data']['training_completed'] is True
    assert len(merged['source_feedback_ids']) == 4


def test_unrelated_edit_does_not_make_old_sleep_fact_newer():
    old = row('1', sleep_hours=6, weight_kg=80)
    old['fact_updated_at'] = '4'
    old['field_updated_at'] = {'sleep_hours': '1', 'weight_kg': '4'}
    newer = row('2', sleep_hours=8)
    assert merge_feedback_days([old, newer])['2026-10-21']['data']['sleep_hours'] == 8


def test_recent_reports_use_calendar_window_and_exclude_future_and_drafts():
    rows = [row('old', '2020-01-01'), row('boundary', '2026-10-08'),
            row('now'), row('future', '2026-10-22'), {**row('draft'), 'status': 'draft'}]
    recent = compact_feedback_reports(rows, end_date=DAY)
    assert [r['feedback_id'] for r in recent] == ['boundary', 'now']


def test_recent_context_preserves_multiple_days_when_one_day_has_many_reports():
    rows = [row('earlier', '2026-10-20'), *[row(f'{i:02}') for i in range(20)]]
    recent = compact_feedback_reports(rows, end_date=DAY, limit=4)
    assert len(recent) == 4
    assert any(r['date'] == '2026-10-20' for r in recent)


def test_coach_history_is_anchored_to_feedback_date_and_queries_have_cutoff(tmp_path):
    from fitness.config import Settings
    from fitness.feedback_coach import FeedbackCoach
    from fitness.storage import Store
    store = Store(tmp_path / 'context.db')
    service = FeedbackCoach(store, Settings(), today=lambda: DAY)
    service.record('很久以前的疲劳', date(2020, 1, 1))
    current = service.record('补录当天', date(2026, 10, 19))
    service.record('后来的信息', DAY)
    task, tools = service.context(current)
    assert task['recent_reports'] == []
    assert tools.call('read_feedback_history', {'query': '后来'})['items'] == []
    assert task['history_scope']['end_date'] == '2026-10-19'


def test_same_exercise_query_returns_distinct_sessions_with_actual_set_metrics(profile_data):
    from test_training_live import task

    from fitness.training_tools import TrainingTools
    history = [row('1', '2026-10-18', exercise_results=[{'exercise_id': 'bench_press',
        'session_id': 'morning', 'sets': [{'reps': 8, 'weight_kg': 45}, {'reps': 7, 'weight_kg': 45}]}]),
        row('2', '2026-10-19', exercise_results=[{'exercise_id': 'bench_press',
            'session_id': 'evening', 'sets': [{'reps': 8, 'weight_kg': 45}, {'reps': 8, 'weight_kg': 45}]}]),
        row('3', '2026-10-19', food_summary='米饭', exercise_results=[]),
        row('4', '2026-10-19', exercise_results=[{'exercise_id': 'squat', 'weight_kg': 60}])]
    result = TrainingTools(task(profile_data, history=history), None).call('get_training_history',
        {'days': 21, 'exercise_id': 'bench_press', 'session_limit': 3})
    sessions = result['exercise_history']['sessions']
    assert [s['date'] for s in sessions] == ['2026-10-19', '2026-10-18']
    assert sessions[0]['total_reps'] == 16
    assert sessions[0]['known_volume_kg'] == 720
    assert sessions[0]['volume_complete'] is True
    assert all(s['exercise_id'] == 'bench_press' for s in sessions)


def test_partial_weight_is_not_reported_as_full_volume():
    from fitness.history import summarize_exercise_history
    records = [row('1', exercise_results=[{'exercise_id': 'pull_up', 'sets': [
        {'reps': 8}, {'reps': 6, 'weight_kg': 5}]}])]
    session = summarize_exercise_history(records, exercise_id='pull_up')['sessions'][0]
    assert session['total_reps'] == 14
    assert session['known_volume_kg'] == 30
    assert session['volume_complete'] is False


def test_partial_action_report_preserves_existing_actual_weight():
    records = [row('1', exercise_results=[{'exercise_id': 'bench_press', 'weight_kg': 45}]),
               row('2', exercise_results=[{'exercise_id': 'bench_press', 'rpe': 9, 'weight_kg': None}])]
    result = merge_feedback_days(records)['2026-10-21']['data']['exercise_results'][0]
    assert result['weight_kg'] == 45
    assert result['rpe'] == 9


def test_editing_squat_does_not_make_unchanged_bench_override_later_report(tmp_path):
    from fitness.models import FeedbackData
    from fitness.storage import Store
    store=Store(tmp_path / 'nested.db')
    def save(results):
        facts=FeedbackData(date=DAY,exercise_results=results).model_dump(mode='json')
        draft=store.create_feedback('训练记录',facts,'demo',{})
        return store.confirm_feedback(draft['id'],facts,0)
    old=save([{'exercise_id':'bench_press','weight_kg':45},{'exercise_id':'squat','weight_kg':60}])
    save([{'exercise_id':'bench_press','weight_kg':50}])
    corrected={**old['data'],'exercise_results':[
        {'exercise_id':'bench_press','weight_kg':45},{'exercise_id':'squat','weight_kg':65}]}
    store.confirm_feedback(old['id'],corrected,old['revision'])
    results=merge_feedback_days(store.feedback(limit=None))[str(DAY)]['data']['exercise_results']
    assert {r['exercise_id']:r['weight_kg'] for r in results} == {'bench_press':50,'squat':65}


def test_unrelated_old_report_edit_keeps_complementary_exercise_attributes(tmp_path):
    from fitness.models import FeedbackData
    from fitness.storage import Store
    store=Store(tmp_path / 'attributes.db')
    facts=FeedbackData(date=DAY,exercise_results=[{'exercise_id':'bench_press','weight_kg':45}]).model_dump(mode='json')
    old=store.create_feedback('卧推45kg',facts,'demo',{})
    old=store.confirm_feedback(old['id'],facts,0)
    new_facts=FeedbackData(date=DAY,exercise_results=[{'exercise_id':'bench_press','rpe':9}]).model_dump(mode='json')
    new=store.create_feedback('末组RPE9',new_facts,'demo',{})
    store.confirm_feedback(new['id'],new_facts,0)
    store.confirm_feedback(old['id'],{**facts,'sleep_hours':8},old['revision'])
    result=merge_feedback_days(store.feedback(limit=None))[str(DAY)]['data']['exercise_results'][0]
    assert result['weight_kg'] == 45
    assert result['rpe'] == 9


def test_partial_set_completion_does_not_erase_actual_reps_or_volume():
    from fitness.history import summarize_exercise_history
    records=[row('1',exercise_results=[{'exercise_id':'bench_press','sets':[
        {'reps':8,'weight_kg':45,'completed':True},{'reps':6,'weight_kg':47.5,'completed':False}]}])]
    session=summarize_exercise_history(records)['sessions'][0]
    assert session['total_reps']==14
    assert session['known_volume_kg']==645


def test_large_performance_context_is_bounded_and_marks_truncation():
    import json

    from fitness.history import summarize_exercise_history
    records=[row(str(i),exercise_results=[{'exercise_id':f'exercise-{i}-{j}',
        'sets':[{'reps':8,'weight_kg':45,'rpe':8} for _ in range(100)]} for j in range(20)]) for i in range(30)]
    result=summarize_exercise_history(records,budget_bytes=12000)
    assert len(json.dumps(result,ensure_ascii=False).encode())<=13000
    assert result['truncated']
    assert result['session_count']==600


def test_same_day_session_limit_prefers_latest_session():
    from fitness.history import summarize_exercise_history
    records=[row(str(i),exercise_results=[{'exercise_id':'bench_press','session_id':f's{i}',
                                          'weight_kg':40+i}]) for i in range(4)]
    sessions=summarize_exercise_history(records,exercise_id='bench_press',limit=3)['sessions']
    assert [s['session_id'] for s in sessions]==['s3','s2','s1']


def test_followup_cannot_attach_future_report_as_history(tmp_path):
    import pytest

    from fitness.config import Settings
    from fitness.feedback_coach import FeedbackCoach
    from fitness.storage import Store
    service=FeedbackCoach(Store(tmp_path / 'parent.db'),Settings(),today=lambda:DAY)
    parent=service.record('今天状态',DAY)
    with pytest.raises(ValueError,match='日期'):
        service.record('补录之前',date(2026,10,19),parent_feedback_id=parent['id'])


def test_performance_citations_reference_action_reports_not_later_food_only_reports():
    from fitness.history import summarize_exercise_history
    rows=[row('training',exercise_results=[{'exercise_id':'bench_press','weight_kg':45}]),
          *[row(f'zz-food{i}',food_summary='米饭') for i in range(10)]]
    result=summarize_exercise_history(rows)['sessions'][0]
    assert result['source_feedback_ids']==['training']
    assert result['sources']==[{'feedback_id':'training','revision':1}]
