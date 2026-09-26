"""T-126/T-127 (F-028/F-029): a coupon the kernel builds, and what calipers teach from it."""

from __future__ import annotations

import pytest

from app.api.errors import ValidationFailedError
from app.geometry.operations import parse_plan
from app.services import calibration
from app.services.calibration import Measurements, derive


def test_the_coupon_is_a_valid_plan_with_every_feature_to_measure() -> None:
    plan = parse_plan(calibration.coupon_plan())
    types = [op.type for op in plan.operations]
    assert types.count("add_hole") == len(calibration.HOLES_MM)
    assert types.count("create_cylinder") == len(calibration.PEGS_MM)
    assert types.count("boolean") == len(calibration.PEGS_MM) + 1  # the pegs and the flow wall
    wall = next(op.model_dump() for op in plan.operations if op.id == "flow_wall")
    assert wall["depth_mm"] == calibration.DEFAULT_WALL_MM
    holes = [op.model_dump()["diameter_mm"] for op in plan.operations if op.type == "add_hole"]
    assert holes == list(calibration.HOLES_MM)
    features = calibration.coupon_features()
    assert {f["id"] for f in features} == set(Measurements.model_fields)


def test_calipers_become_undersize_oversize_and_shrink() -> None:
    learned = derive(
        Measurements(
            hole_3_mm=2.7,
            hole_5_mm=4.75,
            hole_8_mm=7.8,
            peg_5_mm=5.15,
            peg_8_mm=8.1,
            length_60_mm=59.7,
        )
    )
    assert learned.hole_undersize_mm == pytest.approx(0.25, abs=1e-3)  # mean of .3/.25/.2
    assert learned.peg_oversize_mm == pytest.approx(0.125, abs=1e-3)
    assert learned.xy_compensation_mm == pytest.approx(0.094, abs=1e-3)
    assert learned.shrinkage_pct == pytest.approx(0.5, abs=1e-3)
    assert learned.samples == 6 and learned.measured_at
    assert learned.measurements["hole_3_mm"] == 2.7


def test_a_partial_measurement_learns_only_what_it_saw() -> None:
    learned = derive(Measurements(hole_5_mm=4.6))
    assert learned.hole_undersize_mm == pytest.approx(0.4)
    assert learned.peg_oversize_mm is None and learned.xy_compensation_mm is None
    assert learned.shrinkage_pct is None


def test_the_thin_wall_measures_the_flow() -> None:
    fat = derive(Measurements(wall_mm=0.84))  # 5% too thick: the extruder over-pushes
    assert fat.flow_pct == pytest.approx(95.2, abs=0.05)
    wide_nozzle = derive(Measurements(wall_mm=1.14), wall_mm=calibration.wall_for(0.6))
    assert wide_nozzle.flow_pct == pytest.approx(105.3, abs=0.05)  # a 1.2 mm wall, thin
    with pytest.raises(ValidationFailedError):
        derive(Measurements(wall_mm=0.4))  # one line, not two: not a flow reading
    from app.services.printing import calibration_settings

    assert calibration_settings({"flow_pct": 95.2}) == {"flow_pct": 95.2}
    assert calibration_settings({"flow_pct": 60}) == {}


def test_nonsense_readings_are_refused() -> None:
    with pytest.raises(ValidationFailedError):
        derive(Measurements())
    with pytest.raises(ValidationFailedError):
        derive(Measurements(hole_8_mm=3.0))  # 5 mm off: not this coupon, or not calipers
    with pytest.raises(ValidationFailedError):
        derive(Measurements(length_60_mm=50.0))  # would scale every sliced part by 20%


def test_the_slicer_gets_the_measured_corrections_and_nothing_implausible() -> None:
    from app.services.printing import calibration_settings

    learned = derive(Measurements(hole_5_mm=4.8, peg_5_mm=5.2, length_60_mm=59.7))
    applied = calibration_settings(learned.model_dump(exclude_none=True))
    assert applied == {"xy_compensation_mm": pytest.approx(0.1), "shrinkage_pct": 0.5}
    assert calibration_settings(None) == {}
    assert calibration_settings({"xy_compensation_mm": "fat", "shrinkage_pct": True}) == {}
    assert calibration_settings({"xy_compensation_mm": 4.0}) == {}  # outside the worker's bounds


def test_a_measured_undersize_replaces_the_typical_one_in_every_screw_hole() -> None:
    from app.ai import smart_sizes
    from app.engineering import knowledge as kb

    m5 = kb.FASTENERS["m5"]
    assert kb.hole_for(m5, "clearance", "pla") == pytest.approx(5.7)  # typical PLA 0.2
    assert kb.hole_for(m5, "clearance", "pla", undersize_mm=0.35) == pytest.approx(5.85)
    assert kb.hole_for(m5, "clearance", "petg", undersize_mm=0.0) == pytest.approx(5.5)
    found = smart_sizes.fastener_hole("holes for M5", "pla", undersize_mm=0.35)
    assert found is not None and found[1] == pytest.approx(5.85)
