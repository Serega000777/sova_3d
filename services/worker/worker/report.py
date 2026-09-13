"""Import metadata contract (T-018..T-021).

Everything is canonical millimetres. `unit_source` says whether the file
declared units (glTF spec, 3MF attribute) or the platform assumed mm.
Warnings mirror the geometry quality gates in docs/07: NaN/Inf coordinates,
zero extents, missing unit metadata, non-manifold hints.
"""

from __future__ import annotations

import enum
from typing import Literal

from pydantic import BaseModel, Field

Vec3 = tuple[float, float, float]


class Severity(enum.StrEnum):
    info = "info"
    warning = "warning"
    error = "error"


class Warning(BaseModel):  # noqa: A001 — domain name, shadows builtins.Warning on purpose
    code: str
    severity: Severity
    message: str
    details: dict[str, int | float | str | None] = Field(default_factory=dict)


class BBox(BaseModel):
    min: Vec3
    max: Vec3

    @property
    def size(self) -> Vec3:
        return (
            self.max[0] - self.min[0],
            self.max[1] - self.min[1],
            self.max[2] - self.min[2],
        )


class MeshStats(BaseModel):
    vertices: int
    faces: int
    bodies: int
    watertight: bool
    winding_consistent: bool
    volume_mm3: float | None = None
    surface_area_mm2: float
    euler_number: int
    degenerate_faces: int
    duplicate_faces: int


class SceneStats(BaseModel):
    nodes: int
    meshes: int
    materials: int
    textures: int
    animations: int
    cameras: int
    lights: int
    extensions_used: list[str] = Field(default_factory=list)


class ObjectStats(BaseModel):
    id: str
    name: str | None
    type: str
    vertices: int
    triangles: int


class BuildItem(BaseModel):
    object_id: str
    has_transform: bool


class ImportMetadata(BaseModel):
    format: str
    representation: Literal["mesh", "scene"]
    units: Literal["mm"] = "mm"
    unit_source: Literal["file", "assumed"]
    source_units: str | None = None
    scale_to_mm: float = 1.0
    bbox: BBox | None
    mesh: MeshStats | None = None
    scene: SceneStats | None = None
    objects: list[ObjectStats] = Field(default_factory=list)
    build_items: list[BuildItem] = Field(default_factory=list)
    material_refs: list[str] = Field(default_factory=list)
    file_metadata: dict[str, str] = Field(default_factory=dict)
    warnings: list[Warning] = Field(default_factory=list)
    parser: str

    @property
    def has_errors(self) -> bool:
        return any(w.severity is Severity.error for w in self.warnings)


class ImportFailure(BaseModel):
    code: str
    message: str


class ImportResult(BaseModel):
    ok: bool
    metadata: ImportMetadata | None = None
    error: ImportFailure | None = None
