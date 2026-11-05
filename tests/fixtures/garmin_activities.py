"""Les activités d'un faux export Garmin, à l'octet près : de quoi tenir la condition
(2) du moteur (AN2-1) — ``interim/activities/`` s'écrit pour les mêmes exports comme
avant les données journalières.

Un index de deux activités et leurs deux archives FIT, écrits par ``fit_activity`` ;
les archives sont des zip sans compression, à date, attributs et système créateur
fixes, pour que leurs octets ne dépendent ni de l'heure ni du système. Ce module
n'importe que ce que le dépôt avait avant AN2-1 : il s'exécute aussi sur ce code-là,
pour en tirer les empreintes écrites en dur dans le test. Valeurs inventées.
"""

from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from fixtures.fit_activity import Sample, activity_fit

EXPORT = "garmin_a"
"""Le nom du faux export."""

RETRIEVED_AT = "2001-03-12T12:00:00+01:00"
"""Son instant d'acquisition (inventé)."""

_ZIP_DATE = (2001, 3, 12, 12, 0, 0)

_ENTRIES: tuple[dict[str, object], ...] = (
    {
        "activityId": 11,
        "activityName": "nom inventé",
        "activityType": {"typeKey": "trail_running", "parentTypeId": 1},
        "startTimeLocal": "2001-03-10 09:00:00",
        "startTimeGMT": "2001-03-10 08:00:00",
        "elapsedDuration": 60.0,
        "duration": 60.0,
        "movingDuration": 55.0,
        "distance": 100.0,
        "elevationGain": 10.0,
        "elevationLoss": 5.0,
        "averageHR": 120.0,
        "maxHR": 140.0,
        "activityTrainingLoad": 20.5,
        "ownerId": 42,
        "deviceId": 7,
    },
    {
        "activityId": 12,
        "activityName": "nom inventé",
        "activityType": {"typeKey": "hiking", "parentTypeId": 3},
        "startTimeLocal": "2001-03-11 10:00:00",
        "startTimeGMT": "2001-03-11 09:00:00",
        "elapsedDuration": 60.0,
        "duration": 60.0,
        "movingDuration": 50.0,
        "distance": 80.0,
        "elevationGain": 20.0,
        "elevationLoss": 0.0,
        "averageHR": 110.0,
        "maxHR": 130.0,
        "ownerId": 42,
        "deviceId": 7,
    },
)

_STARTS = {
    11: datetime(2001, 3, 10, 8, 0, tzinfo=UTC),
    12: datetime(2001, 3, 11, 9, 0, tzinfo=UTC),
}


def _archive(path: Path, member: str, data: bytes) -> None:
    """Une archive zip à un membre, sans compression, aux métadonnées fixes."""
    info = zipfile.ZipInfo(member, date_time=_ZIP_DATE)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 0
    info.external_attr = 0
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr(info, data)


def write_activities_export(root: Path, name: str = EXPORT) -> Path:
    """Écrit ``root/raw/garmin/<name>/`` : ``acquisition.json``, l'index et les deux
    archives ; rend le dossier de l'export."""
    export = root / "raw" / "garmin" / name
    (export / "activities").mkdir(parents=True)
    (export / "activity_fit").mkdir()
    (export / "acquisition.json").write_text(
        json.dumps({"retrieved_at": RETRIEVED_AT}), encoding="utf-8"
    )
    (export / "activities" / "activities.json").write_text(
        json.dumps(list(_ENTRIES)), encoding="utf-8"
    )
    for ref, start in _STARTS.items():
        samples = [
            Sample(t, lat=45.0, lon=6.0 + t / 1e4, heart_rate=100 + t)
            for t in range(0, 60, 10)
        ]
        fit = activity_fit(samples, start=start)
        _archive(export / "activity_fit" / f"{ref}.zip", f"{ref}_ACTIVITY.fit", fit)
    return export
