"""La lecture d'un fichier d'une famille journalière (``ingest/families.py``), sur des
documents inventés à la forme réelle des champs : chaque famille, chaque refus, les
documents vides, les formes d'horodatage, les décalages, les copies, les feuilles, le
détail. Les codes, les plages et l'ordre des écarts sont dans
``test_ingest_families_points.py``."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from datetime import UTC, timedelta, timezone
from typing import Any

import pytest

from fixtures.days import (
    DAY,
    PLUS1,
    PLUS2,
    SPRING_DAY,
    at,
    midnight,
    ms,
    source,
    wall_ms,
)
from fixtures.families import (
    DEVICE,
    DOCUMENTS,
    NIGHT_START,
    START,
    USER,
    _set,
    balance_entry,
    body_battery_document,
    daily_summary_document,
    encode,
    gmt_text,
    heart_rate_document,
    hrv_document,
    local_text,
    read,
    readiness_entry,
    respiration_document,
    resting_hr_document,
    sleep_document,
    spo2_document,
    status_entry,
    stress_document,
    training_readiness_document,
    training_status_document,
)
from mountain_perf.ingest.families import COPY_FIELDS, FamilyRead
from mountain_perf.schemas import (
    DAY_WINDOW_FAMILIES,
    QUANTITY_SUPPORTS,
    BodyBatteryStatus,
    DayFamily,
    DayFileRefusal,
    DayRecord,
    DaySeries,
    DayState,
    HeartRateSeries,
    Night,
    NightSeries,
    PointDiscard,
    PointDiscardCount,
    SleepSegment,
    SleepStage,
    TrainingStatusKind,
)

OBJECT_FAMILIES = [
    family
    for family in DayFamily
    if family not in (DayFamily.BODY_BATTERY, DayFamily.TRAINING_READINESS)
]
LIST_FAMILIES = [DayFamily.BODY_BATTERY, DayFamily.TRAINING_READINESS]
_SLEEP_SERIES = (
    "sleepLevels",
    "sleepHeartRate",
    "sleepStress",
    "sleepBodyBattery",
    "hrvData",
    "wellnessEpochRespirationDataDTOList",
    "sleepRestlessMoments",
    "wellnessEpochSPO2DataDTOList",
)


def _discards(read_result: FamilyRead) -> dict[tuple[str, PointDiscard], int]:
    return {(d.series_path, d.reason): d.count for d in read_result.discards}


def _copies(read_result: FamilyRead) -> dict[str, Any]:
    return {copy.field_path: copy.value for copy in read_result.copies}


@pytest.mark.parametrize("family", list(DayFamily), ids=str)
def test_every_family_reads_its_document(family: DayFamily) -> None:
    """Le document de chaque famille se lit sans refus, sans écart hors des siens,
    sans code, contexte ni type de confirmation inconnu (``training_readiness`` porte
    le contexte ``UPDATE_REALTIME_VARIABLES``, connu)."""
    result = read(family, DOCUMENTS[family]())
    assert result.refusal is None
    assert result.empty is False
    expected = (
        {("heartRateValues", PointDiscard.NULL_VALUE): 1}
        if family is DayFamily.HEART_RATE
        else {}
    )
    assert _discards(result) == expected
    assert result.unknown_codes == ()
    assert result.unknown_contexts == ()
    assert result.unknown_confirmations == ()
    assert result.source == source(family)
    assert result.fields


def test_a_pure_function_of_its_bytes() -> None:
    data = encode(sleep_document())
    first = read(DayFamily.SLEEP, data)
    assert read(DayFamily.SLEEP, data) == first
    assert first.night is not None
    assert first.night.source == source(DayFamily.SLEEP)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"{",
        b"\xff\xfe{}",
        b'{"calendarDate": "2001-03-10"',
        b"\xef\xbb\xbf{}",
        "{}".encode("utf-16"),
        b"[" * 100000,
    ],
    ids=["vide", "ouvert", "utf16", "tronque", "bom", "utf16-bom", "profond"],
)
def test_unreadable_json(data: bytes) -> None:
    result = read(DayFamily.HEART_RATE, data)
    assert result.refusal is DayFileRefusal.UNREADABLE_JSON
    assert result == FamilyRead(
        DayFamily.HEART_RATE, DAY, source(DayFamily.HEART_RATE), refusal=result.refusal
    )


@pytest.mark.parametrize(
    ("token", "refusal"),
    [
        ("NaN", None),
        ("Infinity", None),
        ("-Infinity", None),
        ("9" * 4300, None),
        ("nan", DayFileRefusal.UNREADABLE_JSON),
        ("9" * 4301, DayFileRefusal.UNREADABLE_JSON),
    ],
    ids=["NaN", "Infinity", "-Infinity", "4300-chiffres", "nan", "4301-chiffres"],
)
def test_json_tokens_of_python(token: str, refusal: DayFileRefusal | None) -> None:
    """Le JSON se lit par ``json.loads`` : les jetons ``NaN``, ``Infinity`` et
    ``-Infinity`` s'y lisent (une valeur non finie, écartée ``out_of_range``, le
    fichier gardé) ; ``nan`` n'est pas un jeton, et un entier de plus de 4 300 chiffres
    ne se lit pas : ``unreadable_json``."""
    document = heart_rate_document()
    document["restingHeartRate"] = "@@"
    data = json.dumps(document).replace('"@@"', token).encode()
    result = read(DayFamily.HEART_RATE, data)
    assert result.refusal is refusal
    if refusal is None:
        assert _discards(result)[("restingHeartRate", PointDiscard.OUT_OF_RANGE)] == 1
        assert result.copies == ()


@pytest.mark.parametrize("root", [[{}], 3, "texte", None, True])
@pytest.mark.parametrize("family", OBJECT_FAMILIES, ids=str)
def test_object_family_with_another_root(family: DayFamily, root: Any) -> None:
    assert read(family, root).refusal is DayFileRefusal.UNEXPECTED_SHAPE


@pytest.mark.parametrize("root", [{"date": "2001-03-10"}, 3, None])
@pytest.mark.parametrize("family", LIST_FAMILIES, ids=str)
def test_list_family_with_another_root(family: DayFamily, root: Any) -> None:
    assert read(family, root).refusal is DayFileRefusal.UNEXPECTED_SHAPE


@pytest.mark.parametrize(
    ("family", "path", "value"),
    [
        (DayFamily.HEART_RATE, ("heartRateValues",), {"0": 1}),
        (DayFamily.HEART_RATE, ("heartRateValues", 0), [ms(midnight(DAY))]),
        (DayFamily.HEART_RATE, ("heartRateValues", 0, 0), "984178800000"),
        (DayFamily.HEART_RATE, ("heartRateValues", 0, 0), 984178800000.0),
        (DayFamily.HEART_RATE, ("heartRateValues", 0, 1), "55"),
        (DayFamily.HEART_RATE, ("heartRateValues", 0, 1), True),
        (DayFamily.HEART_RATE, ("calendarDate",), 20010310),
        (DayFamily.HEART_RATE, ("calendarDate",), "10/03/2001"),
        (DayFamily.HEART_RATE, ("startTimestampGMT",), "2001-03-09 23:00:00"),
        (DayFamily.HEART_RATE, ("startTimestampGMT",), "2001-03-09T23:00:00.0000"),
        (DayFamily.HEART_RATE, ("startTimestampGMT",), "2001-02-30T23:00:00.0"),
        (DayFamily.HEART_RATE, ("restingHeartRate",), "48"),
        (DayFamily.SLEEP, ("dailySleepDTO",), []),
        (DayFamily.SLEEP, ("dailySleepDTO", "sleepFromDevice"), "true"),
        (DayFamily.SLEEP, ("sleepLevels", 0), [1]),
        (DayFamily.SLEEP, ("sleepLevels", 0, "activityLevel"), "1"),
        (DayFamily.SLEEP, ("sleepHeartRate", 0), 52),
        (DayFamily.STRESS, ("bodyBatteryValuesArray", 0, 1), 1),
        (DayFamily.STRESS, ("bodyBatteryValuesArray", 0), [0, "MEASURED"]),
        (DayFamily.DAILY_SUMMARY, ("includesWellnessData",), 1),
        (DayFamily.TRAINING_READINESS, (0,), "entrée"),
        (DayFamily.TRAINING_READINESS, (0, "timestamp"), 984207900000),
        (DayFamily.RESTING_HR, ("allMetrics", "metricsMap"), "carte"),
        (DayFamily.TRAINING_STATUS, ("mostRecentTrainingStatus",), [1]),
    ],
)
def test_a_read_field_of_another_type_is_unexpected_shape(
    family: DayFamily, path: tuple[str | int, ...], value: Any
) -> None:
    document = _set(DOCUMENTS[family](), path, value)
    assert read(family, document).refusal is DayFileRefusal.UNEXPECTED_SHAPE


def test_unicode_digits_are_not_digits() -> None:
    """Les motifs des dates et des instants n'admettent que les chiffres ASCII."""
    for path, value in (
        (("startTimestampGMT",), "\uff12\uff10\uff10\uff11-03-09T23:00:00.0"),
        (("calendarDate",), "\uff12\uff10\uff10\uff11-03-10"),
    ):
        document = _set(heart_rate_document(), path, value)
        assert read(DayFamily.HEART_RATE, document).refusal is (
            DayFileRefusal.UNEXPECTED_SHAPE
        )


