"""Deterministic PDF documents for job-proven marketplace houses.

The renderer intentionally has no browser or office-suite dependency.  It emits a small,
standards-compliant vector PDF from the same validated metadata used by the public listing.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Iterable

from app.engineering.floor_plan import FloorPlan, PlanOpening, PlanWall
from app.services.marketplace import MarketplaceHouseMetadata

PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0


def _pdf_text(value: object) -> str:
    """Return safe WinAnsi-compatible PDF text without pretending to embed Unicode fonts."""
    clean = str(value).encode("cp1252", "replace").decode("cp1252")
    return clean.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _text(x: float, y: float, value: object, size: float = 10.0) -> str:
    return f"BT /F1 {size:.1f} Tf {x:.2f} {y:.2f} Td ({_pdf_text(value)}) Tj ET"


def _line(x1: float, y1: float, x2: float, y2: float, width: float = 1.0) -> str:
    return f"{width:.2f} w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S"


def _polygon(points: Iterable[tuple[float, float]], *, fill: bool = False) -> str:
    rows = list(points)
    if not rows:
        return ""
    commands = [f"{rows[0][0]:.2f} {rows[0][1]:.2f} m"]
    commands.extend(f"{x:.2f} {y:.2f} l" for x, y in rows[1:])
    commands.append("h B" if fill else "h S")
    return " ".join(commands)


def _page_header(title: str, subtitle: str) -> list[str]:
    return [
        "0 G 0 g",
        _text(48, 800, title, 18),
        _text(48, 780, subtitle, 9),
        _line(48, 768, 547, 768, 0.7),
        _text(48, 28, "Generated from validated immutable Sova 3D marketplace evidence", 7),
    ]


def _cover_page(
    *, title: str, listing_id: uuid.UUID, version_id: uuid.UUID, house: MarketplaceHouseMetadata
) -> str:
    rows = _page_header("Sova 3D House Document", "Verified marketplace house summary")
    facts = (
        ("Listing", title),
        ("Listing ID", listing_id),
        ("Immutable version", version_id),
        ("Evidence source", house.source),
        ("Shape", house.shape),
        ("Envelope", f"{house.length_mm:.0f} x {house.width_mm:.0f} mm"),
        ("Floors", house.floors),
        ("Gross floor area", f"{house.gross_floor_area_m2:.3f} m2"),
        ("Floor-plan sheets", len(house.floor_plans)),
    )
    y = 720.0
    for label, value in facts:
        rows.append(_text(58, y, label, 9))
        rows.append(_text(210, y, value, 11))
        y -= 28

    if house.rooms:
        rows.extend((_text(58, y - 8, "Verified rooms", 12), _line(58, y - 16, 537, y - 16, 0.4)))
        y -= 40
        for room in house.rooms:
            rows.append(
                _text(
                    68,
                    y,
                    f"Floor {room.floor_index + 1} | {room.kind} | {room.area_m2:.3f} m2",
                    9,
                )
            )
            y -= 18

    if house.facade is not None:
        facade = house.facade
        y = min(y - 24, 390)
        rows.extend((_text(58, y, "Facade schedule", 12), _line(58, y - 8, 537, y - 8, 0.4)))
        y -= 30
        rows.append(
            _text(
                68,
                y,
                f"Roof {facade.roof} | wall {facade.wall_thickness_mm:.0f} mm | "
                f"floor height {facade.floor_height_mm:.0f} mm",
                9,
            )
        )
        y -= 20
        for opening in facade.openings[:12]:
            floor = str(opening.floor) if opening.floor is not None else "absolute"
            rows.append(
                _text(
                    68,
                    y,
                    f"{opening.opening_id} | {opening.kind} | {opening.side} | floor {floor} | "
                    f"{opening.width_mm:.0f} x {opening.height_mm:.0f} mm",
                    8,
                )
            )
            y -= 16
    return "\n".join(rows)


def _opening_segment(wall: PlanWall, opening: PlanOpening) -> tuple[tuple[float, float], ...]:
    dx = wall.b[0] - wall.a[0]
    dy = wall.b[1] - wall.a[1]
    length = math.hypot(dx, dy)
    if length <= 0:
        return ()
    start = min(float(opening.offset_mm), length)
    end = min(start + float(opening.width_mm), length)
    return (
        (wall.a[0] + dx * start / length, wall.a[1] + dy * start / length),
        (wall.a[0] + dx * end / length, wall.a[1] + dy * end / length),
    )


def _plan_page(*, floor_index: int, name: str, elevation_mm: float, plan: FloorPlan) -> str:
    rows = _page_header(
        f"Floor {floor_index + 1}",
        f"{name} | elevation {elevation_mm:.0f} mm | vector floor plan",
    )
    points = [point for wall in plan.walls for point in (wall.a, wall.b)]
    points.extend(point for room in plan.rooms for point in room.outline)
    points.extend(point for stair in plan.stairs for point in stair.outline)
    if not points:
        rows.append(_text(58, 720, "No proven geometry on this floor.", 11))
        return "\n".join(rows)

    min_x = min(point[0] for point in points)
    max_x = max(point[0] for point in points)
    min_y = min(point[1] for point in points)
    max_y = max(point[1] for point in points)
    scale = min(465 / max(max_x - min_x, 1), 500 / max(max_y - min_y, 1))

    def map_point(point: tuple[float, float]) -> tuple[float, float]:
        return (65 + (point[0] - min_x) * scale, 190 + (point[1] - min_y) * scale)

    rows.append("0.94 g 0.65 G")
    for room in plan.rooms:
        mapped = [map_point(point) for point in room.outline]
        rows.append(_polygon(mapped, fill=True))
        centre_x = sum(point[0] for point in mapped) / len(mapped)
        centre_y = sum(point[1] for point in mapped) / len(mapped)
        kind = room.kind or "room"
        rows.append("0 g")
        rows.append(_text(centre_x - 24, centre_y, kind, 7))

    rows.append("0 G 0 g")
    for wall in plan.walls:
        a = map_point(wall.a)
        b = map_point(wall.b)
        rows.append(_line(*a, *b, max(1.2, min(5.0, wall.thickness_mm * scale / 18))))

    for opening in plan.openings:
        if opening.wall >= len(plan.walls):
            continue
        segment = _opening_segment(plan.walls[opening.wall], opening)
        if len(segment) != 2:
            continue
        a, b = (map_point(point) for point in segment)
        rows.extend(("1 G", _line(*a, *b, 7), "0.35 G", _line(*a, *b, 1)))
        rows.append(
            _text(
                (a[0] + b[0]) / 2 - 4,
                (a[1] + b[1]) / 2 + 5,
                opening.kind[:1].upper(),
                6,
            )
        )

    rows.append("[4 3] 0 d 0.4 G")
    for stair in plan.stairs:
        rows.append(_polygon([map_point(point) for point in stair.outline]))
    rows.append("[] 0 d 0 G")

    rows.append(_text(58, 145, f"Walls: {len(plan.walls)}", 9))
    rows.append(_text(180, 145, f"Openings: {len(plan.openings)}", 9))
    rows.append(_text(320, 145, f"Rooms: {len(plan.rooms)}", 9))
    rows.append(_text(440, 145, f"Stairs: {len(plan.stairs)}", 9))
    rows.append(_text(58, 118, "Legend: D door | W window | O opening | dashed stair", 8))
    return "\n".join(rows)


def _build_pdf(page_streams: list[str]) -> bytes:
    objects: list[bytes] = [b"", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    page_ids: list[int] = []
    for stream in page_streams:
        content = stream.encode("cp1252", "replace")
        content_id = len(objects) + 1
        objects.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
        page_id = len(objects) + 1
        page_ids.append(page_id)
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH:.0f} {PAGE_HEIGHT:.0f}] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
            ).encode()
        )
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[1] = f"<< /Type /Pages /Count {len(page_ids)} /Kids [{kids}] >>".encode()

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n".encode())
        output.extend(body)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(output)


def render_house_pdf(
    *, title: str, listing_id: uuid.UUID, version_id: uuid.UUID, house: MarketplaceHouseMetadata
) -> bytes:
    """Render a cover and one vector sheet per proven floor."""
    pages = [
        _cover_page(
            title=title,
            listing_id=listing_id,
            version_id=version_id,
            house=house,
        )
    ]
    pages.extend(
        _plan_page(
            floor_index=level.floor_index,
            name=level.name,
            elevation_mm=level.elevation_mm,
            plan=level.plan,
        )
        for level in house.floor_plans
    )
    return _build_pdf(pages)
