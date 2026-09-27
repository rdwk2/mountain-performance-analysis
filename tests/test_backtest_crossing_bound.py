"""Borne haute ``end_position`` de ``crossing_candidates`` (§ 6.3 et § 8.3, test 3,
du brief M4a-3).

Les lignes du § 7.3.2 qui dépendent de la borne, sur le repère direct : un
franchissement de position ``π >= end_position`` n'est ni compté parmi les
franchissements orientés, ni candidat. ``end_position=None`` rend exactement ce que
rend l'appel sans le mot-clé, sur des cas de M4a-2a. Les tests de M4a-2a restent
tels quels.
"""

import math
from collections.abc import Callable

import pytest

from fixtures import matching as cases
from fixtures.matching import MatchCase
from fixtures.passages import DIRECT_FRAME, direct_trace
from mountain_perf.backtest import build_series, score_grid
from mountain_perf.backtest.geometry import frame_at
from mountain_perf.backtest.matching import crossing_candidates, window_bound_m
from mountain_perf.schemas import RecordedTrace

EPSILON_M = 30.0


def _bounded(
    trace: RecordedTrace, after: float, before: float
) -> tuple[tuple[float, ...], int]:
    """Positions des candidats et nombre de franchissements orientés, dans la forme
    de ``occurrence_crossing`` (§ 6.4) : fenêtre infinie, condition ouverte,
    ``π > after``, borne ``before``."""
    candidates, oriented = crossing_candidates(
        trace,
        build_series(trace),
        DIRECT_FRAME,
        after,
        math.inf,
        closed=False,
        tolerance_m=EPSILON_M,
        departure=False,
        end_position=before,
    )
    return tuple(c.position for c in candidates), oriented


STRAIGHT = (-2.0, -1.0, 0.0, 1.0, 2.0)
"""Franchissement exactement sur l'enregistrement 2 (``h = 0``) : ``π = 2``."""

STEP = (-2.0, -1.0, 1.0, 2.0)
"""Franchissement entre ``x = −1`` et ``x = 1`` : ``f = 0,5``, ``π = 1,5``."""


def test_crossing_exactly_at_the_bound_is_excluded() -> None:
    """§ 7.3.2 : franchissement en ``π = 2 = before`` : ni candidat, ni compté."""
    assert _bounded(direct_trace(STRAIGHT), 0.0, 2.0) == ((), 0)


def test_crossing_before_the_bound_is_a_candidate() -> None:
    assert _bounded(direct_trace(STRAIGHT), 0.0, 2.5) == ((2.0,), 1)


def test_crossing_beyond_the_bound_is_excluded() -> None:
    """Franchissement en 1,5, au-delà de ``before = 1`` (intervalle 1, où le
    parcours s'arrête)."""
    assert _bounded(direct_trace(STEP), 0.0, 1.0) == ((), 0)


def test_crossing_at_the_bound_inside_the_scanned_interval_is_excluded() -> None:
    """``π = 1,5 = before``, dans l'intervalle 1, parcouru (``1 < 1,5``) : exclu."""
    assert _bounded(direct_trace(STEP), 0.0, 1.5) == ((), 0)


def test_oriented_crossing_beyond_the_bound_is_not_counted() -> None:
    """``y = 45`` : franchissement orienté hors ε en 1,5, au-delà de
    ``before = 1,25`` mais dans l'intervalle 1, parcouru : non compté — ``absent``,
    pas ``hors ε``."""
    assert _bounded(direct_trace(STEP, y_m=45.0), 0.0, 1.25) == ((), 0)


def test_oriented_crossing_before_the_bound_is_counted() -> None:
    """La même trace, ``before = 3`` : un franchissement orienté, aucun candidat."""
    assert _bounded(direct_trace(STEP, y_m=45.0), 0.0, 3.0) == ((), 1)


def test_lower_bound_is_strict() -> None:
    """``π > after`` : ``after = 2`` exclut le franchissement en 2, ``after = 1,5``
    le garde (condition de M4a-2a, inchangée)."""
    assert _bounded(direct_trace(STRAIGHT), 2.0, 4.0) == ((), 0)
    assert _bounded(direct_trace(STRAIGHT), 1.5, 4.0) == ((2.0,), 1)


@pytest.mark.parametrize(
    "case",
    [cases.x01, cases.t05, cases.x03_bis, cases.window, cases.corner, cases.x14],
    ids=lambda f: f.__name__,
)
def test_no_bound_is_the_call_without_the_keyword(
    case: Callable[[], MatchCase],
) -> None:
    """``end_position=None`` rend exactement l'appel sans le mot-clé, pour chaque
    point de la grille, condition ouverte et fermée, depuis plusieurs ``π_cur``."""
    match = case()
    trace, series = match.trace, build_series(match.trace)
    step_m = match.parameters["score_step_m"]
    tolerance_m = match.parameters["lateral_tolerance_m"]
    for k, s_m in enumerate(score_grid(match.geometry.length_m, step_m)):
        frame = frame_at(match.geometry, s_m)
        if frame is None:
            continue
        for current in (0.0, 0.5 * (len(trace.time_s) - 1)):
            bound_m = window_bound_m(0.0, step_m, k, 0)
            for closed in (False, True):
                without = crossing_candidates(
                    trace,
                    series,
                    frame,
                    current,
                    bound_m,
                    closed=closed,
                    tolerance_m=tolerance_m,
                    departure=k == 0,
                )
                explicit = crossing_candidates(
                    trace,
                    series,
                    frame,
                    current,
                    bound_m,
                    closed=closed,
                    tolerance_m=tolerance_m,
                    departure=k == 0,
                    end_position=None,
                )
                assert explicit == without
