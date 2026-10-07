import uuid

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.evaluation.models import EvalCase
from app.users.models import Role
from tests.factories import bearer, login, make_collection, make_group, make_user


async def _admin(client: AsyncClient, session: AsyncSession) -> dict[str, str]:
    await make_user(session, username="boss", role=Role.ADMIN)
    return bearer(await login(client, "boss"))


async def _set(client: AsyncClient, h: dict[str, str], name: str = "HR basics") -> str:
    response = await client.post("/api/admin/eval-sets", headers=h, json={"name": name})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def test_sets_are_created_renamed_listed_and_unique(
    client: AsyncClient, session: AsyncSession
) -> None:
    h = await _admin(client, session)
    set_id = await _set(client, h)
    duplicate = await client.post("/api/admin/eval-sets", headers=h, json={"name": "HR basics"})
    assert duplicate.status_code == 409
    renamed = await client.patch(
        f"/api/admin/eval-sets/{set_id}", headers=h, json={"description": "Leave and pay"}
    )
    assert renamed.json()["description"] == "Leave and pay"
    listed = (await client.get("/api/admin/eval-sets", headers=h)).json()
    assert [(s["name"], s["case_count"]) for s in listed] == [("HR basics", 0)]


async def test_cases_are_validated(client: AsyncClient, session: AsyncSession) -> None:
    h = await _admin(client, session)
    hr = await make_group(session, "hr")
    coll = await make_collection(session, "HR", [hr])
    set_id = await _set(client, h)
    url = f"/api/admin/eval-sets/{set_id}/cases"

    ok = await client.post(
        url,
        headers=h,
        json={
            "question": "  How many leave days?  ",
            "expected_answer": "25 days",
            "collection_ids": [str(coll.id)],
            "run_as_group_ids": [str(hr.id)],
        },
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["question"] == "How many leave days?"
    assert ok.json()["origin"] == "manual"

    no_groups = await client.post(url, headers=h, json={"question": "q", "run_as_group_ids": []})
    assert no_groups.status_code == 422
    unknown_group = await client.post(
        url, headers=h, json={"question": "q", "run_as_group_ids": [str(uuid.uuid4())]}
    )
    assert unknown_group.status_code == 422
    assert unknown_group.json()["detail"]["code"] == "invalid_case"
    unknown_doc = await client.post(
        url,
        headers=h,
        json={
            "question": "q",
            "run_as_group_ids": [str(hr.id)],
            "expected_sources": [{"doc_id": str(uuid.uuid4()), "page": 2}],
        },
    )
    assert unknown_doc.status_code == 422


async def test_cases_update_delete_and_set_delete_cascades(
    client: AsyncClient, session: AsyncSession
) -> None:
    h = await _admin(client, session)
    hr = await make_group(session, "hr")
    set_id = await _set(client, h)
    case = (
        await client.post(
            f"/api/admin/eval-sets/{set_id}/cases",
            headers=h,
            json={"question": "q1", "run_as_group_ids": [str(hr.id)]},
        )
    ).json()
    updated = await client.patch(
        f"/api/admin/eval-cases/{case['id']}",
        headers=h,
        json={"question": "q2", "run_as_group_ids": [str(hr.id)], "unanswerable": True},
    )
    assert (updated.json()["question"], updated.json()["unanswerable"]) == ("q2", True)

    assert (await client.delete(f"/api/admin/eval-sets/{set_id}", headers=h)).status_code == 204
    assert await session.scalar(select(func.count()).select_from(EvalCase)) == 0
    assert (await client.get(f"/api/admin/eval-sets/{set_id}", headers=h)).status_code == 404


async def test_csv_import_reports_bad_rows(client: AsyncClient, session: AsyncSession) -> None:
    h = await _admin(client, session)
    await make_group(session, "hr")
    await make_group(session, "mgmt")
    await make_collection(session, "HR")
    set_id = await _set(client, h)
    doc_id = uuid.uuid4()
    csv_text = (
        "﻿question,expected_answer,expected_sources,collections,groups,unanswerable\n"
        "How many leave days?,25 days,,HR,hr;MGMT,false\n"
        "\n"
        "Who is the CEO?,,,,hr,yes\n"
        "Bad group,,,,nobody,no\n"
        f"Bad source,,{doc_id}:x,,hr,no\n"
        "Bad collection,,,Finance,hr,no\n"
        ",,,,hr,no\n"
    )
    response = await client.post(
        f"/api/admin/eval-sets/{set_id}/import",
        headers=h,
        files={"file": ("cases.csv", csv_text.encode("utf-8"), "text/csv")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created"] == 2
    assert [e["row"] for e in body["errors"]] == [5, 6, 7, 8]
    cases = (await client.get(f"/api/admin/eval-sets/{set_id}/cases", headers=h)).json()
    assert [c["question"] for c in cases] == ["How many leave days?", "Who is the CEO?"]
    assert len(cases[0]["run_as_group_ids"]) == 2 and cases[1]["unanswerable"] is True
