"""La lecture des familles, point par point (``ingest/families.py``) : chaque code connu
et un inconnu, chaque borne de plage des deux côtés (la valeur à la borne gardée, la
voisine écartée), l'ordre des écarts, les segments, la nuit, les siestes, la fenêtre du
jour, les valeurs d'un résumé hors de leur plage."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from fixtures.days import DAY, at, ms, wall_ms
from fixtures.families import (
    DOCUMENTS,
    NIGHT_START,
    START,
    _set,
    body_battery_document,
    daily_summary_document,
    gmt_text,
    heart_rate_document,
    hrv_document,
    local_text,
    read,
    readiness_entry,
    respiration_document,
    sleep_document,
    spo2_document,
    stress_document,
)
from mountain_perf.ingest.families import (
    BODY_BATTERY_LEVEL_RANGE,
    BODY_BATTERY_STATUS_CODES,
    CONFIRMATION_TYPES,
    HRV_RANGE_MS,
    READINESS_CONTEXTS,
    RESPIRATION_RANGE_BREATHS_PER_MIN,
    RESPIRATION_SENTINEL_CODES,
    SKIN_TEMPERATURE_DEVIATION_RANGE_C,
    SLEEP_STAGE_CODES,
    SPO2_RANGE_PERCENT,
    STRESS_LEVEL_RANGE,
    STRESS_SENTINEL_CODES,
    FamilyRead,
)
from mountain_perf.schemas import (
    HEART_RATE_RANGE_BPM,
    WAKING_CONTEXT,
    BodyBatteryStatus,
    DayFamily,
    DayFileRefusal,
    PointDiscard,
    SleepStage,
)

SPEC_STAGES = {
    0: SleepStage.DEEP,
    1: SleepStage.LIGHT,
    2: SleepStage.REM,
    3: SleepStage.AWAKE,
    -1: SleepStage.UNMEASURABLE,
}
SPEC_SENTINELS = (-2, -1)
SPEC_BODY_BATTERY_STATUSES = {
    "MEASURED": BodyBatteryStatus.MEASURED,
    "MODELED": BodyBatteryStatus.MODELED,
    "RESET": BodyBatteryStatus.RESET,
}
SPEC_CONTEXTS = (
    "AFTER_POST_EXERCISE_RESET",
    "AFTER_WAKEUP_RESET",
    "UPDATE_REALTIME_VARIABLES",
)
SPEC_CONFIRMATIONS = ("enhanced_confirmed_final", "manually_confirmed")


def _discards(result: FamilyRead) -> dict[tuple[str, PointDiscard], int]:
    return {(d.series_path, d.reason): d.count for d in result.discards}


def _codes(result: FamilyRead) -> list[tuple[str, str, int]]:
    return [(c.field_path, c.code, c.count) for c in result.unknown_codes]


def _segment(start_min: int, end_min: int, level: Any) -> dict[str, Any]:
    return {
        "startGMT": gmt_text(NIGHT_START + timedelta(minutes=start_min)),
        "endGMT": gmt_text(NIGHT_START + timedelta(minutes=end_min)),
        "activityLevel": level,
    }


def _levels(*segments: dict[str, Any]) -> FamilyRead:
    document = sleep_document()
    document["sleepLevels"] = list(segments)
    return read(DayFamily.SLEEP, document)


def test_codes_of_the_specification() -> None:
    """les codes de l'annexe A, tels quels."""
    assert dict(SLEEP_STAGE_CODES) == SPEC_STAGES
    assert STRESS_SENTINEL_CODES == SPEC_SENTINELS
    assert RESPIRATION_SENTINEL_CODES == SPEC_SENTINELS
    assert dict(BODY_BATTERY_STATUS_CODES) == SPEC_BODY_BATTERY_STATUSES
    assert READINESS_CONTEXTS == SPEC_CONTEXTS
    assert WAKING_CONTEXT in READINESS_CONTEXTS
    assert CONFIRMATION_TYPES == SPEC_CONFIRMATIONS


def test_ranges_from_physical_bounds() -> None:
    assert STRESS_LEVEL_RANGE == (0, 100)
    assert BODY_BATTERY_LEVEL_RANGE == (0, 100)
    assert RESPIRATION_RANGE_BREATHS_PER_MIN == (0.0, 70.0)
    assert SPO2_RANGE_PERCENT == (50.0, 100.0)
    assert HRV_RANGE_MS == (0.0, 500.0)
    assert SKIN_TEMPERATURE_DEVIATION_RANGE_C == (-10.0, 10.0)


@pytest.mark.parametrize(("code", "stage"), list(SPEC_STAGES.items()))
def test_every_known_stage_code(code: int, stage: SleepStage) -> None:
    result = _levels(_segment(0, 10, code))
    assert result.night_segments is not None
    assert result.night_segments.stage == (stage,)
    assert result.discards == ()


@pytest.mark.parametrize(("code", "stage"), list(SPEC_STAGES.items()))
def test_a_stage_code_written_as_a_float(code: int, stage: SleepStage) -> None:
    """La source écrit les phases en flottants de valeur entière (``1.0``) : le même
    code que l'entier."""
    result = _levels(_segment(0, 10, float(code)))
    assert result.night_segments is not None
    assert result.night_segments.stage == (stage,)
    assert result.unknown_codes == ()


@pytest.mark.parametrize(
    ("code", "text"), [(4, "4"), (-2, "-2"), (4.0, "4.0"), (1.5, "1.5"), (-0.5, "-0.5")]
)
def test_an_unknown_stage_code(code: float, text: str) -> None:
    result = _levels(_segment(0, 10, code), _segment(10, 20, 1))
    assert result.night_segments is not None
    assert result.night_segments.stage == (SleepStage.LIGHT,)
    assert _discards(result) == {("sleepLevels", PointDiscard.UNKNOWN_CODE): 1}
    assert _codes(result) == [("sleepLevels[*].activityLevel", text, 1)]


def _stress(*points: list[Any]) -> FamilyRead:
    document = stress_document()
    document["stressValuesArray"] = [list(point) for point in points]
    return read(DayFamily.STRESS, document)


@pytest.mark.parametrize("code", SPEC_SENTINELS)
def test_every_known_stress_code(code: int) -> None:
    result = _stress([ms(START), code])
    stress = result.day_series.stress
    assert stress is not None
    assert (stress.stress_level, stress.code) == ((None,), (code,))
    sleep = sleep_document()
    sleep["sleepStress"] = [{"startGMT": ms(NIGHT_START), "value": code}]
    night = read(DayFamily.SLEEP, sleep).night_series.stress
    assert night is not None
    assert night.code == (code,)


@pytest.mark.parametrize("code", SPEC_SENTINELS)
def test_a_stress_code_written_as_a_float(code: int) -> None:
    """``-1.0`` est le code ``-1`` : gardé en entier, partout où le stress se lit."""
    stress = _stress([ms(START), float(code)]).day_series.stress
    assert stress is not None
    assert stress.code == (code,)
    assert type(stress.code[0]) is int
    sleep = sleep_document()
    sleep["sleepStress"] = [{"startGMT": ms(NIGHT_START), "value": float(code)}]
    night = read(DayFamily.SLEEP, sleep).night_series.stress
    assert night is not None
    assert night.code == (code,)
    summary = daily_summary_document()
    summary["averageStressLevel"] = float(code)
    day_stress = read(DayFamily.DAILY_SUMMARY, summary).stress
    assert day_stress is not None
    assert day_stress.average_level_code == code


@pytest.mark.parametrize(
    ("value", "text"), [(-3, "-3"), (-3.0, "-3.0"), (-0.5, "-0.5"), (-1.5, "-1.5")]
)
def test_an_unknown_stress_code(value: float, text: str) -> None:
    result = _stress([ms(START), value], [ms(START) + 60000, 10])
    stress = result.day_series.stress
    assert stress is not None
    assert stress.stress_level == (10,)
    assert _discards(result) == {("stressValuesArray", PointDiscard.UNKNOWN_CODE): 1}
    assert _codes(result) == [("stressValuesArray[*][1]", text, 1)]


def _respiration(*points: list[Any]) -> FamilyRead:
    document = respiration_document()
    document["respirationValuesArray"] = [list(point) for point in points]
    return read(DayFamily.RESPIRATION, document)


@pytest.mark.parametrize("code", SPEC_SENTINELS)
def test_every_known_respiration_code(code: int) -> None:
    series = _respiration([ms(START), code]).day_series.respiration
    assert series is not None
    assert (series.breaths_per_min, series.code) == ((None,), (code,))


