"""Minimal clamd client using the INSTREAM protocol over TCP."""

import asyncio
import struct

_CHUNK = 1 << 20


class ScanError(Exception):
    pass


class VirusFound(Exception):
    def __init__(self, signature: str) -> None:
        super().__init__(f"Virus detected: {signature}")
        self.signature = signature


async def scan_bytes(
    host: str,
    port: int,
    data: bytes,
    *,
    timeout: float = 120.0,  # noqa: ASYNC109
) -> None:
    """Returns normally when clean. Raises VirusFound or ScanError."""
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    except (OSError, TimeoutError) as exc:
        raise ScanError(f"Cannot connect to clamd: {exc!r}") from exc

    failure: BaseException | None = None
    received = bytearray()

    async def collect() -> None:
        # Read concurrently so a reply sent before clamd drops the socket is not lost.
        while chunk := await reader.read(4096):
            received.extend(chunk)

    collector = asyncio.ensure_future(collect())
    try:
        try:
            writer.write(b"zINSTREAM\0")
            for start in range(0, len(data), _CHUNK):
                part = data[start : start + _CHUNK]
                writer.write(struct.pack("!L", len(part)) + part)
                await asyncio.wait_for(writer.drain(), timeout)
            writer.write(struct.pack("!L", 0))
            await asyncio.wait_for(writer.drain(), timeout)
        except (OSError, TimeoutError) as exc:
            failure = exc  # clamd may have replied (e.g. size limit) before closing
        try:
            await asyncio.wait_for(collector, timeout)
        except (OSError, TimeoutError, asyncio.IncompleteReadError) as exc:
            failure = failure or exc
    finally:
        collector.cancel()
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:  # noqa: BLE001  closing must never mask the real error
            pass

    reply = bytes(received)
    text = reply.rstrip(b"\0").decode(errors="replace").strip()
    if not text:
        raise ScanError(f"No reply from clamd: {failure!r}") from failure
    if text.endswith("OK") and failure is None:
        return
    if text.endswith("FOUND"):
        raise VirusFound(text.split(":", 1)[-1].removesuffix("FOUND").strip())
    raise ScanError(text)
