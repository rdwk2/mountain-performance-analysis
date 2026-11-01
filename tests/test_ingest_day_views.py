"""Les vues des jours (``ingest/day_views.py``, AN2-1) : chaque vue, chaque branche,
chaque motif d'absence ; l'égalité exacte de l'instant propre et de ``t``, avec et
sans ``strict`` ; les ordres des états et des statuts ; l'union d'une nuit et d'une
sieste ; le milieu habituel ; la Training Readiness du réveil ; le changement
d'heure.

Les seuils à leur borne et hors domaine sont dans ``test_ingest_day_views_bounds.py`` ;
la propriété « les données d'après ``t`` ne changent pas la vue à ``t`` » dans
``test_ingest_day_views_properties.py``. Jours inventés (``fixtures/days.py``)."""

from __future__ import annotations

import dataclasses
import math
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from fixtures.days import (
    AUTUMN_DAY,
    DAY,
    DEFAULT_SEGMENTS,
    EMPTY_DAY_SERIES,
    EMPTY_HISTORY,
    EMPTY_NIGHT_SERIES,
    PLUS1,
    PLUS2,
    SPRING_DAY,
    SRC,
    at,
    day_record,
    day_series,
    empty_day,
    history,
    load_balance_block,
    midnight,
    nap,
    night,
    night_series,
    readiness,
    resting_hr,
    status_block,
    truncated_day,
    vo2_max_block,
)
from mountain_perf.ingest.day_views import (
    body_battery_at,
    night_assessment,
    night_before,
    nights_after,
    readiness_at,
    readiness_on_waking,
    resting_hr_at,
    resting_hr_on,
    series_between,
    sleep_within,
    training_status_at,
)
from mountain_perf.schemas import (
    WAKING_CONTEXT,
    BodyBatterySeries,
    BodyBatteryStatus,
    DayRecord,
    DaySeries,
    DayState,
    HeartRateSeries,
    HrvSeries,
    Nap,
    Night,
    NightFlag,
    NightSeries,
    NightState,
    RespirationSeries,
    RestingHrStatus,
    RestlessMomentsSeries,
    SeriesKind,
    SleepSegment,
    SleepStage,
    SpO2Series,
    StressSeries,
    TrainingStatusHistory,
    TrainingStatusKind,
    ViewAbsence,
)

NEXT = DAY + timedelta(days=1)
PREVIOUS = DAY - timedelta(days=1)
H = 3600.0


def _quiet(day: date = DAY, **changes: Any) -> DayRecord:
    """Un jour complet sans nuit, sieste, entrée ni série, sauf ``changes``."""
    defaults: dict[str, Any] = {
        "night": None,
        "naps": (),
        "readiness": (),
        "series": EMPTY_DAY_SERIES,
    }
    return day_record(day, **{**defaults, **changes})


def _full_night(day: date = DAY, **changes: Any) -> Any:
    """Une nuit de 23 h à 7 h tout en sommeil léger (8 h mesurées), sans non
    mesurable."""
    defaults: dict[str, Any] = {
        "deep_s": 0.0,
        "light_s": 28800.0,
        "rem_s": 0.0,
        "awake_s": 0.0,
        "unmeasurable_s": 0.0,
        "segments": (SleepSegment(0.0, 28800.0, SleepStage.LIGHT),),
        "series": EMPTY_NIGHT_SERIES,
    }
    return night(day, **{**defaults, **changes})


def _bb_day(day: date, times: tuple[float, ...], levels: tuple[int, ...]) -> DaySeries:
    series = BodyBatterySeries(
        times, levels, (BodyBatteryStatus.MEASURED,) * len(times), SRC
    )
    return DaySeries(None, None, series, None, None)


def _bb_night(times: tuple[float, ...], levels: tuple[int, ...]) -> NightSeries:
    series = BodyBatterySeries(times, levels, (None,) * len(times), SRC)
    return NightSeries(None, None, series, None, None, None, None)


# --- sleep_within ------------------------------------------------------------------


def test_sleep_within_without_episode_is_absent() -> None:
    for days in ((), (_quiet(),)):
        result = sleep_within(days, at(DAY, 0), at(DAY, 20))
        assert result.episodes == ()
        assert (result.sleep_s, result.sleep_absence) == (None, ViewAbsence.NO_EPISODE)
        assert (result.coverage_fraction, result.coverage_absence) == (
            None,
            ViewAbsence.NO_EPISODE,
        )


@pytest.mark.parametrize(
    ("rem_capable", "expected"), [(None, 19800.0), (False, 19800.0), (True, None)]
)
def test_sleep_within_a_night_without_rem_duration(
    rem_capable: bool | None, expected: float | None
) -> None:
    """La durée du paradoxal manque : un appareil qui ne dit pas s'il le détecte, ou
    qui ne le détecte pas, compte profond + léger (5 h 30) ; un appareil qui le détecte
    rend le sommeil absent."""
    record = day_record(naps=(), night=night(rem_capable=rem_capable, rem_s=None))
    result = sleep_within((record,), at(DAY, 0), at(DAY, 8))
    assert result.sleep_s == expected
    if expected is None:
        assert result.sleep_absence is ViewAbsence.NO_MEASURED_SLEEP


def test_sleep_within_one_night_counts_its_measured_sleep() -> None:
    result = sleep_within((day_record(naps=()),), at(DAY, 0), at(DAY, 8))
    assert len(result.episodes) == 1
    assert result.episodes[0].day == DAY
    assert result.sleep_s == 25200.0
    assert result.coverage_fraction == pytest.approx((28800 - 1800) / 28800, abs=1e-9)


def test_sleep_within_disjoint_episodes_sum_their_sleeps() -> None:
    result = sleep_within((day_record(),), at(DAY, 0), at(DAY, 20))
    assert [type(item.episode).__name__ for item in result.episodes] == ["Night", "Nap"]
    assert result.sleep_s == 25200.0 + 1500.0


def test_sleep_within_touching_episodes_do_not_overlap() -> None:
    """Une sieste qui commence à la fin de la nuit ne la recouvre pas : la somme, même
    sans segments."""
    record = day_record(
        night=night(segments=()),
        naps=(nap(start=at(DAY, 7), end=at(DAY, 8), sleep_s=1800.0),),
    )
    result = sleep_within((record,), at(DAY, 0), at(DAY, 20))
    assert result.sleep_absence is None
    assert result.sleep_s == 25200.0 + 1800.0


def test_c9_iv_union_of_night_segments_and_nap_window() -> None:
    """nuit de 23 h à 7 h tout en sommeil, sieste de 6 h 30 à 8 h avec 1 h 30 de
    sommeil : 9 h sur l'union, pas 9 h 30."""
    record = day_record(
        night=_full_night(),
        naps=(nap(start=at(DAY, 6, 30), end=at(DAY, 8), sleep_s=5400.0),),
    )
    result = sleep_within((record,), at(DAY, 0), at(DAY, 9))
    assert result.sleep_s == 9 * H


def test_c9_iv_the_sum_bounds_the_union() -> None:
    """La même nuit dont la dernière heure est de l'éveil, la sieste avec 1 h : 8 h (la
    somme borne l'union, 8 h 30), pas 8 h 30."""
    record = day_record(
        night=_full_night(
            light_s=25200.0,
            awake_s=3600.0,
            segments=(
                SleepSegment(0.0, 25200.0, SleepStage.LIGHT),
                SleepSegment(25200.0, 28800.0, SleepStage.AWAKE),
            ),
        ),
        naps=(nap(start=at(DAY, 6, 30), end=at(DAY, 8), sleep_s=3600.0),),
    )
    result = sleep_within((record,), at(DAY, 0), at(DAY, 9))
    assert result.sleep_s == 8 * H


def test_sleep_within_awake_and_unmeasurable_segments_are_not_sleep() -> None:
    """L'union ne prend que les segments profond, léger, paradoxal : une heure d'éveil
    au milieu de la nuit et une heure non mesurable en sont exclues."""
    record = day_record(
        night=_full_night(
            segments=(
                SleepSegment(0.0, H, SleepStage.LIGHT),
                SleepSegment(H, 2 * H, SleepStage.AWAKE),
                SleepSegment(2 * H, 7 * H, SleepStage.LIGHT),
                SleepSegment(7 * H, 8 * H, SleepStage.UNMEASURABLE),
            ),
        ),
        naps=(nap(start=at(DAY, 6, 30), end=at(DAY, 8), sleep_s=5400.0),),
    )
    result = sleep_within((record,), at(DAY, 0), at(DAY, 9))
    assert result.sleep_s == 7.5 * H


def test_c9_iv_a_night_without_segments_that_overlaps_is_absent() -> None:
    record = day_record(
        night=_full_night(segments=()),
        naps=(nap(start=at(DAY, 6, 30), end=at(DAY, 8), sleep_s=5400.0),),
    )
    result = sleep_within((record,), at(DAY, 0), at(DAY, 9))
    assert (result.sleep_s, result.sleep_absence) == (None, ViewAbsence.NO_SEGMENTS)
    assert (result.coverage_fraction, result.coverage_absence) == (
        None,
        ViewAbsence.NO_SEGMENTS,
    )


def test_sleep_within_a_lone_night_without_segments_uses_its_summary() -> None:
    """Une nuit seule, sans segments : son sommeil (25 200 s) et sa couverture
    ((28 800 − 1 800) / 28 800, le non mesurable de son résumé) viennent de son
    résumé."""
    record = day_record(night=night(segments=()), naps=())
    result = sleep_within((record,), at(DAY, 0), at(DAY, 9))
    assert result.sleep_s == 25200.0
    assert result.coverage_fraction == pytest.approx((28800 - 1800) / 28800, abs=1e-9)


def test_sleep_within_a_night_without_measured_sleep() -> None:
    record = day_record(night=night(deep_s=None), naps=())
    result = sleep_within((record,), at(DAY, 0), at(DAY, 9))
    assert (result.sleep_s, result.sleep_absence) == (
        None,
        ViewAbsence.NO_MEASURED_SLEEP,
    )
    assert result.coverage_absence is None


def test_sleep_within_a_group_whose_night_has_no_measured_sleep() -> None:
    record = day_record(
        night=_full_night(light_s=None),
        naps=(nap(start=at(DAY, 6, 30), end=at(DAY, 8), sleep_s=5400.0),),
    )
    result = sleep_within((record,), at(DAY, 0), at(DAY, 9))
    assert result.sleep_absence is ViewAbsence.NO_MEASURED_SLEEP
    assert result.coverage_fraction == 1.0


def test_sleep_within_a_lone_night_without_unmeasurable() -> None:
    record = day_record(night=night(unmeasurable_s=None), naps=())
    result = sleep_within((record,), at(DAY, 0), at(DAY, 9))
    assert result.sleep_s == 25200.0
    assert (result.coverage_fraction, result.coverage_absence) == (
        None,
        ViewAbsence.NO_UNMEASURABLE,
    )


def test_sleep_within_group_coverage_reads_the_segments_in_the_windows() -> None:
    """Un groupe : le non mesurable de ses segments, coupé à l'union de ses fenêtres (le
    segment de 7 h à 9 h sort de la nuit ; la sieste finit à 8 h)."""
    record = day_record(
        night=_full_night(
            segments=(
                SleepSegment(0.0, 8 * H, SleepStage.LIGHT),
                SleepSegment(8 * H, 10 * H, SleepStage.UNMEASURABLE),
            ),
        ),
        naps=(nap(start=at(DAY, 6, 30), end=at(DAY, 8), sleep_s=5400.0),),
    )
    result = sleep_within((record,), at(DAY, 0), at(DAY, 10))
    assert result.coverage_fraction == pytest.approx(8 / 9, abs=1e-9)


def test_sleep_within_coverage_never_negative() -> None:
    record = day_record(night=night(segments=(), unmeasurable_s=40000.0), naps=())
    result = sleep_within((record,), at(DAY, 0), at(DAY, 9))
    assert result.coverage_fraction == 0.0


def test_sleep_within_first_motive_in_the_order_of_groups() -> None:
    first = day_record(PREVIOUS, night=night(PREVIOUS, unmeasurable_s=None), naps=())
    second = day_record(
        night=_full_night(segments=()),
        naps=(nap(start=at(DAY, 6, 30), end=at(DAY, 8), sleep_s=5400.0),),
    )
    result = sleep_within((first, second), at(PREVIOUS, 0), at(DAY, 9))
    assert result.coverage_absence is ViewAbsence.NO_UNMEASURABLE
    assert result.sleep_absence is ViewAbsence.NO_SEGMENTS
    flipped = sleep_within(
        (
            day_record(
                PREVIOUS,
                night=_full_night(PREVIOUS, segments=()),
                naps=(nap(PREVIOUS, start=at(PREVIOUS, 6, 30), end=at(PREVIOUS, 8)),),
            ),
            day_record(night=night(unmeasurable_s=None, deep_s=None), naps=()),
        ),
        at(PREVIOUS, 0),
        at(DAY, 9),
    )
    assert flipped.coverage_absence is ViewAbsence.NO_SEGMENTS
    assert flipped.sleep_absence is ViewAbsence.NO_SEGMENTS


