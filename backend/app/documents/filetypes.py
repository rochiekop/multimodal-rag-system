"""Upload validation: the real type is checked from content, never trusted from the name."""

import io
import zipfile
from pathlib import PurePosixPath

EXTENSIONS: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
    ".csv": "csv",
    ".md": "md",
    ".markdown": "md",
    ".txt": "md",  # Docling reads plain text through its Markdown backend
    ".html": "html",
    ".htm": "html",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".tif": "image",
    ".tiff": "image",
}

CONTENT_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "md": "text/markdown",
    "html": "text/html",
    "image": "image/*",
}

_OFFICE_PREFIX = {"docx": "word/", "pptx": "ppt/", "xlsx": "xl/"}
_IMAGE_MAGIC = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"II*\x00", b"MM\x00*")
_MAX_ARCHIVE_ENTRIES = 10_000
_MAX_UNCOMPRESSED = 500 * 1024 * 1024


class FileTypeError(ValueError):
    pass


def sanitize_filename(name: str) -> str:
    """Keep only the final path component; strip control characters."""
    base = PurePosixPath(name.replace("\\", "/")).name
    cleaned = "".join(ch for ch in base if ch.isprintable()).strip()
    if not cleaned or cleaned in {".", ".."}:
        raise FileTypeError("Missing file name")
    return cleaned[:255]


def detect_kind(filename: str, data: bytes) -> str:
    kind = EXTENSIONS.get(PurePosixPath(filename.lower()).suffix)
    if kind is None:
        raise FileTypeError("Unsupported file type")
    if not data:
        raise FileTypeError("File is empty")
    if kind == "pdf" and not data.startswith(b"%PDF-"):
        raise FileTypeError("File content is not a PDF")
    if kind in _OFFICE_PREFIX:
        _check_office(data, _OFFICE_PREFIX[kind])
    if kind == "image" and not data.startswith(_IMAGE_MAGIC):
        raise FileTypeError("File content is not a PNG, JPEG or TIFF image")
    if kind in ("md", "csv", "html"):
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise FileTypeError("Text files must be UTF-8") from None
        if "\x00" in text:
            raise FileTypeError("Text file contains binary data")
    return kind


def _check_office(data: bytes, prefix: str) -> None:
    if not data.startswith(b"PK\x03\x04"):
        raise FileTypeError("File content is not an Office document")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
    except zipfile.BadZipFile:
        raise FileTypeError("Office document is corrupt") from None
    if len(entries) > _MAX_ARCHIVE_ENTRIES or sum(e.file_size for e in entries) > _MAX_UNCOMPRESSED:
        raise FileTypeError("Office document expands to an unsafe size")
    if not any(e.filename.startswith(prefix) for e in entries):
        raise FileTypeError("File content does not match its extension")
