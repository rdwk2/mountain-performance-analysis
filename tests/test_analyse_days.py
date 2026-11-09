"""La table ``jours`` (``mountain_perf.analyse.days``, AN2-2) : le calendrier, chaque
groupe de colonnes, les validités, Training Status, le journal, l'activité du jour, le
résumé, les paramètres. Des documents inventés à partir du 1er janvier 2000."""

from __future__ import annotations

import dataclasses
from datetime import date, datetime, timedelta
from typing import Any

import pytest

from fixtures.day_table import (
    PLUS1,
    PLUS2,
    body_battery,
    complete_days,
    days_with,
    definition,
    dense,
    index_entry,
    index_of,
    jan,
    journal_of,
    night_with,
    row_of,
    table,
)
from fixtures.days import (
    EMPTY_HISTORY,
    EMPTY_NIGHT_SERIES,
    activity_totals,
    altitude_block,
    at,
    day_record,
    empty_day,
    heat_block,
    load_balance_block,
    nap,
    night,
    readiness,
    resting_hr,
    status_block,
    stress_summary,
    truncated_day,
    versions,
    vo2_max_block,
)
from mountain_perf.analyse.days import (
    BODY_BATTERY_CEILING,
    DAY_VIEW_INTEGER_PARAMETERS,
    DAY_VIEW_PARAMETER_SPECS,
    DEFAULT_DAY_DEFINITION,
    DayDefinition,
    DaySummary,
    activity_columns,
    day_rows,
)
from mountain_perf.analyse.journal import Journal
from mountain_perf.analyse.normals import NORMAL_PARAMETER_SPECS
from mountain_perf.ingest.families import BODY_BATTERY_LEVEL_RANGE
from mountain_perf.schemas import (
    ContractError,
    DayState,
    JournalEventType,
    NightState,
    ParameterSet,
    RestingHrStatus,
    TrainingStatusHistory,
    ViewAbsence,
)
from mountain_perf.schemas.processed import AdmissionRefusal, DayRow, DayRowState

D1 = jan(1)
ILLNESS, RACE = JournalEventType.ILLNESS, JournalEventType.RACE
TRAVEL, OTHER = JournalEventType.TRAVEL, JournalEventType.OTHER


def history(**suites: Any) -> TrainingStatusHistory:
    return TrainingStatusHistory(
        suites.get("statuses", ()),
        suites.get("load_balances", ()),
        suites.get("vo2_max", ()),
        suites.get("heat_acclimation", ()),
        suites.get("altitude_acclimation", ()),
    )


def only(*days: Any, **kwargs: Any) -> DayRow:
    """La ligne unique de la table de ces documents."""
    (row,) = table(days, **kwargs).rows
    return row


def nine(day: date, ref: str = "x", **changes: Any) -> Any:
    return index_entry(ref, at(day, 9), **changes)


# --- le calendrier -------------------------------------------------------------------


def test_one_row_per_day_bounds_included_sorted() -> None:
    result = table(complete_days(6, skip=(1, 3, 4)))
    assert [row.day for row in result.rows] == [jan(d) for d in range(1, 7)]
    c, a = DayRowState.COMPLETE, DayRowState.ABSENT
    assert [row.state for row in result.rows] == [c, a, c, a, a, c]
    (single,) = table(complete_days(1)).rows
    assert (single.day, single.state) == (D1, c)


def test_without_a_document_no_row() -> None:
    result = table((), history(statuses=(status_block(D1),)), [nine(D1)])
    assert result.rows == ()
    assert result.summary == DaySummary(1, 0, 1, 0, 0, 0)


@pytest.mark.parametrize(
    "days",
    [
        (day_record(jan(2)), day_record(D1)),
        (day_record(D1), day_record(D1)),
    ],
    ids=["désordre", "doublon"],
)
def test_the_documents_are_sorted_without_duplicate(days: Any) -> None:
    with pytest.raises(ValueError, match="day_rows") as caught:
        day_rows(days, EMPTY_HISTORY, index_of(()), Journal((), None))
    assert str(caught.value) == (
        "day_rows : days doit être trié par jour, sans doublon : rangs 0 et 1."
    )


def test_an_absent_row_has_nothing_of_the_document() -> None:
    result = table(
        complete_days(3, skip=(1,)),
        history(vo2_max=(vo2_max_block(jan(2)),)),
        [nine(jan(2))],
        journal_of((jan(2), jan(2), TRAVEL)),
    )
    row = row_of(result, jan(2))
    assert row.state is DayRowState.ABSENT
    assert (row.window_start, row.data_end, row.reference_export) == (None, None, None)
    assert row.device_ranks == ()
    assert row.body_battery_series_versions == ()
    assert row.night_state is NightState.MISSING
    assert row.night_body_battery_absence is ViewAbsence.NO_NIGHT
    assert row.resting_hr_status is RestingHrStatus.ABSENT
    assert row.readiness_absence is ViewAbsence.NO_NIGHT
    assert row.readiness_entry_count == 0
    assert row.nap_count == 0
    assert row.steps is None
    assert row.ts_vo2_max_ml_kg_min == 56.0
    assert row.journal_types == (TRAVEL,)
    assert row.activity_count == 1
    assert result.summary.absent_days == 1


# --- les colonnes du jour et de la nuit ----------------------------------------------


