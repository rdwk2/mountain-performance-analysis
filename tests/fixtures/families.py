"""Un document inventé par famille journalière (AN2-1), à la forme des fichiers réels :
leurs chemins, leurs types JSON, leurs formes d'horodatage, leurs codes, et des champs
que l'ingestion ne lit pas (identifiants, textes de conseil, champs ``tomorrow…``,
événements de Body Battery). Le jour ``2001-03-10``, à +01:00 ; ``42`` pour
l'utilisateur, ``7`` et ``8`` pour deux appareils ; des valeurs rondes.

Chaque constructeur rend un document neuf à chaque appel : les tests le modifient.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fixtures.days import DAY, PLUS1, at, midnight, ms, source, wall_ms
from mountain_perf.ingest.families import FamilyRead, read_family
from mountain_perf.schemas import DayFamily, SourceRef

USER = 42
"""L'identifiant inventé de l'utilisateur."""

DEVICE = 7
"""L'identifiant inventé de l'appareil principal."""

OTHER_DEVICE = 8
"""L'identifiant inventé d'un second appareil."""

START = midnight(DAY)
"""Le début de la fenêtre du jour par défaut : minuit, +01:00."""

NIGHT_START = at(DAY - timedelta(days=1), 23)
NIGHT_END = at(DAY, 7)


def gmt_text(instant: datetime, fraction: str = ".0") -> str:
    """Un instant en texte GMT de la source, ``AAAA-MM-JJTHH:MM:SS`` + ``fraction``."""
    return instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S") + fraction


def local_text(instant: datetime, fraction: str = ".0") -> str:
    """Un instant en texte d'heure murale de la source (``…Local``)."""
    return instant.strftime("%Y-%m-%dT%H:%M:%S") + fraction


def encode(document: Any) -> bytes:
    """Les octets d'un document, comme la source les écrit."""
    return json.dumps(document).encode("utf-8")


def read(
    family: DayFamily, document: Any, day: date = DAY, src: SourceRef | None = None
) -> FamilyRead:
    """La lecture d'un document."""
    data = document if isinstance(document, bytes) else encode(document)
    return read_family(family, data, day, src or source(family, day))


def _set(document: Any, path: tuple[str | int, ...], value: Any) -> Any:
    """``document`` dont la valeur au chemin ``path`` est ``value`` (en place) ;
    rend le document."""
    node = document
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return document


def _drop(document: Any, path: tuple[str | int, ...]) -> Any:
    node = document
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    return document


def _window(start: datetime = START, end: datetime | None = None) -> dict[str, Any]:
    end = start + timedelta(days=1) if end is None else end
    return {
        "startTimestampGMT": gmt_text(start),
        "startTimestampLocal": local_text(start),
        "endTimestampGMT": gmt_text(end),
        "endTimestampLocal": local_text(end),
    }


