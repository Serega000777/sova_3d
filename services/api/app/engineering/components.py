"""Component Intelligence (T-156, F-035): real components the platform knows the geometry of.

"Add four screws" already resolves to M3×12 (F-025); "a case for a Raspberry Pi 4" needs the
board's outline, its mounting holes, how tall its ports stand and where they poke out. This
catalogue is that knowledge: outlines and hole patterns from the makers' mechanical
drawings, port positions rounded to the millimetre. Every entry says how sure it is; a
maker with calipers can always override.

Coordinates: the board lies in XY with its corner at the origin, X along the long side,
Y along the short side, Z up from the board's top surface.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

Side = Literal["+x", "-x", "+y", "-y"]
Confidence = Literal["datasheet", "measured", "approximate"]


@dataclass(frozen=True)
class Hole:
    x_mm: float
    y_mm: float
    diameter_mm: float


@dataclass(frozen=True)
class Cutout:
    """A port or connector that must reach the outside: where on which side, how big."""

    name: str
    side: Side
    offset_mm: float  # along the side, from the board's origin corner on that axis
    width_mm: float  # along the side
    height_mm: float  # up from the board's top surface
    z_mm: float = 0.0  # gap between the board's top surface and the port's underside


@dataclass(frozen=True)
class Component:
    id: str
    name: str
    aliases: tuple[str, ...]
    kind: Literal["board", "module", "fan", "battery", "motor", "sensor", "display"]
    width_mm: float
    depth_mm: float
    thickness_mm: float  # the PCB or body itself
    height_mm: float  # the tallest thing standing on it, above the top surface
    holes: tuple[Hole, ...]
    screw: str  # the fastener the holes take, e.g. "M2.5"
    cutouts: tuple[Cutout, ...] = ()
    standoff_mm: float = 5.0  # room under the board for solder joints and the SD card
    confidence: Confidence = "datasheet"
    note_en: str = ""
    note_ru: str = ""
    # a window to cut for a display, a fan's air opening: centred on the part, in mm
    opening_mm: tuple[float, float] | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)


def _pi_holes(width: float, depth: float) -> tuple[Hole, ...]:
    """The Raspberry Pi hole pattern: 3.5 mm in from each edge, 58 x 49 mm apart."""
    return (
        Hole(3.5, 3.5, 2.7),
        Hole(3.5 + 58, 3.5, 2.7),
        Hole(3.5, 3.5 + 49, 2.7),
        Hole(3.5 + 58, 3.5 + 49, 2.7),
    )


COMPONENTS: dict[str, Component] = {
    c.id: c
    for c in (
        Component(
            id="raspberry-pi-4b",
            name="Raspberry Pi 4 Model B",
            aliases=(
                "raspberry pi 4",
                "rpi 4",
                "pi 4",
                "распберри пай 4",
                "малина 4",
                "raspberry 4",
            ),
            kind="board",
            width_mm=85.0,
            depth_mm=56.0,
            thickness_mm=1.5,
            height_mm=16.0,
            holes=_pi_holes(85, 56),
            screw="M2.5",
            cutouts=(
                Cutout("Ethernet", "+x", 2.0, 17.0, 14.0),
                Cutout("USB 3.0", "+x", 20.0, 15.5, 16.0),
                Cutout("USB 2.0", "+x", 38.0, 15.5, 16.0),
                Cutout("USB-C power", "-y", 7.0, 10.0, 4.0),
                Cutout("micro HDMI 0", "-y", 20.0, 8.0, 4.0),
                Cutout("micro HDMI 1", "-y", 33.5, 8.0, 4.0),
                Cutout("audio", "-y", 49.0, 7.0, 6.5),
                Cutout("microSD", "-x", 20.0, 13.0, 3.0, z_mm=-3.0),
            ),
            standoff_mm=5.0,
            note_en=(
                "Ports on the two edges per the mechanical drawing; keep 2 mm above the USB "
                "stack for cables."
            ),
            note_ru="Разъёмы на двух рёбрах по чертежу; над USB оставьте 2 мм под кабели.",
            tags=("sbc", "computer"),
        ),
        Component(
            id="raspberry-pi-5",
            name="Raspberry Pi 5",
            aliases=("raspberry pi 5", "rpi 5", "pi 5", "распберри пай 5", "малина 5"),
            kind="board",
            width_mm=85.0,
            depth_mm=56.0,
            thickness_mm=1.5,
            height_mm=17.0,
            holes=_pi_holes(85, 56),
            screw="M2.5",
            cutouts=(
                Cutout("USB 3.0", "+x", 2.0, 15.5, 16.0),
                Cutout("USB 2.0", "+x", 20.0, 15.5, 16.0),
                Cutout("Ethernet", "+x", 38.0, 17.0, 14.0),
                Cutout("USB-C power", "-y", 7.0, 10.0, 4.0),
                Cutout("micro HDMI 0", "-y", 20.0, 8.0, 4.0),
                Cutout("micro HDMI 1", "-y", 33.5, 8.0, 4.0),
                Cutout("power button / UART", "-y", 45.0, 6.0, 4.0),
                Cutout("microSD", "-x", 20.0, 13.0, 3.0, z_mm=-3.0),
            ),
            standoff_mm=5.0,
            note_en=(
                "The Ethernet and USB stacks swapped places against the Pi 4; an active cooler "
                "needs 30 mm of headroom."
            ),
            note_ru=(
                "Ethernet и USB поменялись местами по сравнению с Pi 4; активный кулер требует "
                "30 мм над платой."
            ),
            tags=("sbc", "computer"),
        ),
        Component(
            id="raspberry-pi-zero-2w",
            name="Raspberry Pi Zero 2 W",
            aliases=("pi zero", "raspberry pi zero", "zero 2 w", "zero 2w", "пай зеро", "zero"),
            kind="board",
            width_mm=65.0,
            depth_mm=30.0,
            thickness_mm=1.4,
            height_mm=5.0,
            holes=(
                Hole(3.5, 3.5, 2.75),
                Hole(61.5, 3.5, 2.75),
                Hole(3.5, 26.5, 2.75),
                Hole(61.5, 26.5, 2.75),
            ),
            screw="M2.5",
            cutouts=(
                Cutout("mini HDMI", "-y", 8.5, 12.0, 3.5),
                Cutout("micro USB data", "-y", 36.5, 8.0, 3.0),
                Cutout("micro USB power", "-y", 50.0, 8.0, 3.0),
                Cutout("microSD", "-x", 10.0, 12.0, 2.5, z_mm=-2.5),
            ),
            standoff_mm=4.0,
            note_en="All ports on one long edge; the microSD slot is under the short edge.",
            note_ru="Все разъёмы на одном длинном ребре; слот microSD — под коротким ребром.",
            tags=("sbc", "computer"),
        ),
        Component(
            id="arduino-uno-r3",
            name="Arduino Uno R3",
            aliases=("arduino uno", "uno r3", "uno", "ардуино уно", "arduino"),
            kind="board",
            width_mm=68.6,
            depth_mm=53.3,
            thickness_mm=1.6,
            height_mm=12.0,
            holes=(
                Hole(14.0, 2.5, 3.2),
                Hole(15.3, 50.7, 3.2),
                Hole(66.1, 7.6, 3.2),
                Hole(66.1, 35.5, 3.2),
            ),
            screw="M3",
            cutouts=(
                Cutout("USB-B", "-x", 30.0, 13.0, 11.0),
                Cutout("DC barrel jack", "-x", 3.0, 10.0, 11.0),
            ),
            standoff_mm=5.0,
            note_en="Uno footprint; the USB-B and barrel jack overhang the short edge by 6 mm.",
            note_ru="Посадка Uno; USB-B и разъём питания выступают за короткое ребро на 6 мм.",
            tags=("mcu", "arduino"),
        ),
        Component(
            id="arduino-nano",
            name="Arduino Nano",
            aliases=("nano", "arduino nano", "ардуино нано", "нано"),
            kind="board",
            width_mm=45.0,
            depth_mm=18.0,
            thickness_mm=1.6,
            height_mm=8.0,
            holes=(
                Hole(1.3, 1.3, 1.8),
                Hole(43.7, 1.3, 1.8),
                Hole(1.3, 16.7, 1.8),
                Hole(43.7, 16.7, 1.8),
            ),
            screw="M1.6",
            cutouts=(Cutout("mini USB", "-x", 4.5, 9.0, 4.0),),
            standoff_mm=3.0,
            confidence="approximate",
            note_en="Clones differ by a millimetre; check the USB position before printing.",
            note_ru="Клоны отличаются на миллиметр; проверьте положение USB перед печатью.",
            tags=("mcu", "arduino"),
        ),
        Component(
            id="arduino-mega-2560",
            name="Arduino Mega 2560",
            aliases=("arduino mega", "mega 2560", "mega", "ардуино мега"),
            kind="board",
            width_mm=101.6,
            depth_mm=53.3,
            thickness_mm=1.6,
            height_mm=12.0,
            holes=(
                Hole(14.0, 2.5, 3.2),
                Hole(15.3, 50.7, 3.2),
                Hole(66.1, 7.6, 3.2),
                Hole(66.1, 35.5, 3.2),
                Hole(90.2, 50.7, 3.2),
                Hole(96.5, 2.5, 3.2),
            ),
            screw="M3",
            cutouts=(
                Cutout("USB-B", "-x", 30.0, 13.0, 11.0),
                Cutout("DC barrel jack", "-x", 3.0, 10.0, 11.0),
            ),
            standoff_mm=5.0,
            note_en=(
                "Six mounting holes; the first four match the Uno so a Mega case fits Uno "
                "standoffs."
            ),
            note_ru=(
                "Шесть крепёжных отверстий; первые четыре совпадают с Uno — корпус Mega встаёт на "
                "стойки Uno."
            ),
            tags=("mcu", "arduino"),
        ),
        Component(
            id="esp32-devkitc",
            name="ESP32 DevKitC",
            aliases=("esp32", "esp32 devkit", "devkitc", "эсп32", "есп32"),
            kind="board",
            width_mm=55.0,
            depth_mm=28.0,
            thickness_mm=1.6,
            height_mm=9.0,
            holes=(
                Hole(2.5, 2.5, 3.0),
                Hole(52.5, 2.5, 3.0),
                Hole(2.5, 25.5, 3.0),
                Hole(52.5, 25.5, 3.0),
            ),
            screw="M2.5",
            cutouts=(Cutout("micro USB", "-x", 9.5, 9.0, 4.0),),
            standoff_mm=4.0,
            confidence="approximate",
            note_en=(
                "DevKitC boards have no official mounting holes: these are corner clips' "
                "positions; many clones drill them."
            ),
            note_ru=(
                "У DevKitC нет штатных крепёжных отверстий: это позиции угловых зажимов; многие "
                "клоны их сверлят."
            ),
            tags=("mcu", "wifi"),
        ),
        Component(
            id="raspberry-pi-pico",
            name="Raspberry Pi Pico",
            aliases=("pico", "pi pico", "rp2040", "пико"),
            kind="board",
            width_mm=51.0,
            depth_mm=21.0,
            thickness_mm=1.0,
            height_mm=4.0,
            holes=(
                Hole(4.8, 2.1, 2.1),
                Hole(46.2, 2.1, 2.1),
                Hole(4.8, 18.9, 2.1),
                Hole(46.2, 18.9, 2.1),
            ),
            screw="M2",
            cutouts=(Cutout("micro USB", "-x", 6.5, 8.0, 3.0),),
            standoff_mm=3.0,
            note_en="Castellated edges: keep the long sides clear if headers get soldered on.",
            note_ru="Зубчатые края: оставьте длинные стороны свободными под пайку гребёнок.",
            tags=("mcu",),
        ),
        Component(
            id="oled-096",
            name='OLED 0.96" (SSD1306 module)',
            aliases=("oled", "ssd1306", "oled 0.96", "олед", "дисплей 0.96"),
            kind="display",
            width_mm=27.3,
            depth_mm=27.8,
            thickness_mm=1.2,
            height_mm=3.0,
            holes=(
                Hole(2.0, 2.0, 2.1),
                Hole(25.3, 2.0, 2.1),
                Hole(2.0, 25.8, 2.1),
                Hole(25.3, 25.8, 2.1),
            ),
            screw="M2",
            opening_mm=(22.0, 11.5),
            standoff_mm=3.0,
            confidence="approximate",
            note_en=(
                "Four-pin modules vary by maker; the glass is 26.7 x 19.3, the lit area 21.7 x "
                "10.9 mm."
            ),
            note_ru=(
                "Четырёхпиновые модули у разных производителей отличаются; стекло 26.7 × 19.3, "
                "видимая область 21.7 × 10.9 мм."
            ),
            tags=("display", "i2c"),
        ),
        Component(
            id="fan-40",
            name="40 mm fan",
            aliases=("40 mm fan", "40mm fan", "fan 40", "вентилятор 40", "кулер 40"),
            kind="fan",
            width_mm=40.0,
            depth_mm=40.0,
            thickness_mm=10.0,
            height_mm=0.0,
            holes=(
                Hole(4.0, 4.0, 4.3),
                Hole(36.0, 4.0, 4.3),
                Hole(4.0, 36.0, 4.3),
                Hole(36.0, 36.0, 4.3),
            ),
            screw="M4",
            opening_mm=(37.0, 37.0),
            standoff_mm=0.0,
            note_en=(
                "Standard 40 x 40 x 10 frame, holes on a 32 mm square; airflow needs the 37 mm "
                "opening."
            ),
            note_ru=(
                "Стандартная рамка 40 x 40 x 10, отверстия по квадрату 32 мм; для потока нужно "
                "окно 37 мм."
            ),
            tags=("cooling",),
        ),
        Component(
            id="fan-30",
            name="30 mm fan",
            aliases=("30 mm fan", "30mm fan", "fan 30", "вентилятор 30", "кулер 30"),
            kind="fan",
            width_mm=30.0,
            depth_mm=30.0,
            thickness_mm=7.0,
            height_mm=0.0,
            holes=(
                Hole(3.0, 3.0, 3.2),
                Hole(27.0, 3.0, 3.2),
                Hole(3.0, 27.0, 3.2),
                Hole(27.0, 27.0, 3.2),
            ),
            screw="M3",
            opening_mm=(28.0, 28.0),
            standoff_mm=0.0,
            note_en="Standard 30 x 30 x 7 frame, holes on a 24 mm square.",
            note_ru="Стандартная рамка 30 x 30 x 7, отверстия по квадрату 24 мм.",
            tags=("cooling",),
        ),
        Component(
            id="holder-18650",
            name="18650 cell holder (1 cell)",
            aliases=(
                "18650",
                "18650 holder",
                "аккумулятор 18650",
                "держатель 18650",
                "батарея 18650",
            ),
            kind="battery",
            width_mm=77.0,
            depth_mm=20.5,
            thickness_mm=1.0,
            height_mm=20.0,
            holes=(Hole(9.0, 10.25, 2.5), Hole(68.0, 10.25, 2.5)),
            screw="M2",
            standoff_mm=0.0,
            confidence="approximate",
            note_en=(
                "Plastic holders differ; this is the common Keystone-style one with two screw "
                "slots."
            ),
            note_ru=(
                "Пластиковые держатели различаются; это распространённый тип с двумя пазами под "
                "винты."
            ),
            tags=("power",),
        ),
        Component(
            id="hc-sr04",
            name="HC-SR04 ultrasonic sensor",
            aliases=("hc-sr04", "hcsr04", "ultrasonic", "ультразвуковой датчик", "дальномер"),
            kind="sensor",
            width_mm=45.0,
            depth_mm=20.0,
            thickness_mm=1.2,
            height_mm=12.0,
            holes=(Hole(2.0, 2.0, 1.8), Hole(43.0, 18.0, 1.8)),
            screw="M1.6",
            opening_mm=(42.0, 16.5),
            standoff_mm=2.0,
            note_en="Two 16 mm eyes 26 mm apart: the opening keeps both clear.",
            note_ru="Два «глаза» по 16 мм на расстоянии 26 мм: окно оставляет оба открытыми.",
            tags=("sensor",),
        ),
        Component(
            id="sg90",
            name="SG90 micro servo",
            aliases=("sg90", "micro servo", "серво sg90", "сервопривод"),
            kind="motor",
            width_mm=22.8,
            depth_mm=12.2,
            thickness_mm=22.5,
            height_mm=4.0,
            holes=(Hole(-2.4, 6.1, 2.2), Hole(25.2, 6.1, 2.2)),
            screw="M2",
            standoff_mm=0.0,
            note_en="Mounting tabs stick out 2.4 mm beyond each end; the holes are 27.6 mm apart.",
            note_ru="Крепёжные ушки выступают на 2.4 мм с каждого конца; отверстия на 27.6 мм.",
            tags=("motor",),
        ),
        Component(
            id="nema17",
            name="NEMA 17 stepper motor",
            aliases=("nema 17", "nema17", "шаговый двигатель", "нема 17", "stepper"),
            kind="motor",
            width_mm=42.3,
            depth_mm=42.3,
            thickness_mm=40.0,
            height_mm=2.0,
            holes=(
                Hole(5.65, 5.65, 3.2),
                Hole(36.65, 5.65, 3.2),
                Hole(5.65, 36.65, 3.2),
                Hole(36.65, 36.65, 3.2),
            ),
            screw="M3",
            opening_mm=(22.5, 22.5),
            standoff_mm=0.0,
            note_en="Holes on a 31 mm square; the 22 mm pilot boss needs the opening.",
            note_ru="Отверстия по квадрату 31 мм; центрирующий выступ 22 мм требует окна.",
            tags=("motor", "cnc"),
        ),
    )
}

_WORD = re.compile(r"[a-z0-9а-яё.]+")


def find(text: str, kinds: tuple[str, ...] | None = None) -> Component | None:
    """The component a sentence names, by alias — the longest alias that fits wins, so
    "raspberry pi 4" is not mistaken for "pi 5" and "arduino mega" for "arduino". `kinds`
    narrows the search: a case is built around a board, whatever fan is mentioned too."""
    lowered = " " + " ".join(_WORD.findall(text.lower())) + " "
    best: tuple[int, Component] | None = None
    for component in COMPONENTS.values():
        if kinds is not None and component.kind not in kinds:
            continue
        for alias in component.aliases:
            if f" {alias} " in lowered and (best is None or len(alias) > best[0]):
                best = (len(alias), component)
    return best[1] if best else None


def search(query: str | None, *, limit: int = 50) -> list[Component]:
    if not query or not query.strip():
        return list(COMPONENTS.values())[:limit]
    words = _WORD.findall(query.lower())
    hits = [
        c
        for c in COMPONENTS.values()
        if all(
            any(w in field for field in (c.id, c.name.lower(), *c.aliases, *c.tags)) for w in words
        )
    ]
    return hits[:limit]


def describe(component: Component, language: str = "en") -> dict[str, Any]:
    """The catalogue entry as clients and the planner's prompt see it."""
    return {
        "id": component.id,
        "name": component.name,
        "kind": component.kind,
        "size_mm": [component.width_mm, component.depth_mm, component.thickness_mm],
        "height_mm": component.height_mm,
        "holes": [
            {"x_mm": h.x_mm, "y_mm": h.y_mm, "diameter_mm": h.diameter_mm} for h in component.holes
        ],
        "screw": component.screw,
        "cutouts": [
            {
                "name": c.name,
                "side": c.side,
                "offset_mm": c.offset_mm,
                "width_mm": c.width_mm,
                "height_mm": c.height_mm,
                "z_mm": c.z_mm,
            }
            for c in component.cutouts
        ],
        "opening_mm": list(component.opening_mm) if component.opening_mm else None,
        "standoff_mm": component.standoff_mm,
        "confidence": component.confidence,
        "note": component.note_ru if language == "ru" else component.note_en,
        "aliases": list(component.aliases),
    }
