"""Les jours des profils de démo (M5-3, D13) : les onze familles journalières de
l'export Garmin et le journal.

Chaque document a la forme du gabarit de même nom de ``tests/fixtures/families.py``
(les mêmes clés, les mêmes racines), réécrit ici : le paquet n'importe rien de
``tests/``. Tous ses instants s'écrivent, comme le gabarit, au **décalage fixe
+01:00 toute l'année** : le jour fait toujours 24 h et la nuit 23:00 – 07:00, 28 800 s
(l'égalité de la nuit tient chaque jour). D'un jour à l'autre ne changent que les dates
et les fenêtres, les six mesures et leurs copies, et l'appareil des jours ; les nombres
du gabarit (identifiants, valeurs rondes) sont ceux d'un format, nommés ici.

Le hasard vient d'un seul flux, ``random.Random(graine + DAYS_SEED_OFFSET)``, créé une
fois par :func:`day_values`, tiré dans l'ordre des jours puis des six mesures, un tirage
par mesure et par jour (D8).
"""

import json
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final

from mountain_perf.demo.constantes import (
    ALTITUDE_DAYS,
    ALTITUDE_FROM_T0,
    DAY_DEVICE_AFTER,
    DAY_DEVICE_BEFORE,
    DAYS_SEED_OFFSET,
    DEVICE_CHANGE_FROM_T0,
    HRV_AFTER_TWO_LAPS_MS,
    HRV_ILLNESS_MS,
    HRV_NOISE_MS,
    HRV_NORMAL_MS,
    HRV_WEEKLY_AVG_MS,
    ILLNESS_DAYS,
    ILLNESS_FROM_T0,
    JOURNAL_NOTE,
    RACE_FROM_T0,
    RESPIRATION_ILLNESS,
    RESPIRATION_NOISE,
    RESPIRATION_NORMAL,
    RESTING_HR_AFTER_TWO_LAPS_BPM,
    RESTING_HR_ALTITUDE_BPM,
    RESTING_HR_ILLNESS_BPM,
    RESTING_HR_NOISE_BPM,
    RESTING_HR_NORMAL_BPM,
    SLEEP_ILLNESS_S,
    SLEEP_NOISE_S,
    SLEEP_NORMAL_S,
    SPO2_ALTITUDE_PERCENT,
    SPO2_ILLNESS_PERCENT,
    SPO2_MISSING_FROM_T0,
    SPO2_NOISE_PERCENT,
    SPO2_NORMAL_PERCENT,
    STRESS_AFTER_TWO_LAPS,
    STRESS_ILLNESS,
    STRESS_NOISE,
    STRESS_NORMAL,
)
from mountain_perf.demo.personnages import Character
from mountain_perf.demo.sorties import export_dir, history_days, plan
from mountain_perf.schemas.days import WAKING_CONTEXT

PLUS1: Final = timezone(timedelta(hours=1))
"""Le décalage fixe des instants du gabarit, toute l'année."""

EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
"""L'époque des instants en millisecondes de la source."""

USER: Final = 42
"""L'identifiant de l'utilisateur du gabarit."""

OTHER_DEVICE: Final = 8
"""L'appareil du gabarit dans ``daily_summary`` (non lu)."""

NIGHT_S: Final = 28_800
UNMEASURABLE_S: Final = 1_800
DEEP_S: Final = 3_600
REM_S: Final = 5_400
"""La nuit du gabarit (23:00 – 07:00), son non mesurable, son profond, son
paradoxal ; le léger complète le sommeil mesuré, l'éveil complète la nuit."""

SLEEP_STEP_S: Final = 60
"""La résolution du sommeil mesuré : le bruit en est un multiple."""

FAMILIES: Final = (
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
)
"""Les onze familles, dans l'ordre de ``DayFamily``."""

JOURNAL_HEADER: Final = "debut;fin;type;note"
"""L'en-tête de ``journal.csv``."""


@dataclass(frozen=True)
class DayValues:
    """Les six mesures d'un jour, sous les noms des colonnes de ``DayRow`` ; la SpO2
    est ``None`` une nuit sans valeur."""

    hrv_last_night_avg_ms: float
    resting_hr_bpm: float
    measured_sleep_s: float
    night_avg_stress: float
    respiration_avg_sleep_breaths_per_min: float
    spo2_avg_sleep_percent: float | None


