"""La ligne de ``jours`` et ses énumérations (AN2-2) : chaque invariant des deux côtés,
sur les lignes inventées de ``tests/fixtures/day_rows.py``."""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from itertools import pairwise
from typing import Any

import pytest

from fixtures.day_rows import (
    LOG_CENTER,
    MEASURES,
    PLUS1,
    VALUE_COLUMN,
    absent_row,
    admitted_measure,
    complete_row,
    group_of,
    no_night_row,
)
from mountain_perf.schemas import (
    DAY_STATE_DESCRIPTIONS,
    ContractError,
    DayState,
    NightState,
    RestingHrStatus,
    ViewAbsence,
)
from mountain_perf.schemas.processed import (
    ADMISSION_REFUSAL_DESCRIPTIONS,
    DAY_ROW_STATE_DESCRIPTIONS,
    JOURNAL_EVENT_TYPE_DESCRIPTIONS,
    NORMAL_ABSENCE_DESCRIPTIONS,
    AdmissionRefusal,
    DayRow,
    DayRowState,
    JournalEventType,
    NormalAbsence,
)

Row = Callable[..., DayRow]

MEASURE_NAMES = [name for name, _ in MEASURES]
UNIT = dict(MEASURES)


def refused(build: Row, message: str, **changes: Any) -> None:
    """La construction lève une ``ContractError`` au type exact, au message donné."""
    with pytest.raises(ContractError) as caught:
        build(**changes)
    assert type(caught.value) is ContractError
    assert str(caught.value) == message


def refused_start(build: Row, start: str, **changes: Any) -> None:
    with pytest.raises(ContractError) as caught:
        build(**changes)
    assert type(caught.value) is ContractError
    assert str(caught.value).startswith(start)


def normal_of(measure: str) -> str:
    return f"{measure}_normal{UNIT[measure]}"


def low_of(measure: str) -> str:
    return f"{measure}_range_low{UNIT[measure]}"


def high_of(measure: str) -> str:
    return f"{measure}_range_high{UNIT[measure]}"


def without_group(measure: str, **changes: Any) -> dict[str, Any]:
    gone: dict[str, Any] = dict.fromkeys(group_of(measure))
    return admitted_measure(measure, **gone, **changes)


EXPECTED_FIELDS = [
    "day",
    "state",
    "window_start",
    "data_end",
    "reference_export",
    "device_ranks",
    "uncertain_device",
    "sleep_version",
    "sleep_respiration_version",
    "respiration_version",
    "summary_respiration_version",
    "summary_body_battery_version",
    "body_battery_series_versions",
    "night_start",
    "night_end",
    "night_state",
    "night_short",
    "night_short_absence",
    "night_shifted",
    "night_shifted_absence",
    "measured_sleep_s",
    "deep_s",
    "light_s",
    "rem_s",
    "awake_s",
    "unmeasurable_s",
    "unmeasured_fraction",
    "night_confirmation",
    "night_window_confirmed",
    "night_from_device",
    "night_rem_capable",
    "sleep_score",
    "night_avg_stress",
    "night_avg_heart_rate_bpm",
    "night_body_battery_change",
    "night_restless_moments",
    "skin_temperature_deviation_c",
    "night_body_battery_ceiling",
    "night_body_battery_coverage",
    "night_body_battery_absence",
    "nap_count",
    "nap_window_s",
    "nap_sleep_s",
    "naps_overlapping_night",
    "resting_hr_bpm",
    "resting_hr_status",
    "hrv_last_night_avg_ms",
    "hrv_last_night_5min_high_ms",
    "hrv_weekly_avg_ms",
    "hrv_baseline_balanced_low_ms",
    "hrv_baseline_balanced_upper_ms",
    "hrv_baseline_low_upper_ms",
    "hrv_baseline_marker_value",
    "hrv_status",
    "respiration_avg_sleep_breaths_per_min",
    "respiration_avg_waking_breaths_per_min",
    "spo2_avg_sleep_percent",
    "spo2_average_percent",
    "spo2_lowest_percent",
    "stress_average_level",
    "stress_max_level",
    "stress_measured_s",
    "stress_valid",
    "body_battery_charged",
    "body_battery_drained",
    "body_battery_highest",
    "body_battery_lowest",
    "body_battery_at_wake",
    "body_battery_during_sleep",
    "steps",
    "moderate_intensity_s",
    "vigorous_intensity_s",
    "floors_ascended_m",
    "floors_descended_m",
    "average_altitude_m",
    "readiness_score",
    "readiness_level",
    "readiness_instant",
    "readiness_absence",
    "readiness_entry_count",
    "ts_status_instant",
    "ts_status_code",
    "ts_acute_load",
    "ts_chronic_load",
    "ts_acute_chronic_ratio",
    "ts_acwr_status",
    "ts_load_balance_instant",
    "ts_monthly_aerobic_low",
    "ts_monthly_aerobic_low_target_min",
    "ts_monthly_aerobic_low_target_max",
    "ts_monthly_aerobic_high",
    "ts_monthly_aerobic_high_target_min",
    "ts_monthly_aerobic_high_target_max",
    "ts_monthly_anaerobic",
    "ts_monthly_anaerobic_target_min",
    "ts_monthly_anaerobic_target_max",
    "ts_vo2_max_instant",
    "ts_vo2_max_ml_kg_min",
    "ts_vo2_max_precise_ml_kg_min",
    "ts_heat_instant",
    "ts_heat_acclimation_percent",
    "ts_heat_trend",
    "ts_altitude_instant",
    "ts_acclimation_altitude_m",
    "ts_current_altitude_m",
    "ts_altitude_trend",
    "journal_types",
    "activity_count",
    "garmin_training_load",
    "activities_without_load",
    "foot_elapsed_s",
    "mtb_elapsed_s",
    "ski_touring_elapsed_s",
    "other_elapsed_s",
    "other_activity_count",
    "activities_without_elapsed",
]


