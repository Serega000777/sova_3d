"""Fixed Blender-side package/verify program; callers cannot replace or parameterize it."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from pathlib import Path

import bpy  # type: ignore[import-not-found]
import numpy as np
from mathutils import Vector  # type: ignore[import-not-found]

WORK = Path("/work")
SOURCE = WORK / "input.glb"
OUTPUT = WORK / "output.blend"
REPORT = WORK / "report.json"
VERIFY = WORK / "verify.json"
SCRIPT = Path("/runner/blender_handoff_script.py")


def _drivers() -> list[str]:
    found: list[str] = []
    collections = (
        bpy.data.objects,
        bpy.data.meshes,
        bpy.data.materials,
        bpy.data.scenes,
        bpy.data.actions,
    )
    for collection in collections:
        for block in collection:
            animation = getattr(block, "animation_data", None)
            if animation is not None and getattr(animation, "drivers", None):
                found.append(str(getattr(block, "name", "unnamed")))
    return sorted(found)


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
        raise RuntimeError("Blender handoff network namespace is not isolated")
    capability_fields = ("CapEff", "CapPrm", "CapAmb")
    if os.geteuid() != 65534 or any(
        status.get(field) != "0000000000000000" for field in capability_fields
    ):
        raise RuntimeError("Blender handoff privileges were not dropped")
    if status.get("NoNewPrivs") != "1" or Path("/app").exists():
        raise RuntimeError("Blender handoff mount/privilege isolation is unavailable")
    return {
        "sandbox_network_interfaces": interfaces,
        "sandbox_uid": os.geteuid(),
        "capability_effective": status["CapEff"],
        "capability_permitted": status["CapPrm"],
        "capability_ambient": status["CapAmb"],
        "no_new_privileges": True,
    }


def _inspect() -> dict[str, object]:
    objects = list(bpy.data.objects)
    meshes = list(bpy.data.meshes)
    if not objects or not meshes:
        raise RuntimeError("the imported scene has no editable mesh geometry")
    if len(objects) > 10_000 or len(meshes) > 10_000 or len(bpy.data.materials) > 10_000:
        raise RuntimeError("the imported scene exceeds Blender handoff object limits")
    vertices = sum(len(mesh.vertices) for mesh in meshes)
    for mesh in meshes:
        mesh.calc_loop_triangles()
    triangles = sum(len(mesh.loop_triangles) for mesh in meshes)
    if not 0 < vertices <= 10_000_000 or not 0 < triangles <= 20_000_000:
        raise RuntimeError("the imported scene exceeds Blender handoff geometry limits")
    texture_pixels = sum(image.size[0] * image.size[1] for image in bpy.data.images)
    if texture_pixels > 64_000_000:
        raise RuntimeError("the imported scene exceeds Blender handoff texture limits")

    points: list[tuple[float, float, float]] = []
    for obj in objects:
        matrix_values = [value for row in obj.matrix_world for value in row]
        if not all(math.isfinite(float(value)) for value in matrix_values):
            raise RuntimeError("the imported scene has a non-finite object transform")
        if obj.type == "MESH":
            for corner in obj.bound_box:
                world = obj.matrix_world @ Vector(corner)
                point = (float(world[0]), float(world[1]), float(world[2]))
                if not all(math.isfinite(value) for value in point):
                    raise RuntimeError("the imported scene has non-finite bounds")
                points.append(point)
    if not points:
        raise RuntimeError("the imported scene has no finite mesh bounds")
    minimum = [min(point[index] for point in points) for index in range(3)]
    maximum = [max(point[index] for point in points) for index in range(3)]
    if any(abs(value) > 10_000 for value in minimum + maximum):
        raise RuntimeError("the imported scene exceeds the 10 km Blender handoff bound")

    scripts = sorted(text.name for text in bpy.data.texts)
    drivers = _drivers()
    external_refs = sorted(library.filepath for library in bpy.data.libraries)
    unpacked = [
        image.name
        for image in bpy.data.images
        if image.source not in {"GENERATED", "VIEWER"} and image.packed_file is None
    ]
    if scripts or drivers or external_refs or unpacked:
        raise RuntimeError("the Blender scene contains forbidden executable or external content")
    return {
        "schema_version": 1,
        "operation": "editable_scene",
        "blender_version": bpy.app.version_string,
        "objects": len(objects),
        "meshes": len(meshes),
        "materials": len(bpy.data.materials),
        "vertices": vertices,
        "triangles": triangles,
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "script_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
        "min_bounds_m": minimum,
        "max_bounds_m": maximum,
        "external_refs": external_refs,
        "scripts": scripts,
        "drivers": drivers,
        "packed": not unpacked,
        **_sandbox_attestation(),
    }


def _package() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.preferences.filepaths.use_scripts_auto_execute = False
    bpy.context.preferences.filepaths.save_version = 0
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.length_unit = "METERS"
    bpy.context.scene.unit_settings.scale_length = 1.0
    # Debian's Blender 3.4 glTF add-on still references the removed NumPy alias.  Keep the
    # compatibility shim inside this fixed script rather than weakening the worker environment.
    if not hasattr(np, "bool"):
        np.__dict__["bool"] = np.bool_
    result = bpy.ops.import_scene.gltf(filepath=str(SOURCE), import_pack_images=True)
    if "FINISHED" not in result:
        raise RuntimeError("Blender did not import the validated GLB")
    report = _inspect()
    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT), check_existing=False, compress=False)
    REPORT.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")


def _verify() -> None:
    bpy.context.preferences.filepaths.use_scripts_auto_execute = False
    bpy.ops.wm.open_mainfile(filepath=str(OUTPUT), load_ui=False, use_scripts=False)
    VERIFY.write_text(json.dumps(_inspect(), sort_keys=True), encoding="utf-8")


def main() -> None:
    separator = sys.argv.index("--")
    args = sys.argv[separator + 1 :]
    if args == ["package"]:
        _package()
    elif args == ["verify"]:
        _verify()
    else:
        raise RuntimeError("invalid Blender handoff operation")


main()
