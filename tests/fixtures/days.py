"""Des jours inventés (AN2-1) : les contrats d'``interim/days/`` construits avec des
valeurs rondes, pour les tests des contrats, des documents et des vues.

Mars 2001, le fuseau +01:00 ; le passage à l'heure d'été du 25 mars 2001 (+01:00 →
+02:00) et le passage à l'heure d'hiver du 28 octobre 2001 (+02:00 → +01:00, un
dimanche de 25 h), à la façon de l'Europe centrale. Aucune valeur réelle. Les aides de
date (``at``, ``midnight``, ``ms``) vivent ici : les documents des familles
(``fixtures/families.py``) les importent.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from mountain_perf.schemas import (
    WAKING_CONTEXT,
    ActivityTotals,
    AlgorithmVersions,
    AltitudeAcclimationBlock,
    BlockCount,
    BlockFieldCount,
    BodyBatterySeries,
    BodyBatteryStatus,
    BodyBatterySummary,
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
    DaysExportReport,
    DaysReport,
    DayState,
    ExportDayCount,
    FamilyDayCount,
    HeartRateSeries,
    HeatAcclimationBlock,
    HrvSeries,
    HrvSummary,
    LoadBalanceBlock,
    Nap,
    Night,
    NightSeries,
    PointDiscard,
    PointDiscardCount,
    ReadFile,
    ReadinessCopyCount,
    ReadinessEntry,
    RespirationSeries,
    RespirationSummary,
    RestingHr,
    RestlessMomentsSeries,
    SleepSegment,
    SleepStage,
    SourceRef,
    SpO2Series,
    SpO2Summary,
    StressSeries,
    StressSummary,
    TrainingStatusBlock,
    TrainingStatusHistory,
    TrainingStatusKind,
    Vo2MaxBlock,
    WindowEdgeCount,
)

NAN = float("nan")

PLUS1 = timezone(timedelta(hours=1))
"""Le fuseau d'hiver des jours inventés."""

PLUS2 = timezone(timedelta(hours=2))
"""Le fuseau d'été des jours inventés."""

DAY = date(2001, 3, 10)
"""Le jour par défaut, un samedi d'hiver (+01:00)."""

SPRING_DAY = date(2001, 3, 25)
"""Le dimanche du passage à l'heure d'été : la fenêtre du jour garde +01:00."""

AUTUMN_DAY = date(2001, 10, 28)
"""Le dimanche du passage à l'heure d'hiver : 25 h, de 00:00+02:00 à 00:00+01:00."""

EXPORT_A = "garmin_a"
EXPORT_B = "garmin_b"
EXPORT_C = "garmin_c"

RETRIEVED = {
    EXPORT_A: datetime(2001, 12, 1, 12, 0, tzinfo=PLUS1),
    EXPORT_B: datetime(2001, 12, 2, 12, 0, tzinfo=PLUS1),
    EXPORT_C: datetime(2001, 12, 3, 12, 0, tzinfo=PLUS1),
}
"""Les instants d'acquisition inventés des exports, A le plus ancien."""

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_DAY_LENGTH = timedelta(days=1)


def midnight(day: date, offset: timezone = PLUS1) -> datetime:
    """Le minuit local de ``day``, au décalage ``offset``."""
    return datetime(day.year, day.month, day.day, tzinfo=offset)


def at(
    day: date, hour: int, minute: int = 0, second: int = 0, *, offset: timezone = PLUS1
) -> datetime:
    """``day`` à ``hour:minute:second``, heure locale au décalage ``offset``."""
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=offset)


def ms(instant: datetime) -> int:
    """Un instant en millisecondes depuis l'époque, exactement."""
    return (instant - EPOCH) // timedelta(milliseconds=1)


def wall_ms(instant: datetime) -> int:
    """Les millisecondes d'heure murale de ``instant`` (l'heure locale écrite comme
    GMT, à la façon des champs « locaux » de ``sleep``)."""
    offset = instant.utcoffset()
    assert offset is not None
    return ms(instant) + offset // timedelta(milliseconds=1)


def source(
    family: DayFamily = DayFamily.SLEEP, day: date = DAY, export: str = EXPORT_A
) -> SourceRef:
    """La provenance du fichier ``<famille>/<day>.json`` de ``export``."""
    digest = hashlib.sha256(f"{export}/{family.value}/{day}".encode()).hexdigest()
    return SourceRef(
        f"garmin_{family.value}", f"{day.isoformat()}.json", digest, RETRIEVED[export]
    )


