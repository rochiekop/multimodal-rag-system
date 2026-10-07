"""Production wiring of the chat pipeline's providers."""

from collections.abc import Awaitable, Callable
from functools import lru_cache

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel

from app.chat.answer import ChatDeps
from app.core.config import Settings
from app.ingestion.index import ChunkIndex
from app.llm.gateway import get_chat_model, get_embeddings, get_moderator
from app.llm.rerank import rerank
from app.retrieval.search import RetrievalDeps


def build_chat_deps(settings: Settings, index: ChunkIndex) -> ChatDeps:
    """Real providers, created on first use so the app starts without API keys."""

    @lru_cache(maxsize=1)
    def embeddings() -> Embeddings:
        return get_embeddings(settings)

    async def embed_query(text: str) -> list[float]:
        return await embeddings().aembed_query(text)

    @lru_cache(maxsize=8)
    def chat_model(name: str) -> BaseChatModel:
        return get_chat_model(settings, name)

    @lru_cache(maxsize=1)
    def moderator() -> Callable[[str], Awaitable[dict[str, bool]]]:
        return get_moderator(settings)

    async def moderate(text: str) -> dict[str, bool]:
        return await moderator()(text)

    return ChatDeps(
        retrieval=RetrievalDeps(index=index, embed_query=embed_query, rerank=rerank),
        chat_model=chat_model,
        moderate=moderate,
    )
