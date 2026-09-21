"""Local configuration; no dependency on another project."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    db_path: Path = field(default_factory=lambda: ROOT / "data/local/fitness.sqlite3")
    example_path: Path = field(default_factory=lambda: ROOT / "data/examples/user-profile.json")
    api_key: str = field(default="", repr=False)
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com"
    timezone: str = "Asia/Shanghai"
    timeout_seconds: float = 60
    max_steps: int = 5

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / ".env", override=False)
        base = os.getenv("FITNESS_BASE_URL", "https://api.deepseek.com").rstrip("/")
        key = os.getenv("FITNESS_API_KEY", "")
        # Never send a provider-specific key to an unrelated configured endpoint.
        if not key and base in {"https://api.deepseek.com", "https://api.deepseek.com/v1"}:
            key = os.getenv("DEEPSEEK_API_KEY", "")
        return cls(
            db_path=Path(os.getenv("FITNESS_DB_PATH", str(ROOT / "data/local/fitness.sqlite3"))),
            api_key=key,
            model=os.getenv("FITNESS_MODEL", "deepseek-chat"),
            base_url=base,
            timezone=os.getenv("FITNESS_TIMEZONE", "Asia/Shanghai"),
        )