@pytest.mark.parametrize(
    ("family", "path"),
    [
        (DayFamily.HEART_RATE, ("calendarDate",)),
        (DayFamily.STRESS, ("calendarDate",)),
        (DayFamily.RESPIRATION, ("calendarDate",)),
        (DayFamily.SPO2, ("calendarDate",)),
        (DayFamily.DAILY_SUMMARY, ("calendarDate",)),
        (DayFamily.SLEEP, ("dailySleepDTO", "calendarDate")),
        (DayFamily.HRV, ("hrvSummary", "calendarDate")),
        (
            DayFamily.RESTING_HR,
            (
                "allMetrics",
                "metricsMap",
                "WELLNESS_RESTING_HEART_RATE",
                0,
                "calendarDate",
            ),
        ),
        (DayFamily.BODY_BATTERY, (0, "date")),
        (DayFamily.TRAINING_READINESS, (1, "calendarDate")),
    ],
)
def test_date_mismatch(family: DayFamily, path: tuple[str | int, ...]) -> None:
    document = _set(DOCUMENTS[family](), path, "2001-03-11")
    result = read(family, document)
    assert result.refusal is DayFileRefusal.DATE_MISMATCH
    assert result == FamilyRead(family, DAY, source(family), refusal=result.refusal)


def test_a_document_read_for_another_day_is_a_date_mismatch() -> None:
    other = DAY + timedelta(days=1)
    for family in DayFamily:
        result = read(family, DOCUMENTS[family](), other, source(family, other))
        expected = (
            None
            if family is DayFamily.TRAINING_STATUS
            else (DayFileRefusal.DATE_MISMATCH)
        )
        assert result.refusal is expected, family


def test_the_date_is_checked_before_the_other_fields() -> None:
    document = heart_rate_document()
    document["calendarDate"] = "2001-03-11"
    document["heartRateValues"] = "pas une liste"
    assert read(DayFamily.HEART_RATE, document).refusal is DayFileRefusal.DATE_MISMATCH
    sleep = sleep_document()
    sleep["dailySleepDTO"]["calendarDate"] = "2001-03-11"
    sleep["sleepLevels"] = 3
    assert read(DayFamily.SLEEP, sleep).refusal is DayFileRefusal.DATE_MISMATCH


def test_training_status_has_no_document_date() -> None:
    """Chaque bloc a sa date propre : aucune n'est comparée au jour du fichier."""
    later = DAY + timedelta(days=5)
    result = read(DayFamily.TRAINING_STATUS, training_status_document(), later)
    assert result.refusal is None
    assert result.status_block is not None
    assert result.status_block.day == DAY
    assert result.status_block.file_day == later


def test_training_status_with_one_key_takes_it_primary_or_not() -> None:
    for flag in (False, None, True):
        document = training_status_document(
            statuses={"9": status_entry(primaryTrainingDevice=flag, deviceId=9)},
            balances={"9": balance_entry(primaryTrainingDevice=flag, deviceId=9)},
        )
        result = read(DayFamily.TRAINING_STATUS, document)
        assert result.refusal is None
        assert result.status_block is not None
        assert result.load_balance_block is not None
        assert result.device_ids == (9,)


def test_training_status_with_two_keys_takes_the_primary() -> None:
    document = training_status_document(
        statuses={
            "8": status_entry(
                primaryTrainingDevice=False, deviceId=8, trainingStatus=1
            ),
            "7": status_entry(primaryTrainingDevice=True),
        }
    )
    result = read(DayFamily.TRAINING_STATUS, document)
    assert result.refusal is None
    assert result.status_block is not None
    assert result.status_block.status_code == 4
    assert result.device_ids == (DEVICE,)


@pytest.mark.parametrize("flags", [(False, False), (None, False), (True, True)])
@pytest.mark.parametrize("table", ["statuses", "balances"])
def test_training_status_with_two_keys_without_one_primary_is_refused(
    table: str, flags: tuple[bool | None, bool | None]
) -> None:
    make = status_entry if table == "statuses" else balance_entry
    entries = {
        "7": make(primaryTrainingDevice=flags[0]),
        "8": make(primaryTrainingDevice=flags[1], deviceId=8),
    }
    tables: dict[str, Any] = {table: entries}
    document = training_status_document(**tables)
    result = read(DayFamily.TRAINING_STATUS, document)
    assert result.refusal is DayFileRefusal.NO_PRIMARY_DEVICE


def test_the_status_table_is_read_before_the_balance_table() -> None:
    """La table des statuts, puis celle de l'équilibre, puis les champs des blocs : une
    forme fausse dans la table des statuts passe avant un principal manquant dans celle
    de l'équilibre, qui passe avant un champ d'un autre type dans un bloc."""
    no_primary = {
        "7": balance_entry(primaryTrainingDevice=False),
        "8": balance_entry(primaryTrainingDevice=False),
    }
    shape_first = training_status_document(
        statuses={"7": "pas un bloc"}, balances=no_primary
    )
    assert read(DayFamily.TRAINING_STATUS, shape_first).refusal is (
        DayFileRefusal.UNEXPECTED_SHAPE
    )
    field_after = training_status_document(
        statuses={"7": status_entry(trainingStatus="4")}, balances=no_primary
    )
    assert read(DayFamily.TRAINING_STATUS, field_after).refusal is (
        DayFileRefusal.NO_PRIMARY_DEVICE
    )
    primary_first = training_status_document(
        statuses={
            "7": status_entry(primaryTrainingDevice=False),
            "8": status_entry(primaryTrainingDevice=False),
        },
        balances={"7": balance_entry(monthlyLoadAnaerobic="x")},
    )
    assert read(DayFamily.TRAINING_STATUS, primary_first).refusal is (
        DayFileRefusal.NO_PRIMARY_DEVICE
    )