def test_the_columns_of_the_day() -> None:
    row = only(day_record(D1, device_ranks=(2,), reference_export="garmin_b"))
    assert row.window_start == datetime(2000, 1, 1, tzinfo=PLUS1)
    assert row.data_end == datetime(2000, 1, 2, tzinfo=PLUS1)
    assert row.reference_export == "garmin_b"
    assert row.device_ranks == (2,)
    assert row.uncertain_device is False
    assert row.sleep_version == 2
    assert row.sleep_respiration_version == 200
    assert row.respiration_version == 200
    assert row.summary_respiration_version == 200
    assert row.summary_body_battery_version == 3
    assert row.body_battery_series_versions == (3,)


def test_two_ranks() -> None:
    row = only(day_record(D1, device_ranks=(1, 2)))
    assert row.device_ranks == (1, 2)
    assert row.uncertain_device is True


def test_an_empty_day() -> None:
    row = only(empty_day(D1))
    assert row.state is DayRowState.EMPTY
    assert (row.window_start, row.data_end) == (None, None)
    assert row.reference_export == "garmin_a"


@pytest.mark.parametrize(
    ("document", "state"),
    [
        (day_record(D1, state=DayState.NO_MEASUREMENT), DayRowState.NO_MEASUREMENT),
        (truncated_day(D1), DayRowState.TRUNCATED),
        (day_record(D1), DayRowState.COMPLETE),
    ],
)
def test_the_state_of_the_document_goes_to_the_row(
    document: Any, state: DayRowState
) -> None:
    assert only(document).state is state


def test_the_columns_of_the_night() -> None:
    row = only(day_record(D1, night=night(D1, body_battery_change=40)))
    assert row.night_start == at(date(1999, 12, 31), 23)
    assert row.night_end == at(D1, 7)
    assert row.night_state is NightState.COMPLETE
    assert row.night_short is False
    assert row.night_short_absence is None
    assert row.night_shifted is None
    assert row.night_shifted_absence is ViewAbsence.BELOW_USUAL_MINIMUM
    assert row.measured_sleep_s == 25200.0
    assert (row.deep_s, row.light_s, row.rem_s) == (3600.0, 16200.0, 5400.0)
    assert (row.awake_s, row.unmeasurable_s) == (1800.0, 1800.0)
    assert row.unmeasured_fraction == 1800 / 28800
    assert row.night_confirmation == "enhanced_confirmed_final"
    assert row.night_window_confirmed is True
    assert row.night_from_device is True
    assert row.night_rem_capable is True
    assert row.sleep_score == 80
    assert row.night_avg_stress == 12.0
    assert row.night_avg_heart_rate_bpm == 50.0
    assert row.night_body_battery_change == 40
    assert row.night_restless_moments == 20
    assert row.skin_temperature_deviation_c == -0.25


def test_a_day_without_a_night() -> None:
    row = only(day_record(D1, night=None))
    assert row.night_state is NightState.MISSING
    assert (row.night_start, row.night_end) == (None, None)
    assert row.night_short_absence is ViewAbsence.NO_NIGHT
    assert row.night_shifted_absence is ViewAbsence.NO_NIGHT
    assert row.night_body_battery_absence is ViewAbsence.NO_NIGHT
    assert row.measured_sleep_s is None
    assert row.naps_overlapping_night == 0


@pytest.mark.parametrize(
    ("changes", "state"),
    [
        ({"from_device": False}, NightState.DECLARED),
        ({"window_confirmed": False}, NightState.IN_PROGRESS),
        ({"unmeasurable_s": 0.21 * 28800}, NightState.PARTIAL),
        ({"unmeasurable_s": 0.20 * 28800}, NightState.COMPLETE),
        ({"unmeasurable_s": None}, NightState.PARTIAL),
    ],
)
def test_the_state_of_the_night_is_that_of_the_view(
    changes: dict[str, Any], state: NightState
) -> None:
    assert only(day_record(D1, night=night(D1, **changes))).night_state is state


def test_an_unmeasurable_time_longer_than_the_night() -> None:
    row = only(day_record(D1, night=night(D1, unmeasurable_s=2 * 28800.0)))
    assert row.unmeasured_fraction == 2.0
    assert row.night_state is NightState.PARTIAL


def _sleep(deep: float | None, light: float, rem: float) -> dict[str, Any]:
    return {"deep_s": deep, "light_s": light, "rem_s": rem}


def test_the_short_flag() -> None:
    short = only(day_record(D1, night=night(D1, **_sleep(3600, 7200, 3599))))
    assert short.night_short is True
    limit = only(day_record(D1, night=night(D1, **_sleep(3600, 7200, 3600))))
    assert limit.night_short is False
    unknown = only(day_record(D1, night=night(D1, **_sleep(None, 7200, 3600))))
    assert unknown.night_short is None
    assert unknown.night_short_absence is ViewAbsence.NO_MEASURED_SLEEP


def _shifted_table(hours: int, **changes: Any) -> Any:
    last = jan(20)
    moved = night(
        last,
        start=at(date(2000, 1, 19), 23) + timedelta(hours=hours),
        end=at(last, 7) + timedelta(hours=hours),
    )
    return table(days_with(20, 19, night=moved), **changes)


