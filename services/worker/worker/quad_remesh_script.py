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
from mathutils.bvhtree import BVHTree  # type: ignore[import-not-found]  # noqa: E402

WORK = Path("/work")
SOURCE = WORK / "input.glb"
OUTPUT = WORK / "output.fbx"
REPORT = WORK / "report.json"
VERIFY = WORK / "verify.json"
SCRIPT = Path("/runner/quad_remesh_script.py")
MIN_TARGET_FACES = 100
MAX_TARGET_FACES = 100_000
MAX_INPUT_TRIANGLES = 300_000
MAX_OBJECTS = 64


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
    uv_layers = list(mesh.uv_layers)
    uv_coordinates: list[tuple[float, float]] = []
    if uv_layers:
        active_uv = mesh.uv_layers.active or uv_layers[0]
        for value in active_uv.data:
            coordinate = (float(value.uv[0]), float(value.uv[1]))
            if not all(math.isfinite(component) for component in coordinate):
                raise RuntimeError("quad-remesh output has a non-finite UV coordinate")
            uv_coordinates.append(coordinate)
    uv_bounds = None
    if uv_coordinates:
        uv_bounds = [
            round(min(value[0] for value in uv_coordinates), 6),
            round(min(value[1] for value in uv_coordinates), 6),
            round(max(value[0] for value in uv_coordinates), 6),
            round(max(value[1] for value in uv_coordinates), 6),
        ]
    return {
        "faces": len(polygons),
        "quad_faces": quads,
        "triangle_faces": triangles,
        "other_faces": other,
        "vertices": len(mesh.vertices),
        "quad_ratio": round(quads / len(polygons), 4) if polygons else 0.0,
        "uv_layers": len(uv_layers),
        "uv_coordinates": len(uv_coordinates),
        "uv_bounds": uv_bounds,
    }


def _packed_image_sha256(image: Any) -> str:
    packed = getattr(image, "packed_file", None)
    if packed is None:
        raise RuntimeError("quad-remesh material references an unpacked texture")
    return hashlib.sha256(bytes(packed.data)).hexdigest()


def _material_evidence(obj: Any) -> list[dict[str, object]]:
    evidence: list[dict[str, object]] = []
    for material in obj.data.materials:
        if material is None:
            raise RuntimeError("quad-remesh source has an empty material slot")
        texture_sha256s: set[str] = set()
        if material.use_nodes and material.node_tree is not None:
            for node in material.node_tree.nodes:
                image = getattr(node, "image", None)
                if image is not None:
                    texture_sha256s.add(_packed_image_sha256(image))
        diffuse = [round(float(value), 6) for value in material.diffuse_color]
        if len(diffuse) != 4 or not all(math.isfinite(value) for value in diffuse):
            raise RuntimeError("quad-remesh material has an invalid diffuse colour")
        evidence.append(
            {
                "name": str(material.name),
                "diffuse_rgba": diffuse,
                "texture_sha256s": sorted(texture_sha256s),
            }
        )
    return evidence


def _material_face_counts(obj: Any) -> list[int]:
    counts = [0] * len(obj.data.materials)
    if not counts:
        return counts
    for polygon in obj.data.polygons:
        material_index = int(polygon.material_index)
        if not 0 <= material_index < len(counts):
            raise RuntimeError("quad-remesh polygon material index is outside its slots")
        counts[material_index] += 1
    return counts


