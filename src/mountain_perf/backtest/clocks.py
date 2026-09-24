"""Horloges d'une trace : mesures de fenêtre, qualification, confirmation des arrêts,
partition M/S/U, horloges cumulées, totaux et épisodes (``0010`` D5).

Chaque intervalle élémentaire ``[t_i ; t_{i+1})`` est jugé sur la **fenêtre exacte**
de 30 s centrée sur son milieu, lue sur la série **lissée** (``series.py``) :
valeurs aux bornes interpolées en temps entre les enregistrements qui les encadrent,
positions dans le plan local de ``0008`` ancré à la borne basse. Une fenêtre qui
sort de son bloc ou touche un lissage tronqué est invalide ; un intervalle de trou
n'a pas de fenêtre. L'état ``STOPPED`` n'est pas un arrêt physique prouvé : le
détecteur n'est pas validé (``0010``, Conséquences).
"""

import math
from bisect import bisect_left, bisect_right
from collections.abc import Sequence, Set
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise

from mountain_perf.backtest.series import TraceSeries
from mountain_perf.gpx.geo import EARTH_RADIUS_M
from mountain_perf.schemas import (
    CLOCK_CONVENTIONS,
    Clock,
    ClockConvention,
    ClockKind,
    ClockPartition,
    ClockTotals,
    IntervalState,
    RecordedTrace,
    StopEpisode,
)

CLOCK_HALF_WINDOW_S = 15.0
"""Demi-largeur de la fenêtre exacte ``W_i = [m_i − 15 ; m_i + 15]`` (``0010``
D5.2) ; ses 30 s divisent les déplacements en vitesses et multiplient ``h`` et ``z``
en seuils de diamètre."""

_WINDOW_S = 2 * CLOCK_HALF_WINDOW_S
_MAX_HORIZONTAL_SPEED_MS = max(c.max_horizontal_speed_ms for c in CLOCK_CONVENTIONS)
_MAX_VERTICAL_SPEED_MS = max(c.max_vertical_speed_ms for c in CLOCK_CONVENTIONS)
_MOVING = frozenset({IntervalState.MOVING})
_MOVING_OR_UNDETERMINED = frozenset({IntervalState.MOVING, IntervalState.UNDETERMINED})


class Qualification(StrEnum):
    """Jugement d'une fenêtre sous une convention, avant confirmation (D5.2)."""

    MOBILE = "mobile"
    IMMOBILE = "immobile"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True)
class WindowMeasures:
    """Mesures d'une fenêtre valide — interne au paquet ``backtest``.

    ``v_h`` et ``v_z`` en m/s (``v_z`` en valeur absolue) ; ``d_h`` (diamètre
    horizontal) et ``d_z`` (étendue des altitudes) en mètres, ``None`` quand
    l'économie de :func:`clock_partition` les omet.
    """

    v_h: float
    v_z: float
    d_h: float | None
    d_z: float | None


def _smoothed_at(
    trace: RecordedTrace, series: TraceSeries, at_s: float
) -> tuple[float, float, float]:
    """Latitude, longitude et altitude lissées à l'instant ``at_s`` : valeur de
    l'enregistrement s'il y en a un, sinon interpolation linéaire en temps entre
    ``j⁻ = max{j : t_j <= at_s}`` et ``j⁺ = min{j : t_j >= at_s}``."""
    t = trace.time_s
    below, above = bisect_right(t, at_s) - 1, bisect_left(t, at_s)
    columns = (
        series.smoothed_latitude_deg,
        series.smoothed_longitude_deg,
        series.smoothed_elevation_m,
    )
    if below == above:
        return columns[0][below], columns[1][below], columns[2][below]
    f = (at_s - t[below]) / (t[above] - t[below])
    lat, lon, z = (c[below] + f * (c[above] - c[below]) for c in columns)
    return lat, lon, z


def _diameter_m(points: Sequence[tuple[float, float]]) -> float:
    """Plus grande distance entre deux points du plan."""
    largest_m2 = 0.0
    for k, (ax, ay) in enumerate(points):
        for bx, by in points[k + 1 :]:
            largest_m2 = max(largest_m2, (ax - bx) ** 2 + (ay - by) ** 2)
    return math.sqrt(largest_m2)


