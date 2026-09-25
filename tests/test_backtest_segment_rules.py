"""Règles des segments, valeurs exactes (§ 7.2b du brief M4a-2b, « fonctions pures »).

Une assertion par cellule du tableau des fonctions pures : les égalités de seuil se
testent ici, sur des valeurs exactement représentables, jamais à travers une trace
(§ 7.0 de M4a-2a).
"""

import pytest

from fixtures.matching import local_trace
from fixtures.segments import elevated_route, hand_profile
from mountain_perf.backtest import (
    FineOverlap,
    TraceSeries,
    build_series,
    fine_overlaps,
    gap_between,
    grade_regime,
    interior_ok,
    is_pure,
    length_ratio_ok,
    regime_class,
    regime_lengths,
)
from mountain_perf.gpx import PROFILE_PARAMETER_SPECS, build_profile
from mountain_perf.schemas import ParameterSet, Regime, RegimeClass, RouteProfile


def _gap_series() -> TraceSeries:
    """Instants ``(0, 1, 12, 13, 14, 15)`` : seul trou, l'intervalle 1."""
    trace = local_trace([0, 1, 12, 13, 14, 15], [(float(x), 0.0) for x in range(6)])
    series = build_series(trace)
    assert series.gap_after == (False, True, False, False, False)
    return series


# ---------------------------------------------------------------------------
# gap_between (§ 5b.2 ; 0010 D4.7, D4.9)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("first", "second"), [(0.5, 1.5), (1.0, 2.0), (1.5, 1.7)])
def test_gap_between_sees_the_gap_interval(first: float, second: float) -> None:
    """``⌊first⌋ <= 1 <= ⌈second⌉ − 1``."""
    assert gap_between(_gap_series(), first, second)


@pytest.mark.parametrize(
    ("first", "second"), [(0.5, 1.0), (0.0, 1.0), (1.0, 1.0), (2.0, 3.5)]
)
def test_gap_between_ignores_the_other_intervals(first: float, second: float) -> None:
    """Un franchissement en ``π = 1`` exactement n'entre pas dans l'intervalle 1."""
    assert not gap_between(_gap_series(), first, second)


def test_gap_between_refuses_decreasing_positions() -> None:
    with pytest.raises(ValueError, match="positions décroissantes"):
        gap_between(_gap_series(), 2.5, 1.0)


# ---------------------------------------------------------------------------
# Prédicats de seuil (§ 5b.3 ; 0010 D4.10, D6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("grade", [0.05, -0.05, 0.0])
def test_grade_regime_flat_bounds_are_included(grade: float) -> None:
    assert grade_regime(grade) is Regime.FLAT


def test_grade_regime_just_above_and_below() -> None:
    assert grade_regime(0.05000000000000001) is Regime.ASCENT
    assert grade_regime(-0.05000000000000001) is Regime.DESCENT


def test_is_pure_threshold_is_included() -> None:
    assert is_pure(0.8)
    assert not is_pure(0.7999999999999999)


@pytest.mark.parametrize(
    ("fractions", "expected"),
    [
        ((0.8, 0.2, 0.0), RegimeClass.ASCENT),
        ((0.2, 0.8, 0.0), RegimeClass.FLAT),
        ((0.0, 0.2, 0.8), RegimeClass.DESCENT),
        ((0.7999999999999999, 0.2000000000000001, 0.0), RegimeClass.MIXED),
    ],
)
def test_regime_class_of_fractions(
    fractions: tuple[float, float, float], expected: RegimeClass
) -> None:
    ascent, flat, descent = fractions
    assert (
        regime_class(
            ascent_fraction=ascent, flat_fraction=flat, descent_fraction=descent
        )
        is expected
    )


@pytest.mark.parametrize("ratio", [0.6, 1.6, 12 / 20, 32 / 20])
def test_length_ratio_bounds_are_included(ratio: float) -> None:
    assert length_ratio_ok(ratio)


@pytest.mark.parametrize("ratio", [0.5999999999999999, 1.6000000000000003])
def test_length_ratio_just_outside(ratio: float) -> None:
    assert not length_ratio_ok(ratio)


@pytest.mark.parametrize("deviation_m", [30.0, 29.999])
def test_interior_deviation_equal_to_tolerance_passes(deviation_m: float) -> None:
    assert interior_ok(deviation_m, 30.0)


def test_interior_deviation_just_above_tolerance() -> None:
    assert not interior_ok(30.000000000000004, 30.0)


# ---------------------------------------------------------------------------
# Fractions et pureté (§ 5b.4 ; 0010 D6) — profils écrits à la main
# ---------------------------------------------------------------------------

STEPS = (0.0, 50.0, 100.0, 150.0, 200.0, 250.0)
CLIMB = (0.0, 5.0, 10.0, 15.0, 20.0, 20.0)