def sleep_document(day: date = DAY) -> dict[str, Any]:
    night_start = at(day - timedelta(days=1), 23)
    night_end = at(day, 7)
    nap_start = at(day, 14)
    return {
        "dailySleepDTO": {
            "id": ms(night_start),
            "userProfilePK": USER,
            "calendarDate": day.isoformat(),
            "sleepTimeSeconds": 25200,
            "napTimeSeconds": 1500,
            "sleepWindowConfirmed": True,
            "sleepWindowConfirmationType": "enhanced_confirmed_final",
            "sleepStartTimestampGMT": ms(night_start),
            "sleepEndTimestampGMT": ms(night_end),
            "sleepStartTimestampLocal": wall_ms(night_start),
            "sleepEndTimestampLocal": wall_ms(night_end),
            "autoSleepStartTimestampGMT": None,
            "autoSleepEndTimestampGMT": None,
            "sleepQualityTypePK": None,
            "sleepResultTypePK": None,
            "unmeasurableSleepSeconds": 1800,
            "deepSleepSeconds": 3600,
            "lightSleepSeconds": 16200,
            "remSleepSeconds": 5400,
            "awakeSleepSeconds": 1800,
            "deviceRemCapable": True,
            "retro": False,
            "sleepFromDevice": True,
            "averageSpO2Value": 95,
            "lowestSpO2Value": 90,
            "highestSpO2Value": 99,
            "averageSpO2HRSleep": 50,
            "averageRespirationValue": 13,
            "lowestRespirationValue": 10,
            "highestRespirationValue": 18,
            "awakeCount": 1,
            "avgSleepStress": 12,
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
                "deviceId": DEVICE,
                "baseline": 480,
                "actual": 480,
                "feedback": "INVENTED_FEEDBACK",
            },
            "nextSleepNeed": {"deviceId": DEVICE, "baseline": 480, "actual": 480},
            "sleepAlignment": {"deviceId": DEVICE, "userId": USER, "status": "ALIGNED"},
            "breathingDisruptionSeverity": "NONE",
            "avgHeartRate": 50,
            "dailyNapDTOS": [
                {
                    "userProfilePK": USER,
                    "deviceId": DEVICE,
                    "calendarDate": day.isoformat(),
                    "napTimeSec": 1500,
                    "napStartTimestampGMT": gmt_text(nap_start, ""),
                    "napEndTimestampGMT": gmt_text(
                        nap_start + timedelta(minutes=30), ""
                    ),
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
                "startGMT": gmt_text(night_start),
                "endGMT": gmt_text(night_start + timedelta(minutes=1)),
                "activityLevel": 0.5,
            }
        ],
        "remSleepData": True,
        "sleepLevels": [
            {
                "startGMT": gmt_text(night_start),
                "endGMT": gmt_text(night_start + timedelta(hours=1)),
                "activityLevel": 1,
            },
            {
                "startGMT": gmt_text(night_start + timedelta(hours=1)),
                "endGMT": gmt_text(night_start + timedelta(hours=2)),
                "activityLevel": 0,
            },
        ],
        "sleepRestlessMoments": [
            {"startGMT": ms(night_start + timedelta(minutes=30)), "value": 1}
        ],
        "restlessMomentsCount": 20,
        "wellnessSpO2SleepSummaryDTO": {
            "userProfilePk": USER,
            "deviceId": DEVICE,
            "sleepMeasurementStartGMT": gmt_text(night_start),
            "sleepMeasurementEndGMT": gmt_text(night_end),
            "alertThresholdValue": None,
            "averageSPO2": 95,
            "averageSpO2HR": 50,
            "lowestSPO2": 90,
        },
        "wellnessEpochSPO2DataDTOList": [
            {
                "userProfilePK": USER,
                "epochTimestamp": gmt_text(night_start + timedelta(minutes=minute)),
                "deviceId": DEVICE,
                "calendarDate": gmt_text(night_start + timedelta(minutes=minute)),
                "epochDuration": 60,
                "spo2Reading": reading,
                "readingConfidence": 10,
            }
            for minute, reading in ((0, 95), (1, 94))
        ],
        "wellnessEpochRespirationDataDTOList": [
            {"startTimeGMT": ms(night_start), "respirationValue": 14},
            {
                "startTimeGMT": ms(night_start + timedelta(minutes=2)),
                "respirationValue": -2,
            },
        ],
        "wellnessEpochRespirationAveragesList": [
            {
                "epochEndTimestampGmt": ms(night_start + timedelta(hours=1)),
                "respirationAverageValue": 13.5,
                "respirationHighValue": 15,
                "respirationLowValue": 12,
            }
        ],
        "respirationVersion": 200,
        "sleepHeartRate": [
            {"startGMT": ms(night_start), "value": 52},
            {"startGMT": ms(night_start + timedelta(minutes=2)), "value": 48},
        ],
        "sleepStress": [
            {"startGMT": ms(night_start), "value": 10},
            {"startGMT": ms(night_start + timedelta(minutes=3)), "value": -1},
        ],
        "sleepBodyBattery": [
            {"startGMT": ms(night_start), "value": 30},
            {"startGMT": ms(night_end), "value": 80},
        ],
        "skinTempDataExists": True,
        "skinTempCalibrationDays": 30,
        "hrvData": [
            {"startGMT": ms(night_start + timedelta(minutes=5)), "value": 45},
            {"startGMT": ms(night_start + timedelta(minutes=10)), "value": 50},
        ],
        "breathingDisruptionData": [],
        "avgOvernightHrv": 50,
        "hrvStatus": "BALANCED",
        "bodyBatteryChange": 50,
        "restingHeartRate": 48,
        "avgSkinTempDeviationC": -0.25,
        "avgSkinTempDeviationF": -0.45,
    }