def test_a_refused_file_carries_nothing() -> None:
    document = sleep_document()
    document["sleepLevels"] = "x"
    result = read(DayFamily.SLEEP, document)
    assert result == FamilyRead(
        DayFamily.SLEEP,
        DAY,
        source(DayFamily.SLEEP),
        refusal=DayFileRefusal.UNEXPECTED_SHAPE,
    )
    assert result.empty is False
    assert result.fields == {}
    assert result.device_ids == ()


@pytest.mark.parametrize("document", [{}, []], ids=["objet", "liste"])
@pytest.mark.parametrize("family", list(DayFamily), ids=str)
def test_an_empty_document_is_an_absent_family_not_a_refusal(
    family: DayFamily, document: Any
) -> None:
    result = read(family, document)
    assert result.refusal is None
    assert result.empty is True
    assert result == FamilyRead(family, DAY, source(family), empty=True)


@pytest.mark.parametrize(
    ("family", "document"),
    [
        (
            DayFamily.HEART_RATE,
            {
                "userProfilePK": USER,
                "calendarDate": "2001-03-10",
                "startTimestampGMT": None,
                "startTimestampLocal": None,
                "endTimestampGMT": None,
                "endTimestampLocal": None,
                "heartRateValues": None,
                "restingHeartRate": None,
            },
        ),
        (
            DayFamily.SLEEP,
            {
                "dailySleepDTO": {
                    "id": None,
                    "userProfilePK": USER,
                    "calendarDate": "2001-03-10",
                    "sleepStartTimestampGMT": None,
                    "sleepEndTimestampGMT": None,
                    "sleepStartTimestampLocal": None,
                    "sleepEndTimestampLocal": None,
                    "sleepVersion": 2,
                    "dailyNapDTOS": [],
                },
                "sleepLevels": None,
                "sleepHeartRate": [],
                "respirationVersion": 200,
            },
        ),
        (DayFamily.HRV, {"hrvSummary": None, "hrvReadings": []}),
        (DayFamily.BODY_BATTERY, [{"date": "2001-03-10", "charged": None}]),
        (DayFamily.RESTING_HR, resting_hr_document(value=None)),
        (
            DayFamily.TRAINING_STATUS,
            training_status_document(statuses={}, balances={})
            | {"mostRecentVO2Max": None},
        ),
    ],
    ids=["heart_rate", "sleep", "hrv", "body_battery", "resting_hr", "training_status"],
)
def test_a_document_without_content_is_empty(family: DayFamily, document: Any) -> None:
    result = read(family, document)
    assert result.refusal is None
    assert result.empty is True


def test_versions_and_discards_alone_are_not_content() -> None:
    versions_only = {"calendarDate": "2001-03-10", "respirationVersion": 200}
    result = read(DayFamily.RESPIRATION, versions_only)
    assert result.versions.respiration_version == 200
    assert result.empty is True
    discards_only = {
        "calendarDate": "2001-03-10",
        "heartRateValues": [[ms(START), None]],
        "restingHeartRate": 300,
    }
    result = read(DayFamily.HEART_RATE, discards_only)
    assert result.discards
    assert result.empty is True
    assert result.fields


def test_entries_of_another_device_are_content() -> None:
    document = [readiness_entry(primaryActivityTracker=False)]
    result = read(DayFamily.TRAINING_READINESS, document)
    assert result.readiness == ()
    assert result.readiness_non_primary == 1
    assert result.empty is False


def test_a_refused_block_alone_is_content() -> None:
    """Un ``training_status`` dont le seul bloc est sans date propre (refusé, compté)
    n'est pas vide : la famille est présente ce jour-là."""
    document = training_status_document(
        statuses={"7": status_entry(calendarDate=None)}, balances={}
    ) | {"mostRecentVO2Max": None}
    result = read(DayFamily.TRAINING_STATUS, document)
    assert result.refused_blocks == (TrainingStatusKind.STATUS,)
    assert result.status_block is None
    assert result.empty is False


def test_instants_in_milliseconds_are_exact() -> None:
    document = heart_rate_document()
    exact = ms(START) + 1
    document["heartRateValues"] = [[exact, 55], [exact + 999, 56]]
    points = read(DayFamily.HEART_RATE, document).day_series.heart_rate
    assert points is not None
    assert [round(epoch * 1000) for epoch in points.epoch_s] == [exact, exact + 999]
    assert points.epoch_s[0] == exact / 1000
    night = read(DayFamily.SLEEP, sleep_document()).night
    assert night is not None
    assert night.start == NIGHT_START


@pytest.mark.parametrize(
    ("fraction", "extra_ms"),
    [("", 0), (".0", 0), (".5", 500), (".25", 250), (".125", 125), (".005", 5)],
)
def test_text_instants_with_and_without_fraction(fraction: str, extra_ms: int) -> None:
    """Les trois formes de la source : sans fraction, fraction d'un chiffre, fraction
    de trois chiffres (et de deux), lues comme GMT."""
    document = sleep_document()
    document["sleepLevels"][0]["startGMT"] = gmt_text(NIGHT_START, fraction)
    segments = read(DayFamily.SLEEP, document).night_segments
    assert segments is not None
    assert round(segments.start_epoch_s[0] * 1000) == ms(NIGHT_START) + extra_ms
    entry = readiness_entry(
        timestamp=gmt_text(at(DAY, 7, 5), fraction),
        timestampLocal=local_text(at(DAY, 7, 5), fraction),
    )
    (kept,) = read(DayFamily.TRAINING_READINESS, [entry]).readiness
    assert kept.instant == at(DAY, 7, 5) + timedelta(milliseconds=extra_ms)


def test_offset_is_local_minus_gmt_on_each_form() -> None:
    """Millisecondes d'heure murale (nuit), textes ``…Local`` (fenêtre, entrées),
    minutes (siestes)."""
    sleep = read(DayFamily.SLEEP, sleep_document())
    assert sleep.night is not None
    assert sleep.night.start.utcoffset() == timedelta(hours=1)
    assert sleep.naps[0].start.utcoffset() == timedelta(hours=1)
    assert sleep.naps[0].start == at(DAY, 14)
    window = read(DayFamily.HEART_RATE, heart_rate_document()).window
    assert window is not None
    assert window.start == START
    assert window.start.utcoffset() == timedelta(hours=1)
    (entry, _) = read(
        DayFamily.TRAINING_READINESS, training_readiness_document()
    ).readiness
    assert entry.instant.utcoffset() == timedelta(hours=1)
    west = sleep_document()
    west["dailySleepDTO"]["dailyNapDTOS"][0]["napStartTimeOffset"] = -300
    west["dailySleepDTO"]["dailyNapDTOS"][0]["napEndTimeOffset"] = -300
    nap = read(DayFamily.SLEEP, west).naps[0]
    assert nap.start.utcoffset() == timedelta(hours=-5)
    assert nap.start == at(DAY, 14)