@pytest.mark.parametrize(("hours", "flag"), [(5, True), (4, False), (0, False)])
def test_the_shifted_flag(hours: int, flag: bool) -> None:
    assert row_of(_shifted_table(hours), jan(20)).night_shifted is flag


def test_the_shifted_flag_needs_its_minimum_of_nights() -> None:
    result = table(complete_days(20))
    assert row_of(result, jan(14)).night_shifted is None
    assert row_of(result, jan(15)).night_shifted is False


def test_the_default_series_is_below_the_coverage() -> None:
    result = table(complete_days(1))
    row = result.rows[0]
    assert row.night_body_battery_absence is ViewAbsence.BELOW_COVERAGE
    assert row.night_body_battery_ceiling is None
    assert row.night_body_battery_coverage is None
    assert result.summary.nights_below_body_battery_coverage == 1
    assert result.summary.nights_without_body_battery_point == 0


def _dense_row(count: int, level: int = 50, **kwargs: Any) -> Any:
    return table(
        (day_record(D1, night=night_with(D1, dense(D1, count, level=level))),), **kwargs
    )


def test_a_dense_series() -> None:
    full = _dense_row(160).rows[0]
    assert full.night_body_battery_coverage == 1.0
    assert full.night_body_battery_ceiling is False
    assert full.night_body_battery_absence is None
    assert _dense_row(128).rows[0].night_body_battery_coverage == 0.8
    below = _dense_row(127)
    assert below.rows[0].night_body_battery_coverage is None
    assert below.rows[0].night_body_battery_absence is ViewAbsence.BELOW_COVERAGE
    assert below.summary.nights_below_body_battery_coverage == 1


def test_the_ceiling() -> None:
    assert BODY_BATTERY_CEILING == 100
    assert BODY_BATTERY_LEVEL_RANGE[1] == BODY_BATTERY_CEILING
    assert _dense_row(160, 100).rows[0].night_body_battery_ceiling is True
    assert _dense_row(160, 99).rows[0].night_body_battery_ceiling is False
    series = body_battery(D1, [i * 180.0 for i in range(160)], [50] * 159 + [100])
    assert only(day_record(D1, night=night_with(D1, series))).night_body_battery_ceiling


def test_a_night_without_a_point() -> None:
    result = table(
        (day_record(D1, night=night(D1, series=EMPTY_NIGHT_SERIES)),),
    )
    assert result.rows[0].night_body_battery_absence is ViewAbsence.NO_POINT
    assert result.summary.nights_without_body_battery_point == 1
    assert result.summary.nights_below_body_battery_coverage == 0


def test_the_step_and_the_minimum_go_to_the_view() -> None:
    sparse = day_record(D1, night=night_with(D1, dense(D1, 80, 360.0)))
    wide = definition({"night_body_battery_step_s": 360.0})
    assert only(sparse, day_definition=wide).night_body_battery_coverage == 1.0
    assert only(sparse).night_body_battery_coverage is None
    free = definition({"min_coverage_fraction": 0.0})
    row = only(day_record(D1), day_definition=free)
    assert row.night_body_battery_coverage == 180 / 28800
    assert row.night_body_battery_ceiling is False


def test_the_naps() -> None:
    naps = (
        nap(D1, start=at(D1, 6), end=at(D1, 7, 30), sleep_s=3000.0),
        nap(D1, start=at(D1, 7), end=at(D1, 7, 20), sleep_s=600.0),
        nap(D1),
    )
    row = only(day_record(D1, naps=naps))
    assert row.nap_count == 3
    assert row.nap_window_s == 8400.0
    assert row.nap_sleep_s == 5100.0
    assert row.naps_overlapping_night == 1


def test_without_a_nap() -> None:
    row = only(day_record(D1, naps=()))
    assert (row.nap_count, row.nap_window_s, row.nap_sleep_s) == (0, 0.0, 0.0)
    assert row.naps_overlapping_night == 0


def test_a_nap_that_touches_the_night_does_not_overlap_it() -> None:
    previous = date(1999, 12, 31)
    naps = (
        nap(D1, start=at(previous, 22), end=at(previous, 23)),
        nap(D1, start=at(D1, 2), end=at(D1, 2, 30)),
    )
    assert only(day_record(D1, naps=naps)).naps_overlapping_night == 1


# --- les valeurs ----------------------------------------------------------------------

DAY_SUPPORT = (
    "respiration_avg_waking_breaths_per_min",
    "spo2_average_percent",
    "spo2_lowest_percent",
    "stress_average_level",
    "stress_max_level",
    "body_battery_charged",
    "body_battery_drained",
    "body_battery_highest",
    "body_battery_lowest",
    "steps",
    "moderate_intensity_s",
    "vigorous_intensity_s",
    "floors_ascended_m",
    "floors_descended_m",
    "average_altitude_m",
)
NIGHT_AND_WAKING = (
    "hrv_last_night_avg_ms",
    "hrv_last_night_5min_high_ms",
    "hrv_weekly_avg_ms",
    "hrv_baseline_balanced_low_ms",
    "hrv_baseline_balanced_upper_ms",
    "hrv_baseline_low_upper_ms",
    "hrv_baseline_marker_value",
    "hrv_status",
    "respiration_avg_sleep_breaths_per_min",
    "spo2_avg_sleep_percent",
    "body_battery_at_wake",
    "body_battery_during_sleep",
)