def measure_fields(measure: str) -> list[str]:
    unit = UNIT[measure]
    middle = (
        ["hrv_log_median", "hrv_log_dispersion"]
        if measure == "hrv"
        else [f"{measure}_dispersion{unit}"]
    )
    return [
        f"{measure}_admitted",
        f"{measure}_refusal",
        f"{measure}_normal{unit}",
        f"{measure}_range_low{unit}",
        f"{measure}_range_high{unit}",
        *middle,
        f"{measure}_admitted_days",
        f"{measure}_normal_absence",
        f"{measure}_segment",
        f"{measure}_rupture",
        f"{measure}_normal_straddles",
    ]


NAMES = [field.name for field in dataclasses.fields(DayRow)]


def test_day_row_has_its_183_columns_in_order() -> None:
    expected = EXPECTED_FIELDS + [f for m in MEASURE_NAMES for f in measure_fields(m)]
    assert len(NAMES) == 183
    assert len(set(NAMES)) == 183
    assert expected == NAMES


@pytest.mark.parametrize("measure", MEASURE_NAMES)
def test_each_measure_has_its_columns_together(measure: str) -> None:
    columns = measure_fields(measure)
    assert len(columns) == (12 if measure == "hrv" else 11)
    start = NAMES.index(columns[0])
    assert NAMES[start : start + len(columns)] == columns


@pytest.mark.parametrize(("measure", "column"), VALUE_COLUMN.items())
def test_the_value_of_each_measure_is_a_column(measure: str, column: str) -> None:
    assert measure in MEASURE_NAMES
    assert column in NAMES


def test_the_three_rows_of_the_world() -> None:
    absent = absent_row()
    assert absent.state is DayRowState.ABSENT
    assert absent.night_state is NightState.MISSING
    assert absent.resting_hr_status is RestingHrStatus.ABSENT
    complete = complete_row()
    assert complete.state is DayRowState.COMPLETE
    assert complete.hrv_normal_ms == pytest.approx(54.598150033, rel=1e-6)
    assert no_night_row().night_start is None


def test_a_row_is_a_value() -> None:
    row = complete_row()
    assert dataclasses.replace(row) == row
    assert complete_row() == row
    assert hash(complete_row()) == hash(row)


# ------------------------------------------------------------------------------------
# Les énumérations
# ------------------------------------------------------------------------------------


def test_day_row_state() -> None:
    assert [m.value for m in DayRowState] == [
        "absent",
        "empty",
        "no_measurement",
        "truncated",
        "complete",
    ]
    assert [m.value for m in list(DayRowState)[1:]] == [m.value for m in DayState]
    for state in DayState:
        assert (
            DAY_ROW_STATE_DESCRIPTIONS[DayRowState(state.value)]
            == DAY_STATE_DESCRIPTIONS[state]
        )


def test_journal_event_type() -> None:
    assert [(m.name, m.value) for m in JournalEventType] == [
        ("ILLNESS", "maladie"),
        ("INJURY", "blessure"),
        ("RACE", "course"),
        ("TRAVEL", "deplacement"),
        ("MOVE", "demenagement"),
        ("ALTITUDE_STAY", "sejour_altitude"),
        ("BENCHMARK", "etalon"),
        ("OTHER", "autre"),
    ]


def test_normal_absence() -> None:
    assert [m.value for m in NormalAbsence] == [
        "no_admitted_day",
        "too_few_admitted_days",
    ]


def test_admission_refusal_in_the_order_of_the_rule() -> None:
    assert [m.value for m in AdmissionRefusal] == [
        "absent_row",
        "no_value",
        "invalid_value",
        "night_not_complete",
        "short_night",
        "shifted_night",
        "illness",
        "injury",
        "altitude_stay",
    ]


@pytest.mark.parametrize(
    ("enum", "table"),
    [
        (DayRowState, DAY_ROW_STATE_DESCRIPTIONS),
        (JournalEventType, JOURNAL_EVENT_TYPE_DESCRIPTIONS),
        (NormalAbsence, NORMAL_ABSENCE_DESCRIPTIONS),
        (AdmissionRefusal, ADMISSION_REFUSAL_DESCRIPTIONS),
    ],
)
def test_each_member_has_its_description_in_a_read_only_table(
    enum: Any, table: Any
) -> None:
    assert list(table) == list(enum)
    assert all(text.strip() for text in table.values())
    with pytest.raises(TypeError):
        table[next(iter(enum))] = "x"


# ------------------------------------------------------------------------------------
# Nombres et instants
# ------------------------------------------------------------------------------------


class _Plus2(tzinfo):
    """Un fuseau à décalage constant qui n'est pas un ``datetime.timezone``."""

    def utcoffset(self, dt: datetime | None) -> timedelta:
        return timedelta(hours=2)

    def dst(self, dt: datetime | None) -> timedelta:
        return timedelta(0)

    def tzname(self, dt: datetime | None) -> str:
        return "plus2"


INSTANTS = (
    "window_start",
    "data_end",
    "night_start",
    "night_end",
    "readiness_instant",
    "ts_status_instant",
    "ts_load_balance_instant",
    "ts_vo2_max_instant",
    "ts_heat_instant",
    "ts_altitude_instant",
)


def _instant_of(name: str) -> datetime:
    source = "ts_load_balance_instant" if name == "ts_vo2_max_instant" else name
    value = getattr(complete_row(), source)
    assert isinstance(value, datetime)
    return value


@pytest.mark.parametrize("name", INSTANTS)
def test_an_instant_with_any_constant_zone_is_brought_to_a_fixed_offset(
    name: str,
) -> None:
    instant = _instant_of(name)
    row = complete_row(**{name: instant.astimezone(_Plus2())})
    kept = getattr(row, name)
    assert kept == instant
    assert kept.tzinfo == timezone(timedelta(hours=2))