def hrv_document(day: date = DAY) -> dict[str, Any]:
    night_start = at(day - timedelta(days=1), 23)
    night_end = at(day, 7)
    return {
        "userProfilePk": USER,
        "hrvSummary": {
            "calendarDate": day.isoformat(),
            "weeklyAvg": 48,
            "lastNightAvg": 50,
            "lastNight5MinHigh": 70,
            "baseline": {
                "lowUpper": 35,
                "balancedLow": 40,
                "balancedUpper": 60,
                "markerValue": 0.5,
            },
            "status": "BALANCED",
            "feedbackPhrase": "INVENTED_PHRASE",
            "createTimeStamp": gmt_text(night_end, ".125"),
        },
        "hrvReadings": [
            {
                "hrvValue": value,
                "readingTimeGMT": gmt_text(night_start + timedelta(minutes=minute)),
                "readingTimeLocal": local_text(night_start + timedelta(minutes=minute)),
            }
            for minute, value in ((5, 45), (10, 50))
        ],
        "startTimestampGMT": gmt_text(night_start),
        "endTimestampGMT": gmt_text(night_end),
        "startTimestampLocal": local_text(night_start),
        "endTimestampLocal": local_text(night_end),
        "sleepStartTimestampGMT": gmt_text(night_start),
        "sleepStartTimestampLocal": local_text(night_start),
        "sleepEndTimestampGMT": gmt_text(night_end),
        "sleepEndTimestampLocal": local_text(night_end),
    }


def resting_hr_document(day: date = DAY, value: Any = 48) -> dict[str, Any]:
    return {
        "userProfileId": USER,
        "statisticsStartDate": day.isoformat(),
        "statisticsEndDate": day.isoformat(),
        "allMetrics": {
            "metricsMap": {
                "WELLNESS_RESTING_HEART_RATE": [
                    {"value": value, "calendarDate": day.isoformat()}
                ]
            }
        },
        "groupedMetrics": None,
    }


def heart_rate_document(
    day: date = DAY, start: datetime | None = None
) -> dict[str, Any]:
    begin = midnight(day) if start is None else start
    return {
        "userProfilePK": USER,
        "calendarDate": day.isoformat(),
        **_window(begin),
        "maxHeartRate": 150,
        "minHeartRate": 45,
        "restingHeartRate": 48,
        "lastSevenDaysAvgRestingHeartRate": 49,
        "heartRateValueDescriptors": [
            {"key": "timestamp", "index": 0},
            {"key": "heartrate", "index": 1},
        ],
        "heartRateValues": [
            [ms(begin), 55],
            [ms(begin + timedelta(minutes=2)), None],
            [ms(begin + timedelta(hours=12)), 90],
        ],
    }


def body_battery_document(day: date = DAY) -> list[Any]:
    begin = midnight(day)
    return [
        {
            "date": day.isoformat(),
            "charged": 60,
            "drained": 55,
            **_window(begin),
            "bodyBatteryValuesArray": [[ms(begin), 40]],
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
                    "eventStartTimeGmt": gmt_text(begin),
                    "timezoneOffset": 3600000,
                    "durationInMilliseconds": 28800000,
                    "bodyBatteryImpact": 50,
                    "feedbackType": "INVENTED",
                    "shortFeedback": "INVENTED",
                }
            ],
            "bodyBatteryDynamicFeedbackEvent": {
                "eventTimestampGmt": gmt_text(begin),
                "bodyBatteryLevel": "HIGH",
                "feedbackShortType": None,
                "feedbackLongType": "INVENTED",
            },
        }
    ]


def stress_document(day: date = DAY, start: datetime | None = None) -> dict[str, Any]:
    begin = midnight(day) if start is None else start
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
            [ms(begin), 20],
            [ms(begin + timedelta(minutes=3)), -2],
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
            [ms(begin), "MEASURED", 40, 3],
            [ms(begin + timedelta(minutes=3)), "MODELED", 41, 3],
        ],
    }


