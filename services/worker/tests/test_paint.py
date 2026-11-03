"""F-034 / Reference 77: deterministic face-colour painting."""

from __future__ import annotations

import base64
import hashlib
import io

import numpy as np
import pytest
import trimesh
from PIL import Image
from pydantic import ValidationError

from worker import paint


def test_stroke_opacity_blends_in_order_and_keeps_the_preview_opaque() -> None:
    mesh = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
    request = paint.PaintRequest(
        base_colour="#000000",
        strokes=[
            paint.Stroke(colour="#ff0000", opacity=0.5),
            paint.Stroke(colour="#0000ff", opacity=0.5),
        ],
    )

    result, painted = paint.paint_mesh_into(mesh, request)

    assert result.ok and result.painted_faces == len(painted.faces)
    expected = np.tile(np.array([64, 0, 128, 255], dtype=np.uint8), (len(painted.faces), 1))
    assert isinstance(painted.visual, trimesh.visual.ColorVisuals)
    np.testing.assert_array_equal(painted.visual.face_colors, expected)


@pytest.mark.parametrize("opacity", [0, 0.049, 1.001])
def test_stroke_opacity_is_bounded(opacity: float) -> None:
    with pytest.raises(ValidationError):
        paint.Stroke(colour="#ff0000", opacity=opacity)


def test_catalogue_material_is_exported_as_real_pbr_group(tmp_path) -> None:
    source = tmp_path / "box.stl"
    output = tmp_path / "painted.glb"
    source.write_bytes(trimesh.creation.box(extents=(10.0, 10.0, 10.0)).export(file_type="stl"))
    request = paint.PaintRequest(
        strokes=[
            paint.Stroke(
                material=paint.MaterialInput(
                    catalog_material_id="interior.metal.steel.v1",
                    base_color="#A9AFB5",
                    roughness=0.42,
                    metallic=1.0,
                )
            )
        ]
    )

    result = paint.paint_file(source, "stl", request, output, "glb")

    assert result.ok and result.materials == ["interior.metal.steel.v1"]
    loaded = trimesh.load(output, force="scene", process=False)
    materials = [geometry.visual.material for geometry in loaded.geometry.values()]
    material = next(item for item in materials if item.name == "interior.metal.steel.v1")
    assert material.metallicFactor == pytest.approx(1.0)
    assert material.roughnessFactor == pytest.approx(0.42)


def test_catalogue_texture_is_content_addressed_and_has_repeatable_uv(tmp_path) -> None:
    image = Image.new("RGBA", (4, 4), (180, 170, 160, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    payload = buffer.getvalue()
    encoded = base64.b64encode(payload).decode("ascii")
    digest = hashlib.sha256(payload).hexdigest()
    source = tmp_path / "box.stl"
    output = tmp_path / "painted.glb"
    box = trimesh.creation.box(extents=(1000.0, 1000.0, 1000.0))
    source.write_bytes(box.export(file_type="stl"))
    material = paint.MaterialInput(
        catalog_material_id="interior.concrete.test.v1",
        base_color="#B8B6AF",
        roughness=0.92,
        texture_sha256=digest,
        texture_tile_size_mm=100.0,
        texture_data_b64=encoded,
    )

    result = paint.paint_file(
        source,
        "stl",
        paint.PaintRequest(strokes=[paint.Stroke(material=material)]),
        output,
        "glb",
    )

    assert result.ok
    loaded = trimesh.load(output, force="scene", process=False)
    textured = next(
        geometry
        for geometry in loaded.geometry.values()
        if geometry.visual.material.name == "interior.concrete.test.v1"
    )
    assert textured.visual.material.baseColorTexture is not None
    assert np.ptp(np.asarray(textured.visual.uv), axis=0).max() > 1.0

    with pytest.raises(ValidationError, match="sha256"):
        paint.MaterialInput(
            catalog_material_id="interior.concrete.test.v1",
            base_color="#B8B6AF",
            roughness=0.92,
            texture_sha256="0" * 64,
            texture_tile_size_mm=100.0,
            texture_data_b64=encoded,
        )


def test_catalogue_material_opacity_bakes_opaque_base_and_pbr_atlases(tmp_path) -> None:
    source = tmp_path / "box.stl"
    output = tmp_path / "painted.glb"
    source.write_bytes(trimesh.creation.box(extents=(10.0, 10.0, 10.0)).export(file_type="stl"))
    material = paint.MaterialInput(
        catalog_material_id="interior.metal.steel.v1",
        base_color="#A9AFB5",
        roughness=0.42,
        metallic=1.0,
    )

    result = paint.paint_file(
        source,
        "stl",
        paint.PaintRequest(
            base_colour="#000000",
            strokes=[paint.Stroke(material=material, opacity=0.5)],
        ),
        output,
        "glb",
    )

    assert result.ok
    loaded = trimesh.load(output, force="scene", process=False)
    exported = next(
        geometry.visual.material
        for geometry in loaded.geometry.values()
        if geometry.visual.material.name == material.catalog_material_id
    )
    assert exported.alphaMode == "OPAQUE"
    assert exported.metallicFactor == pytest.approx(1.0)
    assert exported.roughnessFactor == pytest.approx(1.0)
    base = np.asarray(exported.baseColorTexture.convert("RGBA"))
    pbr = np.asarray(exported.metallicRoughnessTexture.convert("RGBA"))
    assert np.all(base[..., 3] == 255)
    assert np.all(pbr[..., 3] == 255)
    np.testing.assert_allclose(
        np.unique(base[base[..., :3].any(axis=2), :3], axis=0),
        [[84, 88, 90]],
        atol=1,
    )
    np.testing.assert_allclose(
        np.unique(pbr[pbr[..., 2] > 0, 1:3], axis=0),
        [[181, 128]],
        atol=1,
    )


def test_partial_surface_finish_fails_closed_over_an_existing_material() -> None:
    material = paint.MaterialInput(
        catalog_material_id="interior.metal.steel.v1",
        base_color="#A9AFB5",
        roughness=0.42,
        metallic=1.0,
    )
    mesh = trimesh.creation.box(extents=(10.0, 10.0, 10.0))

    with pytest.raises(ValueError, match="material cannot overlap another material"):
        paint.paint_mesh(
            mesh,
            paint.PaintRequest(
                strokes=[
                    paint.Stroke(material=material),
                    paint.Stroke(material=material, opacity=0.5),
                ]
            ),
        )
    with pytest.raises(ValueError, match="colour cannot overlap a catalogue material"):
        paint.paint_mesh(
            mesh,
            paint.PaintRequest(
                strokes=[
                    paint.Stroke(material=material),
                    paint.Stroke(colour="#ff0000", opacity=0.5),
                ]
            ),
        )