@pytest.mark.parametrize("code", SPEC_SENTINELS)
def test_a_respiration_code_written_as_a_float(code: int) -> None:
    """La source écrit les sentinelles de la respiration en flottants (``-1.0``) : le
    même code que l'entier, gardé en entier, le jour comme la nuit."""
    series = _respiration([ms(START), float(code)]).day_series.respiration
    assert series is not None
    assert series.code == (code,)
    assert type(series.code[0]) is int
    sleep = sleep_document()
    sleep["wellnessEpochRespirationDataDTOList"] = [
        {"startTimeGMT": ms(NIGHT_START), "respirationValue": float(code)}
    ]
    night = read(DayFamily.SLEEP, sleep).night_series.respiration
    assert night is not None
    assert night.code == (code,)


@pytest.mark.parametrize(("value", "text"), [(-3.0, "-3.0"), (-1.5, "-1.5")])
def test_an_unknown_respiration_code_written_as_a_float(
    value: float, text: str
) -> None:
    result = _respiration([ms(START), value])
    assert result.day_series.respiration is None
    assert _codes(result) == [("respirationValuesArray[*][1]", text, 1)]


def test_an_unknown_respiration_code() -> None:
    result = _respiration([ms(START), -3], [ms(START) + 60000, 15])
    assert _discards(result) == {
        ("respirationValuesArray", PointDiscard.UNKNOWN_CODE): 1
    }
    assert _codes(result) == [("respirationValuesArray[*][1]", "-3", 1)]
    sleep = sleep_document()
    sleep["wellnessEpochRespirationDataDTOList"] = [
        {"startTimeGMT": ms(NIGHT_START), "respirationValue": -9}
    ]
    night = read(DayFamily.SLEEP, sleep)
    assert _codes(night) == [
        ("wellnessEpochRespirationDataDTOList[*].respirationValue", "-9", 1)
    ]


def _battery(*points: list[Any]) -> FamilyRead:
    document = stress_document()
    document["bodyBatteryValuesArray"] = [list(point) for point in points]
    return read(DayFamily.STRESS, document)


@pytest.mark.parametrize(("code", "status"), list(SPEC_BODY_BATTERY_STATUSES.items()))
def test_every_known_body_battery_status(code: str, status: BodyBatteryStatus) -> None:
    battery = _battery([ms(START), code, 0, 3]).day_series.body_battery
    assert battery is not None
    assert (battery.level, battery.status) == ((0,), (status,))


@pytest.mark.parametrize(("code", "text"), [("ESTIMATED", "ESTIMATED"), ("", '""')])
def test_an_unknown_body_battery_status(code: str, text: str) -> None:
    result = _battery([ms(START), code, 40, 3])
    assert result.day_series.body_battery is None
    assert _discards(result) == {
        ("bodyBatteryValuesArray", PointDiscard.UNKNOWN_CODE): 1
    }
    assert _codes(result) == [("bodyBatteryValuesArray[*][1]", text, 1)]


def test_a_body_battery_point_without_status_is_a_null_value() -> None:
    """un point du jour au statut nul est écarté, même avec un niveau ; le statut se
    lit avant le niveau."""
    result = _battery([ms(START), None, 40, 3], [ms(START) + 60000, None, None, 3])
    assert result.day_series.body_battery is None
    assert _discards(result) == {("bodyBatteryValuesArray", PointDiscard.NULL_VALUE): 2}
    unknown_first = _battery([ms(START), "ESTIMATED", 101, 3])
    assert _discards(unknown_first) == {
        ("bodyBatteryValuesArray", PointDiscard.UNKNOWN_CODE): 1
    }


def test_body_battery_series_versions_are_distinct_and_sorted() -> None:
    result = _battery(
        [ms(START), "MEASURED", 40, 4],
        [ms(START) + 60000, "MEASURED", 41, 3.0],
        [ms(START) + 120000, "MEASURED", 42, 4],
        [ms(START) + 180000, "MEASURED", 43, None],
        [ms(START) + 240000, "MEASURED", 44, 1.5],
        [ms(START) + 300000, None, 44, 9],
    )
    assert result.versions.body_battery_series_versions == (3, 4)
    assert _discards(result) == {
        ("bodyBatteryValuesArray[*][3]", PointDiscard.OUT_OF_RANGE): 1,
        ("bodyBatteryValuesArray", PointDiscard.NULL_VALUE): 1,
    }


@pytest.mark.parametrize("context", SPEC_CONTEXTS)
def test_every_known_readiness_context(context: str) -> None:
    result = read(DayFamily.TRAINING_READINESS, [readiness_entry(inputContext=context)])
    (entry,) = result.readiness
    assert entry.input_context == context
    assert result.unknown_contexts == ()


def test_an_unknown_readiness_context_keeps_its_entry() -> None:
    result = read(
        DayFamily.TRAINING_READINESS, [readiness_entry(inputContext="INVENTED_CONTEXT")]
    )
    (entry,) = result.readiness
    assert entry.input_context == "INVENTED_CONTEXT"
    assert [(c.field_path, c.code, c.count) for c in result.unknown_contexts] == [
        ("[*].inputContext", "INVENTED_CONTEXT", 1)
    ]
    assert result.unknown_codes == ()


@pytest.mark.parametrize("confirmation", SPEC_CONFIRMATIONS)
def test_every_known_confirmation_type(confirmation: str) -> None:
    document = sleep_document()
    document["dailySleepDTO"]["sleepWindowConfirmationType"] = confirmation
    result = read(DayFamily.SLEEP, document)
    assert result.night is not None
    assert result.night.confirmation == confirmation
    assert result.unknown_confirmations == ()


def test_an_unknown_confirmation_type_is_kept_and_counted() -> None:
    document = sleep_document()
    document["dailySleepDTO"]["sleepWindowConfirmationType"] = "auto_invented"
    result = read(DayFamily.SLEEP, document)
    assert result.night is not None
    assert result.night.confirmation == "auto_invented"
    assert [(c.field_path, c.code) for c in result.unknown_confirmations] == [
        ("dailySleepDTO.sleepWindowConfirmationType", "auto_invented")
    ]
    assert result.unknown_codes == ()


def test_a_blank_code_text_is_absent_and_counted() -> None:
    document = sleep_document()
    document["dailySleepDTO"]["sleepWindowConfirmationType"] = " "
    document["hrvStatus"] = ""
    result = read(DayFamily.SLEEP, document)
    assert result.night is not None
    assert result.night.confirmation is None
    assert "hrvStatus" not in {copy.field_path for copy in result.copies}
    assert _discards(result) == {
        ("dailySleepDTO.sleepWindowConfirmationType", PointDiscard.NULL_VALUE): 1,
        ("hrvStatus", PointDiscard.NULL_VALUE): 1,
    }
    readiness = read(
        DayFamily.TRAINING_READINESS, [readiness_entry(inputContext="", level=" ")]
    )
    (entry,) = readiness.readiness
    assert (entry.input_context, entry.level) == (None, None)
    assert _discards(readiness) == {
        ("[*].inputContext", PointDiscard.NULL_VALUE): 1,
        ("[*].level", PointDiscard.NULL_VALUE): 1,
    }


_DAY_DOCUMENTS = {
    DayFamily.HEART_RATE: heart_rate_document,
    DayFamily.STRESS: stress_document,
    DayFamily.RESPIRATION: respiration_document,
    DayFamily.SPO2: spo2_document,
}
_DAY_BOUNDS = [
    (DayFamily.HEART_RATE, "heartRateValues", "heart_rate", 20, 19.5),
    (DayFamily.HEART_RATE, "heartRateValues", "heart_rate", 250, 250.5),
    (DayFamily.HEART_RATE, "heartRateValues", "heart_rate", 20, 0),
    (DayFamily.STRESS, "stressValuesArray", "stress", 0, 100.5),
    (DayFamily.STRESS, "stressValuesArray", "stress", 100, 101),
    (DayFamily.STRESS, "bodyBatteryValuesArray", "body_battery", 0, -1),
    (DayFamily.STRESS, "bodyBatteryValuesArray", "body_battery", 100, 101),
    (DayFamily.RESPIRATION, "respirationValuesArray", "respiration", 70, 70.5),
    (DayFamily.RESPIRATION, "respirationValuesArray", "respiration", 0.5, 0),
    (DayFamily.SPO2, "spO2HourlyAverages", "spo2", 50, 49.5),
    (DayFamily.SPO2, "spO2HourlyAverages", "spo2", 100, 100.5),
]


def _day_point(key: str, instant: int, value: Any) -> list[Any]:
    if key == "bodyBatteryValuesArray":
        return [instant, "MEASURED", value, 3]
    return [instant, value]


