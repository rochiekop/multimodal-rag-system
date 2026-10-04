import io

import pytest
from docling_core.types.doc import DocItemLabel, DoclingDocument, ImageRef
from PIL import Image

from app.ingestion.chunking import ChunkDraft, build_chunks, embedding_text
from app.ingestion.enrich import enrich_figures
from app.ingestion.parse import ParseError, parse_document

MD = b"""# Employee Handbook

## Leave

Employees get 20 days of annual leave.

| Type | Days |
|------|------|
| Annual | 20 |
| Sick | 10 |

## Travel

### Flights

Economy class for flights under 6 hours.
"""


def test_markdown_becomes_heading_aware_chunks() -> None:
    parsed = parse_document(MD, "handbook.md")
    chunks = build_chunks(parsed.doc)

    texts = [(c.modality, c.heading_path, c.text) for c in chunks]
    assert texts[0] == (
        "text",
        ["Employee Handbook", "Leave"],
        "Employees get 20 days of annual leave.",
    )
    table = chunks[1]
    assert table.modality == "table"
    assert table.heading_path == ["Employee Handbook", "Leave"]
    assert "| Annual" in table.text and "| 20" in table.text
    assert chunks[2].heading_path == ["Employee Handbook", "Travel", "Flights"]
    assert parsed.pages == []  # Markdown has no pages


def test_txt_is_read_as_text() -> None:
    chunks = build_chunks(parse_document(b"plain line one\nline two", "notes.txt").doc)
    assert "plain line one" in chunks[0].text


def test_long_text_is_split_with_overlap() -> None:
    sentence = "The quarterly revenue grew in every region. "
    parsed = parse_document(b"# Report\n\n" + (sentence * 200).encode(), "report.md")
    chunks = build_chunks(parsed.doc, max_tokens=100, overlap_tokens=20)
    assert len(chunks) > 5
    assert all(c.heading_path == ["Report"] for c in chunks)
    tail_of_first = chunks[0].text.split()[-3:]
    assert " ".join(tail_of_first) in chunks[1].text  # overlap carries context across


def test_figures_become_their_own_chunks_and_get_described() -> None:
    doc = DoclingDocument(name="deck")
    doc.add_heading("Results", level=1)
    caption = doc.add_text(label=DocItemLabel.CAPTION, text="Figure 1: Revenue by region")
    doc.add_picture(
        image=ImageRef.from_pil(Image.new("RGB", (400, 300), "blue"), dpi=72), caption=caption
    )
    doc.add_picture(
        image=ImageRef.from_pil(Image.new("RGB", (20, 20), "red"), dpi=72)
    )  # icon: skipped
    doc.add_text(label=DocItemLabel.PAGE_FOOTER, text="Confidential - page 3")  # skipped

    chunks = build_chunks(doc)
    figures = [c for c in chunks if c.modality == "figure"]
    assert len(figures) == 1
    assert figures[0].text == "Figure 1: Revenue by region"
    assert figures[0].figure_png is not None
    assert Image.open(io.BytesIO(figures[0].figure_png)).size == (400, 300)
    assert not any("Confidential" in c.text for c in chunks)


async def test_enrich_figures_appends_description() -> None:
    chunks = [
        ChunkDraft("Figure 1", "figure", ["Results"], 1, None, figure_png=b"png"),
        ChunkDraft("", "figure", [], None, None, figure_png=None),  # nothing to say: dropped
        ChunkDraft("body", "text", [], None, None),
    ]

    async def describe(png: bytes) -> str:
        assert png == b"png"
        return "Bar chart; APAC highest at $4.2M."

    enriched = await enrich_figures(chunks, describe)
    assert [c.text for c in enriched] == ["Figure 1\n\nBar chart; APAC highest at $4.2M.", "body"]


def test_embedding_text_has_context_header() -> None:
    chunk = ChunkDraft("Economy class only.", "text", ["Employee Handbook", "Travel"], None, None)
    assert (
        embedding_text(chunk, "handbook")
        == "handbook › Employee Handbook › Travel\n\nEconomy class only."
    )


def test_corrupt_pdf_is_a_parse_error() -> None:
    with pytest.raises(ParseError):
        parse_document(b"%PDF-1.7 this is not really a pdf", "broken.pdf")


@pytest.mark.slow
def test_scanned_pdf_gets_ocr_text_pages_and_positions() -> None:
    """Runs Docling's layout + OCR models (downloads ~500 MB the first time)."""
    from PIL import ImageDraw

    page = Image.new("RGB", (1240, 1754), "white")
    ImageDraw.Draw(page).text((100, 200), "Annual leave is twenty days", fill="black", font_size=40)
    buffer = io.BytesIO()
    page.save(buffer, format="PDF")

    parsed = parse_document(buffer.getvalue(), "scan.pdf")
    assert len(parsed.pages) == 1 and parsed.pages[0].png is not None
    chunks = build_chunks(parsed.doc)
    assert any("twenty days" in c.text.lower() for c in chunks)
    assert chunks[0].page == 1 and chunks[0].bbox is not None


def test_heading_only_document_keeps_headings_as_text() -> None:
    chunks = build_chunks(parse_document(b"# A\n\n## B", "h.md").doc)
    assert [c.text for c in chunks] == ["A", "B"]
    assert all(c.modality == "text" for c in chunks)


def test_table_markdown_has_no_padding_runs() -> None:
    table = build_chunks(parse_document(MD, "handbook.md").doc)[1]
    assert "  " not in table.text
    assert "|---" in table.text and table.text.startswith("| Type")


class _FakeConverter:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def convert(self, *args: object, **kwargs: object) -> object:
        raise self.exc


def test_transient_errors_propagate_from_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.ingestion.parse._converter", lambda: _FakeConverter(OSError("disk")))
    with pytest.raises(OSError):
        parse_document(b"x", "a.md")
    monkeypatch.setattr("app.ingestion.parse._converter", lambda: _FakeConverter(MemoryError()))
    with pytest.raises(MemoryError):
        parse_document(b"x", "a.md")


def test_converter_construction_errors_propagate(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> object:
        raise RuntimeError("model load failed")

    monkeypatch.setattr("app.ingestion.parse._converter", boom)
    with pytest.raises(RuntimeError) as info:
        parse_document(b"x", "a.md")
    assert not isinstance(info.value, ParseError)


def test_other_conversion_errors_are_parse_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.ingestion.parse._converter", lambda: _FakeConverter(RuntimeError("bad file"))
    )
    with pytest.raises(ParseError):
        parse_document(b"x", "a.md")