SRC = source()
"""Une provenance quelconque."""


def _merge(defaults: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    unknown = set(changes) - set(defaults)
    assert not unknown, unknown
    return {**defaults, **changes}


# --- la nuit -----------------------------------------------------------------------

DEFAULT_SEGMENTS: tuple[SleepSegment, ...] = (
    SleepSegment(0.0, 3600.0, SleepStage.LIGHT),
    SleepSegment(3600.0, 7200.0, SleepStage.DEEP),
    SleepSegment(7200.0, 14400.0, SleepStage.LIGHT),
    SleepSegment(14400.0, 19800.0, SleepStage.REM),
    SleepSegment(19800.0, 21600.0, SleepStage.AWAKE),
    SleepSegment(21600.0, 27000.0, SleepStage.LIGHT),
    SleepSegment(27000.0, 28800.0, SleepStage.UNMEASURABLE),
)
"""Les segments de la nuit par défaut, de 23 h à 7 h : profond 1 h, léger 4 h 30,
paradoxal 1 h 30, éveil 30 min, non mesurable 30 min (le résumé de ``night``)."""

EMPTY_NIGHT_SERIES = NightSeries(None, None, None, None, None, None, None)
EMPTY_DAY_SERIES = DaySeries(None, None, None, None, None)


def night_series(src: SourceRef = SRC) -> NightSeries:
    """Les séries de la nuit par défaut, en secondes depuis son début."""
    return NightSeries(
        heart_rate=HeartRateSeries((0.0, 120.0), (52.0, 48.0), src),
        stress=StressSeries((0.0, 180.0), (10, None), (None, -1), src),
        body_battery=BodyBatterySeries((0.0, 28800.0), (30, 80), (None, None), src),
        hrv=HrvSeries((300.0, 600.0), (45.0, 50.0), src),
        respiration=RespirationSeries((0.0, 120.0), (14.0, None), (None, -2), src),
        spo2=SpO2Series((0.0, 60.0), (95.0, 94.0), src),
        restless_moments=RestlessMomentsSeries((1800.0,), (1,), src),
    )


def night(day: date = DAY, **changes: Any) -> Night:
    """La nuit principale de ``day`` : de 23 h la veille à 7 h, à +01:00."""
    src = source(DayFamily.SLEEP, day)
    defaults: dict[str, Any] = {
        "start": at(day - _DAY_LENGTH, 23),
        "end": at(day, 7),
        "deep_s": 3600.0,
        "light_s": 16200.0,
        "rem_s": 5400.0,
        "awake_s": 1800.0,
        "unmeasurable_s": 1800.0,
        "confirmation": "enhanced_confirmed_final",
        "window_confirmed": True,
        "from_device": True,
        "rem_capable": True,
        "segments": DEFAULT_SEGMENTS,
        "sleep_score": 80,
        "avg_stress": 12.0,
        "avg_heart_rate_bpm": 50.0,
        "body_battery_change": 50,
        "restless_moments": 20,
        "skin_temperature_deviation_c": -0.25,
        "series": night_series(src),
        "source": src,
    }
    return Night(**_merge(defaults, changes))


def nap(day: date = DAY, **changes: Any) -> Nap:
    """Une sieste de ``day``, de 14 h à 14 h 30 (+01:00), 25 min de sommeil."""
    defaults: dict[str, Any] = {
        "start": at(day, 14),
        "end": at(day, 14, 30),
        "sleep_s": 1500.0,
        "nap_source_code": 1,
        "source": source(DayFamily.SLEEP, day),
    }
    return Nap(**_merge(defaults, changes))


def readiness(day: date = DAY, **changes: Any) -> ReadinessEntry:
    """Une entrée « réveil » de Training Readiness de ``day``, à 7 h 05."""
    defaults: dict[str, Any] = {
        "instant": at(day, 7, 5),
        "input_context": WAKING_CONTEXT,
        "score": 70,
        "level": "MODERATE",
        "valid_sleep": True,
        "sleep_score": 80,
        "hrv_weekly_average_ms": 48.0,
        "acute_load": 300.0,
        "source": source(DayFamily.TRAINING_READINESS, day),
    }
    return ReadinessEntry(**_merge(defaults, changes))


# --- les valeurs du jour ------------------------------------------------------------


def resting_hr(day: date = DAY, **changes: Any) -> RestingHr:
    defaults: dict[str, Any] = {
        "resting_hr_bpm": 48.0,
        "source": source(DayFamily.RESTING_HR, day),
    }
    return RestingHr(**_merge(defaults, changes))


def hrv_summary(day: date = DAY, **changes: Any) -> HrvSummary:
    defaults: dict[str, Any] = {
        "last_night_avg_ms": 50.0,
        "last_night_5min_high_ms": 70.0,
        "weekly_avg_ms": 48.0,
        "status": "BALANCED",
        "baseline_balanced_low_ms": 40.0,
        "baseline_balanced_upper_ms": 60.0,
        "baseline_low_upper_ms": 35.0,
        "baseline_marker_value": 0.5,
        "source": source(DayFamily.HRV, day),
    }
    return HrvSummary(**_merge(defaults, changes))


def respiration_summary(day: date = DAY, **changes: Any) -> RespirationSummary:
    defaults: dict[str, Any] = {
        "avg_sleep_breaths_per_min": 13.0,
        "avg_waking_breaths_per_min": 15.0,
        "highest_breaths_per_min": 22.0,
        "lowest_breaths_per_min": 10.0,
        "source": source(DayFamily.RESPIRATION, day),
    }
    return RespirationSummary(**_merge(defaults, changes))


def spo2_summary(day: date = DAY, **changes: Any) -> SpO2Summary:
    defaults: dict[str, Any] = {
        "avg_sleep_spo2_percent": 95.0,
        "average_spo2_percent": 96.0,
        "lowest_spo2_percent": 90.0,
        "source": source(DayFamily.SPO2, day),
    }
    return SpO2Summary(**_merge(defaults, changes))


def stress_summary(day: date = DAY, **changes: Any) -> StressSummary:
    defaults: dict[str, Any] = {
        "average_level": 25,
        "average_level_code": None,
        "max_level": 90,
        "rest_duration_s": 36000.0,
        "low_duration_s": 18000.0,
        "medium_duration_s": 7200.0,
        "high_duration_s": 1800.0,
        "activity_duration_s": 3600.0,
        "uncategorized_duration_s": 1800.0,
        "total_duration_s": 68400.0,
        "stress_duration_s": 27000.0,
        "source": source(DayFamily.DAILY_SUMMARY, day),
    }
    return StressSummary(**_merge(defaults, changes))


def body_battery_summary(day: date = DAY, **changes: Any) -> BodyBatterySummary:
    defaults: dict[str, Any] = {
        "charged": 60,
        "drained": 55,
        "highest": 90,
        "lowest": 20,
        "at_wake": 85,
        "during_sleep": 45,
        "source": source(DayFamily.DAILY_SUMMARY, day),
    }
    return BodyBatterySummary(**_merge(defaults, changes))


def activity_totals(day: date = DAY, **changes: Any) -> ActivityTotals:
    defaults: dict[str, Any] = {
        "steps": 10000,
        "moderate_intensity_s": 1200.0,
        "vigorous_intensity_s": 600.0,
        "floors_ascended_m": 30.5,
        "floors_descended_m": 27.5,
        "average_altitude_m": 1200.0,
        "source": source(DayFamily.DAILY_SUMMARY, day),
    }
    return ActivityTotals(**_merge(defaults, changes))


def versions(**changes: Any) -> AlgorithmVersions:
    defaults: dict[str, Any] = {
        "sleep_version": 2,
        "sleep_respiration_version": 200,
        "respiration_version": 200,
        "summary_respiration_version": 200,
        "summary_body_battery_version": 3,
        "body_battery_series_versions": (3,),
    }
    return AlgorithmVersions(**_merge(defaults, changes))


NO_VERSIONS = AlgorithmVersions(None, None, None, None, None, ())


def day_series(day: date = DAY) -> DaySeries:
    """Les séries de la journée par défaut, en secondes depuis minuit."""
    return DaySeries(
        heart_rate=HeartRateSeries(
            (0.0, 43200.0), (55.0, 90.0), source(DayFamily.HEART_RATE, day)
        ),
        stress=StressSeries(
            (0.0, 180.0), (20, None), (None, -2), source(DayFamily.STRESS, day)
        ),
        body_battery=BodyBatterySeries(
            (0.0, 180.0),
            (40, 41),
            (BodyBatteryStatus.MEASURED, BodyBatteryStatus.RESET),
            source(DayFamily.STRESS, day),
        ),
        respiration=RespirationSeries(
            (0.0, 120.0), (15.0, None), (None, -1), source(DayFamily.RESPIRATION, day)
        ),
        spo2=SpO2Series((3600.0,), (96.0,), source(DayFamily.SPO2, day)),
    )


def day_record(day: date = DAY, **changes: Any) -> DayRecord:
    """Un jour complet de ``day`` : fenêtre de minuit à minuit (+01:00), toutes ses
    grandeurs."""
    start = midnight(day)
    defaults: dict[str, Any] = {
        "day": day,
        "window_start": start,
        "data_end": start + _DAY_LENGTH,
        "window_family": DayFamily.DAILY_SUMMARY,
        "wellness_data": True,
        "state": DayState.COMPLETE,
        "reference_export": EXPORT_A,
        "night": night(day),
        "naps": (nap(day),),
        "resting_hr": resting_hr(day),
        "hrv": hrv_summary(day),
        "respiration": respiration_summary(day),
        "spo2": spo2_summary(day),
        "stress": stress_summary(day),
        "body_battery": body_battery_summary(day),
        "activity_totals": activity_totals(day),
        "series": day_series(day),
        "readiness": (readiness(day),),
        "versions": versions(),
        "device_ranks": (1,),
    }
    return DayRecord(**_merge(defaults, changes))


def truncated_day(day: date = DAY, **changes: Any) -> DayRecord:
    """Un jour tronqué : ses données s'arrêtent à midi."""
    defaults: dict[str, Any] = {
        "data_end": at(day, 12),
        "state": DayState.TRUNCATED,
    }
    return day_record(day, **{**defaults, **changes})


def empty_day(day: date = DAY, **changes: Any) -> DayRecord:
    """Un jour ``empty`` : aucune fenêtre, aucune série du jour, aucune valeur."""
    defaults: dict[str, Any] = {
        "window_start": None,
        "data_end": None,
        "window_family": None,
        "wellness_data": None,
        "state": DayState.EMPTY,
        "night": None,
        "naps": (),
        "resting_hr": None,
        "hrv": None,
        "respiration": None,
        "spo2": None,
        "stress": None,
        "body_battery": None,
        "activity_totals": None,
        "series": EMPTY_DAY_SERIES,
        "readiness": (),
        "versions": NO_VERSIONS,
        "device_ranks": (),
    }
    return day_record(day, **{**defaults, **changes})


# --- Training Status ---------------------------------------------------------------


def status_block(day: date = DAY, **changes: Any) -> TrainingStatusBlock:
    """Un bloc « statut » de ``day``, horodaté à 18 h (UTC)."""
    timestamp = datetime(day.year, day.month, day.day, 18, tzinfo=UTC)
    defaults: dict[str, Any] = {
        "day": day,
        "file_day": day,
        "timestamp": timestamp,
        "proper_instant": timestamp,
        "status_code": 4,
        "acute_load": 300.0,
        "chronic_load": 320.0,
        "acute_chronic_ratio": 0.9,
        "acwr_percent": 50.0,
        "acwr_status": "OPTIMAL",
        "min_chronic_load": 240.5,
        "max_chronic_load": 450.5,
        "paused": False,
        "fitness_trend": 2,
        "source": source(DayFamily.TRAINING_STATUS, day),
    }
    return TrainingStatusBlock(**_merge(defaults, changes))


def _day_end(day: date) -> datetime:
    return midnight(day) + _DAY_LENGTH


def load_balance_block(day: date = DAY, **changes: Any) -> LoadBalanceBlock:
    defaults: dict[str, Any] = {
        "day": day,
        "file_day": day,
        "proper_instant": _day_end(day),
        "monthly_aerobic_low": 400.5,
        "monthly_aerobic_low_target_min": 200.0,
        "monthly_aerobic_low_target_max": 500.0,
        "monthly_aerobic_high": 300.5,
        "monthly_aerobic_high_target_min": 200.0,
        "monthly_aerobic_high_target_max": 500.0,
        "monthly_anaerobic": 50.5,
        "monthly_anaerobic_target_min": 0.0,
        "monthly_anaerobic_target_max": 100.0,
        "source": source(DayFamily.TRAINING_STATUS, day),
    }
    return LoadBalanceBlock(**_merge(defaults, changes))


def vo2_max_block(day: date = DAY, **changes: Any) -> Vo2MaxBlock:
    defaults: dict[str, Any] = {
        "day": day,
        "file_day": day,
        "proper_instant": _day_end(day),
        "vo2_max_precise_ml_kg_min": 55.5,
        "vo2_max_ml_kg_min": 56.0,
        "source": source(DayFamily.TRAINING_STATUS, day),
    }
    return Vo2MaxBlock(**_merge(defaults, changes))


def heat_block(day: date = DAY, **changes: Any) -> HeatAcclimationBlock:
    defaults: dict[str, Any] = {
        "day": day,
        "file_day": day,
        "proper_instant": _day_end(day),
        "heat_acclimation_percent": 20.0,
        "heat_trend": "ACCLIMATIZING",
        "source": source(DayFamily.TRAINING_STATUS, day),
    }
    return HeatAcclimationBlock(**_merge(defaults, changes))


def altitude_block(day: date = DAY, **changes: Any) -> AltitudeAcclimationBlock:
    defaults: dict[str, Any] = {
        "day": day,
        "file_day": day,
        "proper_instant": _day_end(day),
        "acclimation_altitude_m": 1500.0,
        "current_altitude_m": 1600.0,
        "altitude_trend": "ACCLIMATIZING",
        "source": source(DayFamily.TRAINING_STATUS, day),
    }
    return AltitudeAcclimationBlock(**_merge(defaults, changes))


def history() -> TrainingStatusHistory:
    """Deux jours de chaque sorte."""
    days = (DAY, DAY + _DAY_LENGTH)
    return TrainingStatusHistory(
        statuses=tuple(status_block(d) for d in days),
        load_balances=tuple(load_balance_block(d) for d in days),
        vo2_max=tuple(vo2_max_block(d) for d in days),
        heat_acclimation=tuple(heat_block(d) for d in days),
        altitude_acclimation=tuple(altitude_block(d) for d in days),
    )


EMPTY_HISTORY = TrainingStatusHistory((), (), (), (), ())


# --- le rapport ---------------------------------------------------------------------


def read_name(family: DayFamily, day: date = DAY, export: str = EXPORT_A) -> str:
    """Le nom au rapport d'un fichier journalier."""
    return f"garmin/{export}/{family.value}/{day.isoformat()}.json"


def export_report(export: str = EXPORT_A, **changes: Any) -> DaysExportReport:
    defaults: dict[str, Any] = {
        "name": export,
        "retrieved_at": RETRIEVED[export],
        "first_day": DAY,
        "last_day": DAY,
        "files": 1,
        "families": (DayFamily.SLEEP,),
    }
    return DaysExportReport(**_merge(defaults, changes))


def days_report(**changes: Any) -> DaysReport:
    """Un rapport minimal : un export, un fichier ``sleep`` lu, rien d'autre."""
    defaults: dict[str, Any] = {
        "exports": (export_report(),),
        "read": (ReadFile(read_name(DayFamily.SLEEP), "a" * 64),),
        "refused": (),
        "reference_days": (ExportDayCount(EXPORT_A, 1),),
        "window_families": (),
        "window_mismatches": (),
        "borrowings": (),
        "borrowing_refusals": (),
        "comparisons": (),
        "window_edges": (),
        "day_boundary_gaps": (),
        "copy_disagreements": (),
        "readiness_prior_copies": (),
        "night_equality_violations": 0,
        "point_discards": (),
        "unknown_codes": (),
        "unknown_confirmations": (),
        "naps_overlapping_night": 0,
        "refused_blocks": (),
        "block_differences_in_export": (),
        "block_differences_between_exports": (),
        "blocks_without_proper_instant": (),
        "readiness_non_primary": 0,
    }
    return DaysReport(**_merge(defaults, changes))


def full_report() -> DaysReport:
    """Un rapport à deux exports dont chaque liste porte deux comptes, triés."""
    read_a = (
        ReadFile(read_name(DayFamily.HEART_RATE), "b" * 64),
        ReadFile(read_name(DayFamily.SLEEP), "a" * 64),
    )
    read_b = (
        ReadFile(read_name(DayFamily.SLEEP, export=EXPORT_B), "c" * 64),
        ReadFile(read_name(DayFamily.SLEEP, DAY + _DAY_LENGTH, EXPORT_B), "d" * 64),
    )
    return days_report(
        exports=(
            export_report(files=2, families=(DayFamily.HEART_RATE, DayFamily.SLEEP)),
            export_report(EXPORT_B, last_day=DAY + _DAY_LENGTH, files=2),
        ),
        read=(*read_a, *read_b),
        refused=(
            DayFileRefused(
                read_name(DayFamily.HEART_RATE), DayFileRefusal.DATE_MISMATCH
            ),
        ),
        reference_days=(ExportDayCount(EXPORT_A, 1), ExportDayCount(EXPORT_B, 1)),
        window_families=(
            FamilyDayCount(DayFamily.HEART_RATE, 1),
            FamilyDayCount(DayFamily.STRESS, 2),
        ),
        window_mismatches=(
            FamilyDayCount(DayFamily.HEART_RATE, 1),
            FamilyDayCount(DayFamily.SPO2, 1),
        ),
        borrowings=(
            BorrowingCount(DayFamily.SLEEP, "night", 1),
            BorrowingCount(DayFamily.SLEEP, "night.series.hrv", 2),
        ),
        borrowing_refusals=(
            BorrowingRefusalCount(
                DayFamily.HEART_RATE,
                "series.heart_rate",
                BorrowingRefusal.DAY_WINDOW,
                1,
            ),
            BorrowingRefusalCount(
                DayFamily.SLEEP, "night", BorrowingRefusal.NIGHT_WINDOW, 1
            ),
        ),
        comparisons=(
            ComparisonCount(
                DayFamily.SLEEP,
                "dailySleepDTO.sleepScores.overall.value",
                ComparisonClass.REVISION,
                1,
            ),
            ComparisonCount(
                DayFamily.SLEEP, "sleepLevels[*]", ComparisonClass.DEGRADATION, 2
            ),
        ),
        window_edges=(
            WindowEdgeCount(DayFamily.HEART_RATE, "heartRateValues", 1, 0),
            WindowEdgeCount(DayFamily.STRESS, "stressValuesArray", 0, 2),
        ),
        day_boundary_gaps=(
            DayBoundaryGap(DayFamily.HEART_RATE, "heartRateValues", 1, -120.0),
            DayBoundaryGap(DayFamily.STRESS, "stressValuesArray", 1, 180.0),
        ),
        copy_disagreements=(
            CopyDisagreementCount("hrv.last_night_avg_ms", DayFamily.SLEEP, 1),
            CopyDisagreementCount("resting_hr.resting_hr_bpm", DayFamily.HEART_RATE, 2),
        ),
        readiness_prior_copies=(
            ReadinessCopyCount("hrv.weekly_avg_ms", 2, 1),
            ReadinessCopyCount("night.sleep_score", 2, 0),
        ),
        night_equality_violations=1,
        point_discards=(
            PointDiscardCount(
                DayFamily.HEART_RATE, "heartRateValues", PointDiscard.NULL_VALUE, 3
            ),
            PointDiscardCount(
                DayFamily.STRESS, "stressValuesArray", PointDiscard.UNKNOWN_CODE, 1
            ),
        ),
        unknown_codes=(
            CodeCount(DayFamily.STRESS, "stressValuesArray[*][1]", "-3", 1),
            CodeCount(DayFamily.TRAINING_READINESS, "[*].inputContext", "INVENTED", 1),
        ),
        unknown_confirmations=(
            CodeCount(
                DayFamily.SLEEP, "dailySleepDTO.sleepWindowConfirmationType", "x", 1
            ),
            CodeCount(
                DayFamily.SLEEP, "dailySleepDTO.sleepWindowConfirmationType", "y", 1
            ),
        ),
        naps_overlapping_night=1,
        refused_blocks=(
            BlockCount(TrainingStatusKind.STATUS, 1),
            BlockCount(TrainingStatusKind.VO2_MAX, 1),
        ),
        block_differences_in_export=(
            BlockFieldCount(TrainingStatusKind.VO2_MAX, "vo2MaxPreciseValue", 1),
            BlockFieldCount(TrainingStatusKind.VO2_MAX, "vo2MaxValue", 1),
        ),
        block_differences_between_exports=(
            BlockFieldCount(TrainingStatusKind.STATUS, "trainingStatus", 1),
            BlockFieldCount(TrainingStatusKind.VO2_MAX, "vo2MaxValue", 1),
        ),
        blocks_without_proper_instant=(
            BlockCount(TrainingStatusKind.HEAT_ACCLIMATION, 1),
            BlockCount(TrainingStatusKind.LOAD_BALANCE, 1),
        ),
        readiness_non_primary=2,
    )