@pytest.mark.parametrize(("family", "key", "attribute", "kept", "out"), _DAY_BOUNDS)
def test_day_series_ranges_at_their_bounds(
    family: DayFamily, key: str, attribute: str, kept: float, out: float
) -> None:
    document = _DAY_DOCUMENTS[family]()
    document[key] = [
        _day_point(key, ms(START), kept),
        _day_point(key, ms(START) + 60000, out),
    ]
    if family is DayFamily.STRESS:
        other = (
            "bodyBatteryValuesArray"
            if key == "stressValuesArray"
            else "stressValuesArray"
        )
        document[other] = []
    result = read(family, document)
    series = getattr(result.day_series, attribute)
    assert series is not None
    assert len(series.epoch_s) == 1
    assert _discards(result) == {(key, PointDiscard.OUT_OF_RANGE): 1}


def test_heart_rate_range_is_the_common_one() -> None:
    assert HEART_RATE_RANGE_BPM == (20.0, 250.0)
    document = heart_rate_document()
    document["heartRateValues"] = [[ms(START), 20.0], [ms(START) + 1000, 250.0]]
    series = read(DayFamily.HEART_RATE, document).day_series.heart_rate
    assert series is not None
    assert series.heart_rate_bpm == (20.0, 250.0)


def _night_series_document(key: str, values: tuple[Any, ...]) -> dict[str, Any]:
    document = sleep_document()
    time_key = (
        "startTimeGMT" if key == "wellnessEpochRespirationDataDTOList" else "startGMT"
    )
    value_key = (
        "respirationValue" if key == "wellnessEpochRespirationDataDTOList" else "value"
    )
    document[key] = [
        {time_key: ms(NIGHT_START) + rank * 60000, value_key: value}
        for rank, value in enumerate(values)
    ]
    return document


@pytest.mark.parametrize(
    ("key", "attribute", "kept", "out"),
    [
        ("sleepHeartRate", "heart_rate", 20, 19),
        ("sleepHeartRate", "heart_rate", 250, 251),
        ("sleepStress", "stress", 0, 101),
        ("sleepBodyBattery", "body_battery", 0, -1),
        ("sleepBodyBattery", "body_battery", 100, 101),
        ("hrvData", "hrv", 500, 500.5),
        ("hrvData", "hrv", 0.5, 0),
        ("sleepRestlessMoments", "restless_moments", 0, -1),
    ],
)
def test_night_series_ranges_at_their_bounds(
    key: str, attribute: str, kept: float, out: float
) -> None:
    result = read(DayFamily.SLEEP, _night_series_document(key, (kept, out)))
    series = getattr(result.night_series, attribute)
    assert series is not None
    assert len(series.epoch_s) == 1
    assert _discards(result) == {(key, PointDiscard.OUT_OF_RANGE): 1}


@pytest.mark.parametrize(("kept", "out"), [(50, 49), (100, 101)])
def test_night_spo2_range_at_its_bounds(kept: float, out: float) -> None:
    document = sleep_document()
    document["wellnessEpochSPO2DataDTOList"] = [
        {
            "epochTimestamp": gmt_text(NIGHT_START + timedelta(minutes=minute)),
            "spo2Reading": value,
        }
        for minute, value in ((0, kept), (1, out))
    ]
    result = read(DayFamily.SLEEP, document)
    assert result.night_series.spo2 is not None
    assert result.night_series.spo2.spo2_percent == (float(kept),)
    assert _discards(result) == {
        ("wellnessEpochSPO2DataDTOList", PointDiscard.OUT_OF_RANGE): 1
    }


@pytest.mark.parametrize(("kept", "out"), [(70, 71), (0.5, 0)])
def test_night_respiration_range_at_its_bounds(kept: float, out: float) -> None:
    key = "wellnessEpochRespirationDataDTOList"
    result = read(DayFamily.SLEEP, _night_series_document(key, (kept, out)))
    assert result.night_series.respiration is not None
    assert result.night_series.respiration.breaths_per_min == (float(kept),)
    assert _discards(result) == {(key, PointDiscard.OUT_OF_RANGE): 1}


@pytest.mark.parametrize(("kept", "out"), [(-10, -10.5), (10, 10.5)])
def test_skin_temperature_deviation_range_at_its_bounds(
    kept: float, out: float
) -> None:
    document = sleep_document()
    document["avgSkinTempDeviationC"] = kept
    night = read(DayFamily.SLEEP, document).night
    assert night is not None
    assert night.skin_temperature_deviation_c == kept
    document["avgSkinTempDeviationC"] = out
    result = read(DayFamily.SLEEP, document)
    assert result.night is not None
    assert result.night.skin_temperature_deviation_c is None
    assert _discards(result) == {
        ("avgSkinTempDeviationC", PointDiscard.OUT_OF_RANGE): 1
    }


@pytest.mark.parametrize(
    ("key", "kept", "out", "attribute"),
    [
        ("avgSleepRespirationValue", 70, 70.5, "avg_sleep_breaths_per_min"),
        ("lowestRespirationValue", 0.5, 0, "lowest_breaths_per_min"),
    ],
)
def test_respiration_summary_range_at_its_bounds(
    key: str, kept: float, out: float, attribute: str
) -> None:
    document = respiration_document()
    document[key] = kept
    summary = read(DayFamily.RESPIRATION, document).respiration
    assert summary is not None
    assert getattr(summary, attribute) == kept
    document[key] = out
    result = read(DayFamily.RESPIRATION, document)
    assert result.respiration is not None
    assert getattr(result.respiration, attribute) is None
    assert _discards(result) == {(key, PointDiscard.OUT_OF_RANGE): 1}


@pytest.mark.parametrize(("kept", "out"), [(50, 49.5), (100, 100.5)])
def test_spo2_summary_range_at_its_bounds(kept: float, out: float) -> None:
    document = spo2_document()
    document["averageSpO2"] = kept
    summary = read(DayFamily.SPO2, document).spo2
    assert summary is not None
    assert summary.average_spo2_percent == kept
    document["averageSpO2"] = out
    result = read(DayFamily.SPO2, document)
    assert result.spo2 is not None
    assert result.spo2.average_spo2_percent is None
    assert _discards(result) == {("averageSpO2", PointDiscard.OUT_OF_RANGE): 1}


def test_hrv_summary_range_at_its_bounds() -> None:
    document = hrv_document()
    document["hrvSummary"]["lastNightAvg"] = 500
    document["hrvSummary"]["weeklyAvg"] = 0.5
    document["hrvSummary"]["baseline"]["markerValue"] = 0
    summary = read(DayFamily.HRV, document).hrv
    assert summary is not None
    assert (summary.last_night_avg_ms, summary.weekly_avg_ms) == (500.0, 0.5)
    assert summary.baseline_marker_value == 0.0
    document["hrvSummary"]["lastNightAvg"] = 500.5
    document["hrvSummary"]["weeklyAvg"] = 0
    document["hrvSummary"]["baseline"]["balancedLow"] = 0
    document["hrvSummary"]["baseline"]["markerValue"] = -0.5
    result = read(DayFamily.HRV, document)
    assert result.hrv is not None
    assert result.hrv.last_night_avg_ms is None
    assert result.hrv.weekly_avg_ms is None
    assert _discards(result) == {
        ("hrvSummary.lastNightAvg", PointDiscard.OUT_OF_RANGE): 1,
        ("hrvSummary.weeklyAvg", PointDiscard.OUT_OF_RANGE): 1,
        ("hrvSummary.baseline.balancedLow", PointDiscard.OUT_OF_RANGE): 1,
        ("hrvSummary.baseline.markerValue", PointDiscard.OUT_OF_RANGE): 1,
    }
    readiness = read(
        DayFamily.TRAINING_READINESS, [readiness_entry(hrvWeeklyAverage=0)]
    )
    (entry,) = readiness.readiness
    assert entry.hrv_weekly_average_ms is None
    assert _discards(readiness) == {
        ("[*].hrvWeeklyAverage", PointDiscard.OUT_OF_RANGE): 1
    }


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), float("-inf"), 25.5, 10**400]
)
def test_non_finite_non_integral_and_huge_values_are_out_of_range(value: float) -> None:
    document = stress_document()
    document["stressValuesArray"] = [[ms(START), "@@"], [ms(START) + 60000, 20]]
    document["maxStressLevel"] = "@@"
    text = "NaN" if value != value else json.dumps(value)
    data = json.dumps(document).replace('"@@"', text).encode()
    result = read(DayFamily.STRESS, data)
    assert result.refusal is None
    reason = (
        PointDiscard.UNKNOWN_CODE
        if value == float("-inf")
        else PointDiscard.OUT_OF_RANGE
    )
    assert _discards(result)[("stressValuesArray", reason)] == 1
    assert _discards(result)[("maxStressLevel", PointDiscard.OUT_OF_RANGE)] == 1
    stress = result.day_series.stress
    assert stress is not None
    assert stress.stress_level == (20,)


