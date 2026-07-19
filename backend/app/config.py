import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
DEFAULT_DATABASE_URL = f"sqlite:///{DATA_DIR / 'recruitai.db'}"
DEVELOPMENT_SECRET = "local-development-secret-change-in-production"


def _boolean(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


def _integer(name: str, default: int, minimum: int = 0) -> int:
    return max(minimum, int(os.getenv(name, str(default))))


@dataclass(frozen=True)
class Settings:
    app_env: str
    database_url: str
    jwt_secret: str
    access_token_minutes: int
    public_app_url: str
    cors_origins: tuple[str, ...]
    log_level: str
    auto_create_schema: bool
    bootstrap_demo_users: bool
    bootstrap_admin_email: str
    bootstrap_admin_password: str
    max_upload_bytes: int
    ai_provider: str
    openai_model: str
    openai_embedding_model: str
    openai_timeout_seconds: float
    ai_max_calls_per_minute: int
    ai_circuit_failure_threshold: int
    ai_circuit_reset_seconds: int
    ai_monthly_token_budget: int
    async_ai_jobs: bool
    ai_worker_poll_seconds: int
    ai_worker_max_attempts: int
    candidate_retention_days: int
    privacy_auto_delete: bool
    privacy_sweep_interval_seconds: int
    storage_provider: str
    storage_signed_url_seconds: int
    s3_endpoint_url: str
    s3_region: str
    s3_bucket: str
    s3_access_key_id: str
    s3_secret_access_key: str
    email_provider: str
    email_from: str
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_use_tls: bool
    smtp_max_attempts: int
    transcription_provider: str

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @classmethod
    def from_env(cls) -> "Settings":
        environment = os.getenv("APP_ENV", "development").strip().lower()
        origins = tuple(
            item.strip()
            for item in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
            if item.strip()
        )
        settings = cls(
            app_env=environment,
            database_url=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
            jwt_secret=os.getenv("JWT_SECRET", DEVELOPMENT_SECRET),
            access_token_minutes=_integer("ACCESS_TOKEN_MINUTES", 480, 5),
            public_app_url=os.getenv("PUBLIC_APP_URL", "http://127.0.0.1:5173").strip().rstrip("/"),
            cors_origins=origins,
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            auto_create_schema=_boolean("AUTO_CREATE_SCHEMA", environment != "production"),
            bootstrap_demo_users=_boolean("BOOTSTRAP_DEMO_USERS", environment != "production"),
            bootstrap_admin_email=os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip(),
            bootstrap_admin_password=os.getenv("BOOTSTRAP_ADMIN_PASSWORD", ""),
            max_upload_bytes=_integer("MAX_UPLOAD_MB", 25, 1) * 1024 * 1024,
            ai_provider=os.getenv("AI_PROVIDER", "local").strip().lower(),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5.6-sol"),
            openai_embedding_model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
            openai_timeout_seconds=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "45")),
            ai_max_calls_per_minute=_integer("AI_MAX_CALLS_PER_MINUTE", 30, 1),
            ai_circuit_failure_threshold=_integer("AI_CIRCUIT_FAILURE_THRESHOLD", 3, 1),
            ai_circuit_reset_seconds=_integer("AI_CIRCUIT_RESET_SECONDS", 60, 1),
            ai_monthly_token_budget=_integer("AI_MONTHLY_TOKEN_BUDGET", 0),
            async_ai_jobs=_boolean("ASYNC_AI_JOBS", False),
            ai_worker_poll_seconds=_integer("AI_WORKER_POLL_SECONDS", 2, 1),
            ai_worker_max_attempts=_integer("AI_WORKER_MAX_ATTEMPTS", 3, 1),
            candidate_retention_days=_integer("CANDIDATE_RETENTION_DAYS", 365, 1),
            privacy_auto_delete=_boolean("PRIVACY_AUTO_DELETE", False),
            privacy_sweep_interval_seconds=_integer("PRIVACY_SWEEP_INTERVAL_SECONDS", 3600, 60),
            storage_provider=os.getenv("STORAGE_PROVIDER", "local").strip().lower(),
            storage_signed_url_seconds=_integer("STORAGE_SIGNED_URL_SECONDS", 900, 60),
            s3_endpoint_url=os.getenv("S3_ENDPOINT_URL", "").strip(),
            s3_region=os.getenv("S3_REGION", "us-east-1").strip(),
            s3_bucket=os.getenv("S3_BUCKET", "recruitai").strip(),
            s3_access_key_id=os.getenv("S3_ACCESS_KEY_ID", "").strip(),
            s3_secret_access_key=os.getenv("S3_SECRET_ACCESS_KEY", ""),
            email_provider=os.getenv("EMAIL_PROVIDER", "local").strip().lower(),
            email_from=os.getenv("EMAIL_FROM", "recruitai@localhost").strip(),
            smtp_host=os.getenv("SMTP_HOST", "").strip(),
            smtp_port=_integer("SMTP_PORT", 587, 1),
            smtp_username=os.getenv("SMTP_USERNAME", "").strip(),
            smtp_password=os.getenv("SMTP_PASSWORD", ""),
            smtp_use_tls=_boolean("SMTP_USE_TLS", True),
            smtp_max_attempts=_integer("SMTP_MAX_ATTEMPTS", 3, 1),
            transcription_provider=os.getenv("TRANSCRIPTION_PROVIDER", "local").strip().lower(),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.ai_provider not in {"local", "openai"}:
            raise ValueError("AI_PROVIDER must be local or openai")
        if not self.public_app_url.startswith(("http://", "https://")):
            raise ValueError("PUBLIC_APP_URL must be an http or https URL")
        if self.storage_provider not in {"local", "s3"}:
            raise ValueError("STORAGE_PROVIDER must be local or s3")
        if self.storage_provider == "s3" and not all((self.s3_bucket, self.s3_access_key_id, self.s3_secret_access_key)):
            raise ValueError("S3 storage requires S3_BUCKET, S3_ACCESS_KEY_ID, and S3_SECRET_ACCESS_KEY")
        if self.email_provider not in {"local", "smtp"}:
            raise ValueError("EMAIL_PROVIDER must be local or smtp")
        if self.email_provider == "smtp" and not all((self.email_from, self.smtp_host)):
            raise ValueError("SMTP email requires EMAIL_FROM and SMTP_HOST")
        if self.transcription_provider != "local":
            raise ValueError("TRANSCRIPTION_PROVIDER must be local until an external adapter is configured")
        if bool(self.bootstrap_admin_email) != bool(self.bootstrap_admin_password):
            raise ValueError("BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD must be set together")
        if self.bootstrap_admin_password and len(self.bootstrap_admin_password) < 12:
            raise ValueError("BOOTSTRAP_ADMIN_PASSWORD must contain at least 12 characters")
        if self.is_production:
            if self.jwt_secret == DEVELOPMENT_SECRET or len(self.jwt_secret) < 32:
                raise ValueError("Production JWT_SECRET must be unique and at least 32 characters")
            if self.bootstrap_demo_users:
                raise ValueError("BOOTSTRAP_DEMO_USERS must be false in production")
            if not self.cors_origins or "*" in self.cors_origins:
                raise ValueError("Production CORS_ORIGINS must explicitly list trusted origins")

    def safe_summary(self) -> dict:
        return {
            "environment": self.app_env,
            "public_app_url": self.public_app_url,
            "database": "postgresql" if self.database_url.startswith("postgresql") else "sqlite",
            "auto_create_schema": self.auto_create_schema,
            "demo_users": self.bootstrap_demo_users,
            "max_upload_mb": round(self.max_upload_bytes / 1024 / 1024),
            "ai_calls_per_minute": self.ai_max_calls_per_minute,
            "ai_monthly_token_budget": self.ai_monthly_token_budget,
            "ai_circuit_failure_threshold": self.ai_circuit_failure_threshold,
            "ai_circuit_reset_seconds": self.ai_circuit_reset_seconds,
            "async_ai_jobs": self.async_ai_jobs,
            "ai_worker_max_attempts": self.ai_worker_max_attempts,
            "candidate_retention_days": self.candidate_retention_days,
            "privacy_auto_delete": self.privacy_auto_delete,
            "privacy_sweep_interval_seconds": self.privacy_sweep_interval_seconds,
            "storage_provider": self.storage_provider,
            "storage_signed_url_seconds": self.storage_signed_url_seconds,
            "email_provider": self.email_provider,
            "transcription_provider": self.transcription_provider,
        }


settings = Settings.from_env()
