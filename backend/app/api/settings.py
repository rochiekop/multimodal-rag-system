"""Branding (public, so the sign-in page can show it) and installation settings
(super_admin). Saving or clearing the API key needs password re-entry and is audited."""

from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field

from app.api.errors import api_error
from app.auth.deps import SessionDep, SettingsDep, SuperAdminUser, ensure_password_confirmed
from app.core.config import Settings
from app.core.storage import FileStore
from app.documents.schemas import PasswordConfirm
from app.llm.keys import KeyRing
from app.settings_store import service
from app.settings_store.service import Branding, BrandingOut, KeyStatus

public_router = APIRouter(tags=["branding"])
router = APIRouter(prefix="/admin/settings", tags=["admin-settings"])

_STATUS = {service.SecretsKeyMissing: 409, service.InvalidLogo: 422}


class OpenAIKeyIn(BaseModel):
    api_key: str = Field(min_length=20, max_length=300, pattern=r"^\S+$")
    password: str = Field(min_length=1, max_length=128)


def _http_error(exc: service.SettingsError) -> HTTPException:
    return api_error(_STATUS.get(type(exc), 400), exc.code, exc.message)


def _store(request: Request) -> FileStore:
    store: FileStore = request.app.state.store
    return store


async def _reload_keys(request: Request, settings: Settings) -> None:
    """Apply a saved or cleared key now. Updates the shared ring that chat_deps holds."""
    keys: KeyRing = request.app.state.keys
    keys.use_settings(settings)
    await keys.refresh(force=True)


@public_router.get("/branding")
async def get_branding(session: SessionDep) -> BrandingOut:
    return await service.get_branding(session)


@public_router.get("/branding/logo")
async def get_logo(session: SessionDep, request: Request) -> Response:
    logo = await service.read_logo(session, _store(request))
    if logo is None:
        raise api_error(404, "not_found", "No logo is set")
    data, content_type = logo
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=300", "X-Content-Type-Options": "nosniff"},
    )


@router.put("/branding")
async def update_branding(body: Branding, user: SuperAdminUser, session: SessionDep) -> BrandingOut:
    branding = await service.update_branding(session, user, body)
    await session.commit()
    return branding


@router.post("/branding/logo")
async def upload_logo(
    user: SuperAdminUser,
    session: SessionDep,
    request: Request,
    file: Annotated[UploadFile, File()],
) -> BrandingOut:
    data = await file.read(service.MAX_LOGO_BYTES + 1)
    try:
        branding = await service.set_logo(session, _store(request), user, data)
    except service.SettingsError as exc:
        raise _http_error(exc) from None
    await session.commit()
    return branding


@router.delete("/branding/logo")
async def remove_logo(user: SuperAdminUser, session: SessionDep, request: Request) -> BrandingOut:
    branding = await service.clear_logo(session, _store(request), user)
    await session.commit()
    return branding


@router.get("/openai-key")
async def key_status(_: SuperAdminUser, session: SessionDep, settings: SettingsDep) -> KeyStatus:
    return await service.openai_key_status(session, settings)


@router.put("/openai-key")
async def set_key(
    body: OpenAIKeyIn,
    user: SuperAdminUser,
    session: SessionDep,
    settings: SettingsDep,
    request: Request,
) -> KeyStatus:
    await ensure_password_confirmed(user, body.password)
    try:
        status = await service.set_openai_key(session, settings, user, body.api_key)
    except service.SettingsError as exc:
        raise _http_error(exc) from None
    await session.commit()
    await _reload_keys(request, settings)
    return status


@router.post("/openai-key/clear")
async def clear_key(
    body: PasswordConfirm,
    user: SuperAdminUser,
    session: SessionDep,
    settings: SettingsDep,
    request: Request,
) -> KeyStatus:
    await ensure_password_confirmed(user, body.password)
    status = await service.clear_openai_key(session, settings, user)
    await session.commit()
    await _reload_keys(request, settings)
    return status
