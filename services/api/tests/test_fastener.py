"""Reference 66: a fastener is a real bounded CAD solid, not a label on a hole."""

import pytest

from app.engineering.fastener import envelope, plan_for


def test_socket_fastener_plan_has_a_nominal_shank_and_fused_head() -> None:
    spec = envelope(size="M3", length_mm=12, head="socket_cap", drive="hex")
    plan = plan_for(spec)

    assert spec.metadata() == {
        "schema_version": 1,
        "size": "M3",
        "nominal_mm": 3.0,
        "length_mm": 12,
        "head": "socket_cap",
        "drive": "hex",
        "head_diameter_mm": 5.5,
        "head_height_mm": 3.0,
        "thread_geometry": "smooth_nominal_envelope",
        "drive_recess_modeled": False,
        "geometry_reference": "head_seat_z0",
    }
    assert [operation.type for operation in plan.operations] == [
        "create_cylinder",
        "create_cylinder",
        "boolean",
    ]
    shank, head, join = plan.operations
    assert shank.diameter_mm == 3.0 and shank.origin_mm == (0.0, 0.0, -12.0)
    assert shank.height_mm == pytest.approx(12.1)
    assert head.diameter_mm == 5.5 and head.origin_mm == (0.0, 0.0, 0.0)
    assert join.op == "fuse" and join.target == "shank" and join.tool == "head"
    assert plan.expected_outputs == ["shank"]


def test_countersunk_head_is_an_explicit_conical_envelope() -> None:
    plan = plan_for(envelope(size="m4", length_mm=16, head="countersunk", drive="phillips"))
    head = plan.operations[1]
    assert head.type == "create_cone"
    assert head.bottom_diameter_mm == 4
    assert head.top_diameter_mm == 8
    assert head.height_mm == 2


@pytest.mark.parametrize("size", ["M1", "M10", "wood screw"])
def test_unknown_sizes_fail_closed(size: str) -> None:
    with pytest.raises(ValueError, match="unknown metric fastener"):
        envelope(size=size, length_mm=12, head="pan", drive="torx")
