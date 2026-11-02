from pathlib import Path

import trimesh

from worker.assembly_inspection import ComponentInput, InspectionRequest, inspect


def _matrix(x: float) -> list[list[float]]:
    return [
        [1.0, 0.0, 0.0, x],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def test_world_envelopes_include_instances_and_only_report_positive_overlap(tmp_path: Path) -> None:
    mesh_path = tmp_path / "box.stl"
    trimesh.creation.box(extents=(10.0, 8.0, 6.0)).export(mesh_path)
    result = inspect(
        InspectionRequest(
            version_id="version",
            components=[
                ComponentInput(
                    node_id="source", path=str(mesh_path), format="stl", world_transform=_matrix(0)
                ),
                ComponentInput(
                    node_id="overlap", path=str(mesh_path), format="stl", world_transform=_matrix(7)
                ),
                ComponentInput(
                    node_id="touch", path=str(mesh_path), format="stl", world_transform=_matrix(17)
                ),
            ],
        )
    )
    assert result.ok is True
    assert result.scene_bbox_min_mm == [-5.0, -4.0, -3.0]
    assert result.scene_bbox_max_mm == [22.0, 4.0, 3.0]
    observed = [
        (item.node_a_id, item.node_b_id, item.overlap_mm) for item in result.envelope_overlaps
    ]
    assert observed == [("source", "overlap", [3.0, 8.0, 6.0])]
    assert result.collision_status == "checked"
    assert result.collision_unavailable_pairs == []
    assert [item.model_dump() for item in result.mesh_collisions] == [
        {
            "node_a_id": "source",
            "node_b_id": "overlap",
            "interference_mm3": 144.0,
            "bbox_min_mm": [2.0, -4.0, -3.0],
            "bbox_max_mm": [5.0, 4.0, 3.0],
        }
    ]


def test_broad_phase_overlap_without_mesh_intersection_is_not_a_collision(
    tmp_path: Path,
) -> None:
    box_path = tmp_path / "box.stl"
    ring_path = tmp_path / "ring.stl"
    trimesh.creation.box(extents=(4.0, 4.0, 4.0)).export(box_path)
    trimesh.creation.annulus(r_min=6.0, r_max=10.0, height=4.0).export(ring_path)
    result = inspect(
        InspectionRequest(
            version_id="version",
            components=[
                ComponentInput(
                    node_id="inside_hole",
                    path=str(box_path),
                    format="stl",
                    world_transform=_matrix(0),
                ),
                ComponentInput(
                    node_id="ring",
                    path=str(ring_path),
                    format="stl",
                    world_transform=_matrix(0),
                ),
            ],
        )
    )
    assert len(result.envelope_overlaps) == 1
    assert result.collision_status == "checked"
    assert result.mesh_collisions == []
    assert result.collision_unavailable_pairs == []


def test_non_watertight_candidate_makes_collision_result_unavailable(tmp_path: Path) -> None:
    solid_path = tmp_path / "solid.stl"
    open_path = tmp_path / "open.stl"
    solid = trimesh.creation.box(extents=(10.0, 8.0, 6.0))
    opened = solid.copy()
    opened.update_faces([index for index in range(len(opened.faces)) if index not in {0, 1}])
    solid.export(solid_path)
    opened.export(open_path)
    result = inspect(
        InspectionRequest(
            version_id="version",
            components=[
                ComponentInput(
                    node_id="solid",
                    path=str(solid_path),
                    format="stl",
                    world_transform=_matrix(0),
                ),
                ComponentInput(
                    node_id="open",
                    path=str(open_path),
                    format="stl",
                    world_transform=_matrix(0),
                ),
            ],
        )
    )
    assert result.collision_status == "unavailable"
    assert result.mesh_collisions == []
    assert [item.model_dump() for item in result.collision_unavailable_pairs] == [
        {"node_a_id": "solid", "node_b_id": "open", "reason": "non_watertight"}
    ]


def test_exact_collision_candidate_count_is_bounded(tmp_path: Path) -> None:
    mesh_path = tmp_path / "box.stl"
    trimesh.creation.box(extents=(10.0, 8.0, 6.0)).export(mesh_path)
    result = inspect(
        InspectionRequest(
            version_id="version",
            components=[
                ComponentInput(
                    node_id=f"part_{index}",
                    path=str(mesh_path),
                    format="stl",
                    world_transform=_matrix(0),
                )
                for index in range(17)
            ],
        )
    )
    assert len(result.envelope_overlaps) == 136
    assert result.collision_status == "unavailable"
    assert result.mesh_collisions == []
    assert len(result.collision_unavailable_pairs) == 136
    assert {item.reason for item in result.collision_unavailable_pairs} == {"candidate_limit"}