def test_the_values_read_as_they_are() -> None:
    row = only(
        day_record(D1, activity_totals=activity_totals(D1, average_altitude_m=1300.0))
    )
    expected = {
        "resting_hr_bpm": 48.0,
        "resting_hr_status": RestingHrStatus.VALID,
        "hrv_last_night_avg_ms": 50.0,
        "hrv_last_night_5min_high_ms": 70.0,
        "hrv_weekly_avg_ms": 48.0,
        "hrv_status": "BALANCED",
        "hrv_baseline_balanced_low_ms": 40.0,
        "hrv_baseline_balanced_upper_ms": 60.0,
        "hrv_baseline_low_upper_ms": 35.0,
        "hrv_baseline_marker_value": 0.5,
        "respiration_avg_sleep_breaths_per_min": 13.0,
        "respiration_avg_waking_breaths_per_min": 15.0,
        "spo2_avg_sleep_percent": 95.0,
        "spo2_average_percent": 96.0,
        "spo2_lowest_percent": 90.0,
        "stress_average_level": 25,
        "stress_max_level": 90,
        "body_battery_charged": 60,
        "body_battery_drained": 55,
        "body_battery_highest": 90,
        "body_battery_lowest": 20,
        "body_battery_at_wake": 85,
        "body_battery_during_sleep": 45,
        "steps": 10000,
        "moderate_intensity_s": 1200.0,
        "vigorous_intensity_s": 600.0,
        "floors_ascended_m": 30.5,
        "floors_descended_m": 27.5,
        "average_altitude_m": 1300.0,
    }
    for name, value in expected.items():
        assert getattr(row, name) == value, name


def test_a_quantity_whose_summary_is_missing_is_absent() -> None:
    row = only(day_record(D1, activity_totals=None, hrv=None))
    assert row.steps is None
    assert row.hrv_weekly_avg_ms is None


NOT_COMPLETE = {
    "tronqué": lambda: truncated_day(D1),
    "sans mesure": lambda: day_record(D1, state=DayState.NO_MEASUREMENT),
    "vide": lambda: empty_day(D1, night=night(D1)),
}


@pytest.mark.parametrize("build", NOT_COMPLETE.values(), ids=NOT_COMPLETE.keys())
def test_a_day_not_complete_loses_its_day_support(build: Any) -> None:
    row, full = only(build()), only(day_record(D1))
    for name in DAY_SUPPORT:
        assert getattr(full, name) is not None, name
        assert getattr(row, name) is None, name
    assert (row.stress_measured_s, row.stress_valid) == (None, None)
    assert row.measured_sleep_s == full.measured_sleep_s


@pytest.mark.parametrize(
    "build",
    [NOT_COMPLETE["tronqué"], NOT_COMPLETE["sans mesure"]],
    ids=["tronqué", "sans mesure"],
)
def test_night_and_waking_quantities_stay(build: Any) -> None:
    row, full = only(build()), only(day_record(D1))
    for name in NIGHT_AND_WAKING:
        assert getattr(row, name) == getattr(full, name), name


def test_the_resting_heart_rate() -> None:
    truncated = only(truncated_day(D1))
    assert (truncated.resting_hr_bpm, truncated.resting_hr_status) == (
        48.0,
        RestingHrStatus.PROVISIONAL,
    )
    none = only(day_record(D1, state=DayState.NO_MEASUREMENT))
    assert (none.resting_hr_bpm, none.resting_hr_status) == (
        None,
        RestingHrStatus.ABSENT,
    )
    short = day_record(D1, night=night(D1, **_sleep(3600, 3600, 3599)))
    assert only(short).resting_hr_status is RestingHrStatus.NO_NIGHT
    enough = day_record(D1, night=night(D1, **_sleep(3600, 3600, 3600)))
    assert only(enough).resting_hr_status is RestingHrStatus.VALID
    free = definition({"resting_hr_min_sleep_s": 0.0})
    assert only(short, day_definition=free).resting_hr_status is RestingHrStatus.VALID


def _stress(rest: float, **changes: Any) -> Any:
    durations: dict[str, Any] = {
        "rest_duration_s": rest,
        "low_duration_s": 0.0,
        "medium_duration_s": 0.0,
        "high_duration_s": 0.0,
    }
    return stress_summary(D1, **{**durations, **changes})


def test_the_measured_stress_and_its_validity() -> None:
    row = only(day_record(D1))
    assert (row.stress_measured_s, row.stress_valid) == (63000.0, True)
    assert only(day_record(D1, stress=_stress(43200.0))).stress_valid is True
    assert only(day_record(D1, stress=_stress(43199.0))).stress_valid is False
    strict = definition({"stress_min_fraction": 0.9})
    assert (
        only(
            day_record(D1, stress=_stress(43200.0)), day_definition=strict
        ).stress_valid
        is False
    )


@pytest.mark.parametrize(
    "name",
    ["rest_duration_s", "low_duration_s", "medium_duration_s", "high_duration_s"],
)
def test_one_duration_missing(name: str) -> None:
    row = only(day_record(D1, stress=stress_summary(D1, **{name: None})))
    assert (row.stress_measured_s, row.stress_valid) == (None, None)
    assert row.stress_average_level == 25


