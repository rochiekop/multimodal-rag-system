import uuid

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.models import Document
from app.ingestion.index import IndexedChunk
from app.llm.sparse import SparseVector
from app.users.models import Role
from tests.factories import DEFAULT_PASSWORD, bearer, login, make_group, make_user


async def _admin(client: AsyncClient, session: AsyncSession) -> str:
    await make_user(session, username="admin1", role=Role.ADMIN)
    return await login(client, "admin1")


async def test_create_and_list_collections(client: AsyncClient, session: AsyncSession) -> None:
    token = await _admin(client, session)
    hr = await make_group(session, "hr")
    created = await client.post(
        "/api/admin/collections",
        headers=bearer(token),
        json={"name": "HR Policies", "group_ids": [str(hr.id)], "sensitive": True},
    )
    assert created.status_code == 201
    assert created.json()["sensitive"] is True
    assert [g["name"] for g in created.json()["groups"]] == ["hr"]

    duplicate = await client.post(
        "/api/admin/collections", headers=bearer(token), json={"name": "HR Policies"}
    )
    assert duplicate.status_code == 409

    listed = await client.get("/api/admin/collections", headers=bearer(token))
    assert [c["name"] for c in listed.json()] == ["HR Policies"]


async def test_group_change_requires_password(client: AsyncClient, session: AsyncSession) -> None:
    token = await _admin(client, session)
    eng = await make_group(session, "eng")
    created = await client.post(
        "/api/admin/collections", headers=bearer(token), json={"name": "Manuals"}
    )
    url = f"/api/admin/collections/{created.json()['id']}"

    rename = await client.patch(url, headers=bearer(token), json={"name": "Product Manuals"})
    assert rename.status_code == 200

    no_password = await client.patch(url, headers=bearer(token), json={"group_ids": [str(eng.id)]})
    assert no_password.status_code == 403
    assert no_password.json()["detail"]["code"] == "password_confirmation_failed"

    ok = await client.patch(
        url,
        headers=bearer(token),
        json={"group_ids": [str(eng.id)], "password": DEFAULT_PASSWORD},
    )
    assert ok.status_code == 200
    assert [g["name"] for g in ok.json()["groups"]] == ["eng"]


async def test_changing_collection_groups_updates_chunk_access(
    app: FastAPI, client: AsyncClient, session: AsyncSession
) -> None:
    token = await _admin(client, session)
    hr = await make_group(session, "hr")
    mgmt = await make_group(session, "mgmt")
    created = await client.post(
        "/api/admin/collections",
        headers=bearer(token),
        json={"name": "HR", "group_ids": [str(hr.id), str(mgmt.id)]},
    )
    collection_id = uuid.UUID(created.json()["id"])
    document = Document(
        collection_id=collection_id, filename="a.md", versions=[], restricted_groups=[]
    )
    session.add(document)
    await session.commit()

    version_id = uuid.uuid4()
    await app.state.index.upsert(
        version_id,
        [
            IndexedChunk(
                position=0,
                text="t",
                dense=[0.1] * 8,
                sparse=SparseVector(indices=[1], values=[1.0]),
                payload={"doc_id": str(document.id), "access_groups": ["old"], "deleted": False},
            )
        ],
    )

    response = await client.patch(
        f"/api/admin/collections/{collection_id}",
        headers=bearer(token),
        json={"group_ids": [str(mgmt.id)], "password": DEFAULT_PASSWORD},
    )
    assert response.status_code == 200
    payload = (await app.state.index.list_chunks(version_id))[0]
    assert payload["access_groups"] == [str(mgmt.id)]
