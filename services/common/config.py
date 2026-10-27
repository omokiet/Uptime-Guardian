from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/uptime_guardian"
    SYNC_DATABASE_URL: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/uptime_guardian"
    REDIS_URL: str = "redis://localhost:6379/0"
    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672/"
    RABBITMQ_QUEUE_CHECK_JOBS: str = "check.jobs"
    RABBITMQ_QUEUE_ALERT_EVENTS: str = "alert.events"

    SECRET_KEY: str = "dev-secret-key-change-in-production-min-32-chars"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_DEFAULT_CHAT_ID: str = ""
    COOLDOWN_MINUTES: int = 15
    CONSECUTIVE_THRESHOLD: int = 3

    RATE_LIMIT_ENABLED: bool = True
    TRUST_PROXY: bool = False
    AUTH_LOGIN_RATE_LIMIT: int = 10
    AUTH_LOGIN_WINDOW_SECONDS: int = 60
    AUTH_REGISTER_RATE_LIMIT: int = 5
    AUTH_REGISTER_WINDOW_SECONDS: int = 300

    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""
    SMTP_USE_TLS: bool = True

    model_config = {
        "env_file": ".env",
        "extra": "ignore"
    }


settings = Settings()
