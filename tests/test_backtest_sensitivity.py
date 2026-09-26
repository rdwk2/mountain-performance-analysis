"""Configurations de sensibilité (§ 5b.10 du brief M4a-2b, ``0010`` D13)."""

from mountain_perf.backtest import SENSITIVITY_CONFIGURATIONS
from mountain_perf.schemas import CLOCKS, ClockKind


def test_nineteen_configurations() -> None:
    assert len(SENSITIVITY_CONFIGURATIONS) == 19


def test_nine_elapsed_configurations_first_in_order() -> None:
    """``Δ ∈ (100, 250, 500)``, puis ``ε ∈ (15, 30, 45)``, en écoulé."""
    first = SENSITIVITY_CONFIGURATIONS[:9]
    assert [(c.score_step_m, c.lateral_tolerance_m) for c in first] == [
        (100.0, 15.0),
        (100.0, 30.0),
        (100.0, 45.0),
        (250.0, 15.0),
        (250.0, 30.0),
        (250.0, 45.0),
        (500.0, 15.0),
        (500.0, 30.0),
        (500.0, 45.0),
    ]
    assert all(c.clock == CLOCKS[0] for c in first)
    assert CLOCKS[0].kind is ClockKind.ELAPSED


def test_ten_movement_clocks_at_the_central_grid() -> None:
    """``(250, 30)`` sous ``CLOCKS[1]`` … ``CLOCKS[10]``, dans l'ordre."""
    last = SENSITIVITY_CONFIGURATIONS[9:]
    assert [c.clock for c in last] == list(CLOCKS[1:])
    assert len(last) == 10
    assert all((c.score_step_m, c.lateral_tolerance_m) == (250.0, 30.0) for c in last)


def test_cluster_radius_is_fixed() -> None:
    assert {c.cluster_radius_m for c in SENSITIVITY_CONFIGURATIONS} == {15.0}
