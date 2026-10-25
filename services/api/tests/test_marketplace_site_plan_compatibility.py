from app.services.marketplace import _rectangular_plot_fit, _terrain_profile_delta


def test_rectangular_plot_fit_checks_both_axes_and_one_right_angle_rotation() -> None:
    assert _rectangular_plot_fit((30_000.0, 20_000.0), (35_000.0, 25_000.0)) == (
        "compatible",
        (5_000.0, 5_000.0),
    )
    assert _rectangular_plot_fit((30_000.0, 20_000.0), (20_000.0, 35_000.0)) == (
        "rotated",
        (0.0, 5_000.0),
    )
    assert _rectangular_plot_fit((30_000.0, 20_000.0), (40_000.0, 15_000.0)) == (
        "incompatible",
        None,
    )


def test_terrain_profile_delta_uses_the_best_valid_exact_envelope_rotation() -> None:
    assert _terrain_profile_delta(
        (30_000.0, 20_000.0),
        (0.0, 100.0, 300.0, 50.0),
        (30_000.0, 20_000.0),
        (1_000.0, 1_100.0, 1_300.0, 1_050.0),
    ) == (0, (0.0, 0.0, 0.0, 0.0), 0.0)

    assert _terrain_profile_delta(
        (30_000.0, 20_000.0),
        (0.0, 100.0, 300.0, 50.0),
        (20_000.0, 30_000.0),
        (900.0, 1_100.0, 850.0, 800.0),
    ) == (90, (0.0, 0.0, 0.0, 0.0), 0.0)


def test_terrain_profile_delta_reports_residuals_without_inventing_a_pass_limit() -> None:
    assert _terrain_profile_delta(
        (30_000.0, 20_000.0),
        (0.0, 100.0, 300.0, 50.0),
        (30_000.0, 20_000.0),
        (500.0, 650.0, 900.0, 525.0),
    ) == (0, (0.0, 50.0, 100.0, -25.0), 100.0)
    assert (
        _terrain_profile_delta(
            (30_000.0, 20_000.0),
            (0.0, 100.0, 300.0, 50.0),
            (35_000.0, 25_000.0),
            (0.0, 100.0, 300.0, 50.0),
        )
        is None
    )
