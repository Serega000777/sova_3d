"""Item 41: the text-to-house parser is strict, deterministic and fail-closed."""

import pytest

from app.engineering.house_box import HouseBoxRequest
from app.engineering.house_text import HouseTextError, parse_house_text

CANONICAL = {
    "length_mm": 12_000,
    "width_mm": 8_000,
    "floor_height_mm": 3_000,
    "floors": 2,
    "shape": "rectangle",
}


@pytest.mark.parametrize(
    ("prompt", "language"),
    [
        ("Создай двухэтажный прямоугольный дом 12 × 8 м, высота этажа 3 м", "ru"),
        ("Построй дом длиной 1200 см и шириной 8000 мм, 2 этажа, высота этажа 300 см.", "ru"),
        ("дом 12 на 8 м с высотой этажа 3 м и 2 этажа", "ru"),
        ("Build a rectangular house 12 m x 8 m, 2 floors, floor height 3000 mm", "en"),
        ("Create a two-storey house 12000 mm long, 8 meters wide, 300 cm per floor", "en"),
        ("BUILD A HOUSE 12 X 8 M, 2 FLOORS, FLOOR HEIGHT 3 M", "en"),
    ],
)
def test_valid_ru_and_en_descriptions_normalise_to_the_same_canonical_mm(
    prompt: str, language: str
) -> None:
    parsed = parse_house_text(prompt)
    assert parsed.language == language
    assert parsed.request() == CANONICAL
    HouseBoxRequest(**parsed.request())


@pytest.mark.parametrize(
    ("text", "mm"),
    [
        ("2800 мм", 2_800),
        ("280 см", 2_800),
        ("2,8 м", 2_800),
        ("2.8 m", 2_800),
        ("2.8 метра", 2_800),
    ],
)
def test_mm_cm_m_conversions_are_exact(text: str, mm: int) -> None:
    parsed = parse_house_text(f"дом 10 x 9 м, высота этажа {text}, 1 этаж")
    assert parsed.floor_height_mm == mm
    assert isinstance(parsed.floor_height_mm, int)


def test_repeated_identical_value_is_not_a_conflict() -> None:
    parsed = parse_house_text("Build a house 12 x 8 m, length 1200 cm, 2 floors, floor height 3 m")
    assert parsed.length_mm == 12_000


@pytest.mark.parametrize(
    ("prompt", "shape"),
    [
        ("Создай Г-образный дом 12 x 8 м, 2 этажа, высота этажа 3 м", "l_shape"),
        ("Т-образный дом 12 x 8 м, высота этажа 3 м, 2 этажа", "t_shape"),
        ("Build an L-shaped house 12 x 8 m, 2 floors, floor height 3 m", "l_shape"),
        ("Build a T-shaped house 12 x 8 m, 2 floors, floor height 3 m", "t_shape"),
    ],
)
def test_bounded_non_rectangular_shapes_remain_explicit(prompt: str, shape: str) -> None:
    parsed = parse_house_text(prompt)
    assert parsed.shape == shape
    assert parsed.sources["shape"] in prompt.lower().replace("ё", "е")
    HouseBoxRequest(**parsed.request())


@pytest.mark.parametrize(
    ("prompt", "reason"),
    [
        ("дом 12 x 8, высота этажа 3 м, 2 этажа", "missing_unit"),
        ("дом 12 м x 8, высота этажа 3 м, 2 этажа", "missing_unit"),
        ("дом 12 x 8 м, высота этажа 3, 2 этажа", "missing_unit"),
        ("дом 12 x 8 м, высота этажа 3 м", "missing_fields"),
        ("дом высота этажа 3 м, 2 этажа", "missing_fields"),
        ("дом 12 x 8 м, высота 6 м, 2 этажа", "ambiguous_height"),
        ("дом 12 x 8 м, высота потолка 2,7 м, 2 этажа", "ambiguous_height"),
        ("Build a house 12 x 8 m, 2 floors, floor height 3 m and length 13 m", "conflict"),
        ("двухэтажный дом 12 x 8 м, высота этажа 3 м, 3 этажа", "conflict"),
        ("П-образный дом 12 x 8 м, высота этажа 3 м, 2 этажа", "unsupported_shape"),
        ("Build a U-shaped house 12 x 8 m, 2 floors, floor height 3 m", "unsupported_shape"),
        ("дом 12 x 8 м, высота этажа 3 м, 2 этажа, с лестницей", "unsupported_feature"),
        (
            "Build a house 12 x 8 m, 2 floors, floor height 3 m, with a garage",
            "unsupported_feature",
        ),
        ("сделай красивый дом 12 x 8 м, высота этажа 3 м, 2 этажа", "unknown_clause"),
        ("Build a house 12 x 8 m, 2 этажа, floor height 3 m", "unknown_clause"),
        ("дом 12 000 x 8 000 мм, высота этажа 3 м, 2 этажа", "unknown_clause"),
        ("дом примерно 12 x 8 м, высота этажа 3 м, 2 этажа", "unknown_clause"),
        ("Увеличь свес крыши до 400 мм", "not_a_house"),
        ("дом 12 x 8 м, высота этажа 3,0005 м, 2 этажа", "sub_millimetre"),
        ("дом 12 x 8 м, высота этажа 3 м, 4 этажа", "out_of_range"),
        ("дом 1 x 8 м, высота этажа 3 м, 2 этажа", "out_of_range"),
        ("дом 12 x 80 м, высота этажа 3 м, 2 этажа", "out_of_range"),
        ("дом 12 x 8 м, высота этажа 2 м, 2 этажа", "out_of_range"),
        ("дом 12 x 8 м, высота этажа 3 м, 0 этажей", "out_of_range"),
    ],
)
def test_ambiguous_conflicting_unknown_or_out_of_range_text_fails_closed(
    prompt: str, reason: str
) -> None:
    with pytest.raises(HouseTextError) as refused:
        parse_house_text(prompt)
    assert refused.value.reason == reason
    assert refused.value.details["reason"] == reason
