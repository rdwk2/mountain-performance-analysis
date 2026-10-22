"""Ce que la page « sortie » affiche, calculé dans ``outing_views.py`` (§ 6.2, § 6.3 et
§ 8.2 du brief M5-2 ; ``0010`` D3, D4.11, D7.1, D7.3).

Sur la paire commitée (``appariement_reference.gpx``, ``appariement_trace_x01.gpx``)
et la courbe synthétique, par ``match_outing`` et ``check_outing`` ; sans Streamlit.
"""

import functools
import math
from pathlib import Path

import pytest

from fixtures.matching import MATCH_REFERENCE_GPX, MATCH_TRACE_GPX
from fixtures.scoring import chain, scores
from fixtures.segments import anchored_departure_then_gap, matched
from mountain_perf.outing_views import (
    POINT_STATUS_LABELS,
    admitted_spans,
    clock_label,
    effort_rows,
    followed_route,
    gaps,
    point_name,
)
from mountain_perf.runs import OutingCheck, OutingMatch, check_outing, match_outing
from mountain_perf.schemas import (
    CLOCKS,
    Clock,
    ClockKind,
    PointStatus,
    Unavailability,
)

FIXTURES = Path(__file__).parent / "fixtures"
REFERENCE = FIXTURES / MATCH_REFERENCE_GPX
TRACE = FIXTURES / MATCH_TRACE_GPX
CURVE = FIXTURES / "courbe_synthetique.csv"
UNFOLLOWED_ROUTE = FIXTURES / "mini_11.gpx"
"""Un préparé que la trace commitée ne suit pas (piège 5 du brief)."""

ELAPSED = Clock(ClockKind.ELAPSED)
MOVING_1 = Clock(ClockKind.MOVING, 0)


@functools.cache
def _pair(route: Path = REFERENCE) -> tuple[OutingMatch, OutingCheck]:
    match = match_outing(route, TRACE, CURVE, {})
    return match, check_outing(match)


# ---------------------------------------------------------------------------
# Les libellés partagés avec mperf match
# ---------------------------------------------------------------------------


def test_point_status_labels() -> None:
    assert dict(POINT_STATUS_LABELS) == {
        PointStatus.FOUND: "trouvé",
        PointStatus.ANCHORED: "ancré",
        PointStatus.AMBIGUOUS: "ambigu",
        PointStatus.ABSENT: "absent",
        PointStatus.OUT_OF_TOLERANCE: "hors ε",
        PointStatus.UNDEFINED_TANGENT: "tangente indéfinie",
    }


@pytest.mark.parametrize(
    ("clock", "label"),
    [
        (ELAPSED, "écoulé"),
        (MOVING_1, "M θ1"),
        (Clock(ClockKind.MOVING_OR_UNDETERMINED, 4), "(M+U) θ5"),
    ],
)
def test_clock_label(clock: Clock, label: str) -> None:
    assert clock_label(clock) == label


def test_point_name_of_a_score_point_and_of_a_place() -> None:
    """Un point de score se nomme par son indice ; un lieu, par son nom (le cas
    Passages de ``tests/fixtures/scoring.py``, où le lieu ``B`` est un point
    d'erreur)."""
    passages = chain("Passages").passages
    points = scores("Passages").observation.error_points
    assert [point_name(point, passages) for point in points] == [
        "point 1",
        "B",
        "A",
        "point 2",
        "point 3",
    ]
    assert [point.passage_index for point in points] == [None, 0, 1, None, None]


# ---------------------------------------------------------------------------
# Le tracé suivi (0010 D4.11)
# ---------------------------------------------------------------------------


def test_followed_route_on_the_committed_pair() -> None:
    match, _ = _pair()
    coverage = match.result.coverage
    followed = followed_route(match.result)
    assert followed.reference_length_m == coverage.reference_length_m
    assert followed.admitted_m == coverage.admitted_m
    assert followed.admitted_share == coverage.fraction
    assert followed.prefix_end_m == coverage.prefix_end_m
    assert followed.point_counts == (
        (PointStatus.FOUND, 2),
        (PointStatus.ANCHORED, 2),
        (PointStatus.AMBIGUOUS, 0),
        (PointStatus.ABSENT, 0),
        (PointStatus.OUT_OF_TOLERANCE, 0),
        (PointStatus.UNDEFINED_TANGENT, 0),
    )


def test_the_compared_part_can_go_beyond_the_comparable_prefix() -> None:
    """Sur ``anchored_departure_then_gap()``, le premier segment est exclu par le
    trou : le préfixe s'arrête à 12 m environ, la partie comparée en couvre 257."""
    result = matched(anchored_departure_then_gap())
    coverage = result.coverage
    followed = followed_route(result)
    assert followed.admitted_m == coverage.admitted_m
    assert followed.prefix_end_m == coverage.prefix_end_m
    assert followed.admitted_m == pytest.approx(257.0, abs=1e-6)
    assert followed.prefix_end_m == pytest.approx(12.0, abs=1e-6)
    assert followed.admitted_m > followed.prefix_end_m


def test_admitted_spans_are_the_admitted_segments_in_order() -> None:
    match, _ = _pair()
    segments = match.result.segments
    assert all(segment.admitted for segment in segments)
    assert admitted_spans(match.result) == tuple(
        (segment.start_m, segment.end_m) for segment in segments
    )
    assert len(admitted_spans(match.result)) == 3


