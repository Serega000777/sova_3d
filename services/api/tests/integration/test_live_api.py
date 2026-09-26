"""F-018 end to end: two people in one project's live room."""

from __future__ import annotations

import contextlib
import threading
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketDisconnect

from app.api.live import FORBIDDEN, UNAUTHORIZED, get_live_sessions
from app.models.core import WorkspaceRole
from app.services import projects
from tests.integration.conftest import Actor, make_actor
from tests.integration.test_imports_api import project  # noqa: F401

LOCK = threading.Lock()  # the room's threads and the test share one test session


@pytest.fixture
def room(api_client: TestClient, db_session: Session) -> Iterator[TestClient]:
    @contextlib.contextmanager
    def opener() -> Iterator[Session]:
        with LOCK:
            yield db_session

    api_client.app.dependency_overrides[get_live_sessions] = lambda: opener  # type: ignore[attr-defined]
    api_client.app.state.live_poll_seconds = 0.05  # type: ignore[attr-defined]
    yield api_client
    api_client.app.dependency_overrides.pop(get_live_sessions, None)  # type: ignore[attr-defined]


def _until(ws: Any, kind: str) -> dict[str, Any]:
    for _ in range(50):
        event: dict[str, Any] = ws.receive_json()
        if event["type"] == kind:
            return event
    raise AssertionError(f"no {kind} event")


def _closed_with(room: TestClient, url: str, hello: dict[str, Any]) -> int:
    with room.websocket_connect(url) as ws:
        ws.send_json(hello)
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    return closed.value.code


def test_strangers_and_bad_tokens_are_turned_away(
    room: TestClient,
    actor: Actor,
    db_session: Session,
    project: str,  # noqa: F811
) -> None:
    url = f"/api/v1/projects/{project}/live"
    assert _closed_with(room, url, {"type": "hello", "token": "nope"}) == UNAUTHORIZED
    assert _closed_with(room, url, {"type": "hi"}) == UNAUTHORIZED
    stranger = make_actor(db_session)
    assert _closed_with(room, url, {"type": "hello", "token": stranger.token}) == FORBIDDEN
    missing = f"/api/v1/projects/{uuid.uuid4()}/live"
    assert _closed_with(room, missing, {"type": "hello", "token": actor.token}) == FORBIDDEN


def test_two_people_see_each_other_point_and_leave_notes(
    room: TestClient,
    actor: Actor,
    db_session: Session,
    project: str,  # noqa: F811
) -> None:
    viewer = make_actor(db_session, WorkspaceRole.viewer, workspace=actor.workspace)
    url = f"/api/v1/projects/{project}/live"
    with room.websocket_connect(url) as ann:
        ann.send_json({"type": "hello", "token": actor.token})
        welcome = _until(ann, "welcome")
        assert [m["session"] for m in welcome["members"]] == [welcome["you"]["session"]]
        with room.websocket_connect(url) as bob:
            bob.send_json({"type": "hello", "token": viewer.token})
            bob_welcome = _until(bob, "welcome")
            assert len(bob_welcome["members"]) == 2
            joined = _until(ann, "join")
            assert joined["member"]["session"] == bob_welcome["you"]["session"]

            bob.send_json({"type": "cursor", "point": [1.5, 2, 3], "body": "body"})
            cursor = _until(ann, "cursor")
            assert (
                cursor["point"] == [1.5, 2.0, 3.0]
                and cursor["session"] == joined["member"]["session"]
            )

            ann.send_json({"type": "note", "text": "make this hole 5 mm", "point": [0, 0, 1]})
            for ws in (ann, bob):  # a note is shown to its author too, stamped
                note = _until(ws, "note")
                assert (
                    note["text"] == "make this hole 5 mm"
                    and note["member"]["session"] == welcome["you"]["session"]
                )

            ann.send_json({"type": "shell", "cmd": "rm -rf /"})
            assert "understands" in _until(ann, "error")["message"]
            ann.send_json({"type": "ping"})
            assert _until(ann, "pong") == {"type": "pong"}
        left = _until(ann, "leave")
        assert left["session"] == bob_welcome["you"]["session"]


def test_everyone_hears_about_a_new_version(
    room: TestClient,
    actor: Actor,
    db_session: Session,
    project: str,  # noqa: F811
) -> None:
    with room.websocket_connect(f"/api/v1/projects/{project}/live") as ws:
        ws.send_json({"type": "hello", "token": actor.token})
        assert _until(ws, "welcome")["head"] is None
        with LOCK:
            version = projects.create_version_internal(
                db_session, project_id=uuid.UUID(project), label="Handle added"
            )
            db_session.flush()
        event = _until(ws, "version")
        assert event["version_id"] == str(version.id) and event["label"] == "Handle added"