@pytest.mark.parametrize("name", INSTANTS)
def test_an_instant_without_a_zone_is_refused(name: str) -> None:
    naive = _instant_of(name).replace(tzinfo=None)
    refused(
        complete_row,
        f"{name} doit porter un fuseau horaire, reçu {naive!r}.",
        **{name: naive},
    )


@pytest.mark.parametrize("name", INSTANTS)
def test_an_offset_out_of_range_is_refused(name: str) -> None:
    far = _instant_of(name).replace(tzinfo=timezone(timedelta(hours=15)))
    refused(
        complete_row,
        f"décalage de {name} doit être dans [-43200, 50400], reçu 54000.0.",
        **{name: far},
    )


@pytest.mark.parametrize(
    "name",
    [
        "deep_s",
        "night_avg_stress",
        "skin_temperature_deviation_c",
        "ts_acute_load",
        "ts_current_altitude_m",
        "hrv_baseline_marker_value",
        "hrv_log_median",
        "night_respiration_normal_breaths_per_min",
    ],
)
@pytest.mark.parametrize(
    ("value", "text"),
    [(math.nan, "nan"), (math.inf, "inf"), (-math.inf, "-inf")],
)
def test_numbers_are_finite(name: str, value: float, text: str) -> None:
    refused(complete_row, f"{name} doit être fini, reçu {text}.", **{name: value})


def test_a_skin_temperature_deviation_may_be_negative() -> None:
    assert (
        complete_row(skin_temperature_deviation_c=-2.0).skin_temperature_deviation_c
        == -2.0
    )


@pytest.mark.parametrize(
    "name",
    [
        "sleep_version",
        "summary_body_battery_version",
        "night_restless_moments",
        "steps",
        "hrv_segment",
        "night_stress_segment",
    ],
)
def test_integers_are_not_negative(name: str) -> None:
    refused(complete_row, f"{name} doit être >= 0, reçu -1.", **{name: -1})
    assert getattr(complete_row(**{name: 0}), name) == 0


@pytest.mark.parametrize(
    "name",
    [
        "measured_sleep_s",
        "rem_s",
        "awake_s",
        "unmeasurable_s",
        "nap_window_s",
        "nap_sleep_s",
        "stress_measured_s",
        "moderate_intensity_s",
        "vigorous_intensity_s",
        "floors_ascended_m",
        "floors_descended_m",
        "garmin_training_load",
        "foot_elapsed_s",
        "mtb_elapsed_s",
        "ski_touring_elapsed_s",
        "other_elapsed_s",
        "resting_hr_dispersion_bpm",
        "measured_sleep_dispersion_s",
        "night_respiration_dispersion_breaths_per_min",
        "night_spo2_dispersion_percent",
    ],
)
def test_reals_are_not_negative(name: str) -> None:
    refused(complete_row, f"{name} doit être >= 0, reçu -1.0.", **{name: -1.0})
    assert getattr(complete_row(**{name: 0.0}), name) == 0.0


@pytest.mark.parametrize(
    ("name", "value"), [("deep_s", -0.5), ("hrv_log_dispersion", -0.1)]
)
def test_small_negative_reals_are_refused(name: str, value: float) -> None:
    refused(complete_row, f"{name} doit être >= 0, reçu {value}.", **{name: value})
    assert getattr(complete_row(**{name: 0.0}), name) == 0.0


NON_NEGATIVE = (
    "sleep_version",
    "sleep_respiration_version",
    "respiration_version",
    "summary_respiration_version",
    "summary_body_battery_version",
    "body_battery_series_versions",
    "measured_sleep_s",
    "deep_s",
    "light_s",
    "rem_s",
    "awake_s",
    "unmeasurable_s",
    "unmeasured_fraction",
    "night_restless_moments",
    "night_body_battery_coverage",
    "nap_count",
    "nap_window_s",
    "nap_sleep_s",
    "naps_overlapping_night",
    "stress_measured_s",
    "steps",
    "moderate_intensity_s",
    "vigorous_intensity_s",
    "floors_ascended_m",
    "floors_descended_m",
    "readiness_entry_count",
    "activity_count",
    "garmin_training_load",
    "activities_without_load",
    "foot_elapsed_s",
    "mtb_elapsed_s",
    "ski_touring_elapsed_s",
    "other_elapsed_s",
    "other_activity_count",
    "activities_without_elapsed",
    "hrv_log_dispersion",
    "resting_hr_dispersion_bpm",
    "measured_sleep_dispersion_s",
    "night_stress_dispersion",
    "night_respiration_dispersion_breaths_per_min",
    "night_spo2_dispersion_percent",
    "hrv_admitted_days",
    "resting_hr_admitted_days",
    "measured_sleep_admitted_days",
    "night_stress_admitted_days",
    "night_respiration_admitted_days",
    "night_spo2_admitted_days",
    "hrv_segment",
    "resting_hr_segment",
    "measured_sleep_segment",
    "night_stress_segment",
    "night_respiration_segment",
    "night_spo2_segment",
)
"""Les 53 grandeurs positives ou nulles de l'invariant 3, écrites ici une à une : la
liste du contrat ne se relit pas elle-même."""

FIELD_TYPES = {field.name: str(field.type) for field in dataclasses.fields(DayRow)}


def test_the_invariant_names_53_columns_of_the_row() -> None:
    assert len(NON_NEGATIVE) == len(set(NON_NEGATIVE)) == 53
    assert set(NON_NEGATIVE) <= set(FIELD_TYPES)


@pytest.mark.parametrize("name", NON_NEGATIVE)
def test_each_quantity_of_the_invariant_is_not_negative(name: str) -> None:
    kind = FIELD_TYPES[name]
    negative: float = -1 if kind.startswith(("int", "tuple")) else -1.0
    value = (negative,) if kind.startswith("tuple") else negative
    refused(complete_row, f"{name} doit être >= 0, reçu {negative}.", **{name: value})


