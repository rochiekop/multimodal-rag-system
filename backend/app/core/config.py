from functools import lru_cache
from typing import Literal, cast

from fastapi import Request
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Every field maps to an env var with the RAG_ prefix."""

    model_config = SettingsConfigDict(
        env_prefix="RAG_", env_file=".env", extra="ignore", env_ignore_empty=True
    )

    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://rag:rag@localhost:5432/rag"
    jwt_secret: SecretStr
    jwt_ttl_seconds: int = 8 * 60 * 60
    session_cookie_secure: bool | None = None  # None: secure only when env == "prod"
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
    secrets_key: SecretStr | None = None  # Fernet key encrypting API keys saved in Settings
    embedding_model: str = "text-embedding-3-large"
    embedding_dimensions: int = 1024
    vision_model: str = "gpt-5-mini"
    chunk_max_tokens: int = 500
    chunk_overlap_tokens: int = 50

    phoenix_endpoint: str | None = None  # e.g. http://phoenix:6006/v1/traces
    phoenix_project: str = "multimodal-rag"

    @field_validator("jwt_secret")
    @classmethod
    def _secret_long_enough(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("RAG_JWT_SECRET must be at least 32 characters")
        return value

    @field_validator("secrets_key")
    @classmethod
    def _secrets_key_is_fernet(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            from cryptography.fernet import Fernet

            try:
                Fernet(value.get_secret_value().encode())
            except ValueError:
                raise ValueError(
                    "RAG_SECRETS_KEY must be a Fernet key: generate one with "
                    '`python -c "from cryptography.fernet import Fernet; '
                    'print(Fernet.generate_key().decode())"`'
                ) from None
        return value

    def cookie_secure(self) -> bool:
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return self.env == "prod"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment


def get_app_settings(request: Request) -> Settings:
    """FastAPI dependency: the Settings instance the app was created with."""
    return cast(Settings, request.app.state.settings)
