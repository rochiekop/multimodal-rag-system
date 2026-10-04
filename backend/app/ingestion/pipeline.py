"""One document version through scan → parse → enrich → chunk → embed → index.
Status is committed at every stage so the admin console shows live progress."""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit import service as audit
from app.core.storage import FileStore
from app.documents.access import effective_access_groups
from app.documents.models import Document, DocumentStatus, DocumentVersion
from app.documents.service import original_key
from app.ingestion.chunking import build_chunks, embedding_text
from app.ingestion.enrich import enrich_figures
from app.ingestion.errors import PermanentIngestionError
from app.ingestion.index import ChunkIndex, IndexedChunk
from app.ingestion.parse import ParsedDocument
from app.ingestion.scan import VirusFound
from app.llm.sparse import SparseVector

logger = logging.getLogger(__name__)

_DONE = {DocumentStatus.READY.value, DocumentStatus.REJECTED.value}


@dataclass
class IngestionDeps:
    sessionmaker: async_sessionmaker[AsyncSession]
    store: FileStore
    index: ChunkIndex
    scan: Callable[[bytes], Awaitable[None]]
    parse: Callable[[bytes, str], ParsedDocument]
    describe_image: Callable[[bytes], Awaitable[str]]
    embed_dense: Callable[[list[str]], Awaitable[list[list[float]]]]
    embed_sparse: Callable[[list[str]], list[SparseVector]]
    max_tokens: int = 500
    overlap_tokens: int = 50


def page_key(version_id: uuid.UUID, page_no: int) -> str:
    return f"versions/{version_id}/pages/{page_no}.png"


def figure_key(version_id: uuid.UUID, position: int) -> str:
    return f"versions/{version_id}/figures/{position}.png"


async def run_ingestion(
    version_id: uuid.UUID, deps: IngestionDeps, *, final_attempt: bool = True
) -> DocumentStatus:
    progress = {"stage": DocumentStatus.SCANNING.value}
    try:
        return await _process(version_id, deps, progress)
    except VirusFound as exc:
        await _finish(deps, version_id, DocumentStatus.REJECTED, progress["stage"], str(exc))
        return DocumentStatus.REJECTED
    except Exception as exc:
        permanent = isinstance(exc, PermanentIngestionError)
        message = f"{type(exc).__name__}: {exc}"
        if permanent or final_attempt:
            await _finish(deps, version_id, DocumentStatus.FAILED, progress["stage"], message)
            return DocumentStatus.FAILED
        await _finish(deps, version_id, DocumentStatus.QUEUED, progress["stage"], message)
        raise  # transient: let Celery retry


