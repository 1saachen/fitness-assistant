"""Independent validation of model wording; deterministic health guardrails."""

import re
import unicodedata
from datetime import date

from pydantic import BaseModel, ValidationError

from .models import AdviceData, FeedbackData, PlanData


class SafetyError(ValueError):
    def __init__(self, reason_code: str):
        self.reason_code = reason_code
        super().__init__(reason_code)


UNSAFE_PATTERNS = (
    r"(?:你|您)(?:已|可能|确诊)?(?:患有|得了|患上|是).{0,15}(?:病|症|糖尿|癌)",
    r"(?:诊断为|确诊为|治疗方案|处方药|停药|自行用药|加药|换药)",
    r"(?:确诊|禁食|断食|催吐|泻药|脱水减重)",
    r"(?:药|medication).{0,10}(?:减半|加倍|增量|减量|停用)",
    r"(?:肌酸|咖啡因|补剂|药|creatine|caffeine).{0,15}(?:\d+|[一二三四五六七八九十两]+)\s*(?:毫克|克|片|粒|mg|grams?|g\b)",
    r"(?:take|consume|dose).{0,20}(?:one|two|three|four|five|six|seven|eight|nine|ten).{0,5}(?:grams?|mg|pills?)",
    r"(?:服用|摄入|补充|吃|注射|take|dose|consume).{0,20}\d+(?:\.\d+)?\s*(?:毫克|克|片|粒|mg|g\b|ml|iu\b)",
    r"(?:每天|每日|daily).{0,15}(?:服用|补充|take).{0,15}(?:肌酸|咖啡因|补剂|药|creatine|caffeine)",
    r"\d+\s*(?:组|次|sets?\b|reps?\b)|(?:每组|sets?\s+of)\s*\d+",
    r"(?:深蹲|硬拉|卧推|训练|squat|deadlift|bench).{0,15}\d+\s*(?:公斤|kg|分钟|minutes)",
    r"(?:胸痛|晕厥|呼吸困难).{0,10}(?:继续|坚持|硬撑|不用就医)",
    r"(?:忍痛|带伤训练|不用看医生|忽略疼痛|不需要就医)",
    r"(?:you\s+(?:have|suffer\s+from)|diagnosed\s+with).{0,30}(?:diabetes|disease|cancer|syndrome)",
    r"you\s+are\s+(?:diabetic|hypertensive|pregnant)",
    r"(?:take|consume).{0,15}(?:creatine|caffeine|supplement).{0,15}(?:daily|every\s+day)",
    r"(?:stop|change|increase|decrease).{0,20}(?:medication|medicine|dose)",
    r"(?:train|exercise|continue).{0,30}(?:through|despite|with).{0,15}(?:chest\s+pain|fainting)",
)
UNSAFE = re.compile("|".join(UNSAFE_PATTERNS), re.IGNORECASE)
QUANTIFIED = re.compile(r"\d+(?:\.\d+)?|[零一二三四五六七八九十两]+(?=\s*(?:公斤|千克|小时|克|千卡))")
PERSONAL_CLAIM = re.compile(
    r"(?:证明|导致|造成|使得|因而|因果)|caused\s+by|proves?\s+(?:that|the)|"
    r"(?:建议|方案|补剂).{0,15}(?:让你|让您|使你|使您)|"
    r"(?:你|您|your).{0,25}(?:减重|减脂成功|恢复改善|体重减少|体重下降|weight\s+loss)|"
    r"(?:服用|执行|采纳|按建议).{0,15}(?:后|以后).{0,15}(?:改善|下降|增加|有效)",
    re.IGNORECASE,
)
PERSONAL_HEALTH_FACT = re.compile(
    r"(?:你|您|用户).{0,12}(?:正在服用|在服用|服用|已怀孕|怀孕了|患|有.{0,8}(?:病|症))|"
    r"you\s+(?:are\s+(?:taking|pregnant)|take|have\s+.{0,15}(?:disease|diabetes|cancer))|"
    r"(?:华法林|阿司匹林|降压药|胰岛素|warfarin|aspirin|insulin)", re.IGNORECASE,
)
GENERIC_UNCERTAINTY = re.compile(
    r"(?:睡眠时长|睡眠日期|体重|体重日期|训练完成状态|训练记录|饮食执行状态|食物份量|摄入热量|"
    r"食物记录|疲劳程度|反馈日期|过敏信息)(?:未提供|不明确|不清楚|待确认|未知|存在歧义)"
    r"(?:[，,；;]?(?:需确认|请补充|未估算热量))?"
)


