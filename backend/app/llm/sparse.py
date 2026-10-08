"""BM25 sparse vectors computed locally (no API): the keyword half of hybrid search."""

import os
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fastembed import SparseTextEmbedding


@dataclass(frozen=True)
class SparseVector:
    indices: list[int]
    values: list[float]


def cached_bm25_path() -> str | None:
    """fastembed's BM25 model has no weights file, so its cache check always fails and it asks
    HuggingFace even when the model is cached. Point it at the cached snapshot when we have one."""
    root = Path(
        os.environ.get("FASTEMBED_CACHE_PATH") or Path(tempfile.gettempdir()) / "fastembed_cache"
    )
    repo = root / "models--Qdrant--bm25"
    ref = repo / "refs" / "main"
    snapshots = repo / "snapshots"
    if ref.is_file() and (snapshots / ref.read_text().strip()).is_dir():
        return str(snapshots / ref.read_text().strip())
    found = sorted(snapshots.iterdir()) if snapshots.is_dir() else []
    return str(found[0]) if found else None


@lru_cache(maxsize=1)
def _model() -> SparseTextEmbedding:
    return SparseTextEmbedding("Qdrant/bm25", specific_model_path=cached_bm25_path())


def embed_sparse_documents(texts: list[str]) -> list[SparseVector]:
    return [
        SparseVector(indices=e.indices.tolist(), values=e.values.tolist())
        for e in _model().embed(texts)
    ]


def embed_sparse_query(text: str) -> SparseVector:
    embedding = next(iter(_model().query_embed(text)))
    return SparseVector(indices=embedding.indices.tolist(), values=embedding.values.tolist())
