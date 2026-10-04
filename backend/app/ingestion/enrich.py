import asyncio
from collections.abc import Awaitable, Callable

from app.ingestion.chunking import ChunkDraft


async def enrich_figures(
    chunks: list[ChunkDraft],
    describe: Callable[[bytes], Awaitable[str]],
    *,
    max_concurrency: int = 4,
) -> list[ChunkDraft]:
    """Adds a searchable description to every figure that has an image."""
    semaphore = asyncio.Semaphore(max_concurrency)

    async def describe_one(chunk: ChunkDraft) -> None:
        assert chunk.figure_png is not None
        async with semaphore:
            description = (await describe(chunk.figure_png)).strip()
        chunk.text = "\n\n".join(part for part in (chunk.text, description) if part)

    await asyncio.gather(
        *(describe_one(c) for c in chunks if c.modality == "figure" and c.figure_png)
    )
    return [c for c in chunks if c.text.strip()]
