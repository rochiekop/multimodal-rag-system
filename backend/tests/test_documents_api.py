import io
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.models import Document
from app.ingestion.index import IndexedChunk
from app.llm.sparse import SparseVector
from app.users.models import Role
from tests.factories import DEFAULT_PASSWORD, bearer, login, make_group, make_user

MD = b"# Leave policy\n\nEmployees get 20 days of annual leave.\n"


async def _setup(client: AsyncClient, session: AsyncSession, group_names=("hr", "mgmt")):
    await make_user(session, username="admin1", role=Role.ADMIN)
    token = await login(client, "admin1")
    groups = [await make_group(session, name) for name in group_names]
    created = await client.post(
        "/api/admin/collections",
        headers=bearer(token),
        json={"name": "HR", "group_ids": [str(g.id) for g in groups]},
    )
    return token, created.json()["id"], groups


async def _upload(client: AsyncClient, token: str, collection_id: str, *files):
    return await client.post(
        f"/api/admin/collections/{collection_id}/documents",
        headers=bearer(token),
        files=[("files", f) for f in files],
    )


def _docx_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document/>")
    return buffer.getvalue()


async def test_upload_queues_and_stores_original(
    app: FastAPI, client: AsyncClient, session: AsyncSession, enqueued: list[UUID]
) -> None:
    token, collection_id, _ = await _setup(client, session)
    response = await _upload(
        client,
        token,
        collection_id,
        ("leave.md", MD, "text/markdown"),
        ("spec.docx", _docx_bytes(), "application/octet-stream"),
    )
    assert response.status_code == 200
    results = response.json()
    assert [r["outcome"] for r in results] == ["queued", "queued"]
    version_id = UUID(results[0]["version_id"])
    assert enqueued == [version_id, UUID(results[1]["version_id"])]
    assert app.state.store.read(f"versions/{version_id}/original") == MD

    detail = await client.get(
        f"/api/admin/documents/{results[0]['document_id']}", headers=bearer(token)
    )
    assert detail.json()["versions"][0]["status"] == "queued"
    status = await client.get("/api/admin/ingestion/status", headers=bearer(token))
    assert status.json()["queued"] == 2


async def test_same_name_new_content_creates_version(
    client: AsyncClient, session: AsyncSession
) -> None:
    token, collection_id, _ = await _setup(client, session)
    first = (await _upload(client, token, collection_id, ("leave.md", MD, "text/markdown"))).json()[
        0
    ]
    second = (
        await _upload(client, token, collection_id, ("leave.md", MD + b"More.\n", "text/markdown"))
    ).json()[0]
    assert second["outcome"] == "queued"
    assert second["document_id"] == first["document_id"]
    detail = await client.get(f"/api/admin/documents/{first['document_id']}", headers=bearer(token))
    assert [v["version_no"] for v in detail.json()["versions"]] == [1, 2]


async def test_duplicate_content_is_detected(client: AsyncClient, session: AsyncSession) -> None:
    token, collection_id, _ = await _setup(client, session)
    first = (await _upload(client, token, collection_id, ("leave.md", MD, "text/markdown"))).json()[
        0
    ]
    again = (
        await _upload(client, token, collection_id, ("copy-of-leave.md", MD, "text/markdown"))
    ).json()[0]
    assert again["outcome"] == "duplicate"
    assert again["document_id"] == first["document_id"]


async def test_content_must_match_extension(client: AsyncClient, session: AsyncSession) -> None:
    token, collection_id, _ = await _setup(client, session)
    results = (
        await _upload(
            client,
            token,
            collection_id,
            ("report.pdf", b"MZ\x90\x00 this is an exe", "application/pdf"),
            ("virus.exe", b"MZ\x90\x00", "application/octet-stream"),
            ("empty.md", b"", "text/markdown"),
            ("binary.md", b"abc\x00def", "text/markdown"),
            ("fake.docx", b"PK\x03\x04 not a zip", "application/octet-stream"),
        )
    ).json()
    assert [r["outcome"] for r in results] == ["invalid"] * 5
    expected = ["not a PDF", "Unsupported file type", "empty", "binary data", "corrupt"]
    for result, fragment in zip(results, expected, strict=True):
        assert fragment in result["message"], result