def _validated_wording(candidate, baseline, model_type, mutable):
    if not isinstance(baseline, model_type):
        raise SafetyError("invalid_baseline")
    if isinstance(candidate, BaseModel):
        candidate = candidate.model_dump(mode="json")
    if not isinstance(candidate, dict) or not candidate.keys() <= model_type.model_fields.keys():
        raise SafetyError("invalid_schema")
    source = baseline.model_dump(mode="json")
    for key, value in candidate.items():
        if key not in mutable and value != source[key]:
            raise SafetyError("immutable_field")
    try:
        result = model_type.model_validate({**source, **candidate}, strict=True)
    except (ValidationError, ValueError, TypeError):
        raise SafetyError("invalid_schema") from None
    trusted_wording = " ".join(
        " ".join(getattr(baseline, key)) if isinstance(getattr(baseline, key), list)
        else getattr(baseline, key) for key in mutable
    )
    trusted_numbers = set(QUANTIFIED.findall(unicodedata.normalize("NFKC", trusted_wording)))
    for key in mutable:
        values = getattr(result, key)
        for text in values if isinstance(values, list) else [values]:
            normalized = unicodedata.normalize("NFKC", text)
            normalized = "".join(char for char in normalized if unicodedata.category(char) != "Cf")
            if UNSAFE.search(normalized):
                raise SafetyError("unsafe_content")
            baseline_values = getattr(baseline, key)
            unchanged = text in baseline_values if isinstance(baseline_values, list) else text == baseline_values
            if not unchanged and (PERSONAL_CLAIM.search(normalized)
                                  or PERSONAL_HEALTH_FACT.search(normalized)
                                  or not set(QUANTIFIED.findall(normalized)) <= trusted_numbers):
                raise SafetyError("ungrounded_claim")
    return result


def validate_model_advice(candidate: dict | AdviceData, baseline: AdviceData) -> AdviceData:
    return _validated_wording(candidate, baseline, AdviceData, {"summary", "suggestions"})


def validate_model_plan(candidate: dict | PlanData, baseline: PlanData) -> PlanData:
    return _validated_wording(candidate, baseline, PlanData, {"summary"})


CHINESE_DIGITS = dict(zip("零一二三四五六七八九两", (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 2)))
NUMBER = r"(\d+(?:\.\d+)?|[零一二三四五六七八九十两]+)"


def _number(text):
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return float(text)
    if "十" in text:
        if text.count("十") != 1:
            return None
        left, right = text.split("十")
        if len(left) > 1 or len(right) > 1:
            return None
        return (CHINESE_DIGITS.get(left, 1) * 10) + CHINESE_DIGITS.get(right, 0)
    return CHINESE_DIGITS.get(text)


def _grounded_measurement(text, field, value):
    if re.search(r"(?:没睡|未睡|没有睡|希望|打算|计划|准备|如果|假如|可能|大约|左右)", text):
        return False
    patterns = {
        "sleep_hours": rf"(?:睡了|睡眠|睡)\s*{NUMBER}\s*个?\s*(?:小时|h\b)",
        "weight_kg": rf"(?:体重|weight)\s*(?:为|是|:|：)?\s*{NUMBER}\s*(?:公斤|千克|kg\b)",
        "intake_kcal": rf"(?:摄入|热量|intake)\s*(?:为|是|:|：)?\s*{NUMBER}\s*(?:千卡|大卡|kcal\b)",
    }
    found = [_number(match) for match in re.findall(patterns[field], text, flags=re.IGNORECASE)]
    # Multiple entries may refer to different days. Leave those for explicit correction.
    return len(found) == 1 and found[0] == value