def _span(t0: date, from_t0: int, days: int) -> set[date]:
    first = t0 - timedelta(days=from_t0)
    return {first + timedelta(days=k) for k in range(days)}


def day_values(
    person: Character, t0: date, *, reduced: bool = False
) -> dict[date, DayValues]:
    """Les six mesures de chaque jour de l'historique : la normale, le bruit du jour,
    puis les écarts, qui s'ajoutent (maladie, séjour en altitude, lendemain d'une
    sortie de deux tours) ; la SpO2 ``None`` les nuits sans valeur."""
    days = history_days(person, reduced=reduced)
    first = t0 - timedelta(days=days)
    after_two_laps = {
        outing.day + timedelta(days=1)
        for outing in plan(person, t0, reduced=reduced)
        if outing.laps == 2
    }
    illness = _span(t0, ILLNESS_FROM_T0, ILLNESS_DAYS)
    altitude = _span(t0, ALTITUDE_FROM_T0, ALTITUDE_DAYS)
    missing = {t0 - timedelta(days=n) for n in SPO2_MISSING_FROM_T0}
    rng = random.Random(person.seed + DAYS_SEED_OFFSET)
    values: dict[date, DayValues] = {}
    for k in range(days):
        day = first + timedelta(days=k)
        x = [2 * rng.random() - 1 for _ in range(6)]
        hrv = HRV_NORMAL_MS + round(HRV_NOISE_MS * x[0])
        resting = RESTING_HR_NORMAL_BPM + round(RESTING_HR_NOISE_BPM * x[1])
        sleep = SLEEP_NORMAL_S + SLEEP_STEP_S * round(
            SLEEP_NOISE_S / SLEEP_STEP_S * x[2]
        )
        stress = STRESS_NORMAL + round(STRESS_NOISE * x[3])
        respiration = RESPIRATION_NORMAL + round(RESPIRATION_NOISE * x[4], 1)
        spo2 = SPO2_NORMAL_PERCENT + round(SPO2_NOISE_PERCENT * x[5])
        if day in illness:
            hrv += HRV_ILLNESS_MS
            resting += RESTING_HR_ILLNESS_BPM
            sleep += SLEEP_ILLNESS_S
            stress += STRESS_ILLNESS
            respiration += RESPIRATION_ILLNESS
            spo2 += SPO2_ILLNESS_PERCENT
        if day in altitude:
            resting += RESTING_HR_ALTITUDE_BPM
            spo2 += SPO2_ALTITUDE_PERCENT
        if day in after_two_laps:
            hrv += HRV_AFTER_TWO_LAPS_MS
            resting += RESTING_HR_AFTER_TWO_LAPS_BPM
            stress += STRESS_AFTER_TWO_LAPS
        values[day] = DayValues(
            float(hrv),
            float(resting),
            float(sleep),
            float(stress),
            round(respiration, 1),
            None if day in missing else float(spo2),
        )
    return values


# --- Les instants du gabarit ----------------------------------------------------------


def _at(day: date, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=PLUS1)


def _ms(instant: datetime) -> int:
    return (instant - EPOCH) // timedelta(milliseconds=1)


def _wall_ms(instant: datetime) -> int:
    offset = instant.utcoffset()
    assert offset is not None
    return _ms(instant) + offset // timedelta(milliseconds=1)


def _gmt(instant: datetime, fraction: str = ".0") -> str:
    return instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S") + fraction


def _local(instant: datetime, fraction: str = ".0") -> str:
    return instant.strftime("%Y-%m-%dT%H:%M:%S") + fraction


def _window(start: datetime) -> dict[str, Any]:
    end = start + timedelta(days=1)
    return {
        "startTimestampGMT": _gmt(start),
        "startTimestampLocal": _local(start),
        "endTimestampGMT": _gmt(end),
        "endTimestampLocal": _local(end),
    }


def _sleep_bounds(day: date) -> dict[str, Any]:
    night_start = _at(day - timedelta(days=1), 23)
    night_end = _at(day, 7)
    tomorrow_start = _at(day, 23)
    tomorrow_end = _at(day + timedelta(days=1), 7)
    return {
        "sleepStartTimestampGMT": _gmt(night_start),
        "sleepStartTimestampLocal": _local(night_start),
        "sleepEndTimestampGMT": _gmt(night_end),
        "sleepEndTimestampLocal": _local(night_end),
        "tomorrowSleepStartTimestampGMT": _gmt(tomorrow_start),
        "tomorrowSleepStartTimestampLocal": _local(tomorrow_start),
        "tomorrowSleepEndTimestampGMT": _gmt(tomorrow_end),
        "tomorrowSleepEndTimestampLocal": _local(tomorrow_end),
    }


