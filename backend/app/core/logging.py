"""Request IDs and JSON logs. The request ID lives in a context variable, so every log line
and audit entry written while a request is handled carries it."""

import json
import logging
import re
import time
import uuid
from contextvars import ContextVar
from typing import TextIO

from pythonjsonlogger.json import JsonFormatter
from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
HEADER = b"x-request-id"
_VALID_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
logger = logging.getLogger(__name__)
access_logger = logging.getLogger("app.access")


class RequestIdMiddleware:
    """Pure ASGI (not BaseHTTPMiddleware) so it also wraps streamed responses."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope["headers"]).get(HEADER, b"").decode("latin-1")
        request_id = incoming if _VALID_ID.fullmatch(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = 500
        response_started = False

        async def send_with_id(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                status = message["status"]
                response_started = True
                message["headers"] = [*message.get("headers", []), (HEADER, request_id.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            logger.exception("Unhandled error")
            if response_started:
                raise  # too late to send a response; the server closes the connection
            body = json.dumps(
                {
                    "detail": {
                        "code": "internal_error",
                        "message": "Internal server error",
                        "request_id": request_id,
                    }
                }
            ).encode()
            await send_with_id(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send_with_id({"type": "http.response.body", "body": body})
        finally:
            access_logger.info(
                "request",
                extra={
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            request_id_var.reset(token)


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def json_handler(stream: TextIO | None = None) -> logging.Handler:
    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s")
    )
    handler.addFilter(_RequestIdFilter())
    return handler


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.handlers[:] = [json_handler()]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
