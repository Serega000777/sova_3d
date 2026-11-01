"""Focused unit tests for the real ASCII DXF house drawing renderer.

Integration coverage (``test_marketplace_api.py``) proves the authorized HTTP route end to
end; these tests check the DXF byte structure directly and cheaply.
"""

from __future__ import annotations

import uuid

from app.engineering.floor_plan import FloorPlan, PlanRoom, PlanWall
from app.services.marketplace import MarketplaceFloorPlanMetadata, MarketplaceHouseMetadata
from app.services.marketplace_documents import DXF_MIME, render_house_dxf


def _plan(*, walls: list[PlanWall], rooms: list[PlanRoom] | None = None) -> FloorPlan:
    return FloorPlan(id="floor", name="Floor", walls=walls, rooms=rooms or [])


def _square_walls(size: float) -> list[PlanWall]:
    corners = [(0.0, 0.0), (size, 0.0), (size, size), (0.0, size)]
    return [
        PlanWall(a=corners[index], b=corners[(index + 1) % 4], thickness_mm=200.0)
        for index in range(4)
    ]


def test_render_house_dxf_has_valid_ascii_structure_and_floor_layers() -> None:
    house = MarketplaceHouseMetadata(
        length_mm=10_000.0,
        width_mm=8_000.0,
        floors=2,
        shape="rectangle",
        gross_floor_area_m2=160.0,
        source="house_box",
        floor_plans=(
            MarketplaceFloorPlanMetadata(
                floor_index=0,
                name="Ground floor",
                elevation_mm=0.0,
                plan=_plan(
                    walls=_square_walls(10_000.0),
                    rooms=[
                        PlanRoom(
                            name="Living",
                            outline=[(0.0, 0.0), (5000.0, 0.0), (5000.0, 5000.0)],
                        )
                    ],
                ),
            ),
            MarketplaceFloorPlanMetadata(
                floor_index=1,
                name="First floor",
                elevation_mm=3_000.0,
                plan=_plan(walls=_square_walls(10_000.0)),
            ),
        ),
    )
    document = render_house_dxf(
        title="Proven house",
        listing_id=uuid.uuid4(),
        version_id=uuid.uuid4(),
        house=house,
    )

    text = document.decode("ascii")
    assert text.startswith("0\r\nSECTION\r\n2\r\nHEADER\r\n")
    assert text.rstrip().endswith("0\r\nEOF")
    assert "$INSUNITS" in text
    assert "AC1009" in text
    assert text.count("SECTION") == 3  # HEADER, TABLES, ENTITIES
    assert "FLOOR_1_WALLS" in text
    assert "FLOOR_2_WALLS" in text
    assert "Floor 1 | Ground floor | elevation 0 mm" in text
    assert "Floor 2 | First floor | elevation 3000 mm" in text
    assert text.count("LINE") >= 8  # four walls per floor, two floors
    assert "POLYLINE" in text  # the one room outline
    assert document.count(b"\n") == document.count(b"\r\n")  # every newline is CRLF


def test_render_house_dxf_stacks_floors_without_overlap() -> None:
    house = MarketplaceHouseMetadata(
        length_mm=10_000.0,
        width_mm=10_000.0,
        floors=2,
        shape="rectangle",
        gross_floor_area_m2=100.0,
        source="house_box",
        floor_plans=(
            MarketplaceFloorPlanMetadata(
                floor_index=0,
                name="Ground floor",
                elevation_mm=0.0,
                plan=_plan(walls=_square_walls(4_000.0)),
            ),
            MarketplaceFloorPlanMetadata(
                floor_index=1,
                name="First floor",
                elevation_mm=3_000.0,
                plan=_plan(walls=_square_walls(4_000.0)),
            ),
        ),
    )
    document = render_house_dxf(
        title="Stack",
        listing_id=uuid.uuid4(),
        version_id=uuid.uuid4(),
        house=house,
    )
    tokens = document.decode("ascii").splitlines()
    pairs = list(zip(tokens[0::2], tokens[1::2], strict=True))

    def y_values_for_layer(layer: str) -> list[float]:
        values: list[float] = []
        current_layer: str | None = None
        for code, value in pairs:
            if code == "0":
                current_layer = None
            elif code == "8":
                current_layer = value
            elif code in ("20", "21") and current_layer == layer:
                values.append(float(value))
        return values

    ground_y = y_values_for_layer("FLOOR_1_WALLS")
    first_y = y_values_for_layer("FLOOR_2_WALLS")
    assert ground_y and first_y
    assert max(ground_y) <= min(first_y)


def test_render_house_dxf_empty_floor_plan_does_not_crash() -> None:
    house = MarketplaceHouseMetadata(
        length_mm=1_000.0,
        width_mm=1_000.0,
        floors=1,
        shape="rectangle",
        gross_floor_area_m2=1.0,
        source="house_box",
        floor_plans=(
            MarketplaceFloorPlanMetadata(
                floor_index=0,
                name="Empty",
                elevation_mm=0.0,
                plan=_plan(walls=[]),
            ),
        ),
    )
    document = render_house_dxf(
        title="Empty",
        listing_id=uuid.uuid4(),
        version_id=uuid.uuid4(),
        house=house,
    )
    text = document.decode("ascii")
    assert "Floor 1 | Empty | elevation 0 mm" in text
    assert text.rstrip().endswith("0\r\nEOF")


def test_dxf_mime_is_a_real_registered_cad_type() -> None:
    assert DXF_MIME == "application/dxf"