def test_sleep_within_counts_sleep_before_start() -> None:
    """Conséquence 1 du moteur : une nuit commencée avant ``start``, finie dedans, est
    comptée entière."""
    result = sleep_within((day_record(naps=()),), at(DAY, 5), at(DAY, 9))
    assert result.sleep_s == 25200.0


def test_sleep_within_an_episode_finished_after_end_is_not_counted() -> None:
    """Conséquence 2 du moteur : une sieste presque entière dans l'intervalle, finie une
    minute après ``end``, n'est pas comptée."""
    result = sleep_within((day_record(night=None),), at(DAY, 13), at(DAY, 14, 29))
    assert result.sleep_absence is ViewAbsence.NO_EPISODE


def test_sleep_within_start_bound_is_closed() -> None:
    result = sleep_within((day_record(naps=()),), at(DAY, 7), at(DAY, 9))
    assert result.sleep_s == 25200.0
    after = sleep_within((day_record(naps=()),), at(DAY, 7, 0, 1), at(DAY, 9))
    assert after.sleep_absence is ViewAbsence.NO_EPISODE


def test_sleep_within_night_ending_at_end_with_and_without_strict() -> None:
    """L'égalité exacte : la nuit finit à 7 h, ``end`` à 7 h."""
    days = (day_record(naps=()),)
    assert sleep_within(days, at(DAY, 0), at(DAY, 7)).sleep_s == 25200.0
    strict = sleep_within(days, at(DAY, 0), at(DAY, 7), strict=True)
    assert strict.sleep_absence is ViewAbsence.NO_EPISODE


def test_sleep_within_midnight_night_and_midnight_end() -> None:
    """Une nuit finie à minuit, ``end`` à minuit."""
    record = day_record(
        night=night(start=at(PREVIOUS, 16), end=midnight(DAY), segments=()), naps=()
    )
    result = sleep_within((record,), at(PREVIOUS, 20), midnight(DAY))
    assert result.sleep_s == 25200.0
    assert (
        sleep_within(
            (record,), at(PREVIOUS, 20), midnight(DAY), strict=True
        ).sleep_absence
        is ViewAbsence.NO_EPISODE
    )


def test_sleep_within_end_must_not_precede_start() -> None:
    with pytest.raises(ValueError, match=r"^end doit valoir au moins start"):
        sleep_within((), at(DAY, 9), at(DAY, 8))
    assert sleep_within((), at(DAY, 9), at(DAY, 9)).episodes == ()


# --- body_battery_at -----------------------------------------------------------------


def test_body_battery_at_takes_a_day_point() -> None:
    record = _quiet(series=_bb_day(DAY, (10 * H, 11 * H), (55, 50)))
    reading = body_battery_at((record,), at(DAY, 12))
    assert (reading.point_instant, reading.level) == (at(DAY, 11), 50)
    assert reading.status is BodyBatteryStatus.MEASURED
    assert (reading.from_night, reading.day, reading.age_s) == (False, DAY, 3600.0)
    assert reading.source == SRC
    assert reading.absence is None


def test_body_battery_at_before_any_point_is_absent() -> None:
    record = _quiet(series=_bb_day(DAY, (10 * H,), (55,)))
    reading = body_battery_at((record,), at(DAY, 9))
    assert reading.absence is ViewAbsence.NO_POINT
    assert reading.point_instant is None
    assert reading.level is None


def test_body_battery_at_takes_the_night_point_at_the_end_of_the_night() -> None:
    """un point du jour à la fin de la nuit cède la place au point de la nuit (fenêtre
    fermée à sa fin)."""
    record = _quiet(
        night=night(series=_bb_night((0.0, 8 * H), (30, 80))),
        series=_bb_day(DAY, (7 * H,), (60,)),
    )
    reading = body_battery_at((record,), at(DAY, 7, 30))
    assert (reading.point_instant, reading.level, reading.from_night) == (
        at(DAY, 7),
        80,
        True,
    )
    assert reading.status is None


def test_body_battery_at_a_day_point_at_the_end_of_the_night_is_dropped() -> None:
    """La fenêtre est fermée à sa fin même sans point de la nuit à cet instant : le
    point du jour de 7 h est écarté, le dernier point de la nuit (6 h) vaut."""
    record = _quiet(
        night=night(series=_bb_night((0.0, 7 * H), (30, 70))),
        series=_bb_day(DAY, (7 * H,), (60,)),
    )
    reading = body_battery_at((record,), at(DAY, 7, 30))
    assert (reading.point_instant, reading.level) == (at(DAY, 6), 70)


def test_body_battery_at_strict_at_the_end_of_the_night() -> None:
    """Avec ``strict``, la nuit finie à l'instant ne compte pas : ni sa fenêtre, ni ses
    points ; le dernier point du jour avant 7 h vaut."""
    record = _quiet(
        night=night(series=_bb_night((0.0, 7 * H), (30, 70))),
        series=_bb_day(DAY, (6.5 * H, 7 * H), (61, 62)),
    )
    reading = body_battery_at((record,), at(DAY, 7), strict=True)
    assert (reading.point_instant, reading.level, reading.from_night) == (
        at(DAY, 6, 30),
        61,
        False,
    )
    plain = body_battery_at((record,), at(DAY, 7))
    assert (plain.point_instant, plain.from_night) == (at(DAY, 6), True)


def test_body_battery_at_the_window_is_closed_at_its_start() -> None:
    """Un point du jour à l'instant du début de la nuit est écarté : le point de la nuit
    (même instant, fichier du jour suivant) est rendu."""
    first = _quiet(series=_bb_day(DAY, (23 * H,), (45,)))
    second = _quiet(
        NEXT,
        night=night(NEXT, series=_bb_night((0.0,), (44,))),
        series=EMPTY_DAY_SERIES,
    )
    reading = body_battery_at((first, second), at(NEXT, 8))
    assert (reading.point_instant, reading.level, reading.day, reading.from_night) == (
        at(DAY, 23),
        44,
        NEXT,
        True,
    )


def test_body_battery_at_ignores_a_night_in_progress() -> None:
    """À 3 h, la nuit n'est pas finie : sa fenêtre ne retire pas les points du jour, et
    son point de 2 h ne compte pas."""
    record = _quiet(
        night=night(series=_bb_night((3 * H,), (50,))),
        series=_bb_day(DAY, (H,), (40,)),
    )
    reading = body_battery_at((record,), at(DAY, 3))
    assert (reading.point_instant, reading.level, reading.from_night) == (
        at(DAY, 1),
        40,
        False,
    )


def test_body_battery_at_drops_night_points_outside_their_window() -> None:
    record = _quiet(night=night(series=_bb_night((0.0, 8 * H + 600), (30, 90))))
    reading = body_battery_at((record,), at(DAY, 12))
    assert (reading.point_instant, reading.level) == (at(PREVIOUS, 23), 30)


def test_body_battery_at_drops_night_points_before_their_window() -> None:
    record = _quiet(night=night(series=_bb_night((-600.0,), (30,))))
    assert body_battery_at((record,), at(DAY, 12)).absence is ViewAbsence.NO_POINT


def test_body_battery_at_no_day_point_outside_the_known_night() -> None:
    record = _quiet(
        night=night(series=_bb_night((6 * H,), (70,))),
        series=_bb_day(DAY, (7 * H,), (60,)),
    )
    reading = body_battery_at((record,), at(DAY, 7, 30))
    assert (reading.point_instant, reading.level) == (at(DAY, 5), 70)


def _spring_pair(
    first_times: tuple[float, ...], second_times: tuple[float, ...]
) -> tuple[DayRecord, DayRecord]:
    """Le 25 mars (fenêtre à +01:00) et le 26 (à +02:00) : leurs fenêtres se recouvrent
    d'une heure, de 22 h à 23 h UTC le 25."""
    first = _quiet(
        SPRING_DAY, series=_bb_day(SPRING_DAY, first_times, (41,) * len(first_times))
    )
    after = SPRING_DAY + timedelta(days=1)
    start = midnight(after, PLUS2)
    second = _quiet(
        after,
        window_start=start,
        data_end=start + timedelta(days=1),
        series=_bb_day(after, second_times, (42,) * len(second_times)),
    )
    return first, second


def test_body_battery_at_spring_overlap_keeps_the_oldest_file() -> None:
    first, second = _spring_pair((23.5 * H,), (0.5 * H,))
    reading = body_battery_at((first, second), datetime(2001, 3, 25, 23, tzinfo=UTC))
    assert reading.point_instant == datetime(2001, 3, 25, 22, 30, tzinfo=UTC)
    assert (reading.level, reading.day) == (41, SPRING_DAY)


def test_body_battery_at_spring_overlap_with_distinct_instants() -> None:
    first, second = _spring_pair((23.25 * H,), (0.5 * H,))
    reading = body_battery_at((first, second), datetime(2001, 3, 25, 23, tzinfo=UTC))
    assert reading.level == 42
    assert reading.day == SPRING_DAY + timedelta(days=1)


def _autumn_pair() -> tuple[DayRecord, DayRecord]:
    """Le 28 octobre, sa fenêtre de 24 h à +02:00 (fin à 22 h UTC), et le 29, qui
    commence à 23 h UTC : un trou d'une heure."""
    start = midnight(AUTUMN_DAY, PLUS2)
    first = _quiet(
        AUTUMN_DAY,
        window_start=start,
        data_end=start + timedelta(days=1),
        series=_bb_day(AUTUMN_DAY, (23 * H,), (30,)),
    )
    after = AUTUMN_DAY + timedelta(days=1)
    second = _quiet(after, series=_bb_day(after, (0.0,), (31,)))
    return first, second


def test_body_battery_at_autumn_hole_ages_the_last_point() -> None:
    first, second = _autumn_pair()
    reading = body_battery_at(
        (first, second), datetime(2001, 10, 28, 22, 30, tzinfo=UTC)
    )
    assert reading.point_instant == datetime(2001, 10, 28, 21, tzinfo=UTC)
    assert reading.age_s == 1.5 * H


def test_body_battery_at_strict_on_a_day_point() -> None:
    record = _quiet(series=_bb_day(DAY, (10 * H, 11 * H), (55, 50)))
    assert body_battery_at((record,), at(DAY, 11)).level == 50
    strict = body_battery_at((record,), at(DAY, 11), strict=True)
    assert (strict.level, strict.age_s) == (55, 3600.0)


# --- night_before, nights_after ------------------------------------------------------


def test_night_before_at_the_exact_end() -> None:
    days = (day_record(),)
    found = night_before(days, at(DAY, 7))
    assert (found.day, found.gap_s, found.absence) == (DAY, 0.0, None)
    assert found.night == days[0].night
    strict = night_before(days, at(DAY, 7), strict=True)
    assert (strict.night, strict.absence) == (None, ViewAbsence.NO_NIGHT_BEFORE)


def test_night_before_at_midnight() -> None:
    record = day_record(night=night(start=at(PREVIOUS, 16), end=midnight(DAY)))
    found = night_before((record,), midnight(DAY))
    assert found.gap_s == 0.0
    assert found.day == DAY


def test_night_before_takes_the_latest_end() -> None:
    days = (day_record(), day_record(NEXT))
    found = night_before(days, at(NEXT, 12))
    assert (found.day, found.gap_s) == (NEXT, 5 * H)


def test_night_before_the_latest_end_even_from_an_earlier_day() -> None:
    """La plus grande fin, pas le dernier jour : une nuit d'un jour antérieur qui finit
    plus tard l'emporte."""
    late = day_record(night=night(start=at(DAY, 1), end=at(DAY, 9)))
    early = day_record(NEXT, night=night(NEXT, start=at(DAY, 2), end=at(DAY, 8)))
    assert night_before((late, early), at(DAY, 12)).day == DAY


def test_night_before_equal_ends_take_the_last_day() -> None:
    first = day_record(night=night(start=at(DAY, 1), end=at(DAY, 9)))
    second = day_record(NEXT, night=night(NEXT, start=at(DAY, 2), end=at(DAY, 9)))
    assert night_before((first, second), at(DAY, 12)).day == NEXT


def _late_night() -> DayRecord:
    """La nuit finit à 7 h ; un segment finit à 7 h 30, un point de HRV est à 7 h 20,
    les moments agités n'ont qu'un point, à 7 h 40."""
    series = NightSeries(
        heart_rate=HeartRateSeries((0.0,), (50.0,), SRC),
        stress=None,
        body_battery=None,
        hrv=HrvSeries((7 * H, 8 * H + 1200, 8 * H + 2400), (40.0, 41.0, 42.0), SRC),
        respiration=None,
        spo2=None,
        restless_moments=RestlessMomentsSeries((8 * H + 2400,), (2,), SRC),
    )
    segments = (
        *DEFAULT_SEGMENTS[:-1],
        SleepSegment(27000.0, 30600.0, SleepStage.UNMEASURABLE),
    )
    return day_record(night=night(series=series, segments=segments), naps=())


