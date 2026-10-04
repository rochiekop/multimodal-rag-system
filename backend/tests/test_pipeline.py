import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from langchain_core.embeddings import DeterministicFakeEmbedding
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.audit import service as audit
from app.core.config import Settings
from app.core.db import create_sessionmaker
from app.core.storage import LocalFileStore
from app.documents.models import Collection, Document, DocumentStatus, DocumentVersion
from app.documents.service import original_key
from app.ingestion.errors import PermanentIngestionError
from app.ingestion.index import ChunkIndex, IndexedChunk
from app.ingestion.parse import parse_document
from app.ingestion.pipeline import IngestionDeps, page_key, run_ingestion
from app.ingestion.scan import VirusFound
from app.llm.sparse import SparseVector
from app.users.models import Role
from tests.factories import bearer, login, make_group, make_user

MD = (
    b"# Handbook\n\n## Leave\n\nEmployees get 20 days.\n\n"
    b"| Type | Days |\n|---|---|\n| Annual | 20 |\n"
)


async def _clean(_: bytes) -> None:
    return None


async def _describe(_: bytes) -> str:
    return "a chart"


def _sparse(texts: list[str]) -> list[SparseVector]:
    return [SparseVector(indices=[len(t) % 97 + 1], values=[1.0]) for t in texts]


@pytest.fixture
def deps(engine: AsyncEngine, chunk_index: ChunkIndex, settings: Settings) -> IngestionDeps:
    return IngestionDeps(
        sessionmaker=create_sessionmaker(engine),
        store=LocalFileStore(settings.files_dir),
        index=chunk_index,
        scan=_clean,
        parse=parse_document,
        describe_image=_describe,
        embed_dense=DeterministicFakeEmbedding(size=8).aembed_documents,
        embed_sparse=_sparse,
    )


async def _version(
    session: AsyncSession,
    deps: IngestionDeps,
    data: bytes = MD,
    *,
    document: Document | None = None,
) -> DocumentVersion:
    if document is None:
        group = await make_group(session, f"g{uuid.uuid4().hex[:6]}")
        collection = Collection(name=f"c{uuid.uuid4().hex[:6]}", groups=[group])
        document = Document(
            collection=collection, filename="handbook.md", versions=[], restricted_groups=[]
        )
        session.add(document)
    version = DocumentVersion(
        version_no=len(document.versions) + 1,
        sha256=uuid.uuid4().hex,
        content_type="text/markdown",
        size_bytes=len(data),
    )
    document.versions.append(version)
    await session.commit()
    deps.store.save(original_key(version.id), data)
    return version


async def test_markdown_document_is_indexed(session: AsyncSession, deps: IngestionDeps) -> None:
    version = await _version(session, deps)
    assert await run_ingestion(version.id, deps) is DocumentStatus.READY

    await session.refresh(version)
    document = await session.get(Document, version.document_id)
    assert document is not None
    await session.refresh(document)
    assert version.status == "ready"
    assert version.chunk_count == 2
    assert document.current_version_id == version.id

    chunks = await deps.index.list_chunks(version.id)
    assert [c["modality"] for c in chunks] == ["text", "table"]
    assert chunks[0]["heading_path"] == ["Handbook", "Leave"]
    assert chunks[0]["access_groups"] == [str(document.collection.groups[0].id)]
    assert chunks[0]["deleted"] is False
    assert (await audit.list_recent(session))[0].action == "document.indexed"


async def test_rerun_is_idempotent(session: AsyncSession, deps: IngestionDeps) -> None:
    version = await _version(session, deps)
    await run_ingestion(version.id, deps)
    await session.refresh(version)  # load "ready" so the reset below is a real UPDATE
    version.status = "queued"
    await session.commit()
    assert await run_ingestion(version.id, deps) is DocumentStatus.READY
    assert await deps.index.count_version(version.id) == 2


async def test_new_version_replaces_old_points(session: AsyncSession, deps: IngestionDeps) -> None:
    v1 = await _version(session, deps)
    await run_ingestion(v1.id, deps)
    document = await session.get(Document, v1.document_id)
    v2 = await _version(session, deps, MD + b"\nNew paragraph.\n", document=document)
    await run_ingestion(v2.id, deps)

    assert await deps.index.count_version(v1.id) == 0
    assert await deps.index.count_version(v2.id) > 0
    await session.refresh(document)
    assert document.current_version_id == v2.id


