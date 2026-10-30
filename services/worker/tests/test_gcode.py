"""Real slicing (F-054, second stage): perimeters, infill and G-code."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest
import shapely
import trimesh

from worker import gcode
from worker.gcode import FILAMENT_DIAMETER_MM, SliceSettings, slice_file_in_sandbox, slice_mesh
from worker.printcheck import PrinterProfile


def _filament_area_mm2() -> float:
    r = FILAMENT_DIAMETER_MM / 2
    return math.pi * r * r


def test_full_density_extrudes_the_mesh_volume() -> None:
    """At 100% infill the deposited volume must match the box, whatever wall_count is."""
    mesh = trimesh.creation.box(extents=(20, 20, 10))
    printer = PrinterProfile(layer_height_mm=0.2, nozzle_mm=0.4)
    for walls in (1, 3):
        _, stats = slice_mesh(
            mesh, printer, SliceSettings(infill_density_pct=100, wall_count=walls, skirt=False)
        )
        deposited_mm3 = stats.filament_used_mm * _filament_area_mm2()
        assert deposited_mm3 == pytest.approx(mesh.volume, rel=0.03)
    assert stats.total_layers == 50


def test_lower_density_uses_less_filament_than_full() -> None:
    mesh = trimesh.creation.box(extents=(20, 20, 10))
    printer = PrinterProfile(layer_height_mm=0.2, nozzle_mm=0.4)
    _, sparse = slice_mesh(mesh, printer, SliceSettings(infill_density_pct=10, skirt=False))
    _, dense = slice_mesh(mesh, printer, SliceSettings(infill_density_pct=100, skirt=False))
    assert 0 < sparse.filament_used_mm < dense.filament_used_mm


def test_more_walls_use_more_filament_at_zero_infill() -> None:
    mesh = trimesh.creation.box(extents=(20, 20, 10))
    printer = PrinterProfile(layer_height_mm=0.2, nozzle_mm=0.4)
    _, one_wall = slice_mesh(
        mesh, printer, SliceSettings(infill_density_pct=0, wall_count=1, skirt=False)
    )
    _, three_walls = slice_mesh(
        mesh, printer, SliceSettings(infill_density_pct=0, wall_count=3, skirt=False)
    )
    assert one_wall.filament_used_mm < three_walls.filament_used_mm


def test_a_ring_keeps_its_hole_open() -> None:
    outer = trimesh.creation.box(extents=(30, 30, 6))
    inner = trimesh.creation.cylinder(radius=8, height=20)
    ring = outer.difference(inner, engine="manifold")
    printer = PrinterProfile(layer_height_mm=0.3, nozzle_mm=0.4)
    text, stats = slice_mesh(ring, printer, SliceSettings(infill_density_pct=100, skirt=False))
    deposited_mm3 = stats.filament_used_mm * _filament_area_mm2()
    assert deposited_mm3 == pytest.approx(ring.volume, rel=0.05)
    # a solid box of the same footprint would need noticeably more filament
    solid_text, solid_stats = slice_mesh(
        outer, printer, SliceSettings(infill_density_pct=100, skirt=False)
    )
    assert stats.filament_used_mm < solid_stats.filament_used_mm


def test_gcode_is_well_formed() -> None:
    mesh = trimesh.creation.box(extents=(10, 10, 2))
    printer = PrinterProfile(layer_height_mm=0.2, nozzle_mm=0.4)
    text, stats = slice_mesh(mesh, printer, SliceSettings())
    lines = text.splitlines()
    assert lines[-1] == "M84"
    assert "M104 S0" in lines and "M140 S0" in lines
    assert any(line.startswith("M109") for line in lines)  # waits for nozzle temp
    assert any(line.startswith("M190") for line in lines)  # waits for bed temp
    assert "; TYPE:perimeter" in lines
    assert "; TYPE:solid-infill" in lines
    assert "; TYPE:infill" in lines
    body = text.split("G91", 1)[0]  # the footer's relative Z-lift comes after this
    z_values = [float(m.group(1)) for m in re.finditer(r"^G1 Z([\d.]+)", body, re.MULTILINE)]
    assert z_values == sorted(z_values)
    assert z_values[-1] == pytest.approx(stats.total_layers * printer.layer_height_mm)
    for match in re.finditer(r"E(-?[\d.]+)", text):
        # relative extrusion mode (M83): every E value is a finite, bounded move
        assert abs(float(match.group(1))) < 50


def test_adaptive_layer_plan_varies_with_surface_geometry_and_lands_on_the_top() -> None:
    mesh = trimesh.creation.icosphere(subdivisions=2, radius=5)
    printer = PrinterProfile(layer_height_mm=0.2, nozzle_mm=0.4)
    settings = SliceSettings(
        adaptive_layer_height=True,
        min_layer_height_mm=0.1,
        max_layer_height_mm=0.3,
    )

    layers = gcode._layer_plan(mesh, printer, settings)
    heights = [layer.height_mm for layer in layers]
    assert sum(heights) == pytest.approx(mesh.extents[2])
    assert min(heights) >= 0.1 - 1e-9
    assert max(heights) <= 0.3 + 1e-9
    assert len({round(height, 3) for height in heights}) >= 3
    assert layers[-1].machine_z == pytest.approx(mesh.bounds[1][2])


def test_adaptive_gcode_uses_each_real_layer_height_for_extrusion() -> None:
    mesh = trimesh.creation.box(extents=(20, 20, 4))
    printer = PrinterProfile(layer_height_mm=0.2, nozzle_mm=0.4)
    text, stats = slice_mesh(
        mesh,
        printer,
        SliceSettings(
            adaptive_layer_height=True,
            min_layer_height_mm=0.1,
            max_layer_height_mm=0.3,
            infill_density_pct=100,
            wall_count=2,
            skirt=False,
        ),
    )

    deposited_mm3 = stats.filament_used_mm * _filament_area_mm2()
    assert deposited_mm3 == pytest.approx(mesh.volume, rel=0.04)
    assert stats.layer_height_mode == "adaptive"
    assert stats.min_layer_height_mm >= 0.1
    assert stats.max_layer_height_mm <= 0.3
    assert stats.total_layers < math.ceil(mesh.extents[2] / printer.layer_height_mm)
    assert "layer_height=adaptive" in text
    assert f"G1 Z{mesh.extents[2]:.3f}" in text


def test_adaptive_layer_range_rejects_invalid_nozzle_height() -> None:
    mesh = trimesh.creation.box(extents=(10, 10, 2))
    with pytest.raises(ValueError, match="80%"):
        slice_mesh(
            mesh,
            PrinterProfile(layer_height_mm=0.2, nozzle_mm=0.4),
            SliceSettings(
                adaptive_layer_height=True,
                min_layer_height_mm=0.1,
                max_layer_height_mm=0.4,
            ),
        )


def test_adaptive_layers_spread_an_impossible_short_remainder_safely() -> None:
    mesh = trimesh.creation.box(extents=(10, 10, 0.31))
    layers = gcode._layer_plan(
        mesh,
        PrinterProfile(layer_height_mm=0.2, nozzle_mm=0.4),
        SliceSettings(
            adaptive_layer_height=True,
            min_layer_height_mm=0.2,
            max_layer_height_mm=0.3,
        ),
    )
    assert len(layers) == 2
    assert sum(layer.height_mm for layer in layers) == pytest.approx(0.31)
    assert max(layer.height_mm for layer in layers) <= 0.3
    assert min(layer.height_mm for layer in layers) == pytest.approx(0.155)


def test_rejects_non_fdm_and_non_watertight() -> None:
    mesh = trimesh.creation.box(extents=(10, 10, 2))
    with pytest.raises(ValueError, match="FDM"):
        slice_mesh(mesh, PrinterProfile(technology="resin"), SliceSettings())
    open_mesh = trimesh.creation.box(extents=(10, 10, 2))
    open_mesh.update_faces(open_mesh.face_normals[:, 0] < 0.5)
    with pytest.raises(ValueError, match="closed solid"):
        slice_mesh(open_mesh, PrinterProfile(), SliceSettings())


@pytest.mark.parametrize("speed", [0.0, -1.0, float("nan"), float("inf"), float("-inf")])
def test_rejects_non_positive_or_non_finite_print_speed(speed: float) -> None:
    mesh = trimesh.creation.box(extents=(10, 10, 2))
    with pytest.raises(ValueError, match="print speed must be finite and greater than zero"):
        slice_mesh(mesh, PrinterProfile(print_speed_mm_s=speed), SliceSettings())


def test_supports_add_material_under_a_real_overhang() -> None:
    # a T-bridge: a wide top slab on a narrow leg, so the slab's underside overhangs air
    leg = trimesh.creation.box(extents=(6, 6, 20))
    leg.apply_translation((0, 0, 10))
    slab = trimesh.creation.box(extents=(30, 30, 4))
    slab.apply_translation((0, 0, 22))
    bridge = trimesh.util.concatenate([leg, slab])
    assert isinstance(bridge, trimesh.Trimesh)
    bridge = trimesh.Trimesh(bridge.vertices, bridge.faces).process(validate=True)
    assert bridge.is_watertight
    printer = PrinterProfile(layer_height_mm=0.3, nozzle_mm=0.4, max_overhang_deg=45)
    _, without = slice_mesh(
        bridge, printer, SliceSettings(infill_density_pct=10, supports=False, skirt=False)
    )
    _, with_supports = slice_mesh(
        bridge, printer, SliceSettings(infill_density_pct=10, supports=True, skirt=False)
    )
    assert with_supports.support_columns > 0
    assert with_supports.filament_used_mm > without.filament_used_mm


def test_painted_blocker_removes_automatic_supports() -> None:
    printer = PrinterProfile(layer_height_mm=0.3, nozzle_mm=0.4, max_overhang_deg=45)
    _, automatic = slice_mesh(
        _t_bridge(),
        printer,
        SliceSettings(infill_density_pct=10, supports=True, skirt=False),
    )
    _, blocked = slice_mesh(
        _t_bridge(),
        printer,
        SliceSettings(
            infill_density_pct=10,
            supports=True,
            skirt=False,
            support_modifiers=[
                {
                    "mode": "block",
                    "region": {
                        "kind": "box",
                        "min_mm": (-100.0, -100.0, -1.0),
                        "max_mm": (100.0, 100.0, 30.0),
                    },
                }
            ],
        ),
    )
    assert automatic.support_columns > 0
    assert blocked.support_columns == 0
    assert blocked.support_modifiers == 1
    assert blocked.support_blocked_faces > 0
    assert blocked.support_enforced_faces == 0


def test_painted_enforcer_adds_support_below_a_gentle_downward_face() -> None:
    roof = trimesh.creation.box(extents=(24, 18, 2))
    angle = math.radians(60)
    roof.apply_transform(
        np.array(
            [
                [math.cos(angle), 0.0, math.sin(angle), 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [-math.sin(angle), 0.0, math.cos(angle), 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ]
        )
    )
    roof.apply_translation((0, 0, 15))
    printer = PrinterProfile(layer_height_mm=0.3, nozzle_mm=0.4, max_overhang_deg=45)
    common = SliceSettings(infill_density_pct=10, supports=True, skirt=False)
    _, automatic = slice_mesh(roof, printer, common)
    _, enforced = slice_mesh(
        roof,
        printer,
        common.model_copy(
            update={
                "support_modifiers": [
                    gcode.SupportModifier(
                        mode="enforce",
                        region={
                            "kind": "box",
                            "min_mm": (-100.0, -100.0, -100.0),
                            "max_mm": (100.0, 100.0, 100.0),
                        },
                    )
                ]
            }
        ),
    )
    assert automatic.support_columns == 0
    assert enforced.support_columns > 0
    assert enforced.support_enforced_faces > 0
    assert enforced.support_blocked_faces == 0


def test_painted_local_infill_density_changes_only_the_selected_sparse_region() -> None:
    printer = PrinterProfile(
        bed_x_mm=100,
        bed_y_mm=200,
        bed_z_mm=200,
        layer_height_mm=0.3,
        nozzle_mm=0.4,
    )
    part = trimesh.creation.box(extents=(150, 80, 6))
    plain_settings = SliceSettings(
        infill_density_pct=10,
        wall_count=1,
        top_solid_layers=0,
        bottom_solid_layers=0,
        skirt=False,
    )
    plain_text, plain = slice_mesh(part, printer, plain_settings)
    modified_text, modified = slice_mesh(
        part,
        printer,
        plain_settings.model_copy(
            update={
                "process_modifiers": [
                    gcode.ProcessModifier(
                        infill_density_pct=20,
                        print_speed_pct=50,
                        infill_pattern="honeycomb",
                        wall_count=3,
                        region={
                            "kind": "lasso",
                            "axis": "z",
                            "offset_mm": 3,
                            "depth_mm": 12,
                            "points_mm": [(-75, -40), (0, -40), (0, 40), (-75, 40)],
                        },
                    )
                ]
            }
        ),
    )
    assert plain.process_modifiers == 0
    assert "TYPE:local-infill" not in plain_text
    assert modified.process_modifiers == 1
    assert "tool_switching" not in modified_text
    assert modified.process_modified_layers == modified.total_layers
    assert modified.filament_used_mm > plain.filament_used_mm
    assert "turned 90 degrees to fit" in modified_text
    marker = "; TYPE:local-infill density=20% speed=50% pattern=honeycomb"
    assert marker in modified_text
    assert "; TYPE:local-perimeter walls=3" in modified_text
    local_section = modified_text.split(marker, 1)[1]
    assert re.search(r"^G1 X[-0-9.]+ Y[-0-9.]+ E[0-9.]+ F1800$", local_section, re.MULTILINE)
    following_perimeter = local_section.split("; TYPE:perimeter", 1)[1]
    assert re.search(r"^G1 X[-0-9.]+ Y[-0-9.]+ E[0-9.]+ F3600$", following_perimeter, re.MULTILINE)

    with pytest.raises(ValueError, match="horizontal face"):
        SliceSettings(
            process_modifiers=[
                {
                    "infill_density_pct": 50,
                    "region": {
                        "kind": "lasso",
                        "axis": "x",
                        "offset_mm": 20,
                        "depth_mm": 40,
                        "points_mm": [(-20, -3), (20, -3), (20, 3), (-20, 3)],
                    },
                }
            ]
        )


def test_material_slot_assignment_is_reported_without_emitting_tool_changes() -> None:
    text, stats = slice_mesh(
        trimesh.creation.box(extents=(20, 20, 1.2)),
        PrinterProfile(layer_height_mm=0.3, nozzle_mm=0.4),
        SliceSettings(
            infill_density_pct=20,
            skirt=False,
            tool_change_mode="marlin_tn",
            tool_count=2,
            base_tool=0,
            purge_tower_enabled=True,
            purge_tower_width_mm=24,
            purge_volume_mm3=75,
            process_modifiers=[
                {
                    "infill_density_pct": 30,
                    "material_slot": 1,
                    "material_id": "petg",
                    "region": {
                        "kind": "box",
                        "min_mm": [-10, -10, -1],
                        "max_mm": [0, 10, 2],
                    },
                }
            ],
        ),
    )
    assert stats.material_assigned_regions == 1
    assert stats.planned_tool_change_layers == 4
    assert stats.planned_tool_changes == 8
    assert stats.planned_purge_volume_mm3 == 600
    assert stats.purge_tower_reserved is True
    assert stats.purge_tower_x_mm == 230
    assert stats.purge_tower_y_mm == 230
    assert stats.purge_tower_width_mm == 24
    assert (
        "material_assignments=1 tool_change_mode=marlin_tn tool_count=2 base_tool=T0 "
        "purge_tower=planned purge_tower_width=24mm purge_per_change=75mm3 "
        "tool_switching=disabled" in text
    )
    assert (
        "; purge-plan: layers=4 changes=8 tower=reserved x=230 y=230 "
        "width=24mm paths=disabled" in text
    )
    path_batches = re.findall(
        r"^; material-path-batch: layer=(\d+) tool=(T\d) "
        r"groups=([^\n]+) switching=disabled$",
        text,
        re.MULTILINE,
    )
    assert [(layer, tool) for layer, tool, _ in path_batches] == [
        (str(layer), tool) for layer in range(1, 5) for tool in ("T0", "T1")
    ]
    assert all(
        "perimeter:" in groups and "solid-infill:" in groups for _, _, groups in path_batches
    )
    assert "; material-path-plan:" not in text
    assert re.search(r"^T\d+$", text, re.MULTILINE) is None
    assert "TYPE:purge-tower" not in text

    with pytest.raises(ValueError, match="must be provided together"):
        gcode.ProcessModifier(
            infill_density_pct=30,
            material_slot=1,
            region={"kind": "box", "min_mm": [0, 0, 0], "max_mm": [1, 1, 1]},
        )

    with pytest.raises(ValueError, match="exceeds the configured tool count"):
        SliceSettings(
            tool_change_mode="marlin_tn",
            tool_count=2,
            process_modifiers=[
                {
                    "infill_density_pct": 30,
                    "material_slot": 2,
                    "material_id": "petg",
                    "region": {
                        "kind": "box",
                        "min_mm": [0, 0, 0],
                        "max_mm": [1, 1, 1],
                    },
                }
            ],
        )

    with pytest.raises(ValueError, match="base tool exceeds"):
        SliceSettings(tool_change_mode="marlin_tn", tool_count=2, base_tool=2)

    with pytest.raises(ValueError, match="purge tower requires"):
        SliceSettings(purge_tower_enabled=True)


def test_material_batch_travel_and_retractions_increase_estimated_time() -> None:
    mesh = trimesh.creation.box(extents=(20, 20, 1.2))
    printer = PrinterProfile(layer_height_mm=0.3, nozzle_mm=0.4)
    region = {
        "kind": "box",
        "min_mm": [-10, -10, -1],
        "max_mm": [0, 10, 2],
    }
    common = {
        "infill_density_pct": 20,
        "skirt": False,
        "tool_change_mode": "marlin_tn",
        "tool_count": 2,
        "base_tool": 0,
    }
    plain_text, plain_stats = slice_mesh(
        mesh,
        printer,
        SliceSettings(
            **common,
            process_modifiers=[{"infill_density_pct": 20, "region": region}],
        ),
    )
    batched_text, batched_stats = slice_mesh(
        mesh,
        printer,
        SliceSettings(
            **common,
            process_modifiers=[
                {
                    "infill_density_pct": 20,
                    "material_slot": 1,
                    "material_id": "petg",
                    "region": region,
                }
            ],
        ),
    )

    retract_pattern = re.compile(r"^G1 E-[0-9.]+ F[0-9]+$", re.MULTILINE)
    assert batched_stats.filament_used_mm == plain_stats.filament_used_mm
    assert batched_stats.travel_mm > plain_stats.travel_mm
    assert len(retract_pattern.findall(batched_text)) > len(retract_pattern.findall(plain_text))
    assert batched_stats.estimated_time_s > plain_stats.estimated_time_s


def test_purge_tower_reservation_fails_before_writer_emission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_writer_is_created(*args: object, **kwargs: object) -> None:
        pytest.fail("G-code writer was created before purge reservation preflight")

    monkeypatch.setattr(gcode, "_Writer", fail_if_writer_is_created)
    with pytest.raises(ValueError, match="no collision-free bed position"):
        slice_mesh(
            trimesh.creation.box(extents=(30, 30, 0.6)),
            PrinterProfile(bed_x_mm=40, bed_y_mm=40, bed_z_mm=40, layer_height_mm=0.3),
            SliceSettings(
                infill_density_pct=20,
                skirt=False,
                tool_change_mode="marlin_tn",
                tool_count=2,
                base_tool=0,
                purge_tower_enabled=True,
                purge_tower_width_mm=10,
                purge_volume_mm3=10,
                process_modifiers=[
                    {
                        "infill_density_pct": 30,
                        "material_slot": 1,
                        "material_id": "petg",
                        "region": {
                            "kind": "box",
                            "min_mm": [-15, -15, -1],
                            "max_mm": [0, 15, 1],
                        },
                    }
                ],
            ),
        )


def test_purge_plan_rejects_capacity_before_writer_emission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_writer_is_created(*args: object, **kwargs: object) -> None:
        pytest.fail("G-code writer was created before purge capacity preflight")

    monkeypatch.setattr(gcode, "_Writer", fail_if_writer_is_created)
    with pytest.raises(ValueError, match="exceeds the tower capacity"):
        slice_mesh(
            trimesh.creation.box(extents=(10, 10, 0.6)),
            PrinterProfile(layer_height_mm=0.3),
            SliceSettings(
                infill_density_pct=20,
                skirt=False,
                tool_change_mode="marlin_tn",
                tool_count=2,
                base_tool=0,
                purge_tower_enabled=True,
                purge_tower_width_mm=10,
                # Two transitions need exactly 30 mm3: the old width²h estimate
                # accepted it, while the generated inset centerline holds 29.952 mm3.
                purge_volume_mm3=15,
                process_modifiers=[
                    {
                        "infill_density_pct": 30,
                        "material_slot": 1,
                        "material_id": "petg",
                        "region": {
                            "kind": "box",
                            "min_mm": [-5, -5, -1],
                            "max_mm": [0, 5, 1],
                        },
                    }
                ],
            ),
        )


def test_exact_purge_masks_choose_an_alternate_corner_for_support_beads() -> None:
    printer = PrinterProfile(bed_x_mm=40, bed_y_mm=40, bed_z_mm=40)
    candidates = gcode._purge_tower_candidates(printer, 10)
    assert [candidate.bounds[:2] for candidate in candidates] == [
        (28.0, 28.0),
        (2.0, 28.0),
        (28.0, 2.0),
        (2.0, 2.0),
    ]
    support = gcode.MaterialPathBatch(
        tool=0,
        kind="support",
        comment="TYPE:support",
        paths=([(25.0, 30.0), (25.0, 35.0)],),
        line_width_mm=1.6,
        nearest_first=True,
    )

    blocked = gcode._blocked_purge_path_mask(candidates, (support,))

    assert blocked == 0b0001
    assert gcode._reserve_purge_tower(candidates, blocked).bounds[:2] == (2.0, 28.0)


def test_exact_purge_masks_reject_all_blocked_candidates() -> None:
    candidates = gcode._purge_tower_candidates(
        PrinterProfile(bed_x_mm=40, bed_y_mm=40, bed_z_mm=40), 10
    )
    blockers = gcode.MaterialPathBatch(
        tool=0,
        kind="support",
        comment="TYPE:support",
        paths=tuple(
            [
                (candidate.centroid.x - 1, candidate.centroid.y),
                (candidate.centroid.x + 1, candidate.centroid.y),
            ]
            for candidate in candidates
        ),
        line_width_mm=1.6,
        nearest_first=True,
    )

    blocked = gcode._blocked_purge_path_mask(candidates, (blockers,))

    assert blocked == 0b1111
    with pytest.raises(ValueError, match="no collision-free bed position"):
        gcode._reserve_purge_tower(candidates, blocked)


def test_exact_purge_collision_preserves_hollow_and_sparse_free_space() -> None:
    candidate = shapely.box(10, 10, 20, 20)
    hollow = shapely.box(0, 0, 30, 30).difference(shapely.box(5, 5, 25, 25))
    sparse = gcode.MaterialPathBatch(
        tool=0,
        kind="infill",
        comment="TYPE:infill",
        paths=([(0.0, 0.0), (0.0, 30.0)],),
        line_width_mm=0.4,
        nearest_first=True,
    )

    assert gcode._blocked_purge_candidate_mask((candidate,), hollow, 3.0) == 0
    assert gcode._blocked_purge_path_mask((candidate,), (sparse,)) == 0


def test_immutable_adhesion_paths_are_used_for_exact_collision() -> None:
    candidate = shapely.box(10, 10, 20, 20)
    plan = gcode.AdhesionPathPlan(brim=(((7.0, 15.0), (7.0, 18.0)),))

    assert gcode._adhesion_blocked_purge_mask((candidate,), plan, 0.4) == 1


def test_purge_tower_centerline_is_inset_and_alternates_by_layer() -> None:
    tower = shapely.box(10, 20, 20, 30)
    even = gcode._purge_tower_centerline(tower, 0.4, 0)
    odd = gcode._purge_tower_centerline(tower, 0.4, 1)

    assert even.bounds == pytest.approx((10.2, 20.2, 19.8, 29.8))
    assert odd.bounds == pytest.approx((10.2, 20.2, 19.8, 29.8))
    assert np.asarray(even.coords[0:2]) == pytest.approx(np.asarray(((10.2, 20.2), (19.8, 20.2))))
    assert np.asarray(odd.coords[0:2]) == pytest.approx(np.asarray(((10.2, 20.2), (10.2, 29.8))))
    assert even.length == pytest.approx(odd.length)


def test_purge_tower_capacity_and_segments_follow_generated_line_geometry() -> None:
    centerline = gcode._purge_tower_centerline(shapely.box(0, 0, 10, 10), 0.4, 0)
    capacity = gcode._purge_tower_capacity_mm3(centerline, 0.3, 0.4)
    segments = gcode._purge_tower_segments(centerline, 0.3, 0.4, [10, 12.5])

    assert centerline.length == pytest.approx(249.6)
    assert capacity == pytest.approx(29.952)
    assert [segment.length for segment in segments.purge] == pytest.approx(
        [10 / (0.3 * 0.4), 12.5 / (0.3 * 0.4)]
    )
    assert segments.structural.length + sum(segment.length for segment in segments.purge) == (
        pytest.approx(centerline.length)
    )
    assert [segment.length * 0.3 * 0.4 for segment in segments.purge] == pytest.approx([10, 12.5])


def test_purge_tower_geometry_handles_degenerate_and_multiple_transitions() -> None:
    empty = gcode._purge_tower_centerline(shapely.box(0, 0, 0.2, 0.2), 0.4, 0)
    assert empty.is_empty
    assert gcode._purge_tower_capacity_mm3(empty, 0.2, 0.4) == 0
    zero = gcode._purge_tower_segments(empty, 0.2, 0.4, [0, 0])
    assert zero.structural.is_empty
    assert all(segment.is_empty for segment in zero.purge)
    with pytest.raises(ValueError, match="exceeds the tower capacity"):
        gcode._purge_tower_segments(empty, 0.2, 0.4, [0.001])

    centerline = gcode._purge_tower_centerline(shapely.box(0, 0, 10, 10), 0.4, 3)
    adaptive = gcode._purge_tower_segments(centerline, 0.17, 0.4, [4, 5, 6])
    assert len(adaptive.purge) == 3
    assert [segment.length * 0.17 * 0.4 for segment in adaptive.purge] == pytest.approx([4, 5, 6])


def test_purge_capacity_uses_centerline_not_square_area() -> None:
    centerline = gcode._purge_tower_centerline(shapely.box(0, 0, 10, 10), 0.4, 0)
    assert 29.95 < gcode._purge_tower_capacity_mm3(centerline, 0.3, 0.4) < 30
    with pytest.raises(ValueError, match="exceeds the tower capacity"):
        gcode._purge_tower_segments(centerline, 0.3, 0.4, [15, 15])


def test_material_preflight_precedes_writer_and_output_is_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, int]] = []
    original_bind = gcode._bind_purge_plan_to_paths

    def tracked_bind(
        candidate: gcode.PurgePlan,
        layer_counts: list[gcode.MaterialPathCounts],
        base_tool: int,
        preferred_tools: tuple[int, ...],
    ) -> gcode.PurgePlan:
        assert len(layer_counts) == 2
        assert all(counts for counts in layer_counts)
        events.append(("bind", len(layer_counts)))
        return original_bind(candidate, layer_counts, base_tool, preferred_tools)

    class TrackedWriter(gcode._Writer):
        def __init__(
            self,
            printer: PrinterProfile,
            retraction_mm: float,
            retraction_speed_mm_s: float,
            active_tool: int,
            flow: float = 1.0,
        ) -> None:
            events.append(("writer", 0))
            super().__init__(printer, retraction_mm, retraction_speed_mm_s, active_tool, flow)

    monkeypatch.setattr(gcode, "_bind_purge_plan_to_paths", tracked_bind)
    monkeypatch.setattr(gcode, "_Writer", TrackedWriter)
    mesh = trimesh.creation.box(extents=(10, 10, 0.6))
    printer = PrinterProfile(layer_height_mm=0.3)
    settings = SliceSettings(
        infill_density_pct=20,
        skirt=False,
        tool_change_mode="marlin_tn",
        tool_count=2,
        base_tool=0,
        purge_tower_enabled=True,
        purge_tower_width_mm=20,
        purge_volume_mm3=10,
        process_modifiers=[
            {
                "infill_density_pct": 30,
                "material_slot": 1,
                "material_id": "petg",
                "region": {
                    "kind": "box",
                    "min_mm": [-5, -5, -1],
                    "max_mm": [0, 5, 1],
                },
            }
        ],
    )

    first = slice_mesh(mesh, printer, settings)
    second = slice_mesh(mesh, printer, settings)

    assert events == [("bind", 2), ("writer", 0), ("bind", 2), ("writer", 0)]
    assert first == second
    assert re.search(r"^T\d+$", first[0], re.MULTILINE) is None
    assert "TYPE:purge-tower" not in first[0]


def test_material_preflight_verifies_regenerated_collision_mask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_mask = gcode._blocked_purge_path_mask
    calls = 0

    def diverging_mask(
        candidates: Sequence[shapely.Polygon],
        batches: Sequence[gcode.MaterialPathBatch],
    ) -> int:
        nonlocal calls
        calls += 1
        exact = original_mask(candidates, batches)
        return exact if calls <= 2 else exact ^ 1

    monkeypatch.setattr(gcode, "_blocked_purge_path_mask", diverging_mask)
    with pytest.raises(RuntimeError, match="regeneration diverged"):
        slice_mesh(
            trimesh.creation.box(extents=(10, 10, 0.6)),
            PrinterProfile(layer_height_mm=0.3),
            SliceSettings(
                infill_density_pct=20,
                skirt=False,
                tool_change_mode="marlin_tn",
                tool_count=2,
                purge_tower_enabled=True,
                purge_volume_mm3=10,
                process_modifiers=[
                    {
                        "infill_density_pct": 30,
                        "material_slot": 1,
                        "material_id": "petg",
                        "region": {
                            "kind": "box",
                            "min_mm": [-5, -5, -1],
                            "max_mm": [0, 5, 1],
                        },
                    }
                ],
            ),
        )


def test_material_preflight_skips_collision_masks_when_purge_tower_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def tracked_mask(
        candidates: Sequence[shapely.Polygon],
        batches: Sequence[gcode.MaterialPathBatch],
    ) -> int:
        nonlocal calls
        calls += 1
        return 0

    monkeypatch.setattr(gcode, "_blocked_purge_path_mask", tracked_mask)
    _, stats = slice_mesh(
        trimesh.creation.box(extents=(10, 10, 0.6)),
        PrinterProfile(layer_height_mm=0.3),
        SliceSettings(
            infill_density_pct=20,
            skirt=False,
            tool_change_mode="marlin_tn",
            tool_count=2,
            purge_tower_enabled=False,
            process_modifiers=[
                {
                    "infill_density_pct": 30,
                    "material_slot": 1,
                    "material_id": "petg",
                    "region": {
                        "kind": "box",
                        "min_mm": [-5, -5, -1],
                        "max_mm": [0, 5, 1],
                    },
                }
            ],
        ),
    )

    assert stats.planned_tool_changes > 0
    assert calls == 0


def test_purge_raft_preflight_allows_no_exact_change_and_rejects_real_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mesh = trimesh.creation.box(extents=(10, 10, 0.6))
    printer = PrinterProfile(layer_height_mm=0.3)
    common: dict[str, object] = {
        "infill_density_pct": 0,
        "wall_count": 1,
        "top_solid_layers": 0,
        "bottom_solid_layers": 0,
        "adhesion_mode": "raft",
        "tool_change_mode": "marlin_tn",
        "tool_count": 2,
        "purge_tower_enabled": True,
        "process_modifiers": [
            {
                "infill_density_pct": 0,
                "material_slot": 1,
                "material_id": "petg",
                "region": {
                    "kind": "box",
                    "min_mm": [-1, -1, -1],
                    "max_mm": [1, 1, 1],
                },
            }
        ],
    }
    text, stats = slice_mesh(mesh, printer, SliceSettings(**common))
    assert stats.planned_tool_changes == 0
    assert stats.purge_tower_reserved is False
    assert "TYPE:raft-base" in text

    def fail_if_writer_is_created(*args: object, **kwargs: object) -> None:
        pytest.fail("G-code writer was created before raft/purge rejection")

    monkeypatch.setattr(gcode, "_Writer", fail_if_writer_is_created)
    common.update(
        infill_density_pct=20,
        top_solid_layers=1,
        bottom_solid_layers=1,
        process_modifiers=[
            {
                "infill_density_pct": 30,
                "material_slot": 1,
                "material_id": "petg",
                "region": {
                    "kind": "box",
                    "min_mm": [-5, -5, -1],
                    "max_mm": [0, 5, 1],
                },
            }
        ],
    )
    with pytest.raises(ValueError, match="purge tower with raft adhesion is not supported"):
        slice_mesh(mesh, printer, SliceSettings(**common))


def test_material_preflight_plans_remain_summary_only_across_many_layers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_plan = gcode.LayerMaterialPlan
    captured_plans: list[gcode.LayerMaterialPlan] = []

    def tracked_plan(
        *,
        counts: gcode.MaterialPathCounts,
        tool_order: tuple[int, ...],
        blocked_candidate_mask: int = 0,
    ) -> gcode.LayerMaterialPlan:
        plan = original_plan(
            counts=counts,
            tool_order=tool_order,
            blocked_candidate_mask=blocked_candidate_mask,
        )
        captured_plans.append(plan)
        return plan

    monkeypatch.setattr(gcode, "LayerMaterialPlan", tracked_plan)
    text, stats = slice_mesh(
        trimesh.creation.box(extents=(10, 10, 12)),
        PrinterProfile(layer_height_mm=0.3),
        SliceSettings(
            infill_density_pct=20,
            skirt=False,
            tool_change_mode="marlin_tn",
            tool_count=2,
            process_modifiers=[
                {
                    "infill_density_pct": 20,
                    "material_slot": 1,
                    "material_id": "petg",
                    "region": {
                        "kind": "box",
                        "min_mm": [-5, -5, -1],
                        "max_mm": [0, 5, 13],
                    },
                }
            ],
        ),
    )

    assert stats.total_layers == 40
    assert len(captured_plans) == stats.total_layers
    assert all(not hasattr(plan, "batches") for plan in captured_plans)
    assert re.search(r"^T\d+$", text, re.MULTILINE) is None
    assert "TYPE:purge-tower" not in text


def test_plain_paths_build_once_material_paths_twice_with_identical_fast_path_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_tool_areas = gcode._material_tool_areas
    original_preflight = gcode._requires_material_preflight
    build_calls = 0

    def tracked_tool_areas(
        modifiers: Sequence[gcode.ProcessModifier],
        placement_transform: np.ndarray,
        sample_z: float,
    ) -> gcode.MaterialToolAreas:
        nonlocal build_calls
        build_calls += 1
        return original_tool_areas(modifiers, placement_transform, sample_z)

    def force_preflight(preferred_tools: Sequence[int], base_tool: int) -> bool:
        return True

    monkeypatch.setattr(gcode, "_material_tool_areas", tracked_tool_areas)
    mesh = trimesh.creation.box(extents=(10, 10, 0.6))
    printer = PrinterProfile(layer_height_mm=0.3)
    plain_settings = SliceSettings(infill_density_pct=20, skirt=False)

    plain_fast = slice_mesh(mesh, printer, plain_settings)
    assert build_calls == 2

    build_calls = 0
    monkeypatch.setattr(gcode, "_requires_material_preflight", force_preflight)
    plain_forced_two_pass = slice_mesh(mesh, printer, plain_settings)
    assert build_calls == 4
    assert plain_fast == plain_forced_two_pass

    build_calls = 0
    monkeypatch.setattr(gcode, "_requires_material_preflight", original_preflight)
    slice_mesh(
        mesh,
        printer,
        SliceSettings(
            infill_density_pct=20,
            skirt=False,
            tool_change_mode="marlin_tn",
            tool_count=2,
            process_modifiers=[
                {
                    "infill_density_pct": 20,
                    "material_slot": 1,
                    "material_id": "petg",
                    "region": {
                        "kind": "box",
                        "min_mm": [-5, -5, -1],
                        "max_mm": [0, 5, 1],
                    },
                }
            ],
        ),
    )
    assert build_calls == 4


def test_purge_plan_uses_last_painted_material_for_overlapping_regions() -> None:
    text, stats = slice_mesh(
        trimesh.creation.box(extents=(10, 10, 0.6)),
        PrinterProfile(layer_height_mm=0.3),
        SliceSettings(
            infill_density_pct=20,
            skirt=False,
            tool_change_mode="marlin_tn",
            tool_count=2,
            base_tool=0,
            purge_tower_enabled=True,
            process_modifiers=[
                {
                    "infill_density_pct": 30,
                    "material_slot": tool,
                    "material_id": material,
                    "region": {
                        "kind": "box",
                        "min_mm": [-5, -5, -1],
                        "max_mm": [5, 5, 1],
                    },
                }
                for tool, material in ((1, "petg"), (0, "pla"))
            ],
        ),
    )
    assert stats.planned_tool_changes == 0
    assert stats.purge_tower_reserved is False
    assert "; purge-plan:" not in text


def test_purge_plan_drops_painted_areas_without_real_path_pieces() -> None:
    text, stats = slice_mesh(
        trimesh.creation.box(extents=(20, 20, 0.3)),
        PrinterProfile(layer_height_mm=0.3),
        SliceSettings(
            infill_density_pct=0,
            wall_count=1,
            top_solid_layers=0,
            bottom_solid_layers=0,
            skirt=False,
            tool_change_mode="marlin_tn",
            tool_count=2,
            base_tool=0,
            purge_tower_enabled=True,
            process_modifiers=[
                {
                    "infill_density_pct": 0,
                    "material_slot": 1,
                    "material_id": "petg",
                    "region": {
                        "kind": "box",
                        "min_mm": [-1, -1, -1],
                        "max_mm": [1, 1, 1],
                    },
                }
            ],
        ),
    )
    assert stats.planned_tool_changes == 0
    assert stats.planned_purge_volume_mm3 == 0
    assert stats.purge_tower_reserved is False
    assert "; material-path-plan:" not in text
    assert "; purge-plan:" not in text


def test_material_path_counts_split_real_support_style_paths_last_painted_wins() -> None:
    paths = [[(-5.0, 0.0), (5.0, 0.0)]]
    modifiers = [
        gcode.ProcessModifier(
            infill_density_pct=20,
            material_slot=1,
            material_id="petg",
            region={"kind": "box", "min_mm": [-2, -1, -1], "max_mm": [2, 1, 1]},
        ),
        gcode.ProcessModifier(
            infill_density_pct=20,
            material_slot=2,
            material_id="abs",
            region={"kind": "box", "min_mm": [0, -1, -1], "max_mm": [3, 1, 1]},
        ),
    ]
    counts = gcode._material_path_counts(paths, modifiers, np.eye(4), 0.0, 0)
    assert counts == {0: 2, 1: 1, 2: 1}

    pieces = gcode._material_path_pieces(paths, modifiers, np.eye(4), 0.0, 0)
    assert pieces == {
        0: [[(-5.0, 0.0), (-2.0, 0.0)], [(3.0, 0.0), (5.0, 0.0)]],
        1: [[(-2.0, 0.0), (0.0, 0.0)]],
        2: [[(0.0, 0.0), (3.0, 0.0)]],
    }


def test_real_model_and_support_paths_are_emitted_in_tool_batches() -> None:
    text, _ = slice_mesh(
        _t_bridge(),
        PrinterProfile(layer_height_mm=0.3, nozzle_mm=0.4, max_overhang_deg=45),
        SliceSettings(
            infill_density_pct=10,
            supports=True,
            support_type="grid",
            skirt=False,
            tool_change_mode="marlin_tn",
            tool_count=2,
            base_tool=0,
            process_modifiers=[
                {
                    "infill_density_pct": 10,
                    "material_slot": 1,
                    "material_id": "petg",
                    "region": {
                        "kind": "box",
                        "min_mm": [-100, -100, -100],
                        "max_mm": [0, 100, 100],
                    },
                }
            ],
        ),
    )
    first_layer_batches = re.findall(
        r"^; material-path-batch: layer=1 tool=(T\d) groups=([^\n]+) switching=disabled$",
        text,
        re.MULTILINE,
    )
    assert [tool for tool, _ in first_layer_batches] == ["T0", "T1"]
    assert all("perimeter:" in groups and "support:" in groups for _, groups in first_layer_batches)
    assert re.search(r"^T\d+$", text, re.MULTILINE) is None


def test_local_wall_count_clips_extra_perimeters_to_the_painted_region() -> None:
    polygon = shapely.box(0, 0, 20, 10)
    modifier = gcode.ProcessModifier(
        infill_density_pct=20,
        wall_count=4,
        region={"kind": "box", "min_mm": [0, 0, -1], "max_mm": [10, 10, 1]},
    )
    base, local, infill = gcode._locally_modified_perimeters(
        polygon, 0.4, 1, [modifier], np.eye(4), 0
    )
    assert base
    assert len(local) == 1 and len(local[0][0]) > len(base)
    assert all(max(x for x, _ in path) <= 10.0001 for path in local[0][0])
    assert all(part.is_valid for part in infill)


def test_local_speed_changes_perimeters_and_solid_skin_only_inside_the_region() -> None:
    printer = PrinterProfile(layer_height_mm=0.3, nozzle_mm=0.4)
    part = trimesh.creation.box(extents=(20, 20, 1.2))
    text, _ = slice_mesh(
        part,
        printer,
        SliceSettings(
            infill_density_pct=0,
            wall_count=2,
            top_solid_layers=10,
            bottom_solid_layers=10,
            skirt=False,
            process_modifiers=[
                {
                    "infill_density_pct": 0,
                    "print_speed_pct": 50,
                    "region": {
                        "kind": "box",
                        "min_mm": [-10, -10, -1],
                        "max_mm": [0, 10, 2],
                    },
                }
            ],
        ),
    )
    assert "; TYPE:local-perimeter walls=2 speed=50%" in text
    assert "; TYPE:local-solid-infill speed=50%" in text
    local_perimeter = text.split("; TYPE:local-perimeter walls=2 speed=50%", 1)[1]
    assert re.search(r"^G1 X[-0-9.]+ Y[-0-9.]+ E[0-9.]+ F1800$", local_perimeter, re.MULTILINE)
    local_skin = text.split("; TYPE:local-solid-infill speed=50%", 1)[1]
    assert re.search(r"^G1 X[-0-9.]+ Y[-0-9.]+ E[0-9.]+ F1800$", local_skin, re.MULTILINE)


@pytest.mark.parametrize("support_type", ["grid", "tree"])
def test_local_speed_changes_real_support_paths(support_type: str) -> None:
    printer = PrinterProfile(layer_height_mm=0.3, nozzle_mm=0.4, max_overhang_deg=45)
    text, _ = slice_mesh(
        _t_bridge(),
        printer,
        SliceSettings(
            infill_density_pct=10,
            supports=True,
            support_type=support_type,
            skirt=False,
            process_modifiers=[
                {
                    "infill_density_pct": 10,
                    "print_speed_pct": 50,
                    "region": {
                        "kind": "box",
                        "min_mm": [-100, -100, -100],
                        "max_mm": [100, 100, 100],
                    },
                }
            ],
        ),
    )
    marker = "; TYPE:local-support speed=50%"
    assert marker in text
    local_support = text.split(marker, 1)[1]
    assert re.search(r"^G1 X[-0-9.]+ Y[-0-9.]+ E[0-9.]+ F1800$", local_support, re.MULTILINE)


def test_local_temperature_changes_and_restores_the_real_nozzle_target() -> None:
    printer = PrinterProfile(layer_height_mm=0.3, nozzle_mm=0.4)
    text, _ = slice_mesh(
        trimesh.creation.box(extents=(20, 20, 0.6)),
        printer,
        SliceSettings(
            infill_density_pct=100,
            skirt=False,
            process_modifiers=[
                {
                    "infill_density_pct": 100,
                    "nozzle_temperature_offset_c": 15,
                    "region": {
                        "kind": "box",
                        "min_mm": [-10, -10, -1],
                        "max_mm": [0, 10, 1],
                    },
                }
            ],
        ),
    )
    marker = "; TYPE:local-solid-infill speed=100% temperature_offset=+15C"
    assert marker in text
    local_section = text.split(marker, 1)[1]
    hot = local_section.index("M104 S215")
    extrusion = re.search(r"^G1 X[-0-9.]+ Y[-0-9.]+ E[0-9.]+", local_section, re.MULTILINE)
    restored = local_section.index("M104 S200")
    assert extrusion is not None and hot < extrusion.start() < restored


def test_tree_supports_use_less_material_than_grid_for_the_same_overhang() -> None:
    printer = PrinterProfile(layer_height_mm=0.3, nozzle_mm=0.4, max_overhang_deg=45)
    common = SliceSettings(infill_density_pct=10, supports=True, skirt=False)
    _, grid = slice_mesh(_t_bridge(), printer, common)
    _, tree = slice_mesh(_t_bridge(), printer, common.model_copy(update={"support_type": "tree"}))
    assert tree.support_type == "tree"
    assert 0 < tree.support_trunks < tree.support_columns
    assert tree.support_branches >= tree.support_trunks
    assert tree.filament_used_mm < grid.filament_used_mm


def _branch_reaches(
    branches: list[gcode.SupportBranch], point: tuple[float, float, float], floor: float
) -> bool:
    """Follow a branch junction down through any vertical trunk that contains it."""
    x, y, z = point
    for branch in branches:
        if (
            branch.lower_x == pytest.approx(x)
            and branch.lower_y == pytest.approx(y)
            and branch.lower_z - 1e-6 <= z <= branch.upper_z + 1e-6
            and branch.upper_x == pytest.approx(x)
            and branch.upper_y == pytest.approx(y)
        ):
            return branch.lower_z == pytest.approx(floor)
    return False


def test_tree_branches_connect_every_contact_to_the_supporting_surface() -> None:
    printer = PrinterProfile(layer_height_mm=0.3, nozzle_mm=0.4, max_overhang_deg=45)
    base = trimesh.creation.box(extents=(40, 40, 4))
    base.apply_translation((0, 0, 2))
    pillar = trimesh.creation.box(extents=(6, 6, 12))
    pillar.apply_translation((0, 0, 10))
    roof = trimesh.creation.box(extents=(40, 40, 3))
    roof.apply_translation((0, 0, 17.5))
    on_part = trimesh.boolean.union([base, pillar, roof], engine="manifold")
    supports = gcode._tree_supports(on_part, printer)
    gap = printer.layer_height_mm * gcode.SUPPORT_Z_GAP_LAYERS
    tangent = math.tan(math.radians(gcode.TREE_BRANCH_ANGLE_DEG))
    assert supports.contacts and supports.branches
    assert any(contact.bottom > 0 for contact in supports.contacts)
    for contact in supports.contacts:
        tip = (contact.x, contact.y, contact.top - gap)
        incoming = [
            branch
            for branch in supports.branches
            if branch.upper_x == pytest.approx(tip[0])
            and branch.upper_y == pytest.approx(tip[1])
            and branch.upper_z == pytest.approx(tip[2])
        ]
        assert incoming, contact
        branch = incoming[0]
        horizontal = math.hypot(branch.upper_x - branch.lower_x, branch.upper_y - branch.lower_y)
        assert horizontal <= (branch.upper_z - branch.lower_z) * tangent + 1e-6
        assert _branch_reaches(
            supports.branches,
            (branch.lower_x, branch.lower_y, branch.lower_z),
            contact.bottom + gap,
        )


def test_tree_supports_fall_back_to_grounded_tips_for_a_low_overhang() -> None:
    leg = trimesh.creation.box(extents=(3, 3, 1.2))
    leg.apply_translation((0, 0, 0.6))
    slab = trimesh.creation.box(extents=(20, 20, 1.2))
    slab.apply_translation((0, 0, 1.8))
    low = trimesh.boolean.union([leg, slab], engine="manifold")
    printer = PrinterProfile(layer_height_mm=0.3, nozzle_mm=0.4, max_overhang_deg=45)
    supports = gcode._tree_supports(low, printer)
    assert supports.contacts
    assert supports.trunks == len(supports.contacts)
    assert all(
        branch.lower_x == branch.upper_x
        and branch.lower_y == branch.upper_y
        and branch.lower_z == pytest.approx(0.0)
        for branch in supports.branches
    )


def test_tree_supports_merge_a_very_high_overhang_without_exceeding_branch_angle() -> None:
    leg = trimesh.creation.box(extents=(4, 4, 80))
    leg.apply_translation((0, 0, 40))
    slab = trimesh.creation.box(extents=(28, 28, 2))
    slab.apply_translation((0, 0, 81))
    high = trimesh.boolean.union([leg, slab], engine="manifold")
    printer = PrinterProfile(layer_height_mm=0.3, nozzle_mm=0.4, max_overhang_deg=45)
    supports = gcode._tree_supports(high, printer)
    assert 0 < supports.trunks < len(supports.contacts)
    assert any(
        branch.lower_x != branch.upper_x or branch.lower_y != branch.upper_y
        for branch in supports.branches
    )
    tangent = math.tan(math.radians(gcode.TREE_BRANCH_ANGLE_DEG))
    for branch in supports.branches:
        horizontal = math.hypot(branch.upper_x - branch.lower_x, branch.upper_y - branch.lower_y)
        assert horizontal <= (branch.upper_z - branch.lower_z) * tangent + 1e-6


# --- toolpaths land where the model is -------------------------------------------------------

_MOVE = re.compile(r"^G1 X(-?[\d.]+) Y(-?[\d.]+)(?: E(-?[\d.]+))?", re.MULTILINE)


def _layers(text: str) -> list[tuple[float, list[tuple[float, float, bool]]]]:
    """(z, [(x, y, extruding)]) per layer, from our own G-code dialect."""
    layers: list[tuple[float, list[tuple[float, float, bool]]]] = []
    for block in text.split("; layer ")[1:]:
        z = float(re.search(r"z=([\d.]+)", block).group(1))  # type: ignore[union-attr]
        moves = [
            (float(m.group(1)), float(m.group(2)), m.group(3) is not None)
            for m in _MOVE.finditer(block)
        ]
        layers.append((z, moves))
    return layers


def _l_shape() -> trimesh.Trimesh:
    """A slab x 0..50 with a post standing on its right end, x 40..50: every layer's
    section has a different centroid, which is what exposes a per-layer frame shift."""
    slab = trimesh.creation.box(extents=(50, 20, 4))
    slab.apply_translation((25, 10, 2))
    post = trimesh.creation.box(extents=(10, 20, 20))
    post.apply_translation((45, 10, 14))
    shape = trimesh.boolean.union([slab, post], engine="manifold")
    assert isinstance(shape, trimesh.Trimesh)
    return shape


def test_every_layer_keeps_the_models_own_xy() -> None:
    printer = PrinterProfile(layer_height_mm=0.3, nozzle_mm=0.4)
    text, _ = slice_mesh(_l_shape(), printer, SliceSettings(infill_density_pct=20, skirt=False))
    left = printer.bed_x_mm / 2 - 25  # the 50 mm slab, centred on the bed
    for z, moves in _layers(text):
        xs = [x for x, _, extruding in moves if extruding]
        assert min(xs) >= left - 0.01 and max(xs) <= left + 50.01, z
        if z > 4.5:  # only the post: the slab's last 10 mm, not re-centred on anything
            assert min(xs) >= left + 39.99, z


def test_supports_print_under_the_overhang_beside_the_part() -> None:
    # a narrow leg at x 0..6 carrying a slab that overhangs only to +x, out to 30
    leg = trimesh.creation.box(extents=(6, 20, 12))
    leg.apply_translation((3, 10, 6))
    slab = trimesh.creation.box(extents=(30, 20, 3))
    slab.apply_translation((15, 10, 13.5))
    bridge = trimesh.boolean.union([leg, slab], engine="manifold")
    printer = PrinterProfile(layer_height_mm=0.3, nozzle_mm=0.4, max_overhang_deg=45)
    text, stats = slice_mesh(
        bridge, printer, SliceSettings(infill_density_pct=10, supports=True, skirt=False)
    )
    assert stats.support_columns > 0
    left = printer.bed_x_mm / 2 - 15  # the 30 mm slab, centred on the bed
    z, moves = next((z, m) for z, m in _layers(text) if 5.5 < z < 6.5)
    printed_x = [x - left for x, _, extruding in moves if extruding]
    leg_x = [x for x in printed_x if x <= 6.1]
    support_x = [x for x in printed_x if x > 6.1]
    assert leg_x and min(leg_x) >= -0.01  # the leg where it is
    assert support_x and max(support_x) <= 31  # columns under the slab's overhang only


def _t_bridge() -> trimesh.Trimesh:
    """A 6 mm leg (z 0..20) under a 30 mm slab (z 20..24): the slab overhangs air."""
    leg = trimesh.creation.box(extents=(6, 6, 20))
    leg.apply_translation((0, 0, 10))
    slab = trimesh.creation.box(extents=(30, 30, 4))
    slab.apply_translation((0, 0, 22))
    shape = trimesh.boolean.union([leg, slab], engine="manifold")
    assert isinstance(shape, trimesh.Trimesh) and shape.is_watertight
    return shape


def _support_extrusion(text: str, part_half_width: float, bed: float = 128.0) -> dict[float, int]:
    """Extruding moves per layer outside the leg's own footprint (so: support only)."""
    counts: dict[float, int] = {}
    for z, moves in _layers(text):
        counts[z] = sum(
            1
            for x, y, extruding in moves
            if extruding and max(abs(x - bed), abs(y - bed)) > part_half_width + 0.5
        )
    return counts