def _grounded_boolean(text, field, value):
    if field == "training_completed":
        negative = r"(?:没练|未训练|跳过训练|未完成训练|没有完成训练|训练未完成)"
        positive = r"(?:完成训练|练完|训练完成)"
    else:
        negative = r"(?:没按计划吃|没有按计划吃|饮食没按计划|饮食没有按计划)"
        positive = r"(?:饮食按计划|按饮食计划|按计划吃)"
    has_negative = bool(re.search(negative, text))
    clean = re.sub(negative, "", text)
    has_positive = bool(re.search(positive, clean))
    if has_negative and has_positive:
        return False
    return has_positive if value is True else has_negative


_RESULT_NUMBER = r"(?<![\d.])(\d+(?:\.\d+)?)(?![\d.])"
_RESULT_WEIGHT = re.compile(_RESULT_NUMBER + r"\s*(?:kg(?![a-z])|公斤|千克)", re.IGNORECASE)
_RESULT_RPE = re.compile(r"(?:RPE\s*(?:为|是|:)?\s*|主观用力(?:为|是)?\s*)"
                         r"(\d+(?:\.\d+)?)(?![\d.])", re.IGNORECASE)
_NOT_ACTUAL = re.compile(
    r"计划|准备|打算|希望|预计|明天|后天|下次|将要|想要|想做|要做|尚未|没有做|没做|未做|没练|未练|没能|"
    r"\b(?:tomorrow|planned|planning|intend|will|next\s+time)\b", re.IGNORECASE)


def _result_completion(text, *, goal=False):
    target = r"\s*(?:目标|计划目标)" if goal else r"(?!\s*(?:目标|计划目标|训练))"
    negative = rf"(?:未完成|没有完成|没完成|未达到|没达到){target}"
    positive = rf"(?:完成|达到){target}"
    has_negative = bool(re.search(negative, text))
    has_positive = bool(re.search(positive, re.sub(negative, "", text)))
    if has_negative and has_positive:
        return None
    if has_negative:
        return False
    if has_positive:
        return True
    return None


def _one_result_number(pattern, text):
    values = {float(value) for value in pattern.findall(text)}
    return next(iter(values)) if len(values) == 1 else None


def _source_sets(segment):
    """Recognize explicit set notation only; absent values stay unknown."""
    headings = list(re.finditer(r"第\s*(\d+)\s*组", segment))
    if headings:
        if [int(match[1]) for match in headings] != list(range(1, len(headings) + 1)):
            return None
        records = []
        for index, match in enumerate(headings):
            end = headings[index + 1].start() if index + 1 < len(headings) else len(segment)
            part = segment[match.end():end]
            reps = re.findall(r"(?<![\d./])(\d+)\s*次", part)
            if len(reps) != 1:
                return None
            records.append({"reps": int(reps[0]), "weight_kg": _one_result_number(_RESULT_WEIGHT, part),
                            "rpe": _one_result_number(_RESULT_RPE, part),
                            "completed": _result_completion(part)})
        return records
    sequences = re.findall(r"(?<![\d./])(\d+(?:\s*/\s*\d+)+)\s*次", segment)
    uniform = re.findall(r"(\d+)\s*组\s*[,,:]?\s*(?:每组)?\s*(\d+)\s*次", segment)
    if len(sequences) == 1 and not uniform:
        if segment.count("次") != 1:
            return None
        reps = [int(value.strip()) for value in sequences[0].split("/")]
    elif len(uniform) == 1 and not sequences:
        count, number = map(int, uniform[0])
        if count > 100:
            return None
        reps = [number] * count
    elif not sequences and not uniform:
        singles = re.findall(r"(?<![\d./])(\d+)\s*次", segment)
        if len(singles) != 1 or re.search(r"(?:[2-9]|\d{2,})\s*组", segment):
            return None
        reps = [int(singles[0])]
    else:
        return None
    if len(reps) > 100:
        return None
    weights = {float(value) for value in _RESULT_WEIGHT.findall(segment)}
    if len(weights) > 1:
        return None
    common_weight = next(iter(weights)) if weights else None
    records = [{"reps": value, "weight_kg": common_weight, "rpe": None, "completed": None}
               for value in reps]
    score_sequences = re.findall(r"RPE\s*(\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)+)",
                                 segment, re.IGNORECASE)
    if score_sequences:
        scores = [float(value.strip()) for value in score_sequences[0].split("/")]
        if len(score_sequences) != 1 or len(scores) != len(records):
            return None
        for record, score in zip(records, scores):
            record["rpe"] = score
        return records
    scores = list(_RESULT_RPE.finditer(segment))
    if len(scores) == 1:
        score = scores[0]
        qualifier = segment[max(0, score.start() - 12):score.start()]
        if re.search(r"(?:末组|最后一组|最后1组)\s*$", qualifier):
            records[-1]["rpe"] = float(score[1])
        elif len(records) == 1 or re.search(r"(?:每组|各组|所有组)\s*$", qualifier):
            for record in records:
                record["rpe"] = float(score[1])
    elif scores:
        # Multiple unassociated scores cannot be assigned to sets safely.
        return None
    return records