def test_the_versions_of_the_series_are_not_negative() -> None:
    refused(
        complete_row,
        "body_battery_series_versions doit être >= 0, reçu -1.",
        body_battery_series_versions=(-1, 4),
    )
    assert complete_row(body_battery_series_versions=(0, 4))


@pytest.mark.parametrize(
    "name",
    ["readiness_entry_count", "hrv_admitted_days", "night_spo2_admitted_days"],
)
def test_negative_counts_without_an_admitted_side(name: str) -> None:
    refused(complete_row, f"{name} doit être >= 0, reçu -1.", **{name: -1})


@pytest.mark.parametrize(
    "name",
    [
        "nap_count",
        "naps_overlapping_night",
        "activity_count",
        "activities_without_load",
        "other_activity_count",
        "activities_without_elapsed",
    ],
)
def test_counts_are_not_negative_before_any_check_that_links_them(name: str) -> None:
    refused(complete_row, f"{name} doit être >= 0, reçu -1.", **{name: -1})


def test_the_coverage_is_a_fraction() -> None:
    for value in (0.0, 1.0):
        assert (
            complete_row(night_body_battery_coverage=value).night_body_battery_coverage
            == value
        )
    refused(
        complete_row,
        "night_body_battery_coverage doit être dans [0.0, 1.0], reçu 1.01.",
        night_body_battery_coverage=1.01,
    )
    refused(
        complete_row,
        "night_body_battery_coverage doit être >= 0, reçu -0.01.",
        night_body_battery_coverage=-0.01,
    )


def test_the_unmeasured_fraction_is_bounded_below_only() -> None:
    for value in (0.0, 1.0, 1.5):
        assert complete_row(unmeasured_fraction=value).unmeasured_fraction == value
    refused(
        complete_row,
        "unmeasured_fraction doit être >= 0, reçu -0.01.",
        unmeasured_fraction=-0.01,
    )


# ------------------------------------------------------------------------------------
# Le jour
# ------------------------------------------------------------------------------------

BOTH_WINDOW = "window_start et data_end vont ensemble."
WINDOW_STATE = (
    "window_start et data_end : présents si et seulement si state n'est ni absent ni "
    "empty."
)


@pytest.mark.parametrize("name", ["window_start", "data_end"])
def test_the_window_and_the_data_end_go_together(name: str) -> None:
    refused(complete_row, BOTH_WINDOW, **{name: None})


@pytest.mark.parametrize(
    "state",
    [DayRowState.NO_MEASUREMENT, DayRowState.TRUNCATED, DayRowState.COMPLETE],
)
def test_a_document_with_a_window_has_it(state: DayRowState) -> None:
    assert complete_row(state=state).state is state
    refused(complete_row, WINDOW_STATE, state=state, window_start=None, data_end=None)


def test_an_empty_or_absent_day_has_no_window() -> None:
    row = complete_row(state=DayRowState.EMPTY, window_start=None, data_end=None)
    assert row.state is DayRowState.EMPTY
    refused(complete_row, WINDOW_STATE, state=DayRowState.EMPTY)
    complete = complete_row()
    refused(
        absent_row,
        WINDOW_STATE,
        window_start=complete.window_start,
        data_end=complete.data_end,
    )


def test_the_reference_export() -> None:
    message = "reference_export : absent si et seulement si state est absent."
    refused(complete_row, message, reference_export=None)
    refused(absent_row, message, reference_export="export_2000-a")
    assert complete_row(reference_export="a.b-c_1").reference_export == "a.b-c_1"
    text = (
        "reference_export : le nom d'un export doit être fait de lettres et de "
        "chiffres ASCII, de « _ », « . » ou « - », et n'être ni « . » ni « .. »."
    )
    for name in ("a/b", "..", ""):
        refused(complete_row, text, reference_export=name)


def test_the_device_ranks() -> None:
    assert complete_row(device_ranks=(1, 3), uncertain_device=True)
    refused(complete_row, "device_ranks doit être >= 1, reçu 0.", device_ranks=(0,))
    refused(
        complete_row,
        "device_ranks doit être strictement croissante : device_ranks[0]=2, "
        "device_ranks[1]=1.",
        device_ranks=(2, 1),
        uncertain_device=True,
    )
    refused_start(
        complete_row,
        "device_ranks doit être strictement croissante",
        device_ranks=(1, 1),
        uncertain_device=True,
    )


def test_two_ranks_make_an_uncertain_day_not_the_reverse() -> None:
    refused(
        complete_row,
        "uncertain_device : un jour à au moins deux rangs est incertain.",
        device_ranks=(1, 2),
    )
    assert complete_row(uncertain_device=True).uncertain_device is True
    assert absent_row(uncertain_device=True).uncertain_device is True
    assert complete_row(device_ranks=()).uncertain_device is False


@pytest.mark.parametrize("versions", [(4, 3), (4, 4)])
def test_the_versions_of_the_series_increase(versions: tuple[int, ...]) -> None:
    refused_start(
        complete_row,
        "body_battery_series_versions doit être strictement croissante",
        body_battery_series_versions=versions,
    )


def test_no_version_of_the_series_is_admitted() -> None:
    assert (
        complete_row(body_battery_series_versions=()).body_battery_series_versions == ()
    )


# ------------------------------------------------------------------------------------
# La nuit
# ------------------------------------------------------------------------------------

NIGHT_STATE = (
    "night_start et night_end : présents si et seulement si night_state n'est pas "
    "missing."
)


@pytest.mark.parametrize("name", ["night_start", "night_end"])
def test_the_bounds_of_the_night_go_together(name: str) -> None:
    refused(complete_row, "night_start et night_end vont ensemble.", **{name: None})


@pytest.mark.parametrize(
    "state",
    [
        NightState.DECLARED,
        NightState.IN_PROGRESS,
        NightState.PARTIAL,
        NightState.COMPLETE,
    ],
)
def test_a_night_with_a_state_has_its_bounds(state: NightState) -> None:
    assert complete_row(night_state=state).night_state is state
    refused(no_night_row, NIGHT_STATE, night_state=state)