def window_measures(
    trace: RecordedTrace, series: TraceSeries, i: int, *, complete: bool = False
) -> WindowMeasures | None:
    """Mesures de la fenêtre de l'intervalle ``i`` (``0010`` D5.2).

    ``None`` si l'intervalle est un trou ou si sa fenêtre est invalide : bornes hors
    du bloc de l'intervalle, ou lissage incomplet pour un enregistrement de ``j⁻(lo)``
    à ``j⁺(hi)``. ``D_h`` et ``D_z`` portent sur ``{X̃(lo), enregistrements lissés
    strictement dans ]lo ; hi[, X̃(hi)}``. Sans ``complete``, ils sont omis quand
    ``v_h`` ou ``v_z`` dépasse le seuil le plus haut des cinq conventions — la
    fenêtre est alors mobile sous toutes ; ``complete=True`` (tests) les calcule
    toujours.
    """
    if series.gap_after[i]:
        return None
    t = trace.time_s
    middle_s = (t[i] + t[i + 1]) / 2
    lo, hi = middle_s - CLOCK_HALF_WINDOW_S, middle_s + CLOCK_HALF_WINDOW_S
    first, last = series.blocks[series.block_of[i]]
    if lo < t[first] or hi > t[last]:
        return None
    if not all(
        series.smoothing_complete[j]
        for j in range(bisect_right(t, lo) - 1, bisect_left(t, hi) + 1)
    ):
        return None
    lat_lo, lon_lo, z_lo = _smoothed_at(trace, series, lo)
    lat_hi, lon_hi, z_hi = _smoothed_at(trace, series, hi)
    x_scale_m = EARTH_RADIUS_M * math.cos(math.radians(lat_lo))

    def plane(lat: float, lon: float) -> tuple[float, float]:
        return (
            x_scale_m * math.radians(lon - lon_lo),
            EARTH_RADIUS_M * math.radians(lat - lat_lo),
        )

    end_xy = plane(lat_hi, lon_hi)
    v_h = math.hypot(*end_xy) / _WINDOW_S
    v_z = abs(z_hi - z_lo) / _WINDOW_S
    if not complete and (
        v_h > _MAX_HORIZONTAL_SPEED_MS or v_z > _MAX_VERTICAL_SPEED_MS
    ):
        return WindowMeasures(v_h, v_z, None, None)
    interior = range(bisect_right(t, lo), bisect_left(t, hi))
    points = [
        (0.0, 0.0),
        *(
            plane(series.smoothed_latitude_deg[j], series.smoothed_longitude_deg[j])
            for j in interior
        ),
        end_xy,
    ]
    altitudes = [z_lo, *(series.smoothed_elevation_m[j] for j in interior), z_hi]
    return WindowMeasures(
        v_h, v_z, _diameter_m(points), max(altitudes) - min(altitudes)
    )


def qualify(
    v_h: float,
    v_z: float,
    d_h: float | None,
    d_z: float | None,
    convention: ClockConvention,
) -> Qualification:
    """Mobile si ``v_h > h`` ou ``v_z > z`` ; immobile si ``v_h <= h``, ``v_z <= z``,
    ``D_h <= 30·h`` et ``D_z <= 30·z`` ; indéterminé sinon (``0010`` D5.2).

    Les diamètres ne servent qu'à une fenêtre non mobile ; absents : ``ValueError``.
    """
    h, z = convention.max_horizontal_speed_ms, convention.max_vertical_speed_ms
    if v_h > h or v_z > z:
        return Qualification.MOBILE
    if d_h is None or d_z is None:
        raise ValueError("D_h et D_z sont nécessaires pour une fenêtre non mobile.")
    if d_h <= _WINDOW_S * h and d_z <= _WINDOW_S * z:
        return Qualification.IMMOBILE
    return Qualification.INDETERMINATE


def confirm(
    durations_s: Sequence[float],
    qualifications: Sequence[Qualification],
    min_stop_s: float,
) -> tuple[IntervalState, ...]:
    """États confirmés d'une suite d'intervalles (``0010`` D5.2).

    Une suite **maximale** d'intervalles consécutifs immobiles de durée totale
    ``>= min_stop_s`` devient entièrement ``STOPPED``, plus courte ``UNDETERMINED`` ;
    mobile → ``MOVING`` ; indéterminé → ``UNDETERMINED``. Un trou n'étant jamais
    immobile, une suite ne le traverse jamais.
    """
    if len(durations_s) != len(qualifications):
        raise ValueError(
            f"{len(durations_s)} durées pour {len(qualifications)} qualifications."
        )
    states: list[IntervalState] = []
    i, n = 0, len(qualifications)
    while i < n:
        if qualifications[i] is Qualification.IMMOBILE:
            j = i
            while j < n and qualifications[j] is Qualification.IMMOBILE:
                j += 1
            stopped = math.fsum(durations_s[i:j]) >= min_stop_s
            state = IntervalState.STOPPED if stopped else IntervalState.UNDETERMINED
            states += [state] * (j - i)
            i = j
        else:
            mobile = qualifications[i] is Qualification.MOBILE
            states.append(
                IntervalState.MOVING if mobile else IntervalState.UNDETERMINED
            )
            i += 1
    return tuple(states)


