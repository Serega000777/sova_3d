"""Engineering knowledge base (T-116, F-005): the numbers an FDM engineer carries in their head.

Everything here is deterministic and cited by the assistant; nothing here is learned or
guessed at run time. Values are conservative desktop-FDM rules of thumb — good enough to
keep a beginner out of trouble, and labelled as rules of thumb in every answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Load = Literal["cosmetic", "structural", "load_bearing"]
Fit = Literal["clearance", "sliding", "transition", "press"]
FastenerUse = Literal["clearance", "tap", "heat_set"]

LOADS: tuple[Load, ...] = ("cosmetic", "structural", "load_bearing")
FITS: tuple[Fit, ...] = ("clearance", "sliding", "transition", "press")


@dataclass(frozen=True)
class MaterialKnowledge:
    id: str
    name: str
    tensile_mpa: float
    modulus_gpa: float
    max_service_c: float
    uv_resistant: bool
    flexible: bool
    impact: Literal["low", "medium", "high"]
    # Minimum walls that hold up in practice, by what the wall has to do (mm, 0.4 nozzle).
    wall_cosmetic_mm: float
    wall_structural_mm: float
    wall_load_bearing_mm: float
    # FDM holes come out smaller than modelled; add this before asking for a size.
    hole_undersize_mm: float
    ease: Literal["easy", "medium", "hard"]
    good_for: tuple[str, ...]
    avoid_for: tuple[str, ...]
    note_en: str
    note_ru: str


# Typical printed density (g/cm³) — what a part weighs, for "make it lighter" (F-007).
DENSITY_G_CM3: dict[str, float] = {"pla": 1.24, "petg": 1.27, "abs": 1.04, "tpu": 1.21, "asa": 1.07}

# Ordered by how often a beginner should reach for them.
MATERIALS: dict[str, MaterialKnowledge] = {
    "pla": MaterialKnowledge(
        id="pla",
        name="PLA",
        tensile_mpa=50,
        modulus_gpa=3.5,
        max_service_c=55,
        uv_resistant=False,
        flexible=False,
        impact="low",
        wall_cosmetic_mm=0.8,
        wall_structural_mm=1.6,
        wall_load_bearing_mm=2.5,
        hole_undersize_mm=0.2,
        ease="easy",
        good_for=("indoor", "prototype", "decor", "organizer", "toy"),
        avoid_for=("outdoor", "car", "hot", "flex", "impact"),
        note_en="Stiff and easy to print; brittle and softens above ~55 °C.",
        note_ru="Жёсткий и простой в печати; хрупкий, размягчается выше ~55 °C.",
    ),
    "petg": MaterialKnowledge(
        id="petg",
        name="PETG",
        tensile_mpa=50,
        modulus_gpa=2.1,
        max_service_c=75,
        uv_resistant=False,
        flexible=False,
        impact="medium",
        wall_cosmetic_mm=0.8,
        wall_structural_mm=1.6,
        wall_load_bearing_mm=2.4,
        hole_undersize_mm=0.3,
        ease="medium",
        good_for=("indoor", "kitchen", "bracket", "container", "mechanical", "water"),
        avoid_for=("outdoor_sun", "hot"),
        note_en="Tougher than PLA, some give, water resistant; strings a little.",
        note_ru="Прочнее PLA, чуть пружинит, не боится воды; немного тянет нити.",
    ),
    "abs": MaterialKnowledge(
        id="abs",
        name="ABS",
        tensile_mpa=40,
        modulus_gpa=2.0,
        max_service_c=95,
        uv_resistant=False,
        flexible=False,
        impact="high",
        wall_cosmetic_mm=1.0,
        wall_structural_mm=1.8,
        wall_load_bearing_mm=2.8,
        hole_undersize_mm=0.3,
        ease="hard",
        good_for=("hot", "car_interior", "impact", "mechanical", "enclosure"),
        avoid_for=("outdoor_sun", "large_flat"),
        note_en="Takes heat and knocks; warps without an enclosure.",
        note_ru="Держит нагрев и удары; без закрытой камеры коробится.",
    ),
    "tpu": MaterialKnowledge(
        id="tpu",
        name="TPU 95A",
        tensile_mpa=30,
        modulus_gpa=0.08,
        max_service_c=70,
        uv_resistant=True,
        flexible=True,
        impact="high",
        wall_cosmetic_mm=1.2,
        wall_structural_mm=2.0,
        wall_load_bearing_mm=3.0,
        hole_undersize_mm=0.4,
        ease="hard",
        good_for=("flex", "gasket", "bumper", "grip", "phone_case", "seal"),
        avoid_for=("rigid", "precise", "structural"),
        note_en="Flexible and tough; slow to print and never rigid.",
        note_ru="Гибкий и живучий; печатается медленно и никогда не бывает жёстким.",
    ),
    "asa": MaterialKnowledge(
        id="asa",
        name="ASA",
        tensile_mpa=45,
        modulus_gpa=2.0,
        max_service_c=95,
        uv_resistant=True,
        flexible=False,
        impact="high",
        wall_cosmetic_mm=1.0,
        wall_structural_mm=1.8,
        wall_load_bearing_mm=2.8,
        hole_undersize_mm=0.3,
        ease="hard",
        good_for=("outdoor", "outdoor_sun", "car", "hot", "impact", "garden"),
        avoid_for=("large_flat",),
        note_en="ABS that survives sunlight; the outdoor default.",
        note_ru="ABS, который переживает солнце; выбор по умолчанию для улицы.",
    ),
}


@dataclass(frozen=True)
class Fastener:
    """Metric screw sizes and what to model for them in plastic (mm)."""

    name: str
    nominal_mm: float
    clearance_mm: float  # the screw passes through freely (ISO 273 medium)
    tap_mm: float  # a self-tapping/thread-forming screw bites into the plastic
    heat_set_mm: float  # bore for a common brass heat-set insert
    head_mm: float  # socket head diameter, for counterbores


FASTENERS: dict[str, Fastener] = {
    "m2": Fastener("M2", 2.0, 2.4, 1.8, 3.2, 3.8),
    "m2.5": Fastener("M2.5", 2.5, 2.9, 2.2, 3.5, 4.5),
    "m3": Fastener("M3", 3.0, 3.4, 2.7, 4.0, 5.5),
    "m4": Fastener("M4", 4.0, 4.5, 3.6, 5.6, 7.0),
    "m5": Fastener("M5", 5.0, 5.5, 4.5, 6.4, 8.5),
    "m6": Fastener("M6", 6.0, 6.6, 5.4, 8.0, 10.0),
    "m8": Fastener("M8", 8.0, 9.0, 7.2, 10.0, 13.0),
}

# How much to add to (or take from) a nominal size for a part to fit another (mm, FDM).
FIT_ALLOWANCE_MM: dict[Fit, float] = {
    "clearance": 0.5,  # drops in, rattles a little
    "sliding": 0.3,  # slides without play you can feel
    "transition": 0.1,  # pushes in by hand, stays put
    "press": -0.15,  # needs force; holds
}

FIT_WORDS_RU: dict[Fit, str] = {
    "clearance": "свободная посадка",
    "sliding": "скользящая посадка",
    "transition": "плотная посадка",
    "press": "посадка с натягом",
}
# "для скользящей посадки": the genitive, for sentences that need it
FIT_WORDS_RU_GENITIVE: dict[Fit, str] = {
    "clearance": "свободной посадки",
    "sliding": "скользящей посадки",
    "transition": "плотной посадки",
    "press": "посадки с натягом",
}

# A 0.4 mm nozzle lays a ~0.45 mm line; walls should be whole lines wide.
DEFAULT_NOZZLE_MM = 0.4
LINE_FACTOR = 1.125

# Above this the part is a lever for the load; walls need to grow with it.
SLENDER_RATIO = 20.0


def material(material_id: str | None) -> MaterialKnowledge:
    """The material asked for, PLA when nothing was."""
    return MATERIALS.get((material_id or "pla").lower(), MATERIALS["pla"])


def recommended_wall_mm(
    material_id: str | None, load: Load = "structural", nozzle_mm: float = DEFAULT_NOZZLE_MM
) -> float:
    """The wall to model for the material and the job it has to do, rounded to whole lines."""
    known = material(material_id)
    base = {
        "cosmetic": known.wall_cosmetic_mm,
        "structural": known.wall_structural_mm,
        "load_bearing": known.wall_load_bearing_mm,
    }[load]
    line = nozzle_mm * LINE_FACTOR
    lines = max(2, -(-base // line))  # ceil to whole extrusion lines, never fewer than two
    return round(lines * line, 2)


def hole_for(
    fastener: Fastener,
    use: FastenerUse,
    material_id: str | None,
    undersize_mm: float | None = None,
) -> float:
    """The diameter to model so the printed hole comes out right for the screw.

    `undersize_mm` is what this printer was measured to lose on a hole (F-029); without
    a calibration the material's typical figure is used.
    """
    known = material(material_id)
    modelled = {
        "clearance": fastener.clearance_mm,
        "tap": fastener.tap_mm,
        "heat_set": fastener.heat_set_mm,
    }[use]
    shrink = known.hole_undersize_mm if undersize_mm is None else max(undersize_mm, 0.0)
    return round(modelled + shrink, 2)


def fastener_for(text: str) -> Fastener | None:
    """Find an M-size in free text ("под М5", "m3 screws")."""
    import re

    match = re.search(r"\b[mм]\s?(\d(?:[.,]\d)?)\b", text, re.IGNORECASE)
    if not match:
        return None
    key = "m" + match.group(1).replace(",", ".")
    return FASTENERS.get(key)


def fit_allowance_mm(fit: Fit, material_id: str | None) -> float:
    """What to add to a nominal size for the fit, with the material's own shrink."""
    known = material(material_id)
    extra = FIT_ALLOWANCE_MM[fit]
    if fit != "press":
        extra += max(known.hole_undersize_mm - 0.2, 0.0)  # stringy materials close gaps
    return round(extra, 2)