def test_a_missing_night_has_no_bounds() -> None:
    refused(complete_row, NIGHT_STATE, night_state=NightState.MISSING)


def test_the_night_starts_before_it_ends() -> None:
    end = complete_row().night_end
    assert end is not None
    message = "night_start doit précéder night_end."
    refused(complete_row, message, night_start=end)
    refused(complete_row, message, night_start=end + timedelta(seconds=1))
    assert complete_row(night_start=end - timedelta(microseconds=1))
    in_utc = (end - timedelta(hours=8)).astimezone(UTC)
    assert complete_row(night_start=in_utc, night_end=end)


@pytest.mark.parametrize(
    ("flag", "absence"),
    [
        ("night_short", "night_short_absence"),
        ("night_shifted", "night_shifted_absence"),
    ],
)
def test_a_night_flag_or_its_reason(flag: str, absence: str) -> None:
    message = f"{flag} et {absence} : l'un ou l'autre, jamais les deux."
    refused(complete_row, message, **{flag: None, absence: None})
    refused(complete_row, message, **{flag: True, absence: ViewAbsence.NO_NIGHT})
    for value in (True, False):
        row = complete_row(**{flag: value, absence: None})
        assert getattr(row, flag) is value
    row = complete_row(**{flag: None, absence: ViewAbsence.DISPERSED_MIDPOINTS})
    assert getattr(row, flag) is None


def test_the_body_battery_of_the_night() -> None:
    both = "night_body_battery_ceiling et night_body_battery_coverage vont ensemble."
    either = (
        "night_body_battery_coverage et night_body_battery_absence : l'un ou l'autre, "
        "jamais les deux."
    )
    below = ViewAbsence.BELOW_COVERAGE
    refused(complete_row, both, night_body_battery_ceiling=None)
    refused(
        complete_row,
        both,
        night_body_battery_coverage=None,
        night_body_battery_absence=below,
    )
    refused(complete_row, either, night_body_battery_absence=below)
    refused(
        complete_row,
        either,
        night_body_battery_ceiling=None,
        night_body_battery_coverage=None,
    )
    assert complete_row(
        night_body_battery_ceiling=None,
        night_body_battery_coverage=None,
        night_body_battery_absence=below,
    )
    assert complete_row(night_body_battery_ceiling=True)


def _no_quantity(name: str) -> str:
    return f"Sans nuit, aucune grandeur de la nuit : {name}."


@pytest.mark.parametrize(
    ("flag", "absence"),
    [
        ("night_short", "night_short_absence"),
        ("night_shifted", "night_shifted_absence"),
    ],
)
def test_without_a_night_no_flag(flag: str, absence: str) -> None:
    refused(no_night_row, _no_quantity(flag), **{flag: False, absence: None})


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("measured_sleep_s", 1.0),
        ("deep_s", 1.0),
        ("light_s", 1.0),
        ("rem_s", 1.0),
        ("awake_s", 1.0),
        ("unmeasurable_s", 1.0),
        ("unmeasured_fraction", 0.1),
        ("night_confirmation", "un texte"),
        ("night_window_confirmed", True),
        ("night_from_device", True),
        ("night_rem_capable", False),
        ("sleep_score", 1),
        ("night_avg_stress", 1.0),
        ("night_avg_heart_rate_bpm", 50.0),
        ("night_body_battery_change", 1),
        ("night_restless_moments", 1),
        ("skin_temperature_deviation_c", 0.1),
    ],
)
def test_without_a_night_no_quantity(name: str, value: object) -> None:
    changes: dict[str, Any] = {name: value}
    if name == "measured_sleep_s":
        changes.update(admitted_measure("measured_sleep", measured_sleep_s=1.0))
    if name == "night_avg_stress":
        changes.update(admitted_measure("night_stress", night_avg_stress=1.0))
    refused(no_night_row, _no_quantity(name), **changes)


def test_without_a_night_no_body_battery() -> None:
    refused(
        no_night_row,
        _no_quantity("night_body_battery_ceiling"),
        night_body_battery_ceiling=False,
        night_body_battery_coverage=0.9,
        night_body_battery_absence=None,
    )


@pytest.mark.parametrize(
    "name",
    ["night_short_absence", "night_shifted_absence", "night_body_battery_absence"],
)
def test_without_a_night_the_reasons_are_no_night(name: str) -> None:
    refused(
        no_night_row,
        f"Sans nuit, {name} vaut no_night.",
        **{name: ViewAbsence.BELOW_USUAL_MINIMUM},
    )
    assert getattr(no_night_row(), name) is ViewAbsence.NO_NIGHT


def test_a_day_without_a_night_keeps_the_other_families() -> None:
    row = no_night_row(
        respiration_avg_sleep_breaths_per_min=14.0,
        night_respiration_refusal=None,
        night_respiration_admitted=True,
    )
    assert row.respiration_avg_sleep_breaths_per_min == 14.0
    assert row.hrv_last_night_avg_ms == 55.0
    assert row.spo2_avg_sleep_percent == 95.0


# ------------------------------------------------------------------------------------
# Siestes, stress, Training Readiness, journal
# ------------------------------------------------------------------------------------


def test_the_naps() -> None:
    refused(
        complete_row,
        "naps_overlapping_night : au plus nap_count.",
        naps_overlapping_night=2,
    )
    assert complete_row(naps_overlapping_night=1)
    message = "Sans sieste, nap_window_s et nap_sleep_s sont nuls."
    refused(complete_row, message, nap_count=0, nap_window_s=1800.0, nap_sleep_s=0.0)
    refused(complete_row, message, nap_count=0, nap_window_s=0.0, nap_sleep_s=1500.0)
    assert complete_row(nap_count=0, nap_window_s=0.0, nap_sleep_s=0.0)
    assert complete_row(nap_sleep_s=0.0)