async def test_late_older_version_does_not_replace_newer(
    session: AsyncSession, deps: IngestionDeps
) -> None:
    v1 = await _version(session, deps)
    document = await session.get(Document, v1.document_id)
    v2 = await _version(session, deps, MD + b"\nNewer.\n", document=document)
    await run_ingestion(v2.id, deps)
    await run_ingestion(v1.id, deps)  # older one finishes last

    await session.refresh(document)
    assert document.current_version_id == v2.id
    assert await deps.index.count_version(v1.id) == 0


async def test_infected_file_is_rejected(session: AsyncSession, deps: IngestionDeps) -> None:
    async def infected(_: bytes) -> None:
        raise VirusFound("Eicar-Test-Signature")

    deps.scan = infected
    version = await _version(session, deps)
    assert await run_ingestion(version.id, deps) is DocumentStatus.REJECTED
    await session.refresh(version)
    assert version.status == "rejected"
    assert "Eicar-Test-Signature" in (version.error or "")
    assert await deps.index.count_version(version.id) == 0


async def test_permanent_error_fails_without_retry(
    session: AsyncSession, deps: IngestionDeps
) -> None:
    def broken(_: bytes, __: str):  # type: ignore[no-untyped-def]
        raise PermanentIngestionError("corrupt file")

    deps.parse = broken
    version = await _version(session, deps)
    assert await run_ingestion(version.id, deps, final_attempt=False) is DocumentStatus.FAILED
    await session.refresh(version)
    assert (version.status, version.failed_stage) == ("failed", "parsing")


async def test_transient_error_requeues_then_fails_on_last_attempt(
    session: AsyncSession, deps: IngestionDeps
) -> None:
    async def flaky(_: list[str]) -> list[list[float]]:
        raise ConnectionError("provider down")

    deps.embed_dense = flaky
    version = await _version(session, deps)
    with pytest.raises(ConnectionError):
        await run_ingestion(version.id, deps, final_attempt=False)
    await session.refresh(version)
    assert version.status == "queued"

    assert await run_ingestion(version.id, deps, final_attempt=True) is DocumentStatus.FAILED
    await session.refresh(version)
    assert (version.status, version.failed_stage) == ("failed", "embedding")
    assert "provider down" in (version.error or "")


async def test_chunk_inspector(
    client: AsyncClient,
    session: AsyncSession,
    engine: AsyncEngine,
    settings: Settings,
    app,  # type: ignore[no-untyped-def]
) -> None:
    deps = IngestionDeps(
        sessionmaker=create_sessionmaker(engine),
        store=app.state.store,
        index=app.state.index,
        scan=_clean,
        parse=parse_document,
        describe_image=_describe,
        embed_dense=DeterministicFakeEmbedding(size=8).aembed_documents,
        embed_sparse=_sparse,
    )
    version = await _version(session, deps)
    await run_ingestion(version.id, deps)
    await make_user(session, username="admin1", role=Role.ADMIN)
    token = await login(client, "admin1")

    response = await client.get(
        f"/api/admin/documents/{version.document_id}/chunks", headers=bearer(token)
    )
    assert response.status_code == 200
    body = response.json()
    assert [c["modality"] for c in body] == ["text", "table"]
    assert body[0]["heading_path"] == ["Handbook", "Leave"]


def test_page_key_layout() -> None:
    version_id = uuid.uuid4()
    assert page_key(version_id, 3) == f"versions/{version_id}/pages/3.png"
    assert Path(page_key(version_id, 3)).suffix == ".png"


async def test_overlapping_ingestions_keep_newest_current(
    session: AsyncSession, deps: IngestionDeps, engine: AsyncEngine, chunk_index: ChunkIndex
) -> None:
    v1 = await _version(session, deps)
    document = await session.get(Document, v1.document_id)
    v2 = await _version(session, deps, MD + b"\nNewer.\n", document=document)
    plain = DeterministicFakeEmbedding(size=8)
    deps_v2 = IngestionDeps(
        sessionmaker=deps.sessionmaker,
        store=deps.store,
        index=deps.index,
        scan=_clean,
        parse=parse_document,
        describe_image=_describe,
        embed_dense=plain.aembed_documents,
        embed_sparse=_sparse,
    )
    calls = 0

    async def overlapping(texts: list[str]) -> list[list[float]]:
        nonlocal calls
        calls += 1
        if calls == 1:
            await run_ingestion(v2.id, deps_v2)
        return await plain.aembed_documents(texts)

    deps.embed_dense = overlapping
    await run_ingestion(v1.id, deps)

    await session.refresh(document)
    assert document.current_version_id == v2.id
    assert await deps.index.count_version(v1.id) == 0
    assert await deps.index.count_version(v2.id) > 0


