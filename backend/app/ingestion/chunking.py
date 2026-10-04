"""Structure-aware chunking over a Docling document.
Text is grouped under its heading path and split by tokens with overlap; every table and
figure becomes its own chunk (never split), tables as Markdown (spec §3.3)."""

import io
import re
from dataclasses import dataclass
from typing import Literal

import tiktoken
from docling_core.types.doc import (
    DocItemLabel,
    DoclingDocument,
    PictureItem,
    SectionHeaderItem,
    TableItem,
    TextItem,
    TitleItem,
)

_ENCODING = tiktoken.get_encoding("cl100k_base")
_SKIP_LABELS = {DocItemLabel.PAGE_HEADER, DocItemLabel.PAGE_FOOTER, DocItemLabel.CAPTION}
_MIN_FIGURE_PIXELS = 120 * 120  # smaller pictures are icons/logos: not worth describing
_MAX_EMBED_TOKENS = 8000

Modality = Literal["text", "table", "figure"]


@dataclass
class ChunkDraft:
    text: str
    modality: Modality
    heading_path: list[str]
    page: int | None
    bbox: dict[str, float] | None
    figure_png: bytes | None = None


def _tokens(text: str) -> int:
    return len(_ENCODING.encode(text))


def _split(text: str, max_tokens: int, overlap: int) -> list[str]:
    tokens = _ENCODING.encode(text)
    if len(tokens) <= max_tokens:
        return [text]
    step = max(max_tokens - overlap, 1)
    starts = range(0, max(len(tokens) - overlap, 1), step)
    return [_ENCODING.decode(tokens[s : s + max_tokens]) for s in starts]


def _location(item: object, doc: DoclingDocument) -> tuple[int | None, dict[str, float] | None]:
    prov = getattr(item, "prov", None)
    if not prov:
        return None, None
    first = prov[0]
    page = doc.pages.get(first.page_no)
    if page is None:
        return first.page_no, None
    box = first.bbox.to_top_left_origin(page_height=page.size.height)
    return first.page_no, {"l": box.l, "t": box.t, "r": box.r, "b": box.b}


def _png(image: object) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")  # type: ignore[attr-defined]
    return buffer.getvalue()


def build_chunks(
    doc: DoclingDocument, *, max_tokens: int = 500, overlap_tokens: int = 50
) -> list[ChunkDraft]:
    chunks: list[ChunkDraft] = []
    title: str | None = None
    sections: list[str] = []
    buffer: list[str] = []
    buffer_loc: tuple[int | None, dict[str, float] | None] = (None, None)
    headings: list[ChunkDraft] = []  # fallback when a document is nothing but headings

    def heading_path() -> list[str]:
        return ([title] if title else []) + sections

    def flush() -> None:
        nonlocal buffer
        if buffer:
            for part in _split("\n".join(buffer), max_tokens, overlap_tokens):
                chunks.append(ChunkDraft(part, "text", heading_path(), *buffer_loc))
        buffer = []

    for item, _level in doc.iterate_items():
        if isinstance(item, TitleItem):
            flush()
            headings.append(ChunkDraft(item.text.strip(), "text", [], *_location(item, doc)))
            title, sections = item.text.strip(), []
        elif isinstance(item, SectionHeaderItem):
            flush()
            headings.append(
                ChunkDraft(item.text.strip(), "text", heading_path(), *_location(item, doc))
            )
            sections = sections[: max(item.level - 1, 0)] + [item.text.strip()]
        elif isinstance(item, TableItem):
            flush()
            caption = item.caption_text(doc).strip()
            # tabulate pads cells for alignment; collapse it (wasted tokens, noisy embeddings)
            markdown = re.sub(r" {2,}", " ", item.export_to_markdown(doc=doc))
            text = f"{caption}\n\n{markdown}" if caption else markdown
            chunks.append(ChunkDraft(text, "table", heading_path(), *_location(item, doc)))
        elif isinstance(item, PictureItem):
            flush()
            image = item.get_image(doc)
            if image is not None and image.width * image.height < _MIN_FIGURE_PIXELS:
                image = None
            caption = item.caption_text(doc).strip()
            if image is None and not caption:
                continue
            chunks.append(
                ChunkDraft(
                    caption,
                    "figure",
                    heading_path(),
                    *_location(item, doc),
                    figure_png=_png(image) if image is not None else None,
                )
            )
        elif isinstance(item, TextItem):
            text = item.text.strip()
            if not text or item.label in _SKIP_LABELS:
                continue
            if buffer and _tokens("\n".join([*buffer, text])) > max_tokens:
                flush()
            if not buffer:
                buffer_loc = _location(item, doc)
            buffer.append(text)
    flush()
    if not chunks:
        # e.g. a one-line scan that layout analysis labelled as a heading: keep its text
        chunks = [h for h in headings if h.text]
    return chunks


def embedding_text(chunk: ChunkDraft, title: str) -> str:
    """Context header ("Doc › Section › Sub") + text; noticeably improves retrieval."""
    path = [title, *[h for h in chunk.heading_path if h != title]]
    text = f"{' › '.join(path)}\n\n{chunk.text}"
    tokens = _ENCODING.encode(text)
    return (
        text if len(tokens) <= _MAX_EMBED_TOKENS else _ENCODING.decode(tokens[:_MAX_EMBED_TOKENS])
    )
