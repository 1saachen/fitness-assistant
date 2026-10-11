"""Validated user facts and generated drafts. Null always means unknown."""

from datetime import date as Date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(max_length=2000)]
Short = Annotated[str, Field(max_length=200)]
KnowledgeTitle = Annotated[str, Field(max_length=300)]
VideoTitle = Annotated[str, Field(max_length=500)]
Mode = Literal["demo", "live"]
Equipment = Literal["bodyweight", "dumbbell", "barbell", "machine"]
KnowledgeCollection = Literal["training", "fat_loss", "supplements", "sleep_recovery"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


class Personal(Contract):
    age_years: int = Field(ge=18, le=100)
    sex: Short | None = None
    height_cm: float = Field(ge=100, le=250)
    weight_kg: float = Field(ge=25, le=350)
    weight_measured_on: Date | None = None
    body_fat_percent: float | None = Field(default=None, gt=0, lt=75)
    body_fat_source: Short | None = None
    body_fat_measurement_method: Short | None = None
    body_fat_measured_on: Date | None = None


class Goals(Contract):
    primary: Literal["fat_loss", "muscle_gain", "general_health"]
    secondary: list[Short] = Field(default_factory=list, max_length=10)
    deadline_negotiable: bool = True
    target_date: Date | None = None
    target_weight_kg: float | None = Field(default=None, ge=25, le=350)
    target_body_fat_percent: float | None = Field(default=None, gt=0, lt=75)


class Training(Contract):
    experience_years: float | None = Field(default=None, ge=0, le=80)
    available_sessions_per_week: int | None = Field(default=None, ge=1, le=6)
    session_duration_minutes: int | None = Field(default=None, ge=20, le=180)
    gym_access: bool | None = None
    available_equipment: list[Equipment] | None = Field(default=None, max_length=4)
    preferred_weekdays: list[int] | None = Field(default=None, max_length=6)
    current_routine: Text | None = None

    @model_validator(mode="after")
    def valid_weekdays(self):
        if self.preferred_weekdays is not None:
            if len(set(self.preferred_weekdays)) != len(self.preferred_weekdays):
                raise ValueError("训练日期不能重复")
            if any(day < 0 or day > 6 for day in self.preferred_weekdays):
                raise ValueError("星期必须在 0（周一）到 6（周日）之间")
            if len(self.preferred_weekdays) != self.available_sessions_per_week:
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


class Supplements(Contract):
    budget_separate_from_food: bool = True
    budget: Budget = Field(default_factory=Budget)
    current_products: list[Short] | None = Field(default=None, max_length=30)


class Health(Contract):
    exercise_limiting_conditions_status: Literal[
        "none_known_self_reported", "unknown", "has_conditions"
    ] = "unknown"
    exercise_limiting_conditions_details: Text | None = None
    medications: Text | None = None


class Recovery(Contract):
    usual_sleep_hours: float | None = Field(default=None, ge=0, le=24)
    sleep_schedule: Text | None = None


class Profile(Contract):
    schema_version: Literal[1] = 1
    source: Short = "user_entered"
    profile_status: Literal["incomplete", "complete"] = "incomplete"
    personal: Personal
    goals: Goals
    training: Training = Field(default_factory=Training)
    nutrition: Nutrition = Field(default_factory=Nutrition)
    supplements: Supplements = Field(default_factory=Supplements)
    health: Health = Field(default_factory=Health)
    recovery: Recovery = Field(default_factory=Recovery)
    daily_activity_level: Short | None = None


class Exercise(Contract):
    exercise_id: Short
    sets: int = Field(ge=1, le=5)
    reps_min: int = Field(ge=3, le=20)
    reps_max: int = Field(ge=3, le=20)
    rest_seconds: int = Field(ge=30, le=240)
    name: Short = ""

    @model_validator(mode="after")
    def valid_reps(self):
        if self.reps_min > self.reps_max:
            raise ValueError("次数下限不能超过上限")
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


class NutritionPlan(Contract):
    approach: Text
    meal_options: list[MealOption] = Field(min_length=1, max_length=5)
    budget_note: Text


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
    food_summary: Text | None = None
    diet_followed_plan: bool | None = None
    sleep_hours: float | None = Field(default=None, ge=0, le=24)
    sleep_date: Date | None = None
    fatigue: Short | None = None
    weight_kg: float | None = Field(default=None, ge=25, le=350)
    intake_kcal: float | None = Field(default=None, ge=0, le=15000)
    uncertainties: list[Short] = Field(default_factory=list, max_length=15)


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
    mode: Mode


class ParseRequest(Contract):
    text: str = Field(min_length=1, max_length=4000)
    date: Date
    mode: Mode


class FeedbackConfirm(Contract):
    data: FeedbackData
    expected_revision: int = Field(ge=0)


class ModeRequest(Contract):
    mode: Mode
