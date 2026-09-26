"""Live project rooms (F-018): who has the project open, where they point, what changed.

Everyone with the same project open joins one room. The room relays what people do that
the others should see — a pointer on the model, the body they selected, a short note pinned
to a point — and tells everyone the moment a new version lands, whoever or whatever made it
(an AI command, a manual edit, a job on the worker). Edits themselves stay what they are:
immutable versions, so two people changing the model at once branch rather than overwrite.

Relaying goes through a broker: in-process for a single API instance (and tests), Redis
pub/sub when several instances share rooms. New versions are noticed by the room itself
polling the project's head — no producer anywhere has to know rooms exist.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

MAX_MESSAGE_BYTES = 4096
MAX_MESSAGES_PER_SECOND = 20
PRESENCE_TTL_SECONDS = 45
COLOURS = ("#e4572e", "#29a19c", "#f3a712", "#8e7dbe", "#4c8bf5", "#d64f9b", "#6ab04c")


class Member(BaseModel):
    session: str
    user_id: str
    name: str
    colour: str


class Cursor(BaseModel):
    type: Literal["cursor"]
    point: tuple[float, float, float] | None = None
    body: str | None = Field(default=None, max_length=120)


class Note(BaseModel):
    type: Literal["note"]
    text: str = Field(min_length=1, max_length=300)
    point: tuple[float, float, float] | None = None


class Ping(BaseModel):
    type: Literal["ping"]


ClientMessage: TypeAdapter[Cursor | Note | Ping] = TypeAdapter(Cursor | Note | Ping)


def member_for(user_id: uuid.UUID, name: str | None) -> Member:
    digest = hashlib.sha256(str(user_id).encode()).digest()
    return Member(
        session=uuid.uuid4().hex,
        user_id=str(user_id),
        name=(name or "someone")[:60],
        colour=COLOURS[digest[0] % len(COLOURS)],
    )


def parse_client(raw: str) -> Cursor | Note | Ping:
    if len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise ValueError("message too large")
    try:
        message: Cursor | Note | Ping = ClientMessage.validate_json(raw)
    except ValidationError as exc:
        raise ValueError("not a message this room understands") from exc
    return message


# --- brokers --------------------------------------------------------------------------------


class Broker(Protocol):
    async def publish(self, room: str, message: dict[str, Any]) -> None: ...

    def listen(
        self, room: str
    ) -> contextlib.AbstractAsyncContextManager[AsyncIterator[dict[str, Any]]]: ...

    async def join(self, room: str, member: Member) -> None: ...

    async def leave(self, room: str, session: str) -> None: ...

    async def members(self, room: str) -> list[Member]: ...


@dataclass
class MemoryBroker:
    """One process's rooms: enough for a single API instance, and for tests."""

    queues: dict[str, set[asyncio.Queue[dict[str, Any]]]] = field(default_factory=dict)
    present: dict[str, dict[str, Member]] = field(default_factory=dict)

    async def publish(self, room: str, message: dict[str, Any]) -> None:
        for queue in list(self.queues.get(room, ())):
            queue.put_nowait(message)

    @contextlib.asynccontextmanager
    async def listen(self, room: str) -> AsyncIterator[AsyncIterator[dict[str, Any]]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.queues.setdefault(room, set()).add(queue)

        async def messages() -> AsyncIterator[dict[str, Any]]:
            while True:
                yield await queue.get()

        try:
            yield messages()
        finally:
            self.queues[room].discard(queue)

    async def join(self, room: str, member: Member) -> None:
        self.present.setdefault(room, {})[member.session] = member

    async def leave(self, room: str, session: str) -> None:
        self.present.get(room, {}).pop(session, None)

    async def members(self, room: str) -> list[Member]:
        return list(self.present.get(room, {}).values())


class RedisBroker:
    """Rooms shared by every API instance: pub/sub for events, a sorted set for presence
    (scored by expiry, refreshed by each connection's heartbeat, so a crashed instance's
    members age out instead of haunting the room)."""

    def __init__(self, url: str) -> None:
        import redis.asyncio as redis

        self.redis = redis.from_url(url, decode_responses=True)

    async def publish(self, room: str, message: dict[str, Any]) -> None:
        await self.redis.publish(f"live:{room}", json.dumps(message))

    @contextlib.asynccontextmanager
    async def listen(self, room: str) -> AsyncIterator[AsyncIterator[dict[str, Any]]]:
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(f"live:{room}")

        async def messages() -> AsyncIterator[dict[str, Any]]:
            async for raw in pubsub.listen():
                if raw.get("type") == "message":
                    yield json.loads(raw["data"])

        try:
            yield messages()
        finally:
            await pubsub.unsubscribe(f"live:{room}")
            await pubsub.aclose()  # type: ignore[no-untyped-call]

    async def join(self, room: str, member: Member) -> None:
        expires = time.time() + PRESENCE_TTL_SECONDS
        async with self.redis.pipeline() as pipe:
            pipe.zadd(f"live:{room}:members", {member.session: expires})
            pipe.hset(f"live:{room}:data", member.session, member.model_dump_json())
            pipe.expire(f"live:{room}:data", PRESENCE_TTL_SECONDS * 4)
            await pipe.execute()

    async def leave(self, room: str, session: str) -> None:
        async with self.redis.pipeline() as pipe:
            pipe.zrem(f"live:{room}:members", session)
            pipe.hdel(f"live:{room}:data", session)
            await pipe.execute()

    async def members(self, room: str) -> list[Member]:
        now = time.time()
        await self.redis.zremrangebyscore(f"live:{room}:members", 0, now)
        sessions = [str(s) for s in await self.redis.zrange(f"live:{room}:members", 0, -1)]
        if not sessions:
            return []
        rows = await self.redis.hmget(f"live:{room}:data", sessions)
        return [Member.model_validate_json(row) for row in rows if row]


def broker_for(kind: str, redis_url: str) -> Broker:
    return RedisBroker(redis_url) if kind == "redis" else MemoryBroker()


# --- one connection's life in a room ---------------------------------------------------------


@dataclass
class RateLimit:
    per_second: int = MAX_MESSAGES_PER_SECOND
    window_start: float = 0.0
    count: int = 0

    def allow(self, now: float) -> bool:
        if now - self.window_start >= 1.0:
            self.window_start, self.count = now, 0
        self.count += 1
        return self.count <= self.per_second


def stamp(message: Cursor | Note, member: Member) -> dict[str, Any]:
    """A client's message as the room sees it: who sent it, and when."""
    event = message.model_dump(mode="json")
    event["session"] = member.session
    if isinstance(message, Note):
        event["member"] = member.model_dump()
        event["at"] = datetime.now(UTC).isoformat(timespec="seconds")
    return event


async def watch_head(
    read_head: Callable[[], Any],
    publish: Callable[[dict[str, Any]], Any],
    last: Any,
    every_seconds: float,
) -> None:
    """Tell the room when the project's head changes (whoever changed it)."""
    while True:
        await asyncio.sleep(every_seconds)
        head = await read_head()
        if head is not None and head != last:
            last = head
            await publish(head)
