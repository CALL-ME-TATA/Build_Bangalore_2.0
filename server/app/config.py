"""Settings read from environment variables (CONTRACT section 8).

`.env` is loaded with python-dotenv by `get_settings`. Secrets are never logged: `Settings.__repr__` masks them.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Mapping

STT_MODEL = "prisma-v3.0"
TTS_MODEL = "timbre-v3.0"

_SECRET_FIELDS = {"gnani_api_key", "ledger_key", "admin_token", "access_code"}


@dataclass
class Settings:
    gnani_api_key: str = ""
    gnani_base_url: str = "https://api.vachana.ai"
    stt_format: str = "transliterate"
    stt_language: str = "hi-IN"
    stt_partials: bool = True
    stt_min_silence_ms: int | None = None
    tts_voice: str = "Shivani"
    tts_language: str = "hi-IN"
    tts_sample_rate: int = 24000
    ledger_key: str = ""
    ledger_db: str = "data/khata.db"
    shop_tz: str = "Asia/Kolkata"
    confirm_above: int = 50000
    admin_token: str = ""
    access_code: str = ""
    host: str = "127.0.0.1"
    port: int = 8000

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        """Build settings from a mapping (default: os.environ). Empty values count as unset."""
        e = os.environ if env is None else env

        def get(name: str, default: str = "") -> str:
            value = e.get(name)
            return default if value is None or value == "" else value

        silence = get("GNANI_STT_MIN_SILENCE_MS")
        return cls(
            gnani_api_key=get("GNANI_API_KEY"),
            gnani_base_url=get("GNANI_BASE_URL", cls.gnani_base_url).rstrip("/"),
            stt_format=get("GNANI_STT_FORMAT", cls.stt_format),
            stt_language=get("GNANI_STT_LANGUAGE", cls.stt_language),
            stt_partials=get("GNANI_STT_PARTIALS", "1").lower() not in ("0", "false", "no", "off"),
            stt_min_silence_ms=int(silence) if silence else None,
            tts_voice=get("GNANI_TTS_VOICE", cls.tts_voice),
            tts_language=get("GNANI_TTS_LANGUAGE", cls.tts_language),
            tts_sample_rate=int(get("GNANI_TTS_SAMPLE_RATE", str(cls.tts_sample_rate))),
            ledger_key=get("LEDGER_KEY"),
            ledger_db=get("LEDGER_DB", cls.ledger_db),
            shop_tz=get("SHOP_TZ", cls.shop_tz),
            confirm_above=int(get("CONFIRM_ABOVE", str(cls.confirm_above))),
            admin_token=get("ADMIN_TOKEN"),
            access_code=get("ACCESS_CODE"),
            host=get("HOST", cls.host),
            port=int(get("PORT", str(cls.port))),
        )

    @property
    def data_dir(self) -> Path:
        return Path(self.ledger_db).resolve().parent

    @property
    def key_path(self) -> Path:
        return self.data_dir / "ledger.key"

    @property
    def tts_cache_dir(self) -> Path:
        return self.data_dir / "tts_cache"

    def ws_base(self) -> str:
        """Base URL with the scheme mapped for WebSockets (http to ws, https to wss)."""
        base = self.gnani_base_url
        if base.startswith("https://"):
            return "wss://" + base[len("https://"):]
        if base.startswith("http://"):
            return "ws://" + base[len("http://"):]
        return base

    @property
    def stt_url(self) -> str:
        return self.ws_base() + "/stt/v3/stream"

    @property
    def tts_url(self) -> str:
        return self.ws_base() + "/api/v1/tts"

    def __repr__(self) -> str:
        parts = []
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name in _SECRET_FIELDS:
                value = "<set>" if value else "<unset>"
            parts.append(f"{f.name}={value!r}")
        return "Settings(" + ", ".join(parts) + ")"

    __str__ = __repr__


def get_settings() -> Settings:
    """Load `.env` (if present) and return settings from the environment."""
    from dotenv import load_dotenv

    load_dotenv(override=False)
    return Settings.from_env()
