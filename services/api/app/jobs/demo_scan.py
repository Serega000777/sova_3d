"""`demo_scan` job (F-082): a simulated turntable scanner run on the server, so the Scanner
section can be seen working without a device — fragments arrive one by one with a pause
between them, then the scan finalizes and the platform fuses them like any scanner session.

The object is the same bracket the bridge's simulated driver uses (a plate with a ring,
120 × 60 × 40 mm), so the fused result is checkable against known numbers.
"""

from __future__ import annotations

import io
import math
import time
import uuid
from typing import Any

import numpy as np
import trimesh

from app.jobs.artifacts import store_derived_asset
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.scanning import FrameKind, ScanSession
from app.services import scanning
from app.services.scanning import DEMO_SCAN_JOB

STEPS = 8
PAUSE_S = 1.2  # long enough to watch the fragments arrive, short enough not to bore


def bracket() -> trimesh.Trimesh:
    plate = trimesh.creation.box(extents=(120, 60, 25))
    plate.apply_translation((60, 30, 12.5))
    ring = trimesh.creation.annulus(r_min=10.0, r_max=16.0, height=15.0, sections=48)
    ring.apply_translation((90, 30, 25 + 7.5))
    merged = trimesh.util.concatenate([plate, ring])
    assert isinstance(merged, trimesh.Trimesh)
    return merged


def fragments(steps: int = STEPS) -> list[tuple[int, bytes, dict[str, Any]]]:
    """(sequence_no, PLY bytes, pose) for each turntable step — the faces a scanner looking
    from that angle would see, delivered rotated by the table's angle, as a device does."""
    mesh = bracket()
    centre = mesh.bounds.mean(axis=0)
    normals = np.asarray(mesh.face_normals, dtype=float)
    out: list[tuple[int, bytes, dict[str, Any]]] = []
    for step in range(steps):
        azimuth = 360.0 * step / steps
        view = np.array([math.cos(math.radians(azimuth)), math.sin(math.radians(azimuth)), 0.4])
        view /= np.linalg.norm(view)
        facing = (normals @ view) > 0.15
        facing |= normals[:, 2] > 0.9
        piece = mesh.copy()
        piece.update_faces(facing)
        piece.remove_unreferenced_vertices()
        turn = trimesh.transformations.rotation_matrix(  # type: ignore[no-untyped-call]
            math.radians(azimuth), [0, 0, 1], point=centre
        )
        piece.apply_transform(turn)
        data = io.BytesIO()
        piece.export(data, file_type="ply")
        out.append(
            (
                step,
                data.getvalue(),
                {"azimuth_deg": azimuth, "turntable_centre_mm": [float(v) for v in centre]},
            )
        )
    return out


@register(DEMO_SCAN_JOB)
def handle_demo_scan(ctx: JobContext) -> dict[str, Any]:
    session_id = uuid.UUID(str(ctx.job.input["scan_session_id"]))
    session = ctx.db.get(ScanSession, session_id)
    if session is None:
        raise JobFailureError("scan_not_found", str(session_id))
    user_id = ctx.job.created_by
    assert user_id is not None
    pause = float(ctx.job.input.get("pause_s", PAUSE_S))
    pieces = fragments()
    faces = 0
    for index, (sequence_no, data, pose) in enumerate(pieces, start=1):
        ctx.check_still_wanted()
        ctx.db.refresh(session, ["status"])
        if session.status not in scanning.OPEN_STATES:
            return {"scan_session_id": str(session.id), "status": session.status.value}
        piece = trimesh.load(io.BytesIO(data), file_type="ply", force="mesh")
        assert isinstance(piece, trimesh.Trimesh)
        face_count = len(piece.faces)
        asset = store_derived_asset(
            ctx,
            workspace_id=session.workspace_id,
            data=data,
            format_id="ply",
            metadata={"operation": DEMO_SCAN_JOB, "job_id": str(ctx.job.id), "step": sequence_no},
            created_by=user_id,
        )
        scanning.add_frame(
            ctx.db,
            user_id=user_id,
            session_id=session.id,
            asset_id=asset.id,
            sequence_no=sequence_no,
            kind=FrameKind.mesh,
            pose=pose,
            quality={"faces": face_count},
        )
        faces += face_count
        ctx.progress(int(10 + 70 * index / len(pieces)), f"fragment {index}/{len(pieces)}")
        ctx.db.flush()
        ctx.commit()  # the Scanner page polls: every fragment shows the moment it lands
        if pause > 0 and index < len(pieces):
            time.sleep(pause)
    scanning.update_capture_stats(
        ctx.db,
        user_id=user_id,
        session_id=session.id,
        stats={"fragments": len(pieces), "faces": faces, "device": "simulated turntable"},
    )
    job = scanning.finalize(ctx.db, user_id=user_id, session_id=session.id)
    ctx.progress(100, "finalized")
    return {
        "scan_session_id": str(session.id),
        "fragments": len(pieces),
        "reconstruction_job_id": str(job.id),
    }
