"""Requests a web page of another origin may not make on the operator listener.

The operator listener has no authentication, so CORS alone does not protect it. A browser
sends a POST without a body or with a form body to any origin without asking first, and a
WebSocket is not subject to CORS at all, so any page the operator visits could stop a
campaign or read the live channel through a tunnel to 127.0.0.1:5174. This middleware
refuses a WebSocket and every request that is not GET, HEAD or OPTIONS when the request
carries an Origin header that is not one of the allowed origins. Requests without an Origin
(the CLI, curl, other programs) pass, as do reads, whose answers CORS keeps from other pages.
"""

import json
from typing import Iterable

from starlette.types import ASGIApp, Receive, Scope, Send

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
POLICY_VIOLATION = 1008  # WebSocket close code


class OriginGuard:
    def __init__(self, app: ASGIApp, allowed_origins: Iterable[str]):
        self.app = app
        self.allowed = frozenset(origin.rstrip("/") for origin in allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket") and not self._permitted(scope):
            if scope["type"] == "websocket":
                message = await receive()
                if message["type"] == "websocket.connect":
                    await send({"type": "websocket.close", "code": POLICY_VIOLATION, "reason": "origin not allowed"})
                return
            body = json.dumps({"detail": "origin not allowed"}).encode()
            await send({"type": "http.response.start", "status": 403, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)

    def _permitted(self, scope: Scope) -> bool:
        origin = next((value.decode("latin-1") for name, value in scope.get("headers", []) if name == b"origin"), None)
        if origin is None:
            return True
        if scope["type"] == "http" and scope.get("method", "GET") in SAFE_METHODS:
            return True
        return origin.rstrip("/") in self.allowed
