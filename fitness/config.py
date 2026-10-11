"""Local configuration; no dependency on another project."""

import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    db_path: Path = field(default_factory=lambda: ROOT / "data/local/fitness.sqlite3")
    example_path: Path = field(default_factory=lambda: ROOT / "data/examples/demo-profile.json")
    api_key: str = field(default="", repr=False)
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com"
    timezone: str = "Asia/Shanghai"
    timeout_seconds: float = 60
    max_steps: int = 5
    live_enabled: bool = False
    max_request_bytes: int = 128_000
    max_response_bytes: int = 128_000
    max_tool_calls: int = 1

    def __post_init__(self):
        if type(self.live_enabled) is not bool:
            raise ValueError("live_enabled must be boolean")
        if not isinstance(self.api_key, str) or not self.api_key.isascii() or any(
            ord(char) < 32 or ord(char) == 127 for char in self.api_key
        ):
            raise ValueError("invalid API key format")
        if not math.isfinite(self.timeout_seconds) or not (0 < self.timeout_seconds <= 300):
            raise ValueError("timeout_seconds must be finite and between 0 and 300")
        if type(self.max_steps) is not int or not (1 <= self.max_steps <= 20):
            raise ValueError("max_steps must be between 1 and 20")
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password or not parsed.netloc:
            raise ValueError("base_url must be an http(s) URL without credentials")
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("remote endpoints require HTTPS")
        if parsed.query or parsed.fragment:
            raise ValueError("base_url must not include query or fragment")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:-]{0,199}", self.model):
            raise ValueError("invalid model identifier")
        for bound in (self.max_request_bytes, self.max_response_bytes):
            if type(bound) is not int or not 1024 <= bound <= 1_000_000:
                raise ValueError("request and response limits must be between 1024 and 1000000")
        if self.max_tool_calls != 1:
            raise ValueError("only one tool call per reply is supported")

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
            timeout_seconds=float(os.getenv("FITNESS_TIMEOUT_SECONDS", "60")),
            max_steps=int(os.getenv("FITNESS_MAX_STEPS", "5")),
            live_enabled=os.getenv("FITNESS_LIVE_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"},
        )