async def test_filename_is_sanitized(client: AsyncClient, session: AsyncSession) -> None:
    token, collection_id, _ = await _setup(client, session)
    result = (
        await _upload(client, token, collection_id, ("..\\..\\etc\\leave.md", MD, "text/markdown"))
    ).json()[0]
    detail = await client.get(
        f"/api/admin/documents/{result['document_id']}", headers=bearer(token)
    )
    assert detail.json()["filename"] == "leave.md"


async def test_restricting_a_document_updates_chunk_access(
    app: FastAPI, client: AsyncClient, session: AsyncSession
) -> None:
    token, collection_id, (hr, mgmt) = await _setup(client, session)
    result = (
        await _upload(client, token, collection_id, ("leave.md", MD, "text/markdown"))
    ).json()[0]
    doc_id = result["document_id"]
    await _index_fake_chunk(app, UUID(doc_id), UUID(result["version_id"]))

    other = await make_group(session, "sales")
    bad = await client.put(
        f"/api/admin/documents/{doc_id}/groups",
        headers=bearer(token),
        json={"group_ids": [str(other.id)]},
    )
    assert bad.json()["detail"]["code"] == "group_not_in_collection"

    ok = await client.put(
        f"/api/admin/documents/{doc_id}/groups",
        headers=bearer(token),
        json={"group_ids": [str(mgmt.id)]},
    )
    assert ok.status_code == 200
    payload = (await app.state.index.list_chunks(UUID(result["version_id"])))[0]
    assert payload["access_groups"] == [str(mgmt.id)]


async def test_delete_requires_password_and_restore(
    app: FastAPI, client: AsyncClient, session: AsyncSession
) -> None:
    token, collection_id, _ = await _setup(client, session)
    result = (
        await _upload(client, token, collection_id, ("leave.md", MD, "text/markdown"))
    ).json()[0]
    doc_id, version_id = result["document_id"], UUID(result["version_id"])
    await _index_fake_chunk(app, UUID(doc_id), version_id)

    wrong = await client.post(
        f"/api/admin/documents/{doc_id}/delete", headers=bearer(token), json={"password": "nope"}
    )
    assert wrong.status_code == 403

    deleted = await client.post(
        f"/api/admin/documents/{doc_id}/delete",
        headers=bearer(token),
        json={"password": DEFAULT_PASSWORD},
    )
    assert deleted.json()["deleted_at"] is not None
    assert (await app.state.index.list_chunks(version_id))[0]["deleted"] is True
    listed = await client.get(
        f"/api/admin/collections/{collection_id}/documents", headers=bearer(token)
    )
    assert listed.json() == []

    restored = await client.post(f"/api/admin/documents/{doc_id}/restore", headers=bearer(token))
    assert restored.json()["deleted_at"] is None
    assert (await app.state.index.list_chunks(version_id))[0]["deleted"] is False


async def test_restore_window_is_30_days(client: AsyncClient, session: AsyncSession) -> None:
    token, collection_id, _ = await _setup(client, session)
    result = (
        await _upload(client, token, collection_id, ("leave.md", MD, "text/markdown"))
    ).json()[0]
    document = await session.get(Document, UUID(result["document_id"]))
    assert document is not None
    document.deleted_at = datetime.now(UTC) - timedelta(days=31)
    await session.commit()
    response = await client.post(
        f"/api/admin/documents/{document.id}/restore", headers=bearer(token)
    )
    assert response.json()["detail"]["code"] == "restore_window_expired"


async def test_retry_only_failed_versions(
    client: AsyncClient, session: AsyncSession, enqueued: list[UUID]
) -> None:
    token, collection_id, _ = await _setup(client, session)
    result = (
        await _upload(client, token, collection_id, ("leave.md", MD, "text/markdown"))
    ).json()[0]
    version_id = result["version_id"]
    not_failed = await client.post(f"/api/admin/versions/{version_id}/retry", headers=bearer(token))
    assert not_failed.status_code == 409

    from app.documents.models import DocumentVersion

    version = await session.get(DocumentVersion, UUID(version_id))
    assert version is not None
    version.status, version.failed_stage, version.error = "failed", "parsing", "boom"
    await session.commit()
    retried = await client.post(f"/api/admin/versions/{version_id}/retry", headers=bearer(token))
    assert retried.json()["status"] == "queued"
    assert retried.json()["error"] is None
    assert enqueued[-1] == UUID(version_id)


