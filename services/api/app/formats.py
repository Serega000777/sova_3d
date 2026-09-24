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
    image = "image"
    toolpath = "toolpath"


class Capability(enum.StrEnum):
    import_ = "import"
    export = "export"
    print_ready = "print_ready"
    # Uploadable as a scan frame (E9) but never parsed as a model.
    scan_frame = "scan_frame"


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

    @property
    def is_scan_frame(self) -> bool:
        return Capability.scan_frame in self.capabilities


_IMPORT_ONLY = frozenset({Capability.import_})
_ROUNDTRIP = frozenset({Capability.import_, Capability.export})
_PRINT = frozenset({Capability.import_, Capability.export, Capability.print_ready})
_SCAN = frozenset({Capability.scan_frame})

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
        id="gcode",
        display_name="G-code",
        extensions=("gcode",),
        mime_types=("text/x-gcode", "text/plain"),
        representation=Representation.toolpath,
        # Not "exportable" in the formats.py sense (that means the generic mesh/CAD
        # writer at POST /exports can produce it — worker.exporters has no gcode target).
        # G-code comes only from POST /models/{v}/slice (F-054), never re-imported.
        capabilities=frozenset(),
        max_bytes=64 * MB,
        notes="Machine instructions from the real slicer (F-054): perimeters, infill and "
        "supports for one printer profile.",
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
        notes="External buffers/images are not fetched. Export glTF as GLB: one file, not many.",
    ),
    FormatSpec(
        id="dae",
        display_name="COLLADA",
        extensions=("dae",),
        mime_types=("model/vnd.collada+xml",),
        representation=Representation.scene,
        capabilities=_ROUNDTRIP,
        max_bytes=200 * MB,
        notes="Unit read from the file's own <asset><unit> (T-110 extension); a file with "
        "none is assumed metres per the COLLADA spec default.",
    ),
    FormatSpec(
        id="usdz",
        display_name="USDZ",
        extensions=("usdz",),
        mime_types=("model/vnd.usdz+zip",),
        representation=Representation.scene,
        capabilities=_ROUNDTRIP,
        max_bytes=200 * MB,
        # No magic: a USDZ is a plain ZIP (same b"PK\x03\x04" 3MF already claims), so it is
        # only ever told apart by its .usdz extension, never sniffed from content.
        notes="Apple's AR Quick Look container (T-110 extension); a ZIP, so the same "
        "archive-bomb/path-traversal defenses as 3MF apply. Every Mesh prim is merged, "
        "world-transformed, into one body; scale comes from the stage's own metersPerUnit.",
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
        notes="Read and written by the OCCT geometry service (F-078): CAD-ready export needs "
        "a version with a B-Rep — built from operations or imported as CAD.",
    ),
    FormatSpec(
        id="iges",
        display_name="IGES",
        extensions=("iges", "igs"),
        mime_types=("model/iges", "application/iges"),
        representation=Representation.brep,
        capabilities=_ROUNDTRIP,
        max_bytes=500 * MB,
        notes="Read and written by the OCCT geometry service (F-078); B-Rep versions only.",
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
        capabilities=_ROUNDTRIP,
        max_bytes=300 * MB,
        magic=(b"ply\n", b"ply\r\n"),
        notes="Typical scan output; carries per-vertex colour, so painting survives it.",
    ),
    # Scan frames (E9). Uploadable, never handed to a 3D parser: the reconstruction
    # worker is the only consumer, and it treats them as untrusted input like any file.
    FormatSpec(
        id="jpeg",
        display_name="JPEG image",
        extensions=("jpg", "jpeg"),
        mime_types=("image/jpeg",),
        representation=Representation.image,
        capabilities=_SCAN,
        max_bytes=32 * MB,
        magic=(b"\xff\xd8\xff",),
        notes="Scan frame; the camera's own encoding.",
    ),
    FormatSpec(
        id="png",
        display_name="PNG image",
        extensions=("png",),
        mime_types=("image/png",),
        representation=Representation.image,
        capabilities=_SCAN,
        max_bytes=64 * MB,
        magic=(b"\x89PNG\r\n\x1a\n",),
        notes="Scan frame, or a 16-bit depth map exported by the device.",
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


def scan_frames() -> list[FormatSpec]:
    return [f for f in _FORMATS if f.is_scan_frame]


def exportable() -> list[FormatSpec]:
    return [f for f in _FORMATS if f.can_export]
