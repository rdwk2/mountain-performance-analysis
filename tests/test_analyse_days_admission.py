"""L'admission par mesure, et les normales sur les lignes de la table (AN2-2) : vingt
documents complets du 1er au 20 janvier 2000 ; sauf mention, le dernier a des champs
changés, et l'on lit sa ligne."""

from __future__ import annotations

import dataclasses
import math
from datetime import timedelta
from typing import Any

import pytest

from fixtures.day_rows import complete_row
from fixtures.day_table import (
    complete_days,
    days_with,
    definition,
    jan,
    journal_of,
    row_of,
    table,
)
from fixtures.days import (
    at,
    day_record,
    hrv_summary,
    night,
    respiration_summary,
    spo2_summary,
    truncated_day,
    versions,
)
from mountain_perf.analyse.days import (
    SHORT_NIGHT_ADMITTED,
    VALUE_COLUMNS,
    admission_refusal,
)
from mountain_perf.analyse.normals import NormalMeasure
from mountain_perf.schemas import (
    JournalEventType,
    NightState,
    RestingHrStatus,
)
from mountain_perf.schemas.processed import (
    AdmissionRefusal,
    DayRow,
    DayRowState,
    NormalAbsence,
)

SIX = list(NormalMeasure)
NIGHT_FIVE = [m for m in SIX if m is not NormalMeasure.RESTING_HR]
HRV, HR = NormalMeasure.HRV, NormalMeasure.RESTING_HR
SLEEP = NormalMeasure.MEASURED_SLEEP
STRESS = NormalMeasure.NIGHT_STRESS
ILLNESS = JournalEventType.ILLNESS
INJURY = JournalEventType.INJURY
ALTITUDE = JournalEventType.ALTITUDE_STAY
R = AdmissionRefusal
J20 = jan(20)


def refusal(row: DayRow, measure: NormalMeasure) -> AdmissionRefusal | None:
    value = getattr(row, f"{measure.value}_refusal")
    assert isinstance(value, AdmissionRefusal | None)
    assert getattr(row, f"{measure.value}_admitted") is (value is None)
    return value


def last(journal: Any = None, parameters: Any = None, **changes: Any) -> DayRow:
    """La ligne du 20 janvier, son document aux champs changés."""
    kwargs: dict[str, Any] = {}
    if journal is not None:
        kwargs["journal"] = journal
    if parameters is not None:
        kwargs["day_definition"] = parameters
    return row_of(table(days_with(20, 19, **changes), **kwargs), J20)


def _sleep(deep: float | None, light: float, rem: float) -> dict[str, Any]:
    return {"deep_s": deep, "light_s": light, "rem_s": rem}


SHORT = _sleep(3600, 7200, 3599)


def shifted(**changes: Any) -> Any:
    return night(
        J20,
        start=at(jan(19), 23) + timedelta(hours=6),
        end=at(J20, 7) + timedelta(hours=6),
        **changes,
    )


def day(event: JournalEventType) -> Any:
    return (J20, J20, event)


def test_a_complete_day_is_admitted_everywhere() -> None:
    row = last()
    assert all(refusal(row, m) is None for m in SIX)


def test_absent_row() -> None:
    result = table(
        complete_days(3, skip=(1,)), journal=journal_of((jan(2), jan(2), ILLNESS))
    )
    row = row_of(result, jan(2))
    assert all(refusal(row, m) is R.ABSENT_ROW for m in SIX)


@pytest.mark.parametrize(
    ("measure", "changes"),
    [
        (HRV, {"hrv": hrv_summary(J20, last_night_avg_ms=None)}),
        (HR, {"resting_hr": None}),
        (SLEEP, {"night": night(J20, deep_s=None)}),
        (STRESS, {"night": night(J20, avg_stress=None)}),
        (
            NormalMeasure.NIGHT_RESPIRATION,
            {"respiration": respiration_summary(J20, avg_sleep_breaths_per_min=None)},
        ),
        (
            NormalMeasure.NIGHT_SPO2,
            {"spo2": spo2_summary(J20, avg_sleep_spo2_percent=None)},
        ),
    ],
)
def test_no_value(measure: NormalMeasure, changes: dict[str, Any]) -> None:
    row = last(**changes)
    assert getattr(row, VALUE_COLUMNS[measure]) is None
    assert refusal(row, measure) is R.NO_VALUE


