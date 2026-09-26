"""Real slicing (F-054, second stage): perimeters, infill and G-code."""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest
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
    body = text.split("G91", 1)[0]  # the footer's relative Z-lift comes after this
    z_values = [float(m.group(1)) for m in re.finditer(r"^G1 Z([\d.]+)", body, re.MULTILINE)]
    assert z_values == sorted(z_values)
    assert z_values[-1] == pytest.approx(stats.total_layers * printer.layer_height_mm)
    for match in re.finditer(r"E(-?[\d.]+)", text):
        # relative extrusion mode (M83): every E value is a finite, bounded move
        assert abs(float(match.group(1))) < 50


def test_rejects_non_fdm_and_non_watertight() -> None:
    mesh = trimesh.creation.box(extents=(10, 10, 2))
    with pytest.raises(ValueError, match="FDM"):
        slice_mesh(mesh, PrinterProfile(technology="resin"), SliceSettings())
    open_mesh = trimesh.creation.box(extents=(10, 10, 2))
    open_mesh.update_faces(open_mesh.face_normals[:, 0] < 0.5)
    with pytest.raises(ValueError, match="closed solid"):
        slice_mesh(open_mesh, PrinterProfile(), SliceSettings())


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
    writer = gcode._Writer(PrinterProfile(), retraction_mm=1.0, retraction_speed_mm_s=35)
    writer.loop([(0.0, 5.0), (10.0, 5.0)], 0.4)
    assert writer.filament_mm > 0
    assert any(line.startswith("G1 X10.000 Y5.000 E") for line in writer.lines)


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
    settings = SliceSettings(infill_density_pct=0, wall_count=1, skirt=False)
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