def test_night_before_renders_the_night_as_known_at_the_instant() -> None:
    """Q1 : la nuit rendue à 7 h 10 n'a ni le segment fini à 7 h 30, ni le point de
    7 h 20, ni la série dont le seul point est à 7 h 40 ; fenêtre, durées et autres
    séries inchangées."""
    record = _late_night()
    assert record.night is not None
    found = night_before((record,), at(DAY, 7, 10))
    assert found.night is not None
    assert found.night.segments == DEFAULT_SEGMENTS[:-1]
    assert found.night.series.hrv is not None
    assert found.night.series.hrv.time_s == (7 * H,)
    assert found.night.series.restless_moments is None
    assert found.night.series.heart_rate == record.night.series.heart_rate
    assert (found.night.start, found.night.end) == (
        record.night.start,
        record.night.end,
    )
    assert found.night.deep_s == record.night.deep_s


def test_night_before_cuts_at_the_instant_with_and_without_strict() -> None:
    """À 7 h 40 : le point de HRV de 7 h 40 est rendu ; avec ``strict``, non. Le segment
    fini à 7 h 30 : rendu à 7 h 30, pas avec ``strict`` à 7 h 30."""
    record = _late_night()
    at_40 = night_before((record,), at(DAY, 7, 40)).night
    assert at_40 is not None
    assert at_40.series.hrv is not None
    assert at_40.series.hrv.time_s[-1] == 8 * H + 2400
    strict_40 = night_before((record,), at(DAY, 7, 40), strict=True).night
    assert strict_40 is not None
    assert strict_40.series.hrv is not None
    assert strict_40.series.hrv.time_s[-1] == 8 * H + 1200
    at_30 = night_before((record,), at(DAY, 7, 30)).night
    assert at_30 is not None
    assert at_30.segments[-1].end_s == 30600.0
    strict_30 = night_before((record,), at(DAY, 7, 30), strict=True).night
    assert strict_30 is not None
    assert strict_30.segments[-1].end_s != 30600.0


def test_sleep_within_renders_its_nights_as_known_at_end() -> None:
    """Q1 : l'épisode de nuit rendu est coupé à ``end`` ; le sommeil d'une nuit seule
    reste son résumé."""
    record = _late_night()
    result = sleep_within((record,), at(DAY, 0), at(DAY, 7, 10))
    (episode,) = result.episodes
    assert isinstance(episode.episode, type(record.night))
    known = episode.episode
    assert known.segments == DEFAULT_SEGMENTS[:-1]
    assert result.sleep_s == 25200.0


def test_sleep_within_reads_the_segments_known_at_end() -> None:
    """Q1, dans le calcul : un segment non mesurable de 7 h à 7 h 30 (hors de la nuit),
    avec une sieste de 6 h 30 à 7 h 20 qui la recouvre. À 7 h 20 il n'est pas fini : il
    ne compte pas (couverture 1) ; à 7 h 30 il compte (20 min dans les fenêtres) ; avec
    ``strict`` à 7 h 30, non."""
    record = day_record(
        night=_full_night(
            segments=(
                SleepSegment(0.0, 8 * H, SleepStage.LIGHT),
                SleepSegment(8 * H, 8.5 * H, SleepStage.UNMEASURABLE),
            )
        ),
        naps=(nap(start=at(DAY, 6, 30), end=at(DAY, 7, 20), sleep_s=1800.0),),
    )
    assert sleep_within((record,), at(DAY, 0), at(DAY, 7, 20)).coverage_fraction == 1.0
    windows_s = (8 * 60 + 20) * 60.0
    at_30 = sleep_within((record,), at(DAY, 0), at(DAY, 7, 30)).coverage_fraction
    assert at_30 == pytest.approx((windows_s - 1200) / windows_s, abs=1e-9)
    strict = sleep_within((record,), at(DAY, 0), at(DAY, 7, 30), strict=True)
    assert strict.coverage_fraction == 1.0


def test_nights_after_the_first_ones_strictly_after() -> None:
    days = tuple(day_record(DAY + timedelta(days=i)) for i in range(4))
    found = nights_after(days, at(DAY, 7), 2)
    assert [item.day for item in found] == [NEXT, NEXT + timedelta(days=1)]
    assert found[0].delay_s == 24 * H
    assert found[0].night == days[1].night


def test_nights_after_fewer_than_count() -> None:
    days = (day_record(), day_record(NEXT))
    assert [item.day for item in nights_after(days, at(DAY, 7), 5)] == [NEXT]
    assert nights_after(days, at(NEXT, 7), 5) == ()
    assert [item.day for item in nights_after(days, at(DAY, 6), 5)] == [DAY, NEXT]


def test_nights_after_in_the_order_of_their_end() -> None:
    """Une nuit d'un jour antérieur qui finit plus tard passe après."""
    late = day_record(night=night(start=at(DAY, 1), end=at(DAY, 9)))
    early = day_record(NEXT, night=night(NEXT, start=at(DAY, 2), end=at(DAY, 8)))
    assert [item.day for item in nights_after((late, early), at(DAY, 0), 2)] == [
        NEXT,
        DAY,
    ]


def test_nights_after_reads_after_the_instant() -> None:
    """Hors de la règle commune : elle rend ce qui suit ``after``."""
    found = nights_after((day_record(),), at(PREVIOUS, 12), 1)
    assert found[0].delay_s == 19 * H


# --- training_status_at, readiness_at -------------------------------------------------


def test_training_status_at_a_timestamped_status_at_the_exact_instant() -> None:
    block = status_block()
    assert block.timestamp is not None
    histo = TrainingStatusHistory((block,), (), (), (), ())
    reading = training_status_at(histo, TrainingStatusKind.STATUS, block.timestamp)
    assert (reading.block, reading.age_s, reading.absence) == (block, 0.0, None)
    strict = training_status_at(
        histo, TrainingStatusKind.STATUS, block.timestamp, strict=True
    )
    assert (strict.block, strict.absence) == (None, ViewAbsence.NO_BLOCK)


def test_training_status_at_w15_an_undated_block_is_not_read_the_morning_of_d() -> None:
    """un bloc sans horodatage daté de D, ``t`` au matin de D : pas rendu ; à minuit
    qui suit D (son instant propre) : rendu, sauf ``strict``."""
    block = load_balance_block()
    histo = TrainingStatusHistory((), (block,), (), (), ())
    kind = TrainingStatusKind.LOAD_BALANCE
    assert training_status_at(histo, kind, at(DAY, 8)).absence is ViewAbsence.NO_BLOCK
    assert training_status_at(histo, kind, midnight(NEXT)).block == block
    assert training_status_at(histo, kind, midnight(NEXT), strict=True).block is None


@pytest.mark.parametrize(
    ("kind", "field"),
    [
        (TrainingStatusKind.STATUS, "statuses"),
        (TrainingStatusKind.LOAD_BALANCE, "load_balances"),
        (TrainingStatusKind.VO2_MAX, "vo2_max"),
        (TrainingStatusKind.HEAT_ACCLIMATION, "heat_acclimation"),
        (TrainingStatusKind.ALTITUDE_ACCLIMATION, "altitude_acclimation"),
    ],
)
def test_training_status_at_reads_the_suite_of_its_kind(
    kind: TrainingStatusKind, field: str
) -> None:
    histo = history()
    reading = training_status_at(histo, kind, at(NEXT + timedelta(days=3), 0))
    assert reading.kind is kind
    assert reading.block == getattr(histo, field)[-1]


def test_training_status_at_a_block_without_proper_instant_is_never_read() -> None:
    histo = TrainingStatusHistory((), (), (vo2_max_block(proper_instant=None),), (), ())
    far = at(DAY + timedelta(days=400), 0)
    assert training_status_at(histo, TrainingStatusKind.VO2_MAX, far).absence is (
        ViewAbsence.NO_BLOCK
    )


def test_training_status_at_the_latest_proper_instant() -> None:
    """Le bloc du 9 horodaté après celui du 10 : le plus grand instant propre."""
    later = datetime(2001, 3, 11, 6, tzinfo=UTC)
    ninth = status_block(PREVIOUS, timestamp=later, proper_instant=later)
    tenth = status_block()
    histo = TrainingStatusHistory((ninth, tenth), (), (), (), ())
    reading = training_status_at(histo, TrainingStatusKind.STATUS, at(NEXT, 12))
    assert reading.block == ninth


def test_training_status_at_equal_instants_take_the_last_block() -> None:
    same = midnight(NEXT)
    first = vo2_max_block(PREVIOUS, proper_instant=same)
    second = vo2_max_block(proper_instant=same)
    histo = TrainingStatusHistory((), (), (first, second), (), ())
    assert training_status_at(histo, TrainingStatusKind.VO2_MAX, same).block == second


def test_training_status_at_empty_history() -> None:
    for kind in TrainingStatusKind:
        reading = training_status_at(EMPTY_HISTORY, kind, at(DAY, 12))
        assert (reading.kind, reading.block, reading.age_s, reading.absence) == (
            kind,
            None,
            None,
            ViewAbsence.NO_BLOCK,
        )


def test_readiness_at_the_exact_instant_and_strict() -> None:
    record = day_record()
    entry = record.readiness[0]
    reading = readiness_at((record,), entry.instant)
    assert (reading.day, reading.entry, reading.age_s) == (DAY, entry, 0.0)
    strict = readiness_at((record,), entry.instant, strict=True)
    assert (strict.entry, strict.absence) == (None, ViewAbsence.NO_ENTRY)


def test_readiness_at_the_latest_entry_of_any_context() -> None:
    other = readiness(instant=at(DAY, 18), input_context="UPDATE_REALTIME_VARIABLES")
    record = day_record(readiness=(readiness(), other))
    assert readiness_at((record,), at(DAY, 20)).entry == other


def test_readiness_at_the_latest_instant_even_from_an_earlier_day() -> None:
    late = day_record(readiness=(readiness(instant=at(NEXT, 9)),))
    early = day_record(NEXT, readiness=(readiness(NEXT, instant=at(NEXT, 8)),))
    reading = readiness_at((late, early), at(NEXT, 12))
    assert reading.day == DAY


def test_readiness_at_equal_instants_take_the_last_entry() -> None:
    first = readiness(score=10)
    second = readiness(score=20)
    record = day_record(readiness=(first, second))
    assert readiness_at((record,), at(DAY, 12)).entry == second
    other = day_record(
        NEXT, readiness=(readiness(NEXT, instant=at(DAY, 7, 5), score=30),)
    )
    assert readiness_at((record, other), at(DAY, 12)).day == NEXT


# --- night_assessment ----------------------------------------------------------------

THRESHOLDS: dict[str, Any] = {
    "max_unmeasured_fraction": 0.1,
    "short_sleep_s": 4 * H,
    "shift_s": 2 * H,
    "usual_window_days": 7,
    "usual_min_nights": 1,
}


def _assess(days: tuple[DayRecord, ...], day: date = DAY, **changes: Any) -> Any:
    return night_assessment(days, day, **{**THRESHOLDS, **changes})


def test_night_assessment_complete() -> None:
    result = _assess((day_record(),))
    assert result.state is NightState.COMPLETE
    assert (result.short, result.short_absence) == (False, None)
    assert result.measured_sleep_s == 25200.0
    assert result.unmeasured_fraction == 1800 / 28800
    assert result.midpoint_s == 3 * H
    assert result.flags == ()


def test_night_assessment_missing_without_document_or_night() -> None:
    for days in ((), (day_record(night=None),)):
        result = _assess(days)
        assert result.state is NightState.MISSING
        assert (result.short, result.short_absence) == (None, ViewAbsence.NO_NIGHT)
        assert (result.shifted, result.shifted_absence) == (None, ViewAbsence.NO_NIGHT)
        assert result.measured_sleep_s is None


def test_night_assessment_declared() -> None:
    assert _assess((day_record(night=night(from_device=False)),)).state is (
        NightState.DECLARED
    )
    assert _assess((day_record(night=night(from_device=None)),)).state is (
        NightState.COMPLETE
    )


def test_w14_a_declared_night_ending_after_data_end_stays_declared() -> None:
    record = truncated_day(night=night(from_device=False, end=at(DAY, 13)))
    assert _assess((record,)).state is NightState.DECLARED


def test_night_assessment_in_progress_after_data_end() -> None:
    record = truncated_day(night=night(end=at(DAY, 12, 0, 1)))
    assert _assess((record,)).state is NightState.IN_PROGRESS


def test_night_assessment_ending_at_data_end_is_not_in_progress() -> None:
    record = truncated_day(night=night(end=at(DAY, 12)))
    assert _assess((record,)).state is not NightState.IN_PROGRESS


