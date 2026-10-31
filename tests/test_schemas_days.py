"""Contrats d'``interim/days/`` (``schemas/days.py``, AN2-1) : chaque invariant, des
deux côtés ; un objet construit de chaque type ; l'aller-retour par le codec."""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

import mountain_perf
from fixtures.days import (
    DAY,
    EMPTY_HISTORY,
    EMPTY_NIGHT_SERIES,
    EXPORT_A,
    EXPORT_B,
    NAN,
    PLUS1,
    PLUS2,
    SRC,
    activity_totals,
    altitude_block,
    at,
    body_battery_summary,
    day_record,
    day_series,
    days_report,
    empty_day,
    export_report,
    full_report,
    heat_block,
    history,
    hrv_summary,
    load_balance_block,
    midnight,
    nap,
    night,
    night_series,
    read_name,
    readiness,
    respiration_summary,
    resting_hr,
    spo2_summary,
    status_block,
    stress_summary,
    truncated_day,
    versions,
    vo2_max_block,
)
from mountain_perf.codec import canonical_bytes
from mountain_perf.ingest.interim import decode_interim, encode_interim
from mountain_perf.schemas import (
    BODY_BATTERY_STATUS_DESCRIPTIONS,
    BORROWING_REFUSAL_DESCRIPTIONS,
    COMPARISON_CLASS_DESCRIPTIONS,
    DAY_FAMILY_DESCRIPTIONS,
    DAY_FILE_REFUSAL_DESCRIPTIONS,
    DAY_STATE_DESCRIPTIONS,
    DAY_WINDOW_FAMILIES,
    NIGHT_FLAG_DESCRIPTIONS,
    NIGHT_STATE_DESCRIPTIONS,
    POINT_DISCARD_DESCRIPTIONS,
    QUANTITY_SUPPORTS,
    RESTING_HR_STATUS_DESCRIPTIONS,
    SERIES_KIND_DESCRIPTIONS,
    SLEEP_STAGE_DESCRIPTIONS,
    SUPPORT_DESCRIPTIONS,
    TRAINING_STATUS_KIND_DESCRIPTIONS,
    VIEW_ABSENCE_DESCRIPTIONS,
    WAKING_CONTEXT,
    AlgorithmVersions,
    BlockCount,
    BlockFieldCount,
    BodyBatterySeries,
    BodyBatteryStatus,
    BorrowingCount,
    BorrowingRefusal,
    BorrowingRefusalCount,
    CodeCount,
    ComparisonClass,
    ComparisonCount,
    CopyDisagreementCount,
    DayBoundaryGap,
    DayFamily,
    DayFileRefusal,
    DayFileRefused,
    DayRecord,
    DaySeries,
    DaysReport,
    DayState,
    ExportDayCount,
    FamilyDayCount,
    HeartRateSeries,
    HrvSeries,
    NightFlag,
    NightSeries,
    NightState,
    PointDiscard,
    PointDiscardCount,
    ReadFile,
    ReadinessCopyCount,
    RespirationSeries,
    RestingHrStatus,
    RestlessMomentsSeries,
    SeriesKind,
    SleepSegment,
    SleepStage,
    SpO2Series,
    StressSeries,
    Support,
    TrainingStatusHistory,
    TrainingStatusKind,
    ViewAbsence,
    WindowEdgeCount,
)
from mountain_perf.schemas._dictionary import DOCUMENTED_TYPES, ENUM_DESCRIPTIONS
from mountain_perf.validation import ContractError

ENUMS: list[tuple[type[StrEnum], Any]] = [
    (DayFamily, DAY_FAMILY_DESCRIPTIONS),
    (DayState, DAY_STATE_DESCRIPTIONS),
    (Support, SUPPORT_DESCRIPTIONS),
    (SleepStage, SLEEP_STAGE_DESCRIPTIONS),
    (BodyBatteryStatus, BODY_BATTERY_STATUS_DESCRIPTIONS),
    (DayFileRefusal, DAY_FILE_REFUSAL_DESCRIPTIONS),
    (PointDiscard, POINT_DISCARD_DESCRIPTIONS),
    (BorrowingRefusal, BORROWING_REFUSAL_DESCRIPTIONS),
    (TrainingStatusKind, TRAINING_STATUS_KIND_DESCRIPTIONS),
    (ComparisonClass, COMPARISON_CLASS_DESCRIPTIONS),
    (NightState, NIGHT_STATE_DESCRIPTIONS),
    (NightFlag, NIGHT_FLAG_DESCRIPTIONS),
    (RestingHrStatus, RESTING_HR_STATUS_DESCRIPTIONS),
    (SeriesKind, SERIES_KIND_DESCRIPTIONS),
    (ViewAbsence, VIEW_ABSENCE_DESCRIPTIONS),
]


def _kw(name: str, value: object) -> dict[str, Any]:
    return {name: value}


def _refused(match: str) -> Any:
    return pytest.raises(ContractError, match=re.escape(match))


@pytest.mark.parametrize(("enum", "descriptions"), ENUMS, ids=lambda x: str(x))
def test_every_member_is_described_and_published(enum: Any, descriptions: Any) -> None:
    assert list(descriptions) == list(enum)
    assert all(text.strip() for text in descriptions.values())
    assert ENUM_DESCRIPTIONS[enum] is descriptions
    assert enum in DOCUMENTED_TYPES


def test_enum_values_of_the_specification() -> None:
    expected = {
        DayFamily: [
            "sleep",
            "hrv",
            "resting_hr",
            "heart_rate",
            "body_battery",
            "stress",
            "respiration",
            "spo2",
            "daily_summary",
            "training_readiness",
            "training_status",
        ],
        DayState: ["empty", "no_measurement", "truncated", "complete"],
        Support: ["night", "waking", "day", "instant"],
        SleepStage: ["deep", "light", "rem", "awake", "unmeasurable"],
        BodyBatteryStatus: ["measured", "modeled", "reset"],
        DayFileRefusal: [
            "unreadable_json",
            "unexpected_shape",
            "date_mismatch",
            "no_primary_device",
        ],
        PointDiscard: [
            "null_value",
            "out_of_range",
            "unknown_code",
            "not_increasing",
            "duplicate_instant",
            "overlapping_segment",
            "no_night",
            "no_window",
        ],
        BorrowingRefusal: ["day_window", "night_window", "night_durations"],
        TrainingStatusKind: [
            "status",
            "load_balance",
            "vo2_max",
            "heat_acclimation",
            "altitude_acclimation",
        ],
        ComparisonClass: ["revision", "degradation", "borrowing", "set_apart"],
        NightState: ["missing", "declared", "in_progress", "partial", "complete"],
        NightFlag: ["short", "shifted"],
        RestingHrStatus: ["absent", "provisional", "no_night", "valid"],
        SeriesKind: [
            "day_heart_rate",
            "day_stress",
            "day_body_battery",
            "day_respiration",
            "day_spo2",
            "night_heart_rate",
            "night_stress",
            "night_body_battery",
            "night_hrv",
            "night_respiration",
            "night_spo2",
            "night_restless_moments",
        ],
        ViewAbsence: [
            "no_segments",
            "no_night",
            "no_entry_after_night",
            "below_coverage",
            "no_point",
            "no_episode",
            "no_measured_sleep",
            "no_unmeasurable",
            "below_usual_minimum",
            "no_night_before",
            "no_block",
            "no_entry",
            "no_resting_hr",
            "dispersed_midpoints",
        ],
    }
    for enum, values in expected.items():
        assert [member.value for member in enum] == values, enum


