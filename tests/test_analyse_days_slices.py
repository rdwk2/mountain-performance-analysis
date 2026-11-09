"""La tranche bornée (AN2-2) : chaque vue rend sur sa tranche ce qu'elle rend sur toute
la suite. Deux suites inventées de l'an 2000, qui passent les changements d'heure."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest

from fixtures.day_table import (
    PLUS1,
    PLUS2,
    body_battery,
    definition,
    index_entry,
    journal_of,
    night_with,
    table,
)
from fixtures.days import day_record, nap, readiness
from mountain_perf.analyse import days as days_module
from mountain_perf.analyse.days import DayDefinition, DaySlices, day_slices
from mountain_perf.analyse.normals import integer_parameter
from mountain_perf.ingest.day_views import (
    night_assessment,
    readiness_on_waking,
    resting_hr_on,
    series_between,
)
from mountain_perf.schemas import (
    DayRecord,
    JournalEventType,
    SeriesKind,
)
from mountain_perf.schemas.processed import DayRowState

DAY = timedelta(days=1)


def _span(first: date, last: date) -> list[date]:
    count = (last - first).days + 1
    return [first + timedelta(days=i) for i in range(count)]


def _spring_offset(wall: datetime) -> timezone:
    return PLUS1 if wall < datetime(2000, 3, 26, 2) else PLUS2


def _autumn_offset(wall: datetime) -> timezone:
    return PLUS2 if wall < datetime(2000, 10, 29, 3) else PLUS1


def _local(wall: datetime, offset: Any) -> datetime:
    return wall.replace(tzinfo=offset(wall))


def _document(day: date, offset: Any, **night_changes: Any) -> DayRecord:
    midnight = datetime(day.year, day.month, day.day)
    start = _local(midnight, offset)
    following = _local(midnight + DAY, offset)
    night_start = _local(midnight - timedelta(hours=1), offset)
    night_end = _local(midnight + timedelta(hours=7), offset)
    length = (night_end - night_start).total_seconds()
    times = [i * 180.0 for i in range(int(length // 180))]
    series = night_changes.pop("series", body_battery(day, times, [50] * len(times)))
    begin = night_changes.pop("start", night_start)
    end = night_changes.pop("end", night_end)
    return day_record(
        day,
        window_start=start,
        data_end=max(following, start + DAY),
        night=night_with(day, series, start=begin, end=end),
        naps=(
            nap(
                day,
                start=_local(midnight + timedelta(hours=14), offset),
                end=_local(midnight + timedelta(hours=15), offset),
            ),
        ),
        readiness=(readiness(day, instant=end + timedelta(minutes=5)),),
    )


def spring() -> tuple[DayRecord, ...]:
    documents: list[DayRecord] = []
    skipped = {date(2000, 3, 10), date(2000, 3, 11), date(2000, 4, 2)}
    for day in _span(date(2000, 2, 20), date(2000, 4, 9)):
        if day in skipped:
            continue
        if day == date(2000, 3, 20):
            documents.append(_overflowing(day))
        elif day == date(2000, 3, 16):
            documents.append(_early(day))
        else:
            documents.append(_document(day, _spring_offset))
    return tuple(documents)


def _overflowing(day: date) -> DayRecord:
    """La nuit du 20 mars porte aussi des points aux instants de la nuit du 21."""
    midnight = datetime(day.year, day.month, day.day)
    start = _local(midnight - timedelta(hours=1), _spring_offset)
    end = _local(midnight + timedelta(hours=7), _spring_offset)
    length = (end - start).total_seconds()
    times = [i * 180.0 for i in range(int(length // 180))]
    levels = [50] * len(times)
    times += [86400.0 + i * 180.0 for i in range(10)]
    levels += [100] * 10
    return _document(day, _spring_offset, series=body_battery(day, times, levels))


def _early(day: date) -> DayRecord:
    """Le document du 16 mars : une nuit précoce, dans celle du 15, finie avant elle."""
    start = datetime(2000, 3, 15, 1, 1, 30, tzinfo=PLUS1)
    end = datetime(2000, 3, 15, 3, 1, 30, tzinfo=PLUS1)
    times = [i * 180.0 for i in range(40)]
    return _document(
        day,
        _spring_offset,
        series=body_battery(day, times, [100] * 40),
        start=start,
        end=end,
    )


def autumn() -> tuple[DayRecord, ...]:
    return tuple(
        _document(day, _autumn_offset)
        for day in _span(date(2000, 10, 20), date(2000, 11, 3))
    )


DEFINITIONS = {
    "défaut": definition(),
    "fenêtre 3": definition({"usual_window_days": 3, "usual_min_nights": 2}),
    "fenêtre 40": definition({"usual_window_days": 40, "usual_min_nights": 30}),
    "couverture 0": definition({"min_coverage_fraction": 0.0}),
}
SUITES = {"printemps": spring, "automne": autumn}


def _assessment(
    documents: Sequence[DayRecord], day: date, chosen: DayDefinition
) -> Any:
    v = chosen.views
    return night_assessment(
        documents,
        day,
        max_unmeasured_fraction=v["max_unmeasured_fraction"],
        short_sleep_s=v["short_sleep_s"],
        shift_s=v["shift_s"],
        usual_window_days=integer_parameter(v, "usual_window_days"),
        usual_min_nights=integer_parameter(v, "usual_min_nights"),
    )


def _series(
    documents: Sequence[DayRecord], record: DayRecord, chosen: DayDefinition
) -> Any:
    assert record.night is not None
    return series_between(
        documents,
        SeriesKind.NIGHT_BODY_BATTERY,
        record.night.start,
        record.night.end,
        step_s=chosen.views["night_body_battery_step_s"],
        min_coverage_fraction=chosen.views["min_coverage_fraction"],
    )


def _calendar(documents: tuple[DayRecord, ...]) -> list[date]:
    return _span(documents[0].day, documents[-1].day)


@pytest.mark.parametrize("suite", SUITES.values(), ids=SUITES.keys())
@pytest.mark.parametrize("chosen", DEFINITIONS.values(), ids=DEFINITIONS.keys())
def test_each_view_gives_on_its_slice_what_it_gives_on_the_whole(
    suite: Any, chosen: DayDefinition
) -> None:
    documents = suite()
    keys = tuple(d.day for d in documents)
    records = dict(zip(keys, documents, strict=True))
    window = integer_parameter(chosen.views, "usual_window_days")
    v = chosen.views
    for day in _calendar(documents):
        slices = day_slices(documents, keys, day, window)
        assert _assessment(slices.night, day, chosen) == _assessment(
            documents, day, chosen
        )
        hr = v["resting_hr_min_sleep_s"]
        assert resting_hr_on(slices.own, day, min_sleep_s=hr) == resting_hr_on(
            documents, day, min_sleep_s=hr
        )
        tolerance = v["readiness_tolerance_s"]
        assert readiness_on_waking(
            slices.own, day, tolerance_s=tolerance
        ) == readiness_on_waking(documents, day, tolerance_s=tolerance)
        record = records.get(day)
        if record is not None and record.night is not None:
            assert _series(slices.series, record, chosen) == _series(
                documents, record, chosen
            )


@pytest.mark.parametrize("suite", SUITES.values(), ids=SUITES.keys())
@pytest.mark.parametrize("chosen", DEFINITIONS.values(), ids=DEFINITIONS.keys())
def test_the_table_is_the_same_on_slices_and_on_the_whole(
    suite: Any, chosen: DayDefinition, monkeypatch: pytest.MonkeyPatch
) -> None:
    documents = suite()
    fourth, sixth, seventh = documents[3], documents[5], documents[6]
    assert fourth.window_start is not None
    entries = [index_entry("a", fourth.window_start + timedelta(hours=9))]
    journal = journal_of((sixth.day, seventh.day, JournalEventType.ILLNESS))
    expected = table(documents, entries=entries, journal=journal, day_definition=chosen)

    def whole(
        days: tuple[DayRecord, ...], keys: Any, day: date, window: int
    ) -> DaySlices:
        return DaySlices(days, days, days)

    monkeypatch.setattr(days_module, "day_slices", whole)
    same = table(documents, entries=entries, journal=journal, day_definition=chosen)
    assert same == expected


def _shrunk(slice_: tuple[DayRecord, ...], *excluded: date) -> tuple[DayRecord, ...]:
    return tuple(d for d in slice_ if d.day not in excluded)


def test_the_night_slice_cut_by_one_day_changes_a_view() -> None:
    documents = spring()
    keys = tuple(d.day for d in documents)
    chosen = definition()
    differs = False
    for day in _calendar(documents):
        night = day_slices(documents, keys, day, 28).night
        low = day - timedelta(days=28)
        if _assessment(_shrunk(night, low), day, chosen) != _assessment(
            documents, day, chosen
        ):
            differs = True
    assert differs


@pytest.mark.parametrize("side", [-1, 1], ids=["sans la veille", "sans le lendemain"])
def test_the_series_slice_without_a_neighbour_changes_the_series(side: int) -> None:
    documents = spring()
    keys = tuple(d.day for d in documents)
    chosen = definition()
    differs = False
    for record in documents:
        if record.night is None:
            continue
        series = day_slices(documents, keys, record.day, 28).series
        cut = _shrunk(series, record.day + timedelta(days=side))
        if _series(cut, record, chosen) != _series(documents, record, chosen):
            differs = True
    assert differs


def test_what_the_whole_suite_says_of_the_two_edges() -> None:
    result = table(spring())
    rows = {row.day: row for row in result.rows}
    assert rows[date(2000, 3, 21)].night_body_battery_ceiling is True
    assert rows[date(2000, 3, 22)].night_body_battery_ceiling is False
    assert rows[date(2000, 3, 15)].night_body_battery_ceiling is True
    for day in (date(2000, 3, 10), date(2000, 3, 11), date(2000, 4, 2)):
        assert rows[day].state is DayRowState.ABSENT


def test_the_bounds_of_the_slices() -> None:
    documents = spring()
    keys = tuple(d.day for d in documents)
    day = date(2000, 3, 30)
    slices = day_slices(documents, keys, day, 28)
    assert slices.night[0].day == date(2000, 3, 2)
    assert slices.night[-1].day == day
    assert [d.day for d in slices.night] == [
        k for k in keys if date(2000, 3, 2) <= k <= day
    ]
    assert [d.day for d in slices.own] == [day]
    assert [d.day for d in slices.series] == [
        date(2000, 3, 29),
        day,
        date(2000, 3, 31),
    ]
    gap = day_slices(documents, keys, date(2000, 3, 10), 28)
    assert gap.own == ()
    assert [d.day for d in gap.series] == [date(2000, 3, 9)]


def test_the_bounds_do_not_leave_the_calendar() -> None:
    one, two = day_record(date(2000, 1, 1)), day_record(date(2000, 1, 2))
    keys = (date.max - timedelta(days=1), date.max)
    slices = day_slices((one, two), keys, date.max, 28)
    assert slices.night == (one, two)
    assert slices.series == (one, two)
    assert slices.own == (two,)
    alone = day_slices((one,), (date.min,), date.min, 28)
    assert alone == DaySlices((one,), (one,), (one,))
