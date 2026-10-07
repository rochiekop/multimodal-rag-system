"""Tracing helpers. Without a configured provider OpenTelemetry is a no-op and no trace ID
is recorded."""

from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import trace

_tracer = trace.get_tracer("rag")


@contextmanager
def answer_span(name: str) -> Iterator[str | None]:
    """A span around one answer; LangChain spans nest under it. Yields its trace ID."""
    with _tracer.start_as_current_span(name) as span:
        context = span.get_span_context()
        yield format(context.trace_id, "032x") if context.is_valid else None
