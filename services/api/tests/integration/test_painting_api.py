"""E14 (F-034): colour a model. The shape never changes; the colour is a new version."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models import Asset, ProjectVersion
from app.models.execution import JobStatus
from app.models.versioning import AssetRole
from app.storage import S3Storage
from tests.integration.conftest import Actor
from tests.integration.test_ai_commands import kernel_or_fake  # noqa: F401 — fake kernel
from tests.integration.test_imports_api import project, run_all, upload  # noqa: F401

TOP_FACE = {
    "kind": "lasso",
    "axis": "z",
    "offset_mm": 10,
    "depth_mm": 2,
    "points_mm": [[5, 5], [25, 5], [25, 15], [5, 15]],
}


def corner_box_stl() -> bytes:
    """A 30 × 20 × 10 box sitting at the origin, like everything the kernel makes."""
    import trimesh

    mesh = trimesh.creation.box(extents=(30, 20, 10))
    mesh.apply_translation([15, 10, 5])
    exported = mesh.export(file_type="stl")
    return exported if isinstance(exported, bytes) else str(exported).encode()


def imported_version(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage, project_id: str
) -> str:
    """A 30 × 20 × 10 box, uploaded the way a user would."""
    asset_id = upload(api_client, actor, corner_box_stl(), "box.stl", "model/stl")
    api_client.post(
        f"/api/v1/projects/{project_id}/imports",
        json={"asset_id": asset_id},
        headers=actor.headers,
    )
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    return str((job.result or {})["version_id"])


def paint(api_client: TestClient, actor: Actor, version_id: str, **body: Any) -> Any:
    return api_client.post(f"/api/v1/models/{version_id}/paint", json=body, headers=actor.headers)


def test_painting_keeps_the_shape_and_adds_a_coloured_preview(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id = imported_version(api_client, actor, db_session, storage, project)
    before = db_session.get(ProjectVersion, version_id)
    assert before is not None
    model_asset = {link.role: link.asset_id for link in before.assets}[AssetRole.model]

    response = paint(
        api_client,
        actor,
        version_id,
        base_colour="#202020",
        strokes=[{"colour": "#ff5533", "region": TOP_FACE}],
        label="Red top",
    )
    assert response.status_code == 202, response.text

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["paint"]["painted_faces"] > 0
    assert "#ff5533" in result["paint"]["colours"]

    painted = db_session.get(ProjectVersion, result["version_id"])
    assert painted is not None
    roles = {link.role: link.asset_id for link in painted.assets}
    # The printable model is the same asset — colour is not a change of shape.
    assert roles[AssetRole.model] == model_asset
    preview = db_session.get(Asset, roles[AssetRole.preview])
    assert preview is not None and preview.format == "glb"
    assert painted.label == "Red top"
    assert painted.provenance["strokes"][0]["colour"] == "#ff5533"


def test_painting_a_painted_version_keeps_the_earlier_strokes(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    """Paint accumulates: the second stroke does not wipe the first (F-034)."""
    version_id = imported_version(api_client, actor, db_session, storage, project)
    paint(
        api_client,
        actor,
        version_id,
        base_colour="#202020",
        strokes=[{"colour": "#ff5533", "region": TOP_FACE}],
    )
    (first,) = run_all(db_session, storage)
    assert first.status is JobStatus.succeeded, first.error
    painted_once = str((first.result or {})["version_id"])

    side = {"kind": "box", "min_mm": [0, 0, 0], "max_mm": [30, 20, 3]}
    paint(api_client, actor, painted_once, strokes=[{"colour": "#5b9cff", "region": side}])
    (second,) = run_all(db_session, storage)
    assert second.status is JobStatus.succeeded, second.error
    report = (second.result or {})["paint"]
    assert {"#202020", "#ff5533", "#5b9cff"} <= set(report["colours"])

    twice = db_session.get(ProjectVersion, (second.result or {})["version_id"])
    assert twice is not None
    assert [s["colour"] for s in twice.provenance["strokes"]] == ["#ff5533", "#5b9cff"]
    assert twice.provenance["base_colour"] == "#202020"

    # ...unless the caller asks to start from the bare model.
    paint(
        api_client,
        actor,
        str(twice.id),
        strokes=[{"colour": "#35c48d"}],
        replace=True,
    )
    (third,) = run_all(db_session, storage)
    assert third.status is JobStatus.succeeded, third.error
    fresh = db_session.get(ProjectVersion, (third.result or {})["version_id"])
    assert fresh is not None
    assert [s["colour"] for s in fresh.provenance["strokes"]] == ["#35c48d"]


def test_a_painted_version_keeps_its_parametric_history(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    """Paint on a kernel-built part, then keep editing it: the history survives the paint."""
    import sqlalchemy as sa
    from worker import geometry as kernel

    from app.models.execution import Operation

    response = api_client.post(
        f"/api/v1/projects/{project}/ai-commands",
        json={"prompt": "Plate 40x30x6 mm", "units": "mm", "target": "print"},
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    (built,) = run_all(db_session, storage)
    assert built.status is JobStatus.succeeded, built.error
    built_id = str((built.result or {})["version_id"])

    paint(api_client, actor, built_id, strokes=[{"colour": "#ff5533"}])
    (painted_job,) = run_all(db_session, storage)
    assert painted_job.status is JobStatus.succeeded, painted_job.error
    painted_id = str((painted_job.result or {})["version_id"])

    def operations(version_id: str) -> list[tuple[int, str]]:
        rows = db_session.scalars(
            sa.select(Operation)
            .where(Operation.project_version_id == version_id)
            .order_by(Operation.sequence_no)
        ).all()
        return [(row.sequence_no, row.operation_type) for row in rows]

    assert operations(painted_id) == operations(built_id) != []
    painted = db_session.get(ProjectVersion, painted_id)
    assert painted is not None
    roles = {link.role for link in painted.assets}
    assert {AssetRole.model, AssetRole.source, AssetRole.preview} <= roles  # BREP kept
    bodies = painted.provenance.get("bodies")
    assert bodies  # the kernel bodies, for targeting
    target = bodies[-1]["name"]

    # The editor works on the painted version like on any other.
    response = api_client.post(
        f"/api/v1/models/{painted_id}/edits",
        json={
            "operations": [{"type": "set_dimensions", "target": target, "width_mm": 50}],
            "label": "Wider",
        },
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    (edited,) = run_all(db_session, storage)
    assert edited.status is JobStatus.succeeded, edited.error
    if kernel.available():  # the real kernel actually rescales the body
        size = (edited.result or {})["bodies"][-1]["bbox_mm"]["size"]
        assert size[0] == pytest.approx(50, abs=0.01)


def test_a_stroke_that_misses_the_model_says_so(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id = imported_version(api_client, actor, db_session, storage, project)
    miss = {
        "kind": "box",
        "min_mm": [500, 500, 500],
        "max_mm": [510, 510, 510],
    }
    paint(api_client, actor, version_id, strokes=[{"colour": "#00ff00", "region": miss}])
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.failed
    assert (job.error or {})["code"] == "nothing_painted"


def test_painting_a_whole_body_needs_no_region(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id = imported_version(api_client, actor, db_session, storage, project)
    paint(api_client, actor, version_id, strokes=[{"colour": "#1188ff"}])
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    report = (job.result or {})["paint"]
    assert report["painted_faces"] == report["faces"]  # all of it


def test_an_empty_paint_request_is_refused(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id = imported_version(api_client, actor, db_session, storage, project)
    response = paint(api_client, actor, version_id)
    assert response.status_code == 422
    assert "nothing to paint" in response.json()["error"]["message"]


def test_a_bad_colour_is_refused_before_the_job(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id = imported_version(api_client, actor, db_session, storage, project)
    response = paint(api_client, actor, version_id, strokes=[{"colour": "red"}])
    assert response.status_code == 422


def test_the_worker_and_the_api_agree_on_the_region_shape() -> None:
    """Both sides parse the same JSON; the worker never imports the API to do it."""
    from worker.paint import BoxRegion as WorkerBox
    from worker.paint import LassoRegion as WorkerLasso

    from app.geometry.region import BoxRegion as ApiBox
    from app.geometry.region import LassoRegion as ApiLasso

    box = {"kind": "box", "min_mm": [0, 0, 0], "max_mm": [1, 2, 3]}
    lasso = TOP_FACE
    assert ApiBox.model_validate(box).model_dump() == WorkerBox.model_validate(box).model_dump()
    api_lasso = ApiLasso.model_validate(lasso).model_dump()
    worker_lasso = WorkerLasso.model_validate(lasso).model_dump()
    assert api_lasso == worker_lasso


@pytest.mark.parametrize("target", ["glb", "ply", "obj"])
def test_painted_colours_survive_export(target: str) -> None:
    """A colour-carrying format must actually carry the colours out (F-014).

    PLY stores a colour per face, so it comes back exactly; glTF and OBJ store colour per
    vertex, so the stroke's own colour and the base are both there with a one-triangle
    blend between them.
    """
    import tempfile
    from pathlib import Path

    import trimesh
    from worker.paint import LassoRegion, PaintRequest, Stroke, paint_file

    tmp = Path(tempfile.mkdtemp())
    mesh = trimesh.creation.box(extents=(30, 20, 10))
    mesh.apply_translation([15, 10, 5])
    source = tmp / "box.stl"
    source.write_bytes(mesh.export(file_type="stl"))

    request = PaintRequest(
        base_colour="#202020",
        strokes=[Stroke(colour="#ff5533", region=LassoRegion.model_validate(TOP_FACE))],
    )
    output = tmp / f"painted.{target}"
    result = paint_file(source, "stl", request, output, target)
    assert result.ok and result.painted_faces > 0

    from worker.importers.common import as_single_mesh

    loaded = as_single_mesh(trimesh.load(output, force="mesh"))
    assert loaded is not None
    visual = loaded.visual
    assert visual is not None and hasattr(visual, "face_colors")
    colours = {tuple(colour[:3]) for colour in visual.face_colors}
    assert (255, 85, 51) in colours  # the stroke
    assert (32, 32, 32) in colours  # the base
