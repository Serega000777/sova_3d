"""Fixed Blender-side quad-remesh program; callers cannot replace or parameterize it beyond
the one bounded `target_faces` integer validated by the trusted launcher."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import bpy  # type: ignore[import-not-found]

# Blender's embedded Python does not include Debian's dist-packages directory in
# ``sys.path``. The production image deliberately installs ``python3-numpy`` in that
# fixed, read-only location for Blender's glTF/FBX add-ons and this verifier.
_SYSTEM_DIST_PACKAGES = "/usr/lib/python3/dist-packages"
if _SYSTEM_DIST_PACKAGES not in sys.path:
    sys.path.append(_SYSTEM_DIST_PACKAGES)
import numpy as np  # noqa: E402

WORK = Path("/work")
SOURCE = WORK / "input.glb"
OUTPUT = WORK / "output.fbx"
REPORT = WORK / "report.json"
VERIFY = WORK / "verify.json"
SCRIPT = Path("/runner/quad_remesh_script.py")
MIN_TARGET_FACES = 100
MAX_TARGET_FACES = 100_000
MAX_INPUT_TRIANGLES = 300_000


def _sandbox_attestation() -> dict[str, object]:
    interfaces = sorted(
        line.split(":", 1)[0].strip()
        for line in Path("/proc/net/dev").read_text().splitlines()[2:]
        if ":" in line
    )
    status = {
        line.split(":", 1)[0]: line.split(":", 1)[1].strip()
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    }
    if interfaces not in ([], ["lo"]):
        raise RuntimeError("quad-remesh network namespace is not isolated")
    capability_fields = ("CapEff", "CapPrm", "CapAmb")
    if os.geteuid() != 65534 or any(
        status.get(field) != "0000000000000000" for field in capability_fields
    ):
        raise RuntimeError("quad-remesh privileges were not dropped")
    if status.get("NoNewPrivs") != "1" or Path("/app").exists():
        raise RuntimeError("quad-remesh mount/privilege isolation is unavailable")
    return {
        "sandbox_network_interfaces": interfaces,
        "sandbox_uid": os.geteuid(),
        "capability_effective": status["CapEff"],
        "capability_permitted": status["CapPrm"],
        "capability_ambient": status["CapAmb"],
        "no_new_privileges": True,
    }


def _mesh_stats(obj: Any) -> dict[str, object]:
    mesh = obj.data
    polygons = list(mesh.polygons)
    quads = sum(1 for polygon in polygons if len(polygon.vertices) == 4)
    triangles = sum(1 for polygon in polygons if len(polygon.vertices) == 3)
    other = len(polygons) - quads - triangles
    for vertex in mesh.vertices:
        if not all(math.isfinite(float(component)) for component in vertex.co):
            raise RuntimeError("quad-remesh output has a non-finite vertex")
    return {
        "faces": len(polygons),
        "quad_faces": quads,
        "triangle_faces": triangles,
        "other_faces": other,
        "vertices": len(mesh.vertices),
        "quad_ratio": round(quads / len(polygons), 4) if polygons else 0.0,
    }


def _report(stats: dict[str, object], target_faces: int) -> dict[str, object]:
    return {
        "schema_version": 1,
        "operation": "quad_remesh",
        "blender_version": bpy.app.version_string,
        "target_faces": target_faces,
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "script_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
        **stats,
        **_sandbox_attestation(),
    }


def _single_mesh_object() -> Any:
    meshes = [obj for obj in bpy.data.objects if obj.type == "MESH"]
    if len(meshes) != 1:
        raise RuntimeError("quad-remesh accepts exactly one mesh object, not a multi-part scene")
    return meshes[0]


def _remesh(target_faces: int) -> None:
    if not MIN_TARGET_FACES <= target_faces <= MAX_TARGET_FACES:
        raise RuntimeError("quad-remesh target_faces is outside the fixed bounds")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.preferences.filepaths.use_scripts_auto_execute = False
    # Debian's bundled Blender glTF/FBX add-ons still reference the removed NumPy alias.
    if not hasattr(np, "bool"):
        np.__dict__["bool"] = np.bool_
    result = bpy.ops.import_scene.gltf(filepath=str(SOURCE))
    if "FINISHED" not in result:
        raise RuntimeError("Blender did not import the validated GLB")
    obj = _single_mesh_object()
    triangle_count = sum(len(p.vertices) - 2 for p in obj.data.polygons if len(p.vertices) >= 3)
    if not 0 < triangle_count <= MAX_INPUT_TRIANGLES:
        raise RuntimeError("quad-remesh input exceeds the fixed triangle-count bound")

    view_layer = bpy.context.view_layer
    view_layer.objects.active = obj
    obj.select_set(True)
    try:
        result = bpy.ops.object.quadriflow_remesh(
            mode="FACES",
            target_faces=target_faces,
            use_preserve_sharp=True,
            use_preserve_boundary=True,
            use_mesh_symmetry=False,
            smooth_normals=True,
        )
    except RuntimeError as exc:
        raise RuntimeError(f"Blender's QuadriFlow remesh failed: {exc}") from exc
    if "FINISHED" not in result:
        raise RuntimeError("Blender's QuadriFlow remesh did not finish")

    remeshed = _single_mesh_object()
    stats = _mesh_stats(remeshed)
    if stats["faces"] == 0:
        raise RuntimeError("quad-remesh produced an empty mesh")

    bpy.ops.object.select_all(action="DESELECT")
    remeshed.select_set(True)
    view_layer.objects.active = remeshed
    bpy.ops.export_scene.fbx(
        filepath=str(OUTPUT),
        use_selection=True,
        object_types={"MESH"},
        mesh_smooth_type="FACE",
        add_leaf_bones=False,
        bake_anim=False,
        embed_textures=False,
    )
    REPORT.write_text(json.dumps(_report(stats, target_faces), sort_keys=True), encoding="utf-8")


def _verify(target_faces: int) -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.preferences.filepaths.use_scripts_auto_execute = False
    if not hasattr(np, "bool"):
        np.__dict__["bool"] = np.bool_
    result = bpy.ops.import_scene.fbx(filepath=str(OUTPUT))
    if "FINISHED" not in result:
        raise RuntimeError("Blender did not reopen its own quad-remesh output")
    obj = _single_mesh_object()
    stats = _mesh_stats(obj)
    VERIFY.write_text(json.dumps(_report(stats, target_faces), sort_keys=True), encoding="utf-8")


def main() -> None:
    separator = sys.argv.index("--")
    args = sys.argv[separator + 1 :]
    if len(args) != 2 or args[0] not in {"remesh", "verify"} or not args[1].isdecimal():
        raise RuntimeError("invalid quad-remesh invocation")
    target_faces = int(args[1])
    if args[0] == "remesh":
        _remesh(target_faces)
    else:
        _verify(target_faces)


main()
