import json
import uuid
from collections.abc import AsyncIterator, Iterable, Sequence
from typing import Any

from httpx import AsyncClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.answer import ChatDeps
from app.core.security import hash_password
from app.documents.access import effective_access_groups
from app.documents.models import Collection, Document, DocumentStatus, DocumentVersion
from app.guardrails.input import CLASSIFIER_PROMPT
from app.guardrails.output import JUDGE_PROMPT
from app.ingestion.index import ChunkIndex, IndexedChunk
from app.llm import rag_config
from app.llm.rag_config import RagConfig
from app.llm.sparse import embed_sparse_documents
from app.retrieval.search import RetrievalDeps
from app.users.models import Group, Role, User

DEFAULT_PASSWORD = "correct-horse-42"


async def make_group(session: AsyncSession, name: str = "engineering") -> Group:
    group = Group(name=name, description="")
    session.add(group)
    await session.commit()
    return group


async def make_user(
    session: AsyncSession,
    *,
    username: str = "alice",
    role: Role = Role.USER,
    password: str = DEFAULT_PASSWORD,
    must_change_password: bool = False,
    is_active: bool = True,
    groups: Iterable[Group] = (),
) -> User:
    user = User(
        username=username,
        full_name=username.title(),
        password_hash=hash_password(password),
        role=role.value,
        must_change_password=must_change_password,
        is_active=is_active,
        groups=list(groups),
    )
    session.add(user)
    await session.commit()
    return user


async def login(client: AsyncClient, username: str, password: str = DEFAULT_PASSWORD) -> str:
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


DIMENSIONS = 8  # matches the settings fixture


