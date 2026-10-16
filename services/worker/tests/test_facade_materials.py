from pathlib import Path

import numpy as np
import pytest
import trimesh

from worker import geometry
from worker.facade_materials import (
    Assignment,
    FacadeMaterialRequest,
    Opening,
    apply_materials,
    classify_surfaces,
)


def _wall_with_window() -> trimesh.Trimesh:
    # Four solids form a front wall around a 1200 × 1400 opening at x=2000, sill=900.
    parts = [
        trimesh.creation.box(
            extents=(1400, 250, 3000),
            transform=trimesh.transformations.translation_matrix((700, 125, 1500)),
        ),
        trimesh.creation.box(
            extents=(1400, 250, 3000),
            transform=trimesh.transformations.translation_matrix((3300, 125, 1500)),
        ),
        trimesh.creation.box(
            extents=(1200, 250, 900),
            transform=trimesh.transformations.translation_matrix((2000, 125, 450)),
        ),
        trimesh.creation.box(
            extents=(1200, 250, 700),
            transform=trimesh.transformations.translation_matrix((2000, 125, 2650)),
        ),
    ]
    return trimesh.util.concatenate(parts)


def _request(assignments: list[Assignment] | None = None) -> FacadeMaterialRequest:
    return FacadeMaterialRequest(
        length_mm=4000,
        width_mm=3000,
        height_mm=3000,
        wall_thickness_mm=250,
        roof="none",
        openings=[
            Opening(
                opening_id="front-main",
                kind="window",
                side="front",
                center_mm=2000,
                width_mm=1200,
                height_mm=1400,
                sill_mm=900,
            )
        ],
        assignments=assignments or [],
    )


def test_semantic_keys_identify_wall_and_each_window_frame_role() -> None:
    keys = set(classify_surfaces(_wall_with_window(), _request()).tolist())
    assert "wall.front" in keys
    assert {
        "opening.front-main.left",
        "opening.front-main.right",
        "opening.front-main.head",
        "opening.front-main.sill",
    }.issubset(keys)


def test_unfilled_opening_has_the_same_four_reveal_roles_as_a_window() -> None:
    request = _request().model_copy(
        update={"openings": [_request().openings[0].model_copy(update={"kind": "opening"})]}
    )
    keys = set(classify_surfaces(_wall_with_window(), request).tolist())
    assert {
        "opening.front-main.left",
        "opening.front-main.right",
        "opening.front-main.head",
        "opening.front-main.sill",
    }.issubset(keys)


def test_material_preview_colours_semantic_surfaces_and_flags_missing(tmp_path: Path) -> None:
    source = tmp_path / "facade.stl"
    source.write_bytes(_wall_with_window().export(file_type="stl"))
    output = tmp_path / "facade.glb"
    request = _request(
        [
            Assignment(surface_key="wall.front", colour="#884422", material_id="pla"),
            Assignment(surface_key="opening.removed.left", colour="#112233"),
        ]
    )

    result = apply_materials(source, request, output)

    assert result.ok and result.assigned_faces > 0
    assert result.applied_surface_keys == ["wall.front"]
    assert result.unused_surface_keys == ["opening.removed.left"]
    assert output.read_bytes().startswith(b"glTF")
    loaded = trimesh.load(output, file_type="glb", force="scene")
    colours = np.vstack([geometry.visual.vertex_colors for geometry in loaded.geometry.values()])
    assert (colours[:, :3] == np.array([0x88, 0x44, 0x22])).all(axis=1).any()


def test_shed_roof_faces_have_one_stable_semantic_key() -> None:
    roof = trimesh.creation.box(extents=(4000, 3000, 100))
    transform = trimesh.transformations.rotation_matrix(np.arctan2(1200, 4000), [0, 1, 0])
    roof.apply_transform(transform)
    roof.apply_translation((2000, 1500, 3500))
    request = _request().model_copy(update={"roof": "shed", "openings": []})

    keys = classify_surfaces(roof, request)

    centres = np.asarray(roof.triangles_center)
    normals = np.asarray(roof.face_normals)
    upward_slope = (
        (normals[:, 2] > 1e-6)
        & (np.linalg.norm(normals[:, :2], axis=1) > 1e-6)
        & (centres[:, 2] >= 2997.5)
    )
    underside = (normals[:, 2] < -1e-6) & (centres[:, 2] >= 2997.5)
    assert upward_slope.any() and underside.any()
    assert set(keys[upward_slope].tolist()) == {"roof.slope"}
    assert "roof.slope" not in set(keys[underside].tolist())


def test_real_occt_fused_shed_roof_only_classifies_exterior_slope(tmp_path: Path) -> None:
    if not geometry.available():
        pytest.skip("geometry-service binary missing")
    plan = {
        "schema_version": 1,
        "goal": "fused shed-roof facade classification regression",
        "operations": [
            {
                "id": "house",
                "type": "create_box",
                "schema_version": 1,
                "width_mm": 10_000,
                "depth_mm": 8_000,
                "height_mm": 3_000,
            },
            {
                "id": "hollow_house",
                "type": "shell",
                "schema_version": 1,
                "target": "house",
                "thickness_mm": 250,
                "open_face": {"kind": "face_by_normal", "axis": "z", "sign": "+"},
            },
            {
                "id": "roof",
                "type": "extrude",
                "schema_version": 1,
                "profile": {
                    "kind": "polygon",
                    "points_mm": [[0, 0], [10_600, 0], [10_600, -1_200]],
                },
                "height_mm": 8_600,
                "origin_mm": [-300, -300, 3_000],
                "normal": [0, 1, 0],
                "x_direction": [1, 0, 0],
            },
            {
                "id": "join_roof",
                "type": "boolean",
                "schema_version": 1,
                "op": "fuse",
                "target": "house",
                "tool": "roof",
            },
        ],
        "expected_outputs": ["house"],
    }
    result = geometry.execute_plan(plan, tmp_path / "shed")
    assert result.ok, result.error
    (body,) = result.bodies
    assert body.valid and body.solids == 1 and body.stl is not None
    loaded = trimesh.load(tmp_path / "shed" / body.stl, file_type="stl", force="mesh")
    assert isinstance(loaded, trimesh.Trimesh)

    request = FacadeMaterialRequest(
        length_mm=10_000,
        width_mm=8_000,
        height_mm=3_000,
        wall_thickness_mm=250,
        roof="shed",
    )
    keys = classify_surfaces(loaded, request)
    normals = np.asarray(loaded.face_normals)
    actual_slope = (normals[:, 2] > 1e-6) & (np.linalg.norm(normals[:, :2], axis=1) > 1e-6)
    horizontal_underside = normals[:, 2] < -1 + 1e-6

    assert actual_slope.sum() == 2
    assert horizontal_underside.any()
    assert set(keys[actual_slope].tolist()) == {"roof.slope"}
    assert "roof.slope" not in set(keys[horizontal_underside].tolist())
