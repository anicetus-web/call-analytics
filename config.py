from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Database ---
    DATABASE_URL: str  # must be postgresql+asyncpg://user:pass@host/db

    # --- OpenAI ---
    OPENAI_API_KEY: str
    WHISPER_MODEL: str = "whisper-1"
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_TEMPERATURE: float = 0.1
    LLM_MAX_TOKENS: int = 500

    # --- Telegram ---
    TELEGRAM_BOT_TOKEN: str
    # Comma-separated admin Telegram IDs notified on system errors (quota exhausted, etc.)
    # Example: ADMIN_TELEGRAM_IDS=123456789,987654321
    ADMIN_TELEGRAM_IDS: list[int] = []

    # --- Yandex Cloud S3 ---
    S3_ENDPOINT: str          # https://storage.yandexcloud.net
    S3_BUCKET: str
    S3_ACCESS_KEY: str
    S3_SECRET_KEY: str
    S3_REGION: str = "ru-central1"
    # Object key prefix inside the bucket, e.g. "calls" → keys like "calls/42/audio.ogg"
    S3_KEY_PREFIX: str = "calls"

    # --- Auth (JWT for admin web UI) ---
    JWT_SECRET_KEY: str
    # Token stored in localStorage (XSS-vulnerable); keep the window short.
    # Ideally migrate to httpOnly cookies — but until then, 1 day is a
    # reasonable compromise between security and convenience for 2 admins.
    JWT_EXPIRE_MINUTES: int = 60 * 24  # 1 day

    # --- Bot internal auth ---
    # Pre-shared secret between the bot process and the API for the /upload endpoint
    BOT_SECRET: str

    # --- Process roles ---
    # The system is designed to run as separate processes that share one DB:
    #   - API process(es): serve HTTP. Can be scaled horizontally (stateless).
    #   - ONE worker process: drains the in-memory task queue. MUST be a single instance.
    #   - ONE bot process: polls Telegram. MUST be a single instance (one poller per token).
    # These flags select what a given process runs. Defaults: API only.
    RUN_API: bool = True
    RUN_BOT: bool = False
    RUN_WORKER: bool = False
    # URL the bot uses to reach the API for /api/calls/upload.
    INTERNAL_API_URL: str = "http://localhost:8000"
    # URL the API uses to signal the worker's /internal/enqueue endpoint.
    # In docker-compose: http://worker:8000. Empty = worker runs in same process.
    WORKER_URL: str = ""

    # --- CORS ---
    # Comma-separated list of allowed web origins for the admin panel.
    # In the default docker-compose setup the frontend is served by nginx and
    # proxies /api to the api container, so the browser sees the same origin
    # and CORS is not exercised. CORS only matters when the panel and API live
    # on different origins (e.g. local Vite dev on :5173 → api on :8000).
    # Set to your production panel domain(s) via .env when deploying.
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]

    # --- Processing ---
    # Max retries for Whisper / LLM API failures before marking call as error
    MAX_RETRY_ATTEMPTS: int = 3
    RETRY_DELAY_SECONDS: float = 5.0
    # Transcription shorter than this is considered bad quality; skip LLM analysis
    MIN_TRANSCRIPTION_LENGTH: int = 10
    # Path to ffmpeg binary; None = rely on system PATH
    FFMPEG_PATH: str | None = None
    # Temp directory for downloaded files before S3 upload
    TEMP_DIR: str = "/tmp/call-analytics"

    # --- App ---
    DEBUG: bool = False
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "DATABASE_URL must use postgresql+asyncpg:// scheme for async support"
            )
        return v

    @field_validator("INTERNAL_API_URL", "WORKER_URL")
    @classmethod
    def validate_service_urls(cls, v: str, info) -> str:
        if not v:
            return v  # WORKER_URL is optional — empty means same-process or no worker
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError(
                f"{info.field_name} must start with http:// or https://, got {v!r}"
            )
        return v.rstrip("/")

    @field_validator("ADMIN_TELEGRAM_IDS", mode="before")
    @classmethod
    def parse_admin_ids(cls, v: object) -> list[int]:
        # Support comma-separated string from .env: ADMIN_TELEGRAM_IDS=123,456
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v  # type: ignore[return-value]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: object) -> list[str]:
        # Support comma-separated string from .env
        if isinstance(v, str):
            v = [x.strip() for x in v.split(",") if x.strip()]
        if not isinstance(v, list):
            raise ValueError("CORS_ORIGINS must be a list or comma-separated string")
        # Browsers always send a scheme in Origin headers, so origins without one
        # would never match. Catch the misconfiguration at startup instead of
        # silently failing CORS preflights at runtime.
        for origin in v:
            if not (origin.startswith("http://") or origin.startswith("https://")):
                raise ValueError(
                    f"CORS origin {origin!r} must start with http:// or https://"
                )
        return v

    @field_validator("LLM_TEMPERATURE")
    @classmethod
    def validate_temperature(cls, v: float) -> float:
        if not 0.0 <= v <= 2.0:
            raise ValueError("LLM_TEMPERATURE must be between 0.0 and 2.0")
        return v

    @field_validator("JWT_SECRET_KEY", "BOT_SECRET")
    @classmethod
    def reject_placeholder_secrets(cls, v: str, info) -> str:
        # Refuse obvious placeholder values so a misconfigured .env never reaches production.
        # In DEBUG mode we still require a non-trivial value but allow shorter dev secrets,
        # because forcing a 32-byte hex on every developer just to iterate locally is friction
        # without security benefit.
        # (We can't read other fields here reliably; the DEBUG check is enforced by
        # model_post_init below for full context.)
        lowered = v.strip().lower()
        if lowered.startswith("change-me") or lowered in {"", "secret", "changeme", "password"}:
            raise ValueError(
                f"{info.field_name} is set to a placeholder value. "
                "Generate a real secret, e.g. "
                "python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        return v

    def model_post_init(self, __context) -> None:
        # Production-only secret length check (sees DEBUG, unlike field_validators).
        if not self.DEBUG:
            for name in ("JWT_SECRET_KEY", "BOT_SECRET"):
                value = getattr(self, name)
                if len(value) < 16:
                    raise ValueError(
                        f"{name} must be at least 16 characters when DEBUG is false"
                    )


settings = Settings()