def test_night_assessment_in_progress_with_a_provisional_window() -> None:
    assert _assess((day_record(night=night(window_confirmed=False)),)).state is (
        NightState.IN_PROGRESS
    )
    assert _assess((day_record(night=night(window_confirmed=None)),)).state is (
        NightState.COMPLETE
    )


def test_w6_an_empty_day_night_is_in_progress_only_if_provisional() -> None:
    assert _assess((empty_day(night=night()),)).state is NightState.COMPLETE
    assert _assess((empty_day(night=night(window_confirmed=False)),)).state is (
        NightState.IN_PROGRESS
    )


def test_night_assessment_partial() -> None:
    record = day_record(night=night(unmeasurable_s=3600.0))
    result = _assess((record,))
    assert result.state is NightState.PARTIAL
    assert result.unmeasured_fraction == 0.125


def test_night_assessment_without_unmeasurable_is_partial() -> None:
    result = _assess((day_record(night=night(unmeasurable_s=None)),))
    assert result.state is NightState.PARTIAL
    assert result.unmeasured_fraction is None


def test_w14_a_partial_night_in_progress_is_in_progress() -> None:
    record = day_record(night=night(unmeasurable_s=None, window_confirmed=False))
    assert _assess((record,)).state is NightState.IN_PROGRESS


def test_night_assessment_short_flag() -> None:
    result = _assess((day_record(),), short_sleep_s=8 * H)
    assert result.short is True
    assert result.flags == (NightFlag.SHORT,)


def test_night_assessment_short_unknown_without_measured_sleep() -> None:
    result = _assess((day_record(night=night(deep_s=None)),))
    assert (result.short, result.short_absence) == (None, ViewAbsence.NO_MEASURED_SLEEP)


def _nights(
    hours: list[tuple[int, int]], last: date = DAY, **changes: Any
) -> tuple[DayRecord, ...]:
    """Une nuit par jour avant ``last`` (les jours ``last − n`` … ``last − 1``), puis
    ``last`` ; ``hours`` : (début, fin) en heures locales, la veille pour un début
    après midi."""
    records: list[DayRecord] = []
    count = len(hours)
    for rank, (begin, finish) in enumerate(hours):
        day = last - timedelta(days=count - rank)
        start = at(day - timedelta(days=1), begin) if begin >= 12 else at(day, begin)
        end = (
            at(day - timedelta(days=1), finish)
            if finish > begin >= 12
            else at(day, finish)
        )
        duration = (end - start).total_seconds()
        records.append(
            day_record(
                day,
                naps=(),
                night=night(
                    day,
                    **{
                        "start": start,
                        "end": end,
                        "deep_s": 0.0,
                        "light_s": duration,
                        "rem_s": 0.0,
                        "awake_s": 0.0,
                        "unmeasurable_s": 0.0,
                        "segments": (),
                        "series": EMPTY_NIGHT_SERIES,
                        **changes,
                    },
                ),
            )
        )
    return (*records, day_record(last, naps=()))


def test_usual_midpoint_below_the_minimum_is_unknown() -> None:
    days = _nights([(23, 7), (23, 7)])
    result = _assess(days, usual_min_nights=3)
    assert result.usual_nights == 2
    assert (result.shifted, result.shifted_absence) == (
        None,
        ViewAbsence.BELOW_USUAL_MINIMUM,
    )
    assert result.usual_midpoint_s == pytest.approx(3 * H, abs=1e-6)


def test_usual_midpoint_at_the_minimum_is_known() -> None:
    days = _nights([(23, 7), (23, 7)])
    result = _assess(days, usual_min_nights=2)
    assert (result.shifted, result.shifted_absence) == (False, None)
    assert result.midpoint_distance_s == pytest.approx(0.0, abs=1e-6)


def test_shifted_night() -> None:
    days = (
        *_nights([(23, 7), (23, 7)])[:-1],
        day_record(night=night(start=at(DAY, 2), end=at(DAY, 10)), naps=()),
    )
    result = _assess(days, usual_min_nights=2)
    assert result.midpoint_s == 6 * H
    assert result.midpoint_distance_s == pytest.approx(3 * H, abs=1e-6)
    assert result.shifted is True
    assert result.flags == (NightFlag.SHIFTED,)


def test_usual_midpoint_is_a_circular_mean() -> None:
    """Des milieux de part et d'autre de minuit (23 h 30 et 0 h 30) : milieu habituel à
    minuit, pas à midi (la moyenne linéaire), rendu dans ``[0, 86400)`` (minuit vaut 0,
    jamais 86 400) ; une nuit de milieu minuit n'est pas décalée."""
    days = (
        *_nights([(20, 3), (21, 4)])[:-1],
        day_record(night=night(start=at(PREVIOUS, 20), end=at(DAY, 4)), naps=()),
    )
    result = _assess(days, usual_min_nights=2)
    assert result.usual_midpoint_s is not None
    assert 0.0 <= result.usual_midpoint_s < 86400.0
    assert min(result.usual_midpoint_s, 86400 - result.usual_midpoint_s) == (
        pytest.approx(0.0, abs=1e-6)
    )
    assert result.shifted is False


@pytest.mark.parametrize(
    "windows",
    [
        [(23, 7), (11, 19)],
        [(20, 4), (4, 12), (12, 20)],
        [(20, 4), (2, 10), (8, 16), (14, 22)],
    ],
)
def test_q2_equally_spread_midpoints_have_no_usual_midpoint(
    windows: list[tuple[int, int]],
) -> None:
    """Q2 : des milieux également répartis sur 24 h n'ont pas de moyenne circulaire.
    Avec ``usual_min_nights`` égal au nombre de nuits : milieu habituel et ``shifted``
    inconnus, motif ``dispersed_midpoints``. **Avec une nuit de plus exigée** (les deux
    motifs valent ensemble) : ``below_usual_minimum``, qui passe avant."""
    days = (*_nights(windows)[:-1], day_record(naps=()))
    result = _assess(days, usual_min_nights=len(windows))
    assert result.usual_nights == len(windows)
    assert result.usual_midpoint_s is None
    assert (result.shifted, result.shifted_absence) == (
        None,
        ViewAbsence.DISPERSED_MIDPOINTS,
    )
    more = _assess(days, usual_min_nights=len(windows) + 1)
    assert more.shifted_absence is ViewAbsence.BELOW_USUAL_MINIMUM


def test_q2_nearly_opposite_midpoints_still_have_a_mean() -> None:
    """Deux milieux à 3 h et 14 h 50 (pas tout à fait opposés) : une moyenne existe."""
    before = PREVIOUS - timedelta(days=1)
    days = (
        day_record(before, naps=(), night=night(before)),
        day_record(
            PREVIOUS,
            naps=(),
            night=night(
                PREVIOUS,
                start=at(PREVIOUS, 10, 50),
                end=at(PREVIOUS, 18, 50),
                unmeasurable_s=0.0,
            ),
        ),
        day_record(naps=()),
    )
    result = _assess(days, usual_min_nights=2, max_unmeasured_fraction=1.0)
    assert result.usual_nights == 2
    assert result.usual_midpoint_s is not None
    assert result.shifted_absence is None


def test_usual_midpoint_admits_only_complete_and_not_short_nights() -> None:
    partial = _nights([(23, 7)], unmeasurable_s=7200.0)
    assert _assess(partial).usual_nights == 0
    short = _nights([(5, 7)])
    assert _assess(short).usual_nights == 0
    kept = _nights([(23, 7)])
    assert _assess(kept).usual_nights == 1


def test_usual_midpoint_reads_the_window_of_days() -> None:
    """``[day − window, day − 1]`` : le jour ``day − window`` entre,
    ``day − window − 1`` non, ``day`` non."""
    days = _nights([(23, 7)] * 4)
    assert _assess(days, usual_window_days=3).usual_nights == 3
    assert _assess(days, usual_window_days=4).usual_nights == 4
    assert _assess(days, usual_window_days=40).usual_nights == 4


def test_night_midpoint_in_local_hours_across_the_change_of_time() -> None:
    """Une nuit de 23 h (+01:00) à 7 h (+02:00) : milieu des heures murales, 3 h."""
    record = day_record(
        SPRING_DAY,
        naps=(),
        night=night(
            SPRING_DAY,
            start=at(SPRING_DAY - timedelta(days=1), 23),
            end=at(SPRING_DAY, 7, offset=PLUS2),
        ),
    )
    assert _assess((record,), SPRING_DAY).midpoint_s == 3 * H


def test_night_assessment_with_a_missing_night_still_reads_the_usual() -> None:
    days = (*_nights([(23, 7), (23, 7)])[:-1], day_record(night=None))
    result = _assess(days)
    assert result.state is NightState.MISSING
    assert result.usual_nights == 2
    assert result.usual_midpoint_s == pytest.approx(3 * H, abs=1e-6)
    assert result.shifted_absence is ViewAbsence.NO_NIGHT


# --- resting_hr_on, resting_hr_at -----------------------------------------------------


def test_resting_hr_on_valid() -> None:
    result = resting_hr_on((day_record(),), DAY, min_sleep_s=4 * H)
    assert (result.day, result.resting_hr_bpm, result.status) == (
        DAY,
        48.0,
        RestingHrStatus.VALID,
    )
    assert result.proper_instant == midnight(NEXT)


def test_resting_hr_on_absent_without_document_or_value() -> None:
    assert resting_hr_on((), DAY, min_sleep_s=0).status is RestingHrStatus.ABSENT
    absent = resting_hr_on((day_record(resting_hr=None),), DAY, min_sleep_s=0)
    assert (absent.status, absent.resting_hr_bpm) == (RestingHrStatus.ABSENT, None)


def test_resting_hr_on_absent_on_an_empty_day() -> None:
    record = empty_day(resting_hr=resting_hr())
    result = resting_hr_on((record,), DAY, min_sleep_s=0)
    assert (result.status, result.resting_hr_bpm, result.proper_instant) == (
        RestingHrStatus.ABSENT,
        None,
        None,
    )


def test_w14_a_no_measurement_day_with_a_value_is_absent() -> None:
    record = day_record(state=DayState.NO_MEASUREMENT)
    result = resting_hr_on((record,), DAY, min_sleep_s=0)
    assert (result.status, result.resting_hr_bpm) == (RestingHrStatus.ABSENT, None)


def test_w14_a_truncated_day_without_night_is_provisional() -> None:
    result = resting_hr_on((truncated_day(night=None),), DAY, min_sleep_s=4 * H)
    assert result.status is RestingHrStatus.PROVISIONAL


def test_resting_hr_on_truncated_with_night_is_provisional() -> None:
    result = resting_hr_on((truncated_day(),), DAY, min_sleep_s=4 * H)
    assert (result.status, result.resting_hr_bpm) == (RestingHrStatus.PROVISIONAL, 48.0)


def test_resting_hr_on_no_night() -> None:
    for record in (
        day_record(night=None),
        day_record(night=night(deep_s=None)),
    ):
        assert resting_hr_on((record,), DAY, min_sleep_s=0).status is (
            RestingHrStatus.NO_NIGHT
        )


def test_resting_hr_on_proper_instant_across_the_change_of_time() -> None:
    record = day_record(SPRING_DAY)
    result = resting_hr_on((record,), SPRING_DAY, min_sleep_s=0)
    assert result.proper_instant == midnight(SPRING_DAY) + timedelta(days=1)
    assert result.proper_instant == at(SPRING_DAY + timedelta(days=1), 1, offset=PLUS2)


def test_resting_hr_at_the_exact_end_of_the_window() -> None:
    """La fenêtre du jour finit à ``t`` (minuit) : rendue, âge nul ; ``strict`` : le
    jour d'avant."""
    days = (day_record(PREVIOUS), day_record())
    reading = resting_hr_at(days, midnight(NEXT), min_sleep_s=0)
    assert (reading.day, reading.age_s) == (DAY, 0.0)
    strict = resting_hr_at(days, midnight(NEXT), min_sleep_s=0, strict=True)
    assert (strict.day, strict.age_s) == (PREVIOUS, 24 * H)


def test_resting_hr_at_a_truncated_day_ends_at_start_plus_24h() -> None:
    """Un jour tronqué à 10 h : sa fenêtre finit à début + 24 h (le plus tard de début +
    24 h et de sa fin des données), pas à 10 h."""
    record = truncated_day(data_end=at(DAY, 10))
    assert resting_hr_at((record,), at(DAY, 12), min_sleep_s=0).absence is (
        ViewAbsence.NO_RESTING_HR
    )
    reading = resting_hr_at((record,), midnight(NEXT), min_sleep_s=0)
    assert (reading.status, reading.proper_instant) == (
        RestingHrStatus.PROVISIONAL,
        midnight(NEXT),
    )


def test_resting_hr_at_skips_absent_days() -> None:
    days = (day_record(PREVIOUS), day_record(resting_hr=None))
    assert resting_hr_at(days, at(NEXT, 12), min_sleep_s=0).day == PREVIOUS