def test_the_orders_decided_by_the_athlete() -> None:
    """L'ordre des membres est l'ordre de décision."""
    assert list(DayState) == [
        DayState.EMPTY,
        DayState.NO_MEASUREMENT,
        DayState.TRUNCATED,
        DayState.COMPLETE,
    ]
    assert list(NightState) == [
        NightState.MISSING,
        NightState.DECLARED,
        NightState.IN_PROGRESS,
        NightState.PARTIAL,
        NightState.COMPLETE,
    ]
    assert list(RestingHrStatus) == [
        RestingHrStatus.ABSENT,
        RestingHrStatus.PROVISIONAL,
        RestingHrStatus.NO_NIGHT,
        RestingHrStatus.VALID,
    ]


def test_day_window_families_in_the_order_of_the_note() -> None:
    assert DAY_WINDOW_FAMILIES == (
        DayFamily.DAILY_SUMMARY,
        DayFamily.HEART_RATE,
        DayFamily.STRESS,
        DayFamily.RESPIRATION,
        DayFamily.SPO2,
    )


def test_the_waking_context_is_declared_once_in_the_contracts() -> None:
    """``WAKING_CONTEXT`` n'est déclaré qu'ici : la lecture des familles et les vues
    l'importent."""
    assert WAKING_CONTEXT == "AFTER_WAKEUP_RESET"
    root = Path(mountain_perf.__file__).parent
    declaring = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if '"AFTER_WAKEUP_RESET"' in path.read_text(encoding="utf-8")
        or "'AFTER_WAKEUP_RESET'" in path.read_text(encoding="utf-8")
    )
    assert declaring == ["schemas/days.py"]


def _resolves(path: str) -> bool:
    cls: Any = DayRecord
    for part in path.split("."):
        fields = {field.name: field for field in dataclasses.fields(cls)}
        if part not in fields:
            return False
        hint = fields[part].type
        name = str(hint).split(" | ")[0].strip()
        cls = getattr(mountain_perf.schemas, name, None)
        if cls is None or not dataclasses.is_dataclass(cls):
            cls = None
            continue
    return True


def test_every_quantity_of_a_day_declares_its_support() -> None:
    assert all(_resolves(path) for path in QUANTITY_SUPPORTS)
    summaries = {
        "resting_hr": ("resting_hr_bpm",),
        "hrv": tuple(f.name for f in dataclasses.fields(hrv_summary())),
        "respiration": tuple(f.name for f in dataclasses.fields(respiration_summary())),
        "spo2": tuple(f.name for f in dataclasses.fields(spo2_summary())),
        "stress": tuple(f.name for f in dataclasses.fields(stress_summary())),
        "body_battery": tuple(
            f.name for f in dataclasses.fields(body_battery_summary())
        ),
        "activity_totals": tuple(f.name for f in dataclasses.fields(activity_totals())),
    }
    for summary, names in summaries.items():
        for name in names:
            if name != "source":
                assert f"{summary}.{name}" in QUANTITY_SUPPORTS, (summary, name)
    for path in ("night", "night.series", "naps", "series", "readiness"):
        assert path in QUANTITY_SUPPORTS


def test_supports_follow_the_note() -> None:
    assert QUANTITY_SUPPORTS["night"] is Support.NIGHT
    assert QUANTITY_SUPPORTS["night.series"] is Support.INSTANT
    assert QUANTITY_SUPPORTS["naps"] is Support.INSTANT
    assert QUANTITY_SUPPORTS["resting_hr.resting_hr_bpm"] is Support.DAY
    assert QUANTITY_SUPPORTS["hrv.last_night_avg_ms"] is Support.NIGHT
    assert QUANTITY_SUPPORTS["hrv.weekly_avg_ms"] is Support.WAKING
    assert QUANTITY_SUPPORTS["hrv.status"] is Support.WAKING
    assert QUANTITY_SUPPORTS["respiration.avg_sleep_breaths_per_min"] is Support.NIGHT
    assert QUANTITY_SUPPORTS["respiration.avg_waking_breaths_per_min"] is Support.DAY
    assert QUANTITY_SUPPORTS["spo2.avg_sleep_spo2_percent"] is Support.NIGHT
    assert QUANTITY_SUPPORTS["spo2.average_spo2_percent"] is Support.DAY
    assert QUANTITY_SUPPORTS["body_battery.at_wake"] is Support.WAKING
    assert QUANTITY_SUPPORTS["body_battery.during_sleep"] is Support.NIGHT
    assert QUANTITY_SUPPORTS["body_battery.highest"] is Support.DAY
    assert QUANTITY_SUPPORTS["stress.average_level"] is Support.DAY
    assert QUANTITY_SUPPORTS["activity_totals.steps"] is Support.DAY
    assert QUANTITY_SUPPORTS["series"] is Support.INSTANT
    assert QUANTITY_SUPPORTS["readiness"] is Support.INSTANT
    assert len(QUANTITY_SUPPORTS) == 44


def test_instants_are_brought_to_a_fixed_offset() -> None:
    paris = ZoneInfo("Europe/Paris")
    n = night(start=datetime(2001, 3, 9, 23, tzinfo=paris))
    assert n.start.tzinfo == timezone(timedelta(hours=1))
    assert type(n.start.tzinfo) is timezone
    d = day_record(window_start=datetime(2001, 3, 10, tzinfo=paris))
    assert type(d.window_start.tzinfo) is timezone if d.window_start else False


@pytest.mark.parametrize(
    "make",
    [
        lambda t: night(start=t),
        lambda t: night(end=t),
        lambda t: nap(start=t),
        lambda t: nap(end=t),
        lambda t: readiness(instant=t),
        lambda t: status_block(timestamp=t, proper_instant=t),
        lambda t: load_balance_block(proper_instant=t),
    ],
)
def test_instants_are_aware_with_a_real_whole_second_offset(
    make: Callable[[datetime], object],
) -> None:
    with pytest.raises(ContractError, match="doit porter un fuseau horaire"):
        make(datetime(2001, 3, 10, 6))
    fraction = timezone(timedelta(hours=1, microseconds=500000))
    with pytest.raises(ContractError, match="nombre entier de secondes"):
        make(datetime(2001, 3, 10, 6, tzinfo=fraction))
    with pytest.raises(ContractError, match=r"décalage de \w+ \(s\) doit être dans"):
        make(datetime(2001, 3, 10, 6, tzinfo=timezone(timedelta(hours=-13))))


def test_offsets_at_the_bounds_of_the_range() -> None:
    for seconds, kept in (
        (-43200, True),
        (-43201, False),
        (50400, True),
        (50401, False),
    ):
        zone = timezone(timedelta(seconds=seconds))
        start = datetime(2001, 3, 9, 23, tzinfo=zone)
        if kept:
            assert night(start=start, end=start + timedelta(hours=8)).start == start
        else:
            with pytest.raises(ContractError, match="décalage de start"):
                night(start=start, end=start + timedelta(hours=8))


SERIES: list[Callable[[Any, int], object]] = [
    lambda t, n: HeartRateSeries(t, (60.0,) * n, SRC),
    lambda t, n: StressSeries(t, (10,) * n, (None,) * n, SRC),
    lambda t, n: BodyBatterySeries(t, (50,) * n, (None,) * n, SRC),
    lambda t, n: RespirationSeries(t, (14.0,) * n, (None,) * n, SRC),
    lambda t, n: SpO2Series(t, (95.0,) * n, SRC),
    lambda t, n: HrvSeries(t, (40.0,) * n, SRC),
    lambda t, n: RestlessMomentsSeries(t, (1,) * n, SRC),
]


@pytest.mark.parametrize("make", SERIES)
def test_series_times(make: Callable[[Any, int], object]) -> None:
    make((0.0, 60.0), 2)
    with _refused("time_s doit être une séquence immuable"):
        make([0.0, 60.0], 2)
    with _refused("time_s doit contenir au moins 1 éléments"):
        make((), 0)
    with _refused("time_s[0] doit être fini"):
        make((NAN,), 1)
    with _refused("time_s doit être strictement croissante"):
        make((60.0, 60.0), 2)
    with _refused("time_s doit être strictement croissante"):
        make((60.0, 0.0), 2)


