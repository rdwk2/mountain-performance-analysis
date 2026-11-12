"""La FC d'une montée (AN3-1a, ``docs/decisions/0014``, précisions d'AN3-1a).

La moyenne de la FC sur un **support** : des morceaux de temps de la trace, chacun
décalé de ``lag_s`` ; sur chaque morceau décalé, l'intégrale exacte de la FC
interpolée et la durée couverte viennent de l'outil du moteur
(:meth:`~mountain_perf.estimation.intervals.HeartRateSeries.integral`, ``0017``,
P5.1), la fenêtre rognée à la série. La moyenne est l'intégrale sommée divisée par la
durée couverte sommée ; la couverture, la durée couverte sommée divisée par la durée
du support, bornée à 1. Aucun seuil de couverture : la question qui lit ces valeurs
déclare le sien.

Les supports d'une montée : ses intervalles en mouvement (:func:`moving_pieces`, le
temps M sous θc, celui de sa VAM), leur seconde moitié coupée exactement
(:func:`second_half`), et sa fenêtre écoulée.

Python pur : ni extra, ni ``backtest/``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from mountain_perf.analyse.climbs import MotionTrack
from mountain_perf.estimation.intervals import HeartRateSeries
from mountain_perf.schemas import CENTRAL_CONVENTION_INDEX, IntervalState

HR_LAG_S = 60.0
"""Le décalage de la FC, en secondes : la FC répond à l'effort avec un retard
(``0017``, P5.1)."""


@dataclass(frozen=True)
class ClimbHeartRate:
    """La FC d'un support.

    - ``bpm`` — battements par minute — la moyenne, ``None`` sans durée couverte ;
    - ``coverage`` — fraction — la part du support que la FC couvre, dans ``[0 ; 1]``.

    ``bpm`` est ``None`` si et seulement si ``coverage`` vaut ``0.0``.
    """

    bpm: float | None
    coverage: float


def moving_pieces(
    track: MotionTrack, start_s: float, end_s: float
) -> tuple[tuple[float, float], ...]:
    """Les morceaux du temps M (θc) de ``[start_s ; end_s]`` (temps de la trace) : pour
    chaque pas M de la vue, sa partie dans la fenêtre, si elle a une longueur ; dans
    l'ordre des pas, sans fusionner les pas voisins."""
    t = track.time_s
    marks = track.states[CENTRAL_CONVENTION_INDEX]
    pieces = []
    for i, mark in enumerate(marks):
        if mark is IntervalState.MOVING:
            a, b = max(t[i], start_s), min(t[i + 1], end_s)
            if b - a > 0:
                pieces.append((a, b))
    return tuple(pieces)


def second_half(
    pieces: Sequence[tuple[float, float]],
) -> tuple[tuple[float, float], ...]:
    """La seconde moitié de la durée de ``pieces``, coupée exactement : le morceau qui
    contient le milieu est coupé à cet instant, les suivants gardés entiers. Un milieu
    sur la fin d'un morceau écarte ce morceau ; aucun morceau de longueur nulle."""
    half = math.fsum(b - a for a, b in pieces) / 2
    run = 0.0
    for k, (a, b) in enumerate(pieces):
        if run + (b - a) > half:
            kept = ((a + (half - run), b), *pieces[k + 1 :])
            return tuple((u, v) for u, v in kept if v - u > 0)
        run += b - a
    return ()


def support_heart_rate(
    series: HeartRateSeries | None,
    pieces: Sequence[tuple[float, float]],
    lag_s: float,
) -> ClimbHeartRate:
    """La FC moyenne de ``pieces`` (temps de la trace), chaque morceau décalé de
    ``lag_s`` secondes, et sa couverture ; ``ClimbHeartRate(None, 0.0)`` sans série,
    sans support, ou sans durée couverte qui s'écrive en fraction du support."""
    total = math.fsum(b - a for a, b in pieces)
    if series is None or total <= 0:
        return ClimbHeartRate(None, 0.0)
    parts = [series.integral(a + lag_s, b + lag_s) for a, b in pieces]
    integral = math.fsum(i for i, _ in parts)
    covered = math.fsum(c for _, c in parts)
    if covered <= 0:
        return ClimbHeartRate(None, 0.0)
    coverage = min(1.0, covered / total)
    if coverage == 0.0:
        return ClimbHeartRate(None, 0.0)
    return ClimbHeartRate(integral / covered, coverage)