def _object_report(
    name: str,
    stats: dict[str, object],
    source_uv_layers: int,
    source_materials: list[dict[str, object]],
    source_material_faces: list[int],
) -> dict[str, object]:
    output_uv_layers = stats["uv_layers"]
    output_uv_coordinates = stats["uv_coordinates"]
    if not isinstance(output_uv_layers, int) or not isinstance(output_uv_coordinates, int):
        raise RuntimeError("quad-remesh returned invalid UV statistics")
    if source_uv_layers:
        if output_uv_layers != 1 or output_uv_coordinates <= 0:
            raise RuntimeError("quad-remesh did not preserve the active source UV map")
        uv_transfer = "active_surface_projected"
    else:
        if output_uv_layers != 0 or output_uv_coordinates != 0:
            raise RuntimeError("quad-remesh invented UV data for an untextured source")
        uv_transfer = "none"
    materials = _material_evidence(bpy.data.objects[name])
    if materials != source_materials:
        raise RuntimeError("quad-remesh did not preserve the source material package")
    if any(material["texture_sha256s"] for material in materials) and source_uv_layers == 0:
        raise RuntimeError("quad-remesh cannot package a texture without source UVs")
    output_material_faces = _material_face_counts(bpy.data.objects[name])
    if len(source_material_faces) != len(materials):
        raise RuntimeError("quad-remesh source material assignment evidence is inconsistent")
    materials = [
        {
            **material,
            "source_faces": source_material_faces[index],
            "output_faces": output_material_faces[index],
        }
        for index, material in enumerate(materials)
    ]
    material_transfer = (
        "none"
        if not materials
        else "single_slot_preserved"
        if len(materials) == 1
        else "nearest_source_polygon"
    )
    return {
        "name": name,
        "source_uv_layers": source_uv_layers,
        "uv_transfer": uv_transfer,
        "materials": materials,
        "material_transfer": material_transfer,
        **stats,
    }


def _report(per_object: list[dict[str, object]], target_faces: int) -> dict[str, object]:
    def total(key: str) -> int:
        return sum(int(entry[key]) for entry in per_object)  # type: ignore[call-overload]

    faces = total("faces")
    return {
        "schema_version": 4,
        "operation": "quad_remesh",
        "blender_version": bpy.app.version_string,
        "target_faces": target_faces,
        "objects": len(per_object),
        "faces": faces,
        "quad_faces": total("quad_faces"),
        "triangle_faces": total("triangle_faces"),
        "other_faces": total("other_faces"),
        "vertices": total("vertices"),
        "quad_ratio": round(total("quad_faces") / faces, 4) if faces else 0.0,
        "per_object": sorted(per_object, key=lambda entry: str(entry["name"])),
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "script_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
        **_sandbox_attestation(),
    }


