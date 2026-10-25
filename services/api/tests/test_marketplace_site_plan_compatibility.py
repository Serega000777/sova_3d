from app.services.marketplace import _rectangular_plot_fit


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
