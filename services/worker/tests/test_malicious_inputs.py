"""T-091: every uploaded file is hostile until parsed.

One corpus, one rule: a malicious or malformed file produces a typed refusal, never a
crash, never a read outside the sandbox, never unbounded memory. Each case names the
attack it stands for so a future parser change cannot quietly drop a defense.
"""

from __future__ import annotations

import io
import struct
import zipfile
from pathlib import Path

import pytest

from tests import fixtures
from worker import importers, sandbox
from worker.importers.zipsafe import DEFAULT_ARCHIVE_LIMITS, UnsafeArchiveError, validate_zip

FAST = sandbox.SandboxLimits(wall_seconds=60, isolate_network=False)


# --- archive attacks ---------------------------------------------------------------------


def write_zip(path: Path, entries: dict[str, bytes], *, compress: bool = False) -> Path:
    buffer = io.BytesIO()
    mode = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
    with zipfile.ZipFile(buffer, "w", mode) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    path.write_bytes(buffer.getvalue())
    return path


def test_absolute_paths_and_drive_letters_are_refused(tmp_path: Path) -> None:
    for name in ("/etc/passwd", "C:/windows/system32/evil.dll", "\\\\server\\share\\x"):
        archive = write_zip(tmp_path / "abs.3mf", {name: b"x"})
        with pytest.raises(UnsafeArchiveError):
            validate_zip(archive)


def test_traversal_hidden_in_backslashes_is_refused(tmp_path: Path) -> None:
    archive = write_zip(tmp_path / "back.3mf", {"3D\\..\\..\\evil.model": b"x"})
    with pytest.raises(UnsafeArchiveError, match="traversal"):
        validate_zip(archive)


def test_absurd_entry_names_are_refused(tmp_path: Path) -> None:
    archive = write_zip(tmp_path / "long.3mf", {"a" * 600 + ".model": b"x"})
    with pytest.raises(UnsafeArchiveError, match="name too long"):
        validate_zip(archive)


def test_too_many_entries_are_refused(tmp_path: Path) -> None:
    entries = {f"3D/part_{i}.model": b"x" for i in range(DEFAULT_ARCHIVE_LIMITS.max_entries + 1)}
    archive = write_zip(tmp_path / "many.3mf", entries)
    with pytest.raises(UnsafeArchiveError, match="too many entries"):
        validate_zip(archive)


def test_a_lying_header_is_refused(tmp_path: Path) -> None:
    """Entry claims megabytes but stores nothing — the classic zip-bomb header trick."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("3D/3dmodel.model", b"")
    raw = bytearray(buffer.getvalue())
    # Forge the uncompressed size in the central directory.
    index = raw.rfind(b"PK\x01\x02")
    struct.pack_into("<I", raw, index + 24, 900 * 1024 * 1024)
    path = tmp_path / "lying.3mf"
    path.write_bytes(bytes(raw))
    with pytest.raises(UnsafeArchiveError):
        validate_zip(path)


def test_a_truncated_container_is_refused_not_crashed(tmp_path: Path) -> None:
    good = fixtures.write_3mf(tmp_path / "good.3mf")
    broken = tmp_path / "broken.3mf"
    broken.write_bytes(good.read_bytes()[: len(good.read_bytes()) // 2])
    with pytest.raises(UnsafeArchiveError, match="not a valid ZIP"):
        validate_zip(broken)


# --- mesh payload attacks ----------------------------------------------------------------


def test_stl_that_claims_more_triangles_than_it_has(tmp_path: Path) -> None:
    """A 12-byte file claiming four billion triangles must not allocate for them."""
    path = tmp_path / "liar.stl"
    path.write_bytes(b"\0" * 80 + struct.pack("<I", 4_000_000_000))
    result = importers.import_metadata(path, "stl", limits=FAST)
    assert not result.ok
    assert result.error is not None


def test_empty_file_never_passes_as_geometry(tmp_path: Path) -> None:
    """It may parse, but it must be reported as unusable rather than as an empty model."""
    path = tmp_path / "empty.stl"
    path.write_bytes(b"")
    result = importers.import_metadata(path, "stl", limits=FAST)
    if result.ok:
        assert result.metadata is not None
        errors = [w for w in result.metadata.warnings if w.severity == "error"]
        assert errors, "an empty file was accepted without an error-severity warning"
    else:
        assert result.error is not None


def test_format_confusion_is_caught(tmp_path: Path) -> None:
    """A ZIP renamed to .stl must not be parsed as a mesh."""
    path = tmp_path / "actually.zip.stl"
    path.write_bytes(fixtures.write_3mf(tmp_path / "real.3mf").read_bytes())
    result = importers.import_metadata(path, "stl", limits=FAST)
    assert not result.ok


def test_gltf_pointing_at_the_filesystem_is_not_fetched(tmp_path: Path) -> None:
    path = tmp_path / "external.gltf"
    path.write_text(
        '{"asset":{"version":"2.0"},"buffers":[{"uri":"file:///etc/passwd","byteLength":32}],'
        '"meshes":[],"nodes":[],"scenes":[{"nodes":[]}]}'
    )
    result = importers.import_metadata(path, "gltf", limits=FAST)
    # Either a refusal or a parse with no geometry — never a file read.
    if result.ok:
        assert result.metadata is not None
        assert "/etc/passwd" not in str(result.metadata.model_dump())


def test_xml_entity_expansion_is_refused(tmp_path: Path) -> None:
    """Billion laughs: entity expansion must never run."""
    xml = (
        b'<?xml version="1.0"?>'
        b"<!DOCTYPE model ["
        b'<!ENTITY a "aaaaaaaaaa">'
        b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
        b'<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">'
        b"]>"
        b'<model unit="millimeter" '
        b'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
        b'<metadata name="Title">&c;</metadata><resources/><build/></model>'
    )
    path = fixtures.write_3mf(tmp_path / "laughs.3mf", model_xml=xml)
    result = importers.import_metadata(path, "3mf", limits=FAST)
    assert not result.ok
    assert result.error is not None


# --- the sandbox itself ------------------------------------------------------------------


def test_a_hostile_file_fails_inside_the_sandbox_not_the_worker(tmp_path: Path) -> None:
    """Whatever the parser does with a bad file, the calling process survives it."""
    result = importers.import_metadata(
        fixtures.write_zip_bomb(tmp_path / "bomb.3mf"), "3mf", limits=FAST
    )
    assert not result.ok
    assert result.error is not None
    # And the worker is still able to parse a good file right afterwards.
    good = importers.import_metadata(
        fixtures.write_stl_binary(tmp_path / "box.stl"), "stl", limits=FAST
    )
    assert good.ok
