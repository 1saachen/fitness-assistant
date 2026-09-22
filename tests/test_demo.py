import json
import subprocess
import sys
from pathlib import Path

import pytest

from fitness.demo import DemoDataError, initialize_demo_profile, reset_runtime_data
from fitness.storage import Store


def demo_profile_data():
    return {
        "personal": {"age_years": 22, "height_cm": 180, "weight_kg": 80, "body_fat_percent": 20},
        "goals": {"primary": "fat_loss", "secondary": ["maintain_strength"]},
        "training": {
            "experience_years": 2,
            "available_sessions_per_week": 4,
            "session_duration_minutes": 60,
            "gym_access": True,
            "available_equipment": ["barbell", "dumbbell", "machine"],
            "preferred_weekdays": [0, 2, 4, 6],
        },
        "nutrition": {
            "primary_meal_source": "school_cafeteria",
            "occasional_meal_sources": ["takeout", "quick_meals"],
            "food_budget": {"amount": 40, "period": "day"},
            "food_allergy_status": "none_known_self_reported",
        },
        "supplements": {"budget_separate_from_food": True},
        "health": {"exercise_limiting_conditions_status": "none_known_self_reported"},
        "recovery": {"usual_sleep_hours": 7},
        "profile_status": "complete",
    }


def test_initialize_demo_profile_seeds_empty_store_once(tmp_path):
    profile_path = tmp_path / "demo-profile.json"
    profile_path.write_text(json.dumps(demo_profile_data()), encoding="utf-8")
    store = Store(tmp_path / "local" / "fitness.sqlite3")

    result = initialize_demo_profile(store, profile_path)

    assert result == {"status": "initialized", "version": 1}
    saved = store.profile()
    assert saved["version"] == 1
    assert saved["data"]["personal"]["weight_kg"] == 80

    assert initialize_demo_profile(store, profile_path) == {
        "status": "already_initialized",
        "version": 1,
    }


def test_initialize_demo_profile_refuses_invalid_profile(tmp_path):
    profile_path = tmp_path / "demo-profile.json"
    profile_path.write_text(json.dumps({"personal": {}}), encoding="utf-8")

    with pytest.raises(DemoDataError, match="演示档案无效"):
        initialize_demo_profile(Store(tmp_path / "fitness.sqlite3"), profile_path)


def test_reset_runtime_data_removes_only_sqlite_runtime_files(tmp_path):
    db_path = tmp_path / "data" / "local" / "fitness.sqlite3"
    db_path.parent.mkdir(parents=True)
    db_path.write_text("database", encoding="utf-8")
    Path(str(db_path) + "-wal").write_text("wal", encoding="utf-8")
    Path(str(db_path) + "-shm").write_text("shm", encoding="utf-8")
    knowledge = tmp_path / "data" / "knowledge" / "baseline-strategies.json"
    knowledge.parent.mkdir(parents=True)
    knowledge.write_text("knowledge", encoding="utf-8")

    result = reset_runtime_data(db_path)

    assert result == {"removed": 3}
    assert not db_path.exists()
    assert not Path(str(db_path) + "-wal").exists()
    assert not Path(str(db_path) + "-shm").exists()
    assert knowledge.read_text(encoding="utf-8") == "knowledge"


def test_demo_cli_requires_reset_confirmation(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "fitness.demo_cli", "reset", "--db-path", str(tmp_path / "fitness.sqlite3")],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "--confirm" in result.stderr


def test_demo_cli_initializes_and_resets_an_explicit_database(tmp_path):
    profile_path = tmp_path / "demo-profile.json"
    profile_path.write_text(json.dumps(demo_profile_data()), encoding="utf-8")
    db_path = tmp_path / "runtime" / "fitness.sqlite3"

    initialized = subprocess.run(
        [
            sys.executable,
            "-m",
            "fitness.demo_cli",
            "init",
            "--db-path",
            str(db_path),
            "--profile-path",
            str(profile_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert initialized.returncode == 0
    assert json.loads(initialized.stdout) == {"status": "initialized", "version": 1}
    assert Store(db_path).profile()["data"]["personal"]["weight_kg"] == 80

    reset = subprocess.run(
        [
            sys.executable,
            "-m",
            "fitness.demo_cli",
            "reset",
            "--confirm",
            "--db-path",
            str(db_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert reset.returncode == 0
    assert json.loads(reset.stdout)["removed"] >= 1
    assert not db_path.exists()