def _whole(value: float) -> int:
    """Une mesure entière, écrite en entier JSON comme le gabarit."""
    return round(value)


def _spo2(values: DayValues) -> int | None:
    found = values.spo2_avg_sleep_percent
    return None if found is None else round(found)


# --- Les onze documents ---------------------------------------------------------------


def _sleep(day: date, values: DayValues, device: int | None) -> dict[str, Any]:
    night_start = _at(day - timedelta(days=1), 23)
    night_end = _at(day, 7)
    nap_start = _at(day, 14)
    sleep = _whole(values.measured_sleep_s)
    spo2 = _spo2(values)
    respiration = values.respiration_avg_sleep_breaths_per_min
    return {
        "dailySleepDTO": {
            "id": _ms(night_start),
            "userProfilePK": USER,
            "calendarDate": day.isoformat(),
            "sleepTimeSeconds": sleep,
            "napTimeSeconds": 1500,
            "sleepWindowConfirmed": True,
            "sleepWindowConfirmationType": "enhanced_confirmed_final",
            "sleepStartTimestampGMT": _ms(night_start),
            "sleepEndTimestampGMT": _ms(night_end),
            "sleepStartTimestampLocal": _wall_ms(night_start),
            "sleepEndTimestampLocal": _wall_ms(night_end),
            "autoSleepStartTimestampGMT": None,
            "autoSleepEndTimestampGMT": None,
            "sleepQualityTypePK": None,
            "sleepResultTypePK": None,
            "unmeasurableSleepSeconds": UNMEASURABLE_S,
            "deepSleepSeconds": DEEP_S,
            "lightSleepSeconds": sleep - DEEP_S - REM_S,
            "remSleepSeconds": REM_S,
            "awakeSleepSeconds": NIGHT_S - UNMEASURABLE_S - sleep,
            "deviceRemCapable": True,
            "retro": False,
            "sleepFromDevice": True,
            "averageSpO2Value": spo2,
            "lowestSpO2Value": 90,
            "highestSpO2Value": 99,
            "averageSpO2HRSleep": 50,
            "averageRespirationValue": respiration,
            "lowestRespirationValue": 10,
            "highestRespirationValue": 18,
            "awakeCount": 1,
            "avgSleepStress": _whole(values.night_avg_stress),
            "ageGroup": "ADULT",
            "sleepScoreFeedback": "INVENTED_FEEDBACK",
            "sleepScoreInsight": "INVENTED_INSIGHT",
            "sleepScorePersonalizedInsight": "INVENTED_INSIGHT",
            "sleepScores": {
                "overall": {"value": 80, "qualifierKey": "GOOD"},
                "remPercentage": {"value": 21, "qualifierKey": "GOOD"},
            },
            "sleepVersion": 2,
            "sleepNeed": {
                "userProfilePk": USER,
                "calendarDate": day.isoformat(),
                "deviceId": device,
                "baseline": 480,
                "actual": 480,
                "feedback": "INVENTED_FEEDBACK",
            },
            "nextSleepNeed": {"deviceId": device, "baseline": 480, "actual": 480},
            "sleepAlignment": {"deviceId": device, "userId": USER, "status": "ALIGNED"},
            "breathingDisruptionSeverity": "NONE",
            "avgHeartRate": 50,
            "dailyNapDTOS": [
                {
                    "userProfilePK": USER,
                    "deviceId": device,
                    "calendarDate": day.isoformat(),
                    "napTimeSec": 1500,
                    "napStartTimestampGMT": _gmt(nap_start, ""),
                    "napEndTimestampGMT": _gmt(nap_start + timedelta(minutes=30), ""),
                    "napFeedback": None,
                    "napSource": 1,
                    "napStartTimeOffset": 60,
                    "napEndTimeOffset": 60,
                    "createTimestampGMT": None,
                    "updateTimestampGMT": None,
                }
            ],
        },
        "sleepMovement": [
            {
                "startGMT": _gmt(night_start),
                "endGMT": _gmt(night_start + timedelta(minutes=1)),
                "activityLevel": 0.5,
            }
        ],
        "remSleepData": True,
        "sleepLevels": [
            {
                "startGMT": _gmt(night_start),
                "endGMT": _gmt(night_start + timedelta(hours=1)),
                "activityLevel": 1,
            },
            {
                "startGMT": _gmt(night_start + timedelta(hours=1)),
                "endGMT": _gmt(night_start + timedelta(hours=2)),
                "activityLevel": 0,
            },
        ],
        "sleepRestlessMoments": [
            {"startGMT": _ms(night_start + timedelta(minutes=30)), "value": 1}
        ],
        "restlessMomentsCount": 20,
        "wellnessSpO2SleepSummaryDTO": {
            "userProfilePk": USER,
            "deviceId": device,
            "sleepMeasurementStartGMT": _gmt(night_start),
            "sleepMeasurementEndGMT": _gmt(night_end),
            "alertThresholdValue": None,
            "averageSPO2": spo2,
            "averageSpO2HR": 50,
            "lowestSPO2": 90,
        },
        "wellnessEpochSPO2DataDTOList": [
            {
                "userProfilePK": USER,
                "epochTimestamp": _gmt(night_start + timedelta(minutes=minute)),
                "deviceId": device,
                "calendarDate": _gmt(night_start + timedelta(minutes=minute)),
                "epochDuration": 60,
                "spo2Reading": reading,
                "readingConfidence": 10,
            }
            for minute, reading in ((0, 95), (1, 94))
        ],
        "wellnessEpochRespirationDataDTOList": [
            {"startTimeGMT": _ms(night_start), "respirationValue": 14},
            {
                "startTimeGMT": _ms(night_start + timedelta(minutes=2)),
                "respirationValue": -2,
            },
        ],
        "wellnessEpochRespirationAveragesList": [
            {
                "epochEndTimestampGmt": _ms(night_start + timedelta(hours=1)),
                "respirationAverageValue": 13.5,
                "respirationHighValue": 15,
                "respirationLowValue": 12,
            }
        ],
        "respirationVersion": 200,
        "sleepHeartRate": [
            {"startGMT": _ms(night_start), "value": 52},
            {"startGMT": _ms(night_start + timedelta(minutes=2)), "value": 48},
        ],
        "sleepStress": [
            {"startGMT": _ms(night_start), "value": 10},
            {"startGMT": _ms(night_start + timedelta(minutes=3)), "value": -1},
        ],
        "sleepBodyBattery": [
            {"startGMT": _ms(night_start), "value": 30},
            {"startGMT": _ms(night_end), "value": 80},
        ],
        "skinTempDataExists": True,
        "skinTempCalibrationDays": 30,
        "hrvData": [
            {"startGMT": _ms(night_start + timedelta(minutes=5)), "value": 45},
            {"startGMT": _ms(night_start + timedelta(minutes=10)), "value": 50},
        ],
        "breathingDisruptionData": [],
        "avgOvernightHrv": _whole(values.hrv_last_night_avg_ms),
        "hrvStatus": "BALANCED",
        "bodyBatteryChange": 50,
        "restingHeartRate": _whole(values.resting_hr_bpm),
        "avgSkinTempDeviationC": -0.25,
        "avgSkinTempDeviationF": -0.45,
    }