def test_activity_and_uncategorized_durations_do_not_count() -> None:
    summary = stress_summary(D1, activity_duration_s=0.0, uncategorized_duration_s=0.0)
    assert only(day_record(D1, stress=summary)).stress_measured_s == 63000.0


def test_without_a_stress_summary() -> None:
    row = only(day_record(D1, stress=None))
    assert (row.stress_measured_s, row.stress_valid) == (None, None)
    assert row.stress_average_level is None


def test_the_validity_of_a_day_of_25_hours() -> None:
    day = date(2000, 10, 29)
    start = datetime(2000, 10, 29, tzinfo=PLUS2)
    summary = stress_summary(
        day,
        rest_duration_s=43197.0,
        low_duration_s=1.0,
        medium_duration_s=1.0,
        high_duration_s=1.0,
    )
    long_day = day_record(
        day,
        window_start=start,
        data_end=datetime(2000, 10, 30, tzinfo=PLUS1),
        stress=summary,
    )
    assert only(long_day).stress_valid is False
    usual = day_record(
        day, window_start=start, data_end=start + timedelta(hours=24), stress=summary
    )
    assert only(usual).stress_valid is True


def test_the_readiness_of_waking() -> None:
    row = only(day_record(D1))
    assert (row.readiness_score, row.readiness_level) == (70, "MODERATE")
    assert row.readiness_instant == at(D1, 7, 5)
    assert row.readiness_absence is None
    assert row.readiness_entry_count == 1


def test_the_tolerance_of_the_readiness() -> None:
    limit = (readiness(D1, instant=at(D1, 6, 45)),)
    assert only(day_record(D1, readiness=limit)).readiness_instant == at(D1, 6, 45)
    early = (readiness(D1, instant=at(D1, 6, 44, 59)),)
    row = only(day_record(D1, readiness=early))
    assert (row.readiness_instant, row.readiness_score, row.readiness_level) == (
        None,
        None,
        None,
    )
    assert row.readiness_absence is ViewAbsence.NO_ENTRY_AFTER_NIGHT
    assert row.readiness_entry_count == 1
    wider = definition({"readiness_tolerance_s": 901.0})
    assert only(
        day_record(D1, readiness=early), day_definition=wider
    ).readiness_instant == at(D1, 6, 44, 59)


def test_all_entries_are_counted() -> None:
    entries = (
        readiness(D1, instant=at(D1, 3), input_context="AUTRE"),
        readiness(D1),
        readiness(D1, instant=at(D1, 12), input_context="AUTRE"),
    )
    row = only(day_record(D1, readiness=entries))
    assert row.readiness_entry_count == 3
    assert row.readiness_instant == at(D1, 7, 5)


# --- Training Status ------------------------------------------------------------------


def test_each_block_goes_to_the_row_of_its_day() -> None:
    previous = date(1999, 12, 31)
    balance = load_balance_block(
        D1,
        monthly_aerobic_high_target_min=450.0,
        monthly_aerobic_high_target_max=700.0,
    )
    result = table(
        complete_days(3),
        history(
            statuses=(status_block(previous), status_block(jan(2))),
            load_balances=(balance,),
            vo2_max=(vo2_max_block(jan(2)), vo2_max_block(jan(4))),
            heat_acclimation=(heat_block(jan(3)),),
            altitude_acclimation=(altitude_block(D1), altitude_block(jan(6))),
        ),
    )
    second = row_of(result, jan(2))
    assert second.ts_status_instant == status_block(jan(2)).proper_instant
    assert second.ts_status_code == 4
    assert second.ts_acute_load == 300.0
    assert second.ts_chronic_load == 320.0
    assert second.ts_acute_chronic_ratio == 0.9
    assert second.ts_acwr_status == "OPTIMAL"
    first = row_of(result, D1)
    assert first.ts_status_code is None
    assert first.ts_load_balance_instant == balance.proper_instant
    assert first.ts_monthly_aerobic_low == 400.5
    assert first.ts_monthly_aerobic_low_target_min == 200.0
    assert first.ts_monthly_aerobic_low_target_max == 500.0
    assert first.ts_monthly_aerobic_high == 300.5
    assert first.ts_monthly_aerobic_high_target_min == 450.0
    assert first.ts_monthly_aerobic_high_target_max == 700.0
    assert first.ts_monthly_anaerobic == 50.5
    assert first.ts_monthly_anaerobic_target_min == 0.0
    assert first.ts_monthly_anaerobic_target_max == 100.0
    assert second.ts_vo2_max_instant == vo2_max_block(jan(2)).proper_instant
    assert second.ts_vo2_max_ml_kg_min == 56.0
    assert second.ts_vo2_max_precise_ml_kg_min == 55.5
    third = row_of(result, jan(3))
    assert third.ts_heat_instant == heat_block(jan(3)).proper_instant
    assert third.ts_heat_acclimation_percent == 20.0
    assert third.ts_heat_trend == "ACCLIMATIZING"
    assert first.ts_altitude_instant == altitude_block(D1).proper_instant
    assert first.ts_acclimation_altitude_m == 1500.0
    assert first.ts_current_altitude_m == 1600.0
    assert first.ts_altitude_trend == "ACCLIMATIZING"
    assert result.summary.blocks_outside_days == 3


