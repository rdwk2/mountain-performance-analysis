"""Segments de score : régimes, admissibilité, couverture, totaux admis (M4a-2b).

``0010`` D4.2 (bornes effectives), D4.3 (plan du contrôle intérieur), D4.9 et D4.10
(trou, admissibilité), D4.11 (couverture, préfixe comparable), D5.4 (totaux du
support admis, extrêmes de convention) et D6 (régimes).

Chaque seuil est jugé par un **prédicat nommé** de ce module, et seulement par lui ;
le trou, par ``gap_between`` (``backtest/matching.py``). Ce module importe
``matching``, ``geometry``, ``series`` et ``clocks`` ; aucun d'eux ne l'importe.
"""

import math
from bisect import bisect_right
from dataclasses import dataclass

from mountain_perf.schemas import Regime, RegimeClass, RouteProfile

LENGTH_RATIO_BOUNDS = (0.6, 1.6)
"""Bornes incluses du rapport de longueur ``rho`` d'un segment admis (``0010``
D4.10, point 3)."""

H2_SPACING_M = 10.0
"""Pas des points de référence de ``H_2`` : les abscisses ``b_k + 10·n``
intérieures au segment (m, ``0010`` D4.10, point 4)."""

REGIME_GRADE_THRESHOLD = 0.05
"""Pente fine qui sépare les régimes : montée ``g > 0,05``, descente ``g < −0,05``,
plat entre les deux, bornes incluses (``0010`` D6)."""

PURITY_THRESHOLD = 0.80
"""Fraction à partir de laquelle un segment est pur de son régime, seuil inclus
(``0010`` D6)."""


# ---------------------------------------------------------------------------
# Prédicats de seuil (0010 D4.10, D6)
# ---------------------------------------------------------------------------


def grade_regime(grade: float) -> Regime:
    """Régime d'une pente fine (``0010`` D6) : ``ASCENT`` si ``grade > 0,05``,
    ``DESCENT`` si ``grade < −0,05``, ``FLAT`` sinon (bornes incluses dans le plat)."""
    if grade > REGIME_GRADE_THRESHOLD:
        return Regime.ASCENT
    if grade < -REGIME_GRADE_THRESHOLD:
        return Regime.DESCENT
    return Regime.FLAT


def is_pure(fraction: float) -> bool:
    """Fraction qui rend un segment pur : ``fraction >= 0,80`` (``0010`` D6)."""
    return fraction >= PURITY_THRESHOLD


def length_ratio_ok(ratio: float) -> bool:
    """Rapport de longueur admissible : ``0,6 <= rho <= 1,6`` (``0010`` D4.10,
    point 3)."""
    low, high = LENGTH_RATIO_BOUNDS
    return low <= ratio <= high


def interior_ok(deviation_m: float, tolerance_m: float) -> bool:
    """Contrôle intérieur réussi : ``H <= ε`` (``0010`` D4.10, point 4)."""
    return deviation_m <= tolerance_m


# ---------------------------------------------------------------------------
# Régimes et fractions (0010 D6, D4.2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FineOverlap:
    """Part d'un intervalle de la grille fine du profil dans un intervalle
    d'abscisses : ``length_m`` (m) et la pente ``grade`` de l'intervalle fin."""

    length_m: float
    grade: float


def fine_overlaps(
    profile: RouteProfile, start_m: float, end_m: float
) -> tuple[FineOverlap, ...]:
    """Intersections de ``[start_m ; end_m]`` avec les intervalles de la grille fine.

    Pour chaque intervalle fin ``h`` (``[s_h ; s_{h+1}]``, ``profile.distance_m``),
    dans l'ordre de la grille, la longueur ``min(end, s_{h+1}) − max(start, s_h)``
    quand elle est ``> 0``, avec ``profile.grade[h]`` (``0010`` D6). C'est le bloc du
    futur diagnostic « descente roulante / raide » (M4b). Précondition
    ``0 <= start_m < end_m <= L`` : ``ValueError``.
    """
    distance_m = profile.distance_m
    if not 0 <= start_m < end_m <= distance_m[-1]:
        raise ValueError(
            f"fine_overlaps : intervalle [{start_m} ; {end_m}] hors de "
            f"[0 ; {distance_m[-1]}] ou vide."
        )
    grade = profile.grade
    # Les intervalles avant celui qui contient start_m ne recouvrent rien.
    h = bisect_right(distance_m, start_m) - 1
    overlaps: list[FineOverlap] = []
    while h < len(grade) and distance_m[h] < end_m:
        length_m = min(end_m, distance_m[h + 1]) - max(start_m, distance_m[h])
        if length_m > 0:
            overlaps.append(FineOverlap(length_m, grade[h]))
        h += 1
    return tuple(overlaps)


def regime_lengths(
    profile: RouteProfile, start_m: float, end_m: float
) -> tuple[float, float, float]:
    """Longueurs (m) de montée, de plat et de descente de ``[start_m ; end_m]`` :
    sommes (``math.fsum``) des ``fine_overlaps`` selon ``grade_regime`` (``0010``
    D6)."""
    parts: dict[Regime, list[float]] = {regime: [] for regime in Regime}
    for overlap in fine_overlaps(profile, start_m, end_m):
        parts[grade_regime(overlap.grade)].append(overlap.length_m)
    return (
        math.fsum(parts[Regime.ASCENT]),
        math.fsum(parts[Regime.FLAT]),
        math.fsum(parts[Regime.DESCENT]),
    )


def regime_class(
    ascent_fraction: float, flat_fraction: float, descent_fraction: float
) -> RegimeClass:
    """Classe d'un segment (``0010`` D6) : le régime de la plus grande fraction si
    ``is_pure`` la retient, ``MIXED`` sinon. Arguments : des fractions, jamais les
    longueurs de ``regime_lengths``."""
    regime, largest = max(
        (
            (Regime.ASCENT, ascent_fraction),
            (Regime.FLAT, flat_fraction),
            (Regime.DESCENT, descent_fraction),
        ),
        key=lambda item: item[1],
    )
    return RegimeClass(regime.value) if is_pure(largest) else RegimeClass.MIXED