def _hrv(day: date, values: DayValues) -> dict[str, Any]:
    night_start = _at(day - timedelta(days=1), 23)
    night_end = _at(day, 7)
    return {
        "userProfilePk": USER,
        "hrvSummary": {
            "calendarDate": day.isoformat(),
            "weeklyAvg": HRV_WEEKLY_AVG_MS,
            "lastNightAvg": _whole(values.hrv_last_night_avg_ms),
            "lastNight5MinHigh": 70,
            "baseline": {
                "lowUpper": 35,
                "balancedLow": 40,
                "balancedUpper": 60,
                "markerValue": 0.5,
            },
            "status": "BALANCED",
            "feedbackPhrase": "INVENTED_PHRASE",
            "createTimeStamp": _gmt(night_end, ".125"),
        },
        "hrvReadings": [
            {
                "hrvValue": value,
                "readingTimeGMT": _gmt(night_start + timedelta(minutes=minute)),
                "readingTimeLocal": _local(night_start + timedelta(minutes=minute)),
            }
            for minute, value in ((5, 45), (10, 50))
        ],
        "startTimestampGMT": _gmt(night_start),
        "endTimestampGMT": _gmt(night_end),
        "startTimestampLocal": _local(night_start),
        "endTimestampLocal": _local(night_end),
        "sleepStartTimestampGMT": _gmt(night_start),
        "sleepStartTimestampLocal": _local(night_start),
        "sleepEndTimestampGMT": _gmt(night_end),
        "sleepEndTimestampLocal": _local(night_end),
    }