def respiration_document(
    day: date = DAY, start: datetime | None = None
) -> dict[str, Any]:
    begin = midnight(day) if start is None else start
    night_start = at(day - timedelta(days=1), 23)
    night_end = at(day, 7)
    tomorrow_start = at(day, 23)
    tomorrow_end = at(day + timedelta(days=1), 7)
    return {
        "userProfilePK": USER,
        "calendarDate": day.isoformat(),
        **_window(begin),
        "sleepStartTimestampGMT": gmt_text(night_start),
        "sleepStartTimestampLocal": local_text(night_start),
        "sleepEndTimestampGMT": gmt_text(night_end),
        "sleepEndTimestampLocal": local_text(night_end),
        "tomorrowSleepStartTimestampGMT": gmt_text(tomorrow_start),
        "tomorrowSleepStartTimestampLocal": local_text(tomorrow_start),
        "tomorrowSleepEndTimestampGMT": gmt_text(tomorrow_end),
        "tomorrowSleepEndTimestampLocal": local_text(tomorrow_end),
        "lowestRespirationValue": 10,
        "highestRespirationValue": 22,
        "avgWakingRespirationValue": 15,
        "avgSleepRespirationValue": 13,
        "avgTomorrowSleepRespirationValue": 31,
        "respirationValueDescriptorsDTOList": [
            {"key": "timestamp", "index": 0},
            {"key": "respiration", "index": 1},
        ],
        "respirationValuesArray": [
            [ms(begin), 15],
            [ms(begin + timedelta(minutes=2)), -1],
        ],
        "respirationAveragesValuesArray": [[ms(begin), 14.5, 16, 13]],
        "respirationVersion": 200,
    }


def spo2_document(day: date = DAY, start: datetime | None = None) -> dict[str, Any]:
    begin = midnight(day) if start is None else start
    night_start = at(day - timedelta(days=1), 23)
    night_end = at(day, 7)
    tomorrow_start = at(day, 23)
    tomorrow_end = at(day + timedelta(days=1), 7)
    return {
        "userProfilePK": USER,
        "calendarDate": day.isoformat(),
        **_window(begin),
        "sleepStartTimestampGMT": gmt_text(night_start),
        "sleepStartTimestampLocal": local_text(night_start),
        "sleepEndTimestampGMT": gmt_text(night_end),
        "sleepEndTimestampLocal": local_text(night_end),
        "tomorrowSleepStartTimestampGMT": gmt_text(tomorrow_start),
        "tomorrowSleepStartTimestampLocal": local_text(tomorrow_start),
        "tomorrowSleepEndTimestampGMT": gmt_text(tomorrow_end),
        "tomorrowSleepEndTimestampLocal": local_text(tomorrow_end),
        "averageSpO2": 96,
        "lowestSpO2": 90,
        "lastSevenDaysAvgSpO2": 95.5,
        "latestSpO2": 97,
        "latestSpO2TimestampGMT": gmt_text(begin),
        "latestSpO2TimestampLocal": local_text(begin),
        "avgSleepSpO2": 95,
        "avgTomorrowSleepSpO2": 60,
        "spO2ValueDescriptorsDTOList": [
            {"spo2ValueDescriptorIndex": 0, "spo2ValueDescriptorKey": "timestamp"},
            {"spo2ValueDescriptorIndex": 1, "spo2ValueDescriptorKey": "spo2Reading"},
        ],
        "spO2SingleValues": None,
        "continuousReadingDTOList": None,
        "spO2HourlyAverages": [[ms(begin + timedelta(hours=1)), 96]],
    }


def daily_summary_document(
    day: date = DAY, start: datetime | None = None, end: datetime | None = None
) -> dict[str, Any]:
    begin = midnight(day) if start is None else start
    finish = begin + timedelta(days=1) if end is None else end
    return {
        "userProfileId": USER,
        "displayName": "invented",
        "uuid": "invented-uuid",
        "userDailySummaryId": USER,
        "rule": {"typeId": 1, "typeKey": "public"},
        "calendarDate": day.isoformat(),
        "wellnessStartTimeGmt": gmt_text(begin),
        "wellnessStartTimeLocal": local_text(begin),
        "wellnessEndTimeGmt": gmt_text(finish),
        "wellnessEndTimeLocal": local_text(finish),
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
        "restingHeartRate": 48,
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
                "eventStartTimeGmt": gmt_text(begin, ""),
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
        "latestRespirationTimeGMT": gmt_text(begin),
        "respirationAlgorithmVersion": 200,
    }


def readiness_entry(day: date = DAY, **changes: Any) -> dict[str, Any]:
    """Une entrée de Training Readiness, « réveil » à 7 h 05 par défaut."""
    instant = at(day, 7, 5)
    entry: dict[str, Any] = {
        "userProfilePK": USER,
        "calendarDate": day.isoformat(),
        "timestamp": gmt_text(instant),
        "timestampLocal": local_text(instant),
        "deviceId": DEVICE,
        "level": "MODERATE",
        "feedbackLong": "INVENTED",
        "feedbackShort": "INVENTED",
        "score": 70,
        "sleepScore": 80,
        "sleepScoreFactorPercent": 80,
        "sleepScoreFactorFeedback": "INVENTED",
        "recoveryTime": 600,
        "acuteLoad": 300,
        "hrvWeeklyAverage": 48,
        "validSleep": True,
        "inputContext": "AFTER_WAKEUP_RESET",
        "primaryActivityTracker": True,
        "recoveryTimeChangePhrase": None,
    }
    return {**entry, **changes}