def _actual_exercise_segments(text, name, names):
    pattern = "|".join(re.escape(value) for value in sorted(set(names), key=len, reverse=True) if value)
    mentions = list(re.finditer(pattern, text, re.IGNORECASE)) if pattern else []
    for index, match in enumerate(mentions):
        if match[0].casefold() != name.casefold():
            continue
        end = mentions[index + 1].start() if index + 1 < len(mentions) else len(text)
        # Include the clause prefix so "明天卧推" cannot become an actual record.
        prefix = re.split(r"[,;。!?\n]", text[:match.start()])[-1]
        segment = re.split(r"[。!?\n]", text[match.end():end])[0]
        if not _NOT_ACTUAL.search(prefix + segment):
            # Prefix words establish tense only. Their numbers and notes can
            # belong to a previous action, so they are never fact evidence.
            yield match[0] + segment


def _grounded_result(item, segment):
    if item.weight_kg is not None and _one_result_number(_RESULT_WEIGHT, segment) != item.weight_kg:
        return False
    if item.rpe is not None and _one_result_number(_RESULT_RPE, segment) != item.rpe:
        return False
    if item.form_notes is not None:
        note = unicodedata.normalize("NFKC", item.form_notes)
        position = segment.find(note)
        if position < 0 or re.search(r"(?:并非|不是|没有|未曾|不算|不够)\s*$",
                                     segment[max(0, position - 8):position]):
            return False
    if item.goal_completed is not None and _result_completion(segment, goal=True) is not item.goal_completed:
        return False
    if item.session_id is not None and item.session_id not in segment:
        return False
    if item.sets:
        source = _source_sets(segment)
        if source is None or len(source) != len(item.sets):
            return False
        for actual, grounded in zip(item.sets, source):
            if actual.reps != grounded["reps"]:
                return False
            for key in ("weight_kg", "rpe", "completed"):
                value = getattr(actual, key)
                if value is not None and value != grounded[key]:
                    return False
    return True


def _validate_exercise_results(items, text, exercise_names):
    import hashlib

    from .catalog import CATALOG

    known = {key: unicodedata.normalize("NFKC", value) for key, value in (exercise_names or {}).items()}
    names = [*known.values(), *(entry.name for entry in CATALOG),
             *(unicodedata.normalize("NFKC", item.exercise_name) for item in items if item.exercise_name)]
    seen = set()
    for item in items:
        name = known.get(item.exercise_id)
        if item.exercise_name:
            supplied_name = unicodedata.normalize("NFKC", item.exercise_name)
            if name and supplied_name != name:
                raise SafetyError("ungrounded_fact")
            if not name:
                normalized_name = "".join(supplied_name.casefold().split())
                custom_id = "custom_" + hashlib.sha256(normalized_name.encode("utf-8")).hexdigest()[:20]
                if custom_id != item.exercise_id:
                    raise SafetyError("ungrounded_fact")
                name = supplied_name
        key = (item.exercise_id, item.session_id)
        if not name or key in seen:
            raise SafetyError("ungrounded_fact")
        seen.add(key)
        segments = list(_actual_exercise_segments(text, name, names))
        if not any(_grounded_result(item, segment) for segment in segments):
            raise SafetyError("ungrounded_fact")


