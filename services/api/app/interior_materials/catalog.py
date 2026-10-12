"""Small add-only catalogue of visual interior finishes.

The ids and texture bytes are immutable product data. A changed swatch or tile must get a new
id/hash so historical scene versions remain self-describing and reproducible.
"""

# The immutable base64 PNG payloads are intentionally kept as unwrapped single literals.
# ruff: noqa: E501

from __future__ import annotations

import base64
import hashlib
import math
from dataclasses import dataclass
from typing import Any, Literal

from app.api.errors import ValidationFailedError

MaterialTab = Literal["wall", "floor", "furniture", "tile"]
MaterialKind = Literal["paint", "wallpaper", "plaster", "wood", "stone", "tile"]


@dataclass(frozen=True, slots=True)
class InteriorMaterial:
    id: str
    name: str
    name_ru: str
    tabs: tuple[MaterialTab, ...]
    kind: MaterialKind
    base_color: str
    gloss_pct: int
    texture_sha256: str | None = None
    texture_tile_size_mm: float | None = None

    @property
    def roughness(self) -> float:
        return max(0.04, min(1.0, 1.0 - self.gloss_pct / 100.0))


_TEXTURE_B64 = {
    "6379b2621560db481e004825de6ef0fb6c398b74237f6d1f8649e00813a959f4": "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAaklEQVR42u3PsQ3AIAwAQYdZUqbMsqzBDCkpKRmGiogFIhHpvrItN3c8JcfsvO537q2u63rf6j/FzwMAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD4vgHJ4BgTamhsbgAAAABJRU5ErkJggg==",
    "af79f6e864cc07b729bee60b298343c2457d25d360e98571a8afffb09a7ba466": "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAhElEQVR42u3VoQ2AQBAF0T2a4PrXeByGAnDUsNcFmqAIasn78k5NMptp27r0Psd9maPKYzuPPSpviuL7C0DmeP6VeHQDAL4C1LVfBwDogA4A0AEdAKADbgCADrgBADpAIQA6QCEAOkAhADpAIQA6QCEAOkAhADpAIQA6QCEAOkAhAC92ARJnxr67dJPOAAAAAElFTkSuQmCC",
    "3c5442ea339a6a433eabd30be4905a8fca2ad8f460ac45ca4d84943008b93dec": "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAABA0lEQVR42u2YMQ7CMAxFk5KFHYmJgS1X6NojcCZOxAGy5go5DkMlFkqp5LjG4nlspdTPju1fx8f9FjzbEJwbAAAAAAAA/w1wOB/j9XLyC5BCCKU2yRHTmA0BolALCeHl/NFWzMn5k+0NFoa/1Oa7C01jdt9Gk+qF3qFBJdVanJ+rYqSO3r87Or8qtekx9JkD6/6p5mHQuDlKLX8ZYIdRql4DSrFxoIW6kAvz06eNbiniT21KGIUk9Hv75xch5Vqogxr9OgdU67iPnF7Pw69P4peLjrWQ4b8laxUAAADA1lgtslpktWhqrBYzcwAAAAAAADWKGkWNokZRo6hRBhkAAADg1J5Hd3eAtVxHrwAAAABJRU5ErkJggg==",
    "cdb3556c369eb767562523abc20df49403a3cf352faf42e82fab18aa7b9308e9": "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAACFElEQVR42tVaQZLDIAxrNbwp79pD39RDn5JX7SEdJhMCuFhyQg477TYxki1jMHl+Pu/H79e6rsuyPG5wYQD6uq7bh8kIZOjZ92oOFvvProSylYNmav+nQ2/bbxHoQlRw2Nu02D8nYEfG5XCQqCUURwIDgCgc2kYav34JOEF4Hjc+W7vt+Xr9UTQQELrT+78EiAqWZk6ZEiDOfZb6sC8mA17bP7XZYRLocvBAr41CJlDjUFZx1ihJsQTINcheUIcHgoJAmaN09HkIqNFvf3XLPqh9f7v9wAB6ERlyHbAvXbmLbUyqHImEGuh1qQxuQMOu7CxMJ56DvxCGXqQizJi4+yudxkW0oN/v01mzRSoR5JVjjY9//zkctJJ/6s6GJZ87KKdFoAvU48JNRcTWanJKcJhYIxnaRo5dibHudAMKq7thJJD8wxz2kE55GLtD+etvEehuEXXFoRaZ5AetmOkt8952T6Lg9swzNcLGxxMFtH9SGh4Op7aIjaeZNjQDHPzdLuhWBzFxgHSHFcABao2qOcgJqNetEQTu3pUYLrGUhjvCwi1KBkS2ehQcoiVEjzOuSoCJI8BNM1zlftaZH2Lqjm6nhki9KlyDSXP3ghwQlUjEuF9X4HGJeIisEBDuy5bTzuSLOTuDWjzqLnyye3Hs/SR1BJJx7O6xTbx4TBHw8Gm/c3DlAcfDfAwVkOKcN7ZKPmEnaP9ZyaLG+NUMNQAAAABJRU5ErkJggg==",
    "f05b8a01b6567148bf03b8c9b40dbb5e80d220e4d9df5b500df9cdd24d7eca41": "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAcElEQVR42u3XsQkAIQxAUT2c1E4OMozgvha3wJUGXxobUzxS/Rqjl8zzlOTTvifi/bkw5zrqf/oLAAAAAAAAAADcDKh6QA/oAQAAAAAAAAAAPeACekAPAAAAAAAAAADoARfQA3oAAAAAAAAAAOAawAYICC6Fslln4AAAAABJRU5ErkJggg==",
}
_TEXTURES = {key: base64.b64decode(value) for key, value in _TEXTURE_B64.items()}


