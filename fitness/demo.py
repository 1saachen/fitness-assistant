"""Reproducible local demo data helpers."""

import json
from pathlib import Path

from pydantic import ValidationError

from .models import Profile
from .storage import Store


class DemoDataError(Exception):
    """Raised when demo data cannot be safely loaded or reset."""


def initialize_demo_profile(store: Store, profile_path: Path) -> dict:
    """Seed an empty store with one validated demo profile.

    Initialization is intentionally idempotent: an existing profile is left
    untouched so the command can be rerun safely during a demo.
    """
    existing = store.profile()
    if existing is not None:
        return {"status": "already_initialized", "version": existing["version"]}

    profile_path = Path(profile_path)
    if not profile_path.is_file():
        raise DemoDataError("演示档案文件不存在。")
    try:
        raw = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        raise DemoDataError("演示档案文件无法读取。") from None
    except json.JSONDecodeError:
        raise DemoDataError("演示档案 JSON 无效。") from None

    try:
        profile = Profile.model_validate(raw)
    except (TypeError, ValidationError):
        raise DemoDataError("演示档案无效。") from None

    saved = store.save_profile(profile.model_dump(mode="json"), expected_version=0)
    return {"status": "initialized", "version": saved["version"]}


def reset_runtime_data(db_path: Path) -> dict:
    """Remove only the SQLite database and its WAL/SHM sidecar files."""
    db_path = Path(db_path)
    paths = (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm"))
    removed = 0
    for path in paths:
        if not path.exists():
            continue
        if not path.is_file() and not path.is_symlink():
            raise DemoDataError(f"运行数据路径不是文件，未执行重置：{path}")
        try:
            path.unlink()
        except OSError as exc:
            raise DemoDataError(f"无法删除运行数据文件：{path}") from exc
        removed += 1
    return {"removed": removed}
