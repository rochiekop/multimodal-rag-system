"""Qdrant storage for chunks: one point per chunk with a dense and a BM25 sparse vector.
Payload carries everything retrieval needs to filter (access groups, deleted, collection)."""

import uuid
from dataclasses import dataclass
from typing import Any

from qdrant_client import AsyncQdrantClient, models

from app.llm.sparse import SparseVector

DENSE = "dense"
SPARSE = "bm25"
_POINT_NAMESPACE = uuid.UUID("6f1c3c1e-8a52-4f8e-9a57-2f0f6a3b9d10")
_KEYWORD_FIELDS = ("doc_id", "version_id", "collection_id", "access_groups")


def point_id(version_id: uuid.UUID, position: int) -> str:
    """Deterministic, so re-running a version overwrites instead of duplicating."""
    return str(uuid.uuid5(_POINT_NAMESPACE, f"{version_id}:{position}"))


def _match(key: str, value: str) -> models.Filter:
    return models.Filter(
        must=[models.FieldCondition(key=key, match=models.MatchValue(value=value))]
    )


@dataclass
class IndexedChunk:
    position: int
    text: str
    dense: list[float]
    sparse: SparseVector
    payload: dict[str, Any]


@dataclass(frozen=True)
class SearchHit:
    score: float
    payload: dict[str, Any]


class ChunkIndex:
    def __init__(self, client: AsyncQdrantClient, collection: str, dimensions: int) -> None:
        self.client = client
        self.collection = collection
        self.dimensions = dimensions
        self._ready = False

    async def ensure_collection(self) -> None:
        if self._ready:
            return
        if not await self.client.collection_exists(self.collection):
            try:
                await self.client.create_collection(
                    self.collection,
                    vectors_config={
                        DENSE: models.VectorParams(
                            size=self.dimensions, distance=models.Distance.COSINE, on_disk=True
                        )
                    },
                    sparse_vectors_config={
                        SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)
                    },
                    quantization_config=models.ScalarQuantization(
                        scalar=models.ScalarQuantizationConfig(
                            type=models.ScalarType.INT8, always_ram=True
                        )
                    ),
                )
            except Exception:
                # A concurrent first caller may have created it; only re-raise if not.
                if not await self.client.collection_exists(self.collection):
                    raise
        # Always ensure indexes (idempotent), so a half-initialised collection heals.
        for field in _KEYWORD_FIELDS:
            await self.client.create_payload_index(
                self.collection, field_name=field, field_schema=models.PayloadSchemaType.KEYWORD
            )
        await self.client.create_payload_index(
            self.collection, field_name="deleted", field_schema=models.PayloadSchemaType.BOOL
        )
        self._ready = True

    async def upsert(self, version_id: uuid.UUID, chunks: list[IndexedChunk]) -> None:
        await self.ensure_collection()
        points = [
            models.PointStruct(
                id=point_id(version_id, c.position),
                vector={
                    DENSE: c.dense,
                    SPARSE: models.SparseVector(indices=c.sparse.indices, values=c.sparse.values),
                },
                payload={
                    **c.payload,
                    "text": c.text,
                    "position": c.position,
                    "version_id": str(version_id),
                },
            )
            for c in chunks
        ]
        for start in range(0, len(points), 128):
            await self.client.upsert(self.collection, points=points[start : start + 128], wait=True)

    async def delete_version(self, version_id: uuid.UUID) -> None:
        await self.ensure_collection()
        await self.client.delete(
            self.collection,
            points_selector=models.FilterSelector(filter=_match("version_id", str(version_id))),
            wait=True,
        )

    async def set_document_access(self, doc_id: uuid.UUID, access_groups: list[str]) -> None:
        await self._set_document_payload(doc_id, {"access_groups": access_groups})

    async def set_document_deleted(self, doc_id: uuid.UUID, deleted: bool) -> None:
        await self._set_document_payload(doc_id, {"deleted": deleted})

    async def set_document_sensitive(self, doc_id: uuid.UUID, sensitive: bool) -> None:
        await self._set_document_payload(doc_id, {"sensitive": sensitive})

    async def _set_document_payload(self, doc_id: uuid.UUID, payload: dict[str, Any]) -> None:
        await self.ensure_collection()
        await self.client.set_payload(
            self.collection,
            payload=payload,
            points=models.FilterSelector(filter=_match("doc_id", str(doc_id))),
            wait=True,
        )

    async def list_chunks(self, version_id: uuid.UUID, limit: int = 1000) -> list[dict[str, Any]]:
        await self.ensure_collection()
        records, _ = await self.client.scroll(
            self.collection,
            scroll_filter=_match("version_id", str(version_id)),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        payloads = [dict(r.payload or {}) for r in records]
        return sorted(payloads, key=lambda p: int(p.get("position", 0)))

    async def count_version(self, version_id: uuid.UUID) -> int:
        await self.ensure_collection()
        result = await self.client.count(
            self.collection, count_filter=_match("version_id", str(version_id)), exact=True
        )
        return result.count

    async def search(
        self,
        dense: list[float],
        sparse: SparseVector,
        *,
        access_groups: list[str],
        collection_ids: list[str],
        limit: int,
    ) -> list[SearchHit]:
        """Hybrid search: dense and BM25 candidates fused with RRF, pre-filtered by the
        caller's groups and collections. Callers must still re-check hits in Postgres."""
        await self.ensure_collection()
        allowed = models.Filter(
            must=[
                models.FieldCondition(
                    key="access_groups", match=models.MatchAny(any=access_groups)
                ),
                models.FieldCondition(
                    key="collection_id", match=models.MatchAny(any=collection_ids)
                ),
                models.FieldCondition(key="deleted", match=models.MatchValue(value=False)),
            ]
        )
        prefetch = [models.Prefetch(query=dense, using=DENSE, filter=allowed, limit=limit)]
        if sparse.indices:  # a query of only stop-words has no BM25 terms
            prefetch.append(
                models.Prefetch(
                    query=models.SparseVector(indices=sparse.indices, values=sparse.values),
                    using=SPARSE,
                    filter=allowed,
                    limit=limit,
                )
            )
        response = await self.client.query_points(
            self.collection,
            prefetch=prefetch,
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            query_filter=allowed,
            limit=limit,
            with_payload=True,
        )
        return [SearchHit(score=p.score, payload=dict(p.payload or {})) for p in response.points]