def test_without_a_night() -> None:
    row = last(night=None)
    assert refusal(row, SLEEP) is R.NO_VALUE
    assert refusal(row, STRESS) is R.NO_VALUE
    for measure in (HRV, NormalMeasure.NIGHT_RESPIRATION, NormalMeasure.NIGHT_SPO2):
        assert refusal(row, measure) is R.NIGHT_NOT_COMPLETE
    assert refusal(row, HR) is R.INVALID_VALUE


def test_invalid_value_of_the_resting_heart_rate() -> None:
    documents = [*complete_days(19), truncated_day(J20)]
    row = row_of(table(documents), J20)
    assert row.resting_hr_bpm == 48.0
    assert row.resting_hr_status is RestingHrStatus.PROVISIONAL
    assert refusal(row, HR) is R.INVALID_VALUE
    row = last(night=night(J20, **_sleep(3600, 3600, 0)))
    assert row.resting_hr_status is RestingHrStatus.NO_NIGHT
    assert refusal(row, HR) is R.INVALID_VALUE
    assert row.resting_hr_bpm == 48.0


def test_a_null_hrv_is_invalid() -> None:
    result = table(days_with(20, 3, hrv=hrv_summary(jan(4), last_night_avg_ms=0.0)))
    row = row_of(result, jan(4))
    assert row.hrv_last_night_avg_ms == 0.0
    assert refusal(row, HRV) is R.INVALID_VALUE
    assert row_of(result, J20).hrv_admitted_days == 18
    small = table(days_with(20, 3, hrv=hrv_summary(jan(4), last_night_avg_ms=0.5)))
    assert refusal(row_of(small, jan(4)), HRV) is None


def test_a_partial_night() -> None:
    row = last(night=night(J20, unmeasurable_s=10000.0))
    assert all(refusal(row, m) is R.NIGHT_NOT_COMPLETE for m in NIGHT_FIVE)
    assert refusal(row, HR) is None


@pytest.mark.parametrize(
    "changes", [{"from_device": False}, {"window_confirmed": False}]
)
def test_a_declared_or_in_progress_night(changes: dict[str, Any]) -> None:
    assert refusal(last(night=night(J20, **changes)), HRV) is R.NIGHT_NOT_COMPLETE


def test_a_short_night() -> None:
    assert frozenset({SLEEP}) == SHORT_NIGHT_ADMITTED
    row = last(night=night(J20, **SHORT))
    assert row.night_short is True
    assert refusal(row, SLEEP) is None
    for measure in NIGHT_FIVE:
        if measure is not SLEEP:
            assert refusal(row, measure) is R.SHORT_NIGHT
    assert refusal(row, HR) is None


def test_a_shifted_night() -> None:
    row = last(night=shifted())
    assert row.night_shifted is True
    assert all(refusal(row, m) is R.SHIFTED_NIGHT for m in NIGHT_FIVE)
    assert refusal(row, HR) is None


def test_an_unknown_flag_does_not_exclude() -> None:
    row = row_of(table(complete_days(20)), jan(3))
    assert row.night_shifted is None
    assert row.night_shifted_absence is not None
    assert all(refusal(row, m) is None for m in SIX)
    row = last(night=night(J20, deep_s=None))
    assert row.night_short is None
    assert refusal(row, SLEEP) is R.NO_VALUE
    for measure in NIGHT_FIVE:
        if measure is not SLEEP:
            assert refusal(row, measure) is None


@pytest.mark.parametrize(
    ("event", "expected"),
    [(ILLNESS, R.ILLNESS), (INJURY, R.INJURY), (ALTITUDE, R.ALTITUDE_STAY)],
)
def test_the_journal(event: JournalEventType, expected: AdmissionRefusal) -> None:
    row = last(journal=journal_of(day(event)))
    assert all(refusal(row, m) is expected for m in SIX)


