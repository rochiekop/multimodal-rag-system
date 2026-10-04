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
from app.ingestion.index import ChunkIndex
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