@pytest.mark.parametrize("make", SERIES)
def test_series_lengths(make: Callable[[Any, int], object]) -> None:
    with _refused("Tableaux parallèles de longueurs différentes"):
        make((0.0, 60.0), 1)


@pytest.mark.parametrize(
    ("make", "name", "good", "bad"),
    [
        (lambda v: HeartRateSeries((0.0,), v, SRC), "heart_rate_bpm", 20.0, 19.9),
        (lambda v: HeartRateSeries((0.0,), v, SRC), "heart_rate_bpm", 250.0, 250.1),
        (lambda v: BodyBatterySeries((0.0,), v, (None,), SRC), "level", 0, -1),
        (lambda v: BodyBatterySeries((0.0,), v, (None,), SRC), "level", 100, 101),
        (lambda v: SpO2Series((0.0,), v, SRC), "spo2_percent", 0.0, -0.5),
        (lambda v: SpO2Series((0.0,), v, SRC), "spo2_percent", 100.0, 100.5),
        (lambda v: HrvSeries((0.0,), v, SRC), "hrv_ms", 0.0, -0.5),
        (lambda v: RestlessMomentsSeries((0.0,), v, SRC), "count", 0, -1),
    ],
)
def test_series_values_in_range(
    make: Callable[[tuple[float, ...]], object], name: str, good: float, bad: float
) -> None:
    make((good,))
    with _refused(f"{name}[0] doit être dans"):
        make((bad,))
    with _refused(f"{name}[0] doit être fini"):
        make((NAN,))


@pytest.mark.parametrize(
    ("make", "name", "low", "high", "bad"),
    [
        (
            lambda v, c: StressSeries((0.0,), v, c, SRC),
            "stress_level",
            0,
            100,
            (-1, 101),
        ),
        (
            lambda v, c: RespirationSeries((0.0,), v, c, SRC),
            "breaths_per_min",
            0.0,
            60.0,
            (-0.5, NAN),
        ),
    ],
)
def test_exactly_one_value_or_negative_code_per_point(
    make: Callable[[tuple[Any, ...], tuple[Any, ...]], object],
    name: str,
    low: float,
    high: float,
    bad: tuple[float, ...],
) -> None:
    make((low,), (None,))
    make((high,), (None,))
    make((None,), (-1,))
    make((None,), (-2,))
    exactly_one = f"le point 0 doit porter exactement une valeur ({name}) ou un code."
    with _refused(exactly_one):
        make((None,), (None,))
    with _refused(exactly_one):
        make((low,), (-1,))
    with _refused("code[0] doit être un code négatif, reçu 0."):
        make((None,), (0,))
    for value in bad:
        with pytest.raises(ContractError, match=re.escape(f"{name}[0]")):
            make((value,), (None,))
    with _refused("code doit être une séquence immuable"):
        make((low,), [None])  # type: ignore[arg-type]
    with _refused("Tableaux parallèles de longueurs différentes"):
        make((low, low), (None, None))


def test_body_battery_status_list_and_length() -> None:
    with _refused("status doit être une séquence immuable"):
        BodyBatterySeries((0.0,), (50,), [None], SRC)  # type: ignore[arg-type]
    with _refused("Tableaux parallèles de longueurs différentes"):
        BodyBatterySeries((0.0,), (50,), (None, None), SRC)


def test_night_series_have_no_body_battery_status() -> None:
    measured = BodyBatterySeries((0.0,), (50,), (BodyBatteryStatus.MEASURED,), SRC)
    with _refused("body_battery : les points de la nuit n'ont pas de statut."):
        NightSeries(None, None, measured, None, None, None, None)
    plain = BodyBatterySeries((0.0,), (50,), (None,), SRC)
    assert NightSeries(None, None, plain, None, None, None, None).body_battery == plain


def test_day_series_body_battery_points_carry_a_status() -> None:
    """un point du jour au statut nul est écarté à la lecture ; chaque point gardé de
    la journée a donc un statut (la nuit reste sans statut)."""
    partial = BodyBatterySeries(
        (0.0, 60.0), (50, 51), (BodyBatteryStatus.MEASURED, None), SRC
    )
    with _refused("body_battery : chaque point de la journée porte un statut."):
        DaySeries(None, None, partial, None, None)
    assert day_series().body_battery is not None


def test_a_night_and_its_measured_sleep() -> None:
    assert night().measured_sleep_s == 25200.0
    assert night(rem_capable=False, rem_s=None).measured_sleep_s == 19800.0
    assert night(rem_capable=True, rem_s=None).measured_sleep_s is None
    assert night(rem_capable=None, rem_s=None).measured_sleep_s is None
    assert night(rem_capable=None).measured_sleep_s == 25200.0
    assert night(deep_s=None).measured_sleep_s is None
    assert night(light_s=None).measured_sleep_s is None


def test_night_window() -> None:
    with _refused("end doit suivre start : la nuit a une durée."):
        night(end=at(DAY - timedelta(days=1), 23))
    with _refused("end doit suivre start : la nuit a une durée."):
        night(end=at(DAY - timedelta(days=1), 22))
    # Les deux bornes dans des décalages différents : la durée est celle des instants.
    n = night(end=at(DAY, 7, offset=PLUS2))
    assert n.end - n.start == timedelta(hours=7)


def test_the_night_equality_is_not_an_invariant() -> None:
    """La source peut la violer : elle se compte à l'ingestion."""
    n = night(deep_s=0.0, light_s=60.0, rem_s=0.0, awake_s=0.0, unmeasurable_s=0.0)
    assert n.measured_sleep_s == 60.0


@pytest.mark.parametrize(
    "name", ["deep_s", "light_s", "rem_s", "awake_s", "unmeasurable_s"]
)
def test_night_durations(name: str) -> None:
    assert getattr(night(**_kw(name, 0.0)), name) == 0.0
    assert getattr(night(**_kw(name, None)), name) is None
    with _refused(f"{name} doit être dans"):
        night(**_kw(name, -1.0))
    with _refused(f"{name} doit être fini"):
        night(**_kw(name, NAN))


def test_rem_is_absent_when_the_device_does_not_detect_it() -> None:
    with _refused(
        "rem_s doit être absent quand l'appareil ne détecte pas le paradoxal."
    ):
        night(rem_capable=False, rem_s=0.0)
    assert night(rem_capable=False, rem_s=None).rem_s is None
    assert night(rem_capable=None, rem_s=0.0).rem_s == 0.0


def test_night_confirmation_code() -> None:
    for blank in ("", "  "):
        with _refused("confirmation ne doit pas être vide."):
            night(confirmation=blank)
    assert night(confirmation=None).confirmation is None
    assert night(confirmation="INVENTED_TYPE").confirmation == "INVENTED_TYPE"


def test_night_segments_sorted_without_overlap() -> None:
    touching = (
        SleepSegment(0.0, 60.0, SleepStage.LIGHT),
        SleepSegment(60.0, 120.0, SleepStage.DEEP),
    )
    assert night(segments=touching).segments == touching
    gap = (
        SleepSegment(0.0, 60.0, SleepStage.LIGHT),
        SleepSegment(90.0, 120.0, SleepStage.DEEP),
    )
    assert night(segments=gap).segments == gap
    overlapping = (
        SleepSegment(0.0, 60.0, SleepStage.LIGHT),
        SleepSegment(59.0, 120.0, SleepStage.DEEP),
    )
    with _refused("segments doit être trié sans recouvrement : rangs 0 et 1."):
        night(segments=overlapping)
    with _refused("segments doit être trié sans recouvrement : rangs 0 et 1."):
        night(segments=(touching[1], touching[0]))
    assert night(segments=()).segments == ()