def clock_partition(trace: RecordedTrace, series: TraceSeries) -> ClockPartition:
    """Partition M/S/U de chaque intervalle sous les cinq conventions (``0010`` D5.2).

    Un intervalle de trou ou de fenêtre invalide est indéterminé, donc ``U``. Les
    diamètres ne sont calculés que pour les fenêtres qui ne sont pas mobiles sous
    toutes les conventions : le résultat est identique à la définition complète.
    """
    durations_s = tuple(b - a for a, b in pairwise(trace.time_s))
    qualifications: list[list[Qualification]] = [[] for _ in CLOCK_CONVENTIONS]
    for i in range(len(durations_s)):
        measures = window_measures(trace, series, i)
        for k, convention in enumerate(CLOCK_CONVENTIONS):
            qualifications[k].append(
                Qualification.INDETERMINATE
                if measures is None
                else qualify(
                    measures.v_h, measures.v_z, measures.d_h, measures.d_z, convention
                )
            )
    return ClockPartition(
        time_s=trace.time_s,
        states=tuple(
            confirm(durations_s, qualifications[k], convention.min_stop_s)
            for k, convention in enumerate(CLOCK_CONVENTIONS)
        ),
    )


def _check_instant(partition: ClockPartition, at_s: float) -> None:
    if not 0 <= at_s <= partition.time_s[-1]:
        raise ValueError(
            f"Instant hors de la trace : {at_s} s pour [0 ; {partition.time_s[-1]}]."
        )


def cumulative_s(
    partition: ClockPartition,
    convention_index: int,
    states: Set[IntervalState],
    at_s: float,
) -> float:
    """Temps cumulé dans ``states`` depuis ``t = 0`` jusqu'à ``at_s``, linéaire dans
    chaque intervalle (``0010`` D5.3) ; ``at_s`` hors de ``[0 ; time_s[-1]]`` :
    ``ValueError``."""
    _check_instant(partition, at_s)
    t = partition.time_s
    marks = partition.states[convention_index]
    k = bisect_right(t, at_s) - 1
    parts = [t[j + 1] - t[j] for j in range(min(k, len(marks))) if marks[j] in states]
    if k < len(marks) and marks[k] in states:
        parts.append(at_s - t[k])
    return math.fsum(parts)


def clock_duration_s(
    partition: ClockPartition, clock: Clock, start_s: float, end_s: float
) -> float:
    """Durée de ``[start_s ; end_s]`` sous ``clock`` (``0010`` D5.3) : écoulé
    ``end − start`` ; ``M_θ`` par le cumul de ``{MOVING}`` ; ``M_θ + U_θ`` par celui
    de ``{MOVING, UNDETERMINED}``.

    ``start_s > end_s`` ou borne hors de la trace : ``ValueError`` — jamais de durée
    négative (``0010`` D4.12).
    """
    if start_s > end_s:
        raise ValueError(
            f"start_s ({start_s}) doit précéder end_s ({end_s}) : jamais de durée "
            "négative."
        )
    _check_instant(partition, start_s)
    _check_instant(partition, end_s)
    index = clock.convention_index
    if index is None:  # l'écoulé, seul sans convention (contrat de Clock)
        return end_s - start_s
    states = _MOVING if clock.kind is ClockKind.MOVING else _MOVING_OR_UNDETERMINED
    return cumulative_s(partition, index, states, end_s) - cumulative_s(
        partition, index, states, start_s
    )


def trace_totals(partition: ClockPartition) -> tuple[ClockTotals, ...]:
    """Les cinq totaux de la trace ``(E, M_θ, S_θ, U_θ)``, un par convention
    (``0010`` D5.4)."""
    durations_s = [b - a for a, b in pairwise(partition.time_s)]
    totals: list[ClockTotals] = []
    for marks in partition.states:
        sums = {
            state: math.fsum(
                d for d, mark in zip(durations_s, marks, strict=True) if mark is state
            )
            for state in IntervalState
        }
        totals.append(
            ClockTotals(
                elapsed_s=partition.time_s[-1],
                moving_s=sums[IntervalState.MOVING],
                stopped_s=sums[IntervalState.STOPPED],
                undetermined_s=sums[IntervalState.UNDETERMINED],
            )
        )
    return tuple(totals)


def stop_episodes(
    partition: ClockPartition, convention_index: int
) -> tuple[StopEpisode, ...]:
    """Suites maximales d'intervalles ``STOPPED`` sous une convention : de ``t_i`` à
    ``t_{j+1}``, enregistrements ``i`` à ``j + 1``."""
    t = partition.time_s
    marks = partition.states[convention_index]
    episodes: list[StopEpisode] = []
    i = 0
    while i < len(marks):
        if marks[i] is not IntervalState.STOPPED:
            i += 1
            continue
        j = i
        while j + 1 < len(marks) and marks[j + 1] is IntervalState.STOPPED:
            j += 1
        episodes.append(
            StopEpisode(start_s=t[i], end_s=t[j + 1], first_record=i, last_record=j + 1)
        )
        i = j + 1
    return tuple(episodes)