@pytest.mark.parametrize("value", [float("inf"), float("nan")])
def test_a_non_finite_value_without_upper_bound_is_out_of_range(value: float) -> None:
    """Une durée n'a pas de borne haute : l'infini n'y est pas une valeur pour
    autant."""
    document = daily_summary_document()
    document["restStressDuration"] = value
    result = read(DayFamily.DAILY_SUMMARY, document)
    assert result.stress is not None
    assert result.stress.rest_duration_s is None
    assert _discards(result) == {("restStressDuration", PointDiscard.OUT_OF_RANGE): 1}


def test_an_integral_float_is_an_integer() -> None:
    document = daily_summary_document()
    document["totalSteps"] = 10000.0
    document["bodyBatteryHighestValue"] = 90.0
    result = read(DayFamily.DAILY_SUMMARY, document)
    assert result.activity_totals is not None
    assert result.activity_totals.steps == 10000
    assert type(result.activity_totals.steps) is int
    assert result.body_battery is not None
    assert type(result.body_battery.highest) is int
    stress = _stress([ms(START), 20.0]).day_series.stress
    assert stress is not None
    assert type(stress.stress_level[0]) is int


def test_duplicate_and_earlier_instants() -> None:
    document = heart_rate_document()
    document["heartRateValues"] = [
        [ms(START) + 60000, 60],
        [ms(START) + 60000, 61],
        [ms(START), 62],
        [ms(START) + 120000, 63],
    ]
    result = read(DayFamily.HEART_RATE, document)
    series = result.day_series.heart_rate
    assert series is not None
    assert series.heart_rate_bpm == (60.0, 63.0)
    assert _discards(result) == {
        ("heartRateValues", PointDiscard.DUPLICATE_INSTANT): 1,
        ("heartRateValues", PointDiscard.NOT_INCREASING): 1,
    }


def test_the_value_is_checked_before_the_instant_order() -> None:
    """Un point écarté pour sa valeur n'est pas un point gardé : il ne compte ni comme
    doublon ni comme recul, et ne bloque pas le point suivant au même instant."""
    document = heart_rate_document()
    document["heartRateValues"] = [
        [ms(START) + 60000, 0],
        [ms(START) + 60000, 61],
        [ms(START), None],
    ]
    result = read(DayFamily.HEART_RATE, document)
    series = result.day_series.heart_rate
    assert series is not None
    assert series.heart_rate_bpm == (61.0,)
    assert _discards(result) == {
        ("heartRateValues", PointDiscard.OUT_OF_RANGE): 1,
        ("heartRateValues", PointDiscard.NULL_VALUE): 1,
    }


def test_the_instant_is_checked_before_the_value() -> None:
    document = heart_rate_document()
    document["heartRateValues"] = [
        [None, 0],
        [ms(datetime(1, 1, 1, tzinfo=UTC)), 0],
        [ms(START), 60],
    ]
    result = read(DayFamily.HEART_RATE, document)
    assert _discards(result) == {
        ("heartRateValues", PointDiscard.NULL_VALUE): 1,
        ("heartRateValues", PointDiscard.OUT_OF_RANGE): 1,
    }


def test_a_known_code_at_a_repeated_instant_is_a_duplicate() -> None:
    result = _stress([ms(START), 20], [ms(START), -1], [ms(START) + 60000, -2])
    stress = result.day_series.stress
    assert stress is not None
    assert stress.code == (None, -2)
    assert _discards(result) == {
        ("stressValuesArray", PointDiscard.DUPLICATE_INSTANT): 1
    }


def test_segments_overlap_and_durations() -> None:
    """Huit segments : gardés, le léger (0–10 min) et le paradoxal (10–20) ; écartés,
    un recouvrement (5–15), une durée nulle et une négative, une borne et un code nuls,
    et **un segment de code inconnu (9) et de durée nulle (20–20)** : ``unknown_code``,
    compté avec ``"9"``, pas ``not_increasing`` — le code se contrôle avant la durée."""
    missing_bound = _segment(30, 40, 1)
    missing_bound["endGMT"] = None
    result = _levels(
        _segment(0, 10, 1),
        _segment(10, 20, 2),
        _segment(5, 15, 0),
        _segment(25, 25, 1),
        _segment(30, 28, 1),
        missing_bound,
        _segment(40, 50, None),
        _segment(20, 20, 9),
    )
    segments = result.night_segments
    assert segments is not None
    assert segments.stage == (SleepStage.LIGHT, SleepStage.REM)
    start = ms(NIGHT_START) / 1000
    assert segments.start_epoch_s == (start, start + 600)
    assert segments.end_epoch_s == (start + 600, start + 1200)
    assert _discards(result) == {
        ("sleepLevels", PointDiscard.OVERLAPPING_SEGMENT): 1,
        ("sleepLevels", PointDiscard.NOT_INCREASING): 2,
        ("sleepLevels", PointDiscard.NULL_VALUE): 2,
        ("sleepLevels", PointDiscard.UNKNOWN_CODE): 1,
    }
    assert _codes(result) == [("sleepLevels[*].activityLevel", "9", 1)]


def test_an_overlapping_segment_with_a_null_duration_is_not_increasing() -> None:
    result = _levels(_segment(0, 10, 1), _segment(5, 5, 1))
    assert _discards(result) == {("sleepLevels", PointDiscard.NOT_INCREASING): 1}


@pytest.mark.parametrize("minutes", [0, -60])
def test_a_night_whose_end_does_not_follow_its_start_is_discarded(minutes: int) -> None:
    """l'épisode est écarté et compté, le fichier gardé."""
    document = sleep_document()
    dto = document["dailySleepDTO"]
    end = NIGHT_START + timedelta(minutes=minutes)
    dto["sleepEndTimestampGMT"] = ms(end)
    dto["sleepEndTimestampLocal"] = wall_ms(end)
    result = read(DayFamily.SLEEP, document)
    assert result.refusal is None
    assert result.night is None
    assert _discards(result) == {("night", PointDiscard.NOT_INCREASING): 1}
    assert result.naps != ()


@pytest.mark.parametrize(
    "missing",
    [
        "sleepStartTimestampLocal",
        "sleepEndTimestampLocal",
        "sleepEndTimestampGMT",
        "sleepStartTimestampGMT",
    ],
)
def test_a_night_missing_one_bound_is_discarded(missing: str) -> None:
    document = sleep_document()
    document["dailySleepDTO"][missing] = None
    result = read(DayFamily.SLEEP, document)
    assert result.night is None
    assert _discards(result) == {("night", PointDiscard.NULL_VALUE): 1}


def test_a_night_out_of_the_instant_range_is_discarded() -> None:
    document = sleep_document()
    far = datetime(9999, 12, 31, tzinfo=UTC)
    document["dailySleepDTO"]["sleepEndTimestampGMT"] = ms(far)
    document["dailySleepDTO"]["sleepEndTimestampLocal"] = ms(far) + 3600000
    result = read(DayFamily.SLEEP, document)
    assert result.night is None
    assert _discards(result) == {("night", PointDiscard.OUT_OF_RANGE): 1}


def test_night_summaries_out_of_their_range_are_absent_and_counted() -> None:
    document = sleep_document()
    dto = document["dailySleepDTO"]
    dto["deepSleepSeconds"] = -1
    dto["avgHeartRate"] = 300
    dto["avgSleepStress"] = 101
    dto["sleepScores"]["overall"]["value"] = 80.5
    document["bodyBatteryChange"] = 101
    document["restlessMomentsCount"] = -1
    night = read(DayFamily.SLEEP, document)
    assert night.night is not None
    values = night.night
    assert (values.deep_s, values.avg_heart_rate_bpm, values.avg_stress) == (
        None,
        None,
        None,
    )
    assert (
        values.sleep_score,
        values.body_battery_change,
        values.restless_moments,
    ) == (
        None,
        None,
        None,
    )
    assert _discards(night) == {
        ("dailySleepDTO.deepSleepSeconds", PointDiscard.OUT_OF_RANGE): 1,
        ("dailySleepDTO.avgHeartRate", PointDiscard.OUT_OF_RANGE): 1,
        ("dailySleepDTO.avgSleepStress", PointDiscard.OUT_OF_RANGE): 1,
        ("dailySleepDTO.sleepScores.overall.value", PointDiscard.OUT_OF_RANGE): 1,
        ("bodyBatteryChange", PointDiscard.OUT_OF_RANGE): 1,
        ("restlessMomentsCount", PointDiscard.OUT_OF_RANGE): 1,
    }