def validate_model_feedback(candidate: dict | FeedbackData, text: str, day: date,
                            baseline: FeedbackData, *, exercise_names: dict[str, str] | None = None) -> FeedbackData:
    """Validate a draft only. Explicit measurements need source-text evidence."""
    if not isinstance(baseline, FeedbackData) or baseline.date != day or not isinstance(text, str):
        raise SafetyError("invalid_baseline")
    if isinstance(candidate, FeedbackData):
        candidate = candidate.model_dump(mode="json")
    if not isinstance(candidate, dict) or not candidate.keys() <= FeedbackData.model_fields.keys():
        raise SafetyError("invalid_schema")
    source = baseline.model_dump(mode="json")
    for key in ("date", "sleep_date"):
        if key in candidate and candidate[key] != source[key]:
            raise SafetyError("immutable_field")
    for key in ("training_completed", "diet_followed_plan"):
        if key in candidate and candidate[key] is not None and type(candidate[key]) is not bool:
            raise SafetyError("invalid_schema")
    try:
        result = FeedbackData.model_validate({**source, **candidate})
    except (ValidationError, ValueError, TypeError):
        raise SafetyError("invalid_schema") from None
    normalized = unicodedata.normalize("NFKC", text)
    for key in ("training_summary", "food_summary", "fatigue"):
        value = getattr(result, key)
        if value is not None and value != getattr(baseline, key):
            if UNSAFE.search(unicodedata.normalize("NFKC", value)):
                raise SafetyError("unsafe_content")
            if value not in text:
                raise SafetyError("ungrounded_fact")
    for key in ("sleep_hours", "weight_kg", "intake_kcal"):
        value = getattr(result, key)
        if value != getattr(baseline, key) and (value is None or not _grounded_measurement(normalized, key, value)):
            raise SafetyError("ungrounded_fact")
    for key in ("training_completed", "diet_followed_plan"):
        value = getattr(result, key)
        if value != getattr(baseline, key) and (value is None or not _grounded_boolean(normalized, key, value)):
            raise SafetyError("ungrounded_fact")
    original_results = [item.model_dump(mode="json") for item in baseline.exercise_results]
    parsed_results = [item.model_dump(mode="json") for item in result.exercise_results]
    if parsed_results != original_results:
        _validate_exercise_results(result.exercise_results, normalized, exercise_names)
    if not set(baseline.uncertainties) <= set(result.uncertainties):
        raise SafetyError("immutable_field")
    for uncertainty in result.uncertainties:
        if (uncertainty not in baseline.uncertainties and uncertainty not in text
                and not GENERIC_UNCERTAINTY.fullmatch(uncertainty)):
            raise SafetyError("ungrounded_fact")
    return result


def _mapping(value):
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value if isinstance(value, dict) else {}


def has_urgent_symptoms(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", str(text)).lower()
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Cf")
    return any(word in normalized for word in ("胸痛", "胸闷", "晕厥", "呼吸困难", "剧痛", "chest pain",
                                               "fainting", "shortness of breath", "severe pain"))


def health_guardrails(profile, feedback=None, raw_text: str = "") -> list[str]:
    """Call before every demo/live plan or advice; never depend on provider readiness."""
    profile = _mapping(profile)
    health = profile.get("health") or {}
    warnings = []
    details = health.get("exercise_limiting_conditions_details")
    if health.get("exercise_limiting_conditions_status") == "has_conditions" or details:
        warnings.append("存在疾病、损伤或运动限制时，先咨询医疗专业人员评估适合的活动与限制。")
    if health.get("medications_status") == "taking" or health.get("medications"):
        warnings.append("正在用药时，请向医生或药师确认运动与补剂相互作用，不自行调整用药。")
    text = str(profile).lower() + str(_mapping(feedback)).lower() + raw_text.lower()
    if any(word in text for word in ("怀孕", "孕期", "妊娠", "pregnan", "产后", "postpartum")):
        warnings.append("孕期或产后请先由产科及医疗专业人员评估运动与营养安排。")
    if has_urgent_symptoms(text):
        warnings.append("出现胸痛、晕厥、呼吸困难等异常症状时，立即停止训练并及时就医；严重时联系急救。")
    return warnings
