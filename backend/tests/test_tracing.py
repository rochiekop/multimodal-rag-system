import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.chat.answer import answer
from app.chat.models import Conversation, Message
from app.core import tracing
from app.core.config import Settings
from app.core.db import create_sessionmaker
from app.ingestion.index import ChunkIndex
from tests.factories import chat_deps, make_collection, make_group, make_user, seed_document


async def test_answer_stores_its_trace_id(
    engine: AsyncEngine,
    session: AsyncSession,
    chunk_index: ChunkIndex,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(tracing, "_tracer", provider.get_tracer("test"))

    hr = await make_group(session, "hr")
    alice = await make_user(session, username="alice", groups=[hr])
    coll = await make_collection(session, "HR", [hr])
    await seed_document(session, chunk_index, coll, ["Annual leave is 25 days."])
    conversation = Conversation(user_id=alice.id, title="t")
    session.add(conversation)
    await session.commit()

    events = [
        e
        async for e in answer(
            create_sessionmaker(engine),
            chat_deps(chunk_index),
            user=alice,
            conversation_id=conversation.id,
            question="How many leave days?",
        )
    ]
    span = next(s for s in exporter.get_finished_spans() if s.name == "chat.answer")
    trace_id = format(span.context.trace_id, "032x")
    assert events[-1].data["trace_id"] == trace_id
    saved = await session.scalar(select(Message).where(Message.role == "assistant"))
    assert saved is not None and saved.trace_id == trace_id


def test_setup_tracing_is_a_no_op_without_endpoint(settings: Settings) -> None:
    assert settings.phoenix_endpoint is None
    tracing.setup_tracing(settings)
    assert tracing._configured is False