@pytest.mark.parametrize(
    "event",
    [
        JournalEventType.RACE,
        JournalEventType.TRAVEL,
        JournalEventType.MOVE,
        JournalEventType.BENCHMARK,
        JournalEventType.OTHER,
    ],
)
def test_the_other_events_exclude_nothing(event: JournalEventType) -> None:
    row = last(journal=journal_of(day(event)))
    assert row.journal_types == (event,)
    assert all(refusal(row, m) is None for m in SIX)


def test_the_switch_of_the_altitude_stay() -> None:
    off = definition(normals={"exclude_altitude_stay": 0})
    row = last(journal=journal_of(day(ALTITUDE)), parameters=off)
    assert row.journal_types == (ALTITUDE,)
    assert all(refusal(row, m) is None for m in SIX)
    row = last(journal=journal_of(day(ALTITUDE), day(ILLNESS)), parameters=off)
    assert all(refusal(row, m) is R.ILLNESS for m in SIX)


def test_the_first_reason_is_the_one_carried() -> None:
    no_hrv = hrv_summary(J20, last_night_avg_ms=None)
    zero = hrv_summary(J20, last_night_avg_ms=0.0)
    assert refusal(last(hrv=no_hrv, night=night(J20, **SHORT)), HRV) is R.NO_VALUE
    assert refusal(last(hrv=zero, night=night(J20, **SHORT)), HRV) is R.INVALID_VALUE
    partial = night(J20, unmeasurable_s=10000.0, rem_s=0.0)
    assert (
        refusal(last(journal=journal_of(day(ILLNESS)), night=partial), HRV)
        is R.NIGHT_NOT_COMPLETE
    )
    both = last(night=shifted(**SHORT))
    assert refusal(both, HRV) is R.SHORT_NIGHT
    assert refusal(both, SLEEP) is R.SHIFTED_NIGHT
    assert (
        refusal(last(journal=journal_of(day(ILLNESS)), night=shifted()), HRV)
        is R.SHIFTED_NIGHT
    )
    three = journal_of(day(INJURY), day(ILLNESS), day(ALTITUDE))
    assert refusal(last(journal=three), HRV) is R.ILLNESS
    two = journal_of(day(ALTITUDE), day(INJURY))
    assert refusal(last(journal=two), HRV) is R.INJURY
    documents = [*complete_days(19), truncated_day(J20)]
    result = table(documents, journal=journal_of(day(ILLNESS)))
    assert refusal(row_of(result, J20), HR) is R.INVALID_VALUE


def _columns(**changes: Any) -> dict[str, Any]:
    row = complete_row(
        hrv_admitted=True,
        hrv_refusal=None,
        respiration_avg_sleep_breaths_per_min=14.0,
        night_respiration_admitted=True,
        night_respiration_refusal=None,
        night_short=False,
        night_shifted=False,
        night_shifted_absence=None,
        journal_types=(),
    )
    columns = {f.name: getattr(row, f.name) for f in dataclasses.fields(row)}
    return {**columns, **changes}


TRIGGERS: list[tuple[AdmissionRefusal, dict[str, Any]]] = [
    (R.ABSENT_ROW, {"state": DayRowState.ABSENT}),
    (R.NO_VALUE, {"hrv_last_night_avg_ms": None, "resting_hr_bpm": None}),
    (
        R.INVALID_VALUE,
        {
            "hrv_last_night_avg_ms": 0.0,
            "resting_hr_status": RestingHrStatus.NO_NIGHT,
        },
    ),
    (R.NIGHT_NOT_COMPLETE, {"night_state": NightState.PARTIAL}),
    (R.SHORT_NIGHT, {"night_short": True}),
    (R.SHIFTED_NIGHT, {"night_shifted": True}),
]