def test_offset_at_the_change_of_time() -> None:
    """La nuit du 25 mars 2001 : 23 h (+01:00) → 7 h (+02:00), chaque borne dans son
    décalage ; la fenêtre du jour garde un seul décalage, fin GMT = début + 24 h ; une
    entrée du matin est à +02:00."""
    document = sleep_document(SPRING_DAY)
    end = at(SPRING_DAY, 7, offset=PLUS2)
    document["dailySleepDTO"]["sleepEndTimestampGMT"] = ms(end)
    document["dailySleepDTO"]["sleepEndTimestampLocal"] = wall_ms(end)
    night = read(DayFamily.SLEEP, document, SPRING_DAY).night
    assert night is not None
    assert night.start.utcoffset() == timedelta(hours=1)
    assert night.end.utcoffset() == timedelta(hours=2)
    assert night.end - night.start == timedelta(hours=7)
    window = read(
        DayFamily.HEART_RATE, heart_rate_document(SPRING_DAY), SPRING_DAY
    ).window
    assert window is not None
    assert window.start.utcoffset() == timedelta(hours=1)
    assert window.data_end - window.start == timedelta(days=1)
    morning = at(SPRING_DAY, 8, offset=PLUS2)
    entry = readiness_entry(
        SPRING_DAY, timestamp=gmt_text(morning), timestampLocal=local_text(morning)
    )
    (kept,) = read(DayFamily.TRAINING_READINESS, [entry], SPRING_DAY).readiness
    assert kept.instant.utcoffset() == timedelta(hours=2)


@pytest.mark.parametrize(
    ("offset_s", "kept"),
    [(-43200, True), (-43201, False), (50400, True), (50401, False), (0, True)],
)
def test_night_offsets_at_the_bounds_of_their_range(offset_s: int, kept: bool) -> None:
    document = sleep_document()
    dto = document["dailySleepDTO"]
    dto["sleepStartTimestampLocal"] = dto["sleepStartTimestampGMT"] + offset_s * 1000
    dto["sleepEndTimestampLocal"] = dto["sleepEndTimestampGMT"] + offset_s * 1000
    result = read(DayFamily.SLEEP, document)
    if kept:
        assert result.night is not None
        assert result.night.start.utcoffset() == timedelta(seconds=offset_s)
    else:
        assert result.night is None
        assert _discards(result) == {("night", PointDiscard.OUT_OF_RANGE): 1}


def test_an_offset_in_fractions_of_a_second_is_out_of_range() -> None:
    document = sleep_document()
    dto = document["dailySleepDTO"]
    dto["sleepStartTimestampLocal"] = dto["sleepStartTimestampGMT"] + 3600500
    result = read(DayFamily.SLEEP, document)
    assert result.night is None
    assert _discards(result) == {("night", PointDiscard.OUT_OF_RANGE): 1}


def _nap_document(**changes: Any) -> dict[str, Any]:
    document = sleep_document()
    document["dailySleepDTO"]["dailyNapDTOS"][0].update(changes)
    return document


@pytest.mark.parametrize(
    ("minutes", "kept"), [(-720, True), (-721, False), (840, True), (841, False)]
)
def test_nap_offsets_in_minutes_at_their_bounds(minutes: int, kept: bool) -> None:
    result = read(
        DayFamily.SLEEP,
        _nap_document(napStartTimeOffset=minutes, napEndTimeOffset=minutes),
    )
    if kept:
        (nap,) = result.naps
        assert nap.start.utcoffset() == timedelta(minutes=minutes)
    else:
        assert result.naps == ()
        assert _discards(result) == {("naps", PointDiscard.OUT_OF_RANGE): 1}


@pytest.mark.parametrize(
    ("minutes", "kept"),
    [(60.0, True), (840.0, True), (-720.0, True), (60.5, False), (0.5, False)],
)
def test_nap_offsets_are_whole_minutes(minutes: float, kept: bool) -> None:
    """Un décalage de sieste est un nombre entier de minutes : un flottant de valeur
    entière est admis (``60.0`` vaut 60 min) ; ``60.5`` (3 630 s, des secondes
    entières) et ``0.5`` (30 s) sont hors de leur plage (``out_of_range``)."""
    result = read(DayFamily.SLEEP, _nap_document(napEndTimeOffset=minutes))
    if kept:
        (nap,) = result.naps
        assert nap.end.utcoffset() == timedelta(minutes=minutes)
    else:
        assert result.naps == ()
        assert _discards(result) == {("naps", PointDiscard.OUT_OF_RANGE): 1}


def test_status_timestamp_is_in_utc() -> None:
    """la source ne donne que les millisecondes GMT."""
    block = read(DayFamily.TRAINING_STATUS, training_status_document()).status_block
    assert block is not None
    assert block.timestamp is not None
    assert block.timestamp.utcoffset() == timedelta(0)
    assert block.timestamp == at(DAY, 12)
    assert block.proper_instant == block.timestamp


@pytest.mark.parametrize("family", [DayFamily.RESPIRATION, DayFamily.SPO2])
def test_tomorrow_fields_are_present_and_ignored(family: DayFamily) -> None:
    document = DOCUMENTS[family]()
    assert any("tomorrow" in key for key in document)
    result = read(family, document)
    assert not any("tomorrow" in path.lower() for path in result.fields)
    night_end = _copies(result)["sleepEndTimestampGMT"]
    assert night_end == ms(at(DAY, 7)) / 1000
    if family is DayFamily.RESPIRATION:
        assert result.respiration is not None
        assert result.respiration.avg_sleep_breaths_per_min == 13.0
    else:
        assert result.spo2 is not None
        assert result.spo2.avg_sleep_spo2_percent == 95.0


