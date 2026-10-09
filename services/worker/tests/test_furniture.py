import hashlib

import pytest
import trimesh

from worker.furniture import build_stl


@pytest.mark.parametrize("kind", ["chair", "table", "sofa", "bed", "cabinet"])
def test_catalogue_furniture_is_deterministic_real_scale_mesh(kind: str) -> None:
    first = build_stl(kind, 1200, 700, 800)  # type: ignore[arg-type]
    second = build_stl(kind, 1200, 700, 800)  # type: ignore[arg-type]
    assert hashlib.sha256(first).digest() == hashlib.sha256(second).digest()
    mesh = trimesh.load_mesh(trimesh.util.wrap_as_stream(first), file_type="stl", process=False)
    assert mesh.faces.shape[0] >= 24
    assert mesh.bounds[0][2] == pytest.approx(0)
    assert mesh.extents[0] == pytest.approx(1200)
    assert mesh.extents[1] == pytest.approx(700)
