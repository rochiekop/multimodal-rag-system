"""Local cross-encoder reranker (fastembed, CPU, no API key). Raw scores are logits; a
sigmoid maps them to 0..1 so RagConfig.rerank_threshold reads like a probability."""

import asyncio
import math
from functools import lru_cache

from fastembed.rerank.cross_encoder import TextCrossEncoder


@lru_cache(maxsize=2)
def cross_encoder(model: str) -> TextCrossEncoder:
    return TextCrossEncoder(model)


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)  # stable for very negative logits
    return e / (1.0 + e)


async def rerank(model: str, query: str, documents: list[str]) -> list[float]:
    if not documents:
        return []
    raw = await asyncio.to_thread(lambda: list(cross_encoder(model).rerank(query, documents)))
    return [_sigmoid(float(score)) for score in raw]
