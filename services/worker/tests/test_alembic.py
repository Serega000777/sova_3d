"""F-014/F-015: Alembic Ogawa static PolyMesh import/export without a native SDK."""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest
import trimesh

from tests import fixtures
from worker import exporters, sandbox
from worker.importers import alembic
from worker.importers.child import parse
from worker.integrity import CheckStatus

FAST = sandbox.SandboxLimits(wall_seconds=90, isolate_network=False)
REAL_FILE = Path(__file__).parent / "fixtures" / "blender_static_mesh.abc"


def _size(path: Path) -> tuple[float, float, float]:
    metadata = parse("abc", path)
    assert metadata.bbox is not None
    size = metadata.bbox.size
    return round(size[0], 3), round(size[1], 3), round(size[2], 3)


def _uv(mesh: trimesh.Trimesh) -> np.ndarray:
    uv = getattr(mesh.visual, "uv", None)
    assert uv is not None
    return np.asarray(uv)


def test_a_real_blender_ogawa_file_reads_mesh_transform_normals_and_uvs() -> None:
    """Blender 4.5.3 wrote this fixture through its native Alembic C++ integration."""
    mesh = alembic.load_mesh(REAL_FILE)
    np.testing.assert_allclose(mesh.bounds, [[1.0, 2.0, 4.5], [5.0, 6.0, 5.5]])
    assert len(mesh.faces) == 12
    topology = trimesh.Trimesh(vertices=mesh.vertices, faces=mesh.faces, process=True)
    assert topology.is_watertight and topology.volume == pytest.approx(16.0)
    assert mesh.vertex_normals.shape == (24, 3)
    assert _uv(mesh).shape == (24, 2)

    metadata = parse("abc", REAL_FILE)
    assert metadata.mesh is not None and metadata.mesh.watertight
    assert metadata.mesh.vertices == 8  # UV seam duplicates do not change topology diagnostics
    assert metadata.mesh.volume_mm3 == pytest.approx(16.0)
    assert metadata.unit_source == "assumed" and metadata.scale_to_mm == 1.0


def test_export_roundtrips_through_the_sandbox(tmp_path: Path) -> None:
    source = fixtures.write_stl_binary(tmp_path / "box.stl")
    output = tmp_path / "box.abc"
    outcome = exporters.export_mesh(source, "stl", "abc", output, limits=FAST)
    assert outcome.ok, outcome
    assert outcome.report is not None and outcome.report.status is CheckStatus.warned
    assert output.read_bytes().startswith(b"Ogawa\xff\x00\x01")
    assert _size(output) == tuple(fixtures.BOX_MM)
    back = alembic.load_mesh(output)
    assert back.is_watertight and back.volume == pytest.approx(np.prod(fixtures.BOX_MM))


def test_uvs_and_normals_survive_the_ogawa_subset_roundtrip(tmp_path: Path) -> None:
    mesh = trimesh.creation.box(extents=(20.0, 10.0, 4.0))
    mesh.visual = trimesh.visual.TextureVisuals(  # type: ignore[no-untyped-call]
        uv=np.column_stack(
            (np.linspace(0.0, 1.0, len(mesh.vertices)), np.zeros(len(mesh.vertices)))
        )
    )
    output = tmp_path / "attributes.abc"
    alembic.write_alembic(mesh, output)
    back = alembic.load_mesh(output)
    np.testing.assert_allclose(back.bounds, mesh.bounds, atol=1e-6)
    source_order = np.lexsort(mesh.vertices.T)
    back_order = np.lexsort(back.vertices.T)
    np.testing.assert_allclose(back.vertices[back_order], mesh.vertices[source_order], atol=1e-6)
    np.testing.assert_allclose(
        _uv(back)[back_order], _uv(mesh)[source_order], atol=1e-6
    )
    np.testing.assert_allclose(
        back.vertex_normals[back_order], mesh.vertex_normals[source_order], atol=1e-6
    )


def test_invalid_magic_truncation_and_declared_size_mismatch_are_refused(tmp_path: Path) -> None:
    bad_magic = tmp_path / "magic.abc"
    bad_magic.write_bytes(b"not an Alembic file")
    with pytest.raises(ValueError, match="invalid magic"):
        parse("abc", bad_magic)

    good = REAL_FILE.read_bytes()
    truncated = tmp_path / "truncated.abc"
    truncated.write_bytes(good[: len(good) // 2])
    with pytest.raises(ValueError, match="past the end|exceeds the file|truncated"):
        parse("abc", truncated)

    mismatch = bytearray(good)
    (root_address,) = struct.unpack_from("<Q", mismatch, 8)
    root_children = struct.unpack_from("<6Q", mismatch, root_address + 8)
    time_sampling_address = root_children[4] & alembic.ADDRESS_MASK
    struct.pack_into("<Q", mismatch, time_sampling_address, len(mismatch) + 1)
    wrong_size = tmp_path / "wrong-size.abc"
    wrong_size.write_bytes(mismatch)
    with pytest.raises(ValueError, match="declared size exceeds"):
        parse("abc", wrong_size)


def test_unfinalized_and_hdf5_archives_are_refused(tmp_path: Path) -> None:
    unfinalized = bytearray(REAL_FILE.read_bytes())
    unfinalized[5] = 0
    path = tmp_path / "unfinalized.abc"
    path.write_bytes(unfinalized)
    with pytest.raises(ValueError, match="not finalized"):
        parse("abc", path)

    hdf5 = tmp_path / "legacy.abc"
    hdf5.write_bytes(alembic.HDF5_MAGIC + b"legacy")
    with pytest.raises(ValueError, match="HDF5 Alembic is not supported"):
        parse("abc", hdf5)