def _with_triggers(reason: AdmissionRefusal) -> dict[str, Any]:
    """Les colonnes qui déclenchent ``reason`` et tous les motifs qui le suivent ; une
    colonne déjà changée par un motif antérieur garde la valeur de celui-ci."""
    order = list(AdmissionRefusal)
    columns: dict[str, Any] = {}
    types: list[JournalEventType] = []
    for later in reversed(order[order.index(reason) :]):
        if later is R.ILLNESS:
            types.append(ILLNESS)
        elif later is R.INJURY:
            types.append(INJURY)
        elif later is R.ALTITUDE_STAY:
            types.append(ALTITUDE)
        else:
            columns.update(dict(TRIGGERS)[later])
    return {**columns, "journal_types": tuple(sorted(set(types)))}


def test_the_order_of_the_reasons() -> None:
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


@pytest.mark.parametrize("reason", list(AdmissionRefusal))
def test_each_reason_with_all_those_that_follow_it(reason: AdmissionRefusal) -> None:
    columns = _columns(**_with_triggers(reason))
    assert admission_refusal(HRV, columns, exclude_altitude_stay=True) is reason


@pytest.mark.parametrize("measure", SIX)
def test_the_rule_of_each_measure_reads_its_own_value(measure: NormalMeasure) -> None:
    columns = _columns(**{VALUE_COLUMNS[measure]: None})
    for other in SIX:
        expected = R.NO_VALUE if other is measure else None
        assert admission_refusal(other, columns, exclude_altitude_stay=True) is expected


def test_the_resting_heart_rate_ignores_the_night() -> None:
    columns = _columns(
        night_state=NightState.PARTIAL, night_short=True, night_shifted=True
    )
    assert admission_refusal(HR, columns, exclude_altitude_stay=True) is None


def test_the_switch_of_admission_refusal() -> None:
    columns = _columns(journal_types=(ALTITUDE,))
    assert admission_refusal(HRV, columns, exclude_altitude_stay=False) is None
    assert (
        admission_refusal(HRV, columns, exclude_altitude_stay=True) is R.ALTITUDE_STAY
    )


def test_the_normals_on_the_table_of_twenty_days() -> None:
    result = table(complete_days(20))
    assert row_of(result, jan(1)).hrv_normal_absence is NormalAbsence.NO_ADMITTED_DAY
    d14 = row_of(result, jan(14))
    assert d14.hrv_normal_absence is NormalAbsence.TOO_FEW_ADMITTED_DAYS
    assert d14.hrv_admitted_days == 13
    d15 = row_of(result, jan(15))
    assert d15.hrv_admitted_days == 14
    assert d15.hrv_normal_ms == pytest.approx(50, rel=1e-6)
    assert d15.hrv_log_median == pytest.approx(math.log(50), rel=1e-6)
    assert d15.hrv_log_dispersion == pytest.approx(math.log(1 + 1 / 50), rel=1e-6)
    assert d15.resting_hr_normal_bpm == 48.0
    assert (d15.resting_hr_range_low_bpm, d15.resting_hr_range_high_bpm) == (47.0, 49.0)
    assert d15.resting_hr_dispersion_bpm == 1.0
    assert d15.measured_sleep_normal_s == 25200.0
    assert d15.measured_sleep_dispersion_s == 60.0
    assert d15.night_stress_normal == 12.0
    assert d15.night_respiration_normal_breaths_per_min == 13.0
    assert d15.night_spo2_normal_percent == 95.0
    assert d15.night_spo2_admitted_days == 14
    assert [row.hrv_segment for row in result.rows] == [*range(15), *([14] * 5)]


def test_the_journal_takes_days_out_of_the_normal() -> None:
    hrvs = [50.0, 80.0, 80.0, 80.0, 50.0, 50.0]
    documents = [
        day_record(jan(i + 1), hrv=hrv_summary(jan(i + 1), last_night_avg_ms=value))
        for i, value in enumerate(hrvs)
    ]
    two = definition(normals={"min_admitted_days": 2})
    result = table(
        documents,
        journal=journal_of((jan(2), jan(4), ILLNESS)),
        day_definition=two,
    )
    assert row_of(result, jan(3)).hrv_last_night_avg_ms == 80.0
    assert row_of(result, jan(3)).hrv_admitted is False
    sixth = row_of(result, jan(6))
    assert sixth.hrv_admitted_days == 2
    assert sixth.hrv_normal_ms == pytest.approx(50, rel=1e-6)
    free = row_of(table(documents, day_definition=two), jan(6))
    assert free.hrv_admitted_days == 5
    assert free.hrv_normal_ms == pytest.approx(80, rel=1e-6)


