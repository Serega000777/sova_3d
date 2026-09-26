"""F-018: the live room's rules, without a database or a socket."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import pytest

from app import live


def test_messages_are_validated_and_bounded() -> None:
    cursor = live.parse_client(json.dumps({"type": "cursor", "point": [1, 2, 3], "body": "b"}))
    assert isinstance(cursor, live.Cursor) and cursor.point == (1.0, 2.0, 3.0)
    assert isinstance(live.parse_client('{"type": "ping"}'), live.Ping)
    for bad in (
        '{"type": "cursor", "point": [1, 2]}',
        '{"type": "note", "text": ""}',
        '{"type": "shell", "cmd": "rm"}',
        "not json",
        json.dumps({"type": "note", "text": "x" * 5000}),
    ):
        with pytest.raises(ValueError):
            live.parse_client(bad)


def test_a_flood_is_cut_at_the_per_second_budget() -> None:
    limit = live.RateLimit(per_second=3)
    assert [limit.allow(10.0) for _ in range(5)] == [True, True, True, False, False]
    assert limit.allow(11.1)  # a new second, a new budget


def test_members_keep_their_colour_and_a_short_name() -> None:
    user = uuid.uuid4()
    first, second = live.member_for(user, "a" * 100), live.member_for(user, None)
    assert first.colour == second.colour and first.session != second.session
    assert len(first.name) == 60 and second.name == "someone"


def test_notes_carry_who_and_when_cursors_only_who() -> None:
    member = live.member_for(uuid.uuid4(), "Ann")
    note = live.stamp(live.Note(type="note", text="hole too small", point=(0, 0, 5)), member)
    assert note["session"] == member.session and note["member"]["name"] == "Ann" and note["at"]
    cursor = live.stamp(live.Cursor(type="cursor", point=None), member)
    assert cursor == {"type": "cursor", "point": None, "body": None, "session": member.session}


def test_the_memory_broker_relays_to_listeners_and_tracks_presence() -> None:
    async def scenario() -> tuple[list[dict[str, Any]], list[str]]:
        broker = live.MemoryBroker()
        member = live.member_for(uuid.uuid4(), "Ann")
        async with broker.listen("room") as events:
            await broker.join("room", member)
            await broker.publish("room", {"type": "join"})
            await broker.publish("other", {"type": "elsewhere"})
            received = [await anext(events)]
        names = [m.name for m in await broker.members("room")]
        await broker.leave("room", member.session)
        assert await broker.members("room") == []
        return received, names

    received, names = asyncio.run(scenario())
    assert received == [{"type": "join"}] and names == ["Ann"]


def test_the_head_watcher_announces_each_new_version_once() -> None:
    heads = iter([{"version_id": "a"}, {"version_id": "a"}, {"version_id": "b"}, None])
    announced: list[dict[str, Any]] = []

    async def read() -> dict[str, Any] | None:
        try:
            return next(heads)
        except StopIteration:
            raise asyncio.CancelledError from None

    async def publish(head: dict[str, Any]) -> None:
        announced.append(head)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(live.watch_head(read, publish, {"version_id": "a"}, 0))
    assert announced == [{"version_id": "b"}]