def test_sleep_night_naps_series_and_copies() -> None:
    """Le document ``sleep`` : sa nuit (bornes, durées, score, confirmation), sa
    sieste, ses segments, de codes 1 puis 0 : léger puis profond, ses séries de la nuit
    avec leurs codes, et ses copies."""
    result = read(DayFamily.SLEEP, sleep_document())
    night = result.night
    assert night is not None
    assert (night.start, night.end) == (NIGHT_START, at(DAY, 7))
    assert (night.deep_s, night.light_s, night.rem_s) == (3600.0, 16200.0, 5400.0)
    assert (night.awake_s, night.unmeasurable_s) == (1800.0, 1800.0)
    assert night.confirmation == "enhanced_confirmed_final"
    assert (night.window_confirmed, night.from_device, night.rem_capable) == (
        True,
        True,
        True,
    )
    assert night.sleep_score == 80
    assert night.avg_stress == 12.0
    assert night.avg_heart_rate_bpm == 50.0
    assert night.body_battery_change == 50
    assert night.restless_moments == 20
    assert night.skin_temperature_deviation_c == -0.25
    assert night.segments == ()
    assert night.series == NightSeries(None, None, None, None, None, None, None)
    (nap,) = result.naps
    assert (nap.start, nap.end, nap.sleep_s, nap.nap_source_code) == (
        at(DAY, 14),
        at(DAY, 14, 30),
        1500.0,
        1,
    )
    segments = result.night_segments
    assert segments is not None
    assert segments.stage == (SleepStage.LIGHT, SleepStage.DEEP)
    start = ms(NIGHT_START) / 1000
    assert segments.start_epoch_s == (start, start + 3600)
    assert segments.end_epoch_s == (start + 3600, start + 7200)
    series = result.night_series
    assert series.heart_rate is not None
    assert series.heart_rate.heart_rate_bpm == (52.0, 48.0)
    assert series.stress is not None
    assert (series.stress.stress_level, series.stress.code) == ((10, None), (None, -1))
    assert series.body_battery is not None
    assert series.body_battery.level == (30, 80)
    assert series.body_battery.status == (None, None)
    assert series.hrv is not None
    assert series.hrv.hrv_ms == (45.0, 50.0)
    assert series.respiration is not None
    assert series.respiration.breaths_per_min == (14.0, None)
    assert series.respiration.code == (None, -2)
    assert series.spo2 is not None
    assert series.spo2.spo2_percent == (95.0, 94.0)
    assert series.restless_moments is not None
    assert series.restless_moments.count == (1,)
    assert _copies(result) == {
        "restingHeartRate": 48.0,
        "avgOvernightHrv": 50.0,
        "hrvStatus": "BALANCED",
        "dailySleepDTO.averageRespirationValue": 13.0,
        "dailySleepDTO.averageSpO2Value": 95.0,
        "wellnessSpO2SleepSummaryDTO.averageSPO2": 95.0,
    }
    assert result.versions.sleep_version == 2
    assert result.versions.sleep_respiration_version == 200
    assert result.has_detail is True


def test_sleep_rem_is_absent_when_the_device_does_not_detect_it() -> None:
    document = sleep_document()
    document["dailySleepDTO"]["deviceRemCapable"] = False
    document["dailySleepDTO"]["remSleepSeconds"] = 0
    night = read(DayFamily.SLEEP, document).night
    assert night is not None
    assert night.rem_s is None
    assert night.rem_capable is False
    assert night.measured_sleep_s == 19800.0


def test_sleep_declared_night_and_provisional_window_are_read_as_given() -> None:
    document = sleep_document()
    document["dailySleepDTO"]["sleepFromDevice"] = False
    document["dailySleepDTO"]["sleepWindowConfirmed"] = False
    document["dailySleepDTO"]["sleepWindowConfirmationType"] = "manually_confirmed"
    night = read(DayFamily.SLEEP, document).night
    assert night is not None
    assert (night.from_device, night.window_confirmed) == (False, False)
    assert night.confirmation == "manually_confirmed"


def test_sleep_without_night_keeps_its_naps_and_series() -> None:
    document = sleep_document()
    for key in (
        "sleepStartTimestampGMT",
        "sleepEndTimestampGMT",
        "sleepStartTimestampLocal",
        "sleepEndTimestampLocal",
    ):
        document["dailySleepDTO"][key] = None
    result = read(DayFamily.SLEEP, document)
    assert result.night is None
    assert len(result.naps) == 1
    assert result.night_series.heart_rate is not None
    assert result.night_segments is not None
    assert ("night", PointDiscard.NULL_VALUE) not in _discards(result)


def test_hrv_summary_and_copies() -> None:
    result = read(DayFamily.HRV, hrv_document())
    summary = result.hrv
    assert summary is not None
    assert (summary.last_night_avg_ms, summary.last_night_5min_high_ms) == (50.0, 70.0)
    assert (summary.weekly_avg_ms, summary.status) == (48.0, "BALANCED")
    assert summary.baseline_balanced_low_ms == 40.0
    assert summary.baseline_balanced_upper_ms == 60.0
    assert summary.baseline_low_upper_ms == 35.0
    assert summary.baseline_marker_value == 0.5
    copies = _copies(result)
    assert copies["sleepStartTimestampGMT"] == ms(NIGHT_START) / 1000
    assert copies["sleepEndTimestampGMT"] == ms(at(DAY, 7)) / 1000
    readings = copies["hrvReadings"]
    start = ms(NIGHT_START) / 1000
    assert readings.epoch_s == (start + 300, start + 600)
    assert readings.hrv_ms == (45.0, 50.0)
    assert [copy.quantity for copy in result.copies] == [
        "night.start",
        "night.end",
        "night.series.hrv",
    ]
    assert result.has_detail is True


def test_resting_hr() -> None:
    result = read(DayFamily.RESTING_HR, resting_hr_document())
    assert result.resting_hr is not None
    assert result.resting_hr.resting_hr_bpm == 48.0
    assert result.resting_hr.source == source(DayFamily.RESTING_HR)


def test_a_second_resting_hr_entry_is_a_duplicate() -> None:
    document = resting_hr_document()
    entries = document["allMetrics"]["metricsMap"]["WELLNESS_RESTING_HEART_RATE"]
    entries.append({"value": 50, "calendarDate": "2001-03-10"})
    result = read(DayFamily.RESTING_HR, document)
    assert result.resting_hr is not None
    assert result.resting_hr.resting_hr_bpm == 48.0
    assert _discards(result) == {
        (
            "allMetrics.metricsMap.WELLNESS_RESTING_HEART_RATE",
            PointDiscard.DUPLICATE_INSTANT,
        ): 1
    }


def test_heart_rate_window_series_and_copy() -> None:
    result = read(DayFamily.HEART_RATE, heart_rate_document())
    assert result.window is not None
    assert result.window.start == START
    assert result.window.data_end == START + timedelta(days=1)
    points = result.day_series.heart_rate
    assert points is not None
    assert points.epoch_s == (ms(START) / 1000, ms(START) / 1000 + 43200)
    assert points.heart_rate_bpm == (55.0, 90.0)
    assert _copies(result) == {"restingHeartRate": 48.0}


def test_heart_rate_window_end_is_the_gmt_end_even_when_truncated() -> None:
    """La fin locale de ``heart_rate`` peut dire minuit quand la fin GMT dit autre
    chose (jour tronqué) : seule la fin GMT est lue."""
    document = heart_rate_document()
    document["endTimestampGMT"] = gmt_text(at(DAY, 12))
    document["endTimestampLocal"] = local_text(START + timedelta(days=1))
    window = read(DayFamily.HEART_RATE, document).window
    assert window is not None
    assert window.data_end == at(DAY, 12)


def test_body_battery_copies_and_ignored_events() -> None:
    result = read(DayFamily.BODY_BATTERY, body_battery_document())
    assert _copies(result) == {"[*].charged": 60, "[*].drained": 55}
    assert result.day_series == read(DayFamily.HRV, {}).day_series
    assert not any("Event" in path for path in result.fields)
    assert set(result.fields) == {"[*]"}
    assert "bodyBatteryActivityEvent" not in result.fields["[*]"]
    assert "feedback" not in result.fields["[*]"].lower()


def test_a_second_body_battery_element_is_a_duplicate() -> None:
    document = [*body_battery_document(), {"date": "2001-03-10", "charged": 10}]
    result = read(DayFamily.BODY_BATTERY, document)
    assert _copies(result)["[*].charged"] == 60
    assert _discards(result) == {("[*]", PointDiscard.DUPLICATE_INSTANT): 1}


