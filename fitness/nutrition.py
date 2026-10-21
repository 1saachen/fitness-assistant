"""Compatibility facade for the typed nutrition-planning sub-agent."""

from .models import Profile
from .nutrition_agent import NutritionPlannerAgent


def nutrition_plan(profile: Profile):
    planned = NutritionPlannerAgent().plan(profile)
    return planned, list(planned.questions)
