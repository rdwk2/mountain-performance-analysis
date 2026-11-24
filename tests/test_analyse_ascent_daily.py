"""La vitesse habituelle et l'étage 3 du modèle de la montée
(``mountain_perf.analyse.ascent.speed``, ``…daily``, AN4-2a) : J1 à J13, H1 à H7 du
brief. Les cas à la main du § 12.1 ; le monde E du § 12.2, aux tolérances de la
seconde implémentation. Valeurs inventées (règle 1). Sautés sans numpy ou scipy
(extra ``analyse``)."""

from __future__ import annotations

import dataclasses
import inspect
import itertools
import math
import statistics
from datetime import date, timedelta
from typing import Any

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")

from hypothesis import given, settings
from hypothesis import strategies as st

from fixtures.ascent_world import WORLD_E_LAST_DAY, world_e_tables
from mountain_perf.analyse.ascent.daily import daily_level, shrunk_level
from mountain_perf.analyse.ascent.parameters import MONTH_DAYS
from mountain_perf.analyse.ascent.references import References, references
from mountain_perf.analyse.ascent.selection import select_climbs
from mountain_perf.analyse.ascent.speed import habitual_speed
from mountain_perf.analyse.ascent.states import AscentError, AscentState
from mountain_perf.analyse.ascent.structure import Point, Structure, fit_structure


def on(day: int) -> date:
    """Le jour ``day`` (compté depuis 1) des cas à la main."""
    return date(2001, 1, 1) + timedelta(days=day - 1)


HAND = [
    Point(on(d), v, 0.0016) for d, v in ((1, 0.03), (10, -0.01), (18, 0.03), (25, 0.06))
]
"""Les quatre points du § 12.1."""

EXACT: dict[str, Any] = {"rel": 1e-12, "abs": 1e-15}


def world_e_structure() -> Structure:
    climbs = select_climbs(world_e_tables()).climbs
    refs = references(climbs, WORLD_E_LAST_DAY)
    assert isinstance(refs, References)
    result = fit_structure(climbs, refs)
    assert isinstance(result, Structure)
    return result


def test_j1_the_hand_case() -> None:
    """J1 : le lissage du § 12.1 aux jours 25, 35, 53 et 54."""
    at25 = shrunk_level(HAND, on(25), 56, 0.02)
    assert at25 is not None
    assert at25.n_points == 4
    assert at25.last_day == on(25)
    assert at25.slope == pytest.approx(0.0459881230529595, **EXACT)
    assert at25.slope_variance == pytest.approx(0.0046177764797507796, **EXACT)
    assert at25.weight == pytest.approx(0.0797165839519155, **EXACT)
    assert at25.value == pytest.approx(0.028885106688448, **EXACT)
    assert at25.variance == pytest.approx(0.0004525483774586459, **EXACT)
    assert at25.provisional is False
    at35 = shrunk_level(HAND, on(35), 56, 0.02)
    assert at35 is not None
    assert at35.value == at25.value
    assert at35.variance == pytest.approx(0.0004957243405904211, **EXACT)
    assert at35.provisional is True
    at53 = shrunk_level(HAND, on(53), 56, 0.02)
    assert at53 is not None
    assert at53.variance == pytest.approx(0.0007910479284117637, **EXACT)
    assert shrunk_level(HAND, on(54), 56, 0.02) is None


def test_j2_tau_zero() -> None:
    """J2 : ``τ = 0`` : ``value = m̄``, aucune ouverture après la dernière sortie."""
    at25 = shrunk_level(HAND, on(25), 56, 0.0)
    at40 = shrunk_level(HAND, on(40), 56, 0.0)
    assert at25 is not None
    assert at40 is not None
    assert at25.weight == 0.0
    assert at25.value == pytest.approx(0.0275, **EXACT)
    assert at40.value == at25.value
    assert at25.variance == pytest.approx(0.0004, **EXACT)
    assert at40.variance == at25.variance


def test_j3_a_very_large_tau() -> None:
    """J3 : ``τ = 1e6`` : la droite des MCO lue au dernier point, ``m̄ + ĉ·l``."""
    level = shrunk_level(HAND, on(25), 56, 1e6)
    assert level is not None
    assert level.value == pytest.approx(0.0275 + 0.485 * 11.5 / 321, abs=1e-9)


def test_j4_two_points_have_no_slope() -> None:
    """J4 : deux points, pas de pente : ``value = m̄``."""
    level = shrunk_level(HAND[2:], on(25), 56, 0.02)
    assert level is not None
    assert (level.weight, level.slope, level.slope_variance) == (None, None, None)
    assert level.value == pytest.approx(0.045, **EXACT)