def test_stress_series_body_battery_and_copies() -> None:
    result = read(DayFamily.STRESS, stress_document())
    assert result.window is not None
    stress = result.day_series.stress
    assert stress is not None
    assert stress.stress_level == (20, None)
    assert stress.code == (None, -2)
    battery = result.day_series.body_battery
    assert battery is not None
    assert battery.level == (40, 41)
    assert battery.status == (BodyBatteryStatus.MEASURED, BodyBatteryStatus.MODELED)
    assert result.versions.body_battery_series_versions == (3,)
    assert _copies(result) == {"avgStressLevel": 25, "maxStressLevel": 90}


def test_stress_average_copy_carries_a_known_code() -> None:
    for written in (-1, -1.0):
        document = stress_document()
        document["avgStressLevel"] = written
        result = read(DayFamily.STRESS, document)
        assert _copies(result)["avgStressLevel"] == -1
        assert result.unknown_codes == ()
    document = stress_document()
    document["avgStressLevel"] = -3
    result = read(DayFamily.STRESS, document)
    assert "avgStressLevel" not in _copies(result)
    assert [(c.field_path, c.code) for c in result.unknown_codes] == [
        ("avgStressLevel", "-3")
    ]


def test_respiration() -> None:
    result = read(DayFamily.RESPIRATION, respiration_document())
    summary = result.respiration
    assert summary is not None
    assert summary.avg_sleep_breaths_per_min == 13.0
    assert summary.avg_waking_breaths_per_min == 15.0
    assert summary.highest_breaths_per_min == 22.0
    assert summary.lowest_breaths_per_min == 10.0
    series = result.day_series.respiration
    assert series is not None
    assert series.breaths_per_min == (15.0, None)
    assert series.code == (None, -1)
    assert result.versions.respiration_version == 200
    assert result.window is not None


def test_spo2() -> None:
    result = read(DayFamily.SPO2, spo2_document())
    summary = result.spo2
    assert summary is not None
    assert (summary.avg_sleep_spo2_percent, summary.average_spo2_percent) == (
        95.0,
        96.0,
    )
    assert summary.lowest_spo2_percent == 90.0
    series = result.day_series.spo2
    assert series is not None
    assert series.spo2_percent == (96.0,)
    assert series.epoch_s == (ms(START) / 1000 + 3600,)
    assert result.has_detail is False


def test_daily_summary() -> None:
    result = read(DayFamily.DAILY_SUMMARY, daily_summary_document())
    assert result.window is not None
    assert result.window.start == START
    assert result.wellness_data is True
    stress = result.stress
    assert stress is not None
    assert (stress.average_level, stress.average_level_code, stress.max_level) == (
        25,
        None,
        90,
    )
    assert stress.rest_duration_s == 36000.0
    assert stress.stress_duration_s == 27000.0
    assert stress.total_duration_s == 68400.0
    battery = result.body_battery
    assert battery is not None
    assert (battery.charged, battery.drained, battery.highest, battery.lowest) == (
        60,
        55,
        90,
        20,
    )
    assert (battery.at_wake, battery.during_sleep) == (85, 45)
    totals = result.activity_totals
    assert totals is not None
    assert totals.steps == 10000
    assert (totals.moderate_intensity_s, totals.vigorous_intensity_s) == (1200.0, 600.0)
    assert (totals.floors_ascended_m, totals.floors_descended_m) == (30.5, 27.5)
    assert totals.average_altitude_m == 1200.0
    assert result.versions.summary_respiration_version == 200
    assert result.versions.summary_body_battery_version == 3
    assert _copies(result) == {
        "restingHeartRate": 48.0,
        "avgWakingRespirationValue": 15.0,
        "highestRespirationValue": 22.0,
        "lowestRespirationValue": 10.0,
        "averageSpo2": 96.0,
        "lowestSpo2": 90.0,
    }
    assert result.device_ids == ()


def test_daily_summary_stress_average_code() -> None:
    document = daily_summary_document()
    document["averageStressLevel"] = -2.0
    stress = read(DayFamily.DAILY_SUMMARY, document).stress
    assert stress is not None
    assert (stress.average_level, stress.average_level_code) == (None, -2)


def test_daily_summary_without_wellness_data() -> None:
    document = daily_summary_document()
    document["includesWellnessData"] = False
    assert read(DayFamily.DAILY_SUMMARY, document).wellness_data is False
    del document["includesWellnessData"]
    assert read(DayFamily.DAILY_SUMMARY, document).wellness_data is None


def test_a_summary_without_any_value_is_absent() -> None:
    document = daily_summary_document()
    for key in list(document):
        if "stress" in key.lower() or (
            key.startswith("bodyBattery") and key != "bodyBatteryVersion"
        ):
            document[key] = None
    result = read(DayFamily.DAILY_SUMMARY, document)
    assert result.stress is None
    assert result.body_battery is None
    assert result.activity_totals is not None


def test_training_readiness_entries() -> None:
    result = read(DayFamily.TRAINING_READINESS, training_readiness_document())
    morning, evening = result.readiness
    assert morning.instant == at(DAY, 7, 5)
    assert evening.instant == at(DAY, 18)
    assert morning.input_context == "AFTER_WAKEUP_RESET"
    assert evening.input_context == "UPDATE_REALTIME_VARIABLES"
    assert (morning.score, morning.level, morning.valid_sleep) == (70, "MODERATE", True)
    assert (morning.sleep_score, morning.hrv_weekly_average_ms, morning.acute_load) == (
        80,
        48.0,
        300.0,
    )
    assert result.readiness_non_primary == 0
    assert result.device_ids == (DEVICE,)


@pytest.mark.parametrize("flag", [False, None, "absent"])
def test_training_readiness_entries_of_another_device_are_counted(flag: Any) -> None:
    other = readiness_entry(deviceId=8, timestamp=gmt_text(at(DAY, 9)))
    if flag == "absent":
        del other["primaryActivityTracker"]
    else:
        other["primaryActivityTracker"] = flag
    result = read(DayFamily.TRAINING_READINESS, [readiness_entry(), other])
    assert len(result.readiness) == 1
    assert result.readiness_non_primary == 1
    assert result.device_ids == (DEVICE,)


def test_training_status_blocks() -> None:
    result = read(DayFamily.TRAINING_STATUS, training_status_document())
    status = result.status_block
    assert status is not None
    assert (status.day, status.file_day, status.status_code) == (DAY, DAY, 4)
    assert (status.acute_load, status.chronic_load) == (300.0, 320.0)
    assert (status.acute_chronic_ratio, status.acwr_percent) == (0.9, 50.0)
    assert (status.min_chronic_load, status.max_chronic_load) == (240.5, 450.5)
    assert (status.acwr_status, status.paused, status.fitness_trend) == (
        "OPTIMAL",
        False,
        2,
    )
    balance = result.load_balance_block
    assert balance is not None
    assert balance.proper_instant is None
    assert (balance.monthly_aerobic_low, balance.monthly_anaerobic_target_max) == (
        400.5,
        100.0,
    )
    vo2 = result.vo2_max_block
    assert vo2 is not None
    assert (vo2.day, vo2.vo2_max_precise_ml_kg_min, vo2.vo2_max_ml_kg_min) == (
        DAY - timedelta(days=1),
        55.5,
        56.0,
    )
    heat = result.heat_block
    assert heat is not None
    assert (heat.day, heat.heat_acclimation_percent, heat.heat_trend) == (
        DAY - timedelta(days=2),
        20.0,
        "ACCLIMATIZING",
    )
    altitude = result.altitude_block
    assert altitude is not None
    assert (
        altitude.day,
        altitude.acclimation_altitude_m,
        altitude.current_altitude_m,
    ) == (
        DAY - timedelta(days=3),
        1500.0,
        1600.0,
    )
    assert result.refused_blocks == ()
    assert result.device_ids == (DEVICE,)


