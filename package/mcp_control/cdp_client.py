"""??????? WMPF/CDP WebSocket ???????????????????"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import websockets


JsonDict = dict[str, Any]
EventCallback = Callable[[JsonDict], None]


@dataclass(slots=True)
class PendingCdpCall:
    """?????? CDP ??? Future ?????"""

    future: asyncio.Future
    method: str
    created_at: float = field(default_factory=time.time)


class LocalCdpClient:
    """?? MCP ????? CDP ?????????????????"""

    def __init__(self, *, max_events: int = 1000, disconnect_grace_seconds: float = 1.2) -> None:
        """?????????? Future ???????"""
        self.max_events = int(max_events)
        self.disconnect_grace_seconds = max(0.0, float(disconnect_grace_seconds))
        self.ws_url = "ws://127.0.0.1:62000"
        self.websocket: Any | None = None
        self.connected = False
        self.transient_disconnected = False
        self.next_id = 1
        self.pending: dict[int, PendingCdpCall] = {}
        self.events: deque[JsonDict] = deque(maxlen=self.max_events)
        self.listeners: dict[str, list[EventCallback]] = {}
        self.receive_task: asyncio.Task | None = None
        self.reconnect_task: asyncio.Task | None = None
        self.last_error = ""
        self.lock = asyncio.Lock()

    def assert_local_ws_url(self, ws_url: str) -> None:
        """?? CDP ???????????????????"""
        parsed = urlparse(ws_url)
        if parsed.scheme not in {"ws", "wss"}:
            raise ValueError("CDP WebSocket URL ??? ws:// ? wss:// ??")
        if parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("CDP WebSocket ????? 127.0.0.1 ? localhost")

    def is_connected(self) -> bool:
        """???? WebSocket ?????"""
        return bool(self.connected and self.websocket is not None)

    async def connect(self, ws_url: str | None = None, *, timeout_ms: int = 10_000) -> JsonDict:
        """???? CDP WebSocket?????????"""
        target = str(ws_url or self.ws_url or "ws://127.0.0.1:62000")
        self.assert_local_ws_url(target)
        async with self.lock:
            if self.is_connected() and self.ws_url == target:
                return {"connected": True, "wsUrl": self.ws_url, "reused": True, "transient": False}
            await self._close_locked(fail_pending=False)
            self.ws_url = target
            timeout = max(0.1, float(timeout_ms) / 1000.0)
            self.websocket = await asyncio.wait_for(websockets.connect(target, max_size=None), timeout=timeout)
            self.connected = True
            self.transient_disconnected = False
            self.last_error = ""
            self.receive_task = asyncio.create_task(self._receive_loop(), name="mcp-cdp-receive")
            return {"connected": True, "wsUrl": self.ws_url, "reused": False, "transient": False}

    async def close(self) -> None:
        """???? CDP ??????????"""
        async with self.lock:
            await self._close_locked(fail_pending=True)

    async def _close_locked(self, *, fail_pending: bool) -> None:
        """??????????????????"""
        task = self.receive_task
        self.receive_task = None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        ws = self.websocket
        self.websocket = None
        self.connected = False
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()
        if fail_pending:
            self._fail_all_pending(RuntimeError("CDP connection closed"))

    async def send(
        self,
        method: str,
        params: JsonDict | None = None,
        *,
        timeout_ms: int = 10_000,
        session_id: str | None = None,
    ) -> JsonDict:
        """?? CDP ??????????"""
        await self.wait_until_ready(timeout_ms=timeout_ms)
        if not self.websocket:
            raise RuntimeError("CDP WebSocket ???????? connection_ops(action='connect_wmpf')")
        request_id = self.next_id
        self.next_id += 1
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self.pending[request_id] = PendingCdpCall(future=future, method=method)
        payload: JsonDict = {"id": request_id, "method": method, "params": params or {}}
        if session_id:
            payload["sessionId"] = session_id
        try:
            await self.websocket.send(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            return await asyncio.wait_for(future, timeout=max(0.1, float(timeout_ms) / 1000.0))
        except Exception:
            self.pending.pop(request_id, None)
            raise

    async def wait_until_ready(self, *, timeout_ms: int = 10_000) -> None:
        """?????????????????????"""
        if self.is_connected():
            return
        if self.transient_disconnected:
            deadline = time.monotonic() + max(0.1, float(timeout_ms) / 1000.0)
            while time.monotonic() < deadline:
                if self.is_connected():
                    return
                await asyncio.sleep(0.05)
        raise RuntimeError(f"CDP WebSocket ????????{self.last_error or self.ws_url}")

    def on(self, method: str, callback: EventCallback) -> None:
        """???? CDP ???"""
        self.listeners.setdefault(method, []).append(callback)

    def off(self, method: str, callback: EventCallback) -> None:
        """?????? CDP ???"""
        callbacks = self.listeners.get(method, [])
        if callback in callbacks:
            callbacks.remove(callback)

    async def _receive_loop(self) -> None:
        """???? CDP ?????????????????"""
        try:
            async for message in self.websocket:
                await self._handle_message(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.last_error = str(exc)
        finally:
            if self.receive_task is asyncio.current_task():
                self.connected = False
                self.transient_disconnected = True
                self.receive_task = None
                self._schedule_reconnect()

    async def _handle_message(self, message: str | bytes) -> None:
        """???? CDP ???????????"""
        if isinstance(message, bytes):
            message = message.decode("utf-8", errors="replace")
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return
        if not isinstance(data, dict):
            return
        msg_id = data.get("id")
        if isinstance(msg_id, int) and msg_id in self.pending:
            pending = self.pending.pop(msg_id)
            if not pending.future.done():
                if data.get("error"):
                    pending.future.set_exception(RuntimeError(json.dumps(data.get("error"), ensure_ascii=False)))
                else:
                    pending.future.set_result(data)
        method = data.get("method")
        if isinstance(method, str):
            event = dict(data)
            event["timestamp"] = time.time()
            self.events.append(event)
            for callback in list(self.listeners.get(method, [])):
                with contextlib.suppress(Exception):
                    callback(event)

    def _schedule_reconnect(self) -> None:
        """?????????????????????? MCP ???"""
        if self.reconnect_task is not None and not self.reconnect_task.done():
            return
        self.reconnect_task = asyncio.create_task(self._reconnect_loop(), name="mcp-cdp-reconnect")

    async def _reconnect_loop(self) -> None:
        """????????????????????? MCP ???"""
        deadline = time.monotonic() + self.disconnect_grace_seconds
        while time.monotonic() <= deadline:
            try:
                async with self.lock:
                    if self.is_connected():
                        self.transient_disconnected = False
                        return
                    self.websocket = await websockets.connect(self.ws_url, max_size=None)
                    self.connected = True
                    self.transient_disconnected = False
                    self.last_error = ""
                    self.receive_task = asyncio.create_task(self._receive_loop(), name="mcp-cdp-receive")
                    return
            except Exception as exc:
                self.last_error = str(exc)
                await asyncio.sleep(0.15)
        self.transient_disconnected = False
        self._fail_all_pending(RuntimeError(f"CDP ????????{self.last_error}"))

    def _fail_all_pending(self, exc: Exception) -> None:
        """??????????????? Future ???"""
        for pending in list(self.pending.values()):
            if not pending.future.done():
                pending.future.set_exception(exc)
        self.pending.clear()

    def status(self) -> JsonDict:
        """?? MCP ???????????"""
        return {
            "connected": self.is_connected(),
            "wsUrl": self.ws_url,
            "transientDisconnected": self.transient_disconnected,
            "pendingCalls": len(self.pending),
            "cachedEvents": len(self.events),
            "lastError": self.last_error,
        }
