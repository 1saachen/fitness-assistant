"""Validated user facts and generated drafts. Null always means unknown."""

from datetime import date as Date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(max_length=2000)]
Short = Annotated[str, Field(max_length=200)]
KnowledgeTitle = Annotated[str, Field(max_length=300)]
VideoTitle = Annotated[str, Field(max_length=500)]
Mode = Literal["live"]
Equipment = Literal["bodyweight", "dumbbell", "barbell", "machine"]
KnowledgeCollection = Literal["training", "fat_loss", "supplements", "sleep_recovery"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


class Personal(Contract):
    age_years: int | None = Field(default=None, ge=18, le=100)
    sex: Short | None = None
    height_cm: float | None = Field(default=None, ge=100, le=250)
    weight_kg: float | None = Field(default=None, ge=25, le=350)
    weight_measured_on: Date | None = None
    body_fat_percent: float | None = Field(default=None, gt=0, lt=75)
    body_fat_source: Short | None = None
    body_fat_measurement_method: Short | None = None
    body_fat_measured_on: Date | None = None


class Goals(Contract):
    primary: Literal["fat_loss", "muscle_gain", "general_health"] | None = None
    secondary: list[Short] = Field(default_factory=list, max_length=10)
    deadline_negotiable: bool | None = None
    target_date: Date | None = None
    target_weight_kg: float | None = Field(default=None, ge=25, le=350)
    target_body_fat_percent: float | None = Field(default=None, gt=0, lt=75)


class StrengthBaseline(Contract):
    squat_1rm_kg: float | None = Field(default=None, gt=0, le=1000)
    bench_press_1rm_kg: float | None = Field(default=None, gt=0, le=1000)
    deadlift_1rm_kg: float | None = Field(default=None, gt=0, le=1000)
    pull_up_max_reps: int | None = Field(default=None, ge=0, le=200)
    recorded_on: Date | None = None
    notes: Text | None = None


class Training(Contract):
    experience_years: float | None = Field(default=None, ge=0, le=80)
    available_sessions_per_week: int | None = Field(default=None, ge=1, le=6)
    training_frequency: Short | None = None
    session_duration_minutes: int | None = Field(default=None, ge=20, le=180)
    gym_access: bool | None = None
    available_equipment: list[Equipment] | None = Field(default=None, max_length=4)
    preferred_weekdays: list[int] | None = Field(default=None, max_length=6)
    current_routine: Text | None = None
    usual_training_time: Short | None = None
    strength_baseline: StrengthBaseline = Field(default_factory=StrengthBaseline)

    @model_validator(mode="after")
    def valid_weekdays(self):
        if self.training_frequency is not None and not self.training_frequency.strip():
            raise ValueError("训练频率不能为空")
        if self.preferred_weekdays is not None:
            if len(set(self.preferred_weekdays)) != len(self.preferred_weekdays):
                raise ValueError("训练日期不能重复")
            if any(day < 0 or day > 6 for day in self.preferred_weekdays):
                raise ValueError("星期必须在 0（周一）到 6（周日）之间")
            if (self.available_sessions_per_week is not None
                    and len(self.preferred_weekdays) != self.available_sessions_per_week):
                raise ValueError("选择的训练日数量需要与每周训练次数一致")
        return self


class Budget(Contract):
    amount: float | None = Field(default=None, ge=0, le=100000)
    currency: Literal["CNY"] = "CNY"
    period: Literal["day", "week", "month"] | None = None
    approximate: bool = True


class Nutrition(Contract):
    primary_meal_source: Short | None = None
    occasional_meal_sources: list[Short] = Field(default_factory=list, max_length=10)
    food_budget: Budget = Field(default_factory=Budget)
    food_allergy_status: Literal["none_known_self_reported", "unknown", "has_allergies"] = "unknown"
    food_allergy_details: Text | None = None
    food_intolerances: Text | None = None
    other_dietary_restrictions: Text | None = None
    food_preferences: Text | None = None
    disliked_foods: Text | None = None


class Supplements(Contract):
    budget_separate_from_food: bool = True
    budget: Budget = Field(default_factory=Budget)
    current_products: list[Short] | None = Field(default=None, max_length=30)


class Health(Contract):
    exercise_limiting_conditions_status: Literal[
        "none_known_self_reported", "unknown", "has_conditions"
    ] = "unknown"
    exercise_limiting_conditions_details: Text | None = None
    medications_status: Literal["none_known_self_reported", "unknown", "taking"] = "unknown"
    medications: Text | None = None


class Recovery(Contract):
    usual_sleep_hours: float | None = Field(default=None, ge=0, le=24)
    sleep_schedule: Text | None = None


class Profile(Contract):
    schema_version: Literal[1] = 1
    source: Short = "user_entered"
    profile_status: Literal["incomplete", "complete"] = "incomplete"
    personal: Personal = Field(default_factory=Personal)
    goals: Goals = Field(default_factory=Goals)
    training: Training = Field(default_factory=Training)
    nutrition: Nutrition = Field(default_factory=Nutrition)
    supplements: Supplements = Field(default_factory=Supplements)
    health: Health = Field(default_factory=Health)
    recovery: Recovery = Field(default_factory=Recovery)
    daily_activity_level: Short | None = None


class Exercise(Contract):
    exercise_id: Short | None = None
    sets: int = Field(ge=1, le=5)
    reps_min: int = Field(ge=3, le=20)
    reps_max: int = Field(ge=3, le=20)
    rest_seconds: int = Field(ge=30, le=240)
    weight_kg: float | None = Field(default=None, ge=0, le=1000)
    target_rpe: float | None = Field(default=None, ge=5, le=10)
    name: Short = ""
    equipment: list[Equipment] | None = Field(default=None, max_length=4)
    notes: Text = ""

    @model_validator(mode="after")
    def ensure_identity(self):
        if not self.exercise_id:
            if not self.name:
                raise ValueError("动作需要名称或已有标识")
            import hashlib
            import unicodedata
            normalized = "".join(unicodedata.normalize("NFKC", self.name).casefold().split())
            self.exercise_id = "custom_" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]
        return self

    @model_validator(mode="after")
    def valid_reps(self):
        if self.reps_min > self.reps_max:
            raise ValueError("次数下限不能超过上限")
        if self.target_rpe is not None and self.target_rpe * 2 != round(self.target_rpe * 2):
            raise ValueError("目标RPE需以0.5为步进")
        return self