def _resting_hr(day: date, values: DayValues) -> dict[str, Any]:
    return {
        "userProfileId": USER,
        "statisticsStartDate": day.isoformat(),
        "statisticsEndDate": day.isoformat(),
        "allMetrics": {
            "metricsMap": {
                "WELLNESS_RESTING_HEART_RATE": [
                    {
                        "value": _whole(values.resting_hr_bpm),
                        "calendarDate": day.isoformat(),
                    }
                ]
            }
        },
        "groupedMetrics": None,
    }


def _heart_rate(day: date, values: DayValues) -> dict[str, Any]:
    begin = _at(day)
    return {
        "userProfilePK": USER,
        "calendarDate": day.isoformat(),
        **_window(begin),
        "maxHeartRate": 150,
        "minHeartRate": 45,
        "restingHeartRate": _whole(values.resting_hr_bpm),
        "lastSevenDaysAvgRestingHeartRate": 49,
        "heartRateValueDescriptors": [
            {"key": "timestamp", "index": 0},
            {"key": "heartrate", "index": 1},
        ],
        "heartRateValues": [
            [_ms(begin), 55],
            [_ms(begin + timedelta(minutes=2)), None],
            [_ms(begin + timedelta(hours=12)), 90],
        ],
    }


def _body_battery(day: date) -> list[Any]:
    begin = _at(day)
    offset = begin.utcoffset()
    assert offset is not None
    return [
        {
            "date": day.isoformat(),
            "charged": 60,
            "drained": 55,
            **_window(begin),
            "bodyBatteryValuesArray": [[_ms(begin), 40]],
            "bodyBatteryValueDescriptorDTOList": [
                {
                    "bodyBatteryValueDescriptorIndex": 0,
                    "bodyBatteryValueDescriptorKey": "timestamp",
                },
                {
                    "bodyBatteryValueDescriptorIndex": 1,
                    "bodyBatteryValueDescriptorKey": "bodyBatteryLevel",
                },
            ],
            "bodyBatteryActivityEvent": [
                {
                    "eventType": "SLEEP",
                    "eventStartTimeGmt": _gmt(begin),
                    "timezoneOffset": offset // timedelta(milliseconds=1),
                    "durationInMilliseconds": 28800000,
                    "bodyBatteryImpact": 50,
                    "feedbackType": "INVENTED",
                    "shortFeedback": "INVENTED",
                }
            ],
            "bodyBatteryDynamicFeedbackEvent": {
                "eventTimestampGmt": _gmt(begin),
                "bodyBatteryLevel": "HIGH",
                "feedbackShortType": None,
                "feedbackLongType": "INVENTED",
            },
        }
    ]


def _stress(day: date) -> dict[str, Any]:
    begin = _at(day)
    return {
        "userProfilePK": USER,
        "calendarDate": day.isoformat(),
        **_window(begin),
        "maxStressLevel": 90,
        "avgStressLevel": 25,
        "stressChartValueOffset": 1,
        "stressChartYAxisOrigin": -1,
        "stressValueDescriptorsDTOList": [
            {"key": "timestamp", "index": 0},
            {"key": "stressLevel", "index": 1},
        ],
        "stressValuesArray": [
            [_ms(begin), 20],
            [_ms(begin + timedelta(minutes=3)), -2],
        ],
        "bodyBatteryValueDescriptorsDTOList": [
            {
                "bodyBatteryValueDescriptorIndex": index,
                "bodyBatteryValueDescriptorKey": key,
            }
            for index, key in enumerate(
                (
                    "timestamp",
                    "bodyBatteryStatus",
                    "bodyBatteryLevel",
                    "bodyBatteryVersion",
                )
            )
        ],
        "bodyBatteryValuesArray": [
            [_ms(begin), "MEASURED", 40, 3],
            [_ms(begin + timedelta(minutes=3)), "MODELED", 41, 3],
        ],
    }


