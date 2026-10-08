"""Production wiring of the chat pipeline's providers."""

from collections.abc import Awaitable, Callable
from functools import lru_cache

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import SecretStr

from app.chat.answer import ChatDeps
from app.core.config import Settings
from app.ingestion.index import ChunkIndex
from app.llm.gateway import get_chat_model, get_embeddings, get_moderator
from app.llm.keys import KeyRing
from app.llm.rerank import rerank
from app.retrieval.search import RetrievalDeps


def build_chat_deps(settings: Settings, index: ChunkIndex, keys: KeyRing | None = None) -> ChatDeps:
    """Real providers, created on first use so the app starts without API keys. Clients are
    cached per API key, so a key saved in admin Settings takes effect on the next refresh."""

    def current_key() -> str | None:
        key = keys.openai() if keys is not None else None
        return key.get_secret_value() if key is not None else None

    def secret(key: str | None) -> SecretStr | None:
        return SecretStr(key) if key is not None else None

    @lru_cache(maxsize=2)
    def embeddings(key: str | None) -> Embeddings:
        return get_embeddings(settings, api_key=secret(key))

    async def embed_query(text: str) -> list[float]:
        return await embeddings(current_key()).aembed_query(text)

    @lru_cache(maxsize=16)
    def cached_chat_model(name: str, key: str | None) -> BaseChatModel:
        return get_chat_model(settings, name, api_key=secret(key))

    def chat_model(name: str) -> BaseChatModel:
        return cached_chat_model(name, current_key())

    @lru_cache(maxsize=2)
    def moderator(key: str | None) -> Callable[[str], Awaitable[dict[str, bool]]]:
        return get_moderator(settings, api_key=secret(key))

    async def moderate(text: str) -> dict[str, bool]:
        return await moderator(current_key())(text)

    return ChatDeps(
        retrieval=RetrievalDeps(index=index, embed_query=embed_query, rerank=rerank),
        chat_model=chat_model,
        moderate=moderate,
    )
