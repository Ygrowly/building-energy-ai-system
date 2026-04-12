from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any

from fastapi import WebSocket

from app.core.cache import get_redis_client

_TICKET_TTL_SECONDS = 60
_CHANNEL_PREFIX = "notifications:user:"
_LOCAL_TICKETS: dict[str, tuple[str, float]] = {}
_LOCAL_CONNECTIONS: dict[str, set[WebSocket]] = defaultdict(set)
_LOCAL_LOCK = asyncio.Lock()


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def build_ws_message(event_type: str, data: Any) -> str:
    return json.dumps(
        {"type": event_type, "data": data},
        ensure_ascii=False,
        default=_json_default,
    )


def _cleanup_local_tickets() -> None:
    now = time.time()
    expired = [ticket for ticket, (_, expires_at) in _LOCAL_TICKETS.items() if expires_at <= now]
    for ticket in expired:
        _LOCAL_TICKETS.pop(ticket, None)


async def issue_realtime_ticket(user_id: str, *, ttl_seconds: int = _TICKET_TTL_SECONDS) -> dict[str, Any]:
    ticket = uuid.uuid4().hex
    redis_client = await get_redis_client()
    if redis_client is not None:
        payload = json.dumps({"user_id": user_id}, ensure_ascii=False)
        await redis_client.set(f"notifications:ticket:{ticket}", payload, ex=ttl_seconds, nx=True)
    else:
        async with _LOCAL_LOCK:
            _cleanup_local_tickets()
            _LOCAL_TICKETS[ticket] = (user_id, time.time() + ttl_seconds)
    return {
        "ticket": ticket,
        "expires_in": ttl_seconds,
    }


async def consume_realtime_ticket(ticket: str) -> str | None:
    redis_client = await get_redis_client()
    if redis_client is not None:
        key = f"notifications:ticket:{ticket}"
        try:
            raw = await redis_client.execute_command("GETDEL", key)
        except Exception:
            raw = await redis_client.get(key)
            if raw is not None:
                await redis_client.delete(key)
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return str(payload.get("user_id") or "").strip() or None

    async with _LOCAL_LOCK:
        _cleanup_local_tickets()
        entry = _LOCAL_TICKETS.pop(ticket, None)
        if entry is None:
            return None
        user_id, expires_at = entry
        if expires_at <= time.time():
            return None
        return user_id


async def register_local_connection(user_id: str, websocket: WebSocket) -> None:
    async with _LOCAL_LOCK:
        _LOCAL_CONNECTIONS[user_id].add(websocket)


async def unregister_local_connection(user_id: str, websocket: WebSocket) -> None:
    async with _LOCAL_LOCK:
        bucket = _LOCAL_CONNECTIONS.get(user_id)
        if not bucket:
            return
        bucket.discard(websocket)
        if not bucket:
            _LOCAL_CONNECTIONS.pop(user_id, None)


async def _broadcast_local(user_id: str, message: str) -> None:
    async with _LOCAL_LOCK:
        sockets = list(_LOCAL_CONNECTIONS.get(user_id, set()))
    stale: list[WebSocket] = []
    for socket in sockets:
        try:
            await socket.send_text(message)
        except Exception:
            stale.append(socket)
    for socket in stale:
        await unregister_local_connection(user_id, socket)


async def publish_user_event(user_id: str, event_type: str, data: Any) -> None:
    message = build_ws_message(event_type, data)
    redis_client = await get_redis_client()
    if redis_client is not None:
        await redis_client.publish(f"{_CHANNEL_PREFIX}{user_id}", message)
        return
    await _broadcast_local(user_id, message)


async def stream_user_events(user_id: str, websocket: WebSocket, *, ping_interval_seconds: int = 20) -> None:
    await register_local_connection(user_id, websocket)
    redis_client = await get_redis_client()
    pubsub = None

    async def _ping_loop() -> None:
        while True:
            await asyncio.sleep(ping_interval_seconds)
            await websocket.send_text(build_ws_message("system.ping", {"ts": int(time.time())}))

    async def _receive_loop() -> None:
        while True:
            await websocket.receive_text()

    async def _redis_loop() -> None:
        nonlocal pubsub
        if redis_client is None:
            await asyncio.Future()
        pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
        await pubsub.subscribe(f"{_CHANNEL_PREFIX}{user_id}")
        while True:
            message = await pubsub.get_message(timeout=1.0)
            if not message:
                await asyncio.sleep(0.1)
                continue
            data = message.get("data")
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            if not data:
                continue
            await websocket.send_text(str(data))

    tasks = [
        asyncio.create_task(_ping_loop()),
        asyncio.create_task(_receive_loop()),
        asyncio.create_task(_redis_loop()),
    ]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            task.result()
        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    finally:
        if pubsub is not None:
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe(f"{_CHANNEL_PREFIX}{user_id}")
            with contextlib.suppress(Exception):
                await pubsub.aclose()
        await unregister_local_connection(user_id, websocket)