def _respiration(day: date, values: DayValues) -> dict[str, Any]:
    begin = _at(day)
    return {
        "userProfilePK": USER,
        "calendarDate": day.isoformat(),
        **_window(begin),
        **_sleep_bounds(day),
        "lowestRespirationValue": 10,
        "highestRespirationValue": 22,
        "avgWakingRespirationValue": 15,
        "avgSleepRespirationValue": values.respiration_avg_sleep_breaths_per_min,
        "avgTomorrowSleepRespirationValue": 31,
        "respirationValueDescriptorsDTOList": [
            {"key": "timestamp", "index": 0},
            {"key": "respiration", "index": 1},
        ],
        "respirationValuesArray": [
            [_ms(begin), 15],
            [_ms(begin + timedelta(minutes=2)), -1],
        ],
        "respirationAveragesValuesArray": [[_ms(begin), 14.5, 16, 13]],
        "respirationVersion": 200,
    }


def _spo2_document(day: date, values: DayValues) -> dict[str, Any]:
    begin = _at(day)
    return {
        "userProfilePK": USER,
        "calendarDate": day.isoformat(),
        **_window(begin),
        **_sleep_bounds(day),
        "averageSpO2": 96,
        "lowestSpO2": 90,
        "lastSevenDaysAvgSpO2": 95.5,
        "latestSpO2": 97,
        "latestSpO2TimestampGMT": _gmt(begin),
        "latestSpO2TimestampLocal": _local(begin),
        "avgSleepSpO2": _spo2(values),
        "avgTomorrowSleepSpO2": 60,
        "spO2ValueDescriptorsDTOList": [
            {"spo2ValueDescriptorIndex": 0, "spo2ValueDescriptorKey": "timestamp"},
            {"spo2ValueDescriptorIndex": 1, "spo2ValueDescriptorKey": "spo2Reading"},
        ],
        "spO2SingleValues": None,
        "continuousReadingDTOList": None,
        "spO2HourlyAverages": [[_ms(begin + timedelta(hours=1)), 96]],
    }


def _daily_summary(day: date, values: DayValues) -> dict[str, Any]:
    begin = _at(day)
    finish = begin + timedelta(days=1)
    return {
        "userProfileId": USER,
        "displayName": "invented",
        "uuid": "invented-uuid",
        "userDailySummaryId": USER,
        "rule": {"typeId": 1, "typeKey": "public"},
        "calendarDate": day.isoformat(),
        "wellnessStartTimeGmt": _gmt(begin),
        "wellnessStartTimeLocal": _local(begin),
        "wellnessEndTimeGmt": _gmt(finish),
        "wellnessEndTimeLocal": _local(finish),
        "durationInMilliseconds": 86400000,
        "includesWellnessData": True,
        "includesActivityData": False,
        "includesCalorieConsumedData": False,
        "privacyProtected": False,
        "source": "GARMIN",
        "totalKilocalories": 2500,
        "activeKilocalories": 500,
        "bmrKilocalories": 2000,
        "netRemainingKilocalories": 0,
        "totalSteps": 10000,
        "dailyStepGoal": 8000,
        "totalDistanceMeters": 8000,
        "moderateIntensityMinutes": 20,
        "vigorousIntensityMinutes": 10,
        "floorsAscendedInMeters": 30.5,
        "floorsDescendedInMeters": 27.5,
        "floorsAscended": 10.0,
        "floorsDescended": 9.0,
        "averageMonitoringEnvironmentAltitude": 1200,
        "minHeartRate": 45,
        "maxHeartRate": 150,
        "restingHeartRate": _whole(values.resting_hr_bpm),
        "lastSevenDaysAvgRestingHeartRate": 49,
        "averageStressLevel": 25,
        "maxStressLevel": 90,
        "stressDuration": 27000,
        "restStressDuration": 36000,
        "activityStressDuration": 3600,
        "uncategorizedStressDuration": 1800,
        "totalStressDuration": 68400,
        "lowStressDuration": 18000,
        "mediumStressDuration": 7200,
        "highStressDuration": 1800,
        "stressQualifier": "BALANCED",
        "bodyBatteryChargedValue": 60,
        "bodyBatteryDrainedValue": 55,
        "bodyBatteryHighestValue": 90,
        "bodyBatteryLowestValue": 20,
        "bodyBatteryMostRecentValue": 40,
        "bodyBatteryDuringSleep": 45,
        "bodyBatteryAtWakeTime": 85,
        "bodyBatteryVersion": 3,
        "bodyBatteryActivityEventList": [
            {
                "eventType": "ACTIVITY",
                "eventStartTimeGmt": _gmt(begin, ""),
                "deviceId": OTHER_DEVICE,
                "activityName": "invented",
                "activityType": "cycling",
                "activityId": 501,
                "bodyBatteryImpact": -10,
            }
        ],
        "averageSpo2": 96,
        "lowestSpo2": 90,
        "latestSpo2": 97,
        "avgWakingRespirationValue": 15,
        "highestRespirationValue": 22,
        "lowestRespirationValue": 10,
        "latestRespirationValue": 14,
        "latestRespirationTimeGMT": _gmt(begin),
        "respirationAlgorithmVersion": 200,
    }


