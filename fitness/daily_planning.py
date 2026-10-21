"""Coordinate training and nutrition against confirmed facts and durable plan versions."""

import re
from copy import deepcopy
from datetime import date, timedelta

from .agent_contracts import PlanningRunError
from .feedback_facts import merge_feedback_days
from .feedback_memory import compact_feedback_reports
from .history import summarize_recent_trend
from .models import Profile
from .nutrition_agent import NutritionPlannerAgent
from .plan_store import PlanRepository, fingerprint
from .storage import Conflict, NotFound, now
from .training_agent import TrainingPlannerAgent
from .training_contracts import TrainingTask
from .training_state import resolve_training_state


def nutrition_review(records, end_date, goal, *, health_clear=True):
    """Suggest a small user-reviewed target change only from sustained, adherent data."""
    start = end_date - timedelta(days=13)
    merged = merge_feedback_days(records)
    rows = []
    for key, row in merged.items():
        try:
            day = date.fromisoformat(key)
        except ValueError:
            continue
        if start <= day <= end_date and row.get('status', 'confirmed') == 'confirmed':
            rows.append((day, row.get('data') or {}))
    prior = [data for day, data in rows if start <= day <= end_date - timedelta(days=7)]
    recent = [data for day, data in rows if end_date - timedelta(days=6) <= day <= end_date]
    weights_prior = [data['weight_kg'] for data in prior if isinstance(data.get('weight_kg'), (int, float))]
    weights_recent = [data['weight_kg'] for data in recent if isinstance(data.get('weight_kg'), (int, float))]
    adherence = [data['diet_followed_plan'] for _, data in rows if type(data.get('diet_followed_plan')) is bool]
    result = {'status': 'insufficient_data', 'goal': goal, 'suggested_adjustment_kcal': None,
              'evidence': [], 'recommendation': None, 'review_after_days': 14}
    if (not health_clear or len(weights_prior) < 2 or len(weights_recent) < 2 or
            len(weights_prior) + len(weights_recent) < 4 or len(adherence) < 4):
        result['evidence'].append('最近14天的称重或饮食执行记录不足，暂时维持当前目标。')
        return result
    adherence_rate = sum(adherence) / len(adherence)
    result['adherence_rate'] = round(adherence_rate, 3)
    result['weight_samples'] = len(weights_prior) + len(weights_recent)
    if adherence_rate < 0.75:
        result['evidence'].append(f'饮食执行记录为{len(adherence)}条，执行率约{adherence_rate:.0%}；先改善计划可执行性，不按当前体重趋势调整热量。')
        return result
    prior_average = sum(weights_prior) / len(weights_prior)
    recent_average = sum(weights_recent) / len(weights_recent)
    change = recent_average - prior_average
    weekly_percent = change / prior_average * 100 if prior_average else 0
    fatigue_count = sum(bool(data.get('fatigue')) for data in recent)
    result.update(previous_average_weight_kg=round(prior_average, 2),
                  recent_average_weight_kg=round(recent_average, 2),
                  weekly_change_kg=round(change, 2))
    result['evidence'].append(
        f'前后两周体重均值约{prior_average:.2f}kg和{recent_average:.2f}kg，变化约{change:+.2f}kg；'
        f'{len(adherence)}条饮食执行记录的执行率约{adherence_rate:.0%}。')
    adjustment = None
    if goal == 'fat_loss' and weekly_percent >= -0.15:
        result['status'] = 'monitor'
        result['recommendation'] = (
            '减脂期间体重均值变化较小且饮食执行记录较稳定。先核对餐食份量、烹调油和记录完整度；'
            '目前没有足够的饥饿感与训练表现记录，不贸然下调热量。继续观察并至少两周后复核。')
        result['evidence'].append('当前反馈没有结构化的饥饿感或训练表现记录，因此先检查记录质量，不建议减少热量。')
        return result
    elif goal == 'fat_loss' and weekly_percent <= -0.75 and fatigue_count >= 2:
        adjustment = 100
        reason = f'体重均值下降较快（约{abs(change):.2f}kg/周），近期有{fatigue_count}条疲劳记录'
    elif goal == 'muscle_gain' and weekly_percent <= 0.10:
        adjustment = 100
        reason = '增肌期间体重均值未明显上升，且饮食执行记录较稳定'
    elif goal == 'muscle_gain' and weekly_percent >= 0.50:
        adjustment = -100
        reason = '增肌期间体重均值上升较快，建议复核能量盈余'
    if adjustment is None:
        result['status'] = 'monitor'
        result['evidence'].append('当前趋势未达到保守调整阈值；继续记录至少两周再复核。')
        return result
    result.update(status='review', suggested_adjustment_kcal=adjustment)
    direction = '下调' if adjustment < 0 else '上调'
    result['recommendation'] = (
        f'{reason}。可考虑将每日目标{direction}约{abs(adjustment)}千卡，'
        '这是复盘建议，不会自动改写已确认目标；如确认新目标，请重新生成并确认长期计划，之后至少观察14天。')
    return result


