"""Passages nommés et événements (M4a-3).

``0010`` D4.12 : chaque occurrence d'un lieu nommé du préparé est rattachée à la
grille de score nominale ; son franchissement est cherché sur le préfixe comparable
seulement, entre les deux points de score qui l'encadrent, ou repris du point de
score dont elle est à moins de 1 m ; les arrêts confirmés sous ``θ_c`` sont associés
aux occurrences ; les événements, la chronologie et le maintien dans le préfixe en
découlent.

Chaque seuil est jugé par un **prédicat nommé** de ce module, et seulement par lui ;
le franchissement, le regroupement et la datation sont ceux de M4a-2a
(``crossing_candidates``, ``group_events``, ``time_at``), jamais réécrits. Ce
module importe ``matching``, ``geometry``, ``series`` et ``clocks`` ; aucun d'eux ne
l'importe.
"""

import math
from bisect import bisect_right
from collections.abc import Sequence
from itertools import pairwise

from mountain_perf.backtest.geometry import LocalFrame
from mountain_perf.backtest.matching import crossing_candidates, group_events
from mountain_perf.backtest.series import TraceSeries
from mountain_perf.schemas import PassageRole, PassageStatus, RecordedTrace

WAYPOINT_SNAP_M = 1.0
"""Distance en deçà de laquelle une occurrence reprend un point de score (m,
``0010`` D4.12) : « un waypoint à moins de 1 m d'un point de score réutilise le
franchissement de ce point ». 1 m exactement : encadrement."""

ATTRIBUTION_TIME_TIE_S = 1.0
"""Égalité des distances temporelles de l'association arrêt → passage (s,
``0010`` D4.12) : « égalité jugée à 1 s près », écart de 1 s exactement compris."""

ATTRIBUTION_DISTANCE_TIE_M = 1.0
"""Égalité des distances à la médiane de l'épisode (m, ``0010`` D4.12) :
« égalité à 1 m près », écart de 1 m exactement compris."""


# ---------------------------------------------------------------------------
# Prédicats de seuil (0010 D4.12)
# ---------------------------------------------------------------------------


def snaps_to_point(distance_m: float) -> bool:
    """L'occurrence reprend le point de score : ``distance < 1 m``, strictement
    (``0010`` D4.12)."""
    return distance_m < WAYPOINT_SNAP_M


def observed_in_prefix(
    distance_m: float, start_m: float, end_m: float, prefix_count: int
) -> bool:
    """Occurrence intermédiaire observée : préfixe non vide (``m >= 1``) et
    ``b_0 <= s_w <= b_m``, bornes incluses — le même intervalle que le dernier
    passage publié (``0010`` D4.11, D4.12)."""
    return prefix_count >= 1 and start_m <= distance_m <= end_m


def near_passage(distance_m: float, tolerance_m: float) -> bool:
    """Occurrence candidate par l'espace : ``Q_w`` à moins de ``ε`` de la médiane de
    l'épisode, strictement (``0010`` D4.12)."""
    return distance_m < tolerance_m


def windows_overlap(
    window_start_s: float, window_end_s: float, start_s: float, end_s: float
) -> bool:
    """La fenêtre d'association chevauche ``[a ; b]`` ; un contact est un
    chevauchement (``0010`` D4.12)."""
    return window_start_s <= end_s and start_s <= window_end_s


def time_distance_s(time_s: float, start_s: float, end_s: float) -> float:
    """Distance temporelle de ``t*_w`` à ``[a ; b]`` (s, ``0010`` D4.12) : nulle si
    ``a <= t* <= b``, sinon ``min(|t* − a|, |t* − b|)``."""
    if start_s <= time_s <= end_s:
        return 0.0
    return min(abs(time_s - start_s), abs(time_s - end_s))


def within_tie(value: float, best: float, tie: float) -> bool:
    """``value`` à égalité avec le minimum ``best`` : ``value − best <= tie``, écart
    exactement égal compris (``0010`` D4.12)."""
    return value - best <= tie


def in_order(earlier_s: float, later_s: float) -> bool:
    """Chronologie : ``départ_w <= arrivée_{w+1}``, égalité comprise (``0010``
    D4.12)."""
    return earlier_s <= later_s


def maintained(
    arrival_s: float, departure_s: float, origin_s: float, prefix_end_s: float
) -> bool:
    """Maintien dans le préfixe : ``t*_0 <= arrivée_w`` et ``départ_w <= t*_m``,
    bornes incluses (``0010`` D4.12)."""
    return origin_s <= arrival_s and departure_s <= prefix_end_s