def test_supports_leave_a_gap_and_print_a_dense_roof_under_the_overhang() -> None:
    printer = PrinterProfile(layer_height_mm=0.3, nozzle_mm=0.4, max_overhang_deg=45)
    settings = SliceSettings(infill_density_pct=10, supports=True, skirt=False)
    text, _ = slice_mesh(_t_bridge(), printer, settings)
    below_slab = _support_extrusion(text, part_half_width=3.0)
    support_layers = [z for z, count in below_slab.items() if count and z <= 20.0]
    # the slab's underside (model z 20) is first printed in the layer 20.1..20.4, so the
    # support must stop by 19.8: one empty layer in between
    assert support_layers and max(support_layers) <= 20.1 - 0.3 + 1e-6
    top = max(support_layers)
    middle = min(support_layers, key=lambda z: abs(z - 10.0))
    assert below_slab[top] > 3 * below_slab[middle]  # the roof is dense, the columns are not
    roof = next(m for z, m in _layers(text) if abs(z - top) < 1e-6)
    xs = [x - 128.0 for x, _, extruding in roof if extruding]
    assert max(xs) <= 15.3 and min(xs) >= -15.3  # never past the slab it holds up


def test_a_column_stands_on_the_part_below_not_through_it() -> None:
    base = trimesh.creation.box(extents=(40, 40, 4))
    base.apply_translation((0, 0, 2))
    pillar = trimesh.creation.box(extents=(6, 6, 12))
    pillar.apply_translation((0, 0, 10))
    roof = trimesh.creation.box(extents=(40, 40, 3))
    roof.apply_translation((0, 0, 17.5))
    shape = trimesh.boolean.union([base, pillar, roof], engine="manifold")
    printer = PrinterProfile(layer_height_mm=0.3, nozzle_mm=0.4, max_overhang_deg=45)
    plain = SliceSettings(infill_density_pct=10, supports=False, skirt=False)
    supported = plain.model_copy(update={"supports": True})
    without, _ = slice_mesh(shape, printer, plain)
    with_supports, stats = slice_mesh(shape, printer, supported)
    assert stats.support_columns > 0
    inside_base = [
        (a, b) for a, b in zip(_layers(without), _layers(with_supports), strict=True) if a[0] < 4
    ]
    for (_, plain_moves), (_, supported_moves) in inside_base:
        assert len(supported_moves) == len(plain_moves)  # nothing extra inside the base slab
    columns = _support_extrusion(with_supports, part_half_width=3.0)
    assert any(count for z, count in columns.items() if 4.5 < z < 15)  # but above it, yes


