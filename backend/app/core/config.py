from functools import lru_cache
from typing import Literal, cast

from fastapi import Request
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Every field maps to an env var with the RAG_ prefix."""

    model_config = SettingsConfigDict(env_prefix="RAG_", env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    database_url: str = "postgresql+asyncpg://rag:rag@localhost:5432/rag"
    jwt_secret: SecretStr
    jwt_ttl_seconds: int = 8 * 60 * 60
    login_max_failed_attempts: int = 5
    login_lockout_seconds: int = 15 * 60

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
