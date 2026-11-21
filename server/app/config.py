"""Settings read from environment variables (CONTRACT section 8).

`.env` is loaded with python-dotenv by `get_settings`. Secrets are never logged: `Settings.__repr__` masks them.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
STT_MODEL = "prisma-v3.0"
TTS_MODEL = "timbre-v3.0"

_SECRET_FIELDS = {"gnani_api_key", "ledger_key", "admin_token", "access_code", "llm_api_key",
                  "google_client_secret", "session_secret", "supabase_secret_key", "supabase_access_token",
                  "twilio_auth_token"}


def _flag(value: str) -> bool:
    return value.strip().lower() not in ("0", "false", "no", "off")


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
    confirm_new_customer: bool = True
    strict_save: bool = True  # STRICT_SAVE: the parser confirms a sentence holding a word it does not know
    max_amount: int = 9_999_999
    # Off by default for settings built in code (tests); `from_env` turns it on unless TTS_PREWARM=0.
    tts_prewarm: bool = False
    tts_prewarm_explicit: bool = False  # TTS_PREWARM was set in the environment (allows prewarm inside tests)
    web_dir: str = ""
    allowed_origins: str = ""  # ALLOWED_ORIGINS: extra browser origins for /ws/session, comma separated
    # Noise handling (CONTRACT 3.5): turn down what is clearly not the speaker; ask before saving a noisy turn.
    noise_trim: bool = True
    noise_trim_db: float = 16.0
    noise_confirm_db: float = 14.0  # 0 switches the confirmation off
    admin_token: str = ""
    access_code: str = ""
    # LLM fallback for sentences the rules refuse (app/llm.py). Empty key = rules only.
    llm_api_key: str = ""
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "qwen/qwen3.8-27b"  # fastest correct on Groq, 2026-11-21: ~140 ms median
    llm_reasoning_effort: str = "none"  # sent as reasoning_effort; empty = not sent (hosts without it)
    llm_timeout_s: float = 1.5
    # Google sign-in (app/auth.py). Both set = sign-in required for the khata; ALLOWED_EMAILS lists who gets in.
    google_client_id: str = ""
    google_client_secret: str = ""
    allowed_emails: str = ""
    session_secret: str = ""  # empty: a random key in data/session.key
    public_url: str = ""  # e.g. https://my-tunnel.trycloudflare.com when behind a tunnel; empty = the request's host
    # Kafka notifications (app/notify.py). Empty = off.
    kafka_bootstrap: str = ""
    kafka_topic: str = "khata.notifications"
    # Copy of every shop's ledger in a Supabase project (app/cloud_sync.py). URL and key both set = on.
    supabase_url: str = ""
    supabase_secret_key: str = ""  # SUPABASE_SECRET_KEY (sb_secret_...), else the legacy SUPABASE_SERVICE_ROLE_KEY
    supabase_access_token: str = ""  # optional personal access token: lets the server create missing tables
    cloud_sync_interval_s: int = 300
    # Reminder SMS through Twilio, sent by the Kafka consumer (app/sms.py, app/notify_worker.py).
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_messaging_service_sid: str = ""  # MG...; or TWILIO_FROM, a Twilio phone number
    twilio_from: str = ""
    twilio_allowed_to: str = ""  # numbers that may receive an SMS, comma separated; "*" = anyone; empty = nobody
    # A Twilio trial account sends only its predefined templates: set a template name (e.g. sms_appointment_reminders)
    # and it is sent as the body instead of the reminder text. Empty: the reminder text itself (paid accounts).
    twilio_trial_template: str = ""
    reminder_any_hour: bool = False  # REMINDER_ANY_HOUR=1: reminders at any hour, not only 09:00 to 20:00
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
            stt_partials=_flag(get("GNANI_STT_PARTIALS", "1")),
            stt_min_silence_ms=int(silence) if silence else None,
            tts_voice=get("GNANI_TTS_VOICE", cls.tts_voice),
            tts_language=get("GNANI_TTS_LANGUAGE", cls.tts_language),
            tts_sample_rate=int(get("GNANI_TTS_SAMPLE_RATE", str(cls.tts_sample_rate))),
            ledger_key=get("LEDGER_KEY"),
            ledger_db=get("LEDGER_DB", cls.ledger_db),
            shop_tz=get("SHOP_TZ", cls.shop_tz),
            confirm_above=int(get("CONFIRM_ABOVE", str(cls.confirm_above))),
            confirm_new_customer=_flag(get("CONFIRM_NEW_CUSTOMER", "1")),
            strict_save=_flag(get("STRICT_SAVE", "1")),
            max_amount=int(get("MAX_AMOUNT", str(cls.max_amount))),
            tts_prewarm=_flag(get("TTS_PREWARM", "1")),
            tts_prewarm_explicit=bool(get("TTS_PREWARM")),
            web_dir=get("WEB_DIR"),
            allowed_origins=get("ALLOWED_ORIGINS"),
            noise_trim=_flag(get("NOISE_TRIM", "1")),
            noise_trim_db=float(get("NOISE_TRIM_DB", str(cls.noise_trim_db))),
            noise_confirm_db=float(get("NOISE_CONFIRM_DB", str(cls.noise_confirm_db))),
            admin_token=get("ADMIN_TOKEN"),
            access_code=get("ACCESS_CODE"),
            llm_api_key=get("LLM_API_KEY"),
            llm_base_url=get("LLM_BASE_URL", cls.llm_base_url),
            llm_model=get("LLM_MODEL", cls.llm_model),
            llm_reasoning_effort=e.get("LLM_REASONING_EFFORT", cls.llm_reasoning_effort),
            llm_timeout_s=float(get("LLM_TIMEOUT_S", str(cls.llm_timeout_s))),
            google_client_id=get("GOOGLE_CLIENT_ID"),
            google_client_secret=get("GOOGLE_CLIENT_SECRET"),
            allowed_emails=get("ALLOWED_EMAILS"),
            session_secret=get("SESSION_SECRET"),
            public_url=get("PUBLIC_URL").rstrip("/"),
            kafka_bootstrap=get("KAFKA_BOOTSTRAP"),
            kafka_topic=get("KAFKA_TOPIC", cls.kafka_topic),
            supabase_url=get("SUPABASE_URL").rstrip("/"),
            supabase_secret_key=get("SUPABASE_SECRET_KEY") or get("SUPABASE_SERVICE_ROLE_KEY"),
            supabase_access_token=get("SUPABASE_ACCESS_TOKEN"),
            cloud_sync_interval_s=max(30, int(get("CLOUD_SYNC_INTERVAL_S", str(cls.cloud_sync_interval_s)))),
            twilio_account_sid=get("TWILIO_ACCOUNT_SID"),
            twilio_auth_token=get("TWILIO_AUTH_TOKEN"),
            twilio_messaging_service_sid=get("TWILIO_MESSAGING_SERVICE_SID"),
            twilio_from=get("TWILIO_FROM"),
            twilio_allowed_to=get("TWILIO_ALLOWED_TO"),
            twilio_trial_template=get("TWILIO_TRIAL_TEMPLATE"),
            reminder_any_hour=_flag(get("REMINDER_ANY_HOUR", "0")),
            host=get("HOST", cls.host),
            port=int(get("PORT", str(cls.port))),
        )

    @property
    def db_path(self) -> Path:
        """Database path. A relative LEDGER_DB is resolved against the repository root, not the working directory."""
        p = Path(self.ledger_db)
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def data_dir(self) -> Path:
        return self.db_path.parent

    @property
    def auth_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def cloud_sync_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_secret_key)

    @property
    def sms_enabled(self) -> bool:
        """Twilio is configured. SMS go out only through the Kafka consumer, so Kafka must be on as well."""
        return bool(self.twilio_account_sid and self.twilio_auth_token
                    and (self.twilio_messaging_service_sid or self.twilio_from))

    @property
    def session_key_path(self) -> Path:
        return self.data_dir / "session.key"

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