def _readiness_entry(
    day: date, instant: datetime, device: int | None
) -> dict[str, Any]:
    return {
        "userProfilePK": USER,
        "calendarDate": day.isoformat(),
        "timestamp": _gmt(instant),
        "timestampLocal": _local(instant),
        "deviceId": device,
        "level": "MODERATE",
        "feedbackLong": "INVENTED",
        "feedbackShort": "INVENTED",
        "score": 70,
        "sleepScore": 80,
        "sleepScoreFactorPercent": 80,
        "sleepScoreFactorFeedback": "INVENTED",
        "recoveryTime": 600,
        "acuteLoad": 300,
        "hrvWeeklyAverage": HRV_WEEKLY_AVG_MS,
        "validSleep": True,
        "inputContext": WAKING_CONTEXT,
        "primaryActivityTracker": True,
        "recoveryTimeChangePhrase": None,
    }


def _training_readiness(day: date, device: int | None) -> list[Any]:
    evening = _readiness_entry(day, _at(day, 18), device)
    evening["inputContext"] = "UPDATE_REALTIME_VARIABLES"
    return [evening, _readiness_entry(day, _at(day, 7, 5), device)]


def _status_entry(day: date, device: int) -> dict[str, Any]:
    return {
        "calendarDate": day.isoformat(),
        "sinceDate": day.isoformat(),
        "weeklyTrainingLoad": None,
        "trainingStatus": 4,
        "timestamp": _ms(_at(day, 12)),
        "deviceId": device,
        "loadTunnelMin": None,
        "loadTunnelMax": None,
        "loadLevelTrend": None,
        "sport": "RUNNING",
        "subSport": "GENERIC",
        "fitnessTrendSport": "RUNNING",
        "fitnessTrend": 2,
        "trainingStatusFeedbackPhrase": "INVENTED_PHRASE",
        "trainingPaused": False,
        "acuteTrainingLoadDTO": {
            "acwrPercent": 50,
            "acwrStatus": "OPTIMAL",
            "acwrStatusFeedback": "INVENTED",
            "dailyTrainingLoadAcute": 300,
            "maxTrainingLoadChronic": 450.5,
            "minTrainingLoadChronic": 240.5,
            "dailyTrainingLoadChronic": 320,
            "dailyAcuteChronicWorkloadRatio": 0.9,
        },
        "primaryTrainingDevice": True,
    }


def _balance_entry(day: date, device: int) -> dict[str, Any]:
    return {
        "calendarDate": day.isoformat(),
        "deviceId": device,
        "monthlyLoadAerobicLow": 400.5,
        "monthlyLoadAerobicHigh": 300.5,
        "monthlyLoadAnaerobic": 50.5,
        "monthlyLoadAerobicLowTargetMin": 200,
        "monthlyLoadAerobicLowTargetMax": 500,
        "monthlyLoadAerobicHighTargetMin": 200,
        "monthlyLoadAerobicHighTargetMax": 500,
        "monthlyLoadAnaerobicTargetMin": 0,
        "monthlyLoadAnaerobicTargetMax": 100,
        "trainingBalanceFeedbackPhrase": "INVENTED_PHRASE",
        "primaryTrainingDevice": True,
    }