def test_j5_the_variance_grows_then_stops() -> None:
    """J5 : la variance croît strictement du jour 25 au jour 53, puis ``None``."""
    variances = []
    for d in range(25, 54):
        level = shrunk_level(HAND, on(d), 56, 0.02)
        assert level is not None
        variances.append(level.variance)
    assert all(b > a for a, b in itertools.pairwise(variances))
    assert shrunk_level(HAND, on(54), 56, 0.02) is None


def test_j6_the_window_ends_at_the_last_point() -> None:
    """J6 : un point au jour ``last − N`` n'entre pas, un au jour ``last − N + 1``
    entre (``last``, le dernier point avant le jour lu)."""
    last = on(100)
    points = [Point(last, 0.0, 1e-4), Point(last - timedelta(days=5), 0.0, 1e-4)]
    out = shrunk_level(
        [*points, Point(last - timedelta(days=10), 1.0, 1e-4)], on(110), 10, 0.02
    )
    inside = shrunk_level(
        [*points, Point(last - timedelta(days=9), 1.0, 1e-4)], on(110), 10, 0.02
    )
    assert out is not None
    assert inside is not None
    assert (out.n_points, inside.n_points) == (2, 3)
    assert out.last_day == inside.last_day == last


def test_j13_the_freeze() -> None:
    """J13 : du dernier point au 28ᵉ jour après lui, ``value``, ``weight``,
    ``slope``, ``n_points`` ne changent pas (les points du § 12.1, et le monde E du
    2001-05-06 au 2001-05-16)."""
    for points, last, n in (
        (HAND, on(25), 28),
        (world_e_structure().points, WORLD_E_LAST_DAY, 10),
    ):
        seen = set()
        for k in range(n + 1):
            level = shrunk_level(points, last + timedelta(days=k), 56, 0.03)
            assert level is not None
            seen.add((level.value, level.weight, level.slope, level.n_points))
        assert len(seen) == 1


def test_j7_refusals() -> None:
    """J7 : ``n_days = 0``, ``τ = −0,01`` : ``AscentError``."""
    with pytest.raises(AscentError):
        shrunk_level(HAND, on(25), 0, 0.02)
    with pytest.raises(AscentError):
        shrunk_level(HAND, on(25), 56, -0.01)


J8_ROWS = [
    # jour, FC, n, weight, value, level.variance, band.variance, centre, provisional
    (
        date(2001, 5, 6),
        145.0,
        7,
        0.23961088079749762,
        -1.724160871807712,
        0.0015207180340042516,
        0.0019408714518745899,
        None,
        False,
    ),
    (
        date(2001, 5, 6),
        140.0,
        7,
        0.23961088079749762,
        -1.724160871807712,
        0.0015207180340042516,
        0.0028101780382846614,
        -1.7911300564906598,
        False,
    ),
    (
        date(2001, 5, 6),
        150.0,
        7,
        0.23961088079749762,
        -1.724160871807712,
        0.0015207180340042516,
        0.003217002665324649,
        -1.6594622714866705,
        False,
    ),
    (
        date(2001, 5, 16),
        145.0,
        7,
        0.23961088079749762,
        -1.724160871807712,
        0.0016178639510507457,
        0.002038017368921084,
        None,
        True,
    ),
    (
        date(2001, 3, 20),
        145.0,
        8,
        0.21039496343178166,
        -1.7097453827835758,
        0.0017000416473546688,
        0.002329781491328529,
        None,
        True,
    ),
    (
        date(2001, 1, 13),
        145.0,
        2,
        None,
        -1.663063140373769,
        0.0029040128010261543,
        0.004544136554559448,
        None,
        False,
    ),
]


def test_j8_world_e() -> None:
    """J8 : le monde E, les lignes du tableau du § 12.2 (``N = 56``, ``τ`` par
    défaut)."""
    s = world_e_structure()
    speed = habitual_speed(s.points, 56, WORLD_E_LAST_DAY)
    assert speed.value == pytest.approx(0.03, rel=1e-12)
    assert speed.state is AscentState.DEFAULT
    tol: dict[str, Any] = {"rel": 1e-4, "abs": 1e-9}
    for day, hr, n, weight, value, variance, band_var, centre, provisional in J8_ROWS:
        found = daily_level(s, day, 56, speed.value, hr)
        assert found is not None
        assert found.level.n_points == n
        if weight is None:
            assert found.level.weight is None
        else:
            assert found.level.weight == pytest.approx(weight, **tol)
        assert found.level.value == pytest.approx(value, **tol)
        assert found.level.variance == pytest.approx(variance, **tol)
        assert found.band.variance == pytest.approx(band_var, **tol)
        expected_centre = value if centre is None else centre
        assert found.band.centre == pytest.approx(expected_centre, **tol)
        assert found.level.provisional is provisional
    assert daily_level(s, date(2001, 6, 4), 56, speed.value, 145.0) is None


