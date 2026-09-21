import pytest


@pytest.fixture
def profile_data():
    """Synthetic test profile, independent from the user's local example."""
    return {
        "personal": {"age_years": 26, "height_cm": 172, "weight_kg": 73},
        "goals": {"primary": "fat_loss", "secondary": ["maintain_strength"]},
        "training": {
            "experience_years": 1,
            "available_sessions_per_week": 3,
            "session_duration_minutes": 40,
            "gym_access": False,
            "available_equipment": ["dumbbell", "bodyweight"],
        },
        "nutrition": {
            "primary_meal_source": "school_cafeteria",
            "food_budget": {"amount": 35, "period": "day"},
            "food_allergy_status": "none_known_self_reported",
        },
        "health": {"exercise_limiting_conditions_status": "none_known_self_reported"},
    }