def test_sleep_segment() -> None:
    assert SleepSegment(-60.0, 0.5, SleepStage.AWAKE).end_s == 0.5
    with _refused("end_s doit suivre start_s : reçu 60.0, 60.0."):
        SleepSegment(60.0, 60.0, SleepStage.LIGHT)
    with _refused("end_s doit suivre start_s : reçu 60.0, 0.0."):
        SleepSegment(60.0, 0.0, SleepStage.LIGHT)
    with _refused("start_s doit être fini"):
        SleepSegment(NAN, 60.0, SleepStage.LIGHT)
    with _refused("end_s doit être fini"):
        SleepSegment(0.0, float("inf"), SleepStage.LIGHT)


@pytest.mark.parametrize(
    ("name", "good", "bad"),
    [
        ("sleep_score", (0, 100), (-1, 101)),
        ("avg_stress", (0.0, 100.0), (-0.5, 100.5, NAN)),
        ("avg_heart_rate_bpm", (20.0, 250.0), (19.5, 250.5, NAN)),
        ("body_battery_change", (-100, 100), (-101, 101)),
        ("restless_moments", (0, 300), (-1,)),
    ],
)
def test_night_summaries_in_range(
    name: str, good: tuple[float, ...], bad: tuple[float, ...]
) -> None:
    for value in good:
        assert getattr(night(**_kw(name, value)), name) == value
    assert getattr(night(**_kw(name, None)), name) is None
    for value in bad:
        with pytest.raises(ContractError, match=f"^{name} doit"):
            night(**_kw(name, value))


def test_skin_temperature_deviation_is_finite() -> None:
    assert night(skin_temperature_deviation_c=-12.5).skin_temperature_deviation_c == (
        -12.5
    )
    for value in (NAN, float("inf"), float("-inf")):
        with _refused("skin_temperature_deviation_c doit être fini"):
            night(skin_temperature_deviation_c=value)


def test_night_segments_must_be_a_tuple_of_the_contract() -> None:
    with _refused("segments doit être une séquence immuable"):
        night(segments=list(night().segments))


def test_nap() -> None:
    n = nap()
    assert n.end - n.start == timedelta(minutes=30)
    with _refused("end doit suivre start : la sieste a une durée."):
        nap(end=at(DAY, 14))
    with _refused("end doit suivre start : la sieste a une durée."):
        nap(end=at(DAY, 13))
    with _refused("sleep_s doit être dans"):
        nap(sleep_s=-1.0)
    with _refused("sleep_s doit être fini"):
        nap(sleep_s=NAN)
    assert nap(sleep_s=0.0, nap_source_code=None).sleep_s == 0.0
    # sleep_s n'a pas à valoir end − start.
    assert nap(sleep_s=7200.0).sleep_s == 7200.0


def test_readiness_entry() -> None:
    entry = readiness()
    assert entry.input_context == WAKING_CONTEXT
    with _refused("input_context ne doit pas être vide."):
        readiness(input_context="")
    with _refused("level ne doit pas être vide."):
        readiness(level=" ")
    for name, bad in (
        ("score", 101),
        ("score", -1),
        ("sleep_score", 101),
        ("hrv_weekly_average_ms", -0.5),
        ("acute_load", -1.0),
    ):
        with pytest.raises(ContractError, match=f"^{name} doit"):
            readiness(**_kw(name, bad))
    unknown = readiness(input_context=None, level=None, score=None, valid_sleep=None)
    assert unknown.score is None
    assert readiness(hrv_weekly_average_ms=0.0).hrv_weekly_average_ms == 0.0


def test_resting_hr() -> None:
    assert resting_hr(resting_hr_bpm=20.0).resting_hr_bpm == 20.0
    assert resting_hr(resting_hr_bpm=250.0).resting_hr_bpm == 250.0
    for bad in (19.9, 250.1):
        with _refused("resting_hr_bpm doit être dans"):
            resting_hr(resting_hr_bpm=bad)
    with _refused("resting_hr_bpm doit être fini"):
        resting_hr(resting_hr_bpm=NAN)


SUMMARY_CASES: list[tuple[Callable[..., object], str, float, float]] = [
    *(
        (hrv_summary, name, 0.0, -0.5)
        for name in (
            "last_night_avg_ms",
            "last_night_5min_high_ms",
            "weekly_avg_ms",
            "baseline_balanced_low_ms",
            "baseline_balanced_upper_ms",
            "baseline_low_upper_ms",
            "baseline_marker_value",
        )
    ),
    *(
        (respiration_summary, name, 0.0, -0.5)
        for name in (
            "avg_sleep_breaths_per_min",
            "avg_waking_breaths_per_min",
            "highest_breaths_per_min",
            "lowest_breaths_per_min",
        )
    ),
    *(
        (spo2_summary, name, 100.0, 100.5)
        for name in (
            "avg_sleep_spo2_percent",
            "average_spo2_percent",
            "lowest_spo2_percent",
        )
    ),
    *(
        (spo2_summary, name, 0.0, -0.5)
        for name in ("avg_sleep_spo2_percent", "lowest_spo2_percent")
    ),
    (stress_summary, "average_level", 0, -1),
    (stress_summary, "average_level", 100, 101),
    (stress_summary, "max_level", 100, 101),
    *(
        (stress_summary, name, 0.0, -0.5)
        for name in (
            "rest_duration_s",
            "low_duration_s",
            "medium_duration_s",
            "high_duration_s",
            "activity_duration_s",
            "uncategorized_duration_s",
            "total_duration_s",
            "stress_duration_s",
        )
    ),
    (body_battery_summary, "charged", 0, -1),
    (body_battery_summary, "drained", 0, -1),
    (body_battery_summary, "highest", 100, 101),
    (body_battery_summary, "lowest", 0, -1),
    (body_battery_summary, "at_wake", 100, 101),
    (body_battery_summary, "during_sleep", -100, -101),
    (body_battery_summary, "during_sleep", 100, 101),
    (activity_totals, "steps", 0, -1),
    (activity_totals, "moderate_intensity_s", 0.0, -60.0),
    (activity_totals, "vigorous_intensity_s", 0.0, -60.0),
    (activity_totals, "floors_ascended_m", 0.0, -0.5),
    (activity_totals, "floors_descended_m", 0.0, -0.5),
    (activity_totals, "average_altitude_m", -500.0, -500.5),
    (activity_totals, "average_altitude_m", 9000.0, 9000.5),
]


@pytest.mark.parametrize(
    ("make", "name", "good", "bad"),
    SUMMARY_CASES,
    ids=[f"{case[0].__name__}-{case[1]}-{case[3]}" for case in SUMMARY_CASES],
)
def test_summary_values_in_range(
    make: Callable[..., object], name: str, good: float, bad: float
) -> None:
    changes: dict[str, Any] = {name: good}
    if name == "average_level":
        changes["average_level_code"] = None
    assert getattr(make(**changes), name) == good
    assert getattr(make(**_kw(name, None)), name) is None
    with _refused(f"{name} doit être dans"):
        make(**{**changes, name: bad})
    with _refused(f"{name} doit être fini"):
        make(**{**changes, name: NAN})


def test_stress_average_is_a_level_or_a_code() -> None:
    """la sentinelle de ``averageStressLevel`` est gardée comme code."""
    coded = stress_summary(average_level=None, average_level_code=-1)
    assert coded.average_level_code == -1
    assert (
        stress_summary(average_level=None, average_level_code=-2).average_level is None
    )
    with _refused("average_level et average_level_code : au plus un des deux."):
        stress_summary(average_level=25, average_level_code=-1)
    with _refused("average_level_code doit être un code négatif, reçu 0."):
        stress_summary(average_level=None, average_level_code=0)
    both_absent = stress_summary(average_level=None, average_level_code=None)
    assert both_absent.average_level is None


