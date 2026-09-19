"""Planner contract (T-041): what goes in, what must come out, and the system prompt.

The model never emits geometry or code — only an OperationPlan in the v1
vocabulary (app/geometry/operations.py). Its raw output is parsed loosely
(`PlannerOutput`) and then validated strictly (validator.py); anything else is
a clarification or a rejection, never an invented kernel command.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.geometry.operations import OPERATION_TYPES, OperationPlan
from app.geometry.region import RegionSelection

CONTRACT_VERSION = "planner/v1"
TargetIntent = Literal["print", "game", "cad"]


class PlanRequest(BaseModel):
    """Everything the planner may know about the request (docs/03 §3)."""

    model_config = ConfigDict(frozen=True)

    prompt: str = Field(min_length=1, max_length=4000)
    units: Literal["mm"] = "mm"
    target: TargetIntent = "print"
    selection_entity_ids: list[str] = Field(default_factory=list)
    # The area the user outlined on the model, already in millimetres (T-102, F-062).
    region: RegionSelection | None = None
    current_operations: list[dict[str, Any]] = Field(default_factory=list)
    printer_context: dict[str, Any] = Field(default_factory=dict)
    client_capabilities: dict[str, Any] = Field(default_factory=dict)
    # Earlier (question, answer) rounds when the user answered a clarification.
    conversation: list[dict[str, str]] = Field(default_factory=list)
    # F-075: one of several constructive answers to the same request, by strategy.
    variant: Variant | None = None


class Variant(BaseModel):
    """Which of the N variants this plan is, and the constructive idea behind it."""

    model_config = ConfigDict(frozen=True)

    index: int = Field(ge=1)
    of: int = Field(ge=1, le=6)
    strategy: Literal["as_described", "rounded", "sturdier", "lower_profile"]


VARIANT_STRATEGIES: dict[str, tuple[str, str]] = {
    "as_described": ("As described", "Как описано"),
    "rounded": ("Rounded edges", "Со скруглёнными рёбрами"),
    "sturdier": ("Sturdier: thicker base", "Прочнее: толще основание"),
    "lower_profile": ("Lower profile", "Ниже профиль"),
}


class PlannerOutput(BaseModel):
    """Loose wire shape for the model's JSON. Structural only; numbers and references are
    checked by the strict validator so the model gets actionable feedback instead of a 400."""

    model_config = ConfigDict(extra="forbid")

    goal: str
    assumptions: list[str] = Field(default_factory=list)
    required_clarifications: list[str] = Field(default_factory=list)
    operations: list[dict[str, Any]] = Field(default_factory=list)
    validation_steps: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)


class Usage(BaseModel):
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    latency_ms: int = 0


class PlannerResult(BaseModel):
    """One provider call: the raw text, its loose parse (if any) and usage."""

    output: PlannerOutput | None
    raw_text: str
    usage: Usage
    refusal: str | None = None  # provider-side refusal (e.g. safety), user-safe text


# --- prompt -------------------------------------------------------------------------------

_RULES = """You are the planning layer of a CAD system for people who cannot use CAD.
Turn the user's intent into an OperationPlan (JSON) that a deterministic geometry kernel
executes. You never produce geometry, meshes or code yourself.

Rules:
1. Output only the JSON object. Every length is in millimetres (fields end with `_mm`),
   every angle in degrees. Convert cm/inch/m from the prompt to mm and say so in `assumptions`.
2. Use only the operation types listed in the vocabulary. If the request needs anything
   else (organic shapes, text, threads, patterns you cannot build from the vocabulary),
   do not invent an operation: put a precise question or the limitation into
   `required_clarifications` and leave `operations` empty.
3. When a dimension you need is missing or ambiguous, ask instead of guessing. One
   clarification per missing fact, phrased in the language of the prompt. You may assume
   obvious defaults (wall thickness 2 mm, floor 3 mm, M-hole clearances) — list every
   assumption in `assumptions`.
4. Every operation has a unique snake_case `id`. A create_box / create_cylinder / extrude
   creates a body named after its id; later operations reference bodies by that name.
   Booleans consume their `tool` body.
5. The plan is replayed from scratch: when `current_operations` are given, return the
   complete new list (keep earlier operations, append or edit — use `set_parameter` to
   change a number of an earlier operation instead of duplicating it).
6. Faces and edges are selected by geometric selectors only (face_by_normal, all_faces,
   all_edges, edges_parallel_to, edges_of_face).
7. `validation_steps` are short checks a human could verify (bounding box, wall thickness,
   holes through). `expected_outputs` lists the body ids that form the result.
8. If the request is not about a physical object you can build (or is unsafe), respond with
   a single required_clarification explaining that, and no operations.
