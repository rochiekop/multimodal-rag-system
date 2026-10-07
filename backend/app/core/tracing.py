"""Tracing helpers. Without a configured provider OpenTelemetry is a no-op and no trace ID
is recorded."""

from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import trace

from app.core.config import Settings

_tracer = trace.get_tracer("rag")
_configured = False


def setup_tracing(settings: Settings) -> None:
    """Send OpenTelemetry traces (including LangChain auto-instrumentation) to Phoenix."""
    global _configured
    if _configured or not settings.phoenix_endpoint:
        return
    from phoenix.otel import register  # imported only when tracing is on

    register(
        project_name=settings.phoenix_project,
        endpoint=settings.phoenix_endpoint,
        batch=True,
        auto_instrument=True,
    )
    _configured = True


@contextmanager
def answer_span(name: str) -> Iterator[str | None]:
    """A span around one answer; LangChain spans nest under it. Yields its trace ID."""
    with _tracer.start_as_current_span(name) as span:
        context = span.get_span_context()
        yield format(context.trace_id, "032x") if context.is_valid else None
