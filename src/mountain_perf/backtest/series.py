"""Séries dérivées d'une trace réalisée : trous, blocs, lissage par bloc, ``d_r``.

``0010`` D4.4 : un **bloc** est une suite d'enregistrements sans trou ; positions et
altitudes lissées par une moyenne centrée sur 5 enregistrements, **tronquée aux bords
de bloc**, jamais complétée par zéro ni prolongée à travers un trou ; les séries
brutes restent dans la ``RecordedTrace``, sous leurs propres noms. Lisser latitude et
longitude en degrés revient à lisser dans le plan local, affine en degrés (même
limite que ``0008`` : pas d'antiméridien).
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import accumulate, pairwise

from mountain_perf.gpx.geo import haversine_m
from mountain_perf.schemas import RecordedTrace

MAX_STEP_S = 10.0
"""Plus grand écart entre deux enregistrements consécutifs qui n'est pas un trou (s).

``0010`` D4.4 et D4.9 : 10 s n'est pas un trou, 10,001 s en est un. Aucun
franchissement ni aucune fenêtre d'horloge ne traverse un trou.
"""

SMOOTHING_HALF_WIDTH = 2
"""Demi-largeur de la moyenne centrée, en enregistrements (``0010`` D4.4) : la
fenêtre complète compte ``2 × 2 + 1 = 5`` enregistrements."""


@dataclass(frozen=True)
class TraceSeries:
    """Séries dérivées d'une ``RecordedTrace`` — interne au paquet ``backtest``.

    - ``gap_after[i]`` : l'intervalle ``i``, entre les enregistrements ``i`` et
      ``i + 1``, est un trou (écart ``> MAX_STEP_S``) ;
    - ``block_of[i]`` : indice du bloc de l'enregistrement ``i`` ;
    - ``blocks[b]`` : premier et dernier enregistrement du bloc ``b`` ;
    - ``smoothed_*`` : moyennes centrées, tronquées aux bords de bloc ;
    - ``smoothing_complete[i]`` : la fenêtre de ``i`` n'est pas tronquée ;
    - ``realized_distance_m`` : ``d_r``, haversine cumulée des positions **brutes**,
      ``0`` au premier enregistrement, trous compris.
    """

    gap_after: tuple[bool, ...]
    block_of: tuple[int, ...]
    blocks: tuple[tuple[int, int], ...]
    smoothed_latitude_deg: tuple[float, ...]
    smoothed_longitude_deg: tuple[float, ...]
    smoothed_elevation_m: tuple[float, ...]
    smoothing_complete: tuple[bool, ...]
    realized_distance_m: tuple[float, ...]


def _smooth(
    values: Sequence[float], blocks: Sequence[tuple[int, int]]
) -> tuple[float, ...]:
    smoothed: list[float] = []
    for first, last in blocks:
        for i in range(first, last + 1):
            lo = max(first, i - SMOOTHING_HALF_WIDTH)
            hi = min(last, i + SMOOTHING_HALF_WIDTH)
            smoothed.append(math.fsum(values[lo : hi + 1]) / (hi - lo + 1))
    return tuple(smoothed)


def build_series(trace: RecordedTrace) -> TraceSeries:
    """Trous, blocs, lissage par bloc et abscisse réalisée ``d_r`` d'une trace."""
    gap_after = tuple(b - a > MAX_STEP_S for a, b in pairwise(trace.time_s))
    blocks: list[tuple[int, int]] = []
    first = 0
    for i, gap in enumerate(gap_after):
        if gap:
            blocks.append((first, i))
            first = i + 1
    blocks.append((first, len(trace.time_s) - 1))
    block_of = tuple(b for b, (lo, hi) in enumerate(blocks) for _ in range(lo, hi + 1))
    complete = tuple(
        i - SMOOTHING_HALF_WIDTH >= lo and i + SMOOTHING_HALF_WIDTH <= hi
        for lo, hi in blocks
        for i in range(lo, hi + 1)
    )
    lat, lon = trace.latitude_deg, trace.longitude_deg
    steps_m = (
        haversine_m(lat[i], lon[i], lat[i + 1], lon[i + 1]) for i in range(len(lat) - 1)
    )
    return TraceSeries(
        gap_after=gap_after,
        block_of=block_of,
        blocks=tuple(blocks),
        smoothed_latitude_deg=_smooth(lat, blocks),
        smoothed_longitude_deg=_smooth(lon, blocks),
        smoothed_elevation_m=_smooth(trace.elevation_m, blocks),
        smoothing_complete=complete,
        realized_distance_m=tuple(accumulate(steps_m, initial=0.0)),
    )