class FakeEmbed:
    """Dense query embedding stand-in that records what it was asked to embed."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    async def __call__(self, text: str) -> list[float]:
        self.queries.append(text)
        return [1.0] * DIMENSIONS


async def make_collection(
    session: AsyncSession, name: str, groups: Iterable[Group] = ()
) -> Collection:
    collection = Collection(name=name, groups=list(groups))
    session.add(collection)
    await session.commit()
    return collection


async def index_chunks(
    index: ChunkIndex,
    document: Document,
    version_id: uuid.UUID,
    texts: Sequence[str],
    payload_groups: list[str] | None = None,
) -> None:
    """Write chunks with the payload the ingestion pipeline writes. payload_groups overrides
    the access groups to simulate a stale payload."""
    groups = effective_access_groups(document) if payload_groups is None else payload_groups
    sparse = embed_sparse_documents(list(texts))
    await index.upsert(
        version_id,
        [
            IndexedChunk(
                position=i,
                text=text,
                dense=[1.0] * DIMENSIONS,
                sparse=sparse[i],
                payload={
                    "doc_id": str(document.id),
                    "collection_id": str(document.collection_id),
                    "filename": document.filename,
                    "access_groups": groups,
                    "deleted": False,
                    "sensitive": False,
                    "modality": "text",
                    "heading_path": ["Handbook"],
                    "page": 1,
                    "bbox": {"l": 10.0, "t": 20.0, "r": 200.0, "b": 60.0},
                },
            )
            for i, text in enumerate(texts)
        ],
    )


async def seed_document(
    session: AsyncSession,
    index: ChunkIndex,
    collection: Collection,
    texts: Sequence[str],
    *,
    filename: str = "handbook.pdf",
    restricted: Iterable[Group] = (),
) -> Document:
    """A ready, indexed document (version 1 is current)."""
    version = DocumentVersion(
        id=uuid.uuid4(),
        version_no=1,
        sha256=uuid.uuid4().hex,
        content_type="application/pdf",
        size_bytes=1,
        status=DocumentStatus.READY.value,
    )
    document = Document(
        collection=collection,
        filename=filename,
        restricted_groups=list(restricted),
        versions=[version],
        current_version_id=version.id,
    )
    session.add(document)
    await session.commit()
    await index_chunks(index, document, version.id, texts)
    return document


async def high_scores(model: str, query: str, docs: list[str]) -> list[float]:
    return [0.9 - i * 0.01 for i in range(len(docs))]


def verdict(**flags: bool) -> str:
    """A complete input-classifier reply; unnamed checks are false."""
    keys = ("prompt_injection", "exfiltration", "off_topic")
    return json.dumps({k: flags.get(k, False) for k in keys})


CLEAN_VERDICT = verdict()


def _system(messages: list[BaseMessage]) -> str:
    first = messages[0] if messages else None
    return str(first.content) if isinstance(first, SystemMessage) else ""


class ScreenedFake(FakeListChatModel):
    """A FakeListChatModel that answers the input classifier and groundedness judge with
    fixed verdicts, so one model name can serve rewrite, classifier and judge (as the
    defaults do) without consuming its scripted responses."""

    classifier_reply: str = CLEAN_VERDICT
    judge_reply: str = '{"grounded": true}'

    def _call(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> str:
        system = _system(messages)
        if system.startswith(CLASSIFIER_PROMPT[:40]):
            return self.classifier_reply
        if system == JUDGE_PROMPT:
            return self.judge_reply
        return super()._call(messages, *args, **kwargs)


def _usage(input_tokens: int, output_tokens: int) -> dict[str, int]:
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


class MeteredFake(BaseChatModel):
    """Reports usage and its model name like a real provider: invoke carries both; a stream
    sends words as chunks with response_metadata and usage on the last chunk only."""

    reply: str
    reported_model: str = "gpt-5-mini"
    input_tokens: int = 7
    output_tokens: int = 3

    @property
    def _llm_type(self) -> str:
        return "metered-fake"

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> ChatResult:
        message = AIMessage(
            content=self.reply,
            usage_metadata=_usage(self.input_tokens, self.output_tokens),  # type: ignore[arg-type]
            response_metadata={"model_name": self.reported_model},
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _astream(
        self, messages: list[BaseMessage], *args: Any, **kwargs: Any
    ) -> AsyncIterator[ChatGenerationChunk]:
        words = self.reply.split(" ")
        for n, word in enumerate(words):
            last = n == len(words) - 1
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content=word if last else f"{word} ",
                    response_metadata={"model_name": self.reported_model},
                    usage_metadata=(  # type: ignore[arg-type]
                        _usage(self.input_tokens, self.output_tokens) if last else None
                    ),
                )
            )


def chat_deps(
    index: ChunkIndex,
    *,
    answer: str = "Annual leave is 25 days [1].",
    rewrite: str = "standalone question",
    judge: str = '{"grounded": true}',
    rerank=high_scores,
    embed: FakeEmbed | None = None,
    error_on_chunk: int | None = None,
    moderation: dict[str, bool] | None = None,
    models: dict[str, BaseChatModel] | None = None,
) -> ChatDeps:
    """Fake providers. Extra `models` (e.g. a classifier or judge under its own name) are
    looked up by the model name RagConfig asks for. The default models answer the input
    classifier with a clean verdict and the judge with `judge`."""
    defaults = RagConfig()
    registry: dict[str, BaseChatModel] = {
        defaults.chat_model: ScreenedFake(
            responses=[answer], error_on_chunk_number=error_on_chunk, judge_reply=judge
        ),
        defaults.rewrite_model: ScreenedFake(responses=[rewrite], judge_reply=judge),
        **(models or {}),
    }

    async def moderate(text: str) -> dict[str, bool]:
        return moderation or {}

    return ChatDeps(
        retrieval=RetrievalDeps(index=index, embed_query=embed or FakeEmbed(), rerank=rerank),
        chat_model=registry.__getitem__,
        moderate=moderate,
    )


async def activate_config(session: AsyncSession, **overrides: object) -> RagConfig:
    """Create and activate a RagConfig version, e.g. activate_config(s, guardrails={...})."""
    root = await make_user(session, username=f"root{uuid.uuid4().hex[:8]}", role=Role.SUPER_ADMIN)
    config = RagConfig.model_validate(overrides)
    row = await rag_config.create_version(session, root, config)
    await rag_config.activate(session, root, row.id)
    await session.commit()
    return config
