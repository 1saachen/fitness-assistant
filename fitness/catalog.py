from dataclasses import dataclass


@dataclass(frozen=True)
class ExerciseInfo:
    id: str; name: str; equipment: str; muscle_group: str; estimated_minutes: int

CATALOG = [
    ExerciseInfo('barbell_bench_press','杠铃卧推','barbell','胸/三头',10),
    ExerciseInfo('squat','深蹲','barbell','腿/臀',12), ExerciseInfo('deadlift','硬拉','barbell','背/臀腿',12),
    ExerciseInfo('lat_pulldown','高位下拉','machine','背',9), ExerciseInfo('seated_row','坐姿划船','machine','背',9),
    ExerciseInfo('dumbbell_bench_press','哑铃卧推','dumbbell','胸',10), ExerciseInfo('dumbbell_row','单臂哑铃划船','dumbbell','背',9),
    ExerciseInfo('leg_press','腿举','machine','腿',10), ExerciseInfo('romanian_deadlift','罗马尼亚硬拉','barbell','臀腿',10),
    ExerciseInfo('plank','平板支撑','bodyweight','核心',5),
]
BY_ID = {x.id:x for x in CATALOG}
def available(equipment):
    if not equipment: return CATALOG
    return [x for x in CATALOG if x.equipment in equipment or x.equipment=='bodyweight']
