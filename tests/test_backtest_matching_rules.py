"""Paramètres, grille de score et prédicats de seuil (§§ 5a.3 et 5a.4 du brief M4a-2a).

Les égalités de seuil de ``0010`` D4.5 à D4.8 se testent ici, sur des valeurs
exactement représentables, et jamais à travers une trace (§ 7.0) : une assertion par
cellule du tableau des prédicats du § 7.2a. La dernière ligne du tableau
(``anchor_projection``) est dans ``test_backtest_geometry.py``.
"""

import pytest

from mountain_perf.backtest.matching import (
    MATCHING_PARAMETER_SPECS,
    WINDOW_FACTOR,
    WINDOW_SLACK_M,
    arrival_anchorable,
    arrival_offset_ok,
    crosses,
    crossing_fraction,
    departure_anchorable,
    departure_offset_ok,
    score_grid,
    window_bound_m,
    within_cluster,
    within_tolerance,
    within_window,
)
from mountain_perf.schemas import ParameterSet

# ---------------------------------------------------------------------------
# Paramètres et constantes (§ 5a.3)
# ---------------------------------------------------------------------------


def test_parameters_of_0010() -> None:
    """``Δ``, ``ε``, ``r_c`` : défauts et bornes du § 5a.3."""
    assert [
        (spec.name, spec.unit, spec.default, spec.minimum, spec.maximum)
        for spec in MATCHING_PARAMETER_SPECS
    ] == [
        ("score_step_m", "m", 250.0, 10.0, 5000.0),
        ("lateral_tolerance_m", "m", 30.0, 1.0, 200.0),
        ("cluster_radius_m", "m", 15.0, 0.0, 100.0),
    ]
    parameters = ParameterSet(MATCHING_PARAMETER_SPECS)
    assert dict(parameters.values) == {
        "score_step_m": 250.0,
        "lateral_tolerance_m": 30.0,
        "cluster_radius_m": 15.0,
    }


def test_window_constants_of_0010_d4_6() -> None:
    assert WINDOW_FACTOR == 2.5
    assert WINDOW_SLACK_M == 300.0


# ---------------------------------------------------------------------------
# Grille de score (D4.2)
# ---------------------------------------------------------------------------


def test_score_grid_ends_at_the_length() -> None:
    assert score_grid(520.0, 250.0) == (0.0, 250.0, 500.0, 520.0)


def test_score_grid_shorter_than_one_step() -> None:
    assert score_grid(20.0, 250.0) == (0.0, 20.0)


def test_score_grid_multiplies_instead_of_summing() -> None:
    """Une somme cumulée rendrait ``0,7999999999999999`` au neuvième rang, et un
    point de trop en ``0,9999999999999999``."""
    grid = score_grid(1.0, 0.1)
    assert len(grid) == 11
    assert grid[8] == 8 * 0.1 == 0.8
    assert grid[-2] == 9 * 0.1
    assert grid[-1] == 1.0


def test_score_grid_refuses_a_non_positive_step() -> None:
    with pytest.raises(ValueError, match="pas non positif"):
        score_grid(520.0, 0.0)


# ---------------------------------------------------------------------------
# Prédicats (§ 5a.4) — tableau du § 7.2a, une assertion par cellule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("before", "after"), [(-1.0, 1.0), (0.0, 1.0)])
def test_open_crossing_true(before: float, after: float) -> None:
    """D4.5 : ``h_i <= 0 < h_{i+1}``."""
    assert crosses(before, after, closed=False)


@pytest.mark.parametrize(
    ("before", "after"), [(-1.0, 0.0), (0.0, 0.0), (1.0, 2.0), (-2.0, -1.0)]
)
def test_open_crossing_false(before: float, after: float) -> None:
    assert not crosses(before, after, closed=False)


@pytest.mark.parametrize(("before", "after"), [(-1.0, 0.0), (0.0, 1.0), (-1.0, 1.0)])
def test_closed_crossing_true(before: float, after: float) -> None:
    """D4.8, arrivée : ``h_i <= 0 <= h_{i+1}``."""
    assert crosses(before, after, closed=True)


@pytest.mark.parametrize(("before", "after"), [(0.0, 0.0), (1.0, 0.0), (1.0, 2.0)])
def test_closed_crossing_false(before: float, after: float) -> None:
    """D4.8 : la paire ``(0, 0)`` n'est pas un franchissement."""
    assert not crosses(before, after, closed=True)


