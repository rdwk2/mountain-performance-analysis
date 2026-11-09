"""Des lignes de la table ``jours`` inventées (AN2-2) : une ligne ``absent``, une ligne
``complete`` et un jour sans nuit, chacune constructible avec des champs changés ; pour
une mesure des normales, ses colonnes nommées une à une. Aucune donnée réelle."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from mountain_perf.schemas import NightState, RestingHrStatus, ViewAbsence
from mountain_perf.schemas.processed import (
    AdmissionRefusal,
    DayRow,
    DayRowState,
    JournalEventType,
    NormalAbsence,
)

PLUS1 = timezone(timedelta(hours=1))
PLUS2 = timezone(timedelta(hours=2))

MEASURES: tuple[tuple[str, str], ...] = (
    ("hrv", "_ms"),
    ("resting_hr", "_bpm"),
    ("measured_sleep", "_s"),
    ("night_stress", ""),
    ("night_respiration", "_breaths_per_min"),
    ("night_spo2", "_percent"),
)
"""Les six mesures, dans l'ordre de ``DayRow``, et le suffixe d'unité de leurs
colonnes."""

VALUE_COLUMN: dict[str, str] = {
    "hrv": "hrv_last_night_avg_ms",
    "resting_hr": "resting_hr_bpm",
    "measured_sleep": "measured_sleep_s",
    "night_stress": "night_avg_stress",
    "night_respiration": "respiration_avg_sleep_breaths_per_min",
    "night_spo2": "spo2_avg_sleep_percent",
}
"""La colonne de la valeur de chaque mesure."""

_UNITS = dict(MEASURES)

LOG_CENTER = math.exp(4.0)
LOG_LOW = math.exp(3.9)
LOG_HIGH = math.exp(4.1)


def measure_columns(
    measure: str,
    *,
    admitted: bool = False,
    refusal: AdmissionRefusal | None = AdmissionRefusal.ABSENT_ROW,
    normal: float | None = None,
    low: float | None = None,
    high: float | None = None,
    dispersion: float | None = None,
    log_median: float | None = None,
    admitted_days: int = 0,
    absence: NormalAbsence | None = NormalAbsence.NO_ADMITTED_DAY,
    segment: int = 0,
    rupture: bool = False,
    straddles: bool = False,
) -> dict[str, Any]:
    """Les colonnes des normales d'une mesure, valeurs de la ligne ``absent`` par
    défaut ; pour la HRV, ``dispersion`` est la dispersion du log."""
    unit = _UNITS[measure]
    columns: dict[str, Any] = {
        f"{measure}_admitted": admitted,
        f"{measure}_refusal": refusal,
        f"{measure}_normal{unit}": normal,
        f"{measure}_range_low{unit}": low,
        f"{measure}_range_high{unit}": high,
        f"{measure}_admitted_days": admitted_days,
        f"{measure}_normal_absence": absence,
        f"{measure}_segment": segment,
        f"{measure}_rupture": rupture,
        f"{measure}_normal_straddles": straddles,
    }
    if measure == "hrv":
        columns["hrv_log_median"] = log_median
        columns["hrv_log_dispersion"] = dispersion
    else:
        columns[f"{measure}_dispersion{unit}"] = dispersion
    return columns


def group_of(measure: str) -> tuple[str, ...]:
    """Les colonnes qui vont avec la normale, dans l'ordre du message du contrat."""
    unit = _UNITS[measure]
    head = (
        f"{measure}_normal{unit}",
        f"{measure}_range_low{unit}",
        f"{measure}_range_high{unit}",
    )
    if measure == "hrv":
        return (*head, "hrv_log_dispersion", "hrv_log_median")
    return (*head, f"{measure}_dispersion{unit}")


