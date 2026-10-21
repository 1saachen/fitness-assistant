"""Merge confirmed daily facts without letting missing fields erase prior reports."""

from copy import deepcopy


def merge_feedback_days(rows):
    latest = {}
    for row in sorted(rows, key=lambda r: (str(r.get('fact_updated_at') or r.get('created_at') or ''),
                                          str(r.get('id') or ''))):
        if row.get('status') not in {None, 'confirmed'}:
            continue
        day = str(row.get('date') or (row.get('data') or {}).get('date') or '')
        data = latest.get(day, {}).get('data', {}).copy()
        data.update({key: deepcopy(value) for key, value in (row.get('data') or {}).items() if value is not None})
        latest[day] = {**row, 'date': day, 'data': data}
    return latest