def _nap(**changes: Any) -> FamilyRead:
    document = sleep_document()
    document["dailySleepDTO"]["dailyNapDTOS"][0].update(changes)
    return read(DayFamily.SLEEP, document)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        (
            {"napEndTimestampGMT": gmt_text(at(DAY, 14), "")},
            PointDiscard.NOT_INCREASING,
        ),
        (
            {"napEndTimestampGMT": gmt_text(at(DAY, 13), "")},
            PointDiscard.NOT_INCREASING,
        ),
        ({"napStartTimeOffset": None}, PointDiscard.NULL_VALUE),
        ({"napEndTimestampGMT": None}, PointDiscard.NULL_VALUE),
        ({"napTimeSec": None}, PointDiscard.NULL_VALUE),
        ({"napTimeSec": -1}, PointDiscard.OUT_OF_RANGE),
        ({"napEndTimeOffset": 60.5}, PointDiscard.OUT_OF_RANGE),
    ],
)
def test_a_nap_that_does_not_hold_is_discarded(
    changes: dict[str, Any], reason: PointDiscard
) -> None:
    result = _nap(**changes)
    assert result.refusal is None
    assert result.naps == ()
    assert _discards(result) == {("naps", reason): 1}


def test_naps_are_sorted_by_start() -> None:
    document = sleep_document()
    first = document["dailySleepDTO"]["dailyNapDTOS"][0]
    later = {
        **first,
        "napStartTimestampGMT": gmt_text(at(DAY, 17), ""),
        "napEndTimestampGMT": gmt_text(at(DAY, 18), ""),
    }
    document["dailySleepDTO"]["dailyNapDTOS"] = [later, first]
    naps = read(DayFamily.SLEEP, document).naps
    assert [nap.start for nap in naps] == [at(DAY, 14), at(DAY, 17)]


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"endTimestampGMT": None}, PointDiscard.NULL_VALUE),
        ({"startTimestampLocal": None}, PointDiscard.NULL_VALUE),
        (
            {"endTimestampGMT": gmt_text(START - timedelta(seconds=1))},
            PointDiscard.NOT_INCREASING,
        ),
        (
            {
                "startTimestampGMT": gmt_text(START + timedelta(days=1)),
                "startTimestampLocal": local_text(START + timedelta(days=1)),
                "endTimestampGMT": gmt_text(START + timedelta(days=2)),
            },
            PointDiscard.OUT_OF_RANGE,
        ),
    ],
    ids=["fin", "debut_local", "fin_avant_debut", "autre_jour"],
)
def test_a_window_that_does_not_hold_is_discarded(
    changes: dict[str, Any], reason: PointDiscard
) -> None:
    document = heart_rate_document()
    document.update(changes)
    result = read(DayFamily.HEART_RATE, document)
    assert result.refusal is None
    assert result.window is None
    assert _discards(result)[("window", reason)] == 1


def test_a_window_without_any_text_is_absent_without_count() -> None:
    document = heart_rate_document()
    for key in ("startTimestampGMT", "startTimestampLocal", "endTimestampGMT"):
        document[key] = None
    result = read(DayFamily.HEART_RATE, document)
    assert result.window is None
    assert ("window", PointDiscard.NULL_VALUE) not in _discards(result)


def test_an_empty_window_is_kept() -> None:
    """Une fenêtre dont la fin GMT égale le début : un jour sans donnée reçue."""
    document = heart_rate_document()
    document["endTimestampGMT"] = gmt_text(START)
    window = read(DayFamily.HEART_RATE, document).window
    assert window is not None
    assert window.data_end == window.start == START


def test_a_readiness_entry_without_its_instant_is_discarded() -> None:
    """Deux entrées sans horodatage (le GMT, puis le local) : ``null_value`` ; une dont
    le local diffère du GMT d'une fraction de seconde (``.5``) : ``out_of_range`` ;
    seule la quatrième reste."""
    entries = [
        readiness_entry(timestamp=None),
        readiness_entry(timestampLocal=None),
        readiness_entry(timestampLocal=local_text(at(DAY, 7, 5), ".5")),
        readiness_entry(),
    ]
    result = read(DayFamily.TRAINING_READINESS, entries)
    assert len(result.readiness) == 1
    assert _discards(result) == {
        ("readiness", PointDiscard.NULL_VALUE): 2,
        ("readiness", PointDiscard.OUT_OF_RANGE): 1,
    }


def test_readiness_values_in_their_range() -> None:
    kept = read(
        DayFamily.TRAINING_READINESS,
        [readiness_entry(score=100, sleepScore=0, acuteLoad=0, hrvWeeklyAverage=500)],
    )
    (entry,) = kept.readiness
    assert (entry.score, entry.sleep_score, entry.acute_load) == (100, 0, 0.0)
    assert entry.hrv_weekly_average_ms == 500.0
    out = read(
        DayFamily.TRAINING_READINESS,
        [readiness_entry(score=101, sleepScore=-1, acuteLoad=-1, hrvWeeklyAverage=501)],
    )
    (entry,) = out.readiness
    assert (entry.score, entry.sleep_score, entry.acute_load) == (None, None, None)
    assert _discards(out) == {
        ("[*].score", PointDiscard.OUT_OF_RANGE): 1,
        ("[*].sleepScore", PointDiscard.OUT_OF_RANGE): 1,
        ("[*].acuteLoad", PointDiscard.OUT_OF_RANGE): 1,
        ("[*].hrvWeeklyAverage", PointDiscard.OUT_OF_RANGE): 1,
    }


@pytest.mark.parametrize(
    ("key", "kept", "out"),
    [
        ("bodyBatteryHighestValue", 100, 101),
        ("bodyBatteryLowestValue", 0, -1),
        ("bodyBatteryDuringSleep", -100, -101),
        ("bodyBatteryDuringSleep", 100, 101),
        ("maxStressLevel", 100, 101),
        ("averageStressLevel", 0, 100.5),
        ("totalSteps", 0, -1),
        ("averageMonitoringEnvironmentAltitude", 9000, 9001),
        ("averageMonitoringEnvironmentAltitude", -500, -501),
        ("moderateIntensityMinutes", 0, -1),
    ],
)
def test_daily_summary_values_at_their_bounds(
    key: str, kept: float, out: float
) -> None:
    document = daily_summary_document()
    document[key] = kept
    assert read(DayFamily.DAILY_SUMMARY, document).discards == ()
    document[key] = out
    result = read(DayFamily.DAILY_SUMMARY, document)
    assert _discards(result) == {(key, PointDiscard.OUT_OF_RANGE): 1}


def test_zero_is_discarded_only_outside_the_range() -> None:
    """Le stress et le Body Battery commencent à zéro ; la FC, la SpO2, la respiration
    et la HRV, non."""
    stress = _stress([ms(START), 0]).day_series.stress
    assert stress is not None
    assert stress.stress_level == (0,)
    battery = _battery([ms(START), "RESET", 0, 3]).day_series.body_battery
    assert battery is not None
    assert battery.level == (0,)
    for family, key in (
        (DayFamily.HEART_RATE, "heartRateValues"),
        (DayFamily.SPO2, "spO2HourlyAverages"),
        (DayFamily.RESPIRATION, "respirationValuesArray"),
    ):
        document = _DAY_DOCUMENTS[family]()
        document[key] = [[ms(START), 0]]
        assert _discards(read(family, document)) == {
            (key, PointDiscard.OUT_OF_RANGE): 1
        }
    hrv = read(DayFamily.SLEEP, _night_series_document("hrvData", (0,)))
    assert _discards(hrv) == {("hrvData", PointDiscard.OUT_OF_RANGE): 1}


def test_respiration_series_wall_clock_bounds_are_not_offsets() -> None:
    """Contrôle de la fixture : les millisecondes d'heure murale de ``sleep`` sont
    l'heure locale écrite comme GMT."""
    dto = sleep_document()["dailySleepDTO"]
    assert dto["sleepStartTimestampLocal"] - dto["sleepStartTimestampGMT"] == 3600000
    assert dto["sleepStartTimestampGMT"] == ms(NIGHT_START)


# --- le balayage par mutation : chaque champ, son chemin, sa plage -------------------

_STATUS_BLOCK = ("mostRecentTrainingStatus", "latestTrainingStatusData", "7")
_BALANCE_BLOCK = (
    "mostRecentTrainingLoadBalance",
    "metricsTrainingLoadBalanceDTOMap",
    "7",
)
_VO2 = ("mostRecentVO2Max", "generic")
_ACCLIMATION = ("mostRecentVO2Max", "heatAltitudeAcclimation")
_RESTING = ("allMetrics", "metricsMap", "WELLNESS_RESTING_HEART_RATE", 0)
_TS = "mostRecentTrainingStatus.latestTrainingStatusData.<n>"
_TB = "mostRecentTrainingLoadBalance.metricsTrainingLoadBalanceDTOMap.<n>"
_OUT = PointDiscard.OUT_OF_RANGE
_NULL = PointDiscard.NULL_VALUE
_MIN_MS = ms(datetime(1, 1, 2, tzinfo=UTC))
_MAX_MS = ms(datetime(9999, 12, 30, tzinfo=UTC))
_FIRST_INSTANT = "0001-01-01T00:00:00"
_LAST_INSTANT = "9999-12-31T00:00:00"