def test_body_battery_during_sleep_is_not_the_night_change() -> None:
    """deux grandeurs nommées."""
    record = day_record(
        night=night(body_battery_change=50),
        body_battery=body_battery_summary(during_sleep=-45),
    )
    assert record.night is not None
    assert record.body_battery is not None
    assert record.night.body_battery_change == 50
    assert record.body_battery.during_sleep == -45


def test_hrv_status_code() -> None:
    with _refused("status ne doit pas être vide."):
        hrv_summary(status="")
    assert hrv_summary(status=None).status is None
    assert hrv_summary(status="UNBALANCED").status == "UNBALANCED"


def test_algorithm_versions() -> None:
    assert versions(
        body_battery_series_versions=(1, 3)
    ).body_battery_series_versions == (
        1,
        3,
    )
    for name in (
        "sleep_version",
        "sleep_respiration_version",
        "respiration_version",
        "summary_respiration_version",
        "summary_body_battery_version",
    ):
        assert getattr(versions(**_kw(name, 0)), name) == 0
        with _refused(f"{name} doit être >= 0, reçu -1."):
            versions(**_kw(name, -1))
    with _refused("body_battery_series_versions doit être >= 0, reçu -1."):
        versions(body_battery_series_versions=(-1,))
    with _refused("body_battery_series_versions doit être trié sans doublon : rangs 0"):
        versions(body_battery_series_versions=(3, 1))
    with _refused("body_battery_series_versions doit être trié sans doublon : rangs 0"):
        versions(body_battery_series_versions=(3, 3))
    with _refused("body_battery_series_versions doit être une séquence immuable"):
        versions(body_battery_series_versions=[3])
    assert AlgorithmVersions(None, None, None, None, None, ()).sleep_version is None


def test_a_complete_day() -> None:
    record = day_record()
    assert record.state is DayState.COMPLETE
    assert record.window_start == midnight(DAY)
    assert record.data_end == midnight(DAY) + timedelta(days=1)
    assert record.window_family is DayFamily.DAILY_SUMMARY
    assert record.night is not None
    assert record.night.series == night_series(record.night.source)
    assert record.reference_export == EXPORT_A
    assert record.device_ranks == (1,)


def test_day_window_is_brought_to_its_offset() -> None:
    start = midnight(DAY)
    record = day_record(data_end=(start + timedelta(days=1)).astimezone(UTC))
    assert record.data_end is not None
    assert record.data_end.utcoffset() == timedelta(hours=1)
    assert record.data_end == start + timedelta(days=1)
    paris = day_record(
        window_start=datetime(2001, 3, 10, tzinfo=ZoneInfo("Europe/Paris"))
    )
    assert paris.window_start is not None
    assert type(paris.window_start.tzinfo) is timezone


def test_window_parts_go_together() -> None:
    for name in ("window_start", "data_end", "window_family"):
        with _refused("window_start, data_end et window_family vont ensemble."):
            day_record(**_kw(name, None))


def test_window_absent_if_and_only_if_empty() -> None:
    message = "window_start doit être absent si et seulement si state est empty."
    with _refused(message):
        day_record(state=DayState.EMPTY)
    with _refused(message):
        empty_day(state=DayState.NO_MEASUREMENT)
    assert empty_day().state is DayState.EMPTY


def test_day_is_the_local_date_of_the_window() -> None:
    with _refused("window_start doit tomber le jour day, dans son décalage."):
        day_record(
            window_start=at(DAY - timedelta(days=1), 23),
            data_end=at(DAY, 23),
        )
    # le même instant, exprimé à +02:00 : minuit du jour.
    instant = midnight(DAY, PLUS2)
    assert day_record(
        window_start=instant, data_end=instant + timedelta(days=1)
    ).day == (DAY)


def test_data_end_not_before_the_window_start() -> None:
    start = midnight(DAY)
    with _refused("data_end ne peut pas précéder window_start."):
        truncated_day(data_end=start - timedelta(microseconds=1))
    assert truncated_day(data_end=start).data_end == start


def test_window_family_carries_a_day_window() -> None:
    message = "window_family doit être une famille qui porte une fenêtre du jour."
    for family in (DayFamily.SLEEP, DayFamily.HRV, DayFamily.TRAINING_STATUS):
        with _refused(message):
            day_record(window_family=family)
    for family in DAY_WINDOW_FAMILIES:
        assert day_record(window_family=family).window_family is family


def test_truncated_and_complete_at_the_end_of_the_window() -> None:
    end = midnight(DAY) + timedelta(days=1)
    before = end - timedelta(microseconds=1)
    assert truncated_day(data_end=before).state is DayState.TRUNCATED
    with _refused("state truncated : data_end doit précéder window_start + 24 h."):
        truncated_day(data_end=end)
    assert day_record(data_end=end).state is DayState.COMPLETE
    assert day_record(data_end=end + timedelta(hours=1)).state is DayState.COMPLETE
    with _refused(
        "state complete : data_end doit valoir au moins window_start + 24 h."
    ):
        day_record(data_end=before)
    for data_end in (before, end):
        no_measurement = day_record(data_end=data_end, state=DayState.NO_MEASUREMENT)
        assert no_measurement.state is DayState.NO_MEASUREMENT


def test_no_cross_invariant_with_the_presence_indicator() -> None:
    """``wellness_data`` peut venir d'une famille empruntée : l'état, décidé sur
    l'export de référence, ne se vérifie pas contre lui."""
    assert day_record(wellness_data=False).state is DayState.COMPLETE
    no_measurement = day_record(state=DayState.NO_MEASUREMENT, wellness_data=True)
    assert no_measurement.wellness_data is True
    assert empty_day(wellness_data=False).wellness_data is False


def test_no_day_series_without_a_window() -> None:
    with _refused("series : sans fenêtre du jour, aucune série du jour."):
        empty_day(series=day_series())
    full = day_series()
    for name in ("heart_rate", "stress", "body_battery", "respiration", "spo2"):
        only = DaySeries(**{f.name: None for f in dataclasses.fields(DaySeries)})
        only = dataclasses.replace(only, **_kw(name, getattr(full, name)))
        with _refused("series : sans fenêtre du jour, aucune série du jour."):
            empty_day(series=only)
    assert empty_day(night=night()).night is not None


def test_reference_export_names_a_folder() -> None:
    for bad in ("a/b", "..", "", "a b"):
        with pytest.raises(ContractError, match="le nom d'un export"):
            day_record(reference_export=bad)
    assert day_record(reference_export="export-1.b_c").reference_export == (
        "export-1.b_c"
    )


def test_naps_and_readiness_sorted() -> None:
    early, late = nap(), nap(start=at(DAY, 16), end=at(DAY, 17))
    assert day_record(naps=(early, late)).naps == (early, late)
    assert day_record(naps=(early, early)).naps == (early, early)
    with pytest.raises(ContractError, match=re.escape("naps (début) doit être")):
        day_record(naps=(late, early))
    with _refused("naps doit être une séquence immuable"):
        day_record(naps=[early])
    first, second = readiness(), readiness(instant=at(DAY, 18))
    assert day_record(readiness=(first, second)).readiness == (first, second)
    assert day_record(readiness=(first, first)).readiness == (first, first)
    with pytest.raises(ContractError, match=re.escape("readiness (instant) doit être")):
        day_record(readiness=(second, first))
    with _refused("readiness doit être une séquence immuable"):
        day_record(readiness=[first])


def test_readiness_sorted_by_instant_not_wall_clock() -> None:
    """7 h 30 à +02:00 (5 h 30 UTC) précède 7 h à +01:00 (6 h UTC)."""
    summer = readiness(instant=at(DAY, 7, 30, offset=PLUS2))
    winter = readiness(instant=at(DAY, 7, 0, offset=PLUS1))
    assert day_record(readiness=(summer, winter)).readiness == (summer, winter)
    with pytest.raises(ContractError, match=re.escape("readiness (instant)")):
        day_record(readiness=(winter, summer))