def training_readiness_document(day: date = DAY) -> list[Any]:
    evening = at(day, 18)
    return [
        readiness_entry(
            day,
            timestamp=gmt_text(evening),
            timestampLocal=local_text(evening),
            inputContext="UPDATE_REALTIME_VARIABLES",
        ),
        readiness_entry(day),
    ]


def status_entry(day: date = DAY, **changes: Any) -> dict[str, Any]:
    """Un bloc « statut » de Training Status, de l'appareil principal."""
    entry: dict[str, Any] = {
        "calendarDate": day.isoformat(),
        "sinceDate": day.isoformat(),
        "weeklyTrainingLoad": None,
        "trainingStatus": 4,
        "timestamp": ms(datetime(day.year, day.month, day.day, 12, tzinfo=PLUS1)),
        "deviceId": DEVICE,
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
    return {**entry, **changes}


def balance_entry(day: date = DAY, **changes: Any) -> dict[str, Any]:
    """Un bloc « équilibre de la charge » de Training Status."""
    entry: dict[str, Any] = {
        "calendarDate": day.isoformat(),
        "deviceId": DEVICE,
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
    return {**entry, **changes}


def vo2_max_entry(
    day: date = DAY - timedelta(days=1), **changes: Any
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "calendarDate": day.isoformat(),
        "vo2MaxPreciseValue": 55.5,
        "vo2MaxValue": 56,
        "fitnessAge": None,
        "fitnessAgeDescription": None,
        "maxMetCategory": 0,
    }
    return {**entry, **changes}


def acclimation_entry(day: date = DAY, **changes: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "calendarDate": day.isoformat(),
        "altitudeAcclimationDate": (day - timedelta(days=3)).isoformat(),
        "previousAltitudeAcclimationDate": (day - timedelta(days=3)).isoformat(),
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
        "altitudeAcclimationLocalTimestamp": local_text(midnight(day)),
    }
    return {**entry, **changes}


_RECORDED = [
    {
        "deviceId": DEVICE,
        "imageURL": "invented",
        "deviceName": "invented",
        "category": 0,
    }
]


def training_status_document(
    day: date = DAY,
    *,
    statuses: dict[str, Any] | None = None,
    balances: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Le document de Training Status ; ``statuses`` et ``balances`` remplacent les
    tables rangées par appareil (``{str(DEVICE): bloc}`` par défaut)."""
    status_table = {str(DEVICE): status_entry(day)} if statuses is None else statuses
    balance_table = {str(DEVICE): balance_entry(day)} if balances is None else balances
    return {
        "userId": USER,
        "mostRecentVO2Max": {
            "userId": USER,
            "generic": vo2_max_entry(day - timedelta(days=1)),
            "cycling": None,
            "heatAltitudeAcclimation": acclimation_entry(day),
        },
        "mostRecentTrainingLoadBalance": {
            "userId": USER,
            "metricsTrainingLoadBalanceDTOMap": balance_table,
            "recordedDevices": [dict(item) for item in _RECORDED],
        },
        "mostRecentTrainingStatus": {
            "userId": USER,
            "latestTrainingStatusData": status_table,
            "recordedDevices": [dict(item) for item in _RECORDED],
            "showSelector": False,
            "lastPrimarySyncDate": day.isoformat(),
        },
        "heatAltitudeAcclimationDTO": None,
    }


DOCUMENTS: dict[DayFamily, Callable[..., Any]] = {
    DayFamily.SLEEP: sleep_document,
    DayFamily.HRV: hrv_document,
    DayFamily.RESTING_HR: resting_hr_document,
    DayFamily.HEART_RATE: heart_rate_document,
    DayFamily.BODY_BATTERY: body_battery_document,
    DayFamily.STRESS: stress_document,
    DayFamily.RESPIRATION: respiration_document,
    DayFamily.SPO2: spo2_document,
    DayFamily.DAILY_SUMMARY: daily_summary_document,
    DayFamily.TRAINING_READINESS: training_readiness_document,
    DayFamily.TRAINING_STATUS: training_status_document,
}
"""Le constructeur du document de chaque famille, pour un jour donné."""
