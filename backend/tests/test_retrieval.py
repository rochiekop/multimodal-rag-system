import math
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.models import DocumentStatus, DocumentVersion
from app.ingestion.index import ChunkIndex
from app.llm import rerank as rerank_module
from app.llm.rag_config import RagConfig
from app.retrieval.search import RetrievalDeps, retrieve
from app.users.models import User
from tests.factories import (
    FakeEmbed,
    index_chunks,
    make_collection,
    make_group,
    make_user,
    seed_document,
)


async def _scores(model: str, query: str, docs: list[str]) -> list[float]:
    return [0.9 if "leave" in d else 0.2 for d in docs]


def _deps(index: ChunkIndex, embed: FakeEmbed | None = None) -> RetrievalDeps:
    return RetrievalDeps(index=index, embed_query=embed or FakeEmbed(), rerank=_scores)


async def _search(
    session: AsyncSession,
    deps: RetrievalDeps,
    user: User,
    collection_ids: list[uuid.UUID] | None = None,
    config: RagConfig | None = None,
):
    return await retrieve(
        session,
        deps,
        user=user,
        question="annual leave",
        collection_ids=collection_ids or [],
        config=config or RagConfig(),
    )


async def _world(session: AsyncSession, index: ChunkIndex):
    hr = await make_group(session, "hr")
    eng = await make_group(session, "eng")
    mgmt = await make_group(session, "mgmt")
    alice = await make_user(session, username="alice", groups=[hr])
    hr_coll = await make_collection(session, "HR", [hr, mgmt])
    eng_coll = await make_collection(session, "Engineering", [eng])
    hr_doc = await seed_document(session, index, hr_coll, ["Annual leave is 25 days."])
    eng_doc = await seed_document(session, index, eng_coll, ["Annual leave for engineers."])
    return alice, hr_coll, eng_coll, hr_doc, eng_doc, mgmt


async def test_user_only_gets_chunks_from_permitted_collections(
    session: AsyncSession, chunk_index: ChunkIndex
) -> None:
    alice, _, _, hr_doc, _, _ = await _world(session, chunk_index)
    results = await _search(session, _deps(chunk_index), alice)
    assert results and {r.doc_id for r in results} == {hr_doc.id}
    assert results[0].filename == "handbook.pdf"
    assert results[0].page == 1 and results[0].bbox == {"l": 10.0, "t": 20.0, "r": 200.0, "b": 60.0}


async def test_postgres_recheck_drops_stale_payload(
    session: AsyncSession, chunk_index: ChunkIndex
) -> None:
    alice, _, _, hr_doc, _, mgmt = await _world(session, chunk_index)
    # Restrict in Postgres only: the Qdrant payload still says hr may read it.
    hr_doc.restricted_groups = [mgmt]
    await session.commit()
    assert await _search(session, _deps(chunk_index), alice) == []

    hr_doc.restricted_groups = []
    hr_doc.deleted_at = datetime.now(UTC)  # soft-deleted in Postgres only
    await session.commit()
    assert await _search(session, _deps(chunk_index), alice) == []


async def test_revoking_group_from_collection_hides_its_chunks(
    session: AsyncSession, chunk_index: ChunkIndex
) -> None:
    alice, hr_coll, _, hr_doc, _, mgmt = await _world(session, chunk_index)
    before = await _search(session, _deps(chunk_index), alice)
    assert {r.doc_id for r in before} == {hr_doc.id}
    # Revoke hr from the collection in Postgres only: the Qdrant payload is stale.
    hr_coll.groups = [mgmt]
    await session.commit()
    assert await _search(session, _deps(chunk_index), alice) == []


async def test_removing_user_from_group_hides_its_chunks(
    session: AsyncSession, chunk_index: ChunkIndex
) -> None:
    alice, _, _, hr_doc, _, _ = await _world(session, chunk_index)
    before = await _search(session, _deps(chunk_index), alice)
    assert {r.doc_id for r in before} == {hr_doc.id}
    alice.groups = []
    await session.commit()
    alice = await session.get(User, alice.id, populate_existing=True)
    assert alice is not None and alice.groups == []
    assert await _search(session, _deps(chunk_index), alice) == []


async def test_only_current_version_chunks_are_used(
    session: AsyncSession, chunk_index: ChunkIndex
) -> None:
    alice, _, _, hr_doc, _, _ = await _world(session, chunk_index)
    v2 = DocumentVersion(
        id=uuid.uuid4(),
        version_no=2,
        sha256=uuid.uuid4().hex,
        content_type="application/pdf",
        size_bytes=1,
        status=DocumentStatus.READY.value,
    )
    hr_doc.versions.append(v2)
    hr_doc.current_version_id = v2.id
    await session.commit()
    await index_chunks(chunk_index, hr_doc, v2.id, ["Annual leave is 30 days."])
    # v1 points are still in Qdrant (as after a failed cleanup).
    results = await _search(session, _deps(chunk_index), alice)
    assert [r.text for r in results] == ["Annual leave is 30 days."]
    assert {r.version_id for r in results} == {v2.id}


async def test_user_without_groups_gets_nothing_and_skips_search(
    session: AsyncSession, chunk_index: ChunkIndex
) -> None:
    await _world(session, chunk_index)
    nobody = await make_user(session, username="nobody")
    embed = FakeEmbed()
    assert await _search(session, _deps(chunk_index, embed), nobody) == []
    assert embed.queries == []


async def test_requested_collections_are_intersected_with_visible(
    session: AsyncSession, chunk_index: ChunkIndex
) -> None:
    alice, hr_coll, eng_coll, hr_doc, _, _ = await _world(session, chunk_index)
    assert await _search(session, _deps(chunk_index), alice, [eng_coll.id]) == []
    results = await _search(session, _deps(chunk_index), alice, [hr_coll.id, eng_coll.id])
    assert {r.doc_id for r in results} == {hr_doc.id}


async def test_results_are_reranked_and_cut_to_top_n(
    session: AsyncSession, chunk_index: ChunkIndex
) -> None:
    hr = await make_group(session, "hr")
    alice = await make_user(session, username="alice", groups=[hr])
    coll = await make_collection(session, "HR", [hr])
    await seed_document(
        session,
        chunk_index,
        coll,
        ["Parking rules.", "Annual leave is 25 days.", "Leave carry over."],
    )
    results = await _search(session, _deps(chunk_index), alice, config=RagConfig(rerank_top_n=2))
    assert len(results) == 2
    assert all("eave" in r.text for r in results)
    assert results[0].score >= results[1].score


async def test_local_rerank_squashes_scores(monkeypatch) -> None:
    class FakeEncoder:
        def rerank(self, query: str, documents: list[str]) -> list[float]:
            return [3.0, -3.0, 0.0, -1000.0]

    monkeypatch.setattr(rerank_module, "cross_encoder", lambda model: FakeEncoder())
    scores = await rerank_module.rerank("m", "q", ["a", "b", "c", "d"])
    expected = [1 / (1 + math.exp(-3.0)), 1 / (1 + math.exp(3.0)), 0.5]
    assert scores[:3] == pytest.approx(expected)
    assert 0.0 <= scores[3] < 1e-6  # very negative logit: no overflow
    assert await rerank_module.rerank("m", "q", []) == []