# ---------------------------------------------------------------------------
# Rattachement et recherche d'une occurrence (0010 D4.12, alinéas 1 et 2)
# ---------------------------------------------------------------------------


def attach_occurrence(
    distance_m: float, grid_m: Sequence[float]
) -> tuple[PassageRole, int, bool]:
    """Rattachement d'une occurrence à la grille de score **nominale** (``0010``
    D4.12) : ``(rôle, k, repris)``.

    Dans cet ordre, avec ``K = len(grid_m) − 1`` :

    1. ``snaps_to_point(|s_K − s_w|)`` : l'arrivée, ``(ARRIVAL, K, True)`` — un lieu
       à moins de 1 m de ``L`` représente l'arrivée, même si le dernier segment
       fait moins de 2 m ;
    2. sinon ``snaps_to_point(|s_w − s_0|)`` : le départ, ``(DEPARTURE, 0, True)`` ;
    3. sinon ``k`` = plus grand indice tel que ``s_k <= s_w``, borné à ``K − 1`` :
       ``(INTERMEDIATE, k, True)`` si ``snaps_to_point(s_w − s_k)``, sinon
       ``(INTERMEDIATE, k + 1, True)`` si ``snaps_to_point(s_{k+1} − s_w)``, sinon
       ``(INTERMEDIATE, k, False)`` : encadrée par ``(k, k + 1)``.

    Préconditions (``ValueError``) : au moins deux points, ``s_0 == 0``, grille
    strictement croissante, ``0 <= s_w <= s_K``.
    """
    if len(grid_m) < 2:
        raise ValueError(f"attach_occurrence : grille de {len(grid_m)} point(s).")
    if grid_m[0] != 0:
        raise ValueError(f"attach_occurrence : grille commençant à {grid_m[0]}.")
    if not all(a < b for a, b in pairwise(grid_m)):
        raise ValueError("attach_occurrence : grille non strictement croissante.")
    if not 0 <= distance_m <= grid_m[-1]:
        raise ValueError(
            f"attach_occurrence : abscisse {distance_m} hors de [0 ; {grid_m[-1]}]."
        )
    last = len(grid_m) - 1
    if snaps_to_point(abs(grid_m[last] - distance_m)):
        return PassageRole.ARRIVAL, last, True
    if snaps_to_point(abs(distance_m - grid_m[0])):
        return PassageRole.DEPARTURE, 0, True
    k = min(bisect_right(grid_m, distance_m) - 1, last - 1)
    if snaps_to_point(distance_m - grid_m[k]):
        return PassageRole.INTERMEDIATE, k, True
    if snaps_to_point(grid_m[k + 1] - distance_m):
        return PassageRole.INTERMEDIATE, k + 1, True
    return PassageRole.INTERMEDIATE, k, False


def occurrence_crossing(
    trace: RecordedTrace,
    series: TraceSeries,
    frame: LocalFrame,
    after_position: float,
    before_position: float,
    tolerance_m: float,
    radius_m: float,
) -> tuple[PassageStatus, float | None]:
    """Franchissement de la normale d'une occurrence encadrée (``0010`` D4.12, par
    D4.5 à D4.7 et D4.9).

    ``crossing_candidates`` en condition **ouverte**, sans borne de distance, de
    position ``after < π < before`` (strictes), puis ``group_events`` au rayon
    ``r_c``. Un événement : ``(FOUND, position de son dernier candidat)``, convention
    départ (``0005``) ; deux ou plus : ``(AMBIGUOUS, None)`` ; aucun :
    ``(OUT_OF_TOLERANCE, None)`` s'il y a au moins un franchissement orienté dans
    ``(after ; before)``, ``(ABSENT, None)`` sinon.
    """
    candidates, oriented = crossing_candidates(
        trace,
        series,
        frame,
        after_position,
        math.inf,
        closed=False,
        tolerance_m=tolerance_m,
        departure=False,
        end_position=before_position,
    )
    events = group_events(trace, series, frame, candidates, radius_m)
    if len(events) == 1:
        return PassageStatus.FOUND, events[0][-1].position
    if events:
        return PassageStatus.AMBIGUOUS, None
    if oriented > 0:
        return PassageStatus.OUT_OF_TOLERANCE, None
    return PassageStatus.ABSENT, None