def test_resting_hr_at_skips_a_day_whose_value_is_absent() -> None:
    """Un jour ``no_measurement`` qui porte une valeur : son statut est ``absent``, et
    la vue rend le jour d'avant."""
    days = (day_record(PREVIOUS), day_record(state=DayState.NO_MEASUREMENT))
    assert resting_hr_at(days, at(NEXT, 12), min_sleep_s=0).day == PREVIOUS


def test_resting_hr_at_none() -> None:
    reading = resting_hr_at((), at(DAY, 12), min_sleep_s=0)
    assert reading == type(reading)(
        None, None, None, None, None, ViewAbsence.NO_RESTING_HR
    )


def test_resting_hr_at_a_night_ending_after_the_instant_does_not_count() -> None:
    """Un jour dont la nuit finit après sa propre fenêtre : à un instant entre les deux,
    la nuit ne compte pas (``no_night``) ; après, ``valid``."""
    record = day_record(
        night=night(start=at(DAY, 23), end=at(NEXT, 7)), naps=(), readiness=()
    )
    between = resting_hr_at((record,), at(NEXT, 3), min_sleep_s=0)
    assert between.status is RestingHrStatus.NO_NIGHT
    after = resting_hr_at((record,), at(NEXT, 7), min_sleep_s=0)
    assert after.status is RestingHrStatus.VALID


def _autumn_sunday(data_end: datetime) -> DayRecord:
    start = midnight(AUTUMN_DAY, PLUS2)
    return day_record(AUTUMN_DAY, window_start=start, data_end=data_end, naps=())


def test_resting_hr_a_complete_25_hour_day_ends_at_the_next_local_midnight() -> None:
    """Entrée décisive : le dimanche du passage à l'heure d'hiver, complet sur 25 h
    (début 00:00+02:00, ``data_end`` au lundi 00:00+01:00), sans document du lundi ; la
    veille, un samedi ordinaire à +02:00. Attendu : ``resting_hr_on`` rend pour instant
    propre le minuit du lundi (début + 25 h, pas début + 24 h) ; ``resting_hr_at`` à ce
    minuit rend la FC de repos du dimanche sans ``strict`` ; avec ``strict``, non (sa
    fenêtre ne finit pas strictement avant : c'est celle du samedi) ; une microseconde
    après, avec ``strict``, celle du dimanche."""
    monday = midnight(AUTUMN_DAY + timedelta(days=1), PLUS1)
    saturday_day = AUTUMN_DAY - timedelta(days=1)
    saturday_start = midnight(saturday_day, PLUS2)
    saturday = day_record(
        saturday_day,
        window_start=saturday_start,
        data_end=saturday_start + timedelta(days=1),
        naps=(),
    )
    sunday = _autumn_sunday(monday)
    days = (saturday, sunday)
    assert resting_hr_on(days, AUTUMN_DAY, min_sleep_s=0).proper_instant == monday
    assert monday - midnight(AUTUMN_DAY, PLUS2) == timedelta(hours=25)
    assert resting_hr_at(days, monday, min_sleep_s=0).day == AUTUMN_DAY
    assert resting_hr_at(days, monday, min_sleep_s=0, strict=True).day == saturday_day
    later = monday + timedelta(microseconds=1)
    assert resting_hr_at(days, later, min_sleep_s=0, strict=True).day == AUTUMN_DAY


def test_resting_hr_the_next_day_does_not_move_the_end_of_a_day() -> None:
    """Entrée décisive : le dimanche du passage à l'heure d'hiver tel que Garmin
    l'écrit, une fenêtre de 24 h à +02:00 (``data_end`` = début + 24 h, lundi
    00:00+02:00, soit dimanche 23:00+01:00), seul, puis suivi du lundi, dont la fenêtre
    commence une heure plus tard (00:00+01:00). Attendu, avec ou sans le lundi :
    l'instant propre du dimanche est début + 24 h (le plus tard de début + 24 h et de
    ``data_end`` ; le début du lundi n'y entre pas) ; à cet instant, ``resting_hr_at``
    rend le dimanche sans
    ``strict``, rien avec ``strict`` ; une demi-heure après (dans le trou d'une heure
    entre les deux fenêtres), le dimanche avec ``strict``."""
    start = midnight(AUTUMN_DAY, PLUS2)
    sunday = _autumn_sunday(start + timedelta(days=1))
    monday = day_record(AUTUMN_DAY + timedelta(days=1), naps=())
    end = start + timedelta(days=1)
    for days in ((sunday,), (sunday, monday)):
        assert resting_hr_on(days, AUTUMN_DAY, min_sleep_s=0).proper_instant == end
        assert resting_hr_at(days, end, min_sleep_s=0).day == AUTUMN_DAY
        assert resting_hr_at(days, end, min_sleep_s=0, strict=True).absence is (
            ViewAbsence.NO_RESTING_HR
        )
        half = end + timedelta(minutes=30)
        assert resting_hr_at(days, half, min_sleep_s=0, strict=True).day == AUTUMN_DAY


def test_resting_hr_an_autumn_sunday_in_its_last_hour_ends_at_its_data_end() -> None:
    """Entrée décisive : le dimanche du passage à l'heure d'hiver, sa fenêtre à
    +02:00, ses données jusqu'à 23:30+01:00 (début + 24 h 30 min, entre début + 24 h et
    son minuit local), sans document du lundi ; la veille, un samedi ordinaire.
    Attendu : l'instant propre du dimanche est sa fin des données, pas début + 24 h ; à
    23:15+01:00, ``resting_hr_at`` rend le samedi ; à la fin des données, le dimanche
    sans ``strict``, le samedi avec."""
    data_end = at(AUTUMN_DAY, 23, 30, offset=PLUS1)
    saturday_day = AUTUMN_DAY - timedelta(days=1)
    saturday_start = midnight(saturday_day, PLUS2)
    saturday = day_record(
        saturday_day,
        window_start=saturday_start,
        data_end=saturday_start + timedelta(days=1),
        naps=(),
    )
    days = (saturday, _autumn_sunday(data_end))
    assert resting_hr_on(days, AUTUMN_DAY, min_sleep_s=0).proper_instant == data_end
    quarter = at(AUTUMN_DAY, 23, 15, offset=PLUS1)
    assert resting_hr_at(days, quarter, min_sleep_s=0).day == saturday_day
    assert resting_hr_at(days, data_end, min_sleep_s=0).day == AUTUMN_DAY
    assert resting_hr_at(days, data_end, min_sleep_s=0, strict=True).day == saturday_day


# --- readiness_on_waking --------------------------------------------------------------


def test_readiness_on_waking_after_the_night() -> None:
    result = readiness_on_waking((day_record(),), DAY, tolerance_s=0)
    assert result.entry is not None
    assert result.entry.instant == at(DAY, 7, 5)
    assert (result.night_end, result.absence) == (at(DAY, 7), None)


def test_readiness_on_waking_a_little_before_the_end_within_tolerance() -> None:
    record = day_record(readiness=(readiness(instant=at(DAY, 6, 55)),))
    assert readiness_on_waking((record,), DAY, tolerance_s=0).absence is (
        ViewAbsence.NO_ENTRY_AFTER_NIGHT
    )
    assert readiness_on_waking((record,), DAY, tolerance_s=600).entry is not None


def test_readiness_on_waking_the_first_waking_entry() -> None:
    other = readiness(instant=at(DAY, 7, 2), input_context="UPDATE_REALTIME_VARIABLES")
    first = readiness(instant=at(DAY, 7, 10))
    second = readiness(instant=at(DAY, 9))
    record = day_record(readiness=(other, first, second))
    assert readiness_on_waking((record,), DAY, tolerance_s=0).entry == first
    assert first.input_context == WAKING_CONTEXT


def test_readiness_on_waking_before_the_next_nap() -> None:
    entry = readiness(instant=at(DAY, 14))
    record = day_record(readiness=(entry,))
    assert readiness_on_waking((record,), DAY, tolerance_s=0).absence is (
        ViewAbsence.NO_ENTRY_AFTER_NIGHT
    )
    before = day_record(readiness=(readiness(instant=at(DAY, 13, 59, 59)),))
    assert readiness_on_waking((before,), DAY, tolerance_s=0).entry is not None


def test_readiness_on_waking_a_nap_overlapping_the_night_is_not_the_next_one() -> None:
    overlapping = nap(start=at(DAY, 6, 30), end=at(DAY, 7, 30))
    record = day_record(naps=(overlapping,), readiness=(readiness(instant=at(DAY, 8)),))
    assert readiness_on_waking((record,), DAY, tolerance_s=0).entry is not None


def test_readiness_on_waking_the_next_nap_is_the_earliest_after_the_night() -> None:
    naps = (nap(start=at(DAY, 9), end=at(DAY, 9, 30)), nap())
    record = day_record(naps=naps, readiness=(readiness(instant=at(DAY, 10)),))
    assert readiness_on_waking((record,), DAY, tolerance_s=0).absence is (
        ViewAbsence.NO_ENTRY_AFTER_NIGHT
    )


def test_readiness_on_waking_without_night() -> None:
    for days in ((), (day_record(night=None),)):
        result = readiness_on_waking(days, DAY, tolerance_s=0)
        assert (result.entry, result.night_end, result.absence) == (
            None,
            None,
            ViewAbsence.NO_NIGHT,
        )


def test_readiness_on_waking_reads_only_its_day() -> None:
    other = day_record(NEXT, readiness=(readiness(NEXT, instant=at(DAY, 7, 30)),))
    record = day_record(readiness=())
    assert readiness_on_waking((record, other), DAY, tolerance_s=0).absence is (
        ViewAbsence.NO_ENTRY_AFTER_NIGHT
    )


# --- series_between -------------------------------------------------------------------


def _hr_day(
    day: date, start: datetime, times: tuple[float, ...], values: tuple[float, ...]
) -> DayRecord:
    return _quiet(
        day,
        window_start=start,
        data_end=start + timedelta(days=1),
        series=DaySeries(HeartRateSeries(times, values, SRC), None, None, None, None),
    )


def _between(
    days: tuple[DayRecord, ...],
    kind: SeriesKind,
    start: datetime,
    end: datetime,
    **changes: Any,
) -> Any:
    options: dict[str, Any] = {"step_s": 60.0, "min_coverage_fraction": 0.0}
    return series_between(days, kind, start, end, **{**options, **changes})


def test_series_between_day_heart_rate() -> None:
    record = _hr_day(DAY, midnight(DAY), (0.0, 60.0, 120.0), (50.0, 51.0, 52.0))
    window = _between(
        (record,), SeriesKind.DAY_HEART_RATE, midnight(DAY), at(DAY, 0, 2)
    )
    assert [(p.instant, p.value, p.day) for p in window.points] == [
        (midnight(DAY), 50.0, DAY),
        (at(DAY, 0, 1), 51.0, DAY),
        (at(DAY, 0, 2), 52.0, DAY),
    ]
    assert window.coverage_fraction == 1.0
    assert (window.duplicates, window.absence) == (0, None)


def test_series_between_strict_excludes_the_end() -> None:
    record = _hr_day(DAY, midnight(DAY), (0.0, 60.0, 120.0), (50.0, 51.0, 52.0))
    window = _between(
        (record,), SeriesKind.DAY_HEART_RATE, midnight(DAY), at(DAY, 0, 2), strict=True
    )
    assert [p.value for p in window.points] == [50.0, 51.0]


def test_series_between_a_point_before_start_is_not_counted() -> None:
    """Le point de 0 h est une microseconde avant ``start`` : il n'est pas compté, et
    l'intervalle n'a aucun point. Avec un minimum de couverture non nul (0,5), le motif
    est ``no_point``, pas ``below_coverage`` ; points vides, couverture 0."""
    record = _hr_day(DAY, midnight(DAY), (0.0,), (50.0,))
    start = midnight(DAY) + timedelta(microseconds=1)
    window = _between(
        (record,),
        SeriesKind.DAY_HEART_RATE,
        start,
        at(DAY, 1),
        min_coverage_fraction=0.5,
    )
    assert (window.points, window.coverage_fraction, window.absence) == (
        (),
        0.0,
        ViewAbsence.NO_POINT,
    )


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (SeriesKind.DAY_HEART_RATE, [(55.0, None, None)]),
        (SeriesKind.DAY_STRESS, [(20, None, None), (None, -2, None)]),
        (
            SeriesKind.DAY_BODY_BATTERY,
            [
                (40, None, BodyBatteryStatus.MEASURED),
                (41, None, BodyBatteryStatus.RESET),
            ],
        ),
        (SeriesKind.DAY_RESPIRATION, [(15.0, None, None), (None, -1, None)]),
        (SeriesKind.DAY_SPO2, [(96.0, None, None)]),
    ],
)
def test_series_between_each_day_kind(
    kind: SeriesKind, expected: list[tuple[Any, Any, Any]]
) -> None:
    record = day_record(night=None, series=day_series())
    window = _between((record,), kind, midnight(DAY), at(DAY, 1))
    assert [(p.value, p.code, p.status) for p in window.points] == expected


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (SeriesKind.NIGHT_HEART_RATE, [(52.0, None, None), (48.0, None, None)]),
        (SeriesKind.NIGHT_STRESS, [(10, None, None), (None, -1, None)]),
        (SeriesKind.NIGHT_BODY_BATTERY, [(30, None, None), (80, None, None)]),
        (SeriesKind.NIGHT_HRV, [(45.0, None, None), (50.0, None, None)]),
        (SeriesKind.NIGHT_RESPIRATION, [(14.0, None, None), (None, -2, None)]),
        (SeriesKind.NIGHT_SPO2, [(95.0, None, None), (94.0, None, None)]),
        (SeriesKind.NIGHT_RESTLESS_MOMENTS, [(1, None, None)]),
    ],
)
def test_series_between_each_night_kind(
    kind: SeriesKind, expected: list[tuple[Any, Any, Any]]
) -> None:
    window = _between((day_record(),), kind, at(PREVIOUS, 22), at(DAY, 8))
    assert [(p.value, p.code, p.status) for p in window.points] == expected
    assert all(p.day == DAY for p in window.points)


