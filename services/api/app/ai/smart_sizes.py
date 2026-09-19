"""Smart dimensions (T-120, F-025): sizes that mean something, not Scale → 110 %.

"Сделай отверстие под M5", "подгони под трубу Ø32", "чтобы сюда помещался iPhone 17 Pro Max
в чехле", "добавь 0,3 мм допуска под PETG". The planner resolves the thing named into
millimetres from a catalogue and the engineering knowledge base, asks when the thing is
ambiguous, and changes only the parameter that thing decides — never the whole model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.engineering import knowledge as kb


@dataclass(frozen=True)
class KnownObject:
    """Something a part is often made to hold; sizes in mm (width, depth, height)."""

    id: str
    name: str
    width_mm: float
    depth_mm: float
    height_mm: float
    aliases: tuple[str, ...]
    # How much a common case adds on each side / to the thickness.
    case_side_mm: float = 0.0
    case_thickness_mm: float = 0.0


# Public sizes, rounded to the half millimetre; the fit allowance is added on top.
OBJECTS: tuple[KnownObject, ...] = (
    KnownObject("iphone-17", "iPhone 17", 71.5, 149.5, 8.0, ("iphone 17",), 2.0, 2.0),
    KnownObject("iphone-17-pro", "iPhone 17 Pro", 72.0, 150.0, 8.8, ("iphone 17 pro",), 2.0, 2.0),
    KnownObject(
        "iphone-17-pro-max",
        "iPhone 17 Pro Max",
        78.0,
        163.5,
        8.8,
        ("iphone 17 pro max", "17 pro max"),
        2.0,
        2.0,
    ),
    KnownObject("iphone-16", "iPhone 16", 71.5, 147.5, 7.8, ("iphone 16",), 2.0, 2.0),
    KnownObject("iphone-16-pro", "iPhone 16 Pro", 71.5, 149.5, 8.3, ("iphone 16 pro",), 2.0, 2.0),
    KnownObject(
        "iphone-16-pro-max",
        "iPhone 16 Pro Max",
        78.0,
        163.0,
        8.3,
        ("iphone 16 pro max", "16 pro max"),
        2.0,
        2.0,
    ),
    KnownObject("iphone-15", "iPhone 15", 71.5, 147.5, 7.8, ("iphone 15",), 2.0, 2.0),
    KnownObject(
        "galaxy-s25", "Samsung Galaxy S25", 70.5, 146.5, 7.2, ("galaxy s25", "s25"), 2.0, 2.0
    ),
    KnownObject(
        "galaxy-s25-ultra",
        "Samsung Galaxy S25 Ultra",
        78.0,
        162.5,
        8.2,
        ("galaxy s25 ultra", "s25 ultra"),
        2.0,
        2.0,
    ),
    KnownObject(
        "macbook-air-13", "MacBook Air 13", 304.0, 215.0, 11.5, ("macbook air 13", "air 13")
    ),
    KnownObject(
        "macbook-air-15", "MacBook Air 15", 340.5, 237.5, 11.5, ("macbook air 15", "air 15")
    ),
    KnownObject(
        "macbook-pro-14", "MacBook Pro 14", 312.5, 221.0, 15.5, ("macbook pro 14", "pro 14")
    ),
    KnownObject(
        "macbook-pro-16", "MacBook Pro 16", 355.5, 248.0, 16.8, ("macbook pro 16", "pro 16")
    ),
    KnownObject("ipad-air-11", "iPad Air 11", 178.5, 247.5, 6.1, ("ipad air 11", "ipad air")),
    KnownObject("ipad-pro-13", "iPad Pro 13", 215.5, 281.5, 5.1, ("ipad pro 13",)),
    KnownObject("aa", "AA battery", 14.5, 14.5, 50.5, ("aa battery", "батарейка aa", "aa ")),
    KnownObject("aaa", "AAA battery", 10.5, 10.5, 44.5, ("aaa battery", "батарейка aaa", "aaa ")),
    KnownObject("18650", "18650 cell", 18.5, 18.5, 65.5, ("18650",)),
    KnownObject("cr2032", "CR2032 coin cell", 20.0, 20.0, 3.2, ("cr2032",)),
    KnownObject(
        "sd-card", "SD card", 24.0, 32.0, 2.1, ("sd card", "sd-карт", "sd карт", "карта sd")
    ),
    KnownObject("microsd", "microSD card", 11.0, 15.0, 1.0, ("microsd", "micro sd", "микро sd")),
    KnownObject(
        "credit-card",
        "credit card",
        85.6,
        54.0,
        0.8,
        ("credit card", "bank card", "банковск", "кредитн", "визитк"),
    ),
    KnownObject(
        "raspberry-pi-4", "Raspberry Pi 4", 85.0, 56.0, 17.0, ("raspberry pi 4", "pi 4", "rpi4")
    ),
    KnownObject(
        "raspberry-pi-5", "Raspberry Pi 5", 85.0, 56.0, 17.0, ("raspberry pi 5", "pi 5", "rpi5")
    ),
    KnownObject(
        "arduino-uno", "Arduino Uno", 68.6, 53.4, 15.0, ("arduino uno", "arduino", "ардуино")
    ),
    KnownObject(
        "esp32-devkit", "ESP32 DevKit", 55.0, 28.0, 13.0, ("esp32 devkit", "esp32", "esp-32")
    ),
    KnownObject("pen", "pen", 12.0, 12.0, 145.0, ("pens", "pen ", "ручк", "карандаш")),
    KnownObject("airpods-pro", "AirPods Pro case", 45.5, 61.0, 21.5, ("airpods pro", "airpods")),
    KnownObject("apple-watch", "Apple Watch", 45.0, 38.0, 11.0, ("apple watch", "часы")),
)

# A family named without its model: ask which one (the sizes differ by centimetres).
FAMILIES: dict[str, tuple[str, ...]] = {
    "iphone": ("iphone-17", "iphone-17-pro", "iphone-17-pro-max", "iphone-16", "iphone-15"),
    "macbook": ("macbook-air-13", "macbook-air-15", "macbook-pro-14", "macbook-pro-16"),
    "ipad": ("ipad-air-11", "ipad-pro-13"),
    "galaxy": ("galaxy-s25", "galaxy-s25-ultra"),
    "raspberry": ("raspberry-pi-4", "raspberry-pi-5"),
}

BY_ID = {obj.id: obj for obj in OBJECTS}

_CASE = ("в чехле", "with a case", "with case", "in a case", "in its case", "в кейсе")
_HOLDER = ("holder", "stand", "dock", "держат", "подстав", "докстанц", "док-станц")
_FASTENER_HOLE = re.compile(
    r"(?:(\d+)\s*(?:x|×)?\s*)?(?:hole|holes|отверсти\w*|дыр\w*|под|for)\D{0,12}?"
    r"[mм]\s?(\d(?:[.,]\d)?)\b",
    re.IGNORECASE,
)
# "M4 holes", with the size first.
_FASTENER_HOLE_FIRST = re.compile(
    r"(?:(\d+)\s*(?:x|×)?\s*)?[mм]\s?(\d(?:[.,]\d)?)\s*(?:hole|holes|отверсти\w*|дыр\w*)",
    re.IGNORECASE,
)
_TOLERANCE = re.compile(
    r"(?:допуск\w*|зазор\w*|tolerance|clearance|allowance)\D{0,16}?(\d+(?:[.,]\d+)?)\s*(mm|мм)"
    r"|(\d+(?:[.,]\d+)?)\s*(mm|мм)\s*(?:допуск\w*|зазор\w*|tolerance|clearance|allowance)",
    re.IGNORECASE,
)
_PIPE = re.compile(
    r"(?:труб\w*|pipe|tube|rod|стерж\w*|штанг\w*)\D{0,12}?(?:ø|⌀|d)?\s*(\d+(?:[.,]\d+)?)\s*(mm|мм)?",
    re.IGNORECASE,
)

# "Ø32 mm pipe": the size before the word.
_PIPE_FIRST = re.compile(
    r"(?:ø|⌀)\s*(\d+(?:[.,]\d+)?)\s*(mm|мм|cm|см)?\s*(?:труб\w*|pipe|tube|rod|стерж\w*)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ObjectMatch:
    object: KnownObject
    in_case: bool
    holder: bool

    def cavity_mm(self, material_id: str | None) -> tuple[float, float, float]:
        """The pocket that takes the object: its size, the case, and a sliding fit."""
        gap = kb.fit_allowance_mm("sliding", material_id)
        width = self.object.width_mm + gap
        depth = self.object.depth_mm + gap
        height = self.object.height_mm + gap
        if self.in_case:
            width += 2 * self.object.case_side_mm
            depth += 2 * self.object.case_side_mm
            height += self.object.case_thickness_mm
        return round(width, 2), round(depth, 2), round(height, 2)


@dataclass(frozen=True)
class Ambiguous:
    family: str
    candidates: tuple[KnownObject, ...]


def find_object(text: str) -> ObjectMatch | Ambiguous | None:
    """The thing the part must hold, the most specific name winning ("17 pro max" over "17")."""
    lowered = " " + text.lower() + " "
    best: KnownObject | None = None
    best_len = 0
    for obj in OBJECTS:
        for alias in obj.aliases:
            if alias in lowered and len(alias) > best_len:
                best, best_len = obj, len(alias)
    if best is None:
        for family, ids in FAMILIES.items():
            if family in lowered:
                return Ambiguous(family, tuple(BY_ID[i] for i in ids))
        return None
    return ObjectMatch(
        object=best,
        in_case=any(cue in lowered for cue in _CASE),
        holder=any(cue in lowered for cue in _HOLDER),
    )


def fastener_hole(text: str, material_id: str | None) -> tuple[int, float, str] | None:
    """(count, diameter, "M5 clearance") for "holes for M5" / "отверстия под М3"."""
    match = _FASTENER_HOLE.search(text) or _FASTENER_HOLE_FIRST.search(text)
    if not match:
        return None
    fastener = kb.FASTENERS.get("m" + match.group(2).replace(",", "."))
    if fastener is None:
        return None
    lowered = text.lower()
    use: kb.FastenerUse = "clearance"
    if any(cue in lowered for cue in ("вплав", "insert", "heat", "втулк")):
        use = "heat_set"
    elif any(cue in lowered for cue in ("саморез", "нарез", "self-tap", "tap ", "вкрут")):
        use = "tap"
    count = int(match.group(1) or 1)
    return count, kb.hole_for(fastener, use, material_id), f"{fastener.name} {use}"


def tolerance_mm(text: str) -> float | None:
    """The allowance asked for ("добавь 0,3 мм допуска", "0.3 mm clearance")."""
    match = _TOLERANCE.search(text)
    if not match:
        return None
    value = match.group(1) or match.group(3)
    return float(value.replace(",", ".")) if value else None


def pipe_mm(text: str) -> float | None:
    """The pipe or rod the part must take, by its diameter."""
    match = _PIPE.search(text) or _PIPE_FIRST.search(text)
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    return value * (10.0 if (match.group(2) or "").lower() in ("cm", "см") else 1.0)


def material_in(text: str) -> str | None:
    lowered = text.lower()
    for material_id in ("petg", "abs", "asa", "tpu", "pla"):
        if re.search(r"\b" + material_id + r"\b", lowered):
            return material_id
    return None