@pytest.mark.parametrize(
    ("before", "after", "fraction"),
    [(0.0, 3.0, 0.0), (-1.0, 3.0, 0.25), (-3.0, 0.0, 1.0)],
)
def test_crossing_fraction(before: float, after: float, fraction: float) -> None:
    assert crossing_fraction(before, after) == fraction


@pytest.mark.parametrize("lateral_m", [29.999, -29.999])
def test_within_tolerance_true(lateral_m: float) -> None:
    assert within_tolerance(lateral_m, 30.0)


@pytest.mark.parametrize("lateral_m", [30.0, -30.0])
def test_within_tolerance_false(lateral_m: float) -> None:
    """D4.5 : écart latéral ``< ε`` en valeur absolue, strictement."""
    assert not within_tolerance(lateral_m, 30.0)


@pytest.mark.parametrize(
    ("realized_m", "step_m", "k", "k_last", "bound_m"),
    [(250.0, 250.0, 3, 1, 1800.0), (0.0, 100.0, 1, 0, 550.0)],
)
def test_window_bound(
    realized_m: float, step_m: float, k: int, k_last: int, bound_m: float
) -> None:
    """D4.6 : ``d_r(π_cur) + 2,5·Δ·(k − k_der) + 300`` ; un facteur 2 donnerait
    1 300 et 500."""
    assert window_bound_m(realized_m, step_m, k, k_last) == bound_m


def test_within_window() -> None:
    assert within_window(1800.0, 1800.0)
    assert not within_window(1800.0000000000002, 1800.0)


def test_within_cluster() -> None:
    assert within_cluster(15.0, 15.0)
    assert not within_cluster(15.000000000000002, 15.0)


@pytest.mark.parametrize(("h_m", "lateral_m"), [(30.0, 0.0), (0.5, 29.999)])
def test_departure_anchorable_true(h_m: float, lateral_m: float) -> None:
    assert departure_anchorable(h_m, lateral_m, 30.0)


@pytest.mark.parametrize(
    ("h_m", "lateral_m"),
    [(0.0, 0.0), (30.000000000000004, 0.0), (0.5, 30.0), (-0.5, 0.0)],
)
def test_departure_anchorable_false(h_m: float, lateral_m: float) -> None:
    """D4.8 : ``0 < h_0 <= ε`` et écart latéral ``< ε`` en valeur absolue."""
    assert not departure_anchorable(h_m, lateral_m, 30.0)


@pytest.mark.parametrize(("h_m", "lateral_m"), [(-30.0, 0.0), (-0.5, -29.999)])
def test_arrival_anchorable_true(h_m: float, lateral_m: float) -> None:
    assert arrival_anchorable(h_m, lateral_m, 30.0)


@pytest.mark.parametrize(
    ("h_m", "lateral_m"),
    [(0.0, 0.0), (-30.000000000000004, 0.0), (-0.5, -30.0), (0.5, 0.0)],
)
def test_arrival_anchorable_false(h_m: float, lateral_m: float) -> None:
    """D4.8 : ``−ε <= h < 0`` et écart latéral ``< ε`` en valeur absolue."""
    assert not arrival_anchorable(h_m, lateral_m, 30.0)


@pytest.mark.parametrize(("s_m", "next_m"), [(30.0, 250.0), (19.999, 20.0)])
def test_departure_offset_ok_true(s_m: float, next_m: float) -> None:
    assert departure_offset_ok(s_m, 30.0, next_m)


@pytest.mark.parametrize(("s_m", "next_m"), [(30.000000000000004, 250.0), (20.0, 20.0)])
def test_departure_offset_ok_false(s_m: float, next_m: float) -> None:
    """D4.8 : ``s'_0 <= ε`` et bornes effectives strictement croissantes."""
    assert not departure_offset_ok(s_m, 30.0, next_m)


def test_arrival_offset_ok_true() -> None:
    """``L − s = 30`` exactement : retenue."""
    assert arrival_offset_ok(490.0, 520.0, 30.0, 489.0)


@pytest.mark.parametrize(
    ("s_m", "previous_m"), [(489.99999999999994, 0.0), (500.0, 500.0)]
)
def test_arrival_offset_ok_false(s_m: float, previous_m: float) -> None:
    """D4.8 : ``L − s'_K <= ε`` et ``s'_K > b_{K−1}``."""
    assert not arrival_offset_ok(s_m, 520.0, 30.0, previous_m)
