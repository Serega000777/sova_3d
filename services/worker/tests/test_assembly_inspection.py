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
    assert result.collision_status == "not_checked"
