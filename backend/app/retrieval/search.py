"""Permission-safe hybrid retrieval: filter → hybrid search → Postgres re-check → rerank.

Qdrant pre-filters on the chunk payload (fast). Every hit is then re-checked in Postgres,
because payload updates happen after DB commits and can lag or fail, and old-version points
can linger after a failed cleanup (Plan 2 follow-ups)."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.index import ChunkIndex
from app.llm.rag_config import RagConfig
from app.llm.sparse import embed_sparse_query
from app.retrieval.access import permitted_documents, visible_collection_ids
from app.users.models import User


@dataclass(frozen=True)
class RetrievedChunk:
    doc_id: uuid.UUID
    version_id: uuid.UUID
    filename: str
    text: str
    heading_path: list[str]
    modality: str
    page: int | None
    bbox: dict[str, float] | None
    score: float


@dataclass
class RetrievalDeps:
    index: ChunkIndex
    embed_query: Callable[[str], Awaitable[list[float]]]
    rerank: Callable[[str, str, list[str]], Awaitable[list[float]]]  # (model, query, docs)


def _rerank_text(payload: dict[str, Any]) -> str:
    return " › ".join(payload.get("heading_path") or []) + "\n" + str(payload.get("text", ""))


async def retrieve(
    session: AsyncSession,
    deps: RetrievalDeps,
    *,
    user: User,
    question: str,
    collection_ids: Sequence[uuid.UUID],
    config: RagConfig,
) -> list[RetrievedChunk]:
    group_ids = sorted(str(g.id) for g in user.groups)
    collections = await visible_collection_ids(session, user, collection_ids)
    if not group_ids or not collections:
        return []

    dense = await deps.embed_query(question)
    sparse = await asyncio.to_thread(embed_sparse_query, question)
    hits = await deps.index.search(
        dense,
        sparse,
        access_groups=group_ids,
        collection_ids=[str(c) for c in collections],
        limit=config.search_top_k,
    )

    documents = await permitted_documents(
        session, user, {uuid.UUID(h.payload["doc_id"]) for h in hits}
    )
    allowed = set(collections)
    candidates = []
    for hit in hits:
        document = documents.get(uuid.UUID(hit.payload["doc_id"]))
        if document is None or document.collection_id not in allowed:
            continue
        if hit.payload.get("version_id") != str(document.current_version_id):
            continue
        candidates.append(hit)
    if not candidates:
        return []

    scores = await deps.rerank(
        config.reranker_model, question, [_rerank_text(h.payload) for h in candidates]
    )
    ranked = sorted(zip(scores, candidates, strict=True), key=lambda pair: pair[0], reverse=True)
    return [
        RetrievedChunk(
            doc_id=uuid.UUID(hit.payload["doc_id"]),
            version_id=uuid.UUID(hit.payload["version_id"]),
            filename=str(hit.payload.get("filename", "")),
            text=str(hit.payload.get("text", "")),
            heading_path=list(hit.payload.get("heading_path") or []),
            modality=str(hit.payload.get("modality", "text")),
            page=hit.payload.get("page"),
            bbox=hit.payload.get("bbox"),
            score=float(score),
        )
        for score, hit in ranked[: config.rerank_top_n]
    ]