async def test_unknown_collection_is_404(client: AsyncClient, session: AsyncSession) -> None:
    token, _, _ = await _setup(client, session)
    response = await _upload(client, token, str(uuid.uuid4()), ("a.md", MD, "text/markdown"))
    assert response.status_code == 404


async def _index_fake_chunk(app: FastAPI, doc_id: UUID, version_id: UUID) -> None:
    await app.state.index.upsert(
        version_id,
        [
            IndexedChunk(
                position=0,
                text="t",
                dense=[0.1] * 8,
                sparse=SparseVector(indices=[1], values=[1.0]),
                payload={"doc_id": str(doc_id), "access_groups": [], "deleted": False},
            )
        ],
    )


async def test_over_limit_file_is_rejected(
    app: FastAPI, client: AsyncClient, session: AsyncSession
) -> None:
    token, collection_id, _ = await _setup(client, session)
    app.state.settings.max_upload_mb = 1
    big = b"# Big\n\n" + b"word " * 230_000
    assert len(big) > 1024 * 1024
    result = (await _upload(client, token, collection_id, ("big.md", big, "text/markdown"))).json()[
        0
    ]
    assert result["outcome"] == "invalid"
    assert "exceeds" in result["message"]


async def test_docx_without_word_entries_is_rejected(
    client: AsyncClient, session: AsyncSession
) -> None:
    token, collection_id, _ = await _setup(client, session)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("other/file.txt", "x")
    result = (
        await _upload(
            client, token, collection_id, ("odd.docx", buffer.getvalue(), "application/zip")
        )
    ).json()[0]
    assert result["outcome"] == "invalid"
    assert "does not match its extension" in result["message"]


async def test_invalid_upload_stores_and_enqueues_nothing(
    app: FastAPI, client: AsyncClient, session: AsyncSession, enqueued: list[UUID]
) -> None:
    token, collection_id, _ = await _setup(client, session)
    await _upload(
        client, token, collection_id, ("virus.exe", b"MZ\x90\x00", "application/octet-stream")
    )
    assert enqueued == []
    assert not (app.state.store.root / "versions").exists()


async def test_wrong_password_leaves_document_intact(
    app: FastAPI, client: AsyncClient, session: AsyncSession
) -> None:
    token, collection_id, _ = await _setup(client, session)
    result = (
        await _upload(client, token, collection_id, ("leave.md", MD, "text/markdown"))
    ).json()[0]
    version_id = UUID(result["version_id"])
    await _index_fake_chunk(app, UUID(result["document_id"]), version_id)
    wrong = await client.post(
        f"/api/admin/documents/{result['document_id']}/delete",
        headers=bearer(token),
        json={"password": "nope"},
    )
    assert wrong.status_code == 403
    session.expire_all()
    document = await session.get(Document, UUID(result["document_id"]))
    assert document is not None and document.deleted_at is None
    assert (await app.state.index.list_chunks(version_id))[0]["deleted"] is False


async def test_duplicate_detection_ignores_deleted_documents(
    client: AsyncClient, session: AsyncSession
) -> None:
    token, collection_id, _ = await _setup(client, session)
    first = (await _upload(client, token, collection_id, ("leave.md", MD, "text/markdown"))).json()[
        0
    ]
    deleted = await client.post(
        f"/api/admin/documents/{first['document_id']}/delete",
        headers=bearer(token),
        json={"password": DEFAULT_PASSWORD},
    )
    assert deleted.status_code == 200
    again = (
        await _upload(client, token, collection_id, ("other-name.md", MD, "text/markdown"))
    ).json()[0]
    assert again["outcome"] == "queued"
    assert again["document_id"] != first["document_id"]


async def test_earlier_files_are_enqueued_when_a_later_one_fails(
    app: FastAPI, client: AsyncClient, session: AsyncSession, enqueued: list[UUID]
) -> None:
    token, collection_id, _ = await _setup(client, session)
    real_save = app.state.store.save
    calls = {"n": 0}

    def flaky_save(key: str, data: bytes) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        real_save(key, data)

    app.state.store.save = flaky_save
    with pytest.raises(OSError):
        await _upload(
            client,
            token,
            collection_id,
            ("a.md", MD, "text/markdown"),
            ("b.md", MD + b"b\n", "text/markdown"),
        )
    assert len(enqueued) == 1
