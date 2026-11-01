"""Deterministic PDF/XLSX/DXF documents for job-proven marketplace houses.

The renderers intentionally have no browser, office-suite or CAD dependency. They emit a small
standards-compliant vector PDF, Office Open XML workbook and ASCII DXF drawing from the same
validated metadata used by the public listing.
"""

from __future__ import annotations

import io
import math
import uuid
import zipfile
from collections.abc import Iterable
from xml.sax.saxutils import escape

from app.engineering.floor_plan import FloorPlan, PlanOpening, PlanWall
from app.services.marketplace import MarketplaceHouseMetadata

PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DXF_MIME = "application/dxf"
_DXF_FLOOR_GAP_MM = 1_000.0


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


def _column_name(index: int) -> str:
    value = index + 1
    output = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        output = chr(65 + remainder) + output
    return output


def _sheet_xml(rows: list[list[object]]) -> str:
    xml_rows: list[str] = []
    for row_index, row in enumerate(rows, start=1):
        cells: list[str] = []
        for column_index, value in enumerate(row):
            reference = f"{_column_name(column_index)}{row_index}"
            if isinstance(value, int | float) and not isinstance(value, bool):
                numeric = float(value)
                if not math.isfinite(numeric):
                    raise ValueError("spreadsheet values must be finite")
                cells.append(f'<c r="{reference}"><v>{numeric:.12g}</v></c>')
            else:
                text = escape(str(value))
                cells.append(
                    f'<c r="{reference}" t="inlineStr"><is><t xml:space="preserve">'
                    f"{text}</t></is></c>"
                )
        xml_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(xml_rows)}</sheetData></worksheet>"
    )


def _xlsx_sheets(
    *, title: str, listing_id: uuid.UUID, version_id: uuid.UUID, house: MarketplaceHouseMetadata
) -> list[tuple[str, list[list[object]]]]:
    summary: list[list[object]] = [
        ["Field", "Value"],
        ["Document", "Sova 3D validated house schedule"],
        ["Listing", title],
        ["Listing ID", str(listing_id)],
        ["Immutable version", str(version_id)],
        ["Evidence source", house.source],
        ["Shape", house.shape],
        ["Length mm", house.length_mm],
        ["Width mm", house.width_mm],
        ["Floors", house.floors],
        ["Gross floor area m2", house.gross_floor_area_m2],
        ["Boundary", "Technical schedule only; not construction documentation or a DWG file"],
    ]
    floors: list[list[object]] = [
        ["Floor", "Name", "Elevation mm", "Walls", "Openings", "Rooms", "Stairs"]
    ]
    for level in house.floor_plans:
        floors.append(
            [
                level.floor_index + 1,
                level.name,
                level.elevation_mm,
                len(level.plan.walls),
                len(level.plan.openings),
                len(level.plan.rooms),
                len(level.plan.stairs),
            ]
        )
    rooms: list[list[object]] = [["Floor", "Name", "Kind", "Area m2"]]
    rooms.extend(
        [[room.floor_index + 1, room.name, room.kind, room.area_m2] for room in house.rooms]
    )
    sheets: list[tuple[str, list[list[object]]]] = [
        ("Summary", summary),
        ("Floors", floors),
        ("Rooms", rooms),
    ]
    if house.facade is not None:
        facade = house.facade
        facade_rows: list[list[object]] = [
            ["Field", "Value"],
            ["Wall thickness mm", facade.wall_thickness_mm],
            ["Floor height mm", facade.floor_height_mm],
            ["Roof", facade.roof],
            ["Roof height mm", facade.roof_height_mm],
            ["Overhang mm", facade.overhang_mm],
            [],
            [
                "Opening ID",
                "Kind",
                "Side",
                "Floor",
                "Center mm",
                "Width mm",
                "Height mm",
                "Sill mm",
            ],
        ]
        facade_rows.extend(
            [
                opening.opening_id,
                opening.kind,
                opening.side,
                opening.floor if opening.floor is not None else "absolute",
                opening.center_mm,
                opening.width_mm,
                opening.height_mm,
                opening.sill_mm,
            ]
            for opening in facade.openings
        )
        sheets.append(("Facade", facade_rows))
    return sheets


def _write_zip_entry(archive: zipfile.ZipFile, name: str, content: str) -> None:
    entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    entry.compress_type = zipfile.ZIP_DEFLATED
    entry.external_attr = 0o600 << 16
    archive.writestr(entry, content.encode("utf-8"))


