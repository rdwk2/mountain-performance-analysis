"""La sélection des montées du modèle de la montée (AN4-2a, ``docs/decisions/0024``).

Les motifs se jouent dans l'ordre de :class:`AscentMotif` ; une montée n'est comptée
qu'au premier qui l'écarte. L'appareil et le journal sont **marqués**
(``AscentClimb.device``, ``AscentClimb.journal``), jamais filtrés. Une sortie est une
activité : deux activités le même jour sont deux sorties.

Python pur : bibliothèque standard et contrats.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from types import MappingProxyType

from mountain_perf.analyse.ascent.parameters import (
    ASCENT_REGIMES,
    EXCLUDED_FLAGS,
    MIN_HEART_RATE_COVERAGE,
)
from mountain_perf.analyse.ascent.states import AscentError
from mountain_perf.analyse.tables import Tables
from mountain_perf.schemas.processed import (
    ActivityRow,
    ClimbRegime,
    ClimbRow,
    JournalEventType,
)


class AscentMotif(StrEnum):
    """Les motifs qui écartent une montée, dans leur ordre."""

    SESSIONS = "plusieurs_sessions"
    REGIME = "regime_non_retenu"
    FLAG = "drapeau_exclu"
    NO_SPEED = "vitesse_absente"
    NO_ALTITUDE = "altitude_absente"
    NO_HEART_RATE = "fc_indefinie"


@dataclass(frozen=True)
class AscentClimb:
    """Une montée gardée et ses grandeurs (VAM en log de m/s, D+ et altitude en km)."""

    activity_ref: str
    day: date
    """Le jour de la sortie : ``activity.start_time.date()``."""
    start: datetime
    """``climb.local_start_time``."""
    regime: ClimbRegime
    log_speed: float
    """``ln(vertical_speed_ms)``."""
    hr_bpm: float
    """``lagged_moving_heart_rate_bpm``."""
    d_plus_km: float
    """``(preceding_ascent_m + profile_ascent_m / 2) / 1000`` : le D+ au milieu."""
    altitude_km: float
    """``moving_mean_elevation_m / 1000``."""
    intermediate: bool
    """``regime is ClimbRegime.INTERMEDIATE``."""
    device: tuple[str, int] | None
    """``(device_manufacturer, device_product)`` de la montée ; ``None`` sans l'un."""
    journal: tuple[JournalEventType, ...]
    """``DayRow.journal_types`` du jour, ``()`` sans ligne."""
    temperature_c: float | None
    """``moving_mean_temperature_c``."""


@dataclass(frozen=True)
class AscentSelection:
    """Les montées gardées, triées par ``(day, start, activity_ref)`` ; ``excluded``,
    le compte des montées écartées par motif (tous les motifs, dans leur ordre, zéros
    compris)."""

    climbs: tuple[AscentClimb, ...]
    excluded: Mapping[AscentMotif, int]


def _motif(
    climb: ClimbRow, activity: ActivityRow, regimes: Sequence[ClimbRegime]
) -> AscentMotif | None:
    if (activity.session_count or 1) > 1:
        return AscentMotif.SESSIONS
    if climb.regime not in regimes:
        return AscentMotif.REGIME
    if any(flag in EXCLUDED_FLAGS for flag in climb.flags):
        return AscentMotif.FLAG
    if climb.vertical_speed_ms is None or climb.vertical_speed_ms <= 0:
        return AscentMotif.NO_SPEED
    if climb.moving_mean_elevation_m is None:
        return AscentMotif.NO_ALTITUDE
    if (
        climb.lagged_moving_heart_rate_bpm is None
        or climb.lagged_moving_heart_rate_coverage < MIN_HEART_RATE_COVERAGE
    ):
        return AscentMotif.NO_HEART_RATE
    return None


def _device(climb: ClimbRow) -> tuple[str, int] | None:
    if climb.device_manufacturer is None or climb.device_product is None:
        return None
    return (climb.device_manufacturer, climb.device_product)


def select_climbs(
    tables: Tables, regimes: Sequence[ClimbRegime] = ASCENT_REGIMES
) -> AscentSelection:
    """Les montées gardées de ``tables`` et le compte des écartées par motif ;
    :class:`AscentError` pour une montée dont l'activité manque."""
    activities = {a.activity_ref: a for a in tables.activities}
    journal = {row.day: row.journal_types for row in tables.days}
    counts = dict.fromkeys(AscentMotif, 0)
    kept: list[AscentClimb] = []
    for climb in tables.climbs:
        activity = activities.get(climb.activity_ref)
        if activity is None:
            raise AscentError(f"Une montée sans activité : {climb.activity_ref}.")
        motif = _motif(climb, activity, regimes)
        if motif is not None:
            counts[motif] += 1
            continue
        speed = climb.vertical_speed_ms
        elevation = climb.moving_mean_elevation_m
        heart_rate = climb.lagged_moving_heart_rate_bpm
        assert speed is not None
        assert elevation is not None
        assert heart_rate is not None
        day = activity.start_time.date()
        kept.append(
            AscentClimb(
                activity_ref=climb.activity_ref,
                day=day,
                start=climb.local_start_time,
                regime=climb.regime,
                log_speed=math.log(speed),
                hr_bpm=heart_rate,
                d_plus_km=(climb.preceding_ascent_m + climb.profile_ascent_m / 2)
                / 1000,
                altitude_km=elevation / 1000,
                intermediate=climb.regime is ClimbRegime.INTERMEDIATE,
                device=_device(climb),
                journal=tuple(journal.get(day, ())),
                temperature_c=climb.moving_mean_temperature_c,
            )
        )
    kept.sort(key=lambda c: (c.day, c.start, c.activity_ref))
    return AscentSelection(climbs=tuple(kept), excluded=MappingProxyType(counts))