def test_series_between_a_night_series_needs_its_night_finished() -> None:
    days = (day_record(),)
    assert _between(
        days, SeriesKind.NIGHT_HEART_RATE, at(PREVIOUS, 22), at(DAY, 6)
    ).absence is (ViewAbsence.NO_POINT)
    assert _between(
        days, SeriesKind.NIGHT_HEART_RATE, at(PREVIOUS, 22), at(DAY, 7)
    ).points
    strict = _between(
        days, SeriesKind.NIGHT_HEART_RATE, at(PREVIOUS, 22), at(DAY, 7), strict=True
    )
    assert strict.absence is ViewAbsence.NO_POINT


def test_series_between_without_series_or_night() -> None:
    for days, kind in (
        ((), SeriesKind.DAY_HEART_RATE),
        ((_quiet(),), SeriesKind.DAY_STRESS),
        ((day_record(night=None),), SeriesKind.NIGHT_HRV),
        ((empty_day(),), SeriesKind.DAY_SPO2),
    ):
        window = _between(days, kind, at(PREVIOUS, 0), at(NEXT, 0))
        assert (window.points, window.absence) == ((), ViewAbsence.NO_POINT)


def test_series_between_spring_overlap_deduplicates_keeping_the_oldest() -> None:
    first = _hr_day(SPRING_DAY, midnight(SPRING_DAY), (23.5 * H,), (50.0,))
    after = SPRING_DAY + timedelta(days=1)
    second = _hr_day(after, midnight(after, PLUS2), (0.5 * H, H), (60.0, 61.0))
    window = _between(
        (first, second),
        SeriesKind.DAY_HEART_RATE,
        datetime(2001, 3, 25, 22, tzinfo=UTC),
        datetime(2001, 3, 25, 23, tzinfo=UTC),
    )
    assert [(p.value, p.day) for p in window.points] == [
        (50.0, SPRING_DAY),
        (61.0, after),
    ]
    assert window.duplicates == 1


def test_series_between_autumn_hole_lowers_the_coverage() -> None:
    """Le trou d'automne, sur [21 h, 0 h] UTC au pas d'une heure : deux points, rien
    d'interpolé, couverture 2/3 ; avec un minimum de 0,5, présente ; avec 0,7 (au-dessus
    de 2/3) : absente, ``below_coverage``, points vides, la couverture rendue (2/3)."""
    first = _hr_day(AUTUMN_DAY, midnight(AUTUMN_DAY, PLUS2), (23 * H,), (50.0,))
    after = AUTUMN_DAY + timedelta(days=1)
    second = _hr_day(after, midnight(after), (0.0,), (51.0,))
    start = datetime(2001, 10, 28, 21, tzinfo=UTC)
    end = datetime(2001, 10, 29, 0, tzinfo=UTC)
    present = _between(
        (first, second),
        SeriesKind.DAY_HEART_RATE,
        start,
        end,
        step_s=H,
        min_coverage_fraction=0.5,
    )
    assert len(present.points) == 2
    assert present.coverage_fraction == pytest.approx(2 / 3, abs=1e-9)
    absent = _between(
        (first, second),
        SeriesKind.DAY_HEART_RATE,
        start,
        end,
        step_s=H,
        min_coverage_fraction=0.7,
    )
    assert (absent.points, absent.absence) == ((), ViewAbsence.BELOW_COVERAGE)
    assert absent.coverage_fraction == pytest.approx(2 / 3, abs=1e-9)


def test_series_between_step_is_cut_at_the_end() -> None:
    record = _hr_day(DAY, midnight(DAY), (0.0, 50.0), (50.0, 51.0))
    window = _between(
        (record,), SeriesKind.DAY_HEART_RATE, midnight(DAY), at(DAY, 0, 1), step_s=40.0
    )
    assert window.coverage_fraction == pytest.approx(50 / 60, abs=1e-9)
    overlapping = _between(
        (record,), SeriesKind.DAY_HEART_RATE, midnight(DAY), at(DAY, 0, 1), step_s=55.0
    )
    assert overlapping.coverage_fraction == 1.0


def test_series_between_end_must_follow_start() -> None:
    with pytest.raises(ValueError, match=r"^end doit suivre start"):
        _between((), SeriesKind.DAY_HEART_RATE, at(DAY, 1), at(DAY, 1))


def test_default_segments_are_the_fixture_ones() -> None:
    """Garde-fou des valeurs littérales ci-dessus : la nuit par défaut."""
    default = night()
    assert default.segments == DEFAULT_SEGMENTS
    assert default.series == night_series(default.source)
    assert (default.start, default.end) == (at(PREVIOUS, 23), at(DAY, 7))
    durations = {
        stage: sum(s.end_s - s.start_s for s in DEFAULT_SEGMENTS if s.stage is stage)
        for stage in SleepStage
    }
    assert durations[SleepStage.LIGHT] == default.light_s
    assert durations[SleepStage.DEEP] == default.deep_s
    assert math.isclose(durations[SleepStage.REM], default.rem_s or 0.0)


# --- les règles que les tests ne tenaient pas (relecture) ----------------------------

D2 = DAY + timedelta(days=2)


def _series_at(name: str, times: tuple[float, ...]) -> Any:
    """Une série de la nuit de sorte ``name``, aux instants ``times``."""
    count = len(times)
    values = tuple(range(1, count + 1))
    floats = tuple(float(value) + 40.0 for value in values)
    nones: tuple[None, ...] = (None,) * count
    match name:
        case "heart_rate":
            return HeartRateSeries(times, floats, SRC)
        case "stress":
            return StressSeries(times, values, nones, SRC)
        case "body_battery":
            return BodyBatterySeries(times, values, nones, SRC)
        case "hrv":
            return HrvSeries(times, floats, SRC)
        case "respiration":
            return RespirationSeries(times, floats, nones, SRC)
        case "spo2":
            return SpO2Series(times, tuple(v + 50.0 for v in floats), SRC)
    return RestlessMomentsSeries(times, values, SRC)


_NIGHT_SERIES_NAMES = [
    "heart_rate",
    "stress",
    "body_battery",
    "hrv",
    "respiration",
    "spo2",
    "restless_moments",
]


@pytest.mark.parametrize("name", _NIGHT_SERIES_NAMES)
def test_strict_cuts_a_night_point_at_the_instant_in_each_series(name: str) -> None:
    """Une nuit finie à 7 h dont chaque série a un point à 7 h 30 (hors de sa fenêtre) :
    prise à 7 h 30 avec ``strict``, ce point est coupé, dans ``night_before`` comme dans
    ``sleep_within`` ; sans ``strict``, il reste."""
    series = dataclasses.replace(
        EMPTY_NIGHT_SERIES, **{name: _series_at(name, (0.0, 30600.0))}
    )
    days = (day_record(naps=(), night=night(series=series)),)
    t = at(DAY, 7, 30)
    for strict, expected in ((True, (0.0,)), (False, (0.0, 30600.0))):
        before = night_before(days, t, strict=strict).night
        assert before is not None
        assert getattr(before.series, name).time_s == expected
        within = sleep_within(days, at(DAY, 0), t, strict=strict).episodes
        assert isinstance(within[0].episode, Night)
        assert getattr(within[0].episode.series, name).time_s == expected


def test_sleep_within_a_segment_under_a_microsecond_does_not_stop_the_union() -> None:
    """Un segment de moins d'une microseconde (de durée nulle en instants) en tête de
    l'union d'un groupe : sauté, la suite compte. Union : 23 h 01 → 7 h 30, 30 540 s,
    sous la somme (28 740 + 3 600)."""
    the_night = _full_night(
        light_s=28740.0,
        segments=(
            SleepSegment(0.0, 1e-7, SleepStage.LIGHT),
            SleepSegment(60.0, 28800.0, SleepStage.LIGHT),
        ),
    )
    the_nap = nap(start=at(DAY, 6, 30), end=at(DAY, 7, 30), sleep_s=3600.0)
    record = day_record(night=the_night, naps=(the_nap,))
    assert sleep_within((record,), at(DAY, 0), at(DAY, 8)).sleep_s == 30540.0


def test_sleep_within_a_third_overlapping_episode_joins_the_group() -> None:
    """Trois épisodes : la nuit, une sieste qui la recoupe, une sieste qui recoupe la
    première. Un seul groupe : l'union, 23 h → 8 h, 32 400 s (la somme, 33 300 s)."""
    naps = (
        nap(start=at(DAY, 6, 30), end=at(DAY, 7, 30), sleep_s=1800.0),
        nap(start=at(DAY, 7, 15), end=at(DAY, 8), sleep_s=2700.0),
    )
    record = day_record(night=_full_night(), naps=naps)
    result = sleep_within((record,), at(DAY, 0), at(DAY, 9))
    assert len(result.episodes) == 3
    assert result.sleep_s == 32400.0
    assert result.coverage_fraction == 1.0


def test_sleep_within_a_nap_starting_with_the_night_comes_after_it() -> None:
    """À début égal, la nuit passe avant la sieste dans les épisodes rendus."""
    the_nap = nap(start=at(PREVIOUS, 23), end=at(PREVIOUS, 23, 30), sleep_s=900.0)
    record = day_record(night=_full_night(), naps=(the_nap,))
    result = sleep_within((record,), at(PREVIOUS, 22), at(DAY, 8))
    assert [type(item.episode) for item in result.episodes] == [Night, Nap]
    assert result.episodes[1].episode == the_nap


def test_sleep_within_renders_its_bounds() -> None:
    start, end = at(DAY, 0), at(DAY, 8)
    for days in ((), (day_record(naps=()),)):
        result = sleep_within(days, start, end)
        assert (result.start, result.end) == (start, end)


def test_sleep_within_coverage_adds_the_window_and_unmeasured_of_each_night() -> None:
    """Deux nuits seules, de 8 h chacune et 30 min de non mesurable : couverture
    (57 600 − 3 600) / 57 600."""
    days = (day_record(naps=()), day_record(NEXT, naps=()))
    result = sleep_within(days, at(DAY, 0), at(NEXT, 8))
    assert result.sleep_s == 50400.0
    assert result.coverage_fraction == (57600.0 - 3600.0) / 57600.0


def test_sleep_within_coverage_adds_the_unmeasured_of_each_group() -> None:
    """Deux groupes (une nuit et une sieste de 6 h 45 à 7 h 15), chacun 29 700 s de
    fenêtres dont 1 800 s de segments non mesurables : (59 400 − 3 600) / 59 400."""
    days = tuple(
        day_record(day, naps=(nap(day, start=at(day, 6, 45), end=at(day, 7, 15)),))
        for day in (DAY, NEXT)
    )
    result = sleep_within(days, at(DAY, 0), at(NEXT, 8))
    assert result.coverage_fraction == (59400.0 - 3600.0) / 59400.0


def test_sleep_within_a_one_second_nap_is_covered() -> None:
    the_nap = nap(start=at(DAY, 14), end=at(DAY, 14, 0, 1), sleep_s=1.0)
    result = sleep_within((_quiet(naps=(the_nap,)),), at(DAY, 0), at(DAY, 20))
    assert (result.sleep_s, result.coverage_fraction) == (1.0, 1.0)