def render_house_xlsx(
    *, title: str, listing_id: uuid.UUID, version_id: uuid.UUID, house: MarketplaceHouseMetadata
) -> bytes:
    """Render an actual deterministic XLSX schedule from the same validated house evidence."""
    sheets = _xlsx_sheets(
        title=title,
        listing_id=listing_id,
        version_id=version_id,
        house=house,
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        + "".join(
            f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for index in range(1, len(sheets) + 1)
        )
        + "</Types>"
    )
    package_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>'
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
        + "".join(
            f'<sheet name="{escape(name)}" sheetId="{index}" r:id="rId{index}"/>'
            for index, (name, _) in enumerate(sheets, start=1)
        )
        + "</sheets></workbook>"
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            f'<Relationship Id="rId{index}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{index}.xml"/>'
            for index in range(1, len(sheets) + 1)
        )
        + "</Relationships>"
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        _write_zip_entry(archive, "[Content_Types].xml", content_types)
        _write_zip_entry(archive, "_rels/.rels", package_rels)
        _write_zip_entry(archive, "xl/workbook.xml", workbook)
        _write_zip_entry(archive, "xl/_rels/workbook.xml.rels", workbook_rels)
        for index, (_, rows) in enumerate(sheets, start=1):
            _write_zip_entry(archive, f"xl/worksheets/sheet{index}.xml", _sheet_xml(rows))
    return output.getvalue()


def _dxf_pair(code: int, value: object) -> str:
    return f"{code}\r\n{value}\r\n"


def _dxf_line(layer: str, x1: float, y1: float, x2: float, y2: float) -> str:
    return (
        _dxf_pair(0, "LINE")
        + _dxf_pair(8, layer)
        + _dxf_pair(10, f"{x1:.3f}")
        + _dxf_pair(20, f"{y1:.3f}")
        + _dxf_pair(30, "0.0")
        + _dxf_pair(11, f"{x2:.3f}")
        + _dxf_pair(21, f"{y2:.3f}")
        + _dxf_pair(31, "0.0")
    )


def _dxf_polyline(layer: str, points: Iterable[tuple[float, float]], *, closed: bool) -> str:
    rows = list(points)
    if len(rows) < 2:
        return ""
    chunks = [
        _dxf_pair(0, "POLYLINE")
        + _dxf_pair(8, layer)
        + _dxf_pair(66, 1)
        + _dxf_pair(70, 1 if closed else 0)
    ]
    for x, y in rows:
        chunks.append(
            _dxf_pair(0, "VERTEX")
            + _dxf_pair(8, layer)
            + _dxf_pair(10, f"{x:.3f}")
            + _dxf_pair(20, f"{y:.3f}")
            + _dxf_pair(30, "0.0")
        )
    chunks.append(_dxf_pair(0, "SEQEND") + _dxf_pair(8, layer))
    return "".join(chunks)


def _dxf_text(layer: str, x: float, y: float, height: float, value: object) -> str:
    safe = str(value).replace("\n", " ").replace("\r", " ")
    return (
        _dxf_pair(0, "TEXT")
        + _dxf_pair(8, layer)
        + _dxf_pair(10, f"{x:.3f}")
        + _dxf_pair(20, f"{y:.3f}")
        + _dxf_pair(30, "0.0")
        + _dxf_pair(40, f"{height:.3f}")
        + _dxf_pair(1, safe)
    )


def _dxf_layer_table(names: Iterable[str]) -> str:
    unique = list(dict.fromkeys(names))
    rows = [
        _dxf_pair(0, "SECTION")
        + _dxf_pair(2, "TABLES")
        + _dxf_pair(0, "TABLE")
        + _dxf_pair(2, "LAYER")
        + _dxf_pair(70, len(unique))
    ]
    for layer_name in unique:
        rows.append(
            _dxf_pair(0, "LAYER")
            + _dxf_pair(2, layer_name)
            + _dxf_pair(70, 0)
            + _dxf_pair(62, 7)
            + _dxf_pair(6, "CONTINUOUS")
        )
    rows.append(_dxf_pair(0, "ENDTAB") + _dxf_pair(0, "ENDSEC"))
    return "".join(rows)


def _floor_layers(floor_index: int) -> list[str]:
    base = f"FLOOR_{floor_index + 1}"
    return [f"{base}_WALLS", f"{base}_ROOMS", f"{base}_OPENINGS", f"{base}_STAIRS", f"{base}_TEXT"]


