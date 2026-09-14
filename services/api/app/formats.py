"""Format capability registry (T-016).

Single source of truth for what the platform accepts, what it can emit, and
the hard limits enforced before any untrusted file reaches a parser. Extend
the registry when a converter lands; never let an endpoint accept a format
that is not listed here.
"""

import enum
from dataclasses import dataclass
from types import MappingProxyType

MB = 1024 * 1024


class Representation(enum.StrEnum):
    mesh = "mesh"
    brep = "brep"
    scene = "scene"


class Capability(enum.StrEnum):
    import_ = "import"
    export = "export"
    print_ready = "print_ready"


@dataclass(frozen=True, slots=True)
class FormatSpec:
    id: str
    display_name: str
    extensions: tuple[str, ...]
    mime_types: tuple[str, ...]
    representation: Representation
    capabilities: frozenset[Capability]
    max_bytes: int
    # Magic-byte prefixes for detection; empty means "text, sniffed by content".
    magic: tuple[bytes, ...] = ()
    notes: str = ""

    @property
    def can_import(self) -> bool:
        return Capability.import_ in self.capabilities

    @property
    def can_export(self) -> bool:
        return Capability.export in self.capabilities


_IMPORT_ONLY = frozenset({Capability.import_})
_ROUNDTRIP = frozenset({Capability.import_, Capability.export})
_PRINT = frozenset({Capability.import_, Capability.export, Capability.print_ready})

_FORMATS: tuple[FormatSpec, ...] = (
    FormatSpec(
        id="stl",
        display_name="STL",
        extensions=("stl",),
        mime_types=("model/stl", "application/sla", "application/vnd.ms-pki.stl"),
        representation=Representation.mesh,
        capabilities=_PRINT,
        max_bytes=200 * MB,
        notes="Binary or ASCII; no units, mm assumed unless the user says otherwise.",
    ),
    FormatSpec(
        id="obj",
        display_name="Wavefront OBJ",
        extensions=("obj",),
        mime_types=("model/obj", "text/plain"),
        representation=Representation.mesh,
        capabilities=_ROUNDTRIP,
        max_bytes=200 * MB,
        notes="Referenced .mtl/textures are ignored on upload; materials are metadata only.",
    ),
    FormatSpec(
        id="glb",
        display_name="glTF binary",
        extensions=("glb",),
        mime_types=("model/gltf-binary",),
        representation=Representation.scene,
        capabilities=_ROUNDTRIP,
        max_bytes=300 * MB,
        magic=(b"glTF",),
    ),
    FormatSpec(
        id="gltf",
        display_name="glTF JSON",
        extensions=("gltf",),
        mime_types=("model/gltf+json",),
        representation=Representation.scene,
        capabilities=_IMPORT_ONLY,
        max_bytes=50 * MB,
        notes="External buffers/images are not fetched; embedded (data:) only.",
    ),
    FormatSpec(
        id="3mf",
        display_name="3MF",
        extensions=("3mf",),
        mime_types=("model/3mf", "application/vnd.ms-package.3dmanufacturing-3dmodel+xml"),
        representation=Representation.mesh,
        capabilities=_PRINT,
        max_bytes=200 * MB,
        magic=(b"PK\x03\x04",),
        notes="ZIP container; archive-bomb and path-traversal defenses apply.",
    ),
    FormatSpec(
        id="step",
        display_name="STEP",
        extensions=("step", "stp"),
        mime_types=("model/step", "application/step", "application/x-step"),
        representation=Representation.brep,
        capabilities=_ROUNDTRIP,
        max_bytes=500 * MB,
        magic=(b"ISO-10303-21",),
        notes="Handled by the OCCT geometry service.",
    ),
    FormatSpec(
        id="iges",
        display_name="IGES",
        extensions=("iges", "igs"),
        mime_types=("model/iges", "application/iges"),
        representation=Representation.brep,
        capabilities=_IMPORT_ONLY,
        max_bytes=500 * MB,
        notes="Handled by the OCCT geometry service.",
    ),
    FormatSpec(
        id="brep",
        display_name="OCCT B-Rep",
        extensions=("brep",),
        mime_types=("model/x-occt-brep",),
        representation=Representation.brep,
        capabilities=frozenset(),
        max_bytes=200 * MB,
        magic=(b"DBRep_DrawableShape",),
        notes="Canonical parametric source written by the geometry kernel; internal only.",
    ),
    FormatSpec(
        id="ply",
        display_name="PLY",
        extensions=("ply",),
        mime_types=("model/ply", "application/x-ply"),
        representation=Representation.mesh,
        capabilities=_IMPORT_ONLY,
        max_bytes=300 * MB,
        magic=(b"ply\n", b"ply\r\n"),
        notes="Typical scan output; colours preserved as metadata.",
    ),
)

FORMATS: MappingProxyType[str, FormatSpec] = MappingProxyType({f.id: f for f in _FORMATS})
MAX_UPLOAD_BYTES = max(f.max_bytes for f in _FORMATS)

_BY_EXTENSION = {ext: spec for spec in _FORMATS for ext in spec.extensions}
_BY_MIME = {mime: spec for spec in _FORMATS for mime in spec.mime_types}


def by_extension(filename_or_ext: str) -> FormatSpec | None:
    ext = filename_or_ext.rsplit(".", 1)[-1].lower().lstrip(".")
    return _BY_EXTENSION.get(ext)


def by_mime(mime: str) -> FormatSpec | None:
    return _BY_MIME.get(mime.split(";")[0].strip().lower())


def sniff(head: bytes) -> FormatSpec | None:
    """Detect a format from leading bytes; only formats with magic bytes are detectable."""
    for spec in _FORMATS:
        if any(head.startswith(m) for m in spec.magic):
            return spec
    return None


def importable() -> list[FormatSpec]:
    return [f for f in _FORMATS if f.can_import]


def exportable() -> list[FormatSpec]:
    return [f for f in _FORMATS if f.can_export]
