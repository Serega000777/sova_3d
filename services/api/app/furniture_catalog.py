"""Small, deterministic furniture catalogue shared by the API and placement job."""

from __future__ import annotations

from typing import TypedDict


class FurnitureSpec(TypedDict):
    kind: str
    name: str
    name_ru: str
    width_mm: float
    depth_mm: float
    height_mm: float


CATALOG: tuple[FurnitureSpec, ...] = (
    {
        "kind": "chair",
        "name": "Chair",
        "name_ru": "Стул",
        "width_mm": 480,
        "depth_mm": 520,
        "height_mm": 860,
    },
    {
        "kind": "table",
        "name": "Table",
        "name_ru": "Стол",
        "width_mm": 1200,
        "depth_mm": 700,
        "height_mm": 750,
    },
    {
        "kind": "sofa",
        "name": "Sofa",
        "name_ru": "Диван",
        "width_mm": 2100,
        "depth_mm": 900,
        "height_mm": 850,
    },
    {
        "kind": "bed",
        "name": "Bed",
        "name_ru": "Кровать",
        "width_mm": 1600,
        "depth_mm": 2100,
        "height_mm": 500,
    },
    {
        "kind": "cabinet",
        "name": "Cabinet",
        "name_ru": "Шкаф",
        "width_mm": 1200,
        "depth_mm": 600,
        "height_mm": 2200,
    },
)
BY_KIND = {item["kind"]: item for item in CATALOG}
