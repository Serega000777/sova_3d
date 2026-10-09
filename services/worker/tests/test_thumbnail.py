import hashlib
import io
from pathlib import Path

import trimesh
from PIL import Image

from worker.thumbnail import HEIGHT, WIDTH, render_png


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
