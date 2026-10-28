"""Un ``interim/`` synthétique pour les tables de ``processed/`` (AN1-2b) : quatre
activités écrites par l'écrivain d'``interim/`` de l'ingestion. Aucune donnée réelle
(règle 1)."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fixtures.montees import FLAT, climb_at, recording
from mountain_perf.ingest.interim import write_activities
from mountain_perf.schemas import (
    ActivityIndex,
    ActivityRecording,
    HeartRateChannel,
    PositionChannel,
    TemperatureChannel,
    TimerEvent,
    TimerEventType,
    TimerTrigger,
)
from test_ingest_interim import INDEX_SOURCE, REPORT
from test_schemas_interim import entry

PLUS2 = timezone(timedelta(hours=2))
COMMIT = "c0ffee" * 6 + "c0ff"
"""Le commit inventé des tables synthétiques (40 chiffres hexadécimaux)."""


def _with_heart_rate(rec: ActivityRecording, bpm: float) -> ActivityRecording:
    times = rec.position.time_s if rec.position is not None else ()
    return dataclasses.replace(
        rec,
        heart_rate=HeartRateChannel(times, tuple(bpm for _ in times)),
        temperature=TemperatureChannel(times[::10], tuple(12.0 for _ in times[::10])),
    )


def write_interim(data_dir: Path) -> ActivityIndex:
    """Écrit sous ``data_dir`` : ``a1`` à pied, une côte (60 m) puis une montée
    longue (300 m), FC 140, une pause automatique dans la montée longue ; ``a2`` ski
    de randonnée sans baromètre décrit ; ``a3`` sans altitude ; ``a4`` un type sans
    famille, sans enregistrement."""
    long_start = 500.0 + 60 / 0.15 / (600 / 3600 / 0.15) + 60 / 0.15 / 1.5 + 500.0
    a1 = _with_heart_rate(
        recording(
            [
                FLAT,
                climb_at(600, 0.15, 60),
                (60 / 0.15, -0.15, 1.5),
                FLAT,
                climb_at(600, 0.15, 300),
                FLAT,
            ],
            activity_ref="a1",
        ),
        140.0,
    )
    a1 = dataclasses.replace(
        a1,
        timer_events=(
            TimerEvent(0.0, TimerEventType.START, TimerTrigger.MANUAL),
            TimerEvent(long_start + 300.0, TimerEventType.STOP, TimerTrigger.AUTO),
            TimerEvent(long_start + 302.0, TimerEventType.START, TimerTrigger.AUTO),
        ),
    )
    a2 = recording(
        [FLAT, climb_at(500, 0.25, 400), FLAT], activity_ref="a2", barometer=None
    )
    a3 = dataclasses.replace(recording([FLAT], activity_ref="a3"), elevation=None)
    index = ActivityIndex(
        (
            entry(
                source=INDEX_SOURCE,
                activity_ref="a1",
                start_time=datetime(2024, 3, 9, 9, tzinfo=PLUS2),
            ),
            entry(
                source=INDEX_SOURCE,
                activity_ref="a2",
                source_activity_type="backcountry_skiing",
                start_time=datetime(2024, 3, 10, 9, tzinfo=PLUS2),
            ),
            entry(
                source=INDEX_SOURCE,
                activity_ref="a3",
                start_time=datetime(2024, 3, 11, 9, tzinfo=PLUS2),
            ),
            entry(
                source=INDEX_SOURCE,
                activity_ref="a4",
                source_activity_type="golf",
                has_recording=False,
                start_time=datetime(2024, 3, 12, 9, tzinfo=PLUS2),
            ),
        ),
        (INDEX_SOURCE,),
    )
    write_activities(data_dir, index, [a1, a2, a3], REPORT)
    return index


GAP = (1000.0, 1060.0)
"""Le trou de positions de ``g1`` : ]1 000 ; 1 060[ s, l'altitude continue."""

HEART_RATE_FROM_S = 1400.0
HEART_RATE_STEP_S = 1600.0
"""La FC de ``g1`` n'existe qu'à partir de 1 400 s : 100 avant 1 600 s, 180 ensuite."""


def gap_recording() -> ActivityRecording:
    """``g1``, sans bruit : un replat, une montée de 300 m à 15 % et 600 m/h (de 500 à
    2 300 s), un replat. Les positions manquent sur :data:`GAP`, pas l'altitude : la vue
    a un trou de 60 s, pendant lequel le canal d'altitude monte de 10 m. La FC suit
    :data:`HEART_RATE_FROM_S` et :data:`HEART_RATE_STEP_S` ; la température vaut
    10 °C."""
    rec = recording(
        [FLAT, climb_at(600, 0.15, 300), FLAT], noise=False, activity_ref="g1"
    )
    assert rec.position is not None
    assert rec.elevation is not None
    pos = rec.position
    keep = [i for i, t in enumerate(pos.time_s) if not GAP[0] < t < GAP[1]]
    times = rec.elevation.time_s
    hr_times = tuple(t for t in times if t >= HEART_RATE_FROM_S)
    return dataclasses.replace(
        rec,
        position=PositionChannel(
            tuple(pos.time_s[i] for i in keep),
            tuple(pos.latitude_deg[i] for i in keep),
            tuple(pos.longitude_deg[i] for i in keep),
        ),
        heart_rate=HeartRateChannel(
            hr_times,
            tuple(100.0 if t < HEART_RATE_STEP_S else 180.0 for t in hr_times),
        ),
        temperature=TemperatureChannel(times, tuple(10.0 for _ in times)),
    )


def write_one(
    data_dir: Path,
    rec: ActivityRecording,
    source_activity_type: str = "trail_running",
) -> ActivityIndex:
    """Écrit sous ``data_dir`` un ``interim/`` d'une seule activité, ``rec``."""
    index = ActivityIndex(
        (
            entry(
                source=INDEX_SOURCE,
                activity_ref=rec.activity_ref,
                source_activity_type=source_activity_type,
                start_time=datetime(2024, 3, 9, 9, tzinfo=PLUS2),
            ),
        ),
        (INDEX_SOURCE,),
    )
    write_activities(data_dir, index, [rec], REPORT)
    return index


def write_gap_interim(data_dir: Path) -> ActivityIndex:
    """Écrit sous ``data_dir`` un ``interim/`` d'une seule activité, ``g1``
    (:func:`gap_recording`), à pied."""
    return write_one(data_dir, gap_recording())