def test_training_status_block_without_its_date_is_refused_and_counted() -> None:
    document = training_status_document(statuses={"7": status_entry(calendarDate=None)})
    document["mostRecentVO2Max"]["generic"]["calendarDate"] = None
    result = read(DayFamily.TRAINING_STATUS, document)
    assert result.status_block is None
    assert result.vo2_max_block is None
    assert result.refused_blocks == (
        TrainingStatusKind.STATUS,
        TrainingStatusKind.VO2_MAX,
    )
    assert result.load_balance_block is not None


def test_a_missing_training_status_table_is_no_block() -> None:
    document = training_status_document()
    document["mostRecentTrainingStatus"] = None
    result = read(DayFamily.TRAINING_STATUS, document)
    assert result.status_block is None
    assert result.refused_blocks == ()
    assert result.load_balance_block is not None


def test_copy_fields_name_quantities_of_a_day() -> None:
    """Chaque grandeur recopiée est un chemin de ``DayRecord`` : un champ d'un résumé
    (``QUANTITY_SUPPORTS``), une borne de la nuit, la série HRV de la nuit."""
    for copies in COPY_FIELDS.values():
        for copy in copies:
            assert copy.quantity in QUANTITY_SUPPORTS or copy.quantity in (
                "night.start",
                "night.end",
                "night.series.hrv",
            ), copy


def test_copies_follow_the_table() -> None:
    for family in COPY_FIELDS:
        result = read(family, DOCUMENTS[family]())
        assert [(c.quantity, c.field_path) for c in result.copies] == [
            (c.quantity, c.path) for c in COPY_FIELDS[family]
        ], family


def test_a_copy_out_of_its_range_is_discarded() -> None:
    document = daily_summary_document()
    document["restingHeartRate"] = 300
    document["lowestSpo2"] = 40
    result = read(DayFamily.DAILY_SUMMARY, document)
    copies = _copies(result)
    assert "restingHeartRate" not in copies
    assert "lowestSpo2" not in copies
    assert _discards(result) == {
        ("restingHeartRate", PointDiscard.OUT_OF_RANGE): 1,
        ("lowestSpo2", PointDiscard.OUT_OF_RANGE): 1,
    }


def test_fields_keep_a_value_and_drop_an_identifier() -> None:
    fields = read(DayFamily.HEART_RATE, heart_rate_document()).fields
    assert fields["maxHeartRate"] == "150"
    assert fields["calendarDate"] == '"2001-03-10"'
    assert "userProfilePK" not in fields
    summary = read(DayFamily.DAILY_SUMMARY, daily_summary_document()).fields
    for excluded in ("uuid", "displayName", "userDailySummaryId", "totalKilocalories"):
        assert excluded not in summary
    assert "includesCalorieConsumedData" not in summary
    assert summary["rule.typeKey"] == '"public"'


def test_fields_aggregate_each_list_without_its_identifiers() -> None:
    fields = read(DayFamily.SLEEP, sleep_document()).fields
    naps = json.loads(fields["dailySleepDTO.dailyNapDTOS[*]"])
    assert naps[0]["napTimeSec"] == 1500
    assert "deviceId" not in naps[0]
    assert "userProfilePK" not in naps[0]
    assert "napFeedback" not in naps[0]
    epochs = json.loads(fields["wellnessEpochSPO2DataDTOList[*]"])
    assert all("deviceId" not in epoch for epoch in epochs)
    assert "sleepLevels[*]" in fields
    for excluded in (
        "dailySleepDTO.sleepNeed",
        "dailySleepDTO.sleepNeed.deviceId",
        "sleepMovement[*]",
        "dailySleepDTO.sleepScoreFeedback",
        "dailySleepDTO.id",
    ):
        assert excluded not in fields
    assert not any(path.startswith("dailySleepDTO.sleepAlignment") for path in fields)
    readiness = read(DayFamily.TRAINING_READINESS, training_readiness_document()).fields
    assert set(readiness) == {"[*]"}
    assert "deviceId" not in readiness["[*]"]
    status = read(DayFamily.TRAINING_STATUS, training_status_document()).fields
    assert (
        "mostRecentTrainingStatus.latestTrainingStatusData.<n>.trainingStatus" in status
    )
    assert not any(".7." in path or path.endswith(".7") for path in status)
    assert not any("recordedDevices" in path for path in status)


@pytest.mark.parametrize(
    ("family", "make", "keep", "lists"),
    [
        (
            DayFamily.HEART_RATE,
            heart_rate_document,
            "heartRateValues",
            ("heartRateValues",),
        ),
        (
            DayFamily.STRESS,
            stress_document,
            "stressValuesArray",
            ("stressValuesArray", "bodyBatteryValuesArray"),
        ),
        (
            DayFamily.STRESS,
            stress_document,
            "bodyBatteryValuesArray",
            ("stressValuesArray", "bodyBatteryValuesArray"),
        ),
        (
            DayFamily.RESPIRATION,
            respiration_document,
            "respirationValuesArray",
            ("respirationValuesArray",),
        ),
        (DayFamily.HRV, hrv_document, "hrvReadings", ("hrvReadings",)),
        *[
            (DayFamily.SLEEP, sleep_document, key, _SLEEP_SERIES)
            for key in _SLEEP_SERIES
            if key != "wellnessEpochSPO2DataDTOList"
        ],
    ],
)
def test_has_detail_by_a_single_series(
    family: DayFamily,
    make: Callable[[], dict[str, Any]],
    keep: str,
    lists: tuple[str, ...],
) -> None:
    document = make()
    for key in lists:
        if key != keep:
            document[key] = []
    assert read(family, document).has_detail is True
    document[keep] = []
    assert read(family, document).has_detail is False


def test_no_detail_with_spo2_only() -> None:
    document = sleep_document()
    for key in _SLEEP_SERIES:
        if key != "wellnessEpochSPO2DataDTOList":
            document[key] = []
    result = read(DayFamily.SLEEP, document)
    assert result.night_series.spo2 is not None
    assert result.has_detail is False
    assert read(DayFamily.SPO2, spo2_document()).has_detail is False


def test_a_series_whose_points_are_all_discarded_is_no_detail() -> None:
    document = heart_rate_document()
    document["heartRateValues"] = [[ms(START), None], [ms(START) + 60000, 0]]
    result = read(DayFamily.HEART_RATE, document)
    assert result.day_series.heart_rate is None
    assert result.has_detail is False


def test_device_ids_stay_in_memory() -> None:
    result = read(DayFamily.SLEEP, sleep_document())
    assert result.device_ids == (DEVICE,)
    assert "device_ids" not in repr(result)
    assert not any("deviceId" in path for path in result.fields)
    assert "deviceId" not in "".join(result.fields.values())


