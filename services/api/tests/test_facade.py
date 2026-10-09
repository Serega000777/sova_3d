import pytest
from pydantic import TypeAdapter, ValidationError

from app.engineering.facade import (
    MAX_OPENINGS,
    MAX_PLAN_OPERATIONS,
    FacadeOpening,
    FacadeRequest,
    RoofKind,
    SurfaceMaterial,
    surface_keys,
)
from app.geometry.operations import OperationPlan


def windows(count: int) -> list[FacadeOpening]:
    return [
        FacadeOpening(
            kind="window",
            side=("front", "back", "left", "right")[index % 4],
            center_mm=1_000 + (index // 4) * 150,
            width_mm=300,
            height_mm=600,
        )
        for index in range(count)
    ]


def test_facade_plan_builds_shell_openings_and_gable_roof() -> None:
    request = FacadeRequest(
        length_mm=10_000,
        width_mm=8_000,
        floor_height_mm=3_000,
        floors=2,
        roof="gable",
        openings=[
            FacadeOpening(
                kind="door", side="front", center_mm=2_000, width_mm=900, height_mm=2_100
            ),
            FacadeOpening(
                kind="window", side="right", center_mm=4_000, width_mm=1_200, height_mm=1_400
            ),
        ],
    )
    plan = request.build()
    assert [operation.type for operation in plan.operations] == [
        "create_box",
        "shell",
        "create_box",
        "boolean",
        "create_box",
        "boolean",
        "extrude",
        "boolean",
    ]
    assert plan.operations[-2].normal == (0.0, 1.0, 0.0)  # type: ignore[union-attr]


def test_facade_rejects_openings_outside_the_selected_side() -> None:
    with pytest.raises(ValidationError, match="exceeds the front facade width"):
        FacadeRequest(
            length_mm=8_000,
            width_mm=6_000,
            floor_height_mm=3_000,
            floors=1,
            openings=[
                FacadeOpening(
                    kind="window", side="front", center_mm=200, width_mm=1_000, height_mm=1_000
                )
            ],
        )


def test_facade_rejects_derived_roof_dimensions_before_a_job() -> None:
    with pytest.raises(ValidationError, match="gable roof span"):
        FacadeRequest(
            length_mm=12_000,
            width_mm=10_000,
            floor_height_mm=3_000,
            floors=1,
            roof="gable",
            overhang_mm=300,
        )


def test_opening_ceiling_matches_the_operation_plan_limit() -> None:
    assert OperationPlan.model_fields["operations"].metadata[0].max_length == MAX_PLAN_OPERATIONS
    assert MAX_OPENINGS == 126


@pytest.mark.parametrize("roof", ["none", "flat", "gable"])
def test_facade_plan_at_the_opening_ceiling_fits_every_roof(roof: RoofKind) -> None:
    request = FacadeRequest(
        length_mm=10_000,
        width_mm=8_000,
        floor_height_mm=3_000,
        floors=2,
        roof=roof,
        openings=windows(MAX_OPENINGS),
    )
    plan = request.build()
    roof_operations = 0 if roof == "none" else 2
    assert len(plan.operations) == 2 + 2 * MAX_OPENINGS + roof_operations
    assert len(plan.operations) <= MAX_PLAN_OPERATIONS


def test_facade_rejects_one_opening_past_the_ceiling() -> None:
    with pytest.raises(ValidationError, match=f"at most {MAX_OPENINGS} items"):
        FacadeRequest(
            length_mm=10_000,
            width_mm=8_000,
            floor_height_mm=3_000,
            floors=2,
            openings=windows(MAX_OPENINGS + 1),
        )


def test_doors_default_to_floor_level_and_windows_keep_their_sill() -> None:
    door = FacadeOpening(kind="door", side="front", center_mm=2_000, width_mm=900, height_mm=2_100)
    assert door.sill_mm == 0
    from_json = TypeAdapter(FacadeOpening).validate_python(
        {"kind": "door", "side": "front", "center_mm": 2_000, "width_mm": 900, "height_mm": 2_100}
    )
    assert from_json.sill_mm == 0
    window = FacadeOpening(
        kind="window", side="front", center_mm=5_000, width_mm=900, height_mm=1_200
    )
    assert window.sill_mm == 900
    raised = FacadeOpening(
        kind="window", side="front", center_mm=5_000, width_mm=900, height_mm=1_200, sill_mm=1_500
    )
    assert raised.sill_mm == 1_500


def test_facade_surfaces_use_stable_semantic_opening_keys() -> None:
    request = FacadeRequest(
        length_mm=10_000,
        width_mm=8_000,
        floor_height_mm=3_000,
        floors=1,
        roof="gable",
        openings=[
            FacadeOpening(
                opening_id="front-main",
                kind="window",
                side="front",
                center_mm=2_000,
                width_mm=1_200,
                height_mm=1_400,
            )
        ],
        surface_assignments=[
            SurfaceMaterial(surface_key="opening.front-main.left", colour="#884422")
        ],
    )
    keys = surface_keys(request)
    assert {"wall.front", "roof.slope.left", "roof.slope.right"}.issubset(keys)
    assert {
        "opening.front-main.left",
        "opening.front-main.right",
        "opening.front-main.head",
        "opening.front-main.sill",
    }.issubset(keys)
    operation_ids = [operation.id for operation in request.build().operations]
    assert any(operation_id.startswith("opening_") for operation_id in operation_ids)
    assert any(operation_id.startswith("cut_") for operation_id in operation_ids)


def test_legacy_opening_keys_survive_reordering_without_retargeting() -> None:
    first = FacadeOpening(
        kind="window",
        side="front",
        center_mm=2_000,
        width_mm=1_200,
        height_mm=1_400,
    )
    second = FacadeOpening(
        kind="window",
        side="front",
        center_mm=5_000,
        width_mm=1_000,
        height_mm=1_000,
    )
    common = dict(
        length_mm=10_000,
        width_mm=8_000,
        floor_height_mm=3_000,
        floors=1,
        roof="none",
    )
    original = surface_keys(FacadeRequest(**common, openings=[first, second]))
    reordered = surface_keys(FacadeRequest(**common, openings=[second, first]))
    after_removal = surface_keys(FacadeRequest(**common, openings=[second]))

    assert original == reordered
    assert {key for key in original if key.startswith("opening.")}.issuperset(
        key for key in after_removal if key.startswith("opening.")
    )


def test_facade_rejects_unknown_or_duplicate_surface_assignments() -> None:
    common = dict(
        length_mm=10_000,
        width_mm=8_000,
        floor_height_mm=3_000,
        floors=1,
        roof="none",
    )
    with pytest.raises(ValidationError, match="unknown facade surface keys"):
        FacadeRequest(
            **common,
            surface_assignments=[SurfaceMaterial(surface_key="wall.forged", colour="#ffffff")],
        )
    with pytest.raises(ValidationError, match="at most once"):
        FacadeRequest(
            **common,
            surface_assignments=[
                SurfaceMaterial(surface_key="wall.front", colour="#ffffff"),
                SurfaceMaterial(surface_key="wall.front", colour="#000000"),
            ],
        )
    duplicate = FacadeOpening(
        opening_id="same",
        kind="window",
        side="front",
        center_mm=2_000,
        width_mm=1_000,
        height_mm=1_000,
    )
    with pytest.raises(ValidationError, match="opening_id must be unique"):
        FacadeRequest(**common, openings=[duplicate, duplicate])


@pytest.mark.parametrize("sill_mm", [1, 900])
def test_doors_with_a_sill_are_rejected(sill_mm: float) -> None:
    with pytest.raises(ValidationError, match="doors start at floor level"):
        FacadeOpening(
            kind="door",
            side="front",
            center_mm=2_000,
            width_mm=900,
            height_mm=2_100,
            sill_mm=sill_mm,
        )


def test_door_cutter_uses_the_validated_sill() -> None:
    plan = FacadeRequest(
        length_mm=10_000,
        width_mm=8_000,
        floor_height_mm=3_000,
        floors=1,
        roof="none",
        openings=[
            FacadeOpening(
                kind="door", side="front", center_mm=2_000, width_mm=900, height_mm=2_100
            ),
            FacadeOpening(
                kind="window",
                side="back",
                center_mm=5_000,
                width_mm=900,
                height_mm=1_200,
                sill_mm=1_100,
            ),
        ],
    ).build()
    door_cutter, window_cutter = plan.operations[2], plan.operations[4]
    assert door_cutter.origin_mm[2] == -2  # type: ignore[union-attr]
    assert door_cutter.height_mm == 2_102  # type: ignore[union-attr]
    assert window_cutter.origin_mm[2] == 1_100  # type: ignore[union-attr]
    assert window_cutter.height_mm == 1_200  # type: ignore[union-attr]