def _absent_columns() -> dict[str, Any]:
    columns: dict[str, Any] = {
        "day": date(2000, 1, 5),
        "state": DayRowState.ABSENT,
        "window_start": None,
        "data_end": None,
        "reference_export": None,
        "device_ranks": (),
        "uncertain_device": False,
        "sleep_version": None,
        "sleep_respiration_version": None,
        "respiration_version": None,
        "summary_respiration_version": None,
        "summary_body_battery_version": None,
        "body_battery_series_versions": (),
        "night_start": None,
        "night_end": None,
        "night_state": NightState.MISSING,
        "night_short": None,
        "night_short_absence": ViewAbsence.NO_NIGHT,
        "night_shifted": None,
        "night_shifted_absence": ViewAbsence.NO_NIGHT,
        "measured_sleep_s": None,
        "deep_s": None,
        "light_s": None,
        "rem_s": None,
        "awake_s": None,
        "unmeasurable_s": None,
        "unmeasured_fraction": None,
        "night_confirmation": None,
        "night_window_confirmed": None,
        "night_from_device": None,
        "night_rem_capable": None,
        "sleep_score": None,
        "night_avg_stress": None,
        "night_avg_heart_rate_bpm": None,
        "night_body_battery_change": None,
        "night_restless_moments": None,
        "skin_temperature_deviation_c": None,
        "night_body_battery_ceiling": None,
        "night_body_battery_coverage": None,
        "night_body_battery_absence": ViewAbsence.NO_NIGHT,
        "nap_count": 0,
        "nap_window_s": 0.0,
        "nap_sleep_s": 0.0,
        "naps_overlapping_night": 0,
        "resting_hr_bpm": None,
        "resting_hr_status": RestingHrStatus.ABSENT,
        "hrv_last_night_avg_ms": None,
        "hrv_last_night_5min_high_ms": None,
        "hrv_weekly_avg_ms": None,
        "hrv_baseline_balanced_low_ms": None,
        "hrv_baseline_balanced_upper_ms": None,
        "hrv_baseline_low_upper_ms": None,
        "hrv_baseline_marker_value": None,
        "hrv_status": None,
        "respiration_avg_sleep_breaths_per_min": None,
        "respiration_avg_waking_breaths_per_min": None,
        "spo2_avg_sleep_percent": None,
        "spo2_average_percent": None,
        "spo2_lowest_percent": None,
        "stress_average_level": None,
        "stress_max_level": None,
        "stress_measured_s": None,
        "stress_valid": None,
        "body_battery_charged": None,
        "body_battery_drained": None,
        "body_battery_highest": None,
        "body_battery_lowest": None,
        "body_battery_at_wake": None,
        "body_battery_during_sleep": None,
        "steps": None,
        "moderate_intensity_s": None,
        "vigorous_intensity_s": None,
        "floors_ascended_m": None,
        "floors_descended_m": None,
        "average_altitude_m": None,
        "readiness_score": None,
        "readiness_level": None,
        "readiness_instant": None,
        "readiness_absence": ViewAbsence.NO_NIGHT,
        "readiness_entry_count": 0,
        "ts_status_instant": None,
        "ts_status_code": None,
        "ts_acute_load": None,
        "ts_chronic_load": None,
        "ts_acute_chronic_ratio": None,
        "ts_acwr_status": None,
        "ts_load_balance_instant": None,
        "ts_monthly_aerobic_low": None,
        "ts_monthly_aerobic_low_target_min": None,
        "ts_monthly_aerobic_low_target_max": None,
        "ts_monthly_aerobic_high": None,
        "ts_monthly_aerobic_high_target_min": None,
        "ts_monthly_aerobic_high_target_max": None,
        "ts_monthly_anaerobic": None,
        "ts_monthly_anaerobic_target_min": None,
        "ts_monthly_anaerobic_target_max": None,
        "ts_vo2_max_instant": None,
        "ts_vo2_max_ml_kg_min": None,
        "ts_vo2_max_precise_ml_kg_min": None,
        "ts_heat_instant": None,
        "ts_heat_acclimation_percent": None,
        "ts_heat_trend": None,
        "ts_altitude_instant": None,
        "ts_acclimation_altitude_m": None,
        "ts_current_altitude_m": None,
        "ts_altitude_trend": None,
        "journal_types": (),
        "activity_count": 0,
        "garmin_training_load": 0.0,
        "activities_without_load": 0,
        "foot_elapsed_s": 0.0,
        "mtb_elapsed_s": 0.0,
        "ski_touring_elapsed_s": 0.0,
        "other_elapsed_s": 0.0,
        "other_activity_count": 0,
        "activities_without_elapsed": 0,
    }
    for measure, _ in MEASURES:
        columns.update(measure_columns(measure))
    return columns