def test_the_validity_of_the_stress_needs_its_time() -> None:
    refused(
        complete_row,
        "stress_valid demande stress_measured_s.",
        stress_measured_s=None,
    )
    assert complete_row(stress_measured_s=None, stress_valid=None)
    assert complete_row(stress_valid=None).stress_measured_s == 60000.0
    assert complete_row(stress_valid=False).stress_valid is False


def test_the_readiness_of_waking() -> None:
    either = (
        "readiness_instant et readiness_absence : l'un ou l'autre, jamais les deux."
    )
    after = ViewAbsence.NO_ENTRY_AFTER_NIGHT
    refused(complete_row, either, readiness_instant=None)
    refused(complete_row, either, readiness_absence=after)
    needs = "readiness_score et readiness_level demandent readiness_instant."
    refused(
        complete_row,
        needs,
        readiness_instant=None,
        readiness_absence=after,
        readiness_level=None,
    )
    refused(
        complete_row,
        needs,
        readiness_instant=None,
        readiness_absence=after,
        readiness_score=None,
    )
    row = complete_row(
        readiness_instant=None,
        readiness_absence=after,
        readiness_score=None,
        readiness_level=None,
    )
    assert row.readiness_entry_count == 2
    assert complete_row(readiness_score=None, readiness_level=None)
    refused(
        complete_row,
        "readiness_instant demande readiness_entry_count >= 1.",
        readiness_entry_count=0,
    )
    assert complete_row(readiness_entry_count=1)


@pytest.mark.parametrize(
    "types",
    [
        (JournalEventType.TRAVEL, JournalEventType.RACE),
        (JournalEventType.RACE, JournalEventType.RACE),
    ],
)
def test_the_journal_types_are_sorted_without_duplicate(
    types: tuple[JournalEventType, ...],
) -> None:
    refused(
        complete_row, "journal_types doit être trié, sans doublon.", journal_types=types
    )


def test_journal_types_admitted() -> None:
    assert complete_row(journal_types=()).journal_types == ()
    types = tuple(sorted(JournalEventType, key=lambda m: m.value))
    assert [m.value for m in types] == [
        "autre",
        "blessure",
        "course",
        "demenagement",
        "deplacement",
        "etalon",
        "maladie",
        "sejour_altitude",
    ]
    assert complete_row(journal_types=types).journal_types == types


# ------------------------------------------------------------------------------------
# L'activité du jour
# ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["activities_without_load", "other_activity_count", "activities_without_elapsed"],
)
def test_activity_counts_are_at_most_the_activities(name: str) -> None:
    refused(complete_row, f"{name} : au plus activity_count.", **{name: 4})
    extra: dict[str, Any] = (
        {"garmin_training_load": None} if name == "activities_without_load" else {}
    )
    assert getattr(complete_row(**{name: 3}, **extra), name) == 3


LOAD = (
    "garmin_training_load : absente si et seulement si le jour a des activités, toutes "
    "sans charge."
)


def test_the_load_is_missing_only_when_all_activities_have_none() -> None:
    refused(complete_row, LOAD, activities_without_load=3)
    refused(complete_row, LOAD, garmin_training_load=None)
    refused(absent_row, LOAD, garmin_training_load=None)
    assert complete_row(activities_without_load=3, garmin_training_load=None)
    assert complete_row(garmin_training_load=0.0).garmin_training_load == 0.0


@pytest.mark.parametrize(
    "name",
    [
        "garmin_training_load",
        "foot_elapsed_s",
        "mtb_elapsed_s",
        "ski_touring_elapsed_s",
        "other_elapsed_s",
    ],
)
def test_without_activity_the_load_and_durations_are_zero(name: str) -> None:
    refused(
        absent_row,
        "Sans activité, garmin_training_load et les durées sont nulles.",
        **{name: 1.0},
    )
    assert getattr(absent_row(), name) == 0.0


# ------------------------------------------------------------------------------------
# Les normales
# ------------------------------------------------------------------------------------


@pytest.mark.parametrize("measure", MEASURE_NAMES)
def test_admitted_if_and_only_if_no_refusal(measure: str) -> None:
    admitted, refusal = f"{measure}_admitted", f"{measure}_refusal"
    assert getattr(complete_row(**admitted_measure(measure)), admitted) is True
    message = f"{admitted} : vrai si et seulement si {refusal} est absent."
    refused(
        complete_row,
        message,
        **admitted_measure(measure, **{refusal: AdmissionRefusal.ILLNESS}),
    )
    refused(complete_row, message, **admitted_measure(measure, **{admitted: False}))
    row = complete_row(
        **admitted_measure(
            measure, **{admitted: False, refusal: AdmissionRefusal.INJURY}
        )
    )
    assert getattr(row, refusal) is AdmissionRefusal.INJURY


@pytest.mark.parametrize("measure", MEASURE_NAMES)
def test_absent_row_is_the_reason_of_absent_rows_only(measure: str) -> None:
    admitted, refusal = f"{measure}_admitted", f"{measure}_refusal"
    message = f"{refusal} vaut absent_row si et seulement si state est absent."
    refused(
        complete_row,
        message,
        **admitted_measure(
            measure, **{admitted: False, refusal: AdmissionRefusal.ABSENT_ROW}
        ),
    )
    refused(absent_row, message, **{refusal: AdmissionRefusal.NO_VALUE})
    assert getattr(absent_row(), refusal) is AdmissionRefusal.ABSENT_ROW


@pytest.mark.parametrize("measure", MEASURE_NAMES)
def test_an_admitted_value_is_there(measure: str) -> None:
    admitted, refusal = f"{measure}_admitted", f"{measure}_refusal"
    column = VALUE_COLUMN[measure]
    extra: dict[str, Any] = (
        {"resting_hr_status": RestingHrStatus.ABSENT} if measure == "resting_hr" else {}
    )
    refused(
        complete_row,
        f"{admitted} : une valeur admise ({column}) est là.",
        **admitted_measure(measure, **{column: None}, **extra),
    )
    assert complete_row(
        **admitted_measure(
            measure,
            **{column: None, admitted: False, refusal: AdmissionRefusal.NO_VALUE},
            **extra,
        )
    )