def test_admitted_spans_leave_out_the_excluded_segment() -> None:
    """Le segment exclu par le trou est absent ; les deux segments admis, qui se
    touchent à 500 m, restent deux intervalles."""
    result = matched(anchored_departure_then_gap())
    first, *admitted = result.segments
    assert not first.admitted
    assert all(segment.admitted for segment in admitted)
    spans = admitted_spans(result)
    assert spans == tuple((segment.start_m, segment.end_m) for segment in admitted)
    assert len(spans) == 2
    assert spans[0][1] == spans[1][0] == 500.0


# ---------------------------------------------------------------------------
# Prévu contre réalisé, l'effort effectif (0010 D3, D7.1)
# ---------------------------------------------------------------------------


def test_one_effort_row_per_report_clock_in_order() -> None:
    _, check = _pair()
    rows = effort_rows(check.scores, check.clocks)
    assert tuple(row.clock for row in rows) == check.clocks
    assert len(rows) == 3


def test_the_observed_time_is_that_of_each_clock() -> None:
    """``T`` sous chaque horloge : la somme des temps des segments admis sous cette
    horloge — 260 s sous ``M θ1``, pas les 320 de l'écoulé."""
    _, check = _pair()
    segments = check.scores.observation.segments
    rows = effort_rows(check.scores, check.clocks)
    for row in rows:
        index = CLOCKS.index(row.clock)
        assert row.observed_s == math.fsum(s.times_s[index] for s in segments)
    by_clock = {row.clock: row.observed_s for row in rows}
    assert by_clock[ELAPSED] == pytest.approx(320.0)
    assert by_clock[MOVING_1] == pytest.approx(260.0)


def test_the_effective_effort_is_exp_of_the_support_level() -> None:
    """``e* = exp(L)`` au bit, ``L`` le niveau du support (jamais le diagnostic à
    temps positifs, qui existe sous ``M θ1`` : un segment y a un temps nul) ; et
    ``e* · T = P`` (v0 : la durée prévue est inversement proportionnelle à
    l'effort)."""
    _, check = _pair()
    usage = check.scores.usage
    assert usage is not None
    rows = effort_rows(check.scores, check.clocks)
    moving = usage.clocks[CLOCKS.index(MOVING_1)]
    assert moving.diagnostic is not None
    assert moving.diagnostic.metrics.log_ratio.value != moving.support.log_ratio.value
    for row in rows:
        index = CLOCKS.index(row.clock)
        assert row.usage is not None
        for scenario, effort in (
            (usage, row.usage),
            (check.scores.control, row.control),
        ):
            level = scenario.clocks[index].support.log_ratio.value
            assert level is not None
            assert effort.log_ratio == level
            assert effort.unavailability is None
            assert effort.effective_effort == math.exp(level)
            assert effort.projected_s is not None
            assert effort.effective_effort * row.observed_s == pytest.approx(
                effort.projected_s, rel=1e-12
            )


def test_without_reference_there_is_no_usage_effort() -> None:
    match, _ = _pair()
    check = check_outing(match, with_reference=False)
    rows = effort_rows(check.scores, check.clocks)
    assert rows
    assert all(row.usage is None for row in rows)
    assert all(row.control.effective_effort is not None for row in rows)


def test_without_comparable_part_the_effort_is_unavailable() -> None:
    """Piège 5 : une seule horloge, l'écoulé ; ``L`` vaut « support insuffisant »
    sous les deux scénarios."""
    _, check = _pair(UNFOLLOWED_ROUTE)
    (row,) = effort_rows(check.scores, check.clocks)
    assert row.clock == ELAPSED
    for effort in (row.usage, row.control):
        assert effort is not None
        assert effort.effective_effort is None
        assert effort.projected_s is None
        assert effort.log_ratio is None
        assert effort.unavailability is Unavailability.INSUFFICIENT_SUPPORT


# ---------------------------------------------------------------------------
# L'écart cumulé aux points (0010 D7.3)
# ---------------------------------------------------------------------------


def test_gaps_are_the_usage_passage_errors() -> None:
    match, check = _pair()
    usage = check.scores.usage
    assert usage is not None
    found = gaps(check.scores, match.passages, check.clocks)
    assert found is not None
    observation = check.scores.observation
    assert found.origin_m == observation.origin_m
    assert len(found.rows) == len(observation.error_points) == 3
    for k, (row, point) in enumerate(
        zip(found.rows, observation.error_points, strict=True)
    ):
        assert row.name == point_name(point, match.passages)
        assert row.distance_m == point.distance_m
        for c, clock in enumerate(check.clocks):
            errors = usage.clocks[CLOCKS.index(clock)].passage_errors
            assert errors is not None
            assert row.errors_s[c] == errors.errors_s[k].value
    assert [row.name for row in found.rows] == ["point 1", "point 2", "point 3"]
    assert found.rows[0].errors_s[1] != found.rows[0].errors_s[0]


def test_the_largest_gap_is_that_of_each_clock() -> None:
    """``max |C_k|`` de ``passage_errors`` sous chaque horloge : 160 s sous l'écoulé
    et ``(M+U) θ1``, 101,7 s sous ``M θ1`` — la colonne de l'écoulé prise partout se
    verrait."""
    match, check = _pair()
    usage = check.scores.usage
    assert usage is not None
    found = gaps(check.scores, match.passages, check.clocks)
    assert found is not None
    for c, clock in enumerate(check.clocks):
        errors = usage.clocks[CLOCKS.index(clock)].passage_errors
        assert errors is not None
        assert found.max_abs_s[c] == errors.max_abs_error_s.value
    assert found.max_abs_s == (
        160.00000004615183,
        101.66666666427102,
        160.00000004615183,
    )


def test_without_usage_there_are_no_gaps() -> None:
    match, _ = _pair()
    check = check_outing(match, with_reference=False)
    assert gaps(check.scores, match.passages, check.clocks) is None
