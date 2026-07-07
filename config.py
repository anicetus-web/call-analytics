from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator, Field


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
    #
    # Deliberately typed str here, not list[int]: pydantic-settings tries
    # json.loads() on the raw env string BEFORE any field_validator runs for
    # complex-typed (list/dict) fields, and raises SettingsError outright if
    # that fails — which it does for "" (empty) or "123456789" (a bare int
    # is valid JSON but the wrong shape), a validator never gets a chance to
    # run. This bit us in production (deploy crash-looped on startup).
    # Keeping the field a plain str sidesteps that pre-parse entirely; the
    # ADMIN_TELEGRAM_IDS property below does the actual parsing on access.
    ADMIN_TELEGRAM_IDS_RAW: str = Field(default="", validation_alias="ADMIN_TELEGRAM_IDS")

    @property
    def ADMIN_TELEGRAM_IDS(self) -> list[int]:
        v = self.ADMIN_TELEGRAM_IDS_RAW.strip()
        if not v:
            return []
        return [int(x.strip()) for x in v.strip("[]").split(",") if x.strip()]

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
    # str, not list[str] — see ADMIN_TELEGRAM_IDS_RAW above for why.
    CORS_ORIGINS_RAW: str = Field(default="http://localhost:5173", validation_alias="CORS_ORIGINS")

    @property
    def CORS_ORIGINS(self) -> list[str]:
        origins = [o.strip() for o in self.CORS_ORIGINS_RAW.split(",") if o.strip()]
        # Browsers always send a scheme in Origin headers, so origins without one
        # would never match. Fail loudly (on first access, at app startup via
        # api/main.py reading this immediately) rather than silently failing
        # CORS preflights at runtime.
        for origin in origins:
            if not (origin.startswith("http://") or origin.startswith("https://")):
                raise ValueError(f"CORS origin {origin!r} must start with http:// or https://")
        return origins

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
        # Managed Postgres providers (e.g. Render) hand out postgres:// / postgresql://
        # URLs; normalize to the asyncpg driver scheme instead of requiring users to
        # hand-edit the connection string after every provisioning.
        if v.startswith("postgres://"):
            v = "postgresql+asyncpg://" + v[len("postgres://"):]
        elif v.startswith("postgresql://"):
            v = "postgresql+asyncpg://" + v[len("postgresql://"):]
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

    @field_validator("LLM_TEMPERATURE")
    @classmethod
    def validate_temperature(cls, v: float) -> float:
        if not 0.0 <= v <= 2.0:
            raise ValueError("LLM_TEMPERATURE must be between 0.0 and 2.0")
        return v

    @field_validator("MAX_RETRY_ATTEMPTS")
    @classmethod
    def validate_max_retry_attempts(cls, v: int) -> int:
        # 0 would silently skip the retry loop body entirely (range(1, 1) is empty),
        # raising a confusing "failed after 0 attempts: None" instead of ever calling
        # Whisper/the LLM — fail loudly at startup instead.
        if v < 1:
            raise ValueError("MAX_RETRY_ATTEMPTS must be at least 1")
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
        # Eagerly evaluate the two derived list properties so a malformed
        # ADMIN_TELEGRAM_IDS/CORS_ORIGINS value fails at startup (matching the
        # old fail-fast field_validator behavior), not on first request.
        self.ADMIN_TELEGRAM_IDS  # noqa: B018
        self.CORS_ORIGINS  # noqa: B018


settings = Settings()