def _complete_columns() -> dict[str, Any]:
    columns = _absent_columns()
    start = datetime(2000, 1, 6, tzinfo=PLUS1)
    columns.update(
        {
            "day": date(2000, 1, 6),
            "state": DayRowState.COMPLETE,
            "window_start": start,
            "data_end": datetime(2000, 1, 7, 0, 30, tzinfo=PLUS1),
            "reference_export": "export_2000-a",
            "device_ranks": (1,),
            "sleep_version": 2,
            "sleep_respiration_version": 1,
            "respiration_version": 3,
            "summary_respiration_version": 1,
            "summary_body_battery_version": 4,
            "body_battery_series_versions": (3, 4),
            "night_start": datetime(2000, 1, 5, 23, tzinfo=PLUS1),
            "night_end": datetime(2000, 1, 6, 7, tzinfo=PLUS1),
            "night_state": NightState.COMPLETE,
            "night_short": False,
            "night_short_absence": None,
            "night_shifted": None,
            "night_shifted_absence": ViewAbsence.BELOW_USUAL_MINIMUM,
            "measured_sleep_s": 25200.0,
            "deep_s": 5400.0,
            "light_s": 14400.0,
            "rem_s": 5400.0,
            "awake_s": 1800.0,
            "unmeasurable_s": 1200.0,
            "unmeasured_fraction": 1200.0 / 28800.0,
            "night_confirmation": "confirmation_inventee",
            "night_window_confirmed": True,
            "night_from_device": True,
            "night_rem_capable": True,
            "sleep_score": 80,
            "night_avg_stress": 15.0,
            "night_avg_heart_rate_bpm": 50.0,
            "night_body_battery_change": 40,
            "night_restless_moments": 10,
            "skin_temperature_deviation_c": -0.3,
            "night_body_battery_ceiling": False,
            "night_body_battery_coverage": 0.95,
            "night_body_battery_absence": None,
            "nap_count": 1,
            "nap_window_s": 1800.0,
            "nap_sleep_s": 1500.0,
            "naps_overlapping_night": 0,
            "resting_hr_bpm": 48.0,
            "resting_hr_status": RestingHrStatus.VALID,
            "hrv_last_night_avg_ms": 55.0,
            "hrv_last_night_5min_high_ms": 80.0,
            "hrv_weekly_avg_ms": 54.0,
            "hrv_baseline_balanced_low_ms": 48.0,
            "hrv_baseline_balanced_upper_ms": 62.0,
            "hrv_baseline_low_upper_ms": 44.0,
            "hrv_baseline_marker_value": 0.5,
            "hrv_status": "STATUT_INVENTE",
            "respiration_avg_waking_breaths_per_min": 15.0,
            "spo2_avg_sleep_percent": 95.0,
            "spo2_average_percent": 96.0,
            "spo2_lowest_percent": 88.0,
            "stress_average_level": 30,
            "stress_max_level": 90,
            "stress_measured_s": 60000.0,
            "stress_valid": True,
            "body_battery_charged": 60,
            "body_battery_drained": 55,
            "body_battery_highest": 95,
            "body_battery_lowest": 20,
            "body_battery_at_wake": 90,
            "body_battery_during_sleep": 45,
            "steps": 12000,
            "moderate_intensity_s": 1800.0,
            "vigorous_intensity_s": 900.0,
            "floors_ascended_m": 30.0,
            "floors_descended_m": 28.0,
            "average_altitude_m": 1200.0,
            "readiness_score": 70,
            "readiness_level": "NIVEAU_INVENTE",
            "readiness_instant": datetime(2000, 1, 6, 7, 10, tzinfo=PLUS1),
            "readiness_absence": None,
            "readiness_entry_count": 2,
            "ts_status_instant": datetime(2000, 1, 6, 19, tzinfo=UTC),
            "ts_status_code": 4,
            "ts_acute_load": 400.0,
            "ts_chronic_load": 350.0,
            "ts_acute_chronic_ratio": 1.1,
            "ts_acwr_status": "RAPPORT_INVENTE",
            "ts_load_balance_instant": datetime(2000, 1, 7, tzinfo=PLUS1),
            "ts_monthly_aerobic_low": 300.0,
            "ts_monthly_aerobic_low_target_min": 200.0,
            "ts_monthly_aerobic_low_target_max": 400.0,
            "ts_monthly_aerobic_high": 500.0,
            "ts_monthly_aerobic_high_target_min": 450.0,
            "ts_monthly_aerobic_high_target_max": 700.0,
            "ts_monthly_anaerobic": 100.0,
            "ts_monthly_anaerobic_target_min": 50.0,
            "ts_monthly_anaerobic_target_max": 200.0,
            "ts_heat_instant": datetime(2000, 1, 7, 1, tzinfo=PLUS2),
            "ts_heat_acclimation_percent": 20.0,
            "ts_heat_trend": "TENDANCE_INVENTEE",
            "ts_altitude_instant": datetime(2000, 1, 7, tzinfo=PLUS1),
            "ts_acclimation_altitude_m": 1500.0,
            "ts_current_altitude_m": 1200.0,
            "ts_altitude_trend": "TENDANCE_INVENTEE",
            "journal_types": (JournalEventType.RACE, JournalEventType.TRAVEL),
            "activity_count": 3,
            "garmin_training_load": 150.0,
            "activities_without_load": 1,
            "foot_elapsed_s": 3600.0,
            "ski_touring_elapsed_s": 5400.0,
            "activities_without_elapsed": 1,
        }
    )
    columns.update(
        measure_columns(
            "hrv",
            admitted=True,
            refusal=None,
            normal=LOG_CENTER,
            low=LOG_LOW,
            high=LOG_HIGH,
            dispersion=0.1,
            log_median=4.0,
            admitted_days=20,
            absence=None,
            segment=1,
            straddles=True,
        )
    )
    columns.update(
        measure_columns(
            "resting_hr",
            admitted=True,
            refusal=None,
            normal=49.0,
            low=47.5,
            high=50.5,
            dispersion=1.5,
            admitted_days=14,
            absence=None,
        )
    )
    columns.update(
        measure_columns(
            "measured_sleep",
            admitted=True,
            refusal=None,
            normal=26000.0,
            low=24000.0,
            high=28000.0,
            dispersion=2000.0,
            admitted_days=28,
            absence=None,
        )
    )
    columns.update(
        measure_columns(
            "night_stress",
            admitted=True,
            refusal=None,
            admitted_days=5,
            absence=NormalAbsence.TOO_FEW_ADMITTED_DAYS,
        )
    )
    columns.update(
        measure_columns(
            "night_respiration",
            refusal=AdmissionRefusal.NO_VALUE,
            normal=14.0,
            low=13.0,
            high=15.0,
            dispersion=1.0,
            admitted_days=16,
            absence=None,
            segment=2,
        )
    )
    columns.update(
        measure_columns(
            "night_spo2",
            admitted=True,
            refusal=None,
            normal=95.0,
            low=94.0,
            high=96.0,
            dispersion=1.0,
            admitted_days=20,
            absence=None,
            rupture=True,
            straddles=True,
        )
    )
    return columns