def _training_status(day: date, device: int | None) -> dict[str, Any]:
    yesterday = day - timedelta(days=1)
    statuses = {} if device is None else {str(device): _status_entry(day, device)}
    balances = {} if device is None else {str(device): _balance_entry(day, device)}
    recorded = [
        {
            "deviceId": device,
            "imageURL": "invented",
            "deviceName": "invented",
            "category": 0,
        }
    ]
    return {
        "userId": USER,
        "mostRecentVO2Max": {
            "userId": USER,
            "generic": {
                "calendarDate": yesterday.isoformat(),
                "vo2MaxPreciseValue": 55.5,
                "vo2MaxValue": 56,
                "fitnessAge": None,
                "fitnessAgeDescription": None,
                "maxMetCategory": 0,
            },
            "cycling": None,
            "heatAltitudeAcclimation": {
                "calendarDate": day.isoformat(),
                "altitudeAcclimationDate": (day - timedelta(days=3)).isoformat(),
                "previousAltitudeAcclimationDate": (
                    day - timedelta(days=3)
                ).isoformat(),
                "heatAcclimationDate": (day - timedelta(days=2)).isoformat(),
                "previousHeatAcclimationDate": (day - timedelta(days=3)).isoformat(),
                "altitudeAcclimation": 1500,
                "previousAltitudeAcclimation": 1400,
                "heatAcclimationPercentage": 20,
                "previousHeatAcclimationPercentage": 10,
                "heatTrend": "ACCLIMATIZING",
                "altitudeTrend": "ACCLIMATIZING",
                "currentAltitude": 1600,
                "previousAltitude": 1500,
                "acclimationPercentage": 20,
                "previousAcclimationPercentage": 10,
                "altitudeAcclimationLocalTimestamp": _local(_at(day)),
            },
        },
        "mostRecentTrainingLoadBalance": {
            "userId": USER,
            "metricsTrainingLoadBalanceDTOMap": balances,
            "recordedDevices": [dict(item) for item in recorded],
        },
        "mostRecentTrainingStatus": {
            "userId": USER,
            "latestTrainingStatusData": statuses,
            "recordedDevices": [dict(item) for item in recorded],
            "showSelector": False,
            "lastPrimarySyncDate": day.isoformat(),
        },
        "heatAltitudeAcclimationDTO": None,
    }


def day_device(t0: date, day: date) -> int | None:
    """L'appareil des jours : ``DAY_DEVICE_BEFORE`` avant le changement, aucun la
    veille de la rupture (le jour incertain), ``DAY_DEVICE_AFTER`` dès la rupture."""
    change = t0 - timedelta(days=DEVICE_CHANGE_FROM_T0)
    if day >= change:
        return DAY_DEVICE_AFTER
    if day == change - timedelta(days=1):
        return None
    return DAY_DEVICE_BEFORE


def day_documents(day: date, values: DayValues, device: int | None) -> dict[str, Any]:
    """Les onze documents d'un jour, par nom de famille."""
    return {
        "sleep": _sleep(day, values, device),
        "hrv": _hrv(day, values),
        "resting_hr": _resting_hr(day, values),
        "heart_rate": _heart_rate(day, values),
        "body_battery": _body_battery(day),
        "stress": _stress(day),
        "respiration": _respiration(day, values),
        "spo2": _spo2_document(day, values),
        "daily_summary": _daily_summary(day, values),
        "training_readiness": _training_readiness(day, device),
        "training_status": _training_status(day, device),
    }


def write_days(
    person: Character, folder: Path, t0: date, *, reduced: bool = False
) -> None:
    """Les onze familles de chaque jour de l'historique (du premier jour à T0 − 1)
    sous ``folder/raw/garmin/demo/<famille>/<AAAA-MM-JJ>.json``, avec les valeurs de
    :func:`day_values` et l'appareil de :func:`day_device`."""
    export = export_dir(folder)
    for day, values in day_values(person, t0, reduced=reduced).items():
        documents = day_documents(day, values, day_device(t0, day))
        for family in FAMILIES:
            path = export / family / f"{day.isoformat()}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(json.dumps(documents[family]).encode("utf-8"))


def write_journal(
    person: Character, folder: Path, t0: date, *, reduced: bool = False
) -> None:
    """``folder/journal.csv`` : la maladie, le séjour en altitude et la course, dans
    l'ordre des dates, bornes comprises (le format de ``analyse/journal.py``). Les
    mêmes dates pour tous les personnages et les deux versions."""
    illness = t0 - timedelta(days=ILLNESS_FROM_T0)
    altitude = t0 - timedelta(days=ALTITUDE_FROM_T0)
    race = t0 - timedelta(days=RACE_FROM_T0)
    rows = (
        (illness, illness + timedelta(days=ILLNESS_DAYS - 1), "maladie"),
        (altitude, altitude + timedelta(days=ALTITUDE_DAYS - 1), "sejour_altitude"),
        (race, race, "course"),
    )
    lines = [JOURNAL_HEADER]
    lines += [
        f"{a.isoformat()};{b.isoformat()};{kind};{JOURNAL_NOTE}" for a, b, kind in rows
    ]
    (folder / "journal.csv").write_text(
        "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
    )
