"""Docling conversion. CPU-heavy and synchronous: callers run it in a worker thread."""

import io
from dataclasses import dataclass
from functools import lru_cache
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from app.documents.filetypes import EXTENSIONS
from app.ingestion.errors import PermanentIngestionError

if TYPE_CHECKING:
    from docling.document_converter import DocumentConverter
    from docling_core.types.doc import DoclingDocument

PAGE_IMAGE_SCALE = 1.5  # ~108 dpi previews; enough to read and highlight citations


class ParseError(PermanentIngestionError):
    pass


@dataclass
class ParsedPage:
    page_no: int
    width: float
    height: float
    png: bytes | None


@dataclass
class ParsedDocument:
    doc: "DoclingDocument"
    pages: list[ParsedPage]


@lru_cache(maxsize=1)
def _converter() -> "DocumentConverter":
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import (
        DocumentConverter,
        ImageFormatOption,
        PdfFormatOption,
    )

    options = PdfPipelineOptions(
        generate_page_images=True, generate_picture_images=True, images_scale=PAGE_IMAGE_SCALE
    )
    return DocumentConverter(
        allowed_formats=[
            InputFormat.PDF,
            InputFormat.IMAGE,
            InputFormat.DOCX,
            InputFormat.PPTX,
            InputFormat.XLSX,
            InputFormat.CSV,
            InputFormat.MD,
            InputFormat.HTML,
        ],
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=options),
            InputFormat.IMAGE: ImageFormatOption(pipeline_options=options),
        },
    )


def _stream_name(filename: str) -> str:
    suffix = PurePosixPath(filename.lower()).suffix
    kind = EXTENSIONS.get(suffix)
    if kind is None:
        raise ParseError(f"Unsupported file type: {suffix}")
    # Docling picks the backend from the name; .txt goes through the Markdown backend.
    return "document" + (".md" if kind == "md" else suffix)


def _png(image: object) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)  # type: ignore[attr-defined]
    return buffer.getvalue()


def parse_document(data: bytes, filename: str) -> ParsedDocument:
    from docling.datamodel.base_models import ConversionStatus, DocumentStream

    stream = DocumentStream(name=_stream_name(filename), stream=io.BytesIO(data))
    try:
        result = _converter().convert(stream, raises_on_error=False)
    except Exception as exc:  # Docling raises various backend errors on corrupt input
        raise ParseError(f"Could not read document: {exc}") from exc
    if result.status not in (ConversionStatus.SUCCESS, ConversionStatus.PARTIAL_SUCCESS):
        reasons = "; ".join(str(e.error_message) for e in result.errors) or result.status.name
        raise ParseError(f"Could not read document: {reasons}")

    pages = []
    for page_no, page in sorted(result.document.pages.items()):
        image = page.image.pil_image if page.image is not None else None
        pages.append(
            ParsedPage(
                page_no=page_no,
                width=page.size.width,
                height=page.size.height,
                png=_png(image) if image is not None else None,
            )
        )
    return ParsedDocument(doc=result.document, pages=pages)