def test_j9_the_heart_rate_read() -> None:
    """J9 : à la FC de référence, ``band.centre = level.value`` ; à 140 et 150 bpm,
    la variance diffère, le centre se déplace de ``β·ln(h / 145)``."""
    s = world_e_structure()
    at_ref = daily_level(s, WORLD_E_LAST_DAY, 56, 0.03, 145.0)
    assert at_ref is not None
    assert at_ref.band.centre == at_ref.level.value
    z = statistics.NormalDist().inv_cdf(0.975)
    assert at_ref.band.high - at_ref.band.centre == pytest.approx(
        z * math.sqrt(at_ref.band.variance), rel=1e-12
    )
    for hr in (140.0, 150.0):
        other = daily_level(s, WORLD_E_LAST_DAY, 56, 0.03, hr)
        assert other is not None
        assert other.band.variance != pytest.approx(at_ref.band.variance, rel=1e-6)
        assert other.band.centre - at_ref.band.centre == pytest.approx(
            s.coef[0] * math.log(hr / 145.0), rel=1e-12
        )


def test_j14_the_means_read_the_smoothing_window() -> None:
    """J14 : les moyennes de ``daily_level`` prennent le résumé du jour
    ``last_day − N + 1``, pas celui de ``last_day − N`` (e09 déplacé sur chaque
    borne, son ``mean_x`` changé)."""
    s = world_e_structure()
    day, n = WORLD_E_LAST_DAY, 56

    def moved(on: date, shift: float) -> Structure:
        return dataclasses.replace(
            s,
            summaries=tuple(
                dataclasses.replace(x, day=on, mean_x=x.mean_x + shift)
                if x.activity_ref == "e09"
                else x
                for x in s.summaries
            ),
        )

    def band_variance(structure: Structure) -> float:
        found = daily_level(structure, day, n, 0.03, 140.0)
        assert found is not None
        return found.band.variance

    outside = day - timedelta(days=n)
    inside = day - timedelta(days=n - 1)
    assert band_variance(moved(outside, 0.5)) == band_variance(moved(outside, 0.0))
    assert band_variance(moved(inside, 0.5)) != pytest.approx(
        band_variance(moved(inside, 0.0)), rel=1e-9
    )


def test_j10_the_third_stage_has_no_window() -> None:
    """J10 : l'étage 3 n'a pas d'argument Fenêtre."""
    assert list(inspect.signature(daily_level).parameters) == [
        "structure",
        "day",
        "n_days",
        "tau",
        "hr_bpm",
    ]
    assert list(inspect.signature(shrunk_level).parameters) == [
        "points",
        "day",
        "n_days",
        "tau",
    ]


_POINTS = st.lists(
    st.tuples(
        st.integers(0, 70),
        st.floats(-1.0, 1.0, allow_nan=False),
        st.floats(1e-6, 1e-2, allow_nan=False),
    ),
    min_size=1,
    max_size=12,
)


def _points(drawn: list[tuple[int, float, float]]) -> list[Point]:
    return [Point(on(1 + d), v, w) for d, v, w in sorted(drawn)]


@settings(deadline=None, max_examples=50)
@given(_POINTS, st.floats(0.0, 0.2, allow_nan=False), st.integers(0, 28))
def test_j11_weight_and_value_bounds(
    drawn: list[tuple[int, float, float]], tau: float, after: int
) -> None:
    """J11 : ``0 ≤ weight ≤ 1`` ; ``|value − m̄| ≤ |ĉ·l|`` ; jamais d'exception (des
    jours qui se répètent, au besoin tous le même)."""
    points = _points(drawn)
    last = points[-1].day
    level = shrunk_level(points, last + timedelta(days=after), 56, tau)
    assert level is not None
    members = [p for p in points if p.day >= last - timedelta(days=55)]
    mean = statistics.fmean(p.value for p in members)
    if level.weight is None:
        assert level.value == mean
        return
    assert level.slope is not None
    assert 0.0 <= level.weight <= 1.0
    lever = -statistics.fmean((p.day - last).days / MONTH_DAYS for p in members)
    assert abs(level.value - mean) <= abs(level.slope * lever) + 1e-12