def test_the_instant_is_the_proper_one_and_the_row_that_of_the_day() -> None:
    proper = at(D1, 23, 30)
    result = table(
        complete_days(2),
        history(
            statuses=(
                status_block(
                    D1, timestamp=None, proper_instant=proper, file_day=jan(2)
                ),
                status_block(jan(2), timestamp=None, proper_instant=None),
            ),
            vo2_max=(vo2_max_block(D1, proper_instant=proper, file_day=jan(2)),),
        ),
    )
    first, second = result.rows
    assert first.ts_status_instant == proper
    assert first.ts_vo2_max_instant == proper
    assert first.ts_vo2_max_ml_kg_min == 56.0
    assert second.ts_vo2_max_ml_kg_min is None
    assert second.ts_status_instant is None
    assert second.ts_status_code == 4


def _four_statuses() -> TrainingStatusHistory:
    days = (date(1999, 12, 31), D1, jan(3), jan(4))
    return history(statuses=tuple(status_block(day) for day in days))


def test_the_extent_is_included() -> None:
    result = table(complete_days(3, skip=(1,)), _four_statuses())
    assert row_of(result, D1).ts_status_code == 4
    assert row_of(result, jan(3)).ts_status_code == 4
    assert row_of(result, jan(2)).ts_status_code is None
    assert result.summary.blocks_outside_days == 2
    empty = table((), _four_statuses())
    assert empty.rows == ()
    assert empty.summary.blocks_outside_days == 4


# --- le résumé -----------------------------------------------------------------------


def test_the_six_counts_of_the_summary() -> None:
    assert [f.name for f in dataclasses.fields(DaySummary)] == [
        "activities_before_first_day",
        "activities_after_last_day",
        "blocks_outside_days",
        "nights_below_body_battery_coverage",
        "nights_without_body_battery_point",
        "absent_days",
    ]


def test_two_status_blocks_of_the_same_day_are_refused_by_their_contract() -> None:
    with pytest.raises(ContractError, match=r"^statuses doit être trié sans doublon"):
        history(statuses=(status_block(D1), status_block(D1)))


def test_each_count_at_its_place() -> None:
    previous = date(1999, 12, 31)
    documents = (
        day_record(D1),
        day_record(jan(4), night=night(jan(4), series=EMPTY_NIGHT_SERIES)),
        day_record(jan(5), night=None),
    )
    result = table(
        documents,
        history(
            statuses=(status_block(date(1999, 12, 30)), status_block(jan(2))),
            heat_acclimation=(heat_block(jan(31)),),
        ),
        [
            nine(date(1999, 12, 30), "a"),
            nine(previous, "b"),
            nine(jan(2), "c"),
            nine(jan(20), "d"),
        ],
    )
    c, a = DayRowState.COMPLETE, DayRowState.ABSENT
    assert [row.state for row in result.rows] == [c, a, a, c, c]
    n = ViewAbsence.NO_NIGHT
    assert [row.night_body_battery_absence for row in result.rows] == [
        ViewAbsence.BELOW_COVERAGE,
        n,
        n,
        ViewAbsence.NO_POINT,
        n,
    ]
    assert result.summary == DaySummary(2, 1, 2, 1, 1, 2)


# --- le journal -----------------------------------------------------------------------


def test_the_journal_types_of_each_day() -> None:
    result = table(
        complete_days(4),
        journal=journal_of(
            (date(1999, 12, 27), jan(2), TRAVEL),
            (jan(2), jan(3), RACE),
            (jan(2), jan(2), TRAVEL),
            (jan(3), date(2000, 2, 10), OTHER),
        ),
    )
    assert [row.journal_types for row in result.rows] == [
        (TRAVEL,),
        (RACE, TRAVEL),
        (OTHER, RACE),
        (OTHER,),
    ]


def test_an_illness_and_the_night_of_its_waking_day() -> None:
    result = table(complete_days(20), journal=journal_of((jan(12), jan(14), ILLNESS)))
    for day in (12, 13, 14):
        row = row_of(result, jan(day))
        assert row.hrv_admitted is False
        assert row.measured_sleep_refusal is AdmissionRefusal.ILLNESS
    for day in (11, 15):
        row = row_of(result, jan(day))
        assert row.hrv_refusal is None
        assert row.measured_sleep_refusal is None
    assert row_of(result, jan(12)).night_start == at(jan(11), 23)


# --- l'activité du jour ---------------------------------------------------------------


def test_the_day_of_an_activity_is_the_local_date_of_its_start() -> None:
    result = table(
        complete_days(3),
        entries=[
            index_entry("a", at(D1, 23, 30), elapsed_duration_s=7200.0),
            index_entry("b", at(jan(2), 0, 30, offset=PLUS2)),
        ],
    )
    assert result.rows[0].activity_count == 1
    assert result.rows[0].foot_elapsed_s == 7200.0
    assert result.rows[1].activity_count == 1
    assert result.rows[2].activity_count == 0


def test_activities_outside_the_days() -> None:
    result = table(
        complete_days(3),
        entries=[
            index_entry("a", at(date(1999, 12, 31), 23, 59)),
            index_entry("b", at(D1, 0)),
            index_entry("c", at(jan(3), 23, 59)),
            index_entry("d", at(jan(4), 0)),
            index_entry("e", at(jan(9), 0)),
        ],
    )
    assert result.summary.activities_before_first_day == 1
    assert result.summary.activities_after_last_day == 2
    assert [row.activity_count for row in result.rows] == [1, 0, 1]


