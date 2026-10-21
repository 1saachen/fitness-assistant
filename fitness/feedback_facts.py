"""Merge confirmed daily facts without letting missing fields erase prior reports."""

from copy import deepcopy


def attach_fact_times(db, rows):
    """Use field revision times, never advice/analysis write times, to resolve corrections."""
    from .storage import decode
    for row in rows:
        timestamps, previous, exercise_times, prior_exercises = {}, {}, {}, {}
        for raw in db.execute('SELECT * FROM feedback_revisions WHERE feedback_id=? ORDER BY revision',
                              (row['id'],)):
            revision = decode(raw)
            row['fact_updated_at'] = revision['created_at']
            for field, value in revision['data'].items():
                if value != previous.get(field):
                    timestamps[field] = revision['created_at']
            current_exercises = {}
            for result in revision['data'].get('exercise_results', []):
                identity = exercise_identity(result, row['date'])
                current_exercises[identity] = result
                for attribute, value in result.items():
                    if value != prior_exercises.get(identity, {}).get(attribute):
                        exercise_times.setdefault(identity, {})[attribute] = revision['created_at']
            prior_exercises = current_exercises
            previous = revision['data']
        row['field_updated_at'] = timestamps
        row['exercise_updated_at'] = exercise_times
    return rows


def exercise_identity(result, day):
    import json
    return json.dumps([result.get('session_id') or str(day), result['exercise_id']], ensure_ascii=False)


def merge_feedback_days(rows):
    latest, clocks, exercises, exercise_clocks, exercise_sources = {}, {}, {}, {}, {}
    for row in sorted(rows, key=lambda r: (str(r.get('fact_updated_at') or r.get('created_at') or ''),
                                          str(r.get('id') or ''))):
        if row.get('status') not in {None, 'confirmed'}:
            continue
        day = str(row.get('date') or (row.get('data') or {}).get('date') or '')
        prior = latest.get(day, {})
        data = deepcopy(prior.get('data', {}))
        sources = deepcopy(prior.get('field_sources', {}))
        for key, value in (row.get('data') or {}).items():
            if value is None or value in ([], {}, ''):
                continue
            stamp = (str(row.get('field_updated_at', {}).get(key)
                         or row.get('fact_updated_at') or row.get('created_at') or ''), str(row.get('id') or ''))
            if key == 'exercise_results':
                bucket = exercises.setdefault(day, {})
                for result in value:
                    identity = exercise_identity(result, day)
                    target = bucket.setdefault(identity, {})
                    for attribute, amount in result.items():
                        if amount is None or amount in ([], {}, ''):
                            continue
                        attribute_stamp = (str(row.get('exercise_updated_at', {}).get(identity, {}).get(attribute)
                                               or stamp[0]), stamp[1])
                        clock_key = (day, identity, attribute)
                        if attribute_stamp >= exercise_clocks.get(clock_key, ('', '')):
                            target[attribute] = deepcopy(amount)
                            exercise_clocks[clock_key] = attribute_stamp
                            exercise_sources[clock_key] = {'feedback_id': row.get('id'), 'revision': row.get('revision')}
                data[key] = list(bucket.values())
            elif stamp >= clocks.get((day, key), ('', '')):
                data[key] = deepcopy(value)
                clocks[(day, key)] = stamp
                sources[key] = {'feedback_id': row.get('id'), 'revision': row.get('revision')}
        latest[day] = {**row, 'date': day, 'data': data, 'field_sources': sources,
                       'exercise_updated_at': {identity: {attribute: clock[0]
                           for (clock_day, clock_identity, attribute), clock in exercise_clocks.items()
                           if clock_day == day and clock_identity == identity} for identity in exercises.get(day, {})},
                       'exercise_sources': {identity: [source for (source_day, source_identity, _), source
                           in exercise_sources.items() if source_day == day and source_identity == identity]
                           for identity in exercises.get(day, {})},
                       'source_feedback_ids': list(dict.fromkeys([
                           *prior.get('source_feedback_ids', []), row.get('id')]))}
    return latest