@pytest.mark.parametrize("measure", MEASURE_NAMES)
def test_the_normal_its_range_and_dispersion_go_together(measure: str) -> None:
    group = group_of(measure)
    message = f"{', '.join(group)} vont ensemble."
    for name in group[1:]:
        refused(complete_row, message, **admitted_measure(measure, **{name: None}))
    refused(
        complete_row,
        message,
        **admitted_measure(measure, **dict.fromkeys(group[1:])),
    )


@pytest.mark.parametrize("measure", MEASURE_NAMES)
def test_a_normal_or_its_reason(measure: str) -> None:
    absence = f"{measure}_normal_absence"
    too_few = NormalAbsence.TOO_FEW_ADMITTED_DAYS
    message = f"{normal_of(measure)} et {absence} : l'un ou l'autre, jamais les deux."
    refused(complete_row, message, **admitted_measure(measure, **{absence: too_few}))
    refused(complete_row, message, **without_group(measure))
    assert complete_row(**without_group(measure, **{absence: too_few}))


@pytest.mark.parametrize("measure", MEASURE_NAMES)
def test_no_admitted_day_if_and_only_if_no_day_is_admitted(measure: str) -> None:
    absence, days = f"{measure}_normal_absence", f"{measure}_admitted_days"
    none, few = NormalAbsence.NO_ADMITTED_DAY, NormalAbsence.TOO_FEW_ADMITTED_DAYS
    message = f"{absence} vaut no_admitted_day si et seulement si {days} est nul."
    refused(
        complete_row, message, **without_group(measure, **{absence: none, days: 14})
    )
    refused(complete_row, message, **without_group(measure, **{absence: few, days: 0}))
    refused(complete_row, message, **admitted_measure(measure, **{days: 0}))
    assert complete_row(**without_group(measure, **{absence: none, days: 0}))
    assert complete_row(**without_group(measure, **{absence: few, days: 1}))


LINEAR_MEASURES = [name for name in MEASURE_NAMES if name != "hrv"]


@pytest.mark.parametrize("measure", LINEAR_MEASURES)
def test_the_range_holds_the_normal(measure: str) -> None:
    low, normal, high = low_of(measure), normal_of(measure), high_of(measure)
    message = f"Il faut {low} <= {normal} <= {high}."
    refused(complete_row, message, **admitted_measure(measure, **{low: 40.5}))
    refused(complete_row, message, **admitted_measure(measure, **{high: 39.5}))
    assert complete_row(**admitted_measure(measure, **{low: 40.0, high: 40.0}))


def test_the_range_holds_the_normal_of_the_hrv() -> None:
    message = "Il faut hrv_range_low_ms <= hrv_normal_ms <= hrv_range_high_ms."
    refused(complete_row, message, **admitted_measure("hrv", hrv_range_low_ms=60.0))
    refused(complete_row, message, **admitted_measure("hrv", hrv_range_high_ms=50.0))
    assert complete_row(
        **admitted_measure(
            "hrv", hrv_range_low_ms=LOG_CENTER, hrv_range_high_ms=LOG_CENTER
        )
    )


def test_the_normal_of_the_hrv_is_the_exponential_of_its_log_median() -> None:
    message = "hrv_normal_ms doit valoir exp(hrv_log_median)."
    refused(
        complete_row,
        message,
        **admitted_measure(
            "hrv", hrv_normal_ms=LOG_CENTER * 1.001, hrv_range_high_ms=1000.0
        ),
    )
    refused(complete_row, message, **admitted_measure("hrv", hrv_log_median=4.0001))
    refused(complete_row, message, **admitted_measure("hrv", hrv_log_median=1000.0))
    assert complete_row(
        **admitted_measure("hrv", hrv_normal_ms=LOG_CENTER * (1 + 1e-12))
    )


def test_the_tolerance_on_the_normal_of_the_hrv() -> None:
    refused(
        complete_row,
        "hrv_normal_ms doit valoir exp(hrv_log_median).",
        **admitted_measure("hrv", hrv_normal_ms=LOG_CENTER * (1 + 1e-7)),
    )
    assert complete_row(
        **admitted_measure("hrv", hrv_normal_ms=LOG_CENTER * (1 + 1e-11))
    )


def test_a_row_may_carry_a_normal_without_a_value() -> None:
    row = complete_row()
    assert row.respiration_avg_sleep_breaths_per_min is None
    assert row.night_respiration_refusal is AdmissionRefusal.NO_VALUE
    assert row.night_respiration_normal_breaths_per_min == 14.0


# ------------------------------------------------------------------------------------
# La ligne absent
# ------------------------------------------------------------------------------------


def test_an_absent_row_may_carry_status_journal_activity_and_normal() -> None:
    instant = datetime(2000, 1, 5, 19, tzinfo=PLUS1)
    row = absent_row(
        ts_status_instant=instant,
        ts_status_code=3,
        ts_acute_load=100.0,
        journal_types=(JournalEventType.ILLNESS,),
        activity_count=1,
        garmin_training_load=20.0,
        foot_elapsed_s=1800.0,
        uncertain_device=True,
        resting_hr_normal_bpm=50.0,
        resting_hr_range_low_bpm=49.0,
        resting_hr_range_high_bpm=51.0,
        resting_hr_dispersion_bpm=1.0,
        resting_hr_admitted_days=14,
        resting_hr_normal_absence=None,
        resting_hr_segment=3,
        resting_hr_normal_straddles=True,
    )
    assert row.resting_hr_refusal is AdmissionRefusal.ABSENT_ROW
    assert row.resting_hr_normal_bpm == 50.0
    assert row.ts_status_instant == instant