def test_a_segment_starting_at_zero_is_still_printed() -> None:
    writer = gcode._Writer(
        PrinterProfile(), retraction_mm=1.0, retraction_speed_mm_s=35, active_tool=0
    )
    writer.loop([(0.0, 5.0), (10.0, 5.0)], 0.4)
    assert writer.filament_mm > 0
    assert any(line.startswith("G1 X10.000 Y5.000 E") for line in writer.lines)


def test_writer_records_nonzero_initial_tool_without_emitting_gcode() -> None:
    writer = gcode._Writer(
        PrinterProfile(), retraction_mm=1.4, retraction_speed_mm_s=35, active_tool=3
    )

    assert writer.active_tool == 3
    assert writer.lines == []
    writer.select_tool(3)
    assert writer.lines == []


@pytest.mark.parametrize(
    ("tool", "error"),
    [
        (-1, ValueError),
        (16, ValueError),
        (1.5, TypeError),
        (True, TypeError),
        ("2", TypeError),
        ([], TypeError),
    ],
)
def test_writer_rejects_invalid_initial_tool(
    tool: object, error: type[Exception]
) -> None:
    with pytest.raises(error):
        gcode._Writer(
            PrinterProfile(),
            retraction_mm=1.4,
            retraction_speed_mm_s=35,
            active_tool=tool,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("tool", "error"),
    [
        (-1, ValueError),
        (16, ValueError),
        (1.5, TypeError),
        (True, TypeError),
        ("2", TypeError),
        ([], TypeError),
    ],
)
def test_writer_rejects_invalid_selection_without_mutating_state(
    tool: object, error: type[Exception]
) -> None:
    writer = gcode._Writer(
        PrinterProfile(), retraction_mm=1.4, retraction_speed_mm_s=35, active_tool=1
    )
    writer.loop([(0.0, 0.0), (1.0, 0.0)], 0.4)
    before = (
        list(writer.lines),
        writer.filament_mm,
        writer.travel_mm,
        writer.travel_time_s,
        writer.retraction_time_s,
        writer.active_tool,
        dict(writer._tool_primed),
    )

    with pytest.raises(error):
        writer.select_tool(tool)  # type: ignore[arg-type]

    assert (
        writer.lines,
        writer.filament_mm,
        writer.travel_mm,
        writer.travel_time_s,
        writer.retraction_time_s,
        writer.active_tool,
        writer._tool_primed,
    ) == before