def test_an_absent_row_carries_its_normal() -> None:
    result = table(complete_days(20, skip=(16,)))
    row = row_of(result, jan(17))
    assert row.state is DayRowState.ABSENT
    assert row.hrv_normal_ms == pytest.approx(50, rel=1e-6)
    assert row_of(result, jan(18)).hrv_admitted_days == 16


def test_the_parameters_reach_the_normals() -> None:
    chosen = definition(normals={"min_admitted_days": 2, "window_days": 3})
    result = table(complete_days(20), day_definition=chosen)
    assert row_of(result, jan(3)).hrv_normal_ms == pytest.approx(50, rel=1e-6)
    assert row_of(result, J20).hrv_admitted_days == 3


def test_a_watch_change_on_the_table() -> None:
    documents = [
        day_record(
            jan(d),
            device_ranks=(1,) if d <= 10 else (1, 2) if d == 11 else (2,),
        )
        for d in range(1, 21)
    ]
    result = table(documents)
    for measure in SIX:
        name = measure.value
        assert getattr(row_of(result, jan(10)), f"{name}_rupture") is False
        assert getattr(row_of(result, jan(11)), f"{name}_rupture") is True
        assert getattr(row_of(result, jan(12)), f"{name}_rupture") is False
        assert getattr(row_of(result, jan(13)), f"{name}_normal_straddles") is True
    flags = [row_of(result, jan(d)).uncertain_device for d in (10, 11, 12)]
    assert flags == [False, True, False]


def _versioned(**changes: Any) -> Any:
    return table(
        [
            day_record(jan(d), versions=versions(**(changes if d >= 11 else {})))
            for d in range(1, 21)
        ]
    )


def test_a_version_on_the_table() -> None:
    sleep = row_of(_versioned(sleep_version=3), jan(11))
    assert sleep.measured_sleep_rupture is True
    assert sleep.night_stress_rupture is True
    assert sleep.hrv_rupture is False
    assert sleep.resting_hr_rupture is False
    assert sleep.night_respiration_rupture is False
    assert sleep.night_spo2_rupture is False
    breath = row_of(_versioned(respiration_version=201), jan(11))
    assert breath.night_respiration_rupture is True
    assert breath.measured_sleep_rupture is False
    assert breath.night_stress_rupture is False


def test_a_rupture_of_version_excludes_nothing() -> None:
    result = _versioned(sleep_version=3)
    assert row_of(result, jan(11)).measured_sleep_admitted is True
    assert row_of(result, J20).measured_sleep_admitted_days == 19


@pytest.mark.parametrize("measure", SIX)
def test_the_columns_of_value(measure: NormalMeasure) -> None:
    assert VALUE_COLUMNS[measure] in DayRow.__dataclass_fields__
    assert f"{measure.value}_admitted" in DayRow.__dataclass_fields__


def test_each_measure_reads_its_value() -> None:
    row = last(
        hrv=hrv_summary(J20, last_night_avg_ms=41.0, weekly_avg_ms=42.0),
        respiration=respiration_summary(
            J20, avg_sleep_breaths_per_min=11.0, avg_waking_breaths_per_min=16.0
        ),
        spo2=spo2_summary(J20, avg_sleep_spo2_percent=93.0, average_spo2_percent=97.0),
        night=night(J20, avg_stress=17.0),
    )
    assert row.hrv_last_night_avg_ms == 41.0
    assert row.respiration_avg_sleep_breaths_per_min == 11.0
    assert row.spo2_avg_sleep_percent == 93.0
    assert row.night_avg_stress == 17.0
    assert row.measured_sleep_s == 25200.0
    assert row.resting_hr_bpm == 48.0