def test_device_ranks() -> None:
    assert day_record(device_ranks=()).device_ranks == ()
    assert day_record(device_ranks=(1, 3)).device_ranks == (1, 3)
    with _refused("device_ranks doit être >= 1, reçu 0."):
        day_record(device_ranks=(0,))
    with _refused("device_ranks doit être trié sans doublon : rangs 0 et 1."):
        day_record(device_ranks=(2, 1))
    with _refused("device_ranks doit être trié sans doublon : rangs 0 et 1."):
        day_record(device_ranks=(1, 1))
    with _refused("device_ranks doit être une séquence immuable"):
        day_record(device_ranks=[1])


def test_status_block_proper_instant_is_its_timestamp() -> None:
    block = status_block()
    assert block.proper_instant == block.timestamp
    message = "proper_instant doit être l'horodatage du statut quand il est porté."
    assert block.timestamp is not None
    with _refused(message):
        status_block(proper_instant=block.timestamp + timedelta(seconds=1))
    with _refused(message):
        status_block(proper_instant=None)
    same = status_block(proper_instant=block.timestamp.astimezone(PLUS1))
    assert same.proper_instant == block.timestamp
    undated = status_block(timestamp=None, proper_instant=midnight(DAY))
    assert undated.timestamp is None
    assert status_block(timestamp=None, proper_instant=None).proper_instant is None


@pytest.mark.parametrize(
    "name",
    [
        "acute_load",
        "chronic_load",
        "acute_chronic_ratio",
        "acwr_percent",
        "min_chronic_load",
        "max_chronic_load",
    ],
)
def test_status_block_loads(name: str) -> None:
    assert getattr(status_block(**_kw(name, 0.0)), name) == 0.0
    assert getattr(status_block(**_kw(name, None)), name) is None
    with _refused(f"{name} doit être dans"):
        status_block(**_kw(name, -0.5))
    with _refused(f"{name} doit être fini"):
        status_block(**_kw(name, NAN))


def test_status_block_codes() -> None:
    assert status_block(status_code=0).status_code == 0
    with _refused("status_code doit être >= 0, reçu -1."):
        status_block(status_code=-1)
    with _refused("acwr_status ne doit pas être vide."):
        status_block(acwr_status="")
    assert status_block(fitness_trend=-1).fitness_trend == -1
    assert status_block(status_code=None, acwr_status=None).acwr_status is None


@pytest.mark.parametrize(
    ("make", "name", "good", "bad"),
    [
        (load_balance_block, "monthly_aerobic_low", 0.0, -0.5),
        (load_balance_block, "monthly_aerobic_low_target_min", 0.0, -0.5),
        (load_balance_block, "monthly_aerobic_low_target_max", 0.0, -0.5),
        (load_balance_block, "monthly_aerobic_high", 0.0, -0.5),
        (load_balance_block, "monthly_aerobic_high_target_min", 0.0, -0.5),
        (load_balance_block, "monthly_aerobic_high_target_max", 0.0, -0.5),
        (load_balance_block, "monthly_anaerobic", 0.0, -0.5),
        (load_balance_block, "monthly_anaerobic_target_min", 0.0, -0.5),
        (load_balance_block, "monthly_anaerobic_target_max", 0.0, -0.5),
        (vo2_max_block, "vo2_max_precise_ml_kg_min", 0.0, -0.5),
        (vo2_max_block, "vo2_max_ml_kg_min", 0.0, -0.5),
        (heat_block, "heat_acclimation_percent", 0.0, -0.5),
        (altitude_block, "acclimation_altitude_m", 9000.0, 9000.5),
        (altitude_block, "current_altitude_m", -500.0, -500.5),
    ],
)
def test_block_values_in_range(
    make: Callable[..., object], name: str, good: float, bad: float
) -> None:
    assert getattr(make(**_kw(name, good)), name) == good
    assert getattr(make(**_kw(name, None)), name) is None
    with _refused(f"{name} doit être dans"):
        make(**_kw(name, bad))
    with _refused(f"{name} doit être fini"):
        make(**_kw(name, NAN))


def test_block_codes_and_proper_instants() -> None:
    with _refused("heat_trend ne doit pas être vide."):
        heat_block(heat_trend=" ")
    with _refused("altitude_trend ne doit pas être vide."):
        altitude_block(altitude_trend="")
    for make in (load_balance_block, vo2_max_block, heat_block, altitude_block):
        assert make(proper_instant=None).proper_instant is None
        with _refused("proper_instant doit porter un fuseau horaire"):
            make(proper_instant=datetime(2001, 3, 11))
        paris = datetime(2001, 3, 11, tzinfo=ZoneInfo("Europe/Paris"))
        proper_instant = getattr(make(proper_instant=paris), "proper_instant", None)
        assert proper_instant is not None
        assert type(proper_instant.tzinfo) is timezone


@pytest.mark.parametrize(
    ("name", "make"),
    [
        ("statuses", status_block),
        ("load_balances", load_balance_block),
        ("vo2_max", vo2_max_block),
        ("heat_acclimation", heat_block),
        ("altitude_acclimation", altitude_block),
    ],
)
def test_history_sorted_one_block_per_day(
    name: str, make: Callable[..., object]
) -> None:
    first, second = make(DAY), make(DAY + timedelta(days=1))
    kept = dataclasses.replace(EMPTY_HISTORY, **_kw(name, (first, second)))
    assert getattr(kept, name) == (first, second)
    for blocks in ((second, first), (first, first)):
        with _refused(f"{name} doit être trié sans doublon : rangs 0 et 1."):
            dataclasses.replace(EMPTY_HISTORY, **_kw(name, blocks))
    with _refused(f"{name} doit être une séquence immuable"):
        dataclasses.replace(EMPTY_HISTORY, **_kw(name, [first]))


def test_export_report() -> None:
    report = export_report()
    assert report.retrieved_at.utcoffset() == timedelta(0)
    with pytest.raises(ContractError, match="le nom d'un export"):
        export_report(name="a/b")
    with _refused("retrieved_at doit porter un fuseau horaire"):
        export_report(retrieved_at=datetime(2001, 12, 1))
    with _refused("files doit être >= 0, reçu -1."):
        export_report(files=-1)
    with _refused("first_day et last_day vont ensemble."):
        export_report(last_day=None)
    with _refused("first_day ne peut pas suivre last_day."):
        export_report(first_day=DAY + timedelta(days=1))
    with _refused("first_day : un export sans fichier, sans jour."):
        export_report(files=0, families=())
    empty = export_report(files=0, first_day=None, last_day=None, families=())
    assert empty.files == 0
    with _refused("families doit être trié sans doublon : rangs 0 et 1."):
        export_report(families=(DayFamily.SLEEP, DayFamily.HRV))
    with _refused("families doit être trié sans doublon : rangs 0 et 1."):
        export_report(families=(DayFamily.HRV, DayFamily.HRV))
    with _refused("families doit être une séquence immuable"):
        export_report(families=[DayFamily.HRV])


@pytest.mark.parametrize(
    "name", ["", "/a", "a/", "a//b", "./a", "a/../b", "c:\\x", "a\\b"]
)
def test_refused_names_are_relative(name: str) -> None:
    with pytest.raises(ContractError, match=r"^name "):
        DayFileRefused(name, DayFileRefusal.UNREADABLE_JSON)