def test_writer_tool_selection_orders_moves_and_isolates_prime_state() -> None:
    writer = gcode._Writer(
        PrinterProfile(), retraction_mm=1.4, retraction_speed_mm_s=35, active_tool=1
    )
    writer.loop([(0.0, 0.0), (1.0, 0.0)], 0.4)
    first_tool_filament = writer.filament_mm

    writer.select_tool(2)
    assert writer.lines[-2:] == ["G1 E-1.4000 F2100", "T2"]
    assert writer.filament_mm == first_tool_filament
    writer.loop([(2.0, 0.0), (3.0, 0.0)], 0.4)

    second_tool_filament = writer.filament_mm
    writer.select_tool(1)
    assert writer.lines[-2:] == ["G1 E-1.4000 F2100", "T1"]
    assert writer.filament_mm == second_tool_filament
    assert writer._tool_primed == {1: False, 2: False}
    writer.loop([(4.0, 0.0), (5.0, 0.0)], 0.4)

    extrusion_only = [line for line in writer.lines if line.startswith("G1 E")]
    assert extrusion_only == [
        "G1 E1.4000 F2100",
        "G1 E-1.4000 F2100",
        "G1 E1.4000 F2100",
        "G1 E-1.4000 F2100",
        "G1 E1.4000 F2100",
    ]
    assert writer.retraction_time_s == pytest.approx(5 * 1.4 / 35)
    assert writer.filament_mm == pytest.approx(3 * gcode._extrusion_mm(1.0, 0.2, 0.4))
    assert writer._tool_primed == {1: True, 2: False}