def rank_materials(purpose_words: set[str]) -> list[tuple[MaterialKnowledge, int, list[str]]]:
    """Materials scored against what the part is for; ties keep the beginner-friendly order."""
    ranked: list[tuple[MaterialKnowledge, int, list[str]]] = []
    for known in MATERIALS.values():
        score = 0
        reasons: list[str] = []
        for word in purpose_words:
            if word in known.good_for:
                score += 2
                reasons.append(word)
            if word in known.avoid_for:
                score -= 3
                reasons.append(f"not {word}")
        score += {"easy": 1, "medium": 0, "hard": -1}[known.ease]
        ranked.append((known, score, reasons))
    ranked.sort(key=lambda item: -item[1])
    return ranked


# Words in a question or purpose that map onto material traits (RU and EN).
PURPOSE_WORDS: dict[str, tuple[str, ...]] = {
    "outdoor": ("outdoor", "outside", "garden", "улиц", "сад", "балкон", "двор"),
    "outdoor_sun": ("sun", "солнц", "uv", "уф"),
    "car": ("car", "auto", "машин", "авто", "салон"),
    "hot": ("hot", "heat", "boil", "engine", "горяч", "нагрев", "кипят", "двигател"),
    "flex": ("flex", "bend", "soft", "гибк", "мягк", "гнут"),
    "impact": ("impact", "drop", "hit", "удар", "падени"),
    "kitchen": ("kitchen", "food", "dish", "кухн", "еда", "посуд"),
    "water": ("water", "wet", "shower", "вод", "влаг", "душ"),
    "toy": ("toy", "kid", "child", "игруш", "дет"),
    "decor": ("decor", "vase", "figure", "декор", "ваз", "фигур"),
    "organizer": ("organizer", "holder", "stand", "органайз", "держат", "подстав"),
    "bracket": ("bracket", "mount", "hook", "кронштейн", "крепл", "крюк"),
    "mechanical": ("gear", "hinge", "mechanism", "шестерн", "петл", "механизм"),
    "enclosure": ("enclosure", "case", "box", "корпус", "коробк"),
    "gasket": ("gasket", "seal", "прокладк", "уплотн"),
    "grip": ("grip", "handle", "ручк", "хват"),
    "phone_case": ("phone case", "чехол"),
}


def purpose_words(text: str) -> set[str]:
    lowered = text.lower()
    return {trait for trait, cues in PURPOSE_WORDS.items() if any(cue in lowered for cue in cues)}
