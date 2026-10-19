"""Enregistrements synthétiques pour les montées (AN1-2b) : un profil en tronçons,
parcouru en ligne droite vers l'est, avec un bruit d'altitude reproductible. Aucune
donnée réelle (règle 1).

Un tronçon est ``(longueur horizontale en m, pente, vitesse horizontale en m/s)`` ; la
VAM vraie d'un tronçon montant est ``pente × vitesse``. ``stops`` immobilise l'athlète
sur des intervalles ``[début ; fin[`` (secondes), ``gaps`` retire les instants de
``]début ; fin[`` de l'enregistrement. L'altitude part de 1 000 m ; son bruit est un
AR(1) de constante de temps 100 s et d'écart type 0,15 m, plus un bruit blanc de
0,05 m, arrondi à 0,2 m (la résolution d'un baromètre).
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from datetime import UTC, datetime

from mountain_perf.schemas import (
    ActivityRecording,
    DeviceProvenance,
    ElevationChannel,
    ElevationField,
    PositionChannel,
    RecordingSession,
    SourceRef,
    TimerEvent,
    TimerEventType,
    TimerTrigger,
)

SOURCE = SourceRef("garmin_fit", "x.zip", "0" * 64, datetime(2026, 1, 1, tzinfo=UTC))
START = datetime(2026, 1, 1, 8, tzinfo=UTC)
_M_PER_DEG_LAT = 111_320.0

Segment = tuple[float, float, float]


def recording(
    segments: Sequence[Segment],
    *,
    seed: int = 0,
    step_s: float = 1.0,
    noise: bool = True,
    stops: Sequence[tuple[float, float]] = (),
    gaps: Sequence[tuple[float, float]] = (),
    activity_ref: str = "a1",
    elevation_offset_m: float = 0.0,
    barometer: bool | None = True,
) -> ActivityRecording:
    """Un ``ActivityRecording`` qui parcourt ``segments``, un instant par ``step_s``."""
    rnd = random.Random(seed)
    t_list: list[float] = []
    lat: list[float] = []
    lon: list[float] = []
    z: list[float] = []
    x = h = t = ar = 0.0
    rho = math.exp(-step_s / 100.0)
    for length_m, grade, speed_ms in segments:
        count = max(1, round(length_m / speed_ms / step_s))
        for _ in range(count):
            t += step_s
            if not any(a <= t < b for a, b in stops):
                x += speed_ms * step_s
                h += grade * speed_ms * step_s
            if noise:
                ar = rho * ar + rnd.gauss(0.0, 0.15 * math.sqrt(1 - rho * rho))
            if any(a < t < b for a, b in gaps):
                continue
            white = rnd.gauss(0.0, 0.05) if noise else 0.0
            t_list.append(t)
            lat.append(45.0)
            lon.append(6.0 + x / (_M_PER_DEG_LAT * math.cos(math.radians(45.0))))
            value = 1000.0 + elevation_offset_m + h + ar + white
            z.append(round(value / 0.2) * 0.2 if noise else value)
    times = tuple(t_list)
    return ActivityRecording(
        activity_ref,
        START,
        (RecordingSession("running", None, 0.0, None, None, None),),
        (TimerEvent(0.0, TimerEventType.START, TimerTrigger.MANUAL),),
        PositionChannel(times, tuple(lat), tuple(lon)),
        ElevationChannel(times, tuple(z), ElevationField.ENHANCED_ALTITUDE),
        None,
        None,
        None,
        None,
        DeviceProvenance("activity", "garmin", 1, None, 1.0, barometer, False),
        (),
        SOURCE,
    )


def climb_at(vam_m_per_h: float, grade: float, gain_m: float) -> Segment:
    """Le tronçon qui monte ``gain_m`` à la pente ``grade`` et à la VAM vraie
    ``vam_m_per_h``."""
    speed_ms = vam_m_per_h / 3600.0 / grade
    return (gain_m / grade, grade, speed_ms)


FLAT: Segment = (500.0, 0.0, 1.0)
"""Un replat de 500 m à 1 m/s."""