async def test_cleanup_failure_does_not_undo_ready(
    session: AsyncSession, deps: IngestionDeps, monkeypatch: pytest.MonkeyPatch
) -> None:
    v1 = await _version(session, deps)
    await run_ingestion(v1.id, deps)
    document = await session.get(Document, v1.document_id)
    v2 = await _version(session, deps, MD + b"\nNewer.\n", document=document)

    original = deps.index.delete_version

    async def flaky_delete(version_id: uuid.UUID) -> None:
        if version_id == v1.id:
            raise ConnectionError("qdrant down")
        await original(version_id)

    monkeypatch.setattr(deps.index, "delete_version", flaky_delete)
    assert await run_ingestion(v2.id, deps, final_attempt=False) is DocumentStatus.READY
    await session.refresh(v2)
    await session.refresh(document)
    assert v2.status == "ready"
    assert document.current_version_id == v2.id


async def test_chunk_inspector_version_selection(
    client: AsyncClient,
    session: AsyncSession,
    engine: AsyncEngine,
    app,  # type: ignore[no-untyped-def]
) -> None:
    deps = IngestionDeps(
        sessionmaker=create_sessionmaker(engine),
        store=app.state.store,
        index=app.state.index,
        scan=_clean,
        parse=parse_document,
        describe_image=_describe,
        embed_dense=DeterministicFakeEmbedding(size=8).aembed_documents,
        embed_sparse=_sparse,
    )
    v1 = await _version(session, deps)
    document = await session.get(Document, v1.document_id)
    v2 = await _version(session, deps, MD + b"\nNewer.\n", document=document)
    other = await _version(session, deps)
    for v in (v1, v2, other):
        await run_ingestion(v.id, deps)
    await make_user(session, username="admin2", role=Role.ADMIN)
    headers = bearer(await login(client, "admin2"))
    base = f"/api/admin/documents/{v2.document_id}/chunks"

    current = await client.get(base, headers=headers)
    assert len(current.json()) == await app.state.index.count_version(v2.id)

    # a non-current version of the same document is inspectable via ?version_id=
    await app.state.index.upsert(
        v1.id,
        [
            IndexedChunk(
                position=0,
                text="old",
                dense=[0.1] * 8,
                sparse=SparseVector(indices=[1], values=[1.0]),
                payload={"doc_id": str(v1.document_id), "modality": "text"},
            )
        ],
    )
    older = await client.get(base, params={"version_id": str(v1.id)}, headers=headers)
    assert [c["text"] for c in older.json()] == ["old"]

    foreign = await client.get(base, params={"version_id": str(other.id)}, headers=headers)
    assert foreign.status_code == 200
    assert foreign.json() == []

    unknown = await client.get(f"/api/admin/documents/{uuid.uuid4()}/chunks", headers=headers)
    assert unknown.status_code == 404


async def test_payload_carries_collection_sensitive_flag(
    session: AsyncSession, deps: IngestionDeps
) -> None:
    version = await _version(session, deps)
    document = await session.get(Document, version.document_id)
    assert document is not None
    document.collection.sensitive = True
    await session.commit()
    await run_ingestion(version.id, deps)
    chunks = await deps.index.list_chunks(version.id)
    assert chunks and all(c["sensitive"] is True for c in chunks)


async def test_collection_group_change_during_indexing_is_not_lost(
    session: AsyncSession, deps: IngestionDeps
) -> None:
    from sqlalchemy import select

    from app.documents import service
    from app.users.models import Group

    version = await _version(session, deps)
    document = await session.get(Document, version.document_id)
    assert document is not None
    collection_id = document.collection_id
    keep = await make_group(session, "keep")
    keep_id = keep.id
    old = list(document.collection.groups)
    document.collection.groups = [*old, keep]
    await session.commit()

    real_upsert = deps.index.upsert
    raced = {"done": False}

    async def racing_upsert(version_id: uuid.UUID, chunks: list[IndexedChunk]) -> None:
        if not raced["done"]:
            raced["done"] = True
            async with deps.sessionmaker() as other:
                collection = await other.scalar(
                    select(Collection).where(Collection.id == collection_id)
                )
                assert collection is not None
                collection.groups = [await other.get(Group, keep_id)]
                await other.commit()
                await service.sync_collection_access(other, deps.index, collection_id)
        await real_upsert(version_id, chunks)

    deps.index.upsert = racing_upsert  # type: ignore[method-assign]
    status = await run_ingestion(version.id, deps)
    await session.refresh(version)
    assert status is DocumentStatus.READY, version.error
    chunks = await deps.index.list_chunks(version.id)
    assert chunks and all(c["access_groups"] == [str(keep_id)] for c in chunks)