def test_an_absent_row_has_no_rank_nor_version() -> None:
    refused(
        absent_row,
        "Une ligne absent n'a pas de rang : device_ranks vide.",
        device_ranks=(1,),
    )
    refused(
        absent_row,
        "Une ligne absent n'a pas de version : body_battery_series_versions vide.",
        body_battery_series_versions=(1,),
    )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("sleep_version", 1),
        ("sleep_respiration_version", 1),
        ("respiration_version", 1),
        ("summary_respiration_version", 1),
        ("summary_body_battery_version", 1),
        ("resting_hr_bpm", 48.0),
        ("hrv_last_night_avg_ms", 1.0),
        ("hrv_last_night_5min_high_ms", 1.0),
        ("hrv_weekly_avg_ms", 1.0),
        ("hrv_baseline_balanced_low_ms", 1.0),
        ("hrv_baseline_balanced_upper_ms", 1.0),
        ("hrv_baseline_low_upper_ms", 1.0),
        ("hrv_baseline_marker_value", 1.0),
        ("hrv_status", "X"),
        ("respiration_avg_sleep_breaths_per_min", 1.0),
        ("respiration_avg_waking_breaths_per_min", 1.0),
        ("spo2_avg_sleep_percent", 1.0),
        ("spo2_average_percent", 1.0),
        ("spo2_lowest_percent", 1.0),
        ("stress_average_level", 1),
        ("stress_max_level", 1),
        ("stress_measured_s", 1.0),
        ("body_battery_charged", 1),
        ("body_battery_drained", 1),
        ("body_battery_highest", 1),
        ("body_battery_lowest", 1),
        ("body_battery_at_wake", 1),
        ("body_battery_during_sleep", 1),
        ("steps", 1),
        ("moderate_intensity_s", 1.0),
        ("vigorous_intensity_s", 1.0),
        ("floors_ascended_m", 1.0),
        ("floors_descended_m", 1.0),
        ("average_altitude_m", 1.0),
    ],
)
def test_an_absent_row_has_no_value_of_the_day(name: str, value: object) -> None:
    refused(
        absent_row,
        f"Une ligne absent n'a ni version ni valeur du jour : {name}.",
        **{name: value},
    )


def test_an_absent_row_has_no_stress_time_nor_validity() -> None:
    refused(
        absent_row,
        "Une ligne absent n'a ni version ni valeur du jour : stress_measured_s.",
        stress_measured_s=1.0,
        stress_valid=False,
    )


def test_an_absent_row_has_no_night_nap_status_nor_readiness() -> None:
    complete = complete_row()
    refused(
        absent_row,
        "Une ligne absent n'a pas de nuit : night_state missing.",
        night_state=NightState.DECLARED,
        night_start=complete.night_start,
        night_end=complete.night_end,
    )
    refused(
        absent_row,
        "Une ligne absent n'a pas de sieste : nap_count nul.",
        nap_count=1,
        nap_window_s=60.0,
    )
    refused(
        absent_row,
        "Une ligne absent : resting_hr_status vaut absent.",
        resting_hr_status=RestingHrStatus.NO_NIGHT,
    )
    refused(
        absent_row,
        "Une ligne absent n'a pas d'entrée de Training Readiness : "
        "readiness_entry_count nul.",
        readiness_entry_count=1,
    )


def test_the_day_is_a_date() -> None:
    assert type(absent_row().day) is date
    assert complete_row(day=date(2000, 2, 29)).day == date(2000, 2, 29)


# ------------------------------------------------------------------------------------
# L'ordre des contrôles
# ------------------------------------------------------------------------------------


def test_the_instants_are_checked_before_the_numbers() -> None:
    naive = _instant_of("window_start").replace(tzinfo=None)
    refused(
        complete_row,
        f"window_start doit porter un fuseau horaire, reçu {naive!r}.",
        window_start=naive,
        deep_s=math.nan,
    )


NO_DATA_END = "window_start et data_end vont ensemble."
NO_NIGHT_END = "night_start et night_end vont ensemble."
TOO_MANY_NAPS = "naps_overlapping_night : au plus nap_count."
TOO_MANY_WITHOUT_LOAD = "activities_without_load : au plus activity_count."
HRV_ADMITTED = "hrv_admitted : vrai si et seulement si hrv_refusal est absent."


@pytest.mark.parametrize(
    ("build", "message", "changes"),
    [
        (complete_row, NO_DATA_END, {"data_end": None, "night_end": None}),
        (
            complete_row,
            NO_NIGHT_END,
            {"night_end": None, "naps_overlapping_night": 2},
        ),
        (
            complete_row,
            TOO_MANY_NAPS,
            {"naps_overlapping_night": 2, "activities_without_load": 4},
        ),
        (
            complete_row,
            TOO_MANY_WITHOUT_LOAD,
            {"activities_without_load": 4, "hrv_admitted": False},
        ),
        (absent_row, HRV_ADMITTED, {"hrv_admitted": True, "device_ranks": (1,)}),
    ],
    ids=["5 et 6", "6 et 7", "7 et 8", "8 et 9", "9 et 10"],
)
def test_two_consecutive_groups_give_the_message_of_the_first(
    build: Row, message: str, changes: dict[str, Any]
) -> None:
    refused(build, message, **changes)


def _flipped(measure: str) -> dict[str, bool]:
    """Le ``<p>_admitted`` qui contredit ``<p>_refusal`` de la ligne ``complete``."""
    name = f"{measure}_admitted"
    return {name: not getattr(complete_row(), name)}


@pytest.mark.parametrize(
    ("first", "second"),
    list(pairwise(MEASURE_NAMES)),
)
def test_two_consecutive_measures_give_the_message_of_the_first(
    first: str, second: str
) -> None:
    refused(
        complete_row,
        f"{first}_admitted : vrai si et seulement si {first}_refusal est absent.",
        **_flipped(first),
        **_flipped(second),
    )