def _start() -> datetime:
    return at(D1, 9)


def test_the_load_of_the_day() -> None:
    s = _start()
    three = activity_columns(
        [
            index_entry("a", s, training_load=40.0),
            index_entry("b", s, training_load=0.0),
            index_entry("c", s, training_load=None),
        ]
    )
    assert three["garmin_training_load"] == 40.0
    assert three["activities_without_load"] == 1
    assert (
        activity_columns([index_entry("a", s, training_load=0.0)])[
            "garmin_training_load"
        ]
        == 0.0
    )
    none = activity_columns(
        [
            index_entry("a", s, training_load=None),
            index_entry("b", s, training_load=None),
        ]
    )
    assert none["garmin_training_load"] is None
    assert none["activities_without_load"] == 2
    empty = activity_columns([])
    assert empty["garmin_training_load"] == 0.0
    assert empty["activity_count"] == 0
    assert empty["activities_without_load"] == 0
    row = only(day_record(D1), entries=[nine(D1, training_load=None)])
    assert row.garmin_training_load is None


def test_the_durations_by_family() -> None:
    s = _start()
    columns = activity_columns(
        [
            index_entry("a", s, elapsed_duration_s=100.0),
            index_entry("b", s, source_activity_type="hiking", elapsed_duration_s=50.0),
            index_entry(
                "c", s, source_activity_type="mountain_biking", elapsed_duration_s=200.0
            ),
            index_entry(
                "d",
                s,
                source_activity_type="backcountry_skiing",
                elapsed_duration_s=300.0,
            ),
            index_entry("e", s, source_activity_type="golf", elapsed_duration_s=400.0),
            index_entry("f", s, source_activity_type="golf", elapsed_duration_s=None),
            index_entry(
                "g", s, source_activity_type="running", elapsed_duration_s=None
            ),
        ]
    )
    assert columns["activity_count"] == 7
    assert columns["foot_elapsed_s"] == 150.0
    assert columns["mtb_elapsed_s"] == 200.0
    assert columns["ski_touring_elapsed_s"] == 300.0
    assert columns["other_elapsed_s"] == 400.0
    assert columns["other_activity_count"] == 2
    assert columns["activities_without_elapsed"] == 2


def test_two_types_without_family() -> None:
    s = _start()
    columns = activity_columns(
        [
            index_entry(
                "a", s, source_activity_type="road_biking", elapsed_duration_s=3600.0
            ),
            index_entry(
                "b", s, source_activity_type="bouldering", elapsed_duration_s=5400.0
            ),
        ]
    )
    assert columns["other_elapsed_s"] == 9000.0
    assert columns["other_activity_count"] == 2
    assert columns["activity_count"] == 2
    assert columns["foot_elapsed_s"] == 0.0
    assert columns["activities_without_elapsed"] == 0


def test_a_family_survives_a_refused_view() -> None:
    columns = activity_columns(
        [index_entry("a", _start(), distance_m=None, elapsed_duration_s=100.0)]
    )
    assert columns["foot_elapsed_s"] == 100.0
    assert columns["other_activity_count"] == 0


def test_a_day_without_activity() -> None:
    row = only(day_record(D1))
    assert row.activity_count == 0
    assert row.garmin_training_load == 0.0
    assert (row.foot_elapsed_s, row.mtb_elapsed_s, row.ski_touring_elapsed_s) == (
        0.0,
        0.0,
        0.0,
    )
    assert (row.other_elapsed_s, row.other_activity_count) == (0.0, 0)
    assert (row.activities_without_load, row.activities_without_elapsed) == (0, 0)


def test_an_outing_recorded_twice_adds_up_twice() -> None:
    row = only(day_record(D1), entries=[nine(D1, "a"), nine(D1, "b")])
    assert row.activity_count == 2
    assert row.garmin_training_load == 175.0
    assert row.foot_elapsed_s == 7447.0


# --- les paramètres -------------------------------------------------------------------


def test_the_ten_thresholds() -> None:
    assert [
        (s.name, s.unit, s.default, s.minimum, s.maximum)
        for s in DAY_VIEW_PARAMETER_SPECS
    ] == [
        ("max_unmeasured_fraction", None, 0.20, 0.0, 1.0),
        ("short_sleep_s", "s", 14400.0, 0.0, 86400.0),
        ("shift_s", "s", 14400.0, 0.0, 43200.0),
        ("usual_window_days", "d", 28.0, 1.0, 365.0),
        ("usual_min_nights", None, 14.0, 1.0, 365.0),
        ("resting_hr_min_sleep_s", "s", 10800.0, 0.0, 86400.0),
        ("readiness_tolerance_s", "s", 900.0, 0.0, 86400.0),
        ("stress_min_fraction", None, 0.5, 0.0, 1.0),
        ("min_coverage_fraction", None, 0.8, 0.0, 1.0),
        ("night_body_battery_step_s", "s", 180.0, 0.001, 3600.0),
    ]
    assert DAY_VIEW_INTEGER_PARAMETERS == ("usual_window_days", "usual_min_nights")


