"""Installation settings: branding (name, color, logo) and the OpenAI key, encrypted with
RAG_SECRETS_KEY (Fernet). The key is never returned; only its last 4 characters are.
Functions flush; callers commit."""

import asyncio
import io
import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from cryptography.fernet import Fernet, InvalidToken
from PIL import Image
from pydantic import BaseModel, Field, SecretStr, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.core.config import Settings
from app.core.storage import FileStore
from app.settings_store.models import AppSetting
from app.users.models import User

logger = logging.getLogger(__name__)

BRANDING = "branding"
OPENAI_KEY = "openai_api_key"
LOGO_PREFIX = "branding"
LOGO_KEY = "branding/logo"
DEFAULT_APP_NAME = "Knowledge Assistant"
MAX_LOGO_BYTES = 512 * 1024
LOGO_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


class SettingsError(Exception):
    code = "settings_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SecretsKeyMissing(SettingsError):
    code = "secrets_key_missing"


class InvalidLogo(SettingsError):
    code = "invalid_logo"


class Branding(BaseModel):
    app_name: str = Field(default=DEFAULT_APP_NAME, min_length=1, max_length=60)
    primary_color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")

    @field_validator("app_name", mode="before")
    @classmethod
    def _strip_app_name(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("app_name must not be blank")
        return value


class BrandingOut(Branding):
    logo_url: str | None = None


class KeyStatus(BaseModel):
    source: Literal["database", "environment", "none", "unreadable"]
    last4: str | None
    updated_at: datetime | None
    secrets_key_configured: bool


async def _value(session: AsyncSession, key: str) -> dict[str, Any]:
    row = await session.get(AppSetting, key)
    return dict(row.value) if row is not None else {}


async def _put(
    session: AsyncSession, key: str, value: dict[str, Any], actor: User | None
) -> AppSetting:
    row = await session.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key)
        session.add(row)
    row.value = value
    row.updated_by = actor.id if actor is not None else None
    row.updated_at = datetime.now(UTC)
    await session.flush()
    return row


async def get_branding(session: AsyncSession) -> BrandingOut:
    value = await _value(session, BRANDING)
    branding = Branding.model_validate(
        {k: value[k] for k in ("app_name", "primary_color") if k in value}
    )
    logo = value.get("logo")
    url = f"/api/branding/logo?v={logo['version']}" if logo else None
    return BrandingOut(**branding.model_dump(), logo_url=url)


async def update_branding(session: AsyncSession, actor: User, branding: Branding) -> BrandingOut:
    value = await _value(session, BRANDING)
    value.update(branding.model_dump())
    await _put(session, BRANDING, value, actor)
    await audit.record(
        session,
        action="settings.branding_updated",
        actor=actor,
        target_type="settings",
        target_id=BRANDING,
        detail=branding.model_dump(),
    )
    return await get_branding(session)


def _logo_type(data: bytes) -> str:
    if len(data) > MAX_LOGO_BYTES:
        raise InvalidLogo("The logo can be at most 512 KB")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image_format = image.format
            image.verify()
    except Exception:
        raise InvalidLogo("The logo must be a PNG, JPEG or WebP image") from None
    if image_format not in LOGO_TYPES:
        raise InvalidLogo("The logo must be a PNG, JPEG or WebP image")
    return LOGO_TYPES[image_format]


async def set_logo(
    session: AsyncSession, store: FileStore, actor: User, data: bytes
) -> BrandingOut:
    content_type = _logo_type(data)
    await asyncio.to_thread(store.save, LOGO_KEY, data)
    value = await _value(session, BRANDING)
    value["logo"] = {"content_type": content_type, "version": uuid.uuid4().hex[:12]}
    await _put(session, BRANDING, value, actor)
    await audit.record(
        session,
        action="settings.logo_updated",
        actor=actor,
        target_type="settings",
        target_id=BRANDING,
        detail={"content_type": content_type, "bytes": len(data)},
    )
    return await get_branding(session)


