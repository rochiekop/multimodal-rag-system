"""BM25 sparse vectors computed locally (no API): the keyword half of hybrid search."""

from dataclasses import dataclass
from functools import lru_cache

from fastembed import SparseTextEmbedding


@dataclass(frozen=True)
class SparseVector:
    indices: list[int]
    values: list[float]


@lru_cache(maxsize=1)
def _model() -> SparseTextEmbedding:
    return SparseTextEmbedding("Qdrant/bm25")


def embed_sparse_documents(texts: list[str]) -> list[SparseVector]:
    return [
        SparseVector(indices=e.indices.tolist(), values=e.values.tolist())
        for e in _model().embed(texts)
    ]


def embed_sparse_query(text: str) -> SparseVector:
    embedding = next(iter(_model().query_embed(text)))
    return SparseVector(indices=embedding.indices.tolist(), values=embedding.values.tolist())