class PlanDay(Contract):
    day_index: int = Field(ge=0, le=6)
    label: Short
    kind: Literal["training", "rest"]
    exercises: list[Exercise] = Field(default_factory=list, max_length=8)
    estimated_minutes: int = Field(default=0, ge=0, le=180)


class MealOption(Contract):
    meal: Short
    suggestions: list[Short] = Field(min_length=1, max_length=8)
    estimated_kcal: int | None = Field(default=None, ge=0, le=5000)
    protein_g: int | None = Field(default=None, ge=0, le=500)
    fat_g: int | None = Field(default=None, ge=0, le=300)
    carbs_g: int | None = Field(default=None, ge=0, le=800)
    estimated_cost_cny: float | None = Field(default=None, ge=0, le=1000)
    alternatives: list[Short] = Field(default_factory=list, max_length=8)


class NutritionTargets(Contract):
    calories_kcal: int = Field(ge=800, le=10000)
    protein_g: int = Field(ge=20, le=500)
    fat_g: int = Field(ge=10, le=300)
    carbs_g: int = Field(ge=20, le=1000)
    method: Short
    assumptions: list[Short] = Field(default_factory=list, max_length=10)
    confidence: Literal["low", "medium", "high"] = "low"


class NutritionPlan(Contract):
    approach: Text
    meal_options: list[MealOption] = Field(min_length=1, max_length=5)
    budget_note: Text
    daily_targets: NutritionTargets | None = None
    questions: list[Short] = Field(default_factory=list, max_length=10)


class KnowledgeVideo(Contract):
    bvid: Short | None = None
    title: VideoTitle
    url: Text
    published_at: Short | None = None


class KnowledgeCitation(Contract):
    id: Short
    title: KnowledgeTitle
    excerpt: Text
    creator_name: Short
    collection: KnowledgeCollection
    videos: list[KnowledgeVideo] = Field(default_factory=list, max_length=20)
    matched_issues: list[Short] = Field(default_factory=list, max_length=20)


class StrategySnapshot(Contract):
    id: Short
    title: Short
    summary: Text
    action_rules: list[Text] = Field(default_factory=list, max_length=20)
    knowledge_item_ids: list[Short] = Field(default_factory=list, max_length=100)


