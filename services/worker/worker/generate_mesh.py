"""Organic shapes from words (F-001/F-075): Shap-E's text model, CPU-only.

The parametric kernel builds what can be described with dimensions — brackets, boxes,
holders. A figurine, an animal or a vase with no measurements is a different kind of
object: this module asks Shap-E for one and gives it the platform's conventions (the
size the user asked for along the longest side, millimetres, standing on z = 0). It is
a learned guess at a shape, never a dimensioned part — the caller says so to the user.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from worker.reconstruction import ReconstructionError, run_shap_e

MAX_PROMPT_CHARS = 300
MIN_SIZE_MM = 5.0
MAX_SIZE_MM = 1000.0
_LATIN = re.compile(r"[A-Za-z]")
_OTHER_LETTER = re.compile(r"[^\W\d_A-Za-z]")


@dataclass(frozen=True, slots=True)
class GeneratedMesh:
    mesh_path: Path
    prompt: str
    size_mm: float
    vertices: int
    faces: int
    warnings: tuple[str, ...]


def clean_prompt(prompt: str) -> str:
    """One line, trimmed; refuses what the model cannot use."""
    text = " ".join(prompt.split())
    if not text:
        raise ReconstructionError("empty_prompt", "describe the shape to generate")
    if len(text) > MAX_PROMPT_CHARS:
        raise ReconstructionError(
            "prompt_too_long", f"keep the description under {MAX_PROMPT_CHARS} characters"
        )
    return text


def prompt_warnings(prompt: str) -> tuple[str, ...]:
    """Shap-E's text encoder was trained on English captions; say so rather than hide it."""
    if _OTHER_LETTER.search(prompt) and not _LATIN.search(prompt):
        return (
            "Shap-E understands English descriptions; a prompt in another language gives an "
            "unpredictable shape.",
        )
    return ()


def generate_from_text(prompt: str, size_mm: float, out_dir: Path) -> GeneratedMesh:
    text = clean_prompt(prompt)
    if not MIN_SIZE_MM <= size_mm <= MAX_SIZE_MM:
        raise ReconstructionError(
            "size_out_of_range", f"size must be {MIN_SIZE_MM:g}-{MAX_SIZE_MM:g} mm"
        )
    raw, result = run_shap_e("text", text, out_dir)
    raw.apply_scale(size_mm / float(raw.extents.max()))
    raw.apply_translation(-raw.bounds[0])  # sit on z = 0 like every other model
    out_dir.mkdir(parents=True, exist_ok=True)
    mesh_path = out_dir / "generated.stl"
    raw.export(mesh_path)
    return GeneratedMesh(
        mesh_path=mesh_path,
        prompt=text,
        size_mm=size_mm,
        vertices=int(result.get("vertices", len(raw.vertices))),
        faces=int(result.get("faces", len(raw.faces))),
        warnings=prompt_warnings(text),
    )