def _mesh_objects() -> list[Any]:
    meshes = [obj for obj in bpy.data.objects if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError("quad-remesh source has no mesh object")
    if len(meshes) > MAX_OBJECTS:
        raise RuntimeError("quad-remesh source exceeds the fixed object-count bound")
    # Stable, source-independent order: every fixed-script invocation on the same GLB
    # must walk objects in the same sequence, or per-object stats would not line up
    # between the package and verify passes.
    return sorted(meshes, key=lambda obj: str(obj.name))


def _import_source() -> list[Any]:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.preferences.filepaths.use_scripts_auto_execute = False
    if not hasattr(np, "bool"):
        np.__dict__["bool"] = np.bool_
    result = bpy.ops.import_scene.gltf(filepath=str(SOURCE), import_pack_images=True)
    if "FINISHED" not in result:
        raise RuntimeError("Blender did not import the validated GLB")
    return _mesh_objects()


def _transfer_active_uv(source: Any, remeshed: Any) -> None:
    source_uv = source.data.uv_layers.active or source.data.uv_layers[0]
    while remeshed.data.uv_layers:
        remeshed.data.uv_layers.remove(remeshed.data.uv_layers[0])
    target_uv = remeshed.data.uv_layers.new(name="SovaProjectedUV")
    modifier = remeshed.modifiers.new(name="Sova active UV projection", type="DATA_TRANSFER")
    modifier.object = source
    modifier.use_loop_data = True
    modifier.data_types_loops = {"UV"}
    modifier.loop_mapping = "POLYINTERP_NEAREST"
    modifier.layers_uv_select_src = source_uv.name
    modifier.layers_uv_select_dst = target_uv.name
    bpy.context.view_layer.objects.active = remeshed
    remeshed.select_set(True)
    result = bpy.ops.object.modifier_apply(modifier=modifier.name)
    if "FINISHED" not in result:
        raise RuntimeError("Blender did not apply the fixed active-UV transfer")


def _transfer_material_indices(source: Any, remeshed: Any) -> None:
    tree = BVHTree.FromPolygons(
        [vertex.co.copy() for vertex in source.data.vertices],
        [list(polygon.vertices) for polygon in source.data.polygons],
        all_triangles=False,
    )
    for polygon in remeshed.data.polygons:
        nearest = tree.find_nearest(polygon.center)
        if nearest is None or nearest[2] is None:
            raise RuntimeError("quad-remesh could not project a source material index")
        source_index = int(nearest[2])
        material_index = int(source.data.polygons[source_index].material_index)
        if not 0 <= material_index < len(remeshed.data.materials):
            raise RuntimeError("quad-remesh source material index is outside its slots")
        polygon.material_index = material_index


def _remesh_one(obj: Any, target_faces: int) -> dict[str, object]:
    """Quadriflow-remesh one mesh object in place; its world transform is untouched."""
    source_uv_layers = len(obj.data.uv_layers)
    source_material_slots = list(obj.data.materials)
    source_materials = _material_evidence(obj)
    source_material_faces = _material_face_counts(obj)
    transfer_source = None
    if source_uv_layers or len(source_material_slots) > 1:
        transfer_source = obj.copy()
        transfer_source.data = obj.data.copy()
        transfer_source.name = f"{obj.name}.SovaSurfaceSource"
        bpy.context.collection.objects.link(transfer_source)

    view_layer = bpy.context.view_layer
    bpy.ops.object.select_all(action="DESELECT")
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

    obj.data.materials.clear()
    for material in source_material_slots:
        obj.data.materials.append(material)
    if transfer_source is not None and source_uv_layers:
        _transfer_active_uv(transfer_source, obj)
    if transfer_source is not None and len(source_material_slots) > 1:
        _transfer_material_indices(transfer_source, obj)
    if transfer_source is not None:
        source_mesh = transfer_source.data
        bpy.data.objects.remove(transfer_source, do_unlink=True)
        bpy.data.meshes.remove(source_mesh)
    stats = _mesh_stats(obj)
    if stats["faces"] == 0:
        raise RuntimeError("quad-remesh produced an empty mesh")
    return _object_report(
        obj.name,
        stats,
        source_uv_layers,
        source_materials,
        source_material_faces,
    )


def _remesh(target_faces: int) -> None:
    if not MIN_TARGET_FACES <= target_faces <= MAX_TARGET_FACES:
        raise RuntimeError("quad-remesh target_faces is outside the fixed bounds")
    objects = _import_source()
    triangle_count = sum(
        len(p.vertices) - 2
        for obj in objects
        for p in obj.data.polygons
        if len(p.vertices) >= 3
    )
    if not 0 < triangle_count <= MAX_INPUT_TRIANGLES:
        raise RuntimeError("quad-remesh input exceeds the fixed triangle-count bound")

    per_object = [_remesh_one(obj, target_faces) for obj in objects]

    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.export_scene.fbx(
        filepath=str(OUTPUT),
        use_selection=True,
        object_types={"MESH"},
        mesh_smooth_type="FACE",
        add_leaf_bones=False,
        bake_anim=False,
        path_mode="COPY",
        embed_textures=True,
    )
    REPORT.write_text(
        json.dumps(_report(per_object, target_faces), sort_keys=True),
        encoding="utf-8",
    )


def _verify(target_faces: int) -> None:
    source_objects = _import_source()
    source_evidence = {
        obj.name: (
            len(obj.data.uv_layers),
            _material_evidence(obj),
            _material_face_counts(obj),
        )
        for obj in source_objects
    }
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.preferences.filepaths.use_scripts_auto_execute = False
    if not hasattr(np, "bool"):
        np.__dict__["bool"] = np.bool_
    result = bpy.ops.import_scene.fbx(filepath=str(OUTPUT), use_image_search=False)
    if "FINISHED" not in result:
        raise RuntimeError("Blender did not reopen its own quad-remesh output")
    reopened = _mesh_objects()
    if {obj.name for obj in reopened} != set(source_evidence):
        raise RuntimeError("quad-remesh output does not name the same objects as the source")
    per_object = [
        _object_report(
            obj.name,
            _mesh_stats(obj),
            source_evidence[obj.name][0],
            source_evidence[obj.name][1],
            source_evidence[obj.name][2],
        )
        for obj in reopened
    ]
    VERIFY.write_text(
        json.dumps(_report(per_object, target_faces), sort_keys=True),
        encoding="utf-8",
    )


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
