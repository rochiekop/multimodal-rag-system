import asyncio
import uuid

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_openai import OpenAIEmbeddings

from app.core.config import Settings
from app.ingestion.index import ChunkIndex, IndexedChunk, point_id
from app.ingestion.scan import ScanError, VirusFound, scan_bytes
from app.llm.gateway import describe_image, get_embeddings
from app.llm.sparse import SparseVector, embed_sparse_documents, embed_sparse_query


def _chunk(position: int, doc_id: uuid.UUID, groups: list[str]) -> IndexedChunk:
    return IndexedChunk(
        position=position,
        text=f"chunk {position}",
        dense=[0.1 * (position + 1)] * 8,
        sparse=SparseVector(indices=[position + 1], values=[1.0]),
        payload={"doc_id": str(doc_id), "access_groups": groups, "deleted": False},
    )


async def test_upsert_is_idempotent_and_listable(chunk_index: ChunkIndex) -> None:
    version_id, doc_id = uuid.uuid4(), uuid.uuid4()
    chunks = [_chunk(i, doc_id, ["g1"]) for i in (2, 0, 1)]
    await chunk_index.upsert(version_id, chunks)
    await chunk_index.upsert(version_id, chunks)  # re-run must not duplicate
    assert await chunk_index.count_version(version_id) == 3
    listed = await chunk_index.list_chunks(version_id)
    assert [c["position"] for c in listed] == [0, 1, 2]
    assert listed[0]["text"] == "chunk 0"
    assert point_id(version_id, 0) == point_id(version_id, 0)


async def test_access_deleted_and_version_delete(chunk_index: ChunkIndex) -> None:
    v1, v2, doc_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await chunk_index.upsert(v1, [_chunk(0, doc_id, ["g1"])])
    await chunk_index.upsert(v2, [_chunk(0, doc_id, ["g1"])])

    await chunk_index.set_document_access(doc_id, ["g2", "g3"])
    await chunk_index.set_document_deleted(doc_id, True)
    payload = (await chunk_index.list_chunks(v2))[0]
    assert payload["access_groups"] == ["g2", "g3"]
    assert payload["deleted"] is True

    await chunk_index.delete_version(v1)
    assert await chunk_index.count_version(v1) == 0
    assert await chunk_index.count_version(v2) == 1


def test_bm25_sparse_embeddings_share_terms() -> None:
    doc = embed_sparse_documents(["annual leave policy"])[0]
    query = embed_sparse_query("leave")
    assert doc.indices and len(doc.indices) == len(doc.values)
    assert set(query.indices) <= set(doc.indices)


async def test_describe_image_uses_the_chat_model() -> None:
    model = FakeListChatModel(responses=["  A bar chart of revenue by region.  "])
    assert await describe_image(model, b"\x89PNG fake") == "A bar chart of revenue by region."


def test_embeddings_require_api_key() -> None:
    with pytest.raises(RuntimeError, match="RAG_OPENAI_API_KEY"):
        get_embeddings(Settings(_env_file=None, jwt_secret="x" * 40))
    embeddings = get_embeddings(
        Settings(_env_file=None, jwt_secret="x" * 40, openai_api_key="sk-test")
    )
    assert isinstance(embeddings, OpenAIEmbeddings)
    assert embeddings.dimensions == 1024


async def _fake_clamd(reply: bytes) -> tuple[asyncio.Server, int]:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        assert await reader.readexactly(10) == b"zINSTREAM\0"
        while True:
            size = int.from_bytes(await reader.readexactly(4), "big")
            if size == 0:
                break
            await reader.readexactly(size)
        writer.write(reply)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


@pytest.mark.parametrize(
    ("reply", "error"),
    [
        (b"stream: OK\0", None),
        (b"stream: Eicar-Test-Signature FOUND\0", VirusFound),
        (b"INSTREAM size limit exceeded. ERROR\0", ScanError),
    ],
)
async def test_scan_bytes(reply: bytes, error: type[Exception] | None) -> None:
    server, port = await _fake_clamd(reply)
    async with server:
        if error is None:
            await scan_bytes("127.0.0.1", port, b"x" * 3_000_000)
        else:
            with pytest.raises(error) as raised:
                await scan_bytes("127.0.0.1", port, b"data")
            if error is VirusFound:
                assert raised.value.signature == "Eicar-Test-Signature"