def _texture(kind: str) -> str:
    return {
        "wallpaper": "6379b2621560db481e004825de6ef0fb6c398b74237f6d1f8649e00813a959f4",
        "plaster": "af79f6e864cc07b729bee60b298343c2457d25d360e98571a8afffb09a7ba466",
        "wood": "3c5442ea339a6a433eabd30be4905a8fca2ad8f460ac45ca4d84943008b93dec",
        "stone": "cdb3556c369eb767562523abc20df49403a3cf352faf42e82fab18aa7b9308e9",
        "tile": "f05b8a01b6567148bf03b8c9b40dbb5e80d220e4d9df5b500df9cdd24d7eca41",
    }[kind]


_MATERIALS = (
    InteriorMaterial(
        "interior.paint.warm-white-matte.v1",
        "Warm white, matte",
        "Тёплый белый, матовый",
        ("wall", "furniture"),
        "paint",
        "#F2EBDD",
        8,
    ),
    InteriorMaterial(
        "interior.paint.sand-eggshell.v1",
        "Sand, eggshell",
        "Песочный, полуматовый",
        ("wall", "furniture"),
        "paint",
        "#D8C4A8",
        22,
    ),
    InteriorMaterial(
        "interior.paint.sage-matte.v1",
        "Sage, matte",
        "Шалфей, матовый",
        ("wall", "furniture"),
        "paint",
        "#9CA98F",
        7,
    ),
    InteriorMaterial(
        "interior.paint.graphite-satin.v1",
        "Graphite, satin",
        "Графит, сатиновый",
        ("wall", "furniture"),
        "paint",
        "#3F454B",
        38,
    ),
    InteriorMaterial(
        "interior.paint.terracotta-matte.v1",
        "Terracotta, matte",
        "Терракотовый, матовый",
        ("wall", "furniture"),
        "paint",
        "#B9684F",
        9,
    ),
    InteriorMaterial(
        "interior.paint.deep-blue-satin.v1",
        "Deep blue, satin",
        "Глубокий синий, сатиновый",
        ("wall", "furniture"),
        "paint",
        "#263E5A",
        35,
    ),
    InteriorMaterial(
        "interior.wallpaper.linen-warm.v1",
        "Warm linen wallpaper",
        "Тёплые льняные обои",
        ("wall",),
        "wallpaper",
        "#E8DECD",
        4,
        _texture("wallpaper"),
        320,
    ),
    InteriorMaterial(
        "interior.plaster.mineral-light.v1",
        "Light mineral plaster",
        "Светлая минеральная штукатурка",
        ("wall",),
        "plaster",
        "#D6CFC3",
        5,
        _texture("plaster"),
        450,
    ),
    InteriorMaterial(
        "interior.wood.oak-natural.v1",
        "Natural oak",
        "Натуральный дуб",
        ("floor", "furniture"),
        "wood",
        "#B28452",
        24,
        _texture("wood"),
        180,
    ),
    InteriorMaterial(
        "interior.stone.grey-v1",
        "Grey stone",
        "Серый камень",
        ("floor", "furniture"),
        "stone",
        "#AAAAA6",
        12,
        _texture("stone"),
        500,
    ),
    InteriorMaterial(
        "interior.tile.warm-square.v1",
        "Warm square tile",
        "Тёплая квадратная плитка",
        ("floor", "tile"),
        "tile",
        "#DCD7CD",
        42,
        _texture("tile"),
        300,
    ),
)
_BY_ID = {item.id: item for item in _MATERIALS}


def all_materials() -> tuple[InteriorMaterial, ...]:
    return _MATERIALS


def material_by_id(material_id: str) -> InteriorMaterial:
    material = _BY_ID.get(material_id)
    if material is None:
        raise ValidationFailedError("unknown interior material", {"material_id": material_id})
    return material


def texture_bytes(sha256: str) -> bytes:
    data = _TEXTURES.get(sha256)
    if data is None or hashlib.sha256(data).hexdigest() != sha256:
        raise ValidationFailedError("unknown interior material texture", {"sha256": sha256})
    return data


def snapshot_for(material: InteriorMaterial) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "catalog_material_id": material.id,
        "base_color": material.base_color,
        "gloss_pct": material.gloss_pct,
        "roughness": material.roughness,
        "texture_sha256": material.texture_sha256,
        "texture_tile_size_mm": material.texture_tile_size_mm,
    }


def validate_snapshot(value: object, *, node_id: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValidationFailedError("a scene appearance must be an object", {"node_id": node_id})
    expected_keys = set(snapshot_for(_MATERIALS[0]))
    if set(value) != expected_keys:
        raise ValidationFailedError(
            "a scene appearance has unsupported fields", {"node_id": node_id}
        )
    material_id = value.get("catalog_material_id")
    if not isinstance(material_id, str):
        raise ValidationFailedError("a scene appearance needs a catalogue id", {"node_id": node_id})
    expected = snapshot_for(material_by_id(material_id))
    roughness = value.get("roughness")
    if not isinstance(roughness, int | float) or not math.isfinite(float(roughness)):
        raise ValidationFailedError("a scene appearance roughness is invalid", {"node_id": node_id})
    normalized = {**value, "roughness": float(roughness)}
    if normalized != expected:
        raise ValidationFailedError(
            "a scene appearance does not match its immutable catalogue snapshot",
            {"node_id": node_id, "material_id": material_id},
        )
    if expected["texture_sha256"] is not None:
        texture_bytes(str(expected["texture_sha256"]))
    return expected
