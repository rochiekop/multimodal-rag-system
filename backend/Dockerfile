# syntax=docker/dockerfile:1
FROM python:3.12.11-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app

FROM python:3.12.11-slim-bookworm
# Shared libraries needed by OpenCV/onnxruntime (used by Docling's OCR)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/files /app/.cache && chown appuser:appuser /data/files /app /app/.cache
WORKDIR /app
COPY --from=builder --chown=appuser:appuser /app /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/app/.cache/huggingface \
    TIKTOKEN_CACHE_DIR=/app/.cache/tiktoken \
    FASTEMBED_CACHE_PATH=/app/.cache/fastembed \
    RAG_FILES_DIR=/data/files
USER appuser
# Model downloads are cached across rebuilds (BuildKit), then copied into the image layer.
RUN --mount=type=cache,target=/tmp/model-cache,uid=10001,gid=10001 \
    HF_HOME=/tmp/model-cache/huggingface \
    FASTEMBED_CACHE_PATH=/tmp/model-cache/fastembed \
    TIKTOKEN_CACHE_DIR=/tmp/model-cache/tiktoken \
    python -m app.ingestion.warmup \
    && cp -a /tmp/model-cache/. /app/.cache/
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*' --no-access-log"]
