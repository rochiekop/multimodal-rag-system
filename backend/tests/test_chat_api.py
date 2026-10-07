import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.chat import sse_events
from app.chat.answer import ChatEvent
from app.documents.models import Document
from app.documents.service import page_key
from tests.factories import (
    bearer,
    chat_deps,
    login,
    make_collection,
    make_group,
    make_user,
    seed_document,
)


def _events(response: Response) -> list[tuple[str, dict]]:
    events = []
    for block in response.text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((fields["event"], json.loads(fields["data"])))
    return events


async def _world(app: FastAPI, client: AsyncClient, session: AsyncSession):
    hr = await make_group(session, "hr")
    await make_user(session, username="alice", groups=[hr])
    await make_user(session, username="bob")
    coll = await make_collection(session, "HR", [hr])
    doc = await seed_document(session, app.state.index, coll, ["Annual leave is 25 days."])
    app.state.chat_deps = chat_deps(app.state.index)
    return doc, await login(client, "alice"), await login(client, "bob")


async def _ask(client: AsyncClient, token: str, **body) -> list[tuple[str, dict]]:
    response = await client.post("/api/chat", headers=bearer(token), json=body)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return _events(response)


async def test_chat_streams_and_records_the_conversation(
    app: FastAPI, client: AsyncClient, session: AsyncSession
) -> None:
    _, alice, _ = await _world(app, client, session)
    events = await _ask(client, alice, question="How many leave days?")
    assert events[0][0] == "meta" and events[-1][0] == "done"
    assert events[-1][1]["citations"][0]["n"] == 1
    cid = events[0][1]["conversation_id"]

    listed = (await client.get("/api/conversations", headers=bearer(alice))).json()
    assert [(c["id"], c["title"]) for c in listed] == [(cid, "How many leave days?")]

    follow_up = await _ask(client, alice, question="And contractors?", conversation_id=cid)
    assert follow_up[0][1]["conversation_id"] == cid
    detail = (await client.get(f"/api/conversations/{cid}", headers=bearer(alice))).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant", "user", "assistant"]


async def test_blank_question_is_rejected(
    app: FastAPI, client: AsyncClient, session: AsyncSession
) -> None:
    _, alice, _ = await _world(app, client, session)
    response = await client.post("/api/chat", headers=bearer(alice), json={"question": "   "})
    assert response.status_code == 422


async def test_conversations_are_private(
    app: FastAPI, client: AsyncClient, session: AsyncSession
) -> None:
    _, alice, bob = await _world(app, client, session)
    cid = (await _ask(client, alice, question="How many leave days?"))[0][1]["conversation_id"]
    url = f"/api/conversations/{cid}"
    assert (await client.get(url, headers=bearer(bob))).status_code == 404
    assert (await client.patch(url, headers=bearer(bob), json={"title": "x"})).status_code == 404
    assert (await client.delete(url, headers=bearer(bob))).status_code == 404
    response = await client.post(
        "/api/chat", headers=bearer(bob), json={"question": "hi", "conversation_id": cid}
    )
    assert response.status_code == 404
    assert (await client.get(url, headers=bearer(alice))).status_code == 200


async def test_feedback_on_own_answer(
    app: FastAPI, client: AsyncClient, session: AsyncSession
) -> None:
    _, alice, bob = await _world(app, client, session)
    events = await _ask(client, alice, question="How many leave days?")
    answer_id = events[-1][1]["message_id"]
    question_id = events[0][1]["user_message_id"]
    url = f"/api/messages/{answer_id}/feedback"

    ok = await client.post(url, headers=bearer(alice), json={"rating": -1, "comment": "Wrong"})
    assert ok.status_code == 200
    assert (ok.json()["feedback_rating"], ok.json()["feedback_comment"]) == (-1, "Wrong")
    assert (await client.post(url, headers=bearer(alice), json={"rating": 0})).status_code == 422
    assert (await client.post(url, headers=bearer(bob), json={"rating": 1})).status_code == 404
    on_question = await client.post(
        f"/api/messages/{question_id}/feedback", headers=bearer(alice), json={"rating": 1}
    )
    assert on_question.status_code == 404


async def test_rename_search_and_delete(
    app: FastAPI, client: AsyncClient, session: AsyncSession
) -> None:
    _, alice, _ = await _world(app, client, session)
    cid = (await _ask(client, alice, question="How many leave days?"))[0][1]["conversation_id"]
    url = f"/api/conversations/{cid}"

    renamed = await client.patch(url, headers=bearer(alice), json={"title": "Leave policy"})
    assert renamed.json()["title"] == "Leave policy"
    found = await client.get("/api/conversations", headers=bearer(alice), params={"q": "25 days"})
    assert [c["id"] for c in found.json()] == [cid]  # matched via message content
    none = await client.get("/api/conversations", headers=bearer(alice), params={"q": "zzz%"})
    assert none.json() == []

    assert (await client.delete(url, headers=bearer(alice))).status_code == 204
    assert (await client.get(url, headers=bearer(alice))).status_code == 404


async def test_collections_lists_only_visible(
    app: FastAPI, client: AsyncClient, session: AsyncSession
) -> None:
    _, alice, bob = await _world(app, client, session)
    await make_collection(session, "Secret", [await make_group(session, "board")])
    visible = (await client.get("/api/collections", headers=bearer(alice))).json()
    assert [c["name"] for c in visible] == ["HR"]
    assert (await client.get("/api/collections", headers=bearer(bob))).json() == []


async def test_page_image_requires_permission(
    app: FastAPI, client: AsyncClient, session: AsyncSession
) -> None:
    doc, alice, bob = await _world(app, client, session)
    app.state.store.save(page_key(doc.current_version_id, 1), b"\x89PNG fake")
    url = f"/api/documents/{doc.id}/pages/1"

    ok = await client.get(url, headers=bearer(alice))
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/png"
    assert ok.content == b"\x89PNG fake"
    missing = await client.get(f"/api/documents/{doc.id}/pages/2", headers=bearer(alice))
    assert missing.status_code == 404
    assert (await client.get(url, headers=bearer(bob))).status_code == 404

    stored = await session.get(Document, doc.id)
    assert stored is not None
    stored.deleted_at = datetime.now(UTC)
    await session.commit()
    assert (await client.get(url, headers=bearer(alice))).status_code == 404


async def test_stream_ends_with_error_event_when_answer_fails(
    app: FastAPI,
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, alice, _ = await _world(app, client, session)

    async def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr("app.chat.answer.get_active", boom)
    events = await _ask(client, alice, question="How many leave days?")
    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == "answer_failed"


async def test_closing_the_sse_stream_closes_the_answer_generator() -> None:
    closed = False

    async def events() -> AsyncIterator[ChatEvent]:
        nonlocal closed
        try:
            while True:
                yield ChatEvent("token", {"text": "x"})
        finally:
            closed = True

    stream = sse_events(events())
    await anext(stream)
    await stream.aclose()
    assert closed
