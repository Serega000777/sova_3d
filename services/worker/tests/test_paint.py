"""F-034 / Reference 77: deterministic face-colour painting."""

from __future__ import annotations

import numpy as np
import pytest
import trimesh
from pydantic import ValidationError

from worker import paint


def test_stroke_opacity_blends_in_order_and_keeps_the_preview_opaque() -> None:
    mesh = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
    request = paint.PaintRequest(
        base_colour="#000000",
        strokes=[
            paint.Stroke(colour="#ff0000", opacity=0.5),
            paint.Stroke(colour="#0000ff", opacity=0.5),
        ],
    )

    result, painted = paint.paint_mesh_into(mesh, request)

    assert result.ok and result.painted_faces == len(painted.faces)
    expected = np.tile(np.array([64, 0, 128, 255], dtype=np.uint8), (len(painted.faces), 1))
    assert isinstance(painted.visual, trimesh.visual.ColorVisuals)
    np.testing.assert_array_equal(painted.visual.face_colors, expected)


@pytest.mark.parametrize("opacity", [0, 0.049, 1.001])
def test_stroke_opacity_is_bounded(opacity: float) -> None:
    with pytest.raises(ValidationError):
        paint.Stroke(colour="#ff0000", opacity=opacity)