def _plan_points(plan: FloorPlan) -> list[tuple[float, float]]:
    points = [point for wall in plan.walls for point in (wall.a, wall.b)]
    points.extend(point for room in plan.rooms for point in room.outline)
    points.extend(point for stair in plan.stairs for point in stair.outline)
    return points


def _plan_dxf_entities(
    *,
    floor_index: int,
    name: str,
    elevation_mm: float,
    plan: FloorPlan,
    y_offset: float,
    label_y: float,
) -> tuple[str, list[str]]:
    walls_layer, rooms_layer, openings_layer, stairs_layer, text_layer = _floor_layers(floor_index)

    def shift(point: tuple[float, float]) -> tuple[float, float]:
        return (point[0], point[1] + y_offset)

    chunks = [
        _dxf_text(
            text_layer,
            0.0,
            label_y,
            180.0,
            f"Floor {floor_index + 1} | {name} | elevation {elevation_mm:.0f} mm",
        )
    ]
    for wall in plan.walls:
        a = shift(wall.a)
        b = shift(wall.b)
        chunks.append(_dxf_line(walls_layer, a[0], a[1], b[0], b[1]))
    for room in plan.rooms:
        outline = [shift(point) for point in room.outline]
        chunks.append(_dxf_polyline(rooms_layer, outline, closed=True))
        if outline:
            centre_x = sum(point[0] for point in outline) / len(outline)
            centre_y = sum(point[1] for point in outline) / len(outline)
            chunks.append(
                _dxf_text(text_layer, centre_x, centre_y, 120.0, room.kind or room.name)
            )
    for opening in plan.openings:
        if opening.wall >= len(plan.walls):
            continue
        segment = _opening_segment(plan.walls[opening.wall], opening)
        if len(segment) != 2:
            continue
        a, b = (shift(point) for point in segment)
        chunks.append(_dxf_line(openings_layer, a[0], a[1], b[0], b[1]))
        chunks.append(
            _dxf_text(
                text_layer,
                (a[0] + b[0]) / 2,
                (a[1] + b[1]) / 2 + 20.0,
                90.0,
                opening.kind[:1].upper(),
            )
        )
    for stair in plan.stairs:
        outline = [shift(point) for point in stair.outline]
        chunks.append(_dxf_polyline(stairs_layer, outline, closed=True))
    return "".join(chunks), [walls_layer, rooms_layer, openings_layer, stairs_layer, text_layer]


def render_house_dxf(
    *, title: str, listing_id: uuid.UUID, version_id: uuid.UUID, house: MarketplaceHouseMetadata
) -> bytes:
    """Render one ASCII DXF R12 drawing stacking every proven floor's walls/rooms/openings/stairs.

    This is a real, open CAD-interchange format (millimetre units, every mainstream CAD
    application imports it), not a proprietary binary DWG file and not construction
    documentation on its own.
    """
    layer_names: list[str] = []
    body_chunks: list[str] = []
    cumulative_y = 0.0
    for level in house.floor_plans:
        points = _plan_points(level.plan)
        min_y = min((point[1] for point in points), default=0.0)
        max_y = max((point[1] for point in points), default=0.0)
        offset = cumulative_y - min_y
        entities, layers = _plan_dxf_entities(
            floor_index=level.floor_index,
            name=level.name,
            elevation_mm=level.elevation_mm,
            plan=level.plan,
            y_offset=offset,
            label_y=cumulative_y + (max_y - min_y) + 150.0,
        )
        body_chunks.append(entities)
        layer_names.extend(layers)
        cumulative_y += (max_y - min_y) + _DXF_FLOOR_GAP_MM

    title_block = _dxf_text(
        "TITLE",
        0.0,
        cumulative_y,
        220.0,
        f"Sova 3D house | {title} | listing {listing_id} | version {version_id} | units mm | "
        "technical schedule only, not construction documentation",
    )
    header_section = (
        _dxf_pair(0, "SECTION")
        + _dxf_pair(2, "HEADER")
        + _dxf_pair(9, "$ACADVER")
        + _dxf_pair(1, "AC1009")
        + _dxf_pair(9, "$INSUNITS")
        + _dxf_pair(70, 4)
        + _dxf_pair(0, "ENDSEC")
    )
    layer_table = _dxf_layer_table(["TITLE", *layer_names])
    entities_section = (
        _dxf_pair(0, "SECTION")
        + _dxf_pair(2, "ENTITIES")
        + title_block
        + "".join(body_chunks)
        + _dxf_pair(0, "ENDSEC")
    )
    document = header_section + layer_table + entities_section + _dxf_pair(0, "EOF")
    return document.encode("ascii", "replace")