@pytest.mark.parametrize("spec", DAY_VIEW_PARAMETER_SPECS, ids=lambda s: s.name)
@pytest.mark.parametrize("bound", ["minimum", "maximum"])
def test_each_threshold_at_its_bounds(spec: Any, bound: str) -> None:
    chosen = definition({spec.name: getattr(spec, bound)})
    result = table(complete_days(30, skip=(4,)), day_definition=chosen)
    assert len(result.rows) == 30


def test_each_threshold_of_the_night_goes_to_the_view() -> None:
    documents = complete_days(20)
    partial = table(
        documents, day_definition=definition({"max_unmeasured_fraction": 0.05})
    )
    assert row_of(partial, jan(20)).night_state is NightState.PARTIAL
    assert row_of(table(documents), jan(20)).night_state is NightState.COMPLETE
    short = table(documents, day_definition=definition({"short_sleep_s": 25201.0}))
    assert row_of(short, jan(20)).night_short is True
    minimum = table(documents, day_definition=definition({"usual_min_nights": 1}))
    assert row_of(minimum, jan(6)).night_shifted is False
    assert row_of(table(documents), jan(6)).night_shifted is None
    window = table(documents, day_definition=definition({"usual_window_days": 1}))
    assert (
        row_of(window, jan(20)).night_shifted_absence is ViewAbsence.BELOW_USUAL_MINIMUM
    )
    assert row_of(table(documents), jan(20)).night_shifted_absence is None


def test_the_shift_threshold_goes_to_the_view() -> None:
    assert row_of(_shifted_table(5), jan(20)).night_shifted is True
    wide = definition({"shift_s": 18001.0})
    assert (
        row_of(_shifted_table(5, day_definition=wide), jan(20)).night_shifted is False
    )


def test_the_definition_of_the_days() -> None:
    items = DEFAULT_DAY_DEFINITION.items()
    names = [name for name, _ in items]
    assert names == sorted(names)
    assert len(items) == 21
    found = dict(items)
    assert found["days.short_sleep_s"] == 14400.0
    assert found["days.night_body_battery_step_s"] == 180.0
    assert found["normal.window_days"] == 28.0
    assert found["normal.exclude_altitude_stay"] == 1.0
    assert {name.split(".")[0] for name in names} == {"days", "normal"}


@pytest.mark.parametrize(
    ("views", "normals", "name"),
    [
        ({"usual_window_days": 27.5}, {}, "usual_window_days"),
        ({"usual_min_nights": 13.5}, {}, "usual_min_nights"),
        ({}, {"min_admitted_days": 13.5}, "min_admitted_days"),
        ({}, {"exclude_altitude_stay": 0.5}, "exclude_altitude_stay"),
    ],
)
def test_a_non_integer_count_is_refused(
    views: dict[str, float], normals: dict[str, float], name: str
) -> None:
    with pytest.raises(ValueError, match=f"{name} doit être entier"):
        definition(views, normals)


def test_the_message_of_a_non_integer_threshold() -> None:
    with pytest.raises(
        ValueError,
        match=r"^Le paramètre usual_window_days doit être entier \(un compte ou un "
        r"interrupteur\), reçu 27\.5\.$",
    ):
        definition({"usual_window_days": 27.5})


def test_each_set_is_of_its_specs() -> None:
    views, normals = (
        ParameterSet(DAY_VIEW_PARAMETER_SPECS),
        ParameterSet(NORMAL_PARAMETER_SPECS),
    )
    with pytest.raises(ValueError, match="views doit être un jeu de ses specs"):
        DayDefinition(normals, normals)
    with pytest.raises(ValueError, match="normals doit être un jeu de ses specs"):
        DayDefinition(views, views)


# --- les valeurs que la ligne recopie du document -------------------------------------


def test_each_duration_of_the_night_goes_to_its_column() -> None:
    row = only(
        day_record(
            D1,
            night=night(
                D1,
                deep_s=3000.0,
                light_s=15000.0,
                rem_s=5000.0,
                awake_s=1500.0,
                unmeasurable_s=900.0,
            ),
        )
    )
    assert row.deep_s == 3000.0
    assert row.light_s == 15000.0
    assert row.rem_s == 5000.0
    assert row.awake_s == 1500.0
    assert row.unmeasurable_s == 900.0


def _indicators() -> DayRow:
    return only(
        day_record(
            D1,
            night=night(D1, window_confirmed=True, from_device=False, rem_capable=None),
        )
    )


def test_the_window_confirmed() -> None:
    assert _indicators().night_window_confirmed is True


def test_the_night_from_device() -> None:
    assert _indicators().night_from_device is False


def test_the_rem_capable() -> None:
    assert _indicators().night_rem_capable is None


def test_each_version_goes_to_its_column() -> None:
    row = only(
        day_record(
            D1,
            versions=versions(
                sleep_version=2,
                sleep_respiration_version=201,
                respiration_version=202,
                summary_respiration_version=203,
                summary_body_battery_version=3,
            ),
        )
    )
    assert row.sleep_version == 2
    assert row.sleep_respiration_version == 201
    assert row.respiration_version == 202
    assert row.summary_respiration_version == 203
    assert row.summary_body_battery_version == 3


def test_a_resting_hr_is_read_by_the_view() -> None:
    row = only(day_record(D1, resting_hr=resting_hr(D1, resting_hr_bpm=47.0)))
    assert row.resting_hr_bpm == 47.0
