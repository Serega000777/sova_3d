"""F-018: the Redis broker shares a room between API instances (skipped without Redis)."""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any

import pytest

from app import live

REDIS_URL = os.environ.get("TEST_REDIS_URL") or os.environ.get(
    "REDIS_URL", "redis://127.0.0.1:16379/2"
)


def test_two_brokers_share_one_room() -> None:
    async def scenario() -> tuple[list[dict[str, Any]], list[str], list[str]]:
        first, second = live.RedisBroker(REDIS_URL), live.RedisBroker(REDIS_URL)
        try:
            await first.redis.ping()
        except Exception as exc:  # noqa: BLE001 — any connection failure means "no Redis here"
            # the in-memory broker is the default; this one is optional infrastructure
            pytest.skip(f"Redis unreachable at {REDIS_URL}: {exc}")
        room = uuid.uuid4().hex
        ann = live.member_for(uuid.uuid4(), "Ann")
        async with second.listen(room) as events:
            await asyncio.sleep(0.1)  # the subscription is live before anything is said
            await first.join(room, ann)
            await first.publish(room, {"type": "join", "session": ann.session})
            received = [await asyncio.wait_for(anext(events), 5)]
        present = [m.name for m in await second.members(room)]
        await first.leave(room, ann.session)
        gone = [m.name for m in await second.members(room)]
        await first.redis.aclose()
        await second.redis.aclose()
        return received, present, gone

    received, present, gone = asyncio.run(scenario())
    assert received[0]["type"] == "join"
    assert present == ["Ann"] and gone == []
