from functools import lru_cache
from typing import Literal, cast

from fastapi import Request
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Every field maps to an env var with the RAG_ prefix."""

    model_config = SettingsConfigDict(env_prefix="RAG_", env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://rag:rag@localhost:5432/rag"
    jwt_secret: SecretStr
    jwt_ttl_seconds: int = 8 * 60 * 60
    login_max_failed_attempts: int = 5
    login_lockout_seconds: int = 15 * 60

    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "chunks"
    files_dir: str = "./data/files"
    max_upload_mb: int = 100

    clamav_enabled: bool = True
    clamav_host: str = "localhost"
    clamav_port: int = 3310

    openai_api_key: SecretStr | None = None
    embedding_model: str = "text-embedding-3-large"
    embedding_dimensions: int = 1024
    vision_model: str = "gpt-5-mini"
    chunk_max_tokens: int = 500
    chunk_overlap_tokens: int = 50

    @field_validator("jwt_secret")
    @classmethod
    def _secret_long_enough(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("RAG_JWT_SECRET must be at least 32 characters")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment


def get_app_settings(request: Request) -> Settings:
    """FastAPI dependency: the Settings instance the app was created with."""
    return cast(Settings, request.app.state.settings)