_FIELDS: list[tuple[DayFamily, tuple[str | int, ...], Any, str, PointDiscard]] = [
    (DayFamily.RESPIRATION, ("avgWakingRespirationValue",), 0, "", _OUT),
    (DayFamily.RESPIRATION, ("highestRespirationValue",), 0, "", _OUT),
    (DayFamily.RESPIRATION, ("respirationVersion",), -1, "", _OUT),
    (DayFamily.RESPIRATION, ("respirationVersion",), 200.5, "", _OUT),
    (DayFamily.RESPIRATION, ("sleepStartTimestampGMT",), _FIRST_INSTANT, "", _OUT),
    (DayFamily.SPO2, ("avgSleepSpO2",), 49, "", _OUT),
    (DayFamily.SPO2, ("lowestSpO2",), 49, "", _OUT),
    (DayFamily.SPO2, ("sleepEndTimestampGMT",), _LAST_INSTANT, "", _OUT),
    (DayFamily.HRV, ("sleepStartTimestampGMT",), _FIRST_INSTANT, "", _OUT),
    (DayFamily.DAILY_SUMMARY, ("bodyBatteryChargedValue",), -1, "", _OUT),
    (DayFamily.DAILY_SUMMARY, ("bodyBatteryChargedValue",), 60.5, "", _OUT),
    (DayFamily.DAILY_SUMMARY, ("bodyBatteryDrainedValue",), -1, "", _OUT),
    (DayFamily.DAILY_SUMMARY, ("bodyBatteryDrainedValue",), 55.5, "", _OUT),
    (DayFamily.DAILY_SUMMARY, ("bodyBatteryAtWakeTime",), 101, "", _OUT),
    (DayFamily.DAILY_SUMMARY, ("totalSteps",), 10000.5, "", _OUT),
    (DayFamily.DAILY_SUMMARY, ("vigorousIntensityMinutes",), -1, "", _OUT),
    (DayFamily.DAILY_SUMMARY, ("floorsAscendedInMeters",), -1, "", _OUT),
    (DayFamily.DAILY_SUMMARY, ("floorsDescendedInMeters",), -1, "", _OUT),
    (DayFamily.DAILY_SUMMARY, ("restStressDuration",), -1, "", _OUT),
    (DayFamily.DAILY_SUMMARY, ("restingHeartRate",), 0, "", _OUT),
    (DayFamily.DAILY_SUMMARY, ("avgWakingRespirationValue",), 0, "", _OUT),
    (DayFamily.DAILY_SUMMARY, ("highestRespirationValue",), 0, "", _OUT),
    (DayFamily.DAILY_SUMMARY, ("lowestRespirationValue",), 0, "", _OUT),
    (DayFamily.DAILY_SUMMARY, ("averageSpo2",), 49, "", _OUT),
    (DayFamily.DAILY_SUMMARY, ("lowestSpo2",), 49, "", _OUT),
    (DayFamily.DAILY_SUMMARY, ("respirationAlgorithmVersion",), -1, "", _OUT),
    (DayFamily.DAILY_SUMMARY, ("bodyBatteryVersion",), -1, "", _OUT),
    (DayFamily.BODY_BATTERY, (0, "charged"), -1, "[*].charged", _OUT),
    (DayFamily.BODY_BATTERY, (0, "charged"), 60.5, "[*].charged", _OUT),
    (DayFamily.BODY_BATTERY, (0, "drained"), -1, "[*].drained", _OUT),
    (DayFamily.BODY_BATTERY, (0, "drained"), 55.5, "[*].drained", _OUT),
    (
        DayFamily.RESTING_HR,
        (*_RESTING, "value"),
        0,
        "allMetrics.metricsMap.WELLNESS_RESTING_HEART_RATE[*].value",
        _OUT,
    ),
    (DayFamily.HRV, ("hrvSummary", "lastNightAvg"), 0, "", _OUT),
    (DayFamily.HRV, ("hrvSummary", "lastNight5MinHigh"), 0, "", _OUT),
    (DayFamily.HRV, ("hrvSummary", "status"), "  ", "", _NULL),
    (DayFamily.HRV, ("hrvSummary", "baseline", "balancedLow"), 0, "", _OUT),
    (DayFamily.HRV, ("hrvSummary", "baseline", "balancedUpper"), 0, "", _OUT),
    (DayFamily.HRV, ("hrvSummary", "baseline", "lowUpper"), 0, "", _OUT),
    (DayFamily.HRV, ("hrvReadings", 0, "hrvValue"), 0, "hrvReadings", _OUT),
    (DayFamily.SLEEP, ("restingHeartRate",), 0, "", _OUT),
    (DayFamily.SLEEP, ("avgOvernightHrv",), 0, "", _OUT),
    (DayFamily.SLEEP, ("hrvStatus",), " ", "", _NULL),
    (DayFamily.SLEEP, ("dailySleepDTO", "averageRespirationValue"), 0, "", _OUT),
    (DayFamily.SLEEP, ("dailySleepDTO", "averageSpO2Value"), 49, "", _OUT),
    (DayFamily.SLEEP, ("wellnessSpO2SleepSummaryDTO", "averageSPO2"), 49, "", _OUT),
    (DayFamily.SLEEP, ("dailySleepDTO", "sleepVersion"), -1, "", _OUT),
    (DayFamily.SLEEP, ("respirationVersion",), -1, "", _OUT),
    (DayFamily.SLEEP, ("bodyBatteryChange",), -101, "", _OUT),
    (DayFamily.SLEEP, ("restlessMomentsCount",), 20.5, "", _OUT),
    (DayFamily.SLEEP, ("restlessMomentsCount",), -1, "", _OUT),
    (DayFamily.SLEEP, ("dailySleepDTO", "deepSleepSeconds"), -1, "", _OUT),
    (DayFamily.SLEEP, ("sleepStress", 0, "value"), 10.5, "sleepStress", _OUT),
    (DayFamily.SLEEP, ("sleepBodyBattery", 0, "value"), 30.5, "sleepBodyBattery", _OUT),
    (
        DayFamily.SLEEP,
        ("sleepRestlessMoments", 0, "value"),
        1.5,
        "sleepRestlessMoments",
        _OUT,
    ),
    (
        DayFamily.TRAINING_STATUS,
        (*_STATUS_BLOCK, "timestamp"),
        _MAX_MS + 1,
        f"{_TS}.timestamp",
        _OUT,
    ),
    (
        DayFamily.TRAINING_STATUS,
        (*_STATUS_BLOCK, "trainingStatus"),
        4.5,
        f"{_TS}.trainingStatus",
        _OUT,
    ),
    (
        DayFamily.TRAINING_STATUS,
        (*_STATUS_BLOCK, "trainingStatus"),
        -1,
        f"{_TS}.trainingStatus",
        _OUT,
    ),
    (
        DayFamily.TRAINING_STATUS,
        (*_STATUS_BLOCK, "acuteTrainingLoadDTO", "dailyTrainingLoadAcute"),
        -1,
        f"{_TS}.acuteTrainingLoadDTO.dailyTrainingLoadAcute",
        _OUT,
    ),
    (
        DayFamily.TRAINING_STATUS,
        (*_STATUS_BLOCK, "acuteTrainingLoadDTO", "acwrStatus"),
        " ",
        f"{_TS}.acuteTrainingLoadDTO.acwrStatus",
        _NULL,
    ),
    (
        DayFamily.TRAINING_STATUS,
        (*_BALANCE_BLOCK, "monthlyLoadAerobicLow"),
        -1,
        f"{_TB}.monthlyLoadAerobicLow",
        _OUT,
    ),
    (
        DayFamily.TRAINING_STATUS,
        (*_VO2, "vo2MaxPreciseValue"),
        -1,
        "mostRecentVO2Max.generic.vo2MaxPreciseValue",
        _OUT,
    ),
    (
        DayFamily.TRAINING_STATUS,
        (*_VO2, "vo2MaxValue"),
        -1,
        "mostRecentVO2Max.generic.vo2MaxValue",
        _OUT,
    ),
    (
        DayFamily.TRAINING_STATUS,
        (*_ACCLIMATION, "heatAcclimationPercentage"),
        -1,
        "mostRecentVO2Max.heatAltitudeAcclimation.heatAcclimationPercentage",
        _OUT,
    ),
    (
        DayFamily.TRAINING_STATUS,
        (*_ACCLIMATION, "heatTrend"),
        " ",
        "mostRecentVO2Max.heatAltitudeAcclimation.heatTrend",
        _NULL,
    ),
    (
        DayFamily.TRAINING_STATUS,
        (*_ACCLIMATION, "altitudeAcclimation"),
        9001,
        "mostRecentVO2Max.heatAltitudeAcclimation.altitudeAcclimation",
        _OUT,
    ),
    (
        DayFamily.TRAINING_STATUS,
        (*_ACCLIMATION, "currentAltitude"),
        9001,
        "mostRecentVO2Max.heatAltitudeAcclimation.currentAltitude",
        _OUT,
    ),
    (
        DayFamily.TRAINING_STATUS,
        (*_ACCLIMATION, "altitudeTrend"),
        " ",
        "mostRecentVO2Max.heatAltitudeAcclimation.altitudeTrend",
        _NULL,
    ),
]
"""Un champ, une valeur qui ne tient pas, le chemin sous lequel l'écart se compte
(vide : le chemin du champ, ses clés jointes par des points)."""