def _no_night_columns() -> dict[str, Any]:
    columns = _complete_columns()
    absent = _absent_columns()
    for name in (
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
    ):
        columns[name] = absent[name]
    columns["measured_sleep_admitted"] = False
    columns["measured_sleep_refusal"] = AdmissionRefusal.NO_VALUE
    columns["night_stress_admitted"] = False
    columns["night_stress_refusal"] = AdmissionRefusal.NO_VALUE
    return columns


def absent_row(**changes: Any) -> DayRow:
    """La ligne ``absent``, au 5 janvier 2000."""
    return DayRow(**{**_absent_columns(), **changes})


def complete_row(**changes: Any) -> DayRow:
    """La ligne ``complete``, au 6 janvier 2000."""
    return DayRow(**{**_complete_columns(), **changes})


def no_night_row(**changes: Any) -> DayRow:
    """La ligne d'un jour sans nuit, au 6 janvier 2000."""
    return DayRow(**{**_no_night_columns(), **changes})


def admitted_measure(measure: str, **changes: Any) -> dict[str, Any]:
    """Les champs d'une ligne ``complete`` où ``measure`` a la valeur du jour 40.0, est
    admise, avec 14 jours admis, sa normale, sa plage et sa dispersion ; ``changes``
    s'y ajoutent."""
    columns: dict[str, Any] = {VALUE_COLUMN[measure]: 40.0}
    if measure == "hrv":
        columns.update(
            measure_columns(
                measure,
                admitted=True,
                refusal=None,
                normal=LOG_CENTER,
                low=LOG_LOW,
                high=LOG_HIGH,
                dispersion=0.1,
                log_median=4.0,
                admitted_days=14,
                absence=None,
            )
        )
    else:
        columns.update(
            measure_columns(
                measure,
                admitted=True,
                refusal=None,
                normal=40.0,
                low=39.0,
                high=41.0,
                dispersion=1.0,
                admitted_days=14,
                absence=None,
            )
        )
    return {**columns, **changes}