def test_writer_selecting_active_tool_is_a_complete_noop() -> None:
    writer = gcode._Writer(
        PrinterProfile(), retraction_mm=1.4, retraction_speed_mm_s=35, active_tool=2
    )
    writer.loop([(0.0, 0.0), (1.0, 0.0)], 0.4)
    before = (
        list(writer.lines),
        writer.filament_mm,
        writer.retraction_time_s,
        dict(writer._tool_primed),
    )

    writer.select_tool(2)

    assert (
        writer.lines,
        writer.filament_mm,
        writer.retraction_time_s,
        writer._tool_primed,
    ) == before


def test_writer_accounts_exact_travel_and_each_emitted_retraction_move_once() -> None:
    printer = PrinterProfile(print_speed_mm_s=60)
    writer = gcode._Writer(
        printer, retraction_mm=1.4, retraction_speed_mm_s=35, active_tool=0
    )
    writer.loop([(-1.0, 0.0), (0.0, 0.0)], 0.4)
    writer.loop([(3.0, 4.0), (4.0, 4.0)], 0.4)

    extrusion_only = [line for line in writer.lines if line.startswith("G1 E")]
    assert extrusion_only == [
        "G1 E1.4000 F2100",
        "G1 E-1.4000 F2100",
        "G1 E1.4000 F2100",
    ]
    assert writer.travel_mm == pytest.approx(5.0)
    assert writer.travel_time_s == pytest.approx(5.0 / (writer.travel_feed / 60))
    assert writer.retraction_time_s == pytest.approx(3 * 1.4 / 35)

    no_retraction = gcode._Writer(
        printer, retraction_mm=0.0, retraction_speed_mm_s=35, active_tool=0
    )
    no_retraction.loop([(-1.0, 0.0), (0.0, 0.0)], 0.4)
    no_retraction.loop([(3.0, 4.0), (4.0, 4.0)], 0.4)
    assert no_retraction.retraction_time_s == 0.0


