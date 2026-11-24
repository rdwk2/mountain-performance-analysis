"""Des tables inventées pour le modèle de la montée (AN4-2a) : le monde E du brief
(``ascent_world.csv``, 16 sorties, 32 montées) et des mondes exacts pour les
propriétés, dont les montées suivent ``y = s_j + β·x + g·D + λ·A + rho·I`` (plus un
bruit, d'une graine fixe, quand on le demande). Aucune donnée réelle (règle 1)."""

from __future__ import annotations

import csv
import math
import random
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from pathlib import Path

from fixtures.q2_world import at, q2_activity, q2_climb, q2_tables
from mountain_perf.analyse.tables import Tables
from mountain_perf.schemas.processed import ActivityRow, ClimbRegime, ClimbRow

WORLD_E = Path(__file__).with_name("ascent_world.csv")
"""L'annexe E du brief, copiée telle quelle."""

WORLD_E_LAST_DAY = date(2001, 5, 6)
"""Le dernier jour des données du monde E (aucune ligne de ``jours``)."""


def ascent_climb(
    ref: str,
    day: date,
    rank: int,
    *,
    regime: ClimbRegime = ClimbRegime.LONG_CLIMB,
    vertical_speed_ms: float = 0.17,
    hr_bpm: float = 145.0,
    preceding_ascent_m: float = 300.0,
    profile_ascent_m: float = 400.0,
    altitude_m: float = 1500.0,
    product: int | None = 1,
    hour: int = 9,
) -> ClimbRow:
    """Une montée de rang ``rank`` (0, 1, …) de la sortie ``ref`` du jour ``day``,
    partie ``3600·rank`` secondes après le départ de la sortie (à ``hour`` heures)."""
    return q2_climb(
        ref,
        at(day, hour),
        offset_s=3600.0 * rank,
        regime=regime,
        h=hr_bpm,
        coverage=1.0,
        vertical_speed_ms=vertical_speed_ms,
        preceding_ascent_m=preceding_ascent_m,
        profile_ascent_m=profile_ascent_m,
        moving_mean_elevation_m=altitude_m,
        device_product=product,
    )


def world_e_tables() -> Tables:
    """Les tables du monde E : une activité par sortie, une montée par ligne, sans
    ligne de ``jours``."""
    activities: dict[str, ActivityRow] = {}
    climbs: list[ClimbRow] = []
    with WORLD_E.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            ref = row["activity_ref"]
            day = date.fromisoformat(row["day"])
            product = int(row["device_product"])
            if ref not in activities:
                activities[ref] = q2_activity(ref, at(day, 9), product=product)
            climbs.append(
                ascent_climb(
                    ref,
                    day,
                    int(row["rank"]),
                    regime=ClimbRegime(row["regime"]),
                    vertical_speed_ms=float(row["vam_m_h"]) / 3600,
                    hr_bpm=float(row["hr_bpm"]),
                    preceding_ascent_m=float(row["preceding_ascent_m"]),
                    profile_ascent_m=float(row["profile_ascent_m"]),
                    altitude_m=float(row["altitude_m"]),
                    product=product,
                )
            )
    return q2_tables(list(activities.values()), climbs)


EXACT_FIRST = date(2001, 1, 5)
"""Le jour de la première sortie d'un monde exact."""
EXACT_REF_HR = 145.0
"""La FC autour de laquelle les FC d'un monde exact sont tirées."""
EXACT_COEF = (1.5, -0.05, -0.03, -0.1)
"""β, ``g``, λ, ``rho`` d'un monde exact, par défaut."""


def exact_world(
    offsets: Sequence[float],
    *,
    coef: tuple[float, float, float, float] = EXACT_COEF,
    noise: float = 0.0,
    seed: int = 20011,
    sizes: Callable[[int], int] | None = None,
    intermediate: Callable[[int, int], bool] | None = None,
    heart: Callable[[int, int, float], float] | None = None,
    days: Sequence[date] | None = None,
    refs: Sequence[str] | None = None,
    hours: Sequence[int] | None = None,
    spacing_days: int = 7,
) -> Tables:
    """Un monde de ``len(offsets)`` sorties dont les montées suivent exactement
    ``y = s_j + β·ln(h / 145) + g·D + λ·A + rho·I`` (D et A en km), ``s_j =
    offsets[j]``, plus ``noise`` fois un bruit gaussien d'une graine fixe.

    Les FC, D+, altitudes sont tirés de ``random.Random(seed)``, dans un ordre qui ne
    dépend ni de ``offsets`` ni de ``noise`` : deux jeux de décalages donnent les mêmes
    montées. ``sizes(j)`` : le nombre de montées de la sortie ``j`` (par défaut 2 ou 3
    en alternance) ; ``intermediate(j, i)`` : la montée ``i`` est intermédiaire (par
    défaut, une sur trois, mêlée dans chaque sortie) ; ``heart(j, i, D)`` : la FC, à la
    place du tirage ; ``days``, ``refs``, ``hours`` : le jour, la référence et l'heure
    de départ de chaque sortie (par défaut, tous les ``spacing_days`` jours depuis
    ``EXACT_FIRST``, ``x00``, ``x01``…, 9 h)."""
    beta, g, lam, rho = coef
    draw = random.Random(seed)
    activities: list[ActivityRow] = []
    climbs: list[ClimbRow] = []
    for j, offset in enumerate(offsets):
        day = (
            days[j]
            if days is not None
            else EXACT_FIRST + timedelta(days=spacing_days * j)
        )
        ref = refs[j] if refs is not None else f"x{j:02d}"
        hour = hours[j] if hours is not None else 9
        activities.append(q2_activity(ref, at(day, hour)))
        count = sizes(j) if sizes is not None else 2 + j % 2
        for i in range(count):
            drawn_hr = draw.uniform(130.0, 160.0)
            preceding = draw.uniform(0.0, 1500.0)
            profile = draw.uniform(150.0, 700.0)
            altitude = draw.uniform(1000.0, 2500.0)
            error = draw.gauss(0.0, 1.0)
            d_km = (preceding + profile / 2) / 1000
            hr = heart(j, i, d_km) if heart is not None else drawn_hr
            is_intermediate = (
                intermediate(j, i) if intermediate is not None else (i + j) % 3 == 0
            )
            y = (
                offset
                + beta * math.log(hr / EXACT_REF_HR)
                + g * d_km
                + lam * altitude / 1000
                + rho * (1.0 if is_intermediate else 0.0)
                + noise * error
            )
            climbs.append(
                ascent_climb(
                    ref,
                    day,
                    i,
                    regime=ClimbRegime.INTERMEDIATE
                    if is_intermediate
                    else ClimbRegime.LONG_CLIMB,
                    vertical_speed_ms=math.exp(y),
                    hr_bpm=hr,
                    preceding_ascent_m=preceding,
                    profile_ascent_m=profile,
                    altitude_m=altitude,
                    hour=hour,
                )
            )
    return q2_tables(activities, climbs)


def spread_offsets(count: int, seed: int = 7) -> list[float]:
    """``count`` décalages de sortie dispersés autour de ``ln(0,17)``, hors de tout
    plan simple (tirés d'une graine fixe)."""
    draw = random.Random(seed)
    return [math.log(0.17) + draw.gauss(0.0, 0.08) for _ in range(count)]