async def _process(
    version_id: uuid.UUID, deps: IngestionDeps, progress: dict[str, str]
) -> DocumentStatus:
    async with deps.sessionmaker() as session:
        version = await session.get(DocumentVersion, version_id)
        if version is None:
            raise PermanentIngestionError(f"Version {version_id} not found")
        if version.status in _DONE:
            return DocumentStatus(version.status)
        document = await session.get(Document, version.document_id)
        assert document is not None

        async def advance(stage: DocumentStatus) -> None:
            progress["stage"] = stage.value
            version.status = stage.value
            await session.commit()

        await advance(DocumentStatus.SCANNING)
        data = await asyncio.to_thread(deps.store.read, original_key(version.id))
        await deps.scan(data)

        await advance(DocumentStatus.PARSING)
        parsed = await asyncio.to_thread(deps.parse, data, document.filename)
        for page in parsed.pages:
            if page.png is not None:
                await asyncio.to_thread(
                    deps.store.save, page_key(version.id, page.page_no), page.png
                )
        version.page_count = len(parsed.pages) or None

        await advance(DocumentStatus.ENRICHING)
        drafts = build_chunks(
            parsed.doc, max_tokens=deps.max_tokens, overlap_tokens=deps.overlap_tokens
        )
        drafts = await enrich_figures(drafts, deps.describe_image)

        await advance(DocumentStatus.CHUNKING)
        title = PurePosixPath(document.filename).stem
        texts = [embedding_text(d, title) for d in drafts]
        for position, draft in enumerate(drafts):
            if draft.figure_png is not None:
                await asyncio.to_thread(
                    deps.store.save, figure_key(version.id, position), draft.figure_png
                )

        await advance(DocumentStatus.EMBEDDING)
        dense = await deps.embed_dense(texts) if texts else []
        sparse = await asyncio.to_thread(deps.embed_sparse, texts) if texts else []

        await advance(DocumentStatus.INDEXING)
        # The document was loaded long ago; lock and re-read it so the swap decision and the
        # payload (access, deleted flag) reflect concurrent ingestions, restrictions and deletes.
        await session.execute(
            select(Document)
            .where(Document.id == document.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        base = {
            "doc_id": str(document.id),
            "collection_id": str(document.collection_id),
            "filename": document.filename,
            "access_groups": effective_access_groups(document),
            "deleted": document.deleted_at is not None,
            "sensitive": document.collection.sensitive,
        }
        chunks = [
            IndexedChunk(
                position=i,
                text=d.text,
                dense=dense[i],
                sparse=sparse[i],
                payload={
                    **base,
                    "modality": d.modality,
                    "heading_path": d.heading_path,
                    "page": d.page,
                    "bbox": d.bbox,
                    "has_figure_image": d.figure_png is not None,
                },
            )
            for i, d in enumerate(drafts)
        ]
        await deps.index.delete_version(version.id)  # makes re-runs idempotent
        await deps.index.upsert(version.id, chunks)

        previous = (
            await session.get(DocumentVersion, document.current_version_id)
            if document.current_version_id
            else None
        )
        superseded = previous is not None and previous.version_no > version.version_no
        if not superseded:
            document.current_version_id = version.id
        version.status = DocumentStatus.READY.value
        version.chunk_count = len(chunks)
        version.error = None
        version.failed_stage = None
        await audit.record(
            session,
            action="document.indexed",
            target_type="document",
            target_id=document.id,
            detail={"version": version.version_no, "chunks": len(chunks), "superseded": superseded},
        )
        await session.commit()

        await _resync_payload(deps, document.id)

        # Old points go only after the new ones exist, so search never has a gap.
        stale_id = (
            version.id
            if superseded
            else previous.id
            if previous is not None and previous.id != version.id
            else None
        )
        if stale_id is not None:
            try:
                await deps.index.delete_version(stale_id)
            except Exception:
                # The version is already serving; never let cleanup undo that.
                logger.warning(
                    "Failed to delete stale points for version %s", stale_id, exc_info=True
                )
        return DocumentStatus.READY


async def _resync_payload(deps: IngestionDeps, document_id: uuid.UUID) -> None:
    """Collection access can change while we index (the worker only locks the document row),
    so re-read the live values in a fresh transaction and push them to the new points."""
    try:
        async with deps.sessionmaker() as session:
            document = await session.get(Document, document_id)
            if document is None:
                return
            groups = effective_access_groups(document)
            deleted = document.deleted_at is not None
            sensitive = document.collection.sensitive
        await deps.index.set_document_access(document_id, groups)
        await deps.index.set_document_deleted(document_id, deleted)
        await deps.index.set_document_sensitive(document_id, sensitive)
    except Exception:
        logger.warning("Failed to resync payload for document %s", document_id, exc_info=True)


async def _finish(
    deps: IngestionDeps,
    version_id: uuid.UUID,
    status: DocumentStatus,
    stage: str,
    error: str,
) -> None:
    async with deps.sessionmaker() as session:
        version = await session.get(DocumentVersion, version_id)
        if version is None:
            return
        version.status = status.value
        version.failed_stage = stage
        version.error = error[:1000]
        if status is not DocumentStatus.QUEUED:
            await audit.record(
                session,
                action=f"document.{status.value}",
                target_type="document",
                target_id=version.document_id,
                detail={"version": version.version_no, "stage": stage, "error": error[:300]},
            )
        await session.commit()