def test_c2_the_union_of_a_group_counts_the_rem_segments() -> None:
    """Une nuit de 23 h à 7 h, léger jusqu'à 6 h puis paradoxal, et une sieste de 6 h 30
    à 8 h : l'union, 23 h → 8 h, 32 400 s (sans le paradoxal : 30 600 s)."""
    the_night = _full_night(
        light_s=25200.0,
        rem_s=3600.0,
        segments=(
            SleepSegment(0.0, 25200.0, SleepStage.LIGHT),
            SleepSegment(25200.0, 28800.0, SleepStage.REM),
        ),
    )
    the_nap = nap(start=at(DAY, 6, 30), end=at(DAY, 8), sleep_s=5400.0)
    record = day_record(night=the_night, naps=(the_nap,))
    assert sleep_within((record,), at(DAY, 0), at(DAY, 9)).sleep_s == 32400.0


def test_c3_sleep_within_sorts_its_episodes_by_instant() -> None:
    """Deux siestes : 14 h 30 à +02:00 (12 h 30 UTC) puis 14 h à +01:00 (13 h UTC) ;
    rendues dans l'ordre des instants, pas des heures murales."""
    first = nap(start=at(DAY, 14, 30, offset=PLUS2), end=at(DAY, 14, 45, offset=PLUS2))
    second = nap(start=at(DAY, 14), end=at(DAY, 14, 15))
    record = _quiet(naps=(first, second))
    result = sleep_within((record,), at(DAY, 0), at(DAY, 20))
    assert [item.episode for item in result.episodes] == [first, second]


def test_c7_sleep_within_sorts_the_episodes_of_all_days_by_start() -> None:
    """Une sieste du 10 de 23 h à 23 h 30 ; la nuit du 11, commencée le 10 à 22 h 30 :
    nuit, nuit, sieste."""
    late_nap = nap(start=at(DAY, 23), end=at(DAY, 23, 30))
    days = (
        day_record(naps=(late_nap,)),
        day_record(NEXT, naps=(), night=night(NEXT, start=at(DAY, 22, 30))),
    )
    result = sleep_within(days, at(DAY, 0), at(NEXT, 8))
    assert [(item.day, type(item.episode)) for item in result.episodes] == [
        (DAY, Night),
        (NEXT, Night),
        (DAY, Nap),
    ]


# --- body_battery_at, la série fusionnée par bissection


def test_body_battery_at_an_earlier_point_of_an_older_day_does_not_win() -> None:
    """Le point de la nuit du 11 (6 h le 11), puis le point du jour du 10 (22 h le 10,
    hors de toute nuit) : le dernier est celui de la nuit."""
    days = (
        _quiet(series=_bb_day(DAY, (79200.0,), (60,))),
        _quiet(NEXT, night=_full_night(NEXT, series=_bb_night((25200.0,), (70,)))),
    )
    reading = body_battery_at(days, at(NEXT, 8))
    assert (reading.point_instant, reading.level, reading.from_night, reading.day) == (
        at(NEXT, 6),
        70,
        True,
        NEXT,
    )


def test_body_battery_at_reads_past_a_night_without_series() -> None:
    days = (
        _quiet(night=_full_night()),
        _quiet(NEXT, night=_full_night(NEXT, series=_bb_night((3600.0,), (55,)))),
    )
    reading = body_battery_at(days, at(NEXT, 8))
    assert (reading.point_instant, reading.level, reading.day, reading.source) == (
        midnight(NEXT),
        55,
        NEXT,
        SRC,
    )
    assert reading.age_s == 8 * H


def test_body_battery_at_reads_past_a_day_without_series_or_window() -> None:
    for first in (_quiet(), empty_day()):
        days = (first, _quiet(NEXT, series=_bb_day(NEXT, (3600.0,), (52,))))
        reading = body_battery_at(days, at(NEXT, 8))
        assert (reading.point_instant, reading.level, reading.day) == (
            at(NEXT, 1),
            52,
            NEXT,
        )


def test_body_battery_at_two_nights_at_the_same_instant_keep_the_oldest() -> None:
    """Deux nuits qui se recouvrent, chacune un point de Body Battery à 6 h 30 le 10 :
    le point de la nuit du jour le plus ancien."""
    first = _quiet(night=_full_night(series=_bb_night((27000.0,), (30,))))
    second = _quiet(
        NEXT,
        night=_full_night(
            NEXT,
            start=at(DAY, 6),
            end=at(NEXT, 7),
            segments=(),
            series=_bb_night((1800.0,), (31,)),
        ),
    )
    reading = body_battery_at((first, second), at(NEXT, 8))
    assert (reading.point_instant, reading.level, reading.day) == (
        at(DAY, 6, 30),
        30,
        DAY,
    )


def test_body_battery_at_steps_back_over_a_night_to_the_day_point_before_it() -> None:
    """Une nuit de 13 h à 15 h, sans série ; les points du jour à 12 h et à 14 h : à
    16 h, celui de 14 h tombe dans la nuit, celui de 12 h est rendu."""
    record = _quiet(
        night=_full_night(start=at(DAY, 13), end=at(DAY, 15), segments=()),
        series=_bb_day(DAY, (43200.0, 50400.0), (50, 51)),
    )
    reading = body_battery_at((record,), at(DAY, 16))
    assert (reading.point_instant, reading.level, reading.from_night) == (
        at(DAY, 12),
        50,
        False,
    )
    assert reading.age_s == 4 * H


def test_body_battery_at_a_day_point_inside_a_night_inside_another() -> None:
    """Une nuit de 23 h à 10 h, une autre de 2 h à 4 h dans la première : un point du
    jour à 5 h est dans la fenêtre fusionnée, écarté ; aucun point."""
    outer = _quiet(
        night=_full_night(end=at(DAY, 10), segments=()),
        series=_bb_day(DAY, (18000.0,), (50,)),
    )
    inner = _quiet(
        NEXT, night=_full_night(NEXT, start=at(DAY, 2), end=at(DAY, 4), segments=())
    )
    reading = body_battery_at((outer, inner), at(DAY, 11))
    assert reading.absence is ViewAbsence.NO_POINT


@pytest.mark.parametrize("strict", [False, True])
def test_body_battery_at_a_single_night_point_at_the_start_of_its_night(
    strict: bool,
) -> None:
    record = _quiet(night=_full_night(series=_bb_night((0.0,), (33,))))
    reading = body_battery_at((record,), at(DAY, 8), strict=strict)
    assert (reading.point_instant, reading.level, reading.from_night) == (
        at(PREVIOUS, 23),
        33,
        True,
    )


def test_body_battery_at_a_single_day_point() -> None:
    record = _quiet(series=_bb_day(DAY, (3600.0,), (44,)))
    reading = body_battery_at((record,), at(DAY, 2))
    assert (reading.point_instant, reading.level) == (at(DAY, 1), 44)


def test_body_battery_at_two_points_within_a_microsecond_keep_the_first() -> None:
    """Deux points d'une série à moins d'une microseconde : le même instant ; le premier
    de la série est rendu, de la nuit comme du jour."""
    night_record = _quiet(
        night=_full_night(series=_bb_night((3600.0, 3600.0000001), (30, 31)))
    )
    reading = body_battery_at((night_record,), at(DAY, 8))
    assert (reading.point_instant, reading.level) == (midnight(DAY), 30)
    day_rec = _quiet(series=_bb_day(DAY, (43200.0, 43200.0000001), (50, 51)))
    reading = body_battery_at((day_rec,), at(DAY, 13))
    assert (reading.point_instant, reading.level) == (at(DAY, 12), 50)


@pytest.mark.parametrize(
    ("instant", "strict", "level"),
    [
        (at(DAY, 1), False, 52),
        (at(DAY, 1), True, 51),
        (at(DAY, 1) + timedelta(microseconds=1), True, 52),
        (at(DAY, 0, 30), False, 51),
        (at(DAY, 0, 30), True, 50),
    ],
)
def test_body_battery_at_a_day_point_at_the_instant(
    instant: datetime, strict: bool, level: int
) -> None:
    """Des points du jour à 0 h, 0 h 30 et 1 h : un point à l'instant même est rendu
    sans ``strict``, celui d'avant avec."""
    record = _quiet(series=_bb_day(DAY, (0.0, 1800.0, 3600.0), (50, 51, 52)))
    assert body_battery_at((record,), instant, strict=strict).level == level


def test_body_battery_at_strict_on_a_night_ending_at_the_instant() -> None:
    """Une nuit finie à 7 h, un point du jour à 6 h dans sa fenêtre : à 7 h, la nuit
    compte (le point du jour cède) ; avec ``strict``, elle est en cours, le point du
    jour revient."""
    record = _quiet(
        night=_full_night(series=_bb_night((27000.0,), (30,))),
        series=_bb_day(DAY, (21600.0,), (60,)),
    )
    assert body_battery_at((record,), at(DAY, 7)).level == 30
    assert body_battery_at((record,), at(DAY, 7), strict=True).level == 60


# --- night_before, nights_after, training_status_at, readiness_at


def test_night_before_reads_past_a_day_without_night() -> None:
    result = night_before((_quiet(), day_record(NEXT)), at(NEXT, 8))
    assert (result.day, result.gap_s) == (NEXT, H)


def _two_offset_nights() -> tuple[DayRecord, DayRecord]:
    """La nuit du 10 finie à 7 h 30 à +02:00 (5 h 30 UTC), puis celle du 11 finie le 10
    à 7 h à +01:00 (6 h UTC) : la seconde est la dernière en instants, la première en
    heures murales."""
    return (
        day_record(night=night(end=at(DAY, 7, 30, offset=PLUS2))),
        day_record(NEXT, night=night(NEXT, start=at(DAY, 1), end=at(DAY, 7))),
    )


def test_c3_night_before_compares_instants_not_wall_clocks() -> None:
    """La dernière nuit est celle de la plus grande fin en instants ; l'écart se compte
    en instants (12 h à +02:00 − 6 h UTC : 4 h)."""
    result = night_before(_two_offset_nights(), at(DAY, 12, offset=PLUS2))
    assert (result.day, result.gap_s) == (NEXT, 4 * H)


def test_c3_nights_after_sorts_by_instant() -> None:
    result = nights_after(_two_offset_nights(), at(DAY, 2), 2)
    assert [item.day for item in result] == [DAY, NEXT]


def test_c7_nights_after_equal_ends_keep_the_order_of_the_days() -> None:
    days = (
        day_record(night=night(end=at(DAY, 9))),
        day_record(NEXT, night=night(NEXT, start=at(DAY, 1), end=at(DAY, 9))),
    )
    assert [item.day for item in nights_after(days, at(DAY, 2), 2)] == [DAY, NEXT]


def test_training_status_at_reads_past_a_block_without_proper_instant() -> None:
    blocks = TrainingStatusHistory(
        (status_block(DAY, timestamp=None, proper_instant=None), status_block(NEXT)),
        (),
        (),
        (),
        (),
    )
    result = training_status_at(blocks, TrainingStatusKind.STATUS, at(NEXT, 20))
    assert result.block == status_block(NEXT)


def test_c3_training_status_at_compares_instants_not_wall_clocks() -> None:
    """Deux blocs : 7 h 30 à +02:00 (5 h 30 UTC), puis, daté du lendemain, 7 h à
    +01:00 (6 h UTC) ; le dernier en instants est rendu, son âge en instants (12 h à
    +02:00 : 4 h)."""
    first = at(DAY, 7, 30, offset=PLUS2)
    blocks = TrainingStatusHistory(
        (
            status_block(DAY, timestamp=first, proper_instant=first),
            status_block(NEXT, timestamp=at(DAY, 7), proper_instant=at(DAY, 7)),
        ),
        (),
        (),
        (),
        (),
    )
    result = training_status_at(
        blocks, TrainingStatusKind.STATUS, at(DAY, 12, offset=PLUS2)
    )
    assert result.block is not None
    assert result.block.proper_instant == at(DAY, 7)
    assert result.age_s == 4 * H


def test_c3_readiness_at_compares_instants_not_wall_clocks() -> None:
    early = readiness(instant=at(DAY, 7, 30, offset=PLUS2))
    late = readiness(instant=at(DAY, 7))
    result = readiness_at((_quiet(readiness=(early, late)),), at(DAY, 12, offset=PLUS2))
    assert result.entry == late
    assert result.age_s == 4 * H


# --- night_assessment


def test_night_assessment_renders_its_day() -> None:
    for days in ((), (day_record(),)):
        assert _assess(days).day == DAY


def test_usual_midpoint_at_six_in_the_morning() -> None:
    """Des milieux à 6 h : le cosinus de la résultante est nul, son sinus non ; le
    milieu habituel existe."""
    result = _assess(_nights([(2, 10), (2, 10)]))
    assert result.usual_midpoint_s == pytest.approx(6 * H, abs=1e-6)