async def clear_logo(session: AsyncSession, store: FileStore, actor: User) -> BrandingOut:
    value = await _value(session, BRANDING)
    value.pop("logo", None)
    await _put(session, BRANDING, value, actor)
    await asyncio.to_thread(store.delete_prefix, LOGO_PREFIX)
    await audit.record(
        session,
        action="settings.logo_removed",
        actor=actor,
        target_type="settings",
        target_id=BRANDING,
    )
    return await get_branding(session)


async def read_logo(session: AsyncSession, store: FileStore) -> tuple[bytes, str] | None:
    logo = (await _value(session, BRANDING)).get("logo")
    if not logo:
        return None
    try:
        data = await asyncio.to_thread(store.read, LOGO_KEY)
    except FileNotFoundError:
        return None
    return data, str(logo["content_type"])


def _fernet(settings: Settings) -> Fernet | None:
    if settings.secrets_key is None:
        return None
    return Fernet(settings.secrets_key.get_secret_value().encode())


def _decrypt(settings: Settings, token: str) -> str | None:
    fernet = _fernet(settings)
    if fernet is None:
        return None
    try:
        return fernet.decrypt(token.encode()).decode()
    except InvalidToken:
        return None


async def openai_key_status(session: AsyncSession, settings: Settings) -> KeyStatus:
    configured = settings.secrets_key is not None
    row = await session.get(AppSetting, OPENAI_KEY)
    if row is not None and row.value.get("ciphertext"):
        readable = _decrypt(settings, str(row.value["ciphertext"])) is not None
        return KeyStatus(
            source="database" if readable else "unreadable",
            last4=row.value.get("last4"),
            updated_at=row.updated_at,
            secrets_key_configured=configured,
        )
    if settings.openai_api_key is not None:
        return KeyStatus(
            source="environment",
            last4=settings.openai_api_key.get_secret_value()[-4:],
            updated_at=None,
            secrets_key_configured=configured,
        )
    return KeyStatus(source="none", last4=None, updated_at=None, secrets_key_configured=configured)


async def set_openai_key(
    session: AsyncSession, settings: Settings, actor: User, api_key: str
) -> KeyStatus:
    fernet = _fernet(settings)
    if fernet is None:
        raise SecretsKeyMissing(
            "Set RAG_SECRETS_KEY in deploy/.env and restart before saving API keys"
        )
    token = fernet.encrypt(api_key.encode()).decode()
    last4 = api_key[-4:]
    await _put(session, OPENAI_KEY, {"ciphertext": token, "last4": last4}, actor)
    await audit.record(
        session,
        action="settings.openai_key_set",
        actor=actor,
        target_type="settings",
        target_id=OPENAI_KEY,
        detail={"last4": last4},
    )
    return await openai_key_status(session, settings)


async def clear_openai_key(session: AsyncSession, settings: Settings, actor: User) -> KeyStatus:
    row = await session.get(AppSetting, OPENAI_KEY)
    if row is not None:
        await session.delete(row)
        await session.flush()
    await audit.record(
        session,
        action="settings.openai_key_cleared",
        actor=actor,
        target_type="settings",
        target_id=OPENAI_KEY,
    )
    return await openai_key_status(session, settings)


async def resolve_openai_key(session: AsyncSession, settings: Settings) -> SecretStr | None:
    """The key provider calls use: the saved one if it decrypts, else RAG_OPENAI_API_KEY."""
    row = await session.get(AppSetting, OPENAI_KEY)
    if row is not None and row.value.get("ciphertext"):
        plain = _decrypt(settings, str(row.value["ciphertext"]))
        if plain is not None:
            return SecretStr(plain)
        logger.warning(
            "The saved OpenAI key can't be decrypted with RAG_SECRETS_KEY; "
            "using RAG_OPENAI_API_KEY instead"
        )
    return settings.openai_api_key
