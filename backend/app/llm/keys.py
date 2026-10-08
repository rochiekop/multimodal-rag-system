"""The OpenAI key every provider call uses: the one saved in admin Settings, else
RAG_OPENAI_API_KEY. Re-read at most every `ttl` seconds so a rotation reaches every process
(API and workers) without a restart."""

import logging
import time
from collections.abc import Callable

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.settings_store.service import resolve_openai_key

logger = logging.getLogger(__name__)


class KeyRing:
    def __init__(
        self,
        settings: Settings,
        sessionmaker: async_sessionmaker[AsyncSession],
        ttl: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._sessionmaker = sessionmaker
        self._ttl = ttl
        self._clock = clock
        self._key = settings.openai_api_key
        self._loaded_at: float | None = None

    async def refresh(self, force: bool = False) -> None:
        now = self._clock()
        if not force and self._loaded_at is not None and now - self._loaded_at < self._ttl:
            return
        try:
            async with self._sessionmaker() as session:
                self._key = await resolve_openai_key(session, self._settings)
        except Exception:  # a database hiccup keeps the last known key
            logger.warning("Could not reload the OpenAI key", exc_info=True)
        self._loaded_at = now

    def openai(self) -> SecretStr | None:
        return self._key

    def use_settings(self, settings: Settings) -> None:
        """Follow the app's live settings (tests swap them; production never does)."""
        self._settings = settings