def test_full_slice_never_selects_tool_or_emits_tool_or_purge_moves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_tool_is_selected(self: gcode._Writer, tool: int) -> None:
        pytest.fail(f"slice_mesh unexpectedly selected T{tool}")

    monkeypatch.setattr(gcode._Writer, "select_tool", fail_if_tool_is_selected)
    text, _ = slice_mesh(
        trimesh.creation.box(extents=(10, 10, 0.6)),
        PrinterProfile(layer_height_mm=0.3),
        SliceSettings(
            infill_density_pct=20,
            skirt=False,
            tool_change_mode="marlin_tn",
            tool_count=3,
            base_tool=2,
        ),
    )

    assert re.search(r"^T\d+$", text, re.MULTILINE) is None
    assert "TYPE:purge-tower" not in text


def test_seams_stack_at_the_back() -> None:
    cylinder = trimesh.creation.cylinder(radius=10, height=4, sections=64)
    printer = PrinterProfile(layer_height_mm=0.3, nozzle_mm=0.4)
    text, _ = slice_mesh(cylinder, printer, SliceSettings(infill_density_pct=20, skirt=False))
    seams = [next((x, y) for x, y, e in moves if not e) for _, moves in _layers(text)]
    xs, ys = [x for x, _ in seams], [y for _, y in seams]
    assert max(xs) - min(xs) < 1.0 and max(ys) - min(ys) < 0.5  # one line, not a scatter
    assert min(ys) > printer.bed_y_mm / 2 + 9.0  # at the rear (+Y) of a radius-10 part


def test_nearest_first_ordering_cuts_travel(monkeypatch: pytest.MonkeyPatch) -> None:
    outer = trimesh.creation.cylinder(radius=20, height=2, sections=64)
    hole = trimesh.creation.cylinder(radius=10, height=4, sections=64)
    ring = outer.difference(hole, engine="manifold")  # every infill line splits in two
    printer = PrinterProfile(layer_height_mm=0.3, nozzle_mm=0.4)
    settings = SliceSettings(infill_density_pct=30, skirt=False)
    _, ordered = slice_mesh(ring, printer, settings)
    monkeypatch.setattr(gcode, "_nearest_first", lambda paths, start: paths)
    _, generation_order = slice_mesh(ring, printer, settings)
    assert ordered.filament_used_mm == pytest.approx(generation_order.filament_used_mm)
    assert ordered.travel_mm < 0.7 * generation_order.travel_mm


def test_two_opt_removes_a_greedy_route_detour(monkeypatch: pytest.MonkeyPatch) -> None:
    paths: list[gcode.Path2] = [
        [(7, 18), (17, 4)],
        [(11, 19), (15, 20)],
        [(18, 2), (19, 0)],
        [(15, 8), (17, 7)],
        [(6, 15), (17, 17)],
        [(15, 12), (20, 4)],
        [(7, 20), (4, 16)],
    ]
    start = (0.0, 0.0)
    improved = gcode._nearest_first(paths, start)
    monkeypatch.setattr(gcode, "_two_opt_route", lambda route, _start: route)
    greedy = gcode._nearest_first(paths, start)

    assert gcode._travel_length(improved, start) < 0.8 * gcode._travel_length(greedy, start)
    # The optimization may reverse a segment, but it must neither lose nor invent one.
    assert {frozenset(path) for path in improved} == {frozenset(path) for path in paths}


def test_gcode_is_in_bed_coordinates() -> None:
    # modelled around the origin, as primitives are: raw, that is negative X/Y
    part = trimesh.creation.box(extents=(40, 20, 6))
    printer = PrinterProfile(layer_height_mm=0.3, nozzle_mm=0.4)
    text, _ = slice_mesh(part, printer, SliceSettings(infill_density_pct=20))
    points = [(x, y) for _, moves in _layers(text) for x, y, _ in moves]
    xs, ys = [x for x, _ in points], [y for _, y in points]
    assert min(xs) >= 0 and max(xs) <= printer.bed_x_mm
    assert min(ys) >= 0 and max(ys) <= printer.bed_y_mm
    assert (min(xs) + max(xs)) / 2 == pytest.approx(printer.bed_x_mm / 2, abs=0.5)
    first = _layers(text)[0][0]
    assert first == pytest.approx(printer.layer_height_mm)  # first layer on the bed


def test_a_part_that_only_fits_turned_is_turned() -> None:
    printer = PrinterProfile(bed_x_mm=100, bed_y_mm=200, layer_height_mm=0.3, nozzle_mm=0.4)
    long_part = trimesh.creation.box(extents=(180, 40, 3))
    text, _ = slice_mesh(long_part, printer, SliceSettings(infill_density_pct=10, skirt=False))
    assert "turned 90 degrees" in text
    xs = [x for _, moves in _layers(text) for x, _, e in moves if e]
    assert max(xs) - min(xs) < 41  # the 180 mm side now runs along Y


def test_a_part_bigger_than_the_bed_is_refused() -> None:
    printer = PrinterProfile(bed_x_mm=100, bed_y_mm=100, layer_height_mm=0.3, nozzle_mm=0.4)
    with pytest.raises(ValueError, match="exceeds the printer bed"):
        slice_mesh(trimesh.creation.box(extents=(150, 120, 3)), printer, SliceSettings())


def _skirt_moves(text: str) -> list[tuple[float, float]]:
    """The skirt is printed before the first layer marker."""
    return [
        (float(m.group(1)), float(m.group(2))) for m in _MOVE.finditer(text.split("; layer ")[0])
    ]


def test_the_skirt_follows_the_part_and_stays_on_the_bed() -> None:
    printer = PrinterProfile(bed_x_mm=60, bed_y_mm=60, layer_height_mm=0.3, nozzle_mm=0.4)
    thin = slice_mesh(trimesh.creation.box(extents=(40, 10, 2)), printer, SliceSettings())[0]
    ys = [y for _, y in _skirt_moves(thin)]
    # 5 mm around a 10 mm-deep part: ~20 mm, where a circle round its 40 mm length was 50
    assert ys and max(ys) - min(ys) == pytest.approx(20, abs=0.5)
    edge_to_edge = slice_mesh(trimesh.creation.box(extents=(58, 20, 2)), printer, SliceSettings())
    assert _skirt_moves(edge_to_edge[0]) == []  # no room on the bed: left out, not clipped


# --- the printer's own calibration (F-028/F-029) ----------------------------------------------


def _outer_loop_width(text: str) -> float:
    """X extent of the first layer's first loop (its outer perimeter)."""
    moves = _layers(text)[0][1]
    loop = []
    for x, _, extruding in moves[1:]:
        if not extruding:
            break
        loop.append(x)
    return max(loop) - min(loop)