def _counted_path(path: tuple[str | int, ...], counted: str) -> str:
    return counted or ".".join(str(key) for key in path)


@pytest.mark.parametrize(
    ("family", "path", "value", "counted", "reason"),
    _FIELDS,
    ids=[
        f"{family.value}-{'.'.join(str(key) for key in path)}-{value!r}"
        for family, path, value, _, _ in _FIELDS
    ],
)
def test_a_value_that_does_not_hold_is_counted_under_its_path(
    family: DayFamily,
    path: tuple[str | int, ...],
    value: Any,
    counted: str,
    reason: PointDiscard,
) -> None:
    """Chaque champ lu : une valeur hors de sa plage (non finie, hors bornes, non
    entière pour un compte, un niveau ou une version ; un instant hors de ce que
    ``datetime`` représente) ou un code texte blanc s'écarte et se compte une fois,
    sous le chemin de son champ, avec son motif ; rien d'autre ne change."""
    base = _discards(read(family, DOCUMENTS[family]()))
    result = read(family, _set(DOCUMENTS[family](), path, value))
    assert result.refusal is None
    expected = dict(base)
    key = (_counted_path(path, counted), reason)
    expected[key] = expected.get(key, 0) + 1
    assert _discards(result) == expected


_KEPT: list[tuple[DayFamily, tuple[str | int, ...], Any, Callable[[Any], Any], Any]] = [
    (
        DayFamily.DAILY_SUMMARY,
        ("restStressDuration",),
        0,
        lambda r: r.stress.rest_duration_s,
        0.0,
    ),
    (
        DayFamily.DAILY_SUMMARY,
        ("bodyBatteryChargedValue",),
        0,
        lambda r: r.body_battery.charged,
        0,
    ),
    (
        DayFamily.DAILY_SUMMARY,
        ("bodyBatteryDrainedValue",),
        0,
        lambda r: r.body_battery.drained,
        0,
    ),
    (
        DayFamily.DAILY_SUMMARY,
        ("floorsAscendedInMeters",),
        0,
        lambda r: r.activity_totals.floors_ascended_m,
        0.0,
    ),
    (
        DayFamily.DAILY_SUMMARY,
        ("floorsDescendedInMeters",),
        0,
        lambda r: r.activity_totals.floors_descended_m,
        0.0,
    ),
    (
        DayFamily.DAILY_SUMMARY,
        ("totalSteps",),
        10000.0,
        lambda r: r.activity_totals.steps,
        10000,
    ),
    (
        DayFamily.BODY_BATTERY,
        (0, "charged"),
        0,
        lambda r: [copy.value for copy in r.copies],
        [0, 55],
    ),
    (
        DayFamily.BODY_BATTERY,
        (0, "drained"),
        0,
        lambda r: [copy.value for copy in r.copies],
        [60, 0],
    ),
    (
        DayFamily.SLEEP,
        ("dailySleepDTO", "deepSleepSeconds"),
        0,
        lambda r: r.night.deep_s,
        0.0,
    ),
    (
        DayFamily.SLEEP,
        ("restlessMomentsCount",),
        0,
        lambda r: r.night.restless_moments,
        0,
    ),
    (
        DayFamily.SLEEP,
        ("bodyBatteryChange",),
        -100,
        lambda r: r.night.body_battery_change,
        -100,
    ),
    (
        DayFamily.SLEEP,
        ("dailySleepDTO", "dailyNapDTOS", 0, "napTimeSec"),
        0,
        lambda r: r.naps[0].sleep_s,
        0.0,
    ),
    (
        DayFamily.SLEEP,
        ("dailySleepDTO", "dailyNapDTOS", 0, "napTimeSec"),
        1500.5,
        lambda r: r.naps[0].sleep_s,
        1500.5,
    ),
    (
        DayFamily.SLEEP,
        ("sleepRestlessMoments", 0, "value"),
        0,
        lambda r: r.night_series.restless_moments.count,
        (0,),
    ),
    (
        DayFamily.RESPIRATION,
        ("respirationVersion",),
        0,
        lambda r: r.versions.respiration_version,
        0,
    ),
    (
        DayFamily.SLEEP,
        ("dailySleepDTO", "sleepVersion"),
        0,
        lambda r: r.versions.sleep_version,
        0,
    ),
    (
        DayFamily.TRAINING_STATUS,
        (*_STATUS_BLOCK, "trainingStatus"),
        0,
        lambda r: r.status_block.status_code,
        0,
    ),
    (
        DayFamily.TRAINING_STATUS,
        (*_VO2, "vo2MaxPreciseValue"),
        0,
        lambda r: r.vo2_max_block.vo2_max_precise_ml_kg_min,
        0.0,
    ),
    (
        DayFamily.TRAINING_STATUS,
        (*_VO2, "vo2MaxValue"),
        0,
        lambda r: r.vo2_max_block.vo2_max_ml_kg_min,
        0.0,
    ),
    (
        DayFamily.TRAINING_STATUS,
        (*_ACCLIMATION, "heatAcclimationPercentage"),
        0,
        lambda r: r.heat_block.heat_acclimation_percent,
        0.0,
    ),
]
"""Un champ, une valeur à sa borne basse (zéro, −100) ou non entière là où rien ne
l'exige, ce que la lecture en rend."""


@pytest.mark.parametrize(
    ("family", "path", "value", "get", "expected"),
    _KEPT,
    ids=[
        f"{family.value}-{'.'.join(str(key) for key in path)}-{value!r}"
        for family, path, value, _, _ in _KEPT
    ],
)
def test_a_value_at_its_lower_bound_is_kept(
    family: DayFamily,
    path: tuple[str | int, ...],
    value: Any,
    get: Callable[[Any], Any],
    expected: Any,
) -> None:
    """Zéro, ou −100 pour le changement de Body Battery de la nuit, est une valeur
    gardée, sans écart ; une durée de sieste non entière aussi (seuls les comptes, les
    niveaux et les versions sont entiers)."""
    base = _discards(read(family, DOCUMENTS[family]()))
    result = read(family, _set(DOCUMENTS[family](), path, value))
    assert get(result) == expected
    assert _discards(result) == base


def test_the_instant_range_bounds_are_kept_their_neighbours_discarded() -> None:
    """La plage d'un instant lu : 0001-01-02 et 9999-12-30 UTC (minuit), bornes
    comprises ; une milliseconde au-delà, ``out_of_range``, et la lecture de la série
    continue."""
    document = heart_rate_document()
    document["heartRateValues"] = [
        [_MIN_MS - 1, 55],
        [_MIN_MS, 56],
        [_MAX_MS, 57],
        [_MAX_MS + 1, 58],
    ]
    result = read(DayFamily.HEART_RATE, document)
    series = result.day_series.heart_rate
    assert series is not None
    assert series.epoch_s == (_MIN_MS / 1000, _MAX_MS / 1000)
    assert series.heart_rate_bpm == (56.0, 57.0)
    assert _discards(result) == {("heartRateValues", _OUT): 2}


def test_a_nap_of_the_first_day_of_year_one_is_out_of_range() -> None:
    """Une sieste le 0001-01-01 à 00:30 GMT, décalage −720 min : hors de la plage des
    instants, écartée et comptée ; l'heure locale n'est jamais calculée."""
    result = _nap(
        napStartTimestampGMT="0001-01-01T00:30:00",
        napEndTimestampGMT="0001-01-01T01:00:00",
        napStartTimeOffset=-720,
        napEndTimeOffset=-720,
    )
    assert result.naps == ()
    assert _discards(result) == {("naps", _OUT): 1}


def test_a_nap_whose_end_alone_is_out_of_range_is_discarded() -> None:
    result = _nap(napEndTimestampGMT=_LAST_INSTANT)
    assert result.naps == ()
    assert _discards(result) == {("naps", _OUT): 1}