@settings(deadline=None, max_examples=50)
@given(_POINTS, st.floats(-1.0, 1.0, allow_nan=False), st.integers(0, 28))
def test_j12_a_constant_shifts_the_value(
    drawn: list[tuple[int, float, float]], shift: float, after: int
) -> None:
    """J12 : une même constante ajoutée à toutes les valeurs s'ajoute à ``value`` et
    ne change pas ``variance``."""
    points = _points(drawn)
    moved = [Point(p.day, p.value + shift, p.variance) for p in points]
    day = points[-1].day + timedelta(days=after)
    a = shrunk_level(points, day, 56, 0.03)
    b = shrunk_level(moved, day, 56, 0.03)
    assert a is not None
    assert b is not None
    assert b.value == pytest.approx(a.value + shift, abs=1e-9)
    assert b.variance == pytest.approx(a.variance, rel=1e-9, abs=1e-15)


def speed_points(
    *, skip_p0: bool = False, factor: float = 1.0, skip_k4: bool = False
) -> list[Point]:
    """Les 60 points du § 12.1 (vitesse habituelle)."""
    found = []
    for p in range(12):
        for k in range(5):
            if (skip_p0 and p == 0) or (skip_k4 and k == 4):
                continue
            value = 0.02 * (-1) ** p * 5 * k / MONTH_DAYS + 0.01 * (
                ((7 * k + 3 * p) % 5) - 2
            )
            found.append(Point(on(1 + 28 * p + 5 * k), factor * value, 0.00005))
    return found


@pytest.mark.parametrize(
    ("changes", "value", "estimated", "periods"),
    [
        ({}, 0.033357700640153615, True, 12),
        ({"skip_p0": True}, 0.03, False, 11),
        ({"factor": 3.0}, 0.05, True, 12),
        ({"skip_k4": True}, 0.03, False, 0),
    ],
)
def test_h1_the_hand_table(
    changes: dict[str, Any], value: float, estimated: bool, periods: int
) -> None:
    """H1 : les quatre lignes du tableau du § 12.1."""
    speed = habitual_speed(speed_points(**changes), 28, on(336))
    assert speed.value == pytest.approx(value, rel=1e-9)
    assert speed.estimated is estimated
    assert speed.periods == periods
    expected = AscentState.ESTIMATED if estimated else AscentState.DEFAULT
    assert speed.state is expected


def test_h2_h3_no_point_and_a_bad_length() -> None:
    """H2 : aucun point : ``DEFAULT``, aucune période ; H3 : ``length_days = 0`` :
    ``AscentError``."""
    speed = habitual_speed([], 28, on(10))
    assert (speed.value, speed.estimated, speed.periods) == (0.03, False, 0)
    assert speed.state is AscentState.DEFAULT
    with pytest.raises(AscentError):
        habitual_speed(HAND, 0, on(25))


def test_h4_disjoint_periods_from_the_end() -> None:
    """H4 : un point au jour ``end − L`` appartient à la seconde période."""
    end, length = on(100), 10
    days = [91, 92, 93, 94, 90, 81, 82, 83, 84, 71]
    points = [Point(on(d), 0.01 * d, 1e-4) for d in sorted(days)]
    assert habitual_speed(points, length, end).periods == 1


def test_h5_a_period_before_the_first_point() -> None:
    """H5 : une période qui commencerait avant le premier point n'est pas comptée."""
    inside = [Point(on(d), 0.01 * d, 1e-4) for d in range(5, 10)]
    later = [Point(on(d), 0.01 * d, 1e-4) for d in range(6, 11)]
    assert habitual_speed(inside, 10, on(14)).periods == 1
    assert habitual_speed(later, 10, on(14)).periods == 0


def test_h6_a_negative_tau_square() -> None:
    """H6 : des pentes égales, plus serrées que leurs erreurs : ``τ = 0``,
    ``ESTIMATED``."""
    points = [
        Point(on(1 + 28 * p + 5 * k), 0.01 * k, 1e-4)
        for p in range(12)
        for k in range(5)
    ]
    speed = habitual_speed(points, 28, on(336))
    assert speed.value == 0.0
    assert speed.state is AscentState.ESTIMATED
    assert speed.periods == 12


def test_h7_a_period_on_a_single_day_is_not_rich() -> None:
    """H7 : douze périodes dont une de cinq points le même jour : 11 périodes riches,
    ``DEFAULT``, sans exception."""
    points = [
        Point(on(1 + 28 * p + (0 if p == 5 else 5 * k)), 0.01 * k, 1e-4)
        for p in range(12)
        for k in range(5)
    ]
    speed = habitual_speed(points, 28, on(336))
    assert speed.periods == 11
    assert speed.state is AscentState.DEFAULT
