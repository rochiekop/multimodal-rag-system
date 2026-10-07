from datetime import UTC, datetime

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.chat.models import Conversation, Message
from app.evaluation.models import EvalSet
from app.guardrails.models import GuardrailEvent
from app.users.models import Role, User
from tests.factories import (
    activate_config,
    bearer,
    chat_deps,
    login,
    make_collection,
    make_group,
    make_user,
)


async def _exchange(
    session: AsyncSession,
    user: User,
    question: str,
    answer: str,
    *,
    rating: int | None = None,
    low_confidence: bool = False,
    collection_ids: list[str] | None = None,
) -> Message:
    conversation = Conversation(user_id=user.id, title=question[:50])
    session.add(conversation)
    await session.flush()
    session.add(
        Message(
            conversation_id=conversation.id,
            role="user",
            content=question,
            collection_ids=collection_ids or [],
        )
    )
    await session.flush()
    reply = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=answer,
        outcome="answered",
        collection_ids=collection_ids or [],
        feedback_rating=rating,
        feedback_at=datetime.now(UTC) if rating else None,
        low_confidence=low_confidence,
    )
    session.add(reply)
    await session.commit()
    return reply


async def _world(client: AsyncClient, session: AsyncSession):
    hr = await make_group(session, "hr")
    coll = await make_collection(session, "HR", [hr])
    alice = await make_user(session, username="alice", groups=[hr])
    await make_user(session, username="boss", role=Role.ADMIN)
    disliked = await _exchange(
        session,
        alice,
        "How many leave days?",
        "30 days.",
        rating=-1,
        collection_ids=[str(coll.id)],
    )
    shaky = await _exchange(session, alice, "Parking?", "Free.", low_confidence=True)
    await _exchange(session, alice, "Fine one", "All good.", rating=1)
    session.add(
        GuardrailEvent(user_id=alice.id, check="prompt_injection", action="blocked", strike=True)
    )
    await session.commit()
    return alice, coll, disliked, shaky, bearer(await login(client, "boss"))


async def test_queue_lists_feedback_low_confidence_and_guardrail_items(
    client: AsyncClient, session: AsyncSession
) -> None:
    _, _, disliked, shaky, h = await _world(client, session)
    items = (await client.get("/api/admin/review-queue", headers=h)).json()
    assert sorted(i["kind"] for i in items) == ["feedback", "guardrail", "low_confidence"]
    feedback = next(i for i in items if i["kind"] == "feedback")
    assert feedback["message_id"] == str(disliked.id)
    assert (feedback["question"], feedback["answer"], feedback["username"]) == (
        "How many leave days?",
        "30 days.",
        "alice",
    )
    only = await client.get("/api/admin/review-queue", headers=h, params={"kind": "low_confidence"})
    assert [i["message_id"] for i in only.json()] == [str(shaky.id)]

    marked = await client.post(
        f"/api/admin/review-queue/feedback/{disliked.id}/reviewed", headers=h
    )
    assert marked.status_code == 204
    remaining = (await client.get("/api/admin/review-queue", headers=h)).json()
    assert "feedback" not in [i["kind"] for i in remaining]
    everything = await client.get(
        "/api/admin/review-queue", headers=h, params={"include_reviewed": "true"}
    )
    assert "feedback" in [i["kind"] for i in everything.json()]
    actions = (await session.scalars(select(AuditLog.action))).all()
    assert "review.queue_viewed" in actions


async def test_queue_view_audit_records_whose_content_was_shown(
    client: AsyncClient, session: AsyncSession
) -> None:
    alice, _, disliked, _, h = await _world(client, session)
    items = (await client.get("/api/admin/review-queue", headers=h)).json()
    assert len(items) == 3
    entry = await session.scalar(select(AuditLog).where(AuditLog.action == "review.queue_viewed"))
    assert entry is not None
    shown = entry.detail["items"]
    assert {i["user_id"] for i in shown} == {str(alice.id)}
    assert sorted((i["kind"], i["id"]) for i in shown) == sorted(
        (i["kind"], i["id"]) for i in items
    )
    feedback = next(i for i in shown if i["kind"] == "feedback")
    assert feedback["message_id"] == str(disliked.id)