def test_the_nap_source_of_a_discarded_nap_is_still_checked() -> None:
    """Une sieste écartée (son début nul) dont ``napSource`` est un texte : le champ est
    d'un autre type, le fichier est refusé."""
    result = _nap(napStartTimestampGMT=None, napSource="1")
    assert result.refusal is DayFileRefusal.UNEXPECTED_SHAPE


def test_a_night_whose_end_offset_is_not_whole_seconds_is_out_of_range() -> None:
    document = sleep_document()
    document["dailySleepDTO"]["sleepEndTimestampLocal"] += 500
    result = read(DayFamily.SLEEP, document)
    assert result.night is None
    assert _discards(result) == {("night", _OUT): 1}


def test_a_night_whose_gmt_end_alone_is_out_of_range_is_discarded() -> None:
    """La fin GMT de la nuit au-delà du 9999-12-30, son heure locale (−12 h) en deçà :
    hors plage, la nuit est écartée."""
    day = date(9999, 12, 30)
    document = sleep_document()
    dto = document["dailySleepDTO"]
    dto["calendarDate"] = day.isoformat()
    start = datetime(9999, 12, 29, 22, tzinfo=UTC)
    end = datetime(9999, 12, 30, 6, tzinfo=UTC)
    dto["sleepStartTimestampGMT"] = ms(start)
    dto["sleepEndTimestampGMT"] = ms(end)
    dto["sleepStartTimestampLocal"] = ms(start - timedelta(hours=12))
    dto["sleepEndTimestampLocal"] = ms(end - timedelta(hours=12))
    result = read(DayFamily.SLEEP, document, day)
    assert result.refusal is None
    assert result.night is None
    assert _discards(result) == {("night", _OUT): 1}


def test_a_segment_whose_end_alone_is_out_of_range_is_discarded() -> None:
    result = _levels(
        {
            "startGMT": gmt_text(NIGHT_START),
            "endGMT": _LAST_INSTANT,
            "activityLevel": 1,
        },
        _segment(0, 60, 0),
    )
    segments = result.night_segments
    assert segments is not None
    assert segments.stage == (SleepStage.DEEP,)
    assert _discards(result) == {("sleepLevels", _OUT): 1}


def test_a_window_missing_its_start_alone_is_a_null_value() -> None:
    document = heart_rate_document()
    document["startTimestampGMT"] = None
    result = read(DayFamily.HEART_RATE, document)
    assert result.window is None
    assert _discards(result)[("window", _NULL)] == 1


def test_a_window_whose_end_is_out_of_range_is_discarded() -> None:
    document = heart_rate_document()
    document["endTimestampGMT"] = _LAST_INSTANT
    result = read(DayFamily.HEART_RATE, document)
    assert result.window is None
    assert _discards(result) == {("heartRateValues", _NULL): 1, ("window", _OUT): 1}


def test_a_repeated_unknown_code_is_counted_each_time() -> None:
    result = _stress([ms(START), -3], [ms(START) + 60000, -3])
    assert _codes(result) == [("stressValuesArray[*][1]", "-3", 2)]
    assert _discards(result) == {("stressValuesArray", PointDiscard.UNKNOWN_CODE): 2}


def test_an_unknown_night_stress_code_is_counted_under_its_value_path() -> None:
    document = sleep_document()
    document["sleepStress"][1]["value"] = -3
    result = read(DayFamily.SLEEP, document)
    assert _codes(result) == [("sleepStress[*].value", "-3", 1)]


def test_every_body_battery_discard_is_followed_by_a_kept_point() -> None:
    """La série de Body Battery du jour : chaque défaut (instant nul, instant hors
    plage, statut nul, statut inconnu, niveau nul, non entier, hors plage, instant
    répété), compté sous ``bodyBatteryValuesArray``, est suivi d'un point gardé ; la
    version d'un point écarté ne se lit pas ; la version 0 est une version."""
    base = ms(START)

    def at_minute(minute: int) -> int:
        return base + minute * 60000

    points: list[list[Any]] = [
        [None, "MEASURED", 40, 1],
        [at_minute(1), "MEASURED", 41, 3],
        [_MAX_MS + 1, "MEASURED", 40, 1],
        [at_minute(2), "MEASURED", 42, 3],
        [at_minute(3), None, 40, 1],
        [at_minute(4), "MEASURED", 43, 3],
        [at_minute(5), "BOGUS", 40, 1],
        [at_minute(6), "MEASURED", 44, 3],
        [at_minute(7), "MEASURED", None, 1],
        [at_minute(8), "MEASURED", 45, 3],
        [at_minute(9), "MEASURED", 40.5, 1],
        [at_minute(10), "MEASURED", 46, 3],
        [at_minute(11), "MEASURED", 101, 1],
        [at_minute(12), "MEASURED", 47, 0],
        [at_minute(12), "MEASURED", 48, 9],
        [at_minute(13), "MEASURED", 49, 3],
    ]
    result = _battery(*points)
    battery = result.day_series.body_battery
    assert battery is not None
    assert battery.level == (41, 42, 43, 44, 45, 46, 47, 49)
    assert battery.epoch_s == tuple(
        at_minute(minute) / 1000 for minute in (1, 2, 4, 6, 8, 10, 12, 13)
    )
    assert result.versions.body_battery_series_versions == (0, 3)
    path = "bodyBatteryValuesArray"
    assert _discards(result) == {
        (path, _NULL): 3,
        (path, _OUT): 3,
        (path, PointDiscard.UNKNOWN_CODE): 1,
        (path, PointDiscard.DUPLICATE_INSTANT): 1,
    }
    assert _codes(result) == [("bodyBatteryValuesArray[*][1]", "BOGUS", 1)]


def test_a_body_battery_version_out_of_range_is_counted_apart() -> None:
    result = _battery(
        [ms(START), "MEASURED", 40, -1], [ms(START) + 60000, "RESET", 0, 2]
    )
    assert result.versions.body_battery_series_versions == (2,)
    assert _discards(result) == {("bodyBatteryValuesArray[*][3]", _OUT): 1}


def test_every_body_battery_element_after_the_first_is_read_and_counted() -> None:
    """Trois éléments : les deux derniers, des doublons comptés, sont lus (leurs
    valeurs hors plage se comptent aussi)."""
    first = body_battery_document()[0]
    second = {**first, "charged": 61}
    third = {**first, "charged": -1}
    result = read(DayFamily.BODY_BATTERY, [first, second, third])
    assert [copy.value for copy in result.copies] == [60, 55]
    assert _discards(result) == {
        ("[*]", PointDiscard.DUPLICATE_INSTANT): 2,
        ("[*].charged", _OUT): 1,
    }


def test_non_primary_readiness_entries_are_all_counted() -> None:
    entries = [
        readiness_entry(primaryActivityTracker=False),
        readiness_entry(primaryActivityTracker=None),
        readiness_entry(),
    ]
    result = read(DayFamily.TRAINING_READINESS, entries)
    assert result.readiness_non_primary == 2
    assert len(result.readiness) == 1


def test_a_repeated_unknown_readiness_context_is_counted_each_time() -> None:
    entries = [
        readiness_entry(inputContext="INVENTED_CONTEXT"),
        readiness_entry(
            timestamp=gmt_text(at(DAY, 9)),
            timestampLocal=local_text(at(DAY, 9)),
            inputContext="INVENTED_CONTEXT",
        ),
    ]
    result = read(DayFamily.TRAINING_READINESS, entries)
    assert [(c.field_path, c.code, c.count) for c in result.unknown_contexts] == [
        ("[*].inputContext", "INVENTED_CONTEXT", 2)
    ]


def test_a_readiness_entry_whose_local_instant_alone_is_out_of_range() -> None:
    """L'heure GMT dans la plage (9999-12-29 à 20 h), l'heure locale au-delà
    (9999-12-30 à 10 h, +14:00) : l'entrée est écartée."""
    day = date(9999, 12, 29)
    entry = readiness_entry(
        calendarDate=day.isoformat(),
        timestamp="9999-12-29T20:00:00.0",
        timestampLocal="9999-12-30T10:00:00.0",
    )
    result = read(DayFamily.TRAINING_READINESS, [entry], day)
    assert result.readiness == ()
    assert _discards(result) == {("readiness", _OUT): 1}


def test_a_restless_moment_of_zero_is_kept_as_zero() -> None:
    document = sleep_document()
    document["sleepRestlessMoments"] = [{"startGMT": ms(NIGHT_START), "value": 0}]
    moments = read(DayFamily.SLEEP, document).night_series.restless_moments
    assert moments is not None
    assert moments.count == (0,)
