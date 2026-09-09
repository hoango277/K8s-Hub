"""Application settings, loaded from environment variables / .env."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    APP_NAME: str = "K8s Hub"
    APP_ENV: Literal["local", "dev", "staging", "prod"] = "local"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # --- Database ---
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/k8shub"

    # --- Redis ---
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- Auth ---
    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60

    # --- LLM ---
    ANTHROPIC_API_KEY: str = ""
    LLM_MODEL: str = "claude-sonnet-5"
    LLM_MAX_TOKENS: int = 8192

    # --- Kubernetes ---
    KUBECONFIG: str | None = None
    K8S_IN_CLUSTER: bool = False
    # read_only | require_approval | auto
    K8S_EXECUTION_MODE: Literal["read_only", "require_approval", "auto"] = "require_approval"
    K8S_ALLOWED_NAMESPACES: list[str] = []

    # --- Observability data sources ---
    PROMETHEUS_URL: str = "http://localhost:9090"
    LOKI_URL: str = "http://localhost:3100"

    # --- Langfuse ---
    LANGFUSE_HOST: str = "http://localhost:3001"
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_ENABLED: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
