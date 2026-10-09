from pathlib import Path

import numpy as np
import trimesh

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