def _hole_loop_width(text: str) -> float:
    """X extent of the smallest closed loop on the first layer — the hole's perimeter."""
    loops: list[list[float]] = []
    for x, _, extruding in _layers(text)[0][1]:
        if not extruding:
            loops.append([])
        loops[-1].append(x)
    return float(min(max(loop) - min(loop) for loop in loops if len(loop) > 1))


def test_measured_line_fatness_pulls_outsides_in_and_opens_holes() -> None:
    plate = trimesh.creation.box(extents=(30, 30, 2))
    hole = trimesh.creation.cylinder(radius=5, height=6, sections=64)
    part = plate.difference(hole, engine="manifold")
    settings = SliceSettings(
        infill_density_pct=0,
        wall_count=1,
        top_solid_layers=0,
        bottom_solid_layers=0,
        skirt=False,
    )
    plain = slice_mesh(part, PrinterProfile(layer_height_mm=0.3), settings)[0]
    fat = PrinterProfile(layer_height_mm=0.3, xy_compensation_mm=0.2)
    calibrated, stats = slice_mesh(part, fat, settings)
    assert _outer_loop_width(calibrated) == pytest.approx(_outer_loop_width(plain) - 0.4, abs=0.01)
    assert _hole_loop_width(calibrated) == pytest.approx(_hole_loop_width(plain) + 0.4, abs=0.05)
    assert stats.xy_compensation_mm == 0.2
    assert "calibration (measured on this printer's coupon)" in calibrated


def test_measured_shrinkage_grows_xy_but_not_z() -> None:
    cube = trimesh.creation.box(extents=(20, 20, 3))
    settings = SliceSettings(infill_density_pct=0, wall_count=1, skirt=False)
    plain, before = slice_mesh(cube, PrinterProfile(layer_height_mm=0.3), settings)
    shrinks = PrinterProfile(layer_height_mm=0.3, shrinkage_pct=1.0)
    scaled, after = slice_mesh(cube, shrinks, settings)
    expected = (20 / 0.99 - 0.4) / (20 - 0.4)  # centre lines of the outer loop
    assert _outer_loop_width(scaled) / _outer_loop_width(plain) == pytest.approx(expected, rel=1e-3)
    assert after.total_layers == before.total_layers  # the coupon measures X/Y, not height


def test_measured_flow_and_learned_flow_multiply() -> None:
    cube = trimesh.creation.box(extents=(20, 20, 3))
    settings = SliceSettings(infill_density_pct=0, wall_count=1, skirt=False)
    plain = slice_mesh(cube, PrinterProfile(layer_height_mm=0.3), settings)[1]
    calibrated = PrinterProfile(layer_height_mm=0.3, flow_pct=95.0)
    text, measured = slice_mesh(cube, calibrated, settings)
    # stats round filament to 0.1 mm
    assert measured.filament_used_mm == pytest.approx(plain.filament_used_mm * 0.95, abs=0.1)
    assert measured.flow_pct == 95.0 and "flow 95%" in text
    both = settings.model_copy(update={"tuning": gcode.PrintTuning(flow_pct=104)})
    combined = slice_mesh(cube, calibrated, both)[1]
    assert combined.filament_used_mm == pytest.approx(plain.filament_used_mm * 0.95 * 1.04, abs=0.1)


def test_absurd_calibration_is_refused_by_the_profile() -> None:
    with pytest.raises(ValueError):
        PrinterProfile(xy_compensation_mm=3.0)


# --- F-056: what print reports taught reaches the G-code -------------------------------------

LAYER = PrinterProfile(layer_height_mm=0.3)
BARE = SliceSettings(infill_density_pct=0, wall_count=1, skirt=False)


def _tuned(**tuning: float) -> SliceSettings:
    return BARE.model_copy(update={"tuning": gcode.PrintTuning(**tuning)})


def test_temperature_offsets_and_retraction_are_written() -> None:
    cube = trimesh.creation.box(extents=(20, 20, 3))
    text, stats = slice_mesh(
        cube, LAYER, _tuned(nozzle_offset_c=-10, bed_offset_c=5, retraction_mm=2.5)
    )
    assert "M104 S190" in text and "M109 S190" in text  # PLA 200 - 10
    assert "M140 S65" in text and "M190 S65" in text  # PLA 60 + 5
    assert "G1 E-2.5000" in text and "G1 E-1.2000" not in text
    assert stats.tuning == {"nozzle_offset_c": -10.0, "bed_offset_c": 5.0, "retraction_mm": 2.5}
    assert "tuning (learned from print reports)" in text
    untuned = slice_mesh(cube, LAYER, BARE)[1]
    assert untuned.tuning == {} and untuned.brim_loops == 0


def test_flow_scales_every_extrusion() -> None:
    cube = trimesh.creation.box(extents=(20, 20, 3))
    plain = slice_mesh(cube, LAYER, BARE)[1]
    more = slice_mesh(cube, LAYER, _tuned(flow_pct=110))[1]
    assert more.filament_used_mm == pytest.approx(plain.filament_used_mm * 1.1, rel=1e-3)


def test_a_brim_rings_the_first_layer_and_replaces_the_skirt() -> None:
    cube = trimesh.creation.box(extents=(20, 20, 3))
    settings = SliceSettings(infill_density_pct=0, wall_count=1, skirt=True)
    settings = settings.model_copy(update={"tuning": gcode.PrintTuning(brim_mm=4)})
    text, stats = slice_mesh(cube, LAYER, settings)
    assert stats.brim_loops == 10  # 4 mm of 0.4 mm lines
    assert _skirt_moves(text) == []  # nothing printed before the first layer
    first = _layers(text)[0][1]
    xs = [x for x, _, extruding in first if extruding]
    # the outermost loop's centre line sits 3.8 mm outside the 20 mm part, on each side
    assert max(xs) - min(xs) == pytest.approx(20 + 2 * 3.8, abs=0.05)
    second = [x for x, _, extruding in _layers(text)[1][1] if extruding]
    assert max(second) - min(second) < 20  # only the first layer carries it


def test_manual_adhesion_overrides_learned_brim_without_hiding_the_tuning() -> None:
    cube = trimesh.creation.box(extents=(20, 20, 3))
    learned = gcode.PrintTuning(brim_mm=3)

    manual = SliceSettings(
        infill_density_pct=0,
        wall_count=1,
        adhesion_mode="brim",
        brim_width_mm=6,
        tuning=learned,
    )
    manual_text, manual_stats = slice_mesh(cube, LAYER, manual)
    assert manual_stats.adhesion_mode == "brim"
    assert manual_stats.brim_width_mm == 6
    assert manual_stats.brim_loops == 15
    assert "; adhesion: mode=brim width=6mm" in manual_text
    assert manual_stats.tuning["brim_mm"] == 3

    disabled_text, disabled_stats = slice_mesh(
        cube, LAYER, manual.model_copy(update={"adhesion_mode": "none"})
    )
    assert disabled_stats.adhesion_mode == "none"
    assert disabled_stats.brim_width_mm == 0
    assert disabled_stats.brim_loops == 0
    assert _skirt_moves(disabled_text) == []

    skirt_text, skirt_stats = slice_mesh(
        cube, LAYER, manual.model_copy(update={"adhesion_mode": "skirt"})
    )
    assert skirt_stats.adhesion_mode == "skirt"
    assert skirt_stats.brim_loops == 0
    assert _skirt_moves(skirt_text)


def test_mouse_ears_are_real_local_first_layer_tabs() -> None:
    cube = trimesh.creation.box(extents=(20, 20, 3))
    text, stats = slice_mesh(
        cube,
        LAYER,
        SliceSettings(
            infill_density_pct=0,
            wall_count=1,
            adhesion_mode="mouse_ears",
            mouse_ear_diameter_mm=10,
        ),
    )
    assert stats.adhesion_mode == "mouse_ears"
    assert stats.mouse_ear_count == 4
    assert stats.mouse_ear_diameter_mm == 10
    assert stats.brim_loops == 0
    assert "; adhesion: mode=mouse_ears diameter=10mm" in text
    assert "; TYPE:mouse-ear" in text
    first_x = [x for x, _, extruding in _layers(text)[0][1] if extruding]
    second_x = [x for x, _, extruding in _layers(text)[1][1] if extruding]
    assert max(first_x) - min(first_x) > 29
    assert max(second_x) - min(second_x) < 21

    full_bed = trimesh.creation.box(extents=(LAYER.bed_x_mm, LAYER.bed_y_mm, 1))
    edge_text, edge_stats = slice_mesh(
        full_bed,
        LAYER,
        SliceSettings(infill_density_pct=0, wall_count=1, adhesion_mode="mouse_ears"),
    )
    assert edge_stats.mouse_ear_count == 0
    assert "; TYPE:mouse-ear" not in edge_text


def test_painted_mouse_ears_follow_bed_rotation_and_reject_unattached_points() -> None:
    printer = PrinterProfile(
        bed_x_mm=100,
        bed_y_mm=200,
        bed_z_mm=200,
        layer_height_mm=0.2,
        nozzle_mm=0.4,
    )
    part = trimesh.creation.box(extents=(150, 80, 3))
    text, stats = slice_mesh(
        part,
        printer,
        SliceSettings(
            infill_density_pct=0,
            wall_count=1,
            adhesion_mode="mouse_ears",
            mouse_ear_diameter_mm=10,
            mouse_ear_points_mm=[(-75, -40, 0), (0, 0, 0)],
        ),
    )
    assert "turned 90 degrees to fit" in text
    assert stats.mouse_ear_requested_count == 2
    assert stats.mouse_ear_count == 1
    assert stats.mouse_ear_rejected_count == 1
    assert "; adhesion: mode=mouse_ears diameter=10mm painted_points=2" in text
    assert "; TYPE:mouse-ear" in text


@pytest.mark.parametrize("mode", ["skirt", "brim", "mouse_ears", "raft"])
def test_every_adhesion_path_uses_its_explicit_speed(mode: str) -> None:
    cube = trimesh.creation.box(extents=(20, 20, 3))
    text, stats = slice_mesh(
        cube,
        LAYER,
        SliceSettings(
            infill_density_pct=0,
            wall_count=1,
            adhesion_mode=mode,
            adhesion_speed_pct=50,
        ),
    )
    marker = {
        "skirt": "; TYPE:skirt",
        "brim": "; TYPE:brim",
        "mouse_ears": "; TYPE:mouse-ear",
        "raft": "; TYPE:raft-base",
    }[mode]
    section = text.split(marker, 1)[1]
    assert re.search(r"E[\d.]+ F1800$", section, re.MULTILINE)
    assert stats.adhesion_speed_pct == 50
    assert "speed=50%" in text