class PlanData(Contract):
    title: Short
    summary: Text
    days: list[PlanDay] = Field(min_length=7, max_length=7)
    nutrition: NutritionPlan
    questions: list[Short] = Field(default_factory=list, max_length=15)
    source_ids: list[Short] = Field(default_factory=list, max_length=100)
    strategy_context: list[StrategySnapshot] = Field(default_factory=list, max_length=20)
    knowledge_context: list[KnowledgeCitation] = Field(default_factory=list, max_length=100)
    recovery_guidance: list[Short] = Field(default_factory=list, max_length=8)
    supplement_guidance: list[Short] = Field(default_factory=list, max_length=8)


class FeedbackData(Contract):
    date: Date
    training_summary: Text | None = None
    training_completed: bool | None = None
    exercise_results: list["ExerciseResult"] = Field(default_factory=list, max_length=20)
    food_summary: Text | None = None
    diet_followed_plan: bool | None = None
    sleep_hours: float | None = Field(default=None, ge=0, le=24)
    sleep_date: Date | None = None
    fatigue: Short | None = None
    weight_kg: float | None = Field(default=None, ge=25, le=350)
    intake_kcal: float | None = Field(default=None, ge=0, le=15000)
    meal_to_plan: Short | None = None
    meal_conditions: Text | None = None
    available_foods: Text | None = None
    desired_foods: Text | None = None
    already_eaten: Text | None = None
    uncertainties: list[Short] = Field(default_factory=list, max_length=15)


class ExerciseSet(Contract):
    reps: int = Field(gt=0, strict=True)
    weight_kg: float | None = Field(default=None, ge=0, le=1000)
    rpe: float | None = Field(default=None, ge=1, le=10)
    completed: bool | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def valid_set_rpe(self):
        if self.rpe is not None and self.rpe * 2 != round(self.rpe * 2):
            raise ValueError("实际RPE需以0.5为步进")
        return self


class ExerciseResult(Contract):
    exercise_id: Short = Field(min_length=1)
    exercise_name: Short | None = Field(default=None, min_length=1)
    session_id: Short | None = Field(default=None, min_length=1)
    weight_kg: float | None = Field(default=None, ge=0, le=1000)
    rpe: float | None = Field(default=None, ge=1, le=10)
    sets: list[ExerciseSet] = Field(default_factory=list, max_length=100)
    form_notes: Text | None = Field(default=None, min_length=1)
    goal_completed: bool | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def valid_result(self):
        if (self.weight_kg is None and self.rpe is None and not self.sets
                and self.form_notes is None and self.goal_completed is None):
            raise ValueError("动作反馈至少记录重量、RPE、逐组表现、动作质量或目标状态")
        if self.rpe is not None and self.rpe * 2 != round(self.rpe * 2):
            raise ValueError("实际RPE需以0.5为步进")
        return self


class AdviceExplanation(Contract):
    issue: Short
    facts: list[Short] = Field(default_factory=list, max_length=10)
    rule: Text
    history: list[Short] = Field(default_factory=list, max_length=8)
    knowledge_ids: list[Short] = Field(default_factory=list, max_length=20)


class AdviceData(Contract):
    summary: Text
    suggestions: list[Short] = Field(min_length=1, max_length=8)
    source_ids: list[Short] = Field(default_factory=list, max_length=100)
    knowledge_context: list[KnowledgeCitation] = Field(default_factory=list, max_length=100)
    explanations: list[AdviceExplanation] = Field(default_factory=list, max_length=10)


class ProfileSave(Contract):
    profile: Profile
    expected_version: int = Field(ge=0)


class PlanRequest(Contract):
    start_date: Date
    mode: Mode = "live"


class ParseRequest(Contract):
    text: str = Field(min_length=1, max_length=4000)
    date: Date
    mode: Mode = "live"


class FeedbackConfirm(Contract):
    data: FeedbackData
    expected_revision: int = Field(ge=0)


class ModeRequest(Contract):
    mode: Mode = "live"


class NutritionPlanRequest(Contract):
    date: Date
    feedback_id: Short | None = None
    meal: Short | None = None
    conditions: Text | None = None
    available_foods: Text | None = None
    desired_foods: Text | None = None
    already_eaten: Text | None = None
    budget_amount: float | None = Field(default=None, ge=0, le=1000)
    mode: Mode = "live"


class NutritionMemoryPreviewRequest(Contract):
    text: Text