def _fractions(
    profile: RouteProfile, start_m: float, end_m: float
) -> tuple[float, float, float]:
    ascent_m, flat_m, descent_m = regime_lengths(profile, start_m, end_m)
    length_m = end_m - start_m
    return ascent_m / length_m, flat_m / length_m, descent_m / length_m


def test_last_fine_interval_counts_for_its_length() -> None:
    """Grille ``(0, 50, 100, 150, 200, 270)`` : ``[0 ; 270]`` →
    ``(0,740741 / 0,259259 / 0)``, mixte."""
    profile = hand_profile((*STEPS[:-1], 270.0), CLIMB)
    fractions = _fractions(profile, 0.0, 270.0)
    assert fractions == pytest.approx((0.740741, 0.259259, 0.0), abs=1e-6)
    assert regime_class(*fractions) is RegimeClass.MIXED


def test_eighty_percent_is_pure_exactly() -> None:
    """``[0 ; 250]`` → ``(0,8 / 0,2 / 0)`` exactement : montée, seuil inclus."""
    profile = hand_profile(STEPS, CLIMB)
    assert regime_lengths(profile, 0.0, 250.0) == (200.0, 50.0, 0.0)
    fractions = _fractions(profile, 0.0, 250.0)
    assert fractions == (0.8, 0.2, 0.0)
    assert regime_class(*fractions) is RegimeClass.ASCENT


def test_fine_overlaps_of_a_partial_interval() -> None:
    """``[120 ; 250]`` : ``(30 ; 0,1)``, ``(50 ; 0,1)``, ``(50 ; 0)``,
    fractions ``(0,615385 / 0,384615 / 0)``, mixte."""
    profile = hand_profile(STEPS, CLIMB)
    assert fine_overlaps(profile, 120.0, 250.0) == (
        FineOverlap(30.0, 0.1),
        FineOverlap(50.0, 0.1),
        FineOverlap(50.0, 0.0),
    )
    fractions = _fractions(profile, 120.0, 250.0)
    assert fractions == pytest.approx((0.615385, 0.384615, 0.0), abs=1e-6)
    assert regime_class(*fractions) is RegimeClass.MIXED


def test_grades_at_the_threshold_are_flat() -> None:
    """Pentes ``+0,05`` et ``−0,05`` : tout en plat."""
    profile = hand_profile((0.0, 50.0, 100.0), (0.0, 2.5, 0.0))
    assert profile.grade == (0.05, -0.05)
    fractions = _fractions(profile, 0.0, 100.0)
    assert fractions == (0.0, 1.0, 0.0)
    assert regime_class(*fractions) is RegimeClass.FLAT


def test_two_thirds_of_descent_is_mixed() -> None:
    profile = hand_profile((0.0, 50.0, 100.0, 150.0), (0.0, -7.5, -15.0, -15.0))
    fractions = _fractions(profile, 0.0, 150.0)
    assert fractions == pytest.approx((0.0, 0.333333, 0.666667), abs=1e-6)
    assert regime_class(*fractions) is RegimeClass.MIXED


def test_t06_seventy_metre_fine_interval() -> None:
    """T06 : ``(0,0,0)``, ``(100,0,0)``, ``(120,0,10)`` par ``build_profile`` —
    grille ``(0 ; 50 ; 119,999999999)``, altitudes ``(0 ; 3,333333 ; 5)`` ; montée
    ``0,416667``, plat ``0,583333``, mixte : l'intervalle fin de 70 m compte pour sa
    longueur."""
    profile = build_profile(
        elevated_route((0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (120.0, 0.0, 10.0)),
        ParameterSet(PROFILE_PARAMETER_SPECS),
    )
    assert profile.distance_m == pytest.approx((0.0, 50.0, 119.999999999), abs=1e-6)
    assert profile.elevation_m == pytest.approx((0.0, 3.333333, 5.0), abs=1e-6)
    length_m = profile.distance_m[-1]
    fractions = _fractions(profile, 0.0, length_m)
    assert fractions == pytest.approx((0.416667, 0.583333, 0.0), abs=1e-6)
    assert regime_class(*fractions) is RegimeClass.MIXED


@pytest.mark.parametrize(
    ("start_m", "end_m"), [(-1.0, 100.0), (100.0, 100.0), (120.0, 100.0), (0.0, 251.0)]
)
def test_fine_overlaps_precondition(start_m: float, end_m: float) -> None:
    with pytest.raises(ValueError, match="fine_overlaps"):
        fine_overlaps(hand_profile(STEPS, CLIMB), start_m, end_m)


def test_fine_overlaps_from_a_grid_point_to_the_end() -> None:
    """Départ exactement sur un point de la grille, fin en ``L`` : ni intervalle vide
    ni intervalle manquant."""
    profile = hand_profile(STEPS, CLIMB)
    assert fine_overlaps(profile, 200.0, 250.0) == (FineOverlap(50.0, 0.0),)
    assert fine_overlaps(profile, 0.0, 50.0) == (FineOverlap(50.0, 0.1),)
