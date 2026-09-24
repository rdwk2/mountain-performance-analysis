"""Propriétés de l'appariement (§ 8, test 5 du brief M4a-2a ; ``0010`` D4.2–D4.9).

1. **Trace qui suit une référence droite** : tous les points ``FOUND``, ``c = e = 1``,
   chaque ``t*`` égal à l'instant où ``x`` atteint ``s_k``, interpolé entre les
   enregistrements qui l'encadrent — lu sur la description plane, pas sur la
   géographie du code.
2. **Traces quelconques** : les propriétés du § 5a.8, ``time_s == t(π)`` et
   ``realized_m == d_r(π)`` pour un point daté, ``|lateral_m| < ε`` pour un point
   trouvé. La stratégie sait produire trous, retours, points non datés et extrémités
   ancrées : un ``@example`` de chacun est fixé, et un test vérifie qu'elle les tire.
"""

from bisect import bisect_right
from collections.abc import Callable
from itertools import pairwise

import pytest
from hypothesis import example, find, given, settings

from fixtures import matching as cases
from fixtures.matching import (
    MAX_STRAIGHT_RECORDS,
    MatchCase,
    StraightCase,
    straight_case,
)
from mountain_perf.backtest import build_series, realized_at, score_grid, time_at
from mountain_perf.schemas import PointStatus, ScorePointObservation
from strategies import straight_cases, wandering_cases

FAST = straight_case(260.0, -1.0, 0.0, [(3.0, 1)], [1.0, -1.0])
"""Pas de 1/64 s à 3 m/s sur la référence la plus courte : 5 974 enregistrements."""

SLOW = straight_case(2999.0, -20.0, 10.0, [(0.3, 640)], [-1.0, 0.5])
"""Pas de 10 s à 0,3 m/s sur une référence de 2 999 m : 3 m par enregistrement."""

MIXED = straight_case(1013.0, -7.5, -3.0, [(0.3, 1), (3.0, 640), (1.7, 97)], [0.25])
"""Pas extrêmes alternés : 1/64 s à 0,3 m/s, puis 10 s à 3 m/s."""


@pytest.mark.parametrize("straight", [FAST, SLOW, MIXED])
def test_straight_examples_reach_the_extreme_steps_under_the_cap(
    straight: StraightCase,
) -> None:
    steps = [b - a for a, b in pairwise(straight.time_s)]
    assert len(straight.time_s) < MAX_STRAIGHT_RECORDS
    assert min(steps) >= 1 / 64
    assert max(steps) <= 10.0
    assert straight.x_m[-1] > straight.case.geometry.length_m


@settings(deadline=None)
@given(straight_cases())
@example(FAST)
@example(SLOW)
@example(MIXED)
def test_trace_following_a_straight_reference(straight: StraightCase) -> None:
    points = straight.case.match()
    assert [p.status for p in points] == [PointStatus.FOUND] * len(points)
    assert all(p.candidate_count == 1 and p.event_count == 1 for p in points)
    xs, ts = straight.x_m, straight.time_s
    for point in points:
        s_m = point.nominal_m
        i = bisect_right(xs, s_m) - 1
        expected_s = ts[i] + (s_m - xs[i]) / (xs[i + 1] - xs[i]) * (ts[i + 1] - ts[i])
        assert point.time_s == pytest.approx(expected_s, abs=1e-6)


def _dated(point: ScorePointObservation) -> tuple[float, float]:
    assert point.position is not None
    assert point.time_s is not None
    return point.position, point.time_s


@settings(deadline=None)
@given(wandering_cases())
@example(cases.t05())
@example(cases.x03_bis())
@example(cases.window())
@example(cases.x01())
def test_properties_of_match_points(case: MatchCase) -> None:
    """§ 5a.8. Exemples fixés : T05 (trou), X03-bis (retour en arrière), Fenêtre
    (point non daté), X01 (deux extrémités ancrées)."""
    points = case.match()
    series = build_series(case.trace)
    grid = score_grid(case.geometry.length_m, case.parameters["score_step_m"])
    assert [p.index for p in points] == list(range(len(grid)))
    assert [p.nominal_m for p in points] == list(grid)
    dated = [_dated(p) for p in points if p.dated]
    for (position_a, time_a), (position_b, time_b) in pairwise(dated):
        assert position_a < position_b
        assert time_a < time_b
    for a, b in pairwise(points):
        assert a.effective_m < b.effective_m
    last = len(points) - 1
    tolerance_m = case.parameters["lateral_tolerance_m"]
    for point in points:
        if point.effective_m != point.nominal_m:
            assert point.index in (0, last)
            assert point.status is PointStatus.ANCHORED
        if point.dated:
            position, time_s = _dated(point)
            assert time_s == time_at(case.trace, position)
            assert point.realized_m == realized_at(series, position)
        if point.status is PointStatus.FOUND:
            assert point.lateral_m is not None
            assert abs(point.lateral_m) < tolerance_m


# ---------------------------------------------------------------------------
# Ce que la stratégie des traces quelconques sait produire
# ---------------------------------------------------------------------------

_SEARCH = settings(max_examples=2000, database=None, deadline=None)


def _has_gap(case: MatchCase) -> bool:
    return any(build_series(case.trace).gap_after)


def _backtracks(case: MatchCase) -> bool:
    return "backtrack" in case.features


def _undated_point(case: MatchCase) -> bool:
    return not all(point.dated for point in case.match())


def _anchored_departure(case: MatchCase) -> bool:
    return case.match()[0].status is PointStatus.ANCHORED


def _anchored_arrival(case: MatchCase) -> bool:
    return case.match()[-1].status is PointStatus.ANCHORED


def _found_departure_and_arrival(case: MatchCase) -> bool:
    points = case.match()
    return points[0].status is points[-1].status is PointStatus.FOUND


@pytest.mark.parametrize(
    "condition",
    [
        _has_gap,
        _backtracks,
        _undated_point,
        _anchored_departure,
        _anchored_arrival,
        _found_departure_and_arrival,
    ],
)
def test_wandering_strategy_reaches(condition: Callable[[MatchCase], bool]) -> None:
    find(wandering_cases(), condition, settings=_SEARCH)
