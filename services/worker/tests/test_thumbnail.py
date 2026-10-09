import hashlib
import io
from pathlib import Path

import trimesh
from PIL import Image

from worker.thumbnail import HEIGHT, WIDTH, ThumbnailAngle, render_png


def test_headless_thumbnail_is_a_deterministic_nonempty_png(tmp_path: Path) -> None:
    source = tmp_path / "box.stl"
    source.write_bytes(trimesh.creation.box(extents=(30, 20, 10)).export(file_type="stl"))

    first = render_png(source, "stl")
    second = render_png(source, "stl")

    assert first.startswith(b"\x89PNG\r\n\x1a\n")
    assert hashlib.sha256(first).digest() == hashlib.sha256(second).digest()
    image = Image.open(io.BytesIO(first))
    assert image.size == (WIDTH, HEIGHT)
    colours = image.getcolors(maxcolors=WIDTH * HEIGHT)
    assert colours is not None and len(colours) > 10


def test_fixed_thumbnail_angles_are_deterministic_and_distinct(tmp_path: Path) -> None:
    source = tmp_path / "asymmetric.stl"
    mesh = trimesh.creation.box(extents=(30, 20, 10))
    mesh.apply_translation((4, 0, 0))
    source.write_bytes(mesh.export(file_type="stl"))

    digests = {
        angle: hashlib.sha256(render_png(source, "stl", angle=angle)).hexdigest()
        for angle in ThumbnailAngle
    }

    assert set(digests) == set(ThumbnailAngle)
    assert len(set(digests.values())) == 3


def test_unknown_thumbnail_angle_fails_closed(tmp_path: Path) -> None:
    source = tmp_path / "box.stl"
    source.write_bytes(trimesh.creation.box().export(file_type="stl"))

    try:
        render_png(source, "stl", angle="rear")
    except ValueError as exc:
        assert "rear" in str(exc)
    else:  # pragma: no cover - an invalid angle must never reach the parser sandbox
        raise AssertionError("unknown thumbnail angle was accepted")
