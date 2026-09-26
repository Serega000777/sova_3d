"""WS /projects/{project_id}/live — the project's live room (F-018)."""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections.abc import Callable, Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocketState

from app import live
from app.api.errors import APIError
from app.auth import authenticate
from app.models.core import Project, User
from app.models.versioning import ProjectVersion
from app.services import projects

router = APIRouter(tags=["live"])
HELLO_TIMEOUT_SECONDS = 10.0
# Close codes in the application range: the browser reads them, a proxy never sends them.
UNAUTHORIZED, FORBIDDEN = 4401, 4403

SessionOpener = Callable[[], contextlib.AbstractContextManager[Session]]


def get_live_sessions(websocket: WebSocket) -> SessionOpener:
    """Short sessions, one per check: a room is open for hours and must not hold a
    database connection that long."""
    factory = websocket.app.state.session_factory

    @contextlib.contextmanager
    def open_session() -> Iterator[Session]:
        session = factory()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    return open_session


LiveSessions = Annotated[SessionOpener, Depends(get_live_sessions)]


def _head(db: Session, project_id: uuid.UUID) -> dict[str, Any] | None:
    project = db.get(Project, project_id)
    if project is None or project.deleted_at is not None or project.head_version_id is None:
        return None
    version = db.get(ProjectVersion, project.head_version_id)
    if version is None:
        return None
    return {
        "version_id": str(version.id),
        "sequence_no": version.sequence_no,
        "label": version.label,
        "created_by": str(version.created_by) if version.created_by else None,
    }


@router.websocket("/projects/{project_id}/live")
async def live_room(websocket: WebSocket, project_id: uuid.UUID, sessions: LiveSessions) -> None:
    await websocket.accept()
    # The token comes in the first message, not the URL: URLs end up in proxy logs.
    try:
        hello = await asyncio.wait_for(websocket.receive_json(), HELLO_TIMEOUT_SECONDS)
    except (TimeoutError, ValueError, WebSocketDisconnect):
        await websocket.close(code=UNAUTHORIZED)
        return
    token = hello.get("token") if isinstance(hello, dict) and hello.get("type") == "hello" else None

    def admit() -> tuple[live.Member, dict[str, Any] | None] | int:
        with sessions() as db:
            principal = authenticate(db, token) if isinstance(token, str) else None
            if principal is None:
                return UNAUTHORIZED
            try:
                projects.get_project(db, user_id=principal.user_id, project_id=project_id)
            except APIError:
                return FORBIDDEN  # not found and not allowed look the same from outside
            user = db.get(User, principal.user_id)
            name = None
            if user is not None:
                name = user.display_name or (user.email.split("@")[0] if user.email else None)
            return live.member_for(principal.user_id, name), _head(db, project_id)

    admitted = await run_in_threadpool(admit)
    if isinstance(admitted, int):
        await websocket.close(code=admitted)
        return
    member, head = admitted
    broker: live.Broker = websocket.app.state.live_broker
    room = str(project_id)

    async def read_head() -> dict[str, Any] | None:
        def read() -> dict[str, Any] | None:
            with sessions() as db:
                return _head(db, project_id)

        return await run_in_threadpool(read)

    async def announce_version(new_head: dict[str, Any]) -> None:
        await websocket.send_json({"type": "version", **new_head})

    async with broker.listen(room) as events:
        await broker.join(room, member)
        try:
            await websocket.send_json(
                {
                    "type": "welcome",
                    "you": member.model_dump(),
                    "members": [m.model_dump() for m in await broker.members(room)],
                    "head": head,
                }
            )
            await broker.publish(
                room, {"type": "join", "session": member.session, "member": member.model_dump()}
            )

            async def outgoing() -> None:
                async for event in events:
                    if event.get("session") == member.session and event.get("type") != "note":
                        continue  # your own pointer is already under your finger
                    await websocket.send_json(event)

            async def incoming() -> None:
                limit = live.RateLimit()
                while True:
                    raw = await websocket.receive_text()
                    if not limit.allow(time.monotonic()):
                        continue  # a flood is dropped, not queued
                    try:
                        message = live.parse_client(raw)
                    except ValueError as exc:
                        await websocket.send_json({"type": "error", "message": str(exc)})
                        continue
                    if isinstance(message, live.Ping):
                        await broker.join(room, member)  # the heartbeat keeps presence alive
                        await websocket.send_json({"type": "pong"})
                        continue
                    await broker.publish(room, live.stamp(message, member))

            poll = float(getattr(websocket.app.state, "live_poll_seconds", 2.0))
            tasks = [
                asyncio.create_task(outgoing()),
                asyncio.create_task(incoming()),
                asyncio.create_task(live.watch_head(read_head, announce_version, head, poll)),
            ]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    failure = None if task.cancelled() else task.exception()
                    # a send racing the client's goodbye is how rooms end, not an error
                    gone = websocket.client_state is not WebSocketState.CONNECTED
                    if failure is not None and not isinstance(failure, WebSocketDisconnect):
                        if not gone:
                            raise failure
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            await broker.leave(room, member.session)
            await broker.publish(room, {"type": "leave", "session": member.session})
