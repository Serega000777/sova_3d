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
    invalid_image = b"\x89PNG\r\n\x1a\nnot-an-image"
    invalid_material = paint.MaterialInput(
        catalog_material_id="workspace.texture.invalid",
        base_color="#FFFFFF",
        roughness=0.8,
        texture_sha256=hashlib.sha256(invalid_image).hexdigest(),
        texture_tile_size_mm=100.0,
        texture_data_b64=base64.b64encode(invalid_image).decode("ascii"),
    )
    with pytest.raises(ValueError, match="valid image"):
        paint.paint_file(
            source,
            "stl",
            paint.PaintRequest(strokes=[paint.Stroke(material=invalid_material)]),
            output,
            "glb",
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


def test_partial_untextured_material_blends_over_existing_pbr(tmp_path) -> None:
    source = tmp_path / "box.stl"
    output = tmp_path / "painted.glb"
    source.write_bytes(trimesh.creation.box(extents=(10.0, 10.0, 10.0)).export(file_type="stl"))
    underlay = paint.MaterialInput(
        catalog_material_id="interior.metal.red.v1",
        base_color="#FF0000",
        roughness=0.2,
        metallic=0.8,
    )
    finish = paint.MaterialInput(
        catalog_material_id="interior.paint.blue.v1",
        base_color="#0000FF",
        roughness=0.6,
        metallic=0.2,
    )

    result = paint.paint_file(
        source,
        "stl",
        paint.PaintRequest(
            strokes=[
                paint.Stroke(material=underlay),
                paint.Stroke(material=finish, opacity=0.25),
            ]
        ),
        output,
        "glb",
    )

    assert result.ok
    loaded = trimesh.load(output, force="scene", process=False)
    exported = next(
        geometry.visual.material
        for geometry in loaded.geometry.values()
        if geometry.visual.material.name == finish.catalog_material_id
    )
    base = np.asarray(exported.baseColorTexture.convert("RGBA"))
    pbr = np.asarray(exported.metallicRoughnessTexture.convert("RGBA"))
    np.testing.assert_allclose(
        np.unique(base[base[..., :3].any(axis=2), :3], axis=0),
        [[191, 0, 64]],
        atol=1,
    )
    np.testing.assert_allclose(
        np.unique(pbr[pbr[..., 2] > 0, 1:3], axis=0),
        [[76, 166]],
        atol=1,
    )


def test_partial_colour_blends_over_existing_untextured_pbr(tmp_path) -> None:
    source = tmp_path / "box.stl"
    output = tmp_path / "painted.glb"
    source.write_bytes(trimesh.creation.box(extents=(10.0, 10.0, 10.0)).export(file_type="stl"))
    underlay = paint.MaterialInput(
        catalog_material_id="interior.metal.red.v1",
        base_color="#FF0000",
        roughness=0.2,
        metallic=0.8,
    )

    result = paint.paint_file(
        source,
        "stl",
        paint.PaintRequest(
            strokes=[
                paint.Stroke(material=underlay),
                paint.Stroke(colour="#0000ff", opacity=0.25),
            ]
        ),
        output,
        "glb",
    )

    assert result.ok
    assert result.materials == [underlay.catalog_material_id]
    loaded = trimesh.load(output, force="scene", process=False)
    exported = next(
        geometry.visual.material
        for geometry in loaded.geometry.values()
        if geometry.visual.material.name == "paint:colour-composite:0000FF"
    )
    base = np.asarray(exported.baseColorTexture.convert("RGBA"))
    pbr = np.asarray(exported.metallicRoughnessTexture.convert("RGBA"))
    np.testing.assert_allclose(
        np.unique(base[base[..., :3].any(axis=2), :3], axis=0),
        [[191, 0, 64]],
        atol=1,
    )
    np.testing.assert_allclose(
        np.unique(pbr[pbr[..., 2] > 0, 1:3], axis=0),
        [[102, 153]],
        atol=1,
    )


def test_partial_material_blends_two_textured_pbr_layers(tmp_path) -> None:
    source = tmp_path / "box.stl"
    output = tmp_path / "painted.glb"
    source.write_bytes(trimesh.creation.box(extents=(10.0, 10.0, 10.0)).export(file_type="stl"))
    image = Image.new("RGBA", (2, 2))
    image.putdata([(255, 0, 0, 255), (0, 255, 0, 255)] * 2)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    payload = buffer.getvalue()
    encoded = base64.b64encode(payload).decode("ascii")
    textured = paint.MaterialInput(
        catalog_material_id="interior.concrete.test.v1",
        base_color="#FFFFFF",
        roughness=0.2,
        metallic=0.8,
        texture_sha256=hashlib.sha256(payload).hexdigest(),
        texture_tile_size_mm=10.0,
        texture_data_b64=encoded,
    )
    finish_image = Image.new("RGBA", (2, 2))
    finish_image.putdata([(0, 0, 255, 255), (255, 255, 0, 255)] * 2)
    finish_buffer = io.BytesIO()
    finish_image.save(finish_buffer, format="PNG")
    finish_payload = finish_buffer.getvalue()
    finish = paint.MaterialInput(
        catalog_material_id="interior.metal.steel.v1",
        base_color="#FFFFFF",
        roughness=0.6,
        metallic=0.2,
        texture_sha256=hashlib.sha256(finish_payload).hexdigest(),
        texture_tile_size_mm=100.0,
        texture_data_b64=base64.b64encode(finish_payload).decode("ascii"),
    )

    result = paint.paint_file(
        source,
        "stl",
        paint.PaintRequest(
            strokes=[
                paint.Stroke(material=textured),
                paint.Stroke(material=finish, opacity=0.5),
            ]
        ),
        output,
        "glb",
    )

    assert result.ok
    loaded = trimesh.load(output, force="scene", process=False)
    exported = next(
        geometry.visual.material
        for geometry in loaded.geometry.values()
        if geometry.visual.material.name == finish.catalog_material_id
    )
    base = np.asarray(exported.baseColorTexture.convert("RGBA"))
    pbr = np.asarray(exported.metallicRoughnessTexture.convert("RGBA"))
    assert {tuple(value) for value in np.unique(base[base[..., :3].any(axis=2), :3], axis=0)} == {
        (128, 0, 128),
        (128, 255, 0),
    }
    np.testing.assert_allclose(
        np.unique(pbr[pbr[..., 2] > 0, 1:3], axis=0),
        [[102, 128]],
        atol=1,
    )


def test_partial_colour_samples_one_textured_pbr_underlay(tmp_path) -> None:
    source = tmp_path / "box.stl"
    output = tmp_path / "painted.glb"
    source.write_bytes(trimesh.creation.box(extents=(10.0, 10.0, 10.0)).export(file_type="stl"))
    image = Image.new("RGBA", (2, 2))
    image.putdata([(255, 0, 0, 255), (0, 255, 0, 255)] * 2)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    payload = buffer.getvalue()
    textured = paint.MaterialInput(
        catalog_material_id="interior.concrete.test.v1",
        base_color="#FFFFFF",
        roughness=0.2,
        metallic=0.8,
        texture_sha256=hashlib.sha256(payload).hexdigest(),
        texture_tile_size_mm=10.0,
        texture_data_b64=base64.b64encode(payload).decode("ascii"),
    )

    result = paint.paint_file(
        source,
        "stl",
        paint.PaintRequest(
            strokes=[
                paint.Stroke(material=textured),
                paint.Stroke(colour="#0000ff", opacity=0.25),
            ]
        ),
        output,
        "glb",
    )

    assert result.ok
    loaded = trimesh.load(output, force="scene", process=False)
    exported = next(
        geometry.visual.material
        for geometry in loaded.geometry.values()
        if geometry.visual.material.name == "paint:colour-composite:0000FF"
    )
    base = np.asarray(exported.baseColorTexture.convert("RGBA"))
    pbr = np.asarray(exported.metallicRoughnessTexture.convert("RGBA"))
    assert {tuple(value) for value in np.unique(base[base[..., :3].any(axis=2), :3], axis=0)} == {
        (0, 191, 64),
        (191, 0, 64),
    }
    np.testing.assert_allclose(
        np.unique(pbr[pbr[..., 2] > 0, 1:3], axis=0),
        [[102, 153]],
        atol=1,
    )


def test_bounded_surface_stack_replays_texture_material_and_colour(tmp_path) -> None:
    image = Image.new("RGBA", (2, 2))
    image.putdata([(255, 0, 0, 255), (0, 255, 0, 255)] * 2)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    payload = buffer.getvalue()
    encoded = base64.b64encode(payload).decode("ascii")
    textured = paint.MaterialInput(
        catalog_material_id="interior.concrete.test.v1",
        base_color="#FFFFFF",
        roughness=0.2,
        metallic=0.8,
        texture_sha256=hashlib.sha256(payload).hexdigest(),
        texture_tile_size_mm=100.0,
        texture_data_b64=encoded,
    )
    finish = paint.MaterialInput(
        catalog_material_id="interior.metal.steel.v1",
        base_color="#0000FF",
        roughness=0.6,
        metallic=0.2,
    )
    source = tmp_path / "box.stl"
    output = tmp_path / "painted.glb"
    source.write_bytes(trimesh.creation.box(extents=(10.0, 10.0, 10.0)).export(file_type="stl"))

    result = paint.paint_file(
        source,
        "stl",
        paint.PaintRequest(
            strokes=[
                paint.Stroke(material=textured),
                paint.Stroke(material=finish, opacity=0.5),
                paint.Stroke(colour="#00ff00", opacity=0.25),
            ]
        ),
        output,
        "glb",
    )

    assert result.ok
    loaded = trimesh.load(output, force="scene", process=False)
    exported = next(
        geometry.visual.material
        for geometry in loaded.geometry.values()
        if geometry.visual.material.name == "paint:colour-composite:00FF00"
    )
    base = np.asarray(exported.baseColorTexture.convert("RGBA"))
    pbr = np.asarray(exported.metallicRoughnessTexture.convert("RGBA"))
    assert {tuple(value) for value in np.unique(base[base[..., :3].any(axis=2), :3], axis=0)} == {
        (0, 159, 96),
        (96, 64, 96),
    }
    np.testing.assert_allclose(
        np.unique(pbr[pbr[..., 2] > 0, 1:3], axis=0),
        [[140, 96]],
        atol=1,
    )


def test_surface_stack_fails_closed_above_the_eight_layer_bound() -> None:
    material = paint.MaterialInput(
        catalog_material_id="interior.metal.steel.v1",
        base_color="#A9AFB5",
        roughness=0.42,
        metallic=1.0,
    )
    strokes = [paint.Stroke(material=material)] + [
        paint.Stroke(material=material, opacity=0.5) for _ in range(paint.MAX_SURFACE_LAYERS)
    ]

    with pytest.raises(ValueError, match="surface composite exceeds 8 effective layers"):
        paint.paint_mesh(
            trimesh.creation.box(extents=(10.0, 10.0, 10.0)),
            paint.PaintRequest(strokes=strokes),
        )
