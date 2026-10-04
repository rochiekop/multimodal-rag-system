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


async def scan_bytes(host: str, port: int, data: bytes, *, timeout: float = 120.0) -> None:  # noqa: ASYNC109
    """Returns normally when clean. Raises VirusFound or ScanError."""
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    try:
        writer.write(b"zINSTREAM\0")
        for start in range(0, len(data), _CHUNK):
            part = data[start : start + _CHUNK]
            writer.write(struct.pack("!L", len(part)) + part)
            await writer.drain()
        writer.write(struct.pack("!L", 0))
        await writer.drain()
        reply = (await asyncio.wait_for(reader.read(4096), timeout)).rstrip(b"\0").decode()
    finally:
        writer.close()
        await writer.wait_closed()

    if reply.endswith("OK"):
        return
    if reply.endswith("FOUND"):
        raise VirusFound(reply.split(":", 1)[-1].removesuffix("FOUND").strip())
    raise ScanError(reply or "Empty reply from clamd")