"""


def operation_vocabulary() -> str:
    """Compact, stable description of the v1 vocabulary derived from the schema."""
    schema = OperationPlan.model_json_schema()
    defs = schema.get("$defs", {})
    lines: list[str] = []
    for name in OPERATION_TYPES:
        cls = next(
            (
                d
                for d in defs.values()
                if d.get("properties", {}).get("type", {}).get("const") == name
            ),
            None,
        )
        if cls is None:
            continue
        fields = []
        for field in cls["properties"]:
            if field in ("id", "type", "schema_version"):
                continue
            required = field in cls.get("required", [])
            fields.append(f"{field}{'' if required else '?'}")
        doc = (cls.get("description") or "").strip().split("\n")[0]
        lines.append(f"- {name}: {', '.join(fields)}" + (f" — {doc}" if doc else ""))
    selectors = (
        "Selectors: face {kind: face_by_normal, axis: x|y|z, sign: +|-} | {kind: all_faces}; "
        "edges {kind: all_edges} | {kind: edges_parallel_to, axis} | {kind: edges_of_face, face}. "
        "Profiles: {kind: rectangle, width_mm, depth_mm} | {kind: circle, diameter_mm} | "
        "{kind: polygon, points_mm: [[x, y], ...]}."
    )
    return (
        "Operation vocabulary (v1, schema_version 1 on every operation):\n"
        + "\n".join(lines)
        + "\n"
        + selectors
    )


_EXAMPLE_PLAN = {
    "goal": "Box 40x20x8 mm with a 5 mm through hole",
    "assumptions": ["Units are millimetres", "Hole is centred on the top face"],
    "required_clarifications": [],
    "operations": [
        {
            "id": "body",
            "type": "create_box",
            "schema_version": 1,
            "width_mm": 40,
            "depth_mm": 20,
            "height_mm": 8,
        },
        {
            "id": "hole",
            "type": "add_hole",
            "schema_version": 1,
            "target": "body",
            "face": {"kind": "face_by_normal", "axis": "z", "sign": "+"},
            "position_mm": [20, 10],
            "diameter_mm": 5,
        },
    ],
    "validation_steps": ["bounding box is 40 x 20 x 8 mm", "hole goes through"],
    "expected_outputs": ["body"],
}


def smart_size_rules() -> str:
    """Sizes that mean something (F-025), from the engineering knowledge base.

    Deterministic text, so the prompt stays cacheable: the same tables the rule planner
    and the engineering assistant use, in one place.
    """
    from app.engineering import knowledge as kb

    screws = "; ".join(
        f"{f.name}: pass-through {kb.hole_for(f, 'clearance', None):g}, "
        f"thread-forming {kb.hole_for(f, 'tap', None):g}, "
        f"heat-set insert {kb.hole_for(f, 'heat_set', None):g}"
        for f in kb.FASTENERS.values()
    )
    fits = ", ".join(f"{fit} {kb.FIT_ALLOWANCE_MM[fit]:+g}" for fit in kb.FITS)
    return (
        "Smart dimensions (a size named by what it is for):\n"
        f"- Holes for screws, modelled diameter in mm for PLA ({screws}). Other materials "
        "print holes smaller: add 0.1 mm for PETG/ABS/ASA and 0.2 mm for TPU.\n"
        f"- Fit allowances on a nominal size, mm ({fits}); a pipe or rod gets its diameter "
        "plus the sliding allowance as a round cut-out.\n"
        "- 'Add X mm of tolerance/clearance' changes only the openings that decide the "
        "fit (set_parameter on their diameter_mm), never the whole model.\n"
        "- An object the part must hold (a phone, a battery, a card, a board) sets the "
        "cavity: its size plus the sliding allowance, plus its case when one is mentioned; "
        "if the model of the object is not given, ask which one.\n"
    )


def system_prompt() -> str:
    """Stable text (no timestamps/ids) so it can be prompt-cached across requests."""
    return (
        _RULES
        + "\n"
        + smart_size_rules()
        + "\n"
        + operation_vocabulary()
        + "\n\nExample output:\n"
        + json.dumps(_EXAMPLE_PLAN, ensure_ascii=False, indent=1)
    )


def user_message(request: PlanRequest) -> str:
    parts = [f"Target: {request.target}. Units: {request.units}."]
    if request.current_operations:
        parts.append(
            "current_operations (replay these, then apply the change):\n"
            + json.dumps(request.current_operations, ensure_ascii=False)
        )
    if request.selection_entity_ids:
        parts.append("Selected entities: " + ", ".join(request.selection_entity_ids))
    if request.region is not None:
        parts.append(request.region.describe())
    if request.printer_context:
        parts.append("Printer/material context: " + json.dumps(request.printer_context))
    for round_ in request.conversation:
        parts.append(f"Earlier question: {round_.get('question', '')}")
        parts.append(f"User answer: {round_.get('answer', '')}")
    if request.variant is not None:
        idea = VARIANT_STRATEGIES[request.variant.strategy][0]
        parts.append(
            f"Variant {request.variant.index} of {request.variant.of}: {idea}. Give a distinct "
            "constructive answer along that line; keep the request's sizes and purpose."
        )
    parts.append("Request: " + request.prompt.strip())
    return "\n\n".join(parts)
