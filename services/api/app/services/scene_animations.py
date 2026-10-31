"""Trusted animation derived from immutable mechanism provenance."""

from __future__ import annotations

import math


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _joint_animation(
    mechanism: object,
    *,
    kind: str,
    joint_type: str,
    unit: str,
    axes: set[str],
    visible_ids: set[str],
) -> dict[str, object] | None:
    """Return one validated joint animation or fail closed for malformed provenance."""

    if not isinstance(mechanism, dict) or mechanism.get("kind") != kind:
        return None
    joint = mechanism.get("joint")
    if not isinstance(joint, dict) or joint.get("type") != joint_type:
        return None
    node_id = joint.get("node_id")
    axis = joint.get("axis")
    minimum = _finite(joint.get(f"min_{unit}", 0))
    maximum = _finite(joint.get(f"max_{unit}", 0))
    if (
        axis not in axes
        or not isinstance(node_id, str)
        or node_id not in visible_ids
        or minimum is None
        or maximum is None
        or maximum <= minimum
    ):
        return None
    return {
        "kind": joint_type,
        "node_id": node_id,
        "axis": axis,
        f"min_{unit}": minimum,
        f"max_{unit}": maximum,
        "duration_seconds": 1.0,
    }


def mechanism_animation(
    provenance: dict[str, object], visible_ids: set[str]
) -> dict[str, object] | None:
    """Resolve the single trusted mechanism joint used by preview and scene exports.

    A hidden or malformed joint yields no animation, and so does a scene carrying both a
    hinge and a sliding lid: one animation channel must never guess which mechanism is meant.
    """

    candidates = [
        _joint_animation(
            provenance.get("build_hinged_lid"),
            kind="hinged_lid",
            joint_type="revolute",
            unit="angle_deg",
            axes={"x"},
            visible_ids=visible_ids,
        ),
        _joint_animation(
            provenance.get("build_sliding_lid"),
            kind="sliding_lid",
            joint_type="prismatic",
            unit="travel_mm",
            axes={"y"},
            visible_ids=visible_ids,
        ),
    ]
    present = [key for key in ("build_hinged_lid", "build_sliding_lid") if key in provenance]
    valid = [candidate for candidate in candidates if candidate is not None]
    if len(present) != 1 or len(valid) != 1:
        return None
    animation = valid[0]
    clip = provenance.get("animation_clip")
    if clip is None:
        return animation
    if (
        not isinstance(clip, dict)
        or clip.get("schema_version") != 1
        or clip.get("kind") != "rigid_joint_clip"
        or clip.get("node_id") != animation["node_id"]
        or clip.get("joint_type") != animation["kind"]
    ):
        return None
    duration = _finite(clip.get("duration_seconds"))
    if duration is None or not 0.1 <= duration <= 60:
        return None
    return {**animation, "duration_seconds": duration}