COUNTS: list[tuple[Callable[[int], object], str]] = [
    (lambda n: ExportDayCount(EXPORT_A, n), "days"),
    (lambda n: FamilyDayCount(DayFamily.HEART_RATE, n), "days"),
    (lambda n: BorrowingCount(DayFamily.SLEEP, "night.series.hrv", n), "count"),
    (
        lambda n: BorrowingRefusalCount(
            DayFamily.SLEEP, "night", BorrowingRefusal.NIGHT_WINDOW, n
        ),
        "count",
    ),
    (
        lambda n: ComparisonCount(
            DayFamily.SLEEP, "sleepLevels", ComparisonClass.REVISION, n
        ),
        "days",
    ),
    (lambda n: CopyDisagreementCount("hrv.weekly_avg_ms", DayFamily.SLEEP, n), "days"),
    (
        lambda n: PointDiscardCount(
            DayFamily.STRESS, "stressValuesArray", PointDiscard.UNKNOWN_CODE, n
        ),
        "count",
    ),
    (lambda n: CodeCount(DayFamily.STRESS, "stressValuesArray", "-9", n), "count"),
    (lambda n: BlockCount(TrainingStatusKind.VO2_MAX, n), "count"),
    (
        lambda n: BlockFieldCount(TrainingStatusKind.STATUS, "trainingStatus", n),
        "count",
    ),
    (
        lambda n: DayBoundaryGap(DayFamily.HEART_RATE, "heartRateValues", n, 0.0),
        "pairs",
    ),
    (lambda n: ReadinessCopyCount("night.sleep_score", n, 0), "entries"),
]


@pytest.mark.parametrize(("make", "name"), COUNTS)
def test_counts_are_positive(make: Callable[[int], object], name: str) -> None:
    make(1)
    with _refused(f"{name} doit être >= 1, reçu 0."):
        make(0)


def test_count_texts_are_not_empty() -> None:
    with _refused("piece ne doit pas être vide."):
        BorrowingCount(DayFamily.SLEEP, "", 1)
    with _refused("piece ne doit pas être vide."):
        BorrowingRefusalCount(DayFamily.SLEEP, " ", BorrowingRefusal.DAY_WINDOW, 1)
    with _refused("field_path ne doit pas être vide."):
        ComparisonCount(DayFamily.SLEEP, "", ComparisonClass.REVISION, 1)
    with _refused("series_path ne doit pas être vide."):
        WindowEdgeCount(DayFamily.SLEEP, "", 1, 0)
    with _refused("series_path ne doit pas être vide."):
        DayBoundaryGap(DayFamily.HEART_RATE, "", 1, 0.0)
    with _refused("quantity ne doit pas être vide."):
        ReadinessCopyCount("", 1, 0)
    with _refused("quantity ne doit pas être vide."):
        CopyDisagreementCount("", DayFamily.SLEEP, 1)
    with _refused("series_path ne doit pas être vide."):
        PointDiscardCount(DayFamily.SLEEP, "", PointDiscard.NULL_VALUE, 1)
    with _refused("field_path ne doit pas être vide."):
        CodeCount(DayFamily.SLEEP, "", "-3", 1)
    with _refused("code ne doit pas être vide."):
        CodeCount(DayFamily.SLEEP, "sleepLevels[*].activityLevel", " ", 1)
    with _refused("field_path ne doit pas être vide."):
        BlockFieldCount(TrainingStatusKind.STATUS, "", 1)


def test_day_boundary_gap() -> None:
    """L'écart peut être négatif (deux fichiers qui se recouvrent) ; il est fini."""
    assert (
        DayBoundaryGap(DayFamily.HEART_RATE, "heartRateValues", 2, -3600.0).pairs == 2
    )
    for bad in (NAN, float("inf"), float("-inf")):
        with _refused("max_gap_s doit être fini"):
            DayBoundaryGap(DayFamily.HEART_RATE, "heartRateValues", 1, bad)


def test_readiness_copy_count() -> None:
    """``0 <= differing <= entries``, bornes comprises."""
    assert ReadinessCopyCount("night.sleep_score", 2, 0).differing == 0
    assert ReadinessCopyCount("night.sleep_score", 2, 2).differing == 2
    with _refused("differing ne peut pas dépasser entries."):
        ReadinessCopyCount("night.sleep_score", 2, 3)
    with _refused("differing doit être >= 0, reçu -1."):
        ReadinessCopyCount("night.sleep_score", 2, -1)


def test_window_edge_count() -> None:
    assert (
        WindowEdgeCount(DayFamily.STRESS, "stressValuesArray", 0, 1).outside_window == 0
    )
    assert (
        WindowEdgeCount(DayFamily.STRESS, "stressValuesArray", 1, 0).shared_instants
        == 0
    )
    with _refused(
        "outside_window ou shared_instants doit être > 0 : un compte nul n'est pas "
        "écrit."
    ):
        WindowEdgeCount(DayFamily.STRESS, "stressValuesArray", 0, 0)
    with _refused("outside_window doit être >= 0, reçu -1."):
        WindowEdgeCount(DayFamily.STRESS, "stressValuesArray", -1, 1)
    with _refused("shared_instants doit être >= 0, reçu -1."):
        WindowEdgeCount(DayFamily.STRESS, "stressValuesArray", 1, -1)


def test_a_full_report() -> None:
    report = full_report()
    assert len(report.exports) == 2
    assert [export.files for export in report.exports] == [2, 2]
    assert report.night_equality_violations == 1
    assert report.readiness_non_primary == 2


def test_report_exports() -> None:
    with _refused("exports doit contenir au moins 1 éléments"):
        days_report(exports=(), read=(), reference_days=())
    a = export_report(files=0, first_day=None, last_day=None, families=())
    b = export_report(EXPORT_B, files=0, first_day=None, last_day=None, families=())
    assert days_report(exports=(a, b), read=(), reference_days=()).exports == (a, b)
    with _refused("exports (instant d'acquisition) doit être trié sans doublon"):
        days_report(exports=(b, a), read=(), reference_days=())
    same_instant = dataclasses.replace(b, retrieved_at=a.retrieved_at)
    with _refused("exports (instant d'acquisition) doit être trié sans doublon"):
        days_report(exports=(a, same_instant), read=(), reference_days=())
    same_name = dataclasses.replace(b, name=EXPORT_A)
    with _refused("exports : nom d'export répété."):
        days_report(exports=(a, same_name), read=(), reference_days=())
    with _refused("exports doit être une séquence immuable"):
        days_report(exports=[export_report()])


def test_report_files_match_the_exports() -> None:
    message = (
        "read : un fichier lu se nomme garmin/<export>/<famille>/<fichier>, d'un "
        "export du rapport et d'une famille journalière."
    )
    for name in (
        "garmin/garmin_a/sleep",
        "garmin/garmin_z/sleep/2001-03-10.json",
        "garmin/garmin_a/range/2001-03-10.json",
        "autre/garmin_a/sleep/2001-03-10.json",
        "garmin/garmin_a/sleep/x/2001-03-10.json",
    ):
        with _refused(message):
            days_report(read=(ReadFile(name, "a" * 64),))
    with _refused(
        "exports : files et families d'un export sont ceux de ses fichiers lus."
    ):
        days_report(exports=(export_report(files=2),))
    with _refused(
        "exports : files et families d'un export sont ceux de ses fichiers lus."
    ):
        days_report(exports=(export_report(families=(DayFamily.HRV,)),))
    with _refused("read doit être trié sans doublon : rangs 0 et 1."):
        days_report(
            exports=(export_report(files=2),),
            read=(
                ReadFile(read_name(DayFamily.SLEEP), "a" * 64),
                ReadFile(read_name(DayFamily.SLEEP), "b" * 64),
            ),
        )


def test_report_refused_files_were_read() -> None:
    refused = DayFileRefused(read_name(DayFamily.SLEEP), DayFileRefusal.DATE_MISMATCH)
    assert days_report(refused=(refused,)).refused == (refused,)
    other = DayFileRefused(read_name(DayFamily.HRV), DayFileRefusal.DATE_MISMATCH)
    with _refused("refused : un fichier refusé doit figurer dans read."):
        days_report(refused=(other,))
    with _refused("refused doit être trié sans doublon : rangs 0 et 1."):
        days_report(refused=(refused, refused))


