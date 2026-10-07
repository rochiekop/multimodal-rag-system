"""Numbered sources for the prompt, source cards for the client, and citation cleanup."""

import re
from typing import Any

from app.ingestion.parse import PAGE_IMAGE_SCALE
from app.retrieval.search import RetrievedChunk

SNIPPET_CHARS = 300
_CITATION = re.compile(r"(\s?)\[(\d+(?:\s*,\s*\d+)*)\]")


def _attr(value: str) -> str:
    return value.replace('"', "'").replace("\n", " ")


def format_sources(chunks: list[RetrievedChunk]) -> str:
    """Delimited source blocks. A closing tag inside chunk text is escaped so document text
    cannot end its block early and pose as instructions."""
    blocks = []
    for n, chunk in enumerate(chunks, start=1):
        page = f' page="{chunk.page}"' if chunk.page is not None else ""
        section = _attr(" › ".join(chunk.heading_path))
        body = chunk.text.replace("</source", "&lt;/source")
        blocks.append(
            f'<source id="{n}" document="{_attr(chunk.filename)}"{page} section="{section}">\n'
            f"{body}\n</source>"
        )
    return "\n\n".join(blocks)


def source_card(n: int, chunk: RetrievedChunk) -> dict[str, Any]:
    """What the client needs to render a citation: bbox is in page points (top-left origin);
    multiply by page_image_scale to get pixels on the page image."""
    return {
        "n": n,
        "doc_id": str(chunk.doc_id),
        "version_id": str(chunk.version_id),
        "filename": chunk.filename,
        "page": chunk.page,
        "bbox": chunk.bbox,
        "page_image_scale": PAGE_IMAGE_SCALE if chunk.page is not None else None,
        "heading_path": chunk.heading_path,
        "modality": chunk.modality,
        "score": round(chunk.score, 4),
        "snippet": chunk.text[:SNIPPET_CHARS],
    }


def clean_citations(text: str, source_count: int) -> tuple[str, list[int]]:
    """Drop citation numbers that match no source. Returns the cleaned text and the source
    numbers actually cited, in order of first use."""
    used: list[int] = []

    def replace(match: re.Match[str]) -> str:
        numbers = [int(n) for n in re.split(r"\s*,\s*", match.group(2))]
        valid = [n for n in numbers if 1 <= n <= source_count]
        for n in valid:
            if n not in used:
                used.append(n)
        return match.group(1) + "".join(f"[{n}]" for n in valid) if valid else ""

    return _CITATION.sub(replace, text), used
