"""F-056: a print report becomes bounded, settling corrections for that printer and material."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.services.print_diagnosis import (
    DEFAULTS,
    LIMITS,
    RULES,
    PrintReport,
    diagnose,
    tuning_of,
)


def _report(*symptoms: str, material: str = "pla") -> PrintReport:
    return PrintReport.model_validate(
        {"material_id": material, "outcome": "partial", "symptoms": list(symptoms)}
    )


def _history(material: str, setting: str, before: float, after: float) -> list[dict[str, Any]]:
    return [
        {
            "material_id": material,
            "changes": [{"setting": setting, "before": before, "after": after}],
        }
    ]


def test_stringing_retracts_more_and_prints_cooler() -> None:
    findings, tuning = diagnose(_report("stringing"), dict(DEFAULTS), [])
    assert tuning["retraction_mm"] == pytest.approx(1.7)
    assert tuning["nozzle_offset_c"] == -5.0
    (finding,) = findings
    assert {c.setting for c in finding.changes} == {"retraction_mm", "nozzle_offset_c"}
    assert finding.causes and finding.advice


def test_repeated_reports_keep_moving_but_never_past_the_limits() -> None:
    tuning = dict(DEFAULTS)
    for _ in range(20):
        _, tuning = diagnose(_report("stringing"), tuning, [])
    assert tuning["retraction_mm"] == LIMITS["retraction_mm"][1]
    assert tuning["nozzle_offset_c"] == LIMITS["nozzle_offset_c"][0]


def test_a_contradicting_report_moves_half_as_far() -> None:
    current = {**DEFAULTS, "flow_pct": 104.0}
    history = _history("pla", "flow_pct", 100.0, 104.0)  # last time: more flow
    _, tuning = diagnose(_report("over_extrusion"), current, history)
    assert tuning["flow_pct"] == pytest.approx(102.0)  # -4 halved
    # another material's history does not damp this one
    _, other = diagnose(_report("over_extrusion", material="petg"), current, history)
    assert other["flow_pct"] == pytest.approx(100.0)


def test_the_first_brim_is_worth_having() -> None:
    _, tuning = diagnose(_report("warping"), dict(DEFAULTS), [])
    assert tuning["brim_mm"] == 5.0 and tuning["bed_offset_c"] == 5.0


def test_mechanical_symptoms_change_nothing_and_say_what_to_check() -> None:
    findings, tuning = diagnose(
        _report("layer_shift", "clogging", "dimensions_off"), dict(DEFAULTS), []
    )
    assert tuning == DEFAULTS
    assert all(not f.changes and f.advice for f in findings)
    assert "coupon" in next(f.advice for f in findings if f.symptom == "dimensions_off")


def test_stored_tuning_is_clamped_and_garbage_ignored() -> None:
    class Profile:
        calibration = {
            "tuning": {"pla": {"flow_pct": 400, "retraction_mm": "lots", "brim_mm": True, "x": 1}}
        }

    tuning = tuning_of(Profile(), "pla")  # type: ignore[arg-type]
    assert tuning["flow_pct"] == LIMITS["flow_pct"][1]
    assert tuning["retraction_mm"] == DEFAULTS["retraction_mm"] and tuning["brim_mm"] == 0.0
    assert "x" not in tuning and tuning_of(None, "pla") == DEFAULTS


def test_reports_are_validated() -> None:
    with pytest.raises(ValidationError):
        PrintReport.model_validate({"outcome": "meh"})
    with pytest.raises(ValidationError):
        PrintReport.model_validate({"outcome": "failed", "symptoms": ["gremlins"]})
    deduped = PrintReport.model_validate({"outcome": "failed", "symptoms": ["warping", "warping"]})
    assert deduped.symptoms == ["warping"]


def test_every_rule_names_a_known_setting_and_the_worker_agrees_on_the_bounds() -> None:
    assert {s for rule in RULES.values() for s in rule.steps} <= set(LIMITS)
    gcode = pytest.importorskip("worker.gcode")
    fields = gcode.PrintTuning.model_fields
    assert set(fields) == set(DEFAULTS)
    for name, default in DEFAULTS.items():
        assert fields[name].default == default
        low, high = LIMITS[name]
        gcode.PrintTuning(**{name: low})  # inside the worker's own hard limits
        gcode.PrintTuning(**{name: high})
