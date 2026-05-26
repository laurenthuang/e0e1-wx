"""?????? MCP Streamable HTTP ?????? token ??????"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from urllib.parse import parse_qs


class TokenMiddleware:
    """??????? token ??? MCP HTTP ???????"""

    def __init__(self, app: Callable, token: str) -> None:
        """???? ASGI ????? token?"""
        self.app = app
        self.token = str(token or "")

    async def __call__(self, scope: dict, receive: Callable[..., Awaitable[dict]], send: Callable[..., Awaitable[None]]) -> None:
        """?? HTTP ???? token???????????????"""
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path") or "")
        if path == "/":
            await self.app(scope, receive, send)
            return
        raw_query = bytes(scope.get("query_string") or b"").decode("utf-8", errors="ignore")
        query = parse_qs(raw_query)
        supplied = query.get("token", [""])[0]
        if self.token and supplied != self.token:
            body = b"Unauthorized MCP token"
            await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)