class DailyPlanningService:
    def __init__(self, store, settings, knowledge=None, provider=None):
        self.store, self.settings, self.knowledge = store, settings, knowledge
        self.repo = PlanRepository(store)
        self.training = TrainingPlannerAgent(settings, provider)
        self.nutrition = NutritionPlannerAgent(settings, provider)

    def create_long_term(self, start_date, labels=None, mode='demo', conditions=None, expected_snapshot_token=None,
                         feedback_action_id=None):
        if feedback_action_id:
            saved = next((r for r in self.repo.long_terms() if r['trace'].get('feedback_action_id') == feedback_action_id), None)
            if saved:
                return saved
        snapshot = self.repo.snapshot(start_date)
        self._check_expected(snapshot, expected_snapshot_token)
        record = snapshot['profile']
        if record is None:
            raise Conflict('请先保存档案。')
        profile = Profile.model_validate(record['data'])
        run = None
        if mode == 'live':
            state = resolve_training_state(profile=profile, day=start_date, history=self._training_history(snapshot),
                restrictions=self._restrictions(snapshot), conditions=conditions or '', conditions_recorded_at=now())
            task = self._task(snapshot, start_date, 'cycle', profile, conditions or '', state, cycle_labels=labels)
            run = self.training.plan_cycle_live(task, knowledge=self.knowledge)
            self._require_ready(run, snapshot)
            cycle = run.candidate['cycle']
        else:
            cycle = self.training.build_cycle(profile, labels)
        nutrition_run = None
        if mode == 'live':
            self._check_expected(self.repo.snapshot(start_date), snapshot['token'])
            nutrition_run = self.nutrition.plan_live(profile, conditions=conditions or '', training_cycle=cycle,
                history=compact_feedback_reports(snapshot['feedback']),
                personal_memory=snapshot['personal_memory'])
            self._require_ready(nutrition_run, snapshot)
            nutrition = nutrition_run.candidate
        else:
            nutrition = self.nutrition.plan(profile).model_dump(mode='json')
        context = self.knowledge.for_plan(profile) if self.knowledge else None
        from .planning import context_persistence_status, persistent_context_snapshots
        strategies, citations = persistent_context_snapshots(context) if context else ([], [])
        goal_titles = {'fat_loss': '减脂与力量保持', 'muscle_gain': '增肌与力量',
                       'general_health': '健康与体能'}
        data = {'title': goal_titles.get(profile.goals.primary, '个性化训练') + ' · 长期计划',
                'goals': profile.goals.model_dump(mode='json'), 'cycle': cycle, 'nutrition': nutrition,
                'review_after': (start_date + timedelta(days=14)).isoformat(),
                'review_rules': ['结合连续体重、饥饿感、训练表现和执行情况复盘；单日波动不改写长期目标。',
                                 '持续疲劳、伤痛或难以执行时重新评估训练循环；长期修改保存新版本并确认。'],
                'recovery_guidance': ['保持规律作息，睡眠以7至9小时为参考，结合个人恢复情况调整。'],
                'strategy_context': [s.model_dump(mode='json') for s in strategies],
                'knowledge_context': [c.model_dump(mode='json') for c in citations]}
        if run:
            data.update(summary=run.candidate['summary'], assumptions=run.candidate['assumptions'],
                        training_questions=run.candidate['questions'])
        from .plan_streaming import emit_plan_event
        emit_plan_event('status', {'message': '计划已校验，正在保存…'})
        return self.repo.create_long(start_date, data,
            {'training_planner': 'TrainingPlannerAgent', 'nutrition_planner': 'NutritionPlannerAgent',
             'training_source': 'model' if run else 'deterministic_local',
             'nutrition_source': 'model' if nutrition_run else 'deterministic_local',
             'nutrition_provider': nutrition_run.trace if nutrition_run else {'status': 'demo'},
             'provider': run.trace if run else {'status': 'demo'},
             'mode': mode, 'feedback_action_id': feedback_action_id,
             'knowledge_status': context_persistence_status(context) if context else 'unavailable'},
            record['version'], expected_token=snapshot['token'] if run else None)

    @staticmethod
    def _check_expected(snapshot, expected):
        if expected is not None and expected != snapshot['token']:
            raise Conflict('输入已经变化，请刷新后重新评估。')

    @staticmethod
    def _require_ready(run, snapshot):
        if run.status != 'draft_ready':
            raise PlanningRunError(run, snapshot['token'])

    @staticmethod
    def _restrictions(snapshot):
        releases, active = {}, []
        for row in reversed(snapshot['days']):
            for release in row.get('trace', {}).get('restriction_releases', []):
                releases[release['area']] = deepcopy(release)
        for row in snapshot['days']:
            for restriction in row['data'].get('decision', {}).get('restrictions', []):
                release = releases.get(restriction.get('area'))
                if restriction.get('active', True) and (not release or row['created_at'] > release['resolved_at']):
                    active.append(deepcopy(restriction))
        return [*[{**r, 'active': False} for r in releases.values()], *active]

    @staticmethod
    def _training_history(snapshot):
        history = list(snapshot['feedback'])
        for row in snapshot['days']:
            if row['data'].get('conditions'):
                history.append({'id': 'conditions-' + row['id'], 'date': row['date'],
                    'status': 'confirmed', 'created_at': row.get('trace', {}).get('conditions_recorded_at', row['created_at']),
                    'include_in_current': False, 'source_kind': 'conditions',
                    'raw_text': row['data']['conditions'], 'data': {}})
        return history

    @staticmethod
    def _task(snapshot, day, kind, profile, conditions, state, **kwargs):
        limits = [int(n) for n in re.findall(r'(\d{1,3})\s*(?:分钟|分鐘|minutes?|mins?)', conditions, re.IGNORECASE)]
        if profile.training.session_duration_minutes is not None:
            limits.append(profile.training.session_duration_minutes)
        limit = min(limits) if limits else None
        return TrainingTask(kind=kind, date=day, profile=profile, profile_version=snapshot['profile']['version'],
            long_term=snapshot['long_term'], history=snapshot['feedback'], state=state, conditions=conditions,
            personal_memory=snapshot['personal_memory'],
            snapshot_token=snapshot['token'], time_limit_minutes=limit, **kwargs)

    def confirm_long_term(self, ident):
        return self.repo.confirm_long(ident)

    @staticmethod
    def _latest_days(rows):
        latest = {}
        for row in rows:
            latest.setdefault(row['date'], row)
        return latest

    def generate_day(self, day, conditions=None, mode='demo', expected_snapshot_token=None, feedback_action_id=None):
        if feedback_action_id:
            saved = next((r for r in self.repo.days() if r['trace'].get('feedback_action_id') == feedback_action_id), None)
            if saved:
                return saved
        snapshot = self.repo.snapshot(day)
        self._check_expected(snapshot, expected_snapshot_token)
        record, long = snapshot['profile'], snapshot['long_term']
        if record is None or long is None:
            raise Conflict('请先保存档案并确认生效的长期计划。')
        if long['profile_version'] != record['version']:
            raise Conflict('档案已改变，请重新生成并确认长期计划。')
        profile = Profile.model_validate(record['data'])
        latest = self._latest_days(snapshot['days'])
        current = latest.get(day.isoformat())
        explicit_conditions = conditions is not None
        if conditions is None:
            conditions = current['data'].get('conditions', '') if current else ''
        conditions_recorded_at = (current.get('trace', {}).get('conditions_recorded_at', current['created_at'])
                                  if current else now())
        releases = {}
        for row in reversed(list(latest.values())):
            for release in row.get('trace', {}).get('restriction_releases', []):
                releases[release['area']] = deepcopy(release)
        released_text = any(conditions_recorded_at <= r['resolved_at'] and any(
            item.get('date') == day.isoformat() and item.get('text') == conditions
            for item in r.get('released_conditions', [])) for r in releases.values())
        if explicit_conditions and (not current or conditions != current['data'].get('conditions') or released_text):
            conditions_recorded_at = now()
        completed = current['data'].get('completed_meals', []) if current else []
        past = [r for key, r in sorted(latest.items()) if key < day.isoformat()]
        facts = [{k: r[k] for k in ('id', 'date', 'revision', 'data', 'raw_text')} for r in snapshot['feedback']]
        signature = fingerprint([record['version'], long['id'], facts,
                                 [(r['id'], r['revision']) for r in past], conditions, conditions_recorded_at,
                                 completed, mode, snapshot['personal_memory']])
        if current and current['input_fingerprint'] == signature:
            return current
        cycle, index = long['data']['cycle'], 0
        merged_feedback = merge_feedback_days(snapshot['feedback'])
        by_date = merged_feedback
        restrictions = [{**release, 'active': False} for release in releases.values()]
        # Superseded conditions retain symptom reports until explicit release.
        # Only the current conditions participate in ordinary same-day intent.
        training_history = list(snapshot['feedback'])
        for row in snapshot['days']:
            if row['date'] > day.isoformat():
                continue
            if row['data'].get('conditions'):
                training_history.append({'id': 'conditions-' + row['id'], 'date': row['date'],
                    'status': 'confirmed', 'created_at': row.get('trace', {}).get('conditions_recorded_at', row['created_at']),
                    'include_in_current': False,
                    'source_kind': 'conditions', 'raw_text': row['data']['conditions'], 'data': {}})
        for row in latest.values():
            for restriction in row['data'].get('decision', {}).get('restrictions', []):
                if restriction.get('area') == 'urgent_symptoms' and restriction.get('active', True):
                    release = releases.get('urgent_symptoms')
                    if not release or row['created_at'] > release['resolved_at']:
                        restrictions.append(deepcopy(restriction))
        for row in past:
            if row['long_term_id'] != long['id']:
                continue
            action = row['data']['decision']['action']
            fact = (by_date.get(row['date']) or {}).get('data', {})
            if action == 'skip' or (action == 'rest' and cycle[index]['kind'] == 'rest') or row['data']['training']['kind'] == 'training' and fact.get('training_completed') is True:
                index = (index + 1) % len(cycle)
        today_facts = (merged_feedback.get(day.isoformat()) or {}).get('data', {})
        actual_training = next((r['data']['training'] for r in snapshot['days']
                                if r['date'] == day.isoformat()
                                and r['data']['training']['kind'] == 'training'), None)
        if mode == 'live' and today_facts.get('training_completed') is True and actual_training:
            decision = {'action': 'train', 'training': deepcopy(actual_training), 'cycle_index': index,
                'next_cycle_index': index, 'restrictions': self._restrictions(snapshot),
                'reasons': ['保留已确认完成的训练。'], 'questions': [],
                'provider': {'status': 'preserved', 'calls': 0, 'usage': {}}}
        elif mode == 'live':
            state = resolve_training_state(profile=profile, day=day, history=training_history,
                restrictions=restrictions, conditions=conditions, conditions_recorded_at=conditions_recorded_at)
            task = self._task(snapshot, day, 'day', profile, conditions, state, cycle=cycle, cycle_index=index)
            run = self.training.plan_day_live(task, knowledge=self.knowledge)
            self._require_ready(run, snapshot)
            candidate = run.candidate
            decision = {**candidate, 'cycle_index': index,
                'next_cycle_index': (index + 1) % len(cycle) if candidate['action'] == 'skip' else index,
                'restrictions': state['restrictions'], 'provider': run.trace}
        else:
            decision = self.training.plan_day(profile, cycle, index, day, training_history,
                restrictions, conditions=conditions, mode='demo', conditions_recorded_at=conditions_recorded_at)
        meal_training = actual_training if today_facts.get('training_completed') is True and actual_training else decision['training']
        nutrition_context = {'conditions': conditions or today_facts.get('meal_conditions'),
            'available_foods': today_facts.get('available_foods'), 'desired_foods': today_facts.get('desired_foods'),
            'already_eaten': today_facts.get('already_eaten') or today_facts.get('food_summary'),
            'daily_targets': long['data']['nutrition']['daily_targets'], 'training': meal_training}
        nutrition_run = None
        if mode == 'live':
            self._check_expected(self.repo.snapshot(day), snapshot['token'])
            eaten_rows = [m for m in current['data']['nutrition']['meal_options']
                          if m['meal'] in completed] if current else []
            nutrition_run = self.nutrition.plan_live(profile, **nutrition_context, lock_daily_targets=True, completed_meals=eaten_rows,
                history=compact_feedback_reports(snapshot['feedback']),
                personal_memory=snapshot['personal_memory'])
            self._require_ready(nutrition_run, snapshot)
            nutrition = nutrition_run.candidate
        else:
            nutrition = self.nutrition.plan(profile, **nutrition_context).model_dump(mode='json')
        # The confirmed long-term target governs daily meals until a new long-term version is confirmed.
        nutrition['daily_targets'] = deepcopy(long['data']['nutrition']['daily_targets'])
        training = decision['training']
        if current:
            eaten = {m['meal']: m for m in current['data']['nutrition']['meal_options'] if m['meal'] in completed}
            nutrition['meal_options'] = [deepcopy(eaten.get(m['meal'], m)) for m in nutrition['meal_options']]
            if today_facts.get('training_completed') is True:
                completed_row = next((r for r in snapshot['days'] if r['date'] == day.isoformat()
                                      and r['data'].get('training', {}).get('kind') == 'training'), None)
                if completed_row is not None:
                    training = deepcopy(completed_row['data']['training'])
                    decision = {**decision, 'action': 'train', 'cycle_index': completed_row['data']['cycle_index'],
                            'next_cycle_index': completed_row['data']['cycle_index'],
                            'reasons': ['保留当天已确认完成的训练；新限制用于后续安排。', *decision['reasons']]}
        trend = summarize_recent_trend(snapshot['feedback'], end_date=day, days=14)
        review = []
        if day.isoformat() >= long['data']['review_after']:
            review.append('已到长期计划复盘日期，请结合趋势检查目标与执行情况。')
        fatigue = trend['metrics']['fatigue_reports']
        if fatigue['reported_count'] >= 3:
            review.append('近期多次反馈疲劳，建议复盘训练量和恢复安排。')
        nutrition_review_result = nutrition_review(snapshot['feedback'], day, profile.goals.primary,
            health_clear=(profile.health.exercise_limiting_conditions_status == 'none_known_self_reported'
                          and not profile.health.medications))
        if nutrition_review_result['recommendation']:
            review.extend(nutrition_review_result['evidence'])
            review.append(nutrition_review_result['recommendation'])
        water = {'base_ml': round(profile.personal.weight_kg * 30 / 50) * 50
                 if profile.personal.weight_kg is not None else None,
                 'note': ('按体重约30毫升/公斤给出起始饮水参考，分次饮用；出汗、天气和饮食会影响需求。'
                          '如有心肾疾病、限水要求或特殊情况，遵从专业意见，不执行通用水量。')
                 if profile.personal.weight_kg is not None else
                 '档案未提供体重，暂不生成个体化饮水量；按口渴和环境调整，有限水要求时遵从专业意见。'}
        data = {'date': day.isoformat(), 'conditions': conditions, 'cycle_index': decision['cycle_index'],
                'training': training, 'decision': decision, 'nutrition': nutrition, 'water': water,
                'completed_meals': completed, 'training_completed': today_facts.get('training_completed'),
                'recovery_guidance': long['data']['recovery_guidance'], 'review_suggestions': review}
        trace = {'steps': ['long_term_plan', 'confirmed_history', 'training_planner', 'nutrition_planner'],
                 'feedback_action_id': feedback_action_id,
                 'mode': mode, 'training_source': 'model' if mode == 'live' else 'deterministic_local',
                 'nutrition_source': 'model' if nutrition_run else 'deterministic_local',
                 'nutrition_provider': nutrition_run.trace if nutrition_run else {'status': 'demo'},
                 'long_term_id': long['id'], 'feedback_versions': [{k: r[k] for k in ('id', 'revision', 'date')}
                                                                for r in snapshot['feedback']],
                 'trend': trend, 'nutrition_review': nutrition_review_result,
                 'provider': decision['provider'],
                 'conditions_recorded_at': conditions_recorded_at,
                 'restriction_releases': list(releases.values())}
        if today_facts.get('training_completed') is True and actual_training:
            original = next(r for r in snapshot['days'] if r['date'] == day.isoformat()
                            and r['data']['training']['kind'] == 'training')
            trace['training_source'] = original.get('trace', {}).get('training_source', 'unknown')
            trace['preserved_from'] = original['id']
        from .plan_streaming import emit_plan_event
        emit_plan_event('status', {'message': '计划已校验，正在保存…'})
        return self.repo.append_day(day, data, trace, snapshot['token'], signature)

    def complete_meal(self, ident, meal, expected_revision):
        with self.store.connection() as db:
            from .storage import decode
            row = decode(db.execute('SELECT * FROM daily_plans WHERE id=?', (ident,)).fetchone())
        if row is None:
            raise NotFound('当天计划不存在。')
        snapshot = self.repo.snapshot(row['date'])
        current = next(r for r in snapshot['days'] if r['date'] == row['date'])
        if current['id'] != ident or current['revision'] != expected_revision:
            raise Conflict('当天计划已有更新，请刷新后记录餐次。')
        if row['long_term_id'] != snapshot['long_term']['id'] or row['profile_version'] != snapshot['profile']['version']:
            raise Conflict('长期计划或档案已有更新，请刷新当天计划后记录餐次。')
        if meal not in {m['meal'] for m in row['data']['nutrition']['meal_options']}:
            raise ValueError('餐次不存在。')
        if meal in row['data']['completed_meals']:
            return row
        data = deepcopy(row['data'])
        data['completed_meals'].append(meal)
        return self.repo.append_day(row['date'], data, row['trace'], snapshot['token'],
                                    fingerprint([row['input_fingerprint'], data['completed_meals']]))

    def release_restriction(self, ident, area, expected_revision, confirmation_text):
        if not isinstance(confirmation_text, str) or len(confirmation_text.strip()) < 5:
            raise ValueError('解除限制需要填写恢复情况和活动范围确认。')
        with self.store.connection() as db:
            from .storage import decode
            row = decode(db.execute('SELECT * FROM daily_plans WHERE id=?', (ident,)).fetchone())
        if row is None:
            raise NotFound('当天计划不存在。')
        snapshot = self.repo.snapshot(row['date'])
        current = next((r for r in snapshot['days'] if r['date'] == row['date']), None)
        if current is None or current['id'] != ident or current['revision'] != expected_revision:
            raise Conflict('当天计划已有更新，请刷新后解除限制。')
        if row['long_term_id'] != snapshot['long_term']['id'] or row['profile_version'] != snapshot['profile']['version']:
            raise Conflict('长期计划或档案已有更新，请刷新当天计划后解除限制。')
        profile = Profile.model_validate(snapshot['profile']['data'])
        if (profile.health.exercise_limiting_conditions_status == 'has_conditions'
                or profile.health.exercise_limiting_conditions_details):
            raise ValueError('档案中仍记录运动限制。请先更新档案并确认新的长期计划。')
        data = deepcopy(row['data'])
        if not any(r.get('area') == area and r.get('active', True)
                   for r in data.get('decision', {}).get('restrictions', [])):
            raise ValueError('该部位没有可解除的活跃限制。')
        resolved_at = now()
        for restriction in data.get('decision', {}).get('restrictions', []):
            if restriction.get('area') == area:
                restriction['active'] = False
                restriction['resolved_at'] = resolved_at
                restriction['released_conditions'] = [
                    {'date': r['date'], 'text': r['data'].get('conditions', '')}
                    for r in snapshot['days']]
        trace = deepcopy(row['trace'])
        trace.setdefault('restriction_releases', []).append({
            'area': area, 'confirmation_text': confirmation_text.strip(),
            'resolved_on': row['date'], 'resolved_at': resolved_at, 'source_revision': expected_revision,
            'released_conditions': [{'date': r['date'], 'text': r['data'].get('conditions', '')}
                                    for r in snapshot['days']],
        })
        return self.repo.append_day(row['date'], data, trace, snapshot['token'],
                                    fingerprint([row['input_fingerprint'], 'release', area, confirmation_text]))
