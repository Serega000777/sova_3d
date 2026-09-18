"""T-092: what a conversion costs, written down.

Every format pair loses something. This suite converts the same fixtures through each
supported pair and asserts the loss stays inside a recorded threshold, so a library
upgrade that starts rounding vertices shows up here instead of in someone's print.
The thresholds are the contract: raising one is a decision, not a fix.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests import fixtures
from worker import exporters
from worker.importers.child import parse

THRESHOLDS_FILE = Path(__file__).with_name("conversion_thresholds.json")


@dataclass(frozen=True, slots=True)
class Drift:
    volume_pct: float
    area_pct: float
    bbox_mm: float


@dataclass(frozen=True, slots=True)
class Measured:
    """A model as the platform sees it: canonical millimetres, whatever the file said."""

    volume_mm3: float
    area_mm2: float
    size_mm: tuple[float, float, float]


def measure(path: Path, file_type: str) -> Measured:
    """Parse through the importer, so the file's own unit convention is applied.

    glTF is metres by spec and 3MF states its unit; comparing raw numbers across formats
    would measure the convention, not the conversion.
    """
    meta = parse(file_type, path)
    assert meta.bbox is not None, f"{file_type} round trip produced no geometry"
    assert meta.mesh is not None, f"{file_type} carries no mesh statistics to compare"
    volume = float(meta.mesh.volume_mm3 or 0.0)
    area = float(meta.mesh.surface_area_mm2 or 0.0)
    assert volume > 0, f"{file_type} round trip produced no volume (scale_to_mm={meta.scale_to_mm})"
    x, y, z = (float(v) for v in meta.bbox.size)
    return Measured(volume, area, (x, y, z))


def drift(before: Measured, after: Measured) -> Drift:
    volume = abs(after.volume_mm3 - before.volume_mm3) / max(before.volume_mm3, 1e-9)
    area = abs(after.area_mm2 - before.area_mm2) / max(before.area_mm2, 1e-9)
    bbox = max(abs(a - b) for a, b in zip(after.size_mm, before.size_mm, strict=True))
    return Drift(volume * 100, area * 100, bbox)


def thresholds() -> dict[str, dict[str, float]]:
    pairs: dict[str, dict[str, float]] = json.loads(THRESHOLDS_FILE.read_text(encoding="utf-8"))[
        "pairs"
    ]
    return pairs


@pytest.mark.parametrize("pair", sorted(thresholds()))
def test_conversion_drift_stays_inside_the_recorded_threshold(pair: str, tmp_path: Path) -> None:
    source_format, target_format = pair.split("->")
    limits = thresholds()[pair]

    source = tmp_path / f"source.{source_format}"
    mesh = fixtures.box()
    source.write_bytes(fixtures.export_bytes(mesh, source_format))
    before = measure(source, source_format)

    target = tmp_path / f"target.{target_format}"
    outcome = exporters.export_mesh(source, source_format, target_format, target)
    assert outcome.ok, outcome.error
    after = measure(target, target_format)

    observed = drift(before, after)
    assert observed.volume_pct <= limits["volume_pct"], (
        f"{pair}: volume drifted {observed.volume_pct:.4f}% (limit {limits['volume_pct']}%)"
    )
    assert observed.area_pct <= limits["area_pct"], (
        f"{pair}: area drifted {observed.area_pct:.4f}% (limit {limits['area_pct']}%)"
    )
    assert observed.bbox_mm <= limits["bbox_mm"], (
        f"{pair}: bounding box drifted {observed.bbox_mm:.6f} mm (limit {limits['bbox_mm']} mm)"
    )


def test_every_supported_pair_has_a_recorded_threshold() -> None:
    """A new exporter must come with its measured drift, not without one."""
    recorded = set(thresholds())
    expected = {
        f"{source}->{target}" for source in ("stl", "obj") for target in ("stl", "glb", "3mf")
    } | {"glb->stl", "3mf->stl"}
    assert expected <= recorded, f"missing thresholds for {sorted(expected - recorded)}"


def test_a_round_trip_through_glb_keeps_millimetres(tmp_path: Path) -> None:
    """glTF is metres by contract; the scale must come back exactly, not approximately."""
    source = tmp_path / "box.stl"
    source.write_bytes(fixtures.export_bytes(fixtures.box(), "stl"))
    middle = tmp_path / "box.glb"
    back = tmp_path / "back.stl"
    assert exporters.export_mesh(source, "stl", "glb", middle).ok
    assert exporters.export_mesh(middle, "glb", "stl", back).ok

    before, after = measure(source, "stl"), measure(back, "stl")
    assert after.size_mm == pytest.approx(before.size_mm, rel=1e-6)
