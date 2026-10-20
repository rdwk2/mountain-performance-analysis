"""Ce que l'interface affiche d'une projection : ``passage_rows``, ``clock_time``,
``civil_start``, ``interval_speeds`` (§ 6.8 et § 8.2 du brief M5-1)."""

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pytest

from fixtures.curves import SUPPORT_CURVE
from fixtures.projection import CURVE_REF, ENDPOINTS, SIX_INTERVAL_PROFILE
from mountain_perf.model import PROJECTION_PARAMETER_SPECS, project, projected_timeline
from mountain_perf.model.views import (
    CIVIL_ZONE,
    civil_start,
    clock_time,
    interval_speeds,
    passage_rows,
)
from mountain_perf.runs import project_route
from mountain_perf.schemas import ParameterSet, Projection

FIXTURES = Path(__file__).parent / "fixtures"
RELATIVE = 1e-12


def _six_intervals(effort: float = 1.0) -> Projection:
    return project(
        SIX_INTERVAL_PROFILE,
        SUPPORT_CURVE,
        ParameterSet(PROJECTION_PARAMETER_SPECS, {"effort": effort}),
        curve_ref=CURVE_REF,
        endpoints=ENDPOINTS,
    )


# ---------------------------------------------------------------------------
# passage_rows
# ---------------------------------------------------------------------------


def test_the_departure_row_has_no_segment() -> None:
    first = passage_rows(_six_intervals())[0]
    assert first.name == "Départ"
    assert first.segment is None
    assert first.speed_ms is None
    assert first.ascent_rate_ms is None
    assert first.clock_time is None


def test_each_row_carries_the_preceding_segment_and_its_means() -> None:
    projection = _six_intervals()
    rows = passage_rows(projection)
    assert len(rows) == len(projection.passages)
    for i, row in enumerate(rows[1:], start=1):
        segment = projection.segments[i - 1]
        assert row.segment == segment
        assert segment.end == projection.passages[i]
        assert row.speed_ms == segment.distance_m / segment.duration_s
        assert row.ascent_rate_ms == segment.ascent_m / segment.duration_s
        passage = projection.passages[i]
        assert (row.name, row.distance_m, row.elevation_m, row.arrival_s) == (
            passage.point.point.name,
            passage.point.distance_m,
            passage.point.elevation_m,
            passage.arrival_s,
        )


def test_refuge_and_arrival_values() -> None:
    """Pas au bit : l'arrivée au Refuge vaut ``123.33333333333331``, pas ``370 / 3``."""
    refuge, arrival = passage_rows(_six_intervals())[1:]
    assert refuge.name == "Refuge"
    assert refuge.speed_ms == pytest.approx(250 / (370 / 3), rel=RELATIVE)
    assert refuge.ascent_rate_ms == pytest.approx(10 / (370 / 3), rel=RELATIVE)
    assert arrival.name == "Arrivée"
    assert arrival.speed_ms == pytest.approx(350 / (1250 / 3), rel=RELATIVE)
    assert arrival.ascent_rate_ms == pytest.approx(60 / (1250 / 3), rel=RELATIVE)


def test_a_zero_duration_segment_has_no_means() -> None:
    """``mini_11.gpx`` : le départ synthétisé et le lieu « Départ », à la même
    abscisse."""
    run = project_route(
        FIXTURES / "mini_11.gpx", FIXTURES / "courbe_synthetique.csv", {}, {}
    )
    rows = passage_rows(run.projection)
    assert [row.name for row in rows[:2]] == ["Départ", "Départ"]
    assert rows[1].segment is not None
    assert rows[1].segment.duration_s == 0
    assert rows[1].speed_ms is None
    assert rows[1].ascent_rate_ms is None
    assert all(row.speed_ms is not None for row in rows[2:])


def test_rows_carry_the_clock_time_of_each_passage() -> None:
    projection = _six_intervals()
    start = civil_start(date(2026, 10, 24), time(23, 0))
    rows = passage_rows(projection, start)
    assert [row.clock_time for row in rows] == [
        clock_time(start, passage.arrival_s) for passage in projection.passages
    ]


# ---------------------------------------------------------------------------
# clock_time, civil_start
# ---------------------------------------------------------------------------


def test_the_duration_is_added_in_universal_time() -> None:
    """Départ la veille du passage à l'heure d'hiver, à 23 h ; six heures plus tard, il
    est 4 h (et non 5 h, l'addition faite dans le fuseau)."""
    start = datetime(2026, 10, 24, 23, 0, tzinfo=CIVIL_ZONE)
    later = clock_time(start, 6 * 3600)
    assert (later.year, later.month, later.day, later.hour, later.minute) == (
        2026,
        10,
        25,
        4,
        0,
    )
    assert later.utcoffset() == timedelta(hours=1)
    assert later == datetime(2026, 10, 25, 3, 0, tzinfo=UTC)


def test_zero_elapsed_is_the_start_itself() -> None:
    start = datetime(2026, 7, 1, 8, 0, tzinfo=CIVIL_ZONE)
    assert clock_time(start, 0) == start
    assert clock_time(start, 0).utcoffset() == timedelta(hours=2)


def test_a_naive_start_is_refused() -> None:
    with pytest.raises(
        ValueError, match=r"^L'heure de départ doit porter un fuseau\.$"
    ):
        clock_time(datetime(2026, 7, 1, 8, 0), 60)


@pytest.mark.parametrize(
    ("day", "at", "offset_h"),
    [
        (date(2026, 7, 1), time(8, 0), 2),
        (date(2026, 1, 15), time(8, 0), 1),
        (date(2026, 10, 25), time(2, 30), 2),
    ],
    ids=["été", "hiver", "ambiguë"],
)
def test_civil_start(day: date, at: time, offset_h: int) -> None:
    start = civil_start(day, at)
    assert (start.date(), start.time()) == (day, at)
    assert start.utcoffset() == timedelta(hours=offset_h)


# ---------------------------------------------------------------------------
# interval_speeds
# ---------------------------------------------------------------------------


def test_interval_speeds_are_the_inverse_of_the_projected_paces() -> None:
    projection = _six_intervals()
    speeds = interval_speeds(projection, SUPPORT_CURVE)
    assert len(speeds) == len(projection.profile.distance_m) - 1
    timeline = projected_timeline(
        projection.profile, SUPPORT_CURVE, projection.parameters
    )
    assert speeds == tuple(1 / pace for pace in timeline.pace_s_per_m)


def test_interval_speeds_follow_the_effort_of_the_projection() -> None:
    reference = interval_speeds(_six_intervals(), SUPPORT_CURVE)
    slower = interval_speeds(_six_intervals(0.9), SUPPORT_CURVE)
    assert slower == pytest.approx(
        tuple(0.9 * speed for speed in reference), rel=RELATIVE
    )
