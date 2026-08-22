"""Configuracao por ambiente do AutoFlow."""

import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def development_redis_url() -> str:
    """Keep the host broker URL aligned with the local Redis password.

    Docker Compose already builds its internal URL from REDIS_PASSWORD. When
    Flask/Celery run directly on the host, use that same password for a local
    broker so stale credentials embedded in REDIS_URL cannot silently strand
    every outbox task.
    """

    configured = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    password = os.getenv("REDIS_PASSWORD", "").strip()
    try:
        parsed = urlsplit(configured)
    except ValueError:
        return configured
    if not password or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return configured
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f":{quote(password, safe='')}@{host}{port}"
    return urlunsplit((parsed.scheme or "redis", netloc, parsed.path or "/0", "", ""))


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me-before-production")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", "mysql+pymysql://root:password@localhost/autoflow"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
    }
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024

    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    WTF_CSRF_TIME_LIMIT = None

    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    GROQ_API_URL = os.getenv(
        "GROQ_API_URL", "https://api.groq.com/openai/v1/chat/completions"
    )

    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "") or "memory://"
    CELERY_BROKER_URL = REDIS_URL
    CELERY_RESULT_BACKEND = REDIS_URL
    CELERY = {
        "broker_connection_retry_on_startup": True,
        "task_acks_late": True,
        "task_reject_on_worker_lost": True,
        "worker_prefetch_multiplier": 1,
        "broker_connection_timeout": 1,
        "timezone": "UTC",
        "enable_utc": True,
        "beat_schedule": {
            "dispatch-pending-task-outbox": {
                "task": "app.tasks.dispatch_task_outbox",
                "schedule": float(os.getenv("OUTBOX_DISPATCH_INTERVAL_SECONDS", "10")),
            }
        },
    }
    OUTBOX_IMMEDIATE_DISPATCH = env_bool("OUTBOX_IMMEDIATE_DISPATCH", True)
    OUTBOX_BATCH_SIZE = int(os.getenv("OUTBOX_BATCH_SIZE", "100"))
    AI_INBOUND_HOURLY_LIMIT = int(os.getenv("AI_INBOUND_HOURLY_LIMIT", "300"))
    AI_SENDER_MINUTE_LIMIT = int(os.getenv("AI_SENDER_MINUTE_LIMIT", "30"))

    EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "http://127.0.0.1:8080").rstrip(
        "/"
    )
    EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")
    EVOLUTION_REQUEST_TIMEOUT = float(os.getenv("EVOLUTION_REQUEST_TIMEOUT", "25"))
    EVOLUTION_WEBHOOK_URL = os.getenv("EVOLUTION_WEBHOOK_URL", "").rstrip("/")

    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_USE_TLS = env_bool("SMTP_USE_TLS", True)
    SMTP_USE_SSL = env_bool("SMTP_USE_SSL", False)
    SMTP_TIMEOUT = float(os.getenv("SMTP_TIMEOUT", "10"))
    MAIL_FROM = os.getenv("MAIL_FROM", "")

    PRODUCT_UPLOAD_DIR = os.getenv("PRODUCT_UPLOAD_DIR", "")
    PRODUCT_UPLOAD_URL_PREFIX = os.getenv(
        "PRODUCT_UPLOAD_URL_PREFIX", "/products/uploads"
    )

    APP_URL = os.getenv("APP_URL", "http://localhost:5000")
    LANDING_PAGE_URL = os.getenv("LANDING_PAGE_URL", "")
    CORS_ORIGINS = [
        item.strip()
        for item in os.getenv("CORS_ORIGINS", "http://localhost:5000").split(",")
        if item.strip()
    ]
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    TRUST_PROXY_HOPS = max(0, int(os.getenv("TRUST_PROXY_HOPS", "0")))


class DevelopmentConfig(Config):
    DEBUG = True
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    REDIS_URL = development_redis_url()
    CELERY_BROKER_URL = REDIS_URL
    CELERY_RESULT_BACKEND = REDIS_URL


class ProductionConfig(Config):
    DEBUG = False
    RATELIMIT_STORAGE_URI = (
        os.getenv("RATELIMIT_STORAGE_URI", "") or Config.REDIS_URL
    )
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    PREFERRED_URL_SCHEME = "https"


class TestingConfig(Config):
    TESTING = True
    SECRET_KEY = "testing-secret"
    SQLALCHEMY_DATABASE_URI = os.getenv("TEST_DATABASE_URL", "sqlite:///:memory:")
    SQLALCHEMY_ENGINE_OPTIONS = {}
    WTF_CSRF_ENABLED = False
    LOGIN_DISABLED = False
    CELERY = {"task_always_eager": True, "task_eager_propagates": True}
    OUTBOX_IMMEDIATE_DISPATCH = False
    RATELIMIT_ENABLED = False


CONFIGS = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}
