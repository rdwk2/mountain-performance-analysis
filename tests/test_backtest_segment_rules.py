"""Règles des segments, valeurs exactes (§ 7.2b du brief M4a-2b, « fonctions pures »).

Une assertion par cellule du tableau des fonctions pures : les égalités de seuil se
testent ici, sur des valeurs exactement représentables, jamais à travers une trace
(§ 7.0 de M4a-2a). Puis fractions et pureté, T06, et les totaux admis écrits à la
main (T10, T11, X07).
"""

import pytest

from fixtures.matching import local_trace
from fixtures.segments import elevated_route, hand_profile
from mountain_perf.backtest import (
    FineOverlap,
    TraceSeries,
    build_series,
    convention_extremes,
    fine_overlaps,
    gap_between,
    grade_regime,
    interior_ok,
    is_pure,
    last_passage,
    length_ratio_ok,
    regime_class,
    regime_lengths,
    sensitivity_range_s,
)
from mountain_perf.gpx import PROFILE_PARAMETER_SPECS, build_profile
from mountain_perf.schemas import (
    AdmittedTotals,
    NamedPoint,
    ParameterSet,
    Regime,
    RegimeClass,
    ResolvedPoint,
    RouteProfile,
)


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


# ---------------------------------------------------------------------------
# Dernier passage du préfixe (§ 5b.6 ; 0010 D4.11)
# ---------------------------------------------------------------------------


def _resolved(name: str, distance_m: float) -> ResolvedPoint:
    return ResolvedPoint(
        point=NamedPoint(name, 45.0, 6.0, elevation_m=None),
        distance_m=distance_m,
        elevation_m=0.0,
        offset_m=0.0,
    )


PLACES = (
    _resolved("A", 5.0),
    _resolved("B", 300.0),
    _resolved("C", 480.0),
    _resolved("C2", 480.0),
    _resolved("E", 500.0),
)
"""Lieux résolus d'abscisses 5, 300, 480, 480 (C2 après C dans le tuple) et 500."""


@pytest.mark.parametrize(
    ("start_m", "end_m", "name"),
    [
        (12.0, 500.0, "E"),
        (12.0, 499.99999999999994, "C2"),
        (5.0, 5.0, "A"),
        (0.0, 12.0, "A"),
    ],
)
def test_last_passage_bounds_included_last_of_the_tuple(
    start_m: float, end_m: float, name: str
) -> None:
    assert last_passage(PLACES, start_m, end_m) == name


@pytest.mark.parametrize(
    ("start_m", "end_m"), [(12.0, 12.0), (500.00000000000006, 600.0)]
)
def test_last_passage_never_invents_a_name(start_m: float, end_m: float) -> None:
    assert last_passage(PLACES, start_m, end_m) is None


def test_last_passage_is_the_largest_abscissa_whatever_the_order() -> None:
    """R3 (correctifs de la PR #10) : entrée non triée, B à 300 m puis A à 5 m ;
    ``[0 ; 500]`` → B, le lieu de plus grande abscisse, et non le dernier du tuple."""
    unsorted = (_resolved("B", 300.0), _resolved("A", 5.0))
    assert last_passage(unsorted, 0.0, 500.0) == "B"


# ---------------------------------------------------------------------------
# Totaux admis et extrêmes (§ 5b.7 ; 0010 D5.4) — écrits à la main
# ---------------------------------------------------------------------------


def _totals(
    elapsed_s: float, *msu: tuple[float, float, float]
) -> tuple[AdmittedTotals, ...]:
    return tuple(AdmittedTotals(elapsed_s, m, s, u) for m, s, u in msu)


def test_t10_extremes_are_taken_on_the_totals() -> None:
    """T10 : sommes de deux segments de 200 s ; ``θ_bas`` = 2 (premier des trois à
    200), ``θ_haut`` = 0, ``I_sens,A = [200 ; 320]`` — un extrême pris segment par
    segment donnerait 400."""
    totals = _totals(
        400.0, (320, 80, 0), (280, 120, 0), (200, 200, 0), (200, 200, 0), (200, 200, 0)
    )
    assert convention_extremes(totals) == (2, 0)
    assert sensitivity_range_s(totals) == (200.0, 320.0)


def test_t11_high_convention_is_the_maximum_of_moving_or_undetermined() -> None:
    """T11 : ``θ_bas`` = 1, ``θ_haut`` = 1, ``I_sens,A = [280 ; 400]`` ; le maximum
    de ``M`` seul serait l'indice 0, le minimum de ``M + U`` aussi."""
    totals = _totals(
        400.0, (300, 100, 0), (280, 0, 120), (290, 50, 60), (290, 50, 60), (290, 50, 60)
    )
    assert convention_extremes(totals) == (1, 1)
    assert sensitivity_range_s(totals) == (280.0, 400.0)


def test_x07_interval_uses_the_elapsed_time_of_the_support() -> None:
    """X07 : cinq fois ``(400, 100, 100)``, ``E_A = 600``, pour une trace de 1 000 s :
    ``[400 ; 500]``, et non 900 — jamais le ``E`` de la trace avec le ``S`` du
    support."""
    totals = _totals(600.0, *((400, 100, 100),) * 5)
    assert sensitivity_range_s(totals) == (400.0, 500.0)
    assert convention_extremes(totals) == (0, 0)