def test_the_pieces_fit_a_day_record() -> None:
    """La fenêtre, la nuit (ses séries et segments remis en secondes depuis son début),
    les entrées entrent dans un ``DayRecord`` sans erreur de contrat."""
    sleep = read(DayFamily.SLEEP, sleep_document())
    assert sleep.night is not None
    assert sleep.night_segments is not None
    begin = sleep.night.start.timestamp()
    segments = tuple(
        SleepSegment(start - begin, end - begin, stage)
        for start, end, stage in zip(
            sleep.night_segments.start_epoch_s,
            sleep.night_segments.end_epoch_s,
            sleep.night_segments.stage,
            strict=True,
        )
    )
    heart = sleep.night_series.heart_rate
    assert heart is not None
    series = NightSeries(
        HeartRateSeries(
            tuple(t - begin for t in heart.epoch_s), heart.heart_rate_bpm, sleep.source
        ),
        None,
        None,
        None,
        None,
        None,
        None,
    )
    night = dataclasses.replace(sleep.night, segments=segments, series=series)
    window = read(DayFamily.DAILY_SUMMARY, daily_summary_document()).window
    assert window is not None
    readiness = read(DayFamily.TRAINING_READINESS, training_readiness_document())
    record = DayRecord(
        day=DAY,
        window_start=window.start,
        data_end=window.data_end,
        window_family=DayFamily.DAILY_SUMMARY,
        wellness_data=True,
        state=DayState.COMPLETE,
        reference_export="garmin_a",
        night=night,
        naps=sleep.naps,
        resting_hr=None,
        hrv=None,
        respiration=None,
        spo2=None,
        stress=None,
        body_battery=None,
        activity_totals=None,
        series=DaySeries(None, None, None, None, None),
        readiness=readiness.readiness,
        versions=sleep.versions,
        device_ranks=(1,),
    )
    assert isinstance(record.night, Night)


def test_read_values_are_not_recomputed_from_the_series() -> None:
    """Un résumé reste celui de Garmin, quelle que soit la série."""
    document = stress_document()
    document["stressValuesArray"] = [[ms(START), 5]]
    result = read(DayFamily.STRESS, document)
    assert _copies(result) == {"avgStressLevel": 25, "maxStressLevel": 90}
    sleep = sleep_document()
    sleep["sleepHeartRate"] = [{"startGMT": ms(NIGHT_START), "value": 100}]
    night = read(DayFamily.SLEEP, sleep).night
    assert night is not None
    assert night.avg_heart_rate_bpm == 50.0


def test_discards_are_sorted_by_path_and_reason() -> None:
    document = heart_rate_document()
    document["heartRateValues"] = [
        [ms(START), 0],
        [None, 60],
        [ms(START) + 60000, None],
        [ms(START) + 120000, 60],
        [ms(START) + 120000, 61],
    ]
    document["restingHeartRate"] = 10
    result = read(DayFamily.HEART_RATE, document)
    assert [(d.series_path, d.reason, d.count) for d in result.discards] == [
        ("heartRateValues", PointDiscard.DUPLICATE_INSTANT, 1),
        ("heartRateValues", PointDiscard.NULL_VALUE, 2),
        ("heartRateValues", PointDiscard.OUT_OF_RANGE, 1),
        ("restingHeartRate", PointDiscard.OUT_OF_RANGE, 1),
    ]
    assert all(isinstance(d, PointDiscardCount) for d in result.discards)


def test_a_window_family_window_starts_on_its_day() -> None:
    for family in DAY_WINDOW_FAMILIES:
        window = read(family, DOCUMENTS[family]()).window
        assert window is not None, family
        assert window.start.date() == DAY
        assert window.start.utcoffset() == timedelta(hours=1)


@pytest.mark.parametrize(
    ("value", "expected"), [(1, 1), (1.0, 1), (-2.0, -2), (0.0, 0), (None, None)]
)
def test_the_nap_source_is_read_by_its_value(value: Any, expected: int | None) -> None:
    """Un code s'écrit en entier ou en flottant de valeur entière : ``1.0`` est le code
    ``1``, rendu en entier, sans écart compté."""
    result = read(DayFamily.SLEEP, _nap_document(napSource=value))
    (nap,) = result.naps
    assert nap.nap_source_code == expected
    assert type(nap.nap_source_code) is (int if expected is not None else type(None))
    assert result.discards == ()


@pytest.mark.parametrize(
    ("value", "expected"), [(2, 2), (2.0, 2), (-1.0, -1), (None, None)]
)
def test_the_fitness_trend_is_read_by_its_value(
    value: Any, expected: int | None
) -> None:
    document = training_status_document(
        statuses={"7": status_entry(fitnessTrend=value)}
    )
    result = read(DayFamily.TRAINING_STATUS, document)
    assert result.status_block is not None
    assert result.status_block.fitness_trend == expected
    assert result.discards == ()


@pytest.mark.parametrize("value", [1.5, float("inf")])
def test_a_non_integral_nap_source_is_no_code(value: float) -> None:
    """Un flottant non entier (ou non fini) n'est aucun code : la sieste reste, son code
    est absent, l'écart compté ; le fichier n'est pas refusé."""
    result = read(DayFamily.SLEEP, _nap_document(napSource=value))
    assert result.refusal is None
    (nap,) = result.naps
    assert nap.nap_source_code is None
    assert _discards(result) == {
        ("dailySleepDTO.dailyNapDTOS[*].napSource", PointDiscard.OUT_OF_RANGE): 1
    }


def test_a_non_integral_fitness_trend_is_no_code() -> None:
    document = training_status_document(statuses={"7": status_entry(fitnessTrend=2.5)})
    result = read(DayFamily.TRAINING_STATUS, document)
    assert result.status_block is not None
    assert result.status_block.fitness_trend is None
    path = "mostRecentTrainingStatus.latestTrainingStatusData.<n>.fitnessTrend"
    assert _discards(result) == {(path, PointDiscard.OUT_OF_RANGE): 1}


@pytest.mark.parametrize(
    ("family", "make"),
    [
        (
            DayFamily.SLEEP,
            lambda: _set(
                sleep_document(), ("dailySleepDTO", "dailyNapDTOS", 0, "napSource"), "1"
            ),
        ),
        (
            DayFamily.TRAINING_STATUS,
            lambda: training_status_document(
                statuses={str(DEVICE): status_entry(fitnessTrend=True)}
            ),
        ),
    ],
)
def test_a_code_of_another_type_refuses_the_file(
    family: DayFamily, make: Callable[[], Any]
) -> None:
    """Un texte ou un booléen n'est pas un nombre : le champ lu est d'un autre type."""
    assert read(family, make()).refusal is DayFileRefusal.UNEXPECTED_SHAPE


def test_fixture_documents_are_dated_in_utc_and_plus_one() -> None:
    assert START.utcoffset() == timedelta(hours=1)
    assert gmt_text(START) == "2001-03-09T23:00:00.0"
    assert local_text(START) == "2001-03-10T00:00:00.0"
    assert UTC.utcoffset(None) == timedelta(0)
    assert timezone(timedelta(hours=1)) == PLUS1
