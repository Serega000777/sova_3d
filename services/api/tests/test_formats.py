"""T-016: format capability registry."""

from fastapi.testclient import TestClient

from app import formats
from app.formats import Capability, Representation


def test_lookup_by_extension_is_case_insensitive_and_accepts_filenames() -> None:
    assert formats.by_extension("part.STP") is formats.FORMATS["step"]
    assert formats.by_extension(".stl") is formats.FORMATS["stl"]
    assert formats.by_extension("archive.tar.gz") is None


def test_lookup_by_mime_ignores_parameters() -> None:
    assert formats.by_mime("model/gltf-binary; charset=binary") is formats.FORMATS["glb"]
    assert formats.by_mime("image/png") is formats.FORMATS["png"]  # a scan frame, not a model
    assert formats.by_mime("application/zip") is None


def test_sniff_detects_magic_bytes_only() -> None:
    assert formats.sniff(b"glTF\x02\x00\x00\x00") is formats.FORMATS["glb"]
    assert formats.sniff(b"PK\x03\x04rest") is formats.FORMATS["3mf"]
    assert formats.sniff(b"ISO-10303-21;\nHEADER;") is formats.FORMATS["step"]
    assert formats.sniff(b"solid cube") is None  # STL has no magic


def test_capabilities_are_consistent() -> None:
    for spec in formats.FORMATS.values():
        assert spec.max_bytes > 0 and spec.extensions and spec.mime_types
        if Capability.print_ready in spec.capabilities:
            assert spec.can_export and spec.representation is Representation.mesh
    assert {f.id for f in formats.importable()} >= {"stl", "obj", "glb", "3mf", "step"}
    assert {f.id for f in formats.exportable()} == {"stl", "obj", "glb", "3mf", "step"}
    # Scan frames are uploadable images, never handed to a 3D parser (E9).
    assert {f.id for f in formats.scan_frames()} == {"jpeg", "png"}
    for spec in formats.scan_frames():
        assert spec.representation is Representation.image
        assert not spec.can_import and not spec.can_export


def test_formats_endpoint_returns_limits(client: TestClient) -> None:
    response = client.get("/api/v1/formats")
    assert response.status_code == 200
    body = response.json()
    assert body["max_upload_bytes"] == formats.MAX_UPLOAD_BYTES
    stl = next(f for f in body["formats"] if f["id"] == "stl")
    assert stl["max_bytes"] == 200 * formats.MB
    assert set(stl["capabilities"]) == {"import", "export", "print_ready"}