def test_report_reference_days_and_window_families() -> None:
    with _refused(
        "reference_days : un export de référence doit être l'un des exports."
    ):
        days_report(reference_days=(ExportDayCount(EXPORT_B, 1),))
    message = (
        "window_families : une famille qui porte une fenêtre du jour, autre que "
        "daily_summary."
    )
    for family in (DayFamily.DAILY_SUMMARY, DayFamily.SLEEP):
        with _refused(message):
            days_report(window_families=(FamilyDayCount(family, 1),))
    kept = days_report(window_families=(FamilyDayCount(DayFamily.SPO2, 1),))
    assert kept.window_families[0].family is DayFamily.SPO2
    # Une famille à fenêtre propre qui diffère peut être n'importe laquelle.
    mismatch = days_report(
        window_mismatches=(FamilyDayCount(DayFamily.DAILY_SUMMARY, 1),)
    )
    assert mismatch.window_mismatches[0].days == 1


SORTED_LISTS = [
    "reference_days",
    "window_families",
    "window_mismatches",
    "borrowings",
    "borrowing_refusals",
    "comparisons",
    "window_edges",
    "day_boundary_gaps",
    "copy_disagreements",
    "readiness_prior_copies",
    "point_discards",
    "unknown_codes",
    "unknown_confirmations",
    "refused_blocks",
    "block_differences_in_export",
    "block_differences_between_exports",
    "blocks_without_proper_instant",
]


@pytest.mark.parametrize("name", SORTED_LISTS)
def test_report_lists_sorted_without_duplicate(name: str) -> None:
    report = full_report()
    first, second = getattr(report, name)
    for items in ((second, first), (first, first)):
        with _refused(f"{name} doit être trié sans doublon : rangs 0 et 1."):
            dataclasses.replace(report, **_kw(name, items))
    with _refused(f"{name} doit être une séquence immuable"):
        dataclasses.replace(report, **_kw(name, [first, second]))


@pytest.mark.parametrize(
    "name",
    ["night_equality_violations", "naps_overlapping_night", "readiness_non_primary"],
)
def test_report_scalar_counts(name: str) -> None:
    assert getattr(days_report(**_kw(name, 0)), name) == 0
    with _refused(f"{name} doit être >= 0, reçu -1."):
        days_report(**_kw(name, -1))


VALUES: list[object] = [
    day_record(),
    truncated_day(),
    day_record(state=DayState.NO_MEASUREMENT, wellness_data=False),
    empty_day(),
    empty_day(night=night(segments=(), series=EMPTY_NIGHT_SERIES)),
    day_record(
        date(2001, 3, 25),
        night=night(
            date(2001, 3, 25),
            start=at(date(2001, 3, 24), 23),
            end=at(date(2001, 3, 25), 7, offset=PLUS2),
        ),
        naps=(nap(date(2001, 3, 25)),),
    ),
    history(),
    EMPTY_HISTORY,
    days_report(),
    full_report(),
]


@pytest.mark.parametrize("value", VALUES, ids=lambda v: type(v).__name__)
def test_round_trip_by_the_codec_is_exact(value: object) -> None:
    data = encode_interim(value)
    assert decode_interim(data, type(value)) == value
    assert encode_interim(decode_interim(data, type(value))) == data


def test_instants_keep_their_offset_in_the_document() -> None:
    spring = date(2001, 3, 25)
    record = day_record(
        spring,
        night=night(
            spring, start=at(date(2001, 3, 24), 23), end=at(spring, 7, offset=PLUS2)
        ),
    )
    data = json.loads(encode_interim(record))["data"]
    assert data["window_start"] == "2001-03-25T00:00:00+01:00"
    assert data["night"]["start"] == "2001-03-24T23:00:00+01:00"
    assert data["night"]["end"] == "2001-03-25T07:00:00+02:00"
    relu = decode_interim(encode_interim(record), DayRecord)
    assert relu.night is not None
    assert relu.night.end.utcoffset() == timedelta(hours=2)


def test_a_relayed_document_is_revalidated() -> None:
    document = json.loads(encode_interim(day_record()))
    document["data"]["state"] = "truncated"
    with _refused("state truncated : data_end doit précéder window_start + 24 h."):
        decode_interim(canonical_bytes(document), DayRecord)
    report = json.loads(encode_interim(days_report()))
    report["data"]["readiness_non_primary"] = -1
    with _refused("readiness_non_primary doit être >= 0, reçu -1."):
        decode_interim(canonical_bytes(report), DaysReport)
    status = json.loads(encode_interim(history()))
    status["data"]["vo2_max"].reverse()
    with _refused("vo2_max doit être trié sans doublon"):
        decode_interim(canonical_bytes(status), TrainingStatusHistory)


NEW_TYPES = [
    "DayFamily",
    "DayState",
    "Support",
    "SleepStage",
    "BodyBatteryStatus",
    "DayFileRefusal",
    "PointDiscard",
    "BorrowingRefusal",
    "TrainingStatusKind",
    "ComparisonClass",
    "HeartRateSeries",
    "StressSeries",
    "BodyBatterySeries",
    "RespirationSeries",
    "SpO2Series",
    "HrvSeries",
    "RestlessMomentsSeries",
    "DaySeries",
    "NightSeries",
    "SleepSegment",
    "Night",
    "Nap",
    "RestingHr",
    "HrvSummary",
    "RespirationSummary",
    "SpO2Summary",
    "StressSummary",
    "BodyBatterySummary",
    "ActivityTotals",
    "AlgorithmVersions",
    "ReadinessEntry",
    "DayRecord",
    "TrainingStatusBlock",
    "LoadBalanceBlock",
    "Vo2MaxBlock",
    "HeatAcclimationBlock",
    "AltitudeAcclimationBlock",
    "TrainingStatusHistory",
    "DaysExportReport",
    "DayFileRefused",
    "ExportDayCount",
    "FamilyDayCount",
    "BorrowingCount",
    "BorrowingRefusalCount",
    "ComparisonCount",
    "WindowEdgeCount",
    "DayBoundaryGap",
    "CopyDisagreementCount",
    "ReadinessCopyCount",
    "PointDiscardCount",
    "CodeCount",
    "BlockCount",
    "BlockFieldCount",
    "DaysReport",
    "NightState",
    "NightFlag",
    "RestingHrStatus",
    "SeriesKind",
    "ViewAbsence",
]


def test_every_day_type_is_published_after_the_activities() -> None:
    names = [cls.__name__ for cls in DOCUMENTED_TYPES]
    start = names.index("IngestionReport") + 1
    assert names[start : start + len(NEW_TYPES)] == NEW_TYPES
    assert names[start + len(NEW_TYPES)] == "ClimbFlag"
    enums = [cls.__name__ for cls in ENUM_DESCRIPTIONS]
    first = enums.index("IndexDifference") + 1
    assert enums[first : first + len(ENUMS)] == [enum.__name__ for enum, _ in ENUMS]
    assert enums[first + len(ENUMS)] == "ClimbFlag"
    for name in NEW_TYPES:
        assert name in mountain_perf.schemas.__all__


def test_fixture_sources_name_the_family_file() -> None:
    record = day_record()
    assert record.night is not None
    assert record.resting_hr is not None
    assert record.night.source.kind == "garmin_sleep"
    assert record.night.source.identifier == f"{DAY.isoformat()}.json"
    assert record.resting_hr.source.kind == "garmin_resting_hr"
    assert record.readiness[0].source.kind == "garmin_training_readiness"
    assert record.series.heart_rate is not None
    assert record.series.heart_rate.source.kind == "garmin_heart_rate"
