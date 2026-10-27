"""Deterministic PDF document for one persisted immutable-version integrity report."""

from __future__ import annotations

import json
import textwrap
import uuid
from datetime import datetime
from typing import Any

from app.services.marketplace_documents import PAGE_HEIGHT, _build_pdf, _line, _text


def _display(value: object) -> str:
    if value is None:
        return "not reported"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return str(value)


def _wrapped(rows: list[str], *, x: float, y: float, value: object, size: float = 8.0) -> float:
    for line in textwrap.wrap(_display(value), width=102, break_long_words=True) or [""]:
        rows.append(_text(x, y, line, size))
        y -= 12
    return y


def _new_page(title: str, subtitle: str) -> tuple[list[str], float]:
    rows = [
        "0 G 0 g",
        _text(48, 800, title, 18),
        _text(48, 780, subtitle, 9),
        _line(48, 768, 547, 768, 0.7),
        _text(
            48,
            28,
            "Generated from a persisted Sova 3D integrity job; not a signed certificate.",
            7,
        ),
    ]
    return rows, PAGE_HEIGHT - 108


def render_integrity_pdf(
    *,
    project_name: str,
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    sequence_no: int,
    job_id: uuid.UUID,
    checked_at: datetime,
    report: dict[str, Any],
) -> bytes:
    """Render stable report facts and every canonical check into a small vector PDF."""
    pages: list[str] = []
    rows, y = _new_page("Sova 3D Integrity Report", "Immutable model conversion evidence")
    facts = (
        ("Project", project_name),
        ("Project ID", project_id),
        ("Immutable version", f"v{sequence_no} | {version_id}"),
        ("Integrity job", job_id),
        ("Checked at", checked_at.isoformat()),
        ("Result", str(report.get("status", "unknown")).upper()),
        (
            "Conversion",
            f"{str(report.get('source_format', 'unknown')).upper()} -> "
            f"{str(report.get('target_format', 'unknown')).upper()}",
        ),
    )
    for label, value in facts:
        rows.append(_text(58, y, label, 9))
        y = _wrapped(rows, x=190, y=y, value=value, size=9)
        y -= 10

    raw_output = report.get("output")
    output: dict[str, Any] = raw_output if isinstance(raw_output, dict) else {}
    rows.extend((_text(58, y - 4, "Measured output", 12), _line(58, y - 12, 537, y - 12, 0.4)))
    y -= 34
    for label, key in (
        ("Dimensions (mm)", "bbox_size_mm"),
        ("Faces", "faces"),
        ("Vertices", "vertices"),
        ("Watertight", "watertight"),
        ("Materials", "material_count"),
        ("Textures", "texture_count"),
        ("Scene nodes", "node_count"),
        ("Scene meshes", "mesh_count"),
        ("Animations", "animation_count"),
    ):
        rows.append(_text(68, y, label, 8))
        rows.append(_text(220, y, _display(output.get(key)), 8))
        y -= 17

    summary = report.get("summary", "No summary was recorded.")
    rows.extend((_text(58, y - 4, "Summary", 12), _line(58, y - 12, 537, y - 12, 0.4)))
    y = _wrapped(rows, x=68, y=y - 32, value=summary, size=8)
    rows.append(
        _text(
            68,
            y - 10,
            "This validates file conversion, not strength, safety, or regulatory compliance.",
            8,
        )
    )
    pages.append("\n".join(rows))

    raw_checks = report.get("checks")
    checks: list[Any] = raw_checks if isinstance(raw_checks, list) else []
    rows, y = _new_page("Canonical checks", f"{len(checks)} checks from integrity job {job_id}")
    for index, check in enumerate(checks, start=1):
        if not isinstance(check, dict):
            continue
        message_lines = textwrap.wrap(_display(check.get("message", "")), width=94) or [""]
        needed = 49 + max(0, len(message_lines) - 1) * 12
        if y - needed < 55:
            pages.append("\n".join(rows))
            rows, y = _new_page("Canonical checks (continued)", f"Integrity job {job_id}")
        status = str(check.get("status", "unknown")).upper()
        rows.append(_text(58, y, f"{index}. [{status}] {_display(check.get('id', 'unnamed'))}", 10))
        y -= 15
        for line in message_lines:
            rows.append(_text(68, y, line, 8))
            y -= 12
        rows.append(
            _text(
                68,
                y,
                f"Expected: {_display(check.get('expected'))} | "
                f"Actual: {_display(check.get('actual'))}",
                7,
            )
        )
        y -= 22
    pages.append("\n".join(rows))
    return _build_pdf(pages)