def test_usual_midpoint_the_guard_is_relative_to_the_number_of_nights() -> None:
    """100 nuits aux milieux équilibrés (0 h, 6 h, 12 h, 18 h), l'une finie 2 µs plus
    tard (son milieu 1 µs plus tard) : une résultante d'environ 7,3e-11, rapportée aux
    100 nuits, sous la garde (``dispersed_midpoints``) ; multipliée, elle la
    passerait."""
    hours = [(20, 4), (2, 10), (8, 16), (14, 22)] * 25
    days = list(_nights(hours))
    shifted = days[0].night
    assert shifted is not None
    days[0] = dataclasses.replace(
        days[0],
        night=dataclasses.replace(shifted, end=shifted.end + timedelta(microseconds=2)),
    )
    result = _assess(tuple(days), usual_window_days=100)
    assert result.usual_nights == 100
    assert result.usual_midpoint_s is None
    assert result.shifted_absence is ViewAbsence.DISPERSED_MIDPOINTS


def test_c1_shifted_reads_the_circular_distance_across_midnight() -> None:
    """Le milieu habituel à 23 h (nuits de 19 h à 3 h), celui de la nuit du jour à 1 h
    (22 h → 4 h) : l'écart circulaire, 2 h, pas 22 h ; ``shift_s`` = 2 h 30 : pas
    décalée."""
    days = (
        *_nights([(19, 3), (19, 3)])[:-1],
        day_record(naps=(), night=night(start=at(PREVIOUS, 22), end=at(DAY, 4))),
    )
    result = _assess(days, shift_s=2.5 * H)
    assert result.midpoint_s == H
    assert result.usual_midpoint_s == pytest.approx(23 * H, abs=1e-6)
    assert result.midpoint_distance_s == pytest.approx(2 * H, abs=1e-6)
    assert (result.shifted, result.shifted_absence) == (False, None)


def test_c7_a_night_at_the_short_sleep_threshold_enters_the_usual_midpoint() -> None:
    """La veille, une nuit de 4 h de sommeil mesuré, ``short_sleep_s`` = 4 h :
    admise."""
    result = _assess(_nights([(23, 3)]), short_sleep_s=4 * H)
    assert result.usual_nights == 1


def test_c3_the_unmeasured_fraction_reads_the_real_duration_of_the_night() -> None:
    """Une nuit de 23 h (+01:00) à 7 h (+02:00) : 7 h, pas 8 ; 2 700 s de non
    mesurable, 0,1071 > 0,1 : ``partial``."""
    the_night = night(end=at(DAY, 7, offset=PLUS2), unmeasurable_s=2700.0)
    result = _assess((day_record(night=the_night),))
    assert result.unmeasured_fraction == 2700.0 / 25200.0
    assert result.state is NightState.PARTIAL


# --- resting_hr_at


def test_resting_hr_at_reads_past_a_day_without_window_or_value() -> None:
    for first in (empty_day(), day_record(resting_hr=None)):
        result = resting_hr_at((first, day_record(NEXT)), midnight(D2), min_sleep_s=0.0)
        assert (result.day, result.resting_hr_bpm, result.status) == (
            NEXT,
            48.0,
            RestingHrStatus.VALID,
        )


def test_resting_hr_at_strict_on_a_night_ending_at_the_instant() -> None:
    """Une nuit finie le 11 à 1 h, après la fin de la fenêtre du 10 : prise à 1 h, la
    nuit compte ; avec ``strict``, non (``no_night``)."""
    record = day_record(night=night(start=at(DAY, 22), end=at(NEXT, 1)))
    plain = resting_hr_at((record,), at(NEXT, 1), min_sleep_s=0.0)
    strict = resting_hr_at((record,), at(NEXT, 1), min_sleep_s=0.0, strict=True)
    assert plain.status is RestingHrStatus.VALID
    assert strict.status is RestingHrStatus.NO_NIGHT
    assert strict.resting_hr_bpm == 48.0


def test_resting_hr_at_a_later_day_with_an_earlier_end_does_not_win() -> None:
    """Le 10, ses données jusqu'au 12 à 6 h ; le 11, jusqu'au 12 à 0 h : le 10."""
    days = (day_record(data_end=at(D2, 6)), day_record(NEXT))
    result = resting_hr_at(days, at(D2, 12), min_sleep_s=0.0)
    assert (result.day, result.proper_instant) == (DAY, at(D2, 6))


def test_c7_resting_hr_at_equal_ends_take_the_last_day() -> None:
    days = (day_record(data_end=midnight(D2)), day_record(NEXT))
    result = resting_hr_at(days, at(D2, 12), min_sleep_s=0.0)
    assert result.day == NEXT


def test_c3_resting_hr_at_compares_instants_not_wall_clocks() -> None:
    """Le 10, sa fenêtre à +02:00, ses données jusqu'au 12 à 0 h 30 (22 h 30 UTC le
    11) ; le 11, à +01:00, jusqu'au 12 à 0 h (23 h UTC) : le 11 ; âge à 2 h à +02:00 :
    1 h."""
    first = day_record(
        window_start=midnight(DAY, PLUS2), data_end=at(D2, 0, 30, offset=PLUS2)
    )
    days = (first, day_record(NEXT))
    result = resting_hr_at(days, at(D2, 2, offset=PLUS2), min_sleep_s=0.0)
    assert (result.day, result.age_s) == (NEXT, H)


# --- readiness_on_waking


def test_readiness_on_waking_renders_its_day_and_the_end_of_the_night() -> None:
    entry = readiness()
    assert readiness_on_waking((), DAY, tolerance_s=0.0).day == DAY
    found = readiness_on_waking(
        (day_record(naps=(), readiness=(entry,)),), DAY, tolerance_s=0.0
    )
    assert (found.day, found.entry, found.night_end, found.absence) == (
        DAY,
        entry,
        at(DAY, 7),
        None,
    )
    late = readiness(instant=at(DAY, 6), input_context="AFTER_POST_EXERCISE_RESET")
    missing = readiness_on_waking(
        (day_record(naps=(), readiness=(late,)),), DAY, tolerance_s=0.0
    )
    assert (missing.day, missing.entry, missing.night_end, missing.absence) == (
        DAY,
        None,
        at(DAY, 7),
        ViewAbsence.NO_ENTRY_AFTER_NIGHT,
    )


def test_c7_a_nap_starting_at_the_end_of_the_night_bounds_the_entry() -> None:
    """La nuit finie à 7 h, une sieste de 7 h à 7 h 30, l'entrée « réveil » à 7 h 05 :
    la sieste est la suivante, l'entrée n'est pas avant elle."""
    record = day_record(
        naps=(nap(start=at(DAY, 7), end=at(DAY, 7, 30)),), readiness=(readiness(),)
    )
    result = readiness_on_waking((record,), DAY, tolerance_s=600.0)
    assert (result.entry, result.absence) == (None, ViewAbsence.NO_ENTRY_AFTER_NIGHT)


def test_readiness_on_waking_reads_past_an_entry_too_early() -> None:
    early = readiness(instant=at(DAY, 5))
    entry = readiness()
    record = day_record(naps=(), readiness=(early, entry))
    assert readiness_on_waking((record,), DAY, tolerance_s=600.0).entry == entry


def test_c3_readiness_on_waking_compares_instants_not_wall_clocks() -> None:
    """La nuit finie à 7 h à +02:00 (5 h UTC), l'entrée à 6 h 55 à +01:00 (5 h 55
    UTC), après la fin : retenue sans tolérance (en heures murales, 5 min avant)."""
    entry = readiness(instant=at(DAY, 6, 55))
    record = day_record(
        night=night(end=at(DAY, 7, offset=PLUS2)), naps=(), readiness=(entry,)
    )
    assert readiness_on_waking((record,), DAY, tolerance_s=0.0).entry == entry


# --- series_between


def test_series_between_reads_past_a_day_without_its_night_window_or_series() -> None:
    hr = _hr_day(NEXT, midnight(NEXT), (0.0,), (50.0,))
    for first in (_quiet(), empty_day()):
        window = _between(
            (first, hr), SeriesKind.DAY_HEART_RATE, midnight(NEXT), at(NEXT, 1)
        )
        assert [(p.instant, p.value) for p in window.points] == [(midnight(NEXT), 50.0)]
    window = _between(
        (_quiet(), day_record(NEXT)),
        SeriesKind.NIGHT_HEART_RATE,
        at(DAY, 20),
        at(NEXT, 8),
    )
    assert [p.instant for p in window.points] == [at(DAY, 23), at(DAY, 23, 2)]


def test_series_between_reads_past_a_point_before_start() -> None:
    record = _hr_day(DAY, midnight(DAY), (0.0, 60.0, 120.0), (50.0, 51.0, 52.0))
    window = _between(
        (record,), SeriesKind.DAY_HEART_RATE, at(DAY, 0, 1), at(DAY, 0, 2)
    )
    assert [p.value for p in window.points] == [51.0, 52.0]


def test_series_between_counts_every_duplicate() -> None:
    """Le 10 porte deux points le 11 à 0 h et 0 h 01, que le 11 porte aussi : deux
    doublons, les points du 10 gardés."""
    first = _hr_day(DAY, midnight(DAY), (86400.0, 86460.0), (50.0, 51.0))
    second = _hr_day(NEXT, midnight(NEXT), (0.0, 60.0), (60.0, 61.0))
    window = _between(
        (first, second), SeriesKind.DAY_HEART_RATE, midnight(NEXT), at(NEXT, 0, 2)
    )
    assert window.duplicates == 2
    assert [(p.value, p.day) for p in window.points] == [(50.0, DAY), (51.0, DAY)]


def test_series_between_renders_its_kind_bounds_and_duplicates() -> None:
    """Chaque issue rend la sorte, les deux bornes et les doublons : aucun point ; sous
    la couverture ; les points."""
    first = _hr_day(DAY, midnight(DAY), (86400.0,), (50.0,))
    second = _hr_day(NEXT, midnight(NEXT), (0.0,), (60.0,))
    start, end = midnight(NEXT), at(NEXT, 1)
    kind = SeriesKind.DAY_HEART_RATE
    for minimum, absence in ((0.5, ViewAbsence.BELOW_COVERAGE), (0.0, None)):
        window = _between(
            (first, second), kind, start, end, min_coverage_fraction=minimum
        )
        assert (window.kind, window.start, window.end, window.duplicates) == (
            kind,
            start,
            end,
            1,
        )
        assert window.absence is absence
    empty = _between((first, second), kind, at(NEXT, 2), at(NEXT, 3))
    assert (empty.kind, empty.start, empty.end, empty.duplicates, empty.absence) == (
        kind,
        at(NEXT, 2),
        at(NEXT, 3),
        0,
        ViewAbsence.NO_POINT,
    )


def test_c5_a_point_before_start_does_not_count_in_the_coverage() -> None:
    """Un point la veille à 23 h 59 min 30 s, un à 0 h 01 ; [0 h, 0 h 02], pas de 60 s :
    couverture 0,5 (le point d'avant ``start`` n'y entre pas) ; minimum 0,6 :
    ``below_coverage``."""
    days = (
        _hr_day(PREVIOUS, midnight(PREVIOUS), (86370.0,), (50.0,)),
        _hr_day(DAY, midnight(DAY), (60.0,), (51.0,)),
    )
    kind = SeriesKind.DAY_HEART_RATE
    window = _between(days, kind, midnight(DAY), at(DAY, 0, 2))
    assert window.coverage_fraction == 0.5
    assert [p.value for p in window.points] == [51.0]
    low = _between(days, kind, midnight(DAY), at(DAY, 0, 2), min_coverage_fraction=0.6)
    assert (low.points, low.coverage_fraction, low.absence) == (
        (),
        0.5,
        ViewAbsence.BELOW_COVERAGE,
    )


# --- la 25ᵉ heure d'un dimanche d'automne


def _autumn_record(series: DaySeries) -> DayRecord:
    """Le dimanche du passage à l'heure d'hiver, complet sur ses 25 h."""
    start = midnight(AUTUMN_DAY, PLUS2)
    return _quiet(
        AUTUMN_DAY,
        window_start=start,
        data_end=start + timedelta(hours=25),
        series=series,
    )


def test_c3_series_between_keeps_a_point_of_the_25th_hour() -> None:
    """Un point à début + 24 h 30 (0 h 30 à +02:00 le lundi, dans la fenêtre de 25 h du
    dimanche) est rendu."""
    series = DaySeries(
        HeartRateSeries((0.0, 88200.0), (50.0, 51.0), SRC), None, None, None, None
    )
    record = _autumn_record(series)
    start = midnight(AUTUMN_DAY, PLUS2)
    window = _between(
        (record,),
        SeriesKind.DAY_HEART_RATE,
        start + timedelta(hours=24),
        start + timedelta(hours=25),
    )
    assert [(p.instant, p.value) for p in window.points] == [
        (start + timedelta(hours=24, minutes=30), 51.0)
    ]


def test_c3_body_battery_at_keeps_a_point_of_the_25th_hour() -> None:
    record = _autumn_record(_bb_day(AUTUMN_DAY, (0.0, 88200.0), (40, 41)))
    start = midnight(AUTUMN_DAY, PLUS2)
    reading = body_battery_at((record,), start + timedelta(hours=25))
    assert (reading.level, reading.age_s) == (41, 1800.0)
