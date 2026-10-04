"""Run at image build time so no model is downloaded while serving requests:
Docling layout/table/OCR models, the BM25 model and the tiktoken encoding."""

import io

from PIL import Image, ImageDraw

from app.ingestion.chunking import build_chunks
from app.ingestion.parse import parse_document
from app.llm.sparse import embed_sparse_documents


def main() -> None:
    page = Image.new("RGB", (1240, 1754), "white")
    ImageDraw.Draw(page).text((100, 200), "Warm up the models", fill="black", font_size=40)
    buffer = io.BytesIO()
    page.save(buffer, format="PDF")
    parsed = parse_document(buffer.getvalue(), "warmup.pdf")
    build_chunks(parsed.doc)
    embed_sparse_documents(["warm up"])
    print("models ready")


if __name__ == "__main__":
    main()
