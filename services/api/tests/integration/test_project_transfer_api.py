"""Item 40: fail-closed transfer of a complete immutable project history by email."""

import hashlib
import uuid

import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.core import Project, WorkspaceRole
from app.models.execution import MeshModifier, Operation
from app.models.plan_annotations import PlanAnnotations
from app.models.references import ProjectReference
from app.models.versioning import Asset, AssetKind, VersionAsset
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor


def _asset(
    db: Session,
    storage: S3Storage,
    actor: Actor,
    *,
    data: bytes,
    extension: str,
    mime: str,
    format_: str,
) -> Asset:
    sha = hashlib.sha256(data).hexdigest()
    key = storage.object_key(actor.workspace.id, sha, extension)
    storage.put(key, data, mime)
    row = Asset(
        workspace_id=actor.workspace.id,
        kind=AssetKind.original,
        sha256=sha,
        storage_key=key,
        mime=mime,
        format=format_,
        byte_size=len(data),
        created_by=actor.user.id,
    )
    db.add(row)
    db.flush()
    return row


def _project(api_client: TestClient, actor: Actor, name: str = "Kitchen concept") -> dict:
    response = api_client.post(
        "/api/v1/projects",
        json={"workspace_id": str(actor.workspace.id), "name": name, "description": "handoff"},
        headers=actor.headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_owner_transfers_full_version_graph_assets_reference_and_annotations(
    api_client: TestClient,
    db_session: Session,
    storage: S3Storage,
) -> None:
    owner = make_actor(db_session)
    recipient = make_actor(db_session)
    project = _project(api_client, owner)
    model = _asset(
        db_session,
        storage,
        owner,
        data=b"solid transfer\nendsolid transfer\n",
        extension="stl",
        mime="model/stl",
        format_="stl",
    )
    photo = _asset(
        db_session,
        storage,
        owner,
        data=b"not-a-real-png-but-stored-for-transfer",
        extension="png",
        mime="image/png",
        format_="png",
    )

    first_response = api_client.post(
        f"/api/v1/projects/{project['id']}/versions",
        json={
            "label": "scan",
            "assets": {"model": str(model.id)},
            "provenance": {
                "operation": "scan",
                "scene": {"nodes": [{"id": "room", "asset_id": str(model.id)}]},
            },
        },
        headers=owner.headers,
    )
    assert first_response.status_code == 201, first_response.text
    first = first_response.json()
    second_response = api_client.post(
        f"/api/v1/projects/{project['id']}/versions",
        json={"label": "edited", "assets": {"model": str(model.id)}},
        headers=owner.headers,
    )
    assert second_response.status_code == 201, second_response.text
    second = second_response.json()

    db_session.add(
        Operation(
            project_version_id=uuid.UUID(second["id"]),
            sequence_no=1,
            operation_type="set_dimensions",
            schema_version=1,
            params={"source_asset_id": str(model.id)},
            entity_refs=[],
        )
    )
    db_session.add(
        MeshModifier(
            project_version_id=uuid.UUID(second["id"]),
            sequence_no=1,
            modifier_key="move_1",
            modifier_type="move",
            enabled=True,
            tolerance_mm=0.2,
            params={"asset_id": str(model.id), "delta_mm": [1, 0, 0]},
        )
    )
    db_session.add(
        ProjectReference(
            project_id=uuid.UUID(project["id"]),
            asset_id=photo.id,
            settings={
                "width_px": 100,
                "height_px": 100,
                "width_mm": 3000,
                "known_mm": 0,
                "calibration": [],
                "offset_x": 0,
                "offset_z": 0,
                "opacity": 0.65,
                "visible": True,
            },
        )
    )
    db_session.add(
        PlanAnnotations(
            project_id=uuid.UUID(project["id"]),
            plan_id="ground-floor",
            annotations=[{"id": "issue-1", "photo_asset_ids": [str(photo.id)]}],
            revision=3,
            updated_by=owner.user.id,
        )
    )
    db_session.flush()

    transferred = api_client.post(
        f"/api/v1/projects/{project['id']}/transfer",
        json={
            "recipient_email": recipient.user.email,
            "confirmation_name": project["name"],
        },
        headers=owner.headers,
    )
    assert transferred.status_code == 200, transferred.text
    receipt = transferred.json()
    assert receipt["source_project_id"] == project["id"]
    assert receipt["recipient_email"] == recipient.user.email
    assert receipt["version_count"] == 2
    assert receipt["asset_count"] == 2

    target_id = receipt["target_project_id"]
    source_response = api_client.get(f"/api/v1/projects/{project['id']}", headers=owner.headers)
    assert source_response.status_code == 404
    assert api_client.get(f"/api/v1/projects/{target_id}", headers=owner.headers).status_code == 404
    target_response = api_client.get(f"/api/v1/projects/{target_id}", headers=recipient.headers)
    assert target_response.status_code == 200, target_response.text
    assert target_response.json()["workspace_id"] == str(recipient.workspace.id)

    target_versions = api_client.get(
        f"/api/v1/projects/{target_id}/versions", headers=recipient.headers
    ).json()
    assert [version["sequence_no"] for version in target_versions] == [2, 1]
    target_first = target_versions[1]
    target_second = target_versions[0]
    assert target_second["parent_version_id"] == target_first["id"]
    assert target_first["id"] != first["id"] and target_second["id"] != second["id"]
    copied_model_id = target_first["assets"][0]["asset_id"]
    assert copied_model_id != str(model.id)
    assert target_first["provenance"]["scene"]["nodes"][0]["asset_id"] == copied_model_id
    assert target_first["provenance"]["ownership_transfer"]["source_version_id"] == first["id"]

    copied_assets = list(
        db_session.scalars(sa.select(Asset).where(Asset.workspace_id == recipient.workspace.id))
    )
    assert {asset.sha256 for asset in copied_assets} == {model.sha256, photo.sha256}
    assert all(
        asset.storage_key.startswith(f"ws/{recipient.workspace.id}/") for asset in copied_assets
    )
    assert storage.get(model.storage_key).startswith(b"solid transfer")

    target_reference = api_client.get(
        f"/api/v1/projects/{target_id}/reference", headers=recipient.headers
    )
    assert target_reference.status_code == 200, target_reference.text
    assert target_reference.json()["asset_id"] != str(photo.id)
    annotation = db_session.scalar(
        sa.select(PlanAnnotations).where(PlanAnnotations.project_id == uuid.UUID(target_id))
    )
    assert annotation is not None and annotation.revision == 3
    assert annotation.annotations[0]["photo_asset_ids"][0] == target_reference.json()["asset_id"]

    operation = db_session.scalar(
        sa.select(Operation).where(Operation.project_version_id == uuid.UUID(target_second["id"]))
    )
    modifier = db_session.scalar(
        sa.select(MeshModifier).where(
            MeshModifier.project_version_id == uuid.UUID(target_second["id"])
        )
    )
    assert operation is not None and operation.params["source_asset_id"] == copied_model_id
    assert modifier is not None and modifier.params["asset_id"] == copied_model_id

    source = db_session.get(Project, uuid.UUID(project["id"]))
    assert source is not None and source.deleted_at is not None
    copied_model = db_session.get(Asset, uuid.UUID(copied_model_id))
    assert copied_model is not None
    editable = api_client.post(
        f"/api/v1/projects/{target_id}/versions",
        json={"label": "recipient edit", "assets": {"model": copied_model_id}},
        headers=recipient.headers,
    )
    assert editable.status_code == 201, editable.text


def test_transfer_is_owner_only_and_fails_closed_before_copy(
    api_client: TestClient,
    db_session: Session,
) -> None:
    owner = make_actor(db_session)
    editor = make_actor(db_session, role=WorkspaceRole.editor, workspace=owner.workspace)
    stranger = make_actor(db_session)
    recipient = make_actor(db_session)
    project = _project(api_client, owner, name="Private handoff")
    path = f"/api/v1/projects/{project['id']}/transfer"
    body = {"recipient_email": recipient.user.email, "confirmation_name": project["name"]}

    assert api_client.post(path, json=body, headers=stranger.headers).status_code == 404
    assert api_client.post(path, json=body, headers=editor.headers).status_code == 403
    wrong = api_client.post(
        path,
        json={**body, "confirmation_name": "wrong"},
        headers=owner.headers,
    )
    assert wrong.status_code == 422
    unavailable = api_client.post(
        path,
        json={**body, "recipient_email": "missing@example.com"},
        headers=owner.headers,
    )
    assert unavailable.status_code == 422
    self_transfer = api_client.post(
        path,
        json={**body, "recipient_email": owner.user.email},
        headers=owner.headers,
    )
    assert self_transfer.status_code == 422

    draft = api_client.post(
        f"/api/v1/projects/{project['id']}/versions",
        json={"finalize": False},
        headers=owner.headers,
    )
    assert draft.status_code == 201
    blocked = api_client.post(path, json=body, headers=owner.headers)
    assert blocked.status_code == 409
    assert (
        db_session.scalar(
            sa.select(sa.func.count())
            .select_from(Project)
            .where(Project.workspace_id == recipient.workspace.id)
        )
        == 0
    )


def test_transfer_rejects_malformed_email_without_recipient_disclosure(
    api_client: TestClient,
    db_session: Session,
) -> None:
    owner = make_actor(db_session)
    project = _project(api_client, owner)
    response = api_client.post(
        f"/api/v1/projects/{project['id']}/transfer",
        json={"recipient_email": "not-an-email", "confirmation_name": project["name"]},
        headers=owner.headers,
    )
    assert response.status_code == 422


def test_transfer_assets_are_linked_only_to_the_recipient_workspace(
    api_client: TestClient,
    db_session: Session,
    storage: S3Storage,
) -> None:
    owner = make_actor(db_session)
    recipient = make_actor(db_session)
    project = _project(api_client, owner)
    model = _asset(
        db_session,
        storage,
        owner,
        data=b"solid isolated\nendsolid isolated\n",
        extension="stl",
        mime="model/stl",
        format_="stl",
    )
    created = api_client.post(
        f"/api/v1/projects/{project['id']}/versions",
        json={"assets": {"model": str(model.id)}},
        headers=owner.headers,
    )
    assert created.status_code == 201
    transferred = api_client.post(
        f"/api/v1/projects/{project['id']}/transfer",
        json={"recipient_email": recipient.user.email, "confirmation_name": project["name"]},
        headers=owner.headers,
    )
    assert transferred.status_code == 200, transferred.text
    target_id = transferred.json()["target_project_id"]
    target_version_id = api_client.get(
        f"/api/v1/projects/{target_id}", headers=recipient.headers
    ).json()["head_version_id"]
    link = db_session.scalar(
        sa.select(VersionAsset).where(VersionAsset.version_id == uuid.UUID(target_version_id))
    )
    assert link is not None
    copied = db_session.get(Asset, link.asset_id)
    assert copied is not None and copied.workspace_id == recipient.workspace.id
    assert copied.storage_key != model.storage_key