def test_raft_profiles_layers_and_lifts_the_model_with_a_gap() -> None:
    cube = trimesh.creation.box(extents=(20, 20, 3))
    plain_stats = slice_mesh(cube, LAYER, BARE)[1]
    text, stats = slice_mesh(
        cube,
        LAYER,
        SliceSettings(
            infill_density_pct=0,
            wall_count=1,
            adhesion_mode="raft",
            raft_margin_mm=6,
            raft_base_layers=2,
            raft_interface_layers=2,
            raft_base_layer_height_mm=0.3,
            raft_interface_layer_height_mm=0.15,
            raft_base_speed_pct=50,
            raft_interface_speed_pct=80,
            raft_air_gap_mm=0.3,
            adhesion_speed_pct=60,
        ),
    )
    layers = _layers(text)
    assert stats.adhesion_mode == "raft"
    assert stats.raft_layers == 4
    assert stats.raft_base_layers == 2
    assert stats.raft_interface_layers == 2
    assert stats.raft_base_layer_height_mm == 0.3
    assert stats.raft_interface_layer_height_mm == 0.15
    assert stats.raft_base_speed_pct == 50
    assert stats.raft_interface_speed_pct == 80
    assert stats.raft_margin_mm == 6
    assert stats.raft_air_gap_mm == 0.3
    assert stats.total_layers == plain_stats.total_layers + 4 == len(layers)
    assert layers[0][0] == pytest.approx(0.3)
    assert layers[1][0] == pytest.approx(0.6)
    assert layers[2][0] == pytest.approx(0.75)
    assert layers[3][0] == pytest.approx(0.9)
    assert layers[4][0] == pytest.approx(1.5)
    assert text.count("; TYPE:raft-base") == 2
    assert text.count("; TYPE:raft-interface") == 2
    base_section = text.split("; TYPE:raft-base", 1)[1].split("; layer", 1)[0]
    interface_section = text.split("; TYPE:raft-interface", 1)[1].split("; layer", 1)[0]
    assert re.search(r"E[\d.]+ F1080$", base_section, re.MULTILINE)
    assert re.search(r"E[\d.]+ F1728$", interface_section, re.MULTILINE)
    assert (
        "; adhesion: mode=raft margin=6mm layers=4 base_layers=2 "
        "interface_layers=2 base_height=0.3mm interface_height=0.15mm gap=0.3mm "
        "base_density=40% interface_density=100% "
        "density_source=fallback base_speed=50% interface_speed=80% speed=60%" in text
    )

    full_bed = trimesh.creation.box(extents=(LAYER.bed_x_mm, LAYER.bed_y_mm, 1))
    with pytest.raises(ValueError, match="raft exceeds the printer bed"):
        slice_mesh(full_bed, LAYER, SliceSettings(adhesion_mode="raft", raft_margin_mm=3))


def test_raft_height_fallback_preserves_profile_layers_and_rejects_unsafe_nozzle_ratio() -> None:
    cube = trimesh.creation.box(extents=(20, 20, 3))
    text, stats = slice_mesh(cube, LAYER, SliceSettings(adhesion_mode="raft"))
    layers = _layers(text)

    assert SliceSettings().raft_base_layer_height_mm is None
    assert SliceSettings().raft_interface_layer_height_mm is None
    assert stats.raft_base_layer_height_mm == LAYER.layer_height_mm
    assert stats.raft_interface_layer_height_mm == LAYER.layer_height_mm
    assert layers[0][0] == pytest.approx(LAYER.layer_height_mm)
    assert layers[1][0] == pytest.approx(2 * LAYER.layer_height_mm)
    assert "base_height=" not in text
    assert "interface_height=" not in text

    with pytest.raises(ValueError, match="raft layer height must be at most 80%"):
        slice_mesh(
            cube,
            LAYER,
            SliceSettings(adhesion_mode="raft", raft_base_layer_height_mm=0.33),
        )


def test_fallback_raft_base_preserves_legacy_two_point_five_line_spacing() -> None:
    first_layer = [shapely.Polygon([(80, 80), (100, 80), (100, 100), (80, 100)])]
    line_width = 0.4
    margin_mm = 5.0
    fallback_base, _ = gcode._raft_paths(first_layer, LAYER, line_width, margin_mm)

    solid = shapely.union_all([shapely.Polygon(p.exterior) for p in first_layer]).buffer(
        margin_mm, join_style="round"
    )
    legacy_base: list[list[tuple[float, float]]] = []
    for area in gcode._as_polygons(solid):
        rings, infill_area = gcode._perimeter_rings(area, line_width, 1)
        legacy_base.extend(rings)
        legacy_base.extend(gcode._infill_lines(infill_area, line_width * 2.5, 0.0))

    assert fallback_base == legacy_base
    assert SliceSettings().raft_base_density_pct == 40


def test_raft_density_changes_real_line_count_and_is_reported_in_gcode() -> None:
    cube = trimesh.creation.box(extents=(30, 30, 2))
    sparse_text, sparse_stats = slice_mesh(
        cube,
        LAYER,
        SliceSettings(
            adhesion_mode="raft",
            raft_base_density_pct=10,
            raft_interface_density_pct=50,
            raft_density_profiled=True,
        ),
    )
    dense_text, dense_stats = slice_mesh(
        cube,
        LAYER,
        SliceSettings(
            adhesion_mode="raft",
            raft_base_density_pct=70,
            raft_interface_density_pct=100,
            raft_density_profiled=True,
        ),
    )
    sparse_raft = sparse_text.split("; TYPE:raft-base", 1)[1].split("; layer", 1)[0]
    dense_raft = dense_text.split("; TYPE:raft-base", 1)[1].split("; layer", 1)[0]
    assert dense_raft.count("G1 X") > sparse_raft.count("G1 X")
    assert dense_stats.filament_used_mm > sparse_stats.filament_used_mm
    assert dense_stats.raft_base_density_pct == 70
    assert dense_stats.raft_interface_density_pct == 100
    assert dense_stats.raft_density_profiled is True
    assert "base_density=70% interface_density=100% density_source=profile" in dense_text


def test_elephant_foot_pulls_in_the_first_layer_only() -> None:
    cube = trimesh.creation.box(extents=(20, 20, 3))
    text = slice_mesh(cube, LAYER, _tuned(elephant_foot_mm=0.2))[0]
    widths = []
    for _, moves in _layers(text)[:2]:
        loop = [x for x, _, extruding in moves if extruding]
        widths.append(max(loop) - min(loop))
    assert widths[0] == pytest.approx(widths[1] - 0.4, abs=0.01)


def test_a_slower_first_layer_is_slower_only_there() -> None:
    cube = trimesh.creation.box(extents=(20, 20, 3))
    text = slice_mesh(cube, LAYER, _tuned(first_layer_speed_pct=50))[0]
    layer_blocks = text.split("; layer ")[1:]
    first_feeds = set(re.findall(r"Y[\d.]+ E[\d.]+ F(\d+)", layer_blocks[0]))
    later_feeds = set(re.findall(r"Y[\d.]+ E[\d.]+ F(\d+)", layer_blocks[1]))
    assert first_feeds == {"1800"} and later_feeds == {"3600"}  # 60 mm/s halved


def test_tuning_outside_safe_bounds_is_refused() -> None:
    for bad in ({"nozzle_offset_c": 40}, {"flow_pct": 150}, {"retraction_mm": 12}, {"brim_mm": 30}):
        with pytest.raises(ValueError):
            gcode.PrintTuning(**bad)


# --- honeycomb infill: a real hexagonal tiling, not three crossed line families --------------


def test_honeycomb_tiling_stays_inside_the_polygon_and_dedupes_shared_walls() -> None:
    from shapely.geometry import Polygon

    square = Polygon([(0, 0), (60, 0), (60, 60), (0, 60)])
    lines = gcode._honeycomb_lines([square], cell_mm=6.0)
    assert lines  # something was actually generated
    pad = 0.5  # roundtrip float slop
    seen: set[tuple[tuple[float, float], tuple[float, float]]] = set()
    for line in lines:
        for x, y in line:
            assert -pad <= x <= 60 + pad
            assert -pad <= y <= 60 + pad
        # Every interior wall belongs to two neighbouring hexagons; if dedup failed, the
        # same clipped segment would appear a second time under the other hexagon's pass.
        ends = (
            (round(line[0][0], 2), round(line[0][1], 2)),
            (round(line[-1][0], 2), round(line[-1][1], 2)),
        )
        key = ends if ends[0] <= ends[1] else (ends[1], ends[0])
        assert key not in seen, "a shared hexagon edge was printed twice"
        seen.add(key)


def test_honeycomb_density_scales_like_lines_infill() -> None:
    mesh = trimesh.creation.box(extents=(20, 20, 10))
    printer = PrinterProfile(layer_height_mm=0.2, nozzle_mm=0.4)
    _, sparse = slice_mesh(
        mesh, printer, SliceSettings(infill_density_pct=10, infill_pattern="honeycomb", skirt=False)
    )
    _, dense = slice_mesh(
        mesh, printer, SliceSettings(infill_density_pct=60, infill_pattern="honeycomb", skirt=False)
    )
    assert 0 < sparse.filament_used_mm < dense.filament_used_mm


def test_honeycomb_gcode_is_well_formed() -> None:
    mesh = trimesh.creation.box(extents=(20, 20, 4))
    printer = PrinterProfile(layer_height_mm=0.2, nozzle_mm=0.4)
    text, stats = slice_mesh(
        mesh, printer, SliceSettings(infill_density_pct=25, infill_pattern="honeycomb")
    )
    assert stats.filament_used_mm > 0
    for match in re.finditer(r"E(-?[\d.]+)", text):
        assert abs(float(match.group(1))) < 50  # relative extrusion (M83): bounded moves


def test_top_and_bottom_skins_close_a_sparse_print() -> None:
    mesh = trimesh.creation.box(extents=(20, 20, 4))
    printer = PrinterProfile(layer_height_mm=0.2, nozzle_mm=0.4)
    _, open_stats = slice_mesh(
        mesh,
        printer,
        SliceSettings(
            infill_density_pct=0,
            wall_count=1,
            top_solid_layers=0,
            bottom_solid_layers=0,
            skirt=False,
        ),
    )
    text, closed_stats = slice_mesh(
        mesh,
        printer,
        SliceSettings(
            infill_density_pct=0,
            wall_count=1,
            top_solid_layers=4,
            bottom_solid_layers=4,
            skirt=False,
        ),
    )
    assert open_stats.solid_skin_paths == 0
    assert closed_stats.solid_skin_paths > 0
    assert closed_stats.filament_used_mm > open_stats.filament_used_mm
    assert "top_layers=4 bottom_layers=4" in text


def test_solid_skins_cover_intermediate_ledges_for_the_requested_thickness() -> None:
    from shapely.geometry import Polygon

    small = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    large = Polygon([(0, 0), (20, 0), (20, 10), (0, 10)])
    footprints = [small] * 5 + [large] * 5

    for layer in (5, 6, 7):
        dense, sparse = gcode._solid_skin_areas(
            [large], footprints, layer, top_layers=0, bottom_layers=3
        )
        assert sum(part.area for part in dense) == pytest.approx(100)
        assert sum(part.area for part in sparse) == pytest.approx(100)

    dense, sparse = gcode._solid_skin_areas([large], footprints, 8, top_layers=0, bottom_layers=3)
    assert dense == []
    assert sum(part.area for part in sparse) == pytest.approx(200)

    descending = [large] * 5 + [small] * 5
    for layer in (2, 3, 4):
        dense, sparse = gcode._solid_skin_areas(
            [large], descending, layer, top_layers=3, bottom_layers=0
        )
        assert sum(part.area for part in dense) == pytest.approx(100)
        assert sum(part.area for part in sparse) == pytest.approx(100)


def test_sandbox_slice_writes_a_real_gcode_file(tmp_path: Path) -> None:
    mesh_path = tmp_path / "box.stl"
    trimesh.creation.box(extents=(8, 8, 2)).export(mesh_path)
    out_dir = tmp_path / "out"
    stats = slice_file_in_sandbox(mesh_path, PrinterProfile(), SliceSettings(), out_dir)
    gcode_path = out_dir / stats["gcode_file"]
    assert gcode_path.exists()
    assert gcode_path.stat().st_size == stats["gcode_bytes"]
    import hashlib

    assert hashlib.sha256(gcode_path.read_bytes()).hexdigest() == stats["gcode_sha256"]