async def test_viewing_a_message_is_audited(client: AsyncClient, session: AsyncSession) -> None:
    alice, _, disliked, _, h = await _world(client, session)
    detail = await client.get(f"/api/admin/review-queue/messages/{disliked.id}", headers=h)
    assert detail.status_code == 200
    body = detail.json()
    assert (body["question"], body["answer"]["content"], body["user"]["username"]) == (
        "How many leave days?",
        "30 days.",
        "alice",
    )
    entry = await session.scalar(select(AuditLog).where(AuditLog.action == "review.message_viewed"))
    assert entry is not None
    assert entry.actor_username == "boss"
    assert entry.target_id == str(disliked.id)
    assert entry.detail["owner_id"] == str(alice.id)


async def test_add_message_to_eval_set(client: AsyncClient, session: AsyncSession) -> None:
    alice, coll, disliked, _, h = await _world(client, session)
    eval_set = EvalSet(name="From review")
    session.add(eval_set)
    await session.commit()
    response = await client.post(
        f"/api/admin/review-queue/messages/{disliked.id}/add-to-eval-set",
        headers=h,
        json={"eval_set_id": str(eval_set.id), "expected_answer": "25 days"},
    )
    assert response.status_code == 201, response.text
    case = response.json()
    assert case["question"] == "How many leave days?"
    assert case["expected_answer"] == "25 days"
    assert case["collection_ids"] == [str(coll.id)]
    assert case["run_as_group_ids"] == [str(g.id) for g in alice.groups]
    assert (case["origin"], case["source_message_id"]) == ("review", str(disliked.id))

    loner = await make_user(session, username="loner")
    lonely = await _exchange(session, loner, "Q?", "A.", rating=-1)
    no_groups = await client.post(
        f"/api/admin/review-queue/messages/{lonely.id}/add-to-eval-set",
        headers=h,
        json={"eval_set_id": str(eval_set.id)},
    )
    assert no_groups.status_code == 422


async def test_preflight_refusals_are_recorded_once_per_hour(
    app: FastAPI, client: AsyncClient, session: AsyncSession
) -> None:
    hr = await make_group(session, "hr")
    await make_user(session, username="alice", groups=[hr])
    app.state.chat_deps = chat_deps(app.state.index)
    await activate_config(session, guardrails={"max_question_chars": 10})
    token = await login(client, "alice")
    for _ in range(2):
        response = await client.post(
            "/api/chat", headers=bearer(token), json={"question": "x" * 11}
        )
        assert response.status_code == 422
    count = await session.scalar(
        select(func.count())
        .select_from(GuardrailEvent)
        .where(GuardrailEvent.check == "question_too_long")
    )
    assert count == 1


async def test_mark_reviewed_validates_target_and_audits(
    client: AsyncClient, session: AsyncSession
) -> None:
    import uuid

    alice, _, disliked, shaky, h = await _world(client, session)
    url = "/api/admin/review-queue"
    wrong_kind = await client.post(f"{url}/low_confidence/{disliked.id}/reviewed", headers=h)
    assert wrong_kind.status_code == 404
    wrong_kind = await client.post(f"{url}/feedback/{shaky.id}/reviewed", headers=h)
    assert wrong_kind.status_code == 404
    user_msg = await session.scalar(
        select(Message.id).where(
            Message.conversation_id == disliked.conversation_id, Message.role == "user"
        )
    )
    assert (await client.post(f"{url}/feedback/{user_msg}/reviewed", headers=h)).status_code == 404
    unknown = await client.post(f"{url}/feedback/{uuid.uuid4()}/reviewed", headers=h)
    assert unknown.status_code == 404
    assert "review.marked_reviewed" not in (await session.scalars(select(AuditLog.action))).all()

    assert (
        await client.post(f"{url}/feedback/{disliked.id}/reviewed", headers=h)
    ).status_code == 204
    assert "review.marked_reviewed" in (await session.scalars(select(AuditLog.action))).all()

    event_id = await session.scalar(select(GuardrailEvent.id))
    done = await client.post(f"{url}/guardrail/{event_id}/reviewed", headers=h)
    assert done.status_code == 204
    kinds = [i["kind"] for i in (await client.get(url, headers=h)).json()]
    assert "guardrail" not in kinds


async def test_add_to_eval_set_is_audited(client: AsyncClient, session: AsyncSession) -> None:
    _, _, disliked, _, h = await _world(client, session)
    eval_set = EvalSet(name="Audited")
    session.add(eval_set)
    await session.commit()
    response = await client.post(
        f"/api/admin/review-queue/messages/{disliked.id}/add-to-eval-set",
        headers=h,
        json={"eval_set_id": str(eval_set.id)},
    )
    assert response.status_code == 201
    assert "review.added_to_eval_set" in (await session.scalars(select(AuditLog.action))).all()
