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
import statistics
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from mountain_perf.backtest.clocks import stop_episodes
from mountain_perf.backtest.geometry import (
    LocalFrame,
    ReferenceGeometry,
    frame_at,
    position_at,
    to_local,
)
from mountain_perf.backtest.matching import (
    MATCHING_PARAMETER_SPECS,
    crossing_candidates,
    group_events,
    score_grid,
    time_at,
)
from mountain_perf.backtest.series import TraceSeries
from mountain_perf.schemas import (
    CENTRAL_CONVENTION_INDEX,
    PASSAGE_STATUS_UNAVAILABILITY,
    ClockPartition,
    EpisodeAttribution,
    EpisodeOutcome,
    MatchResult,
    PassageMatchResult,
    PassageObservation,
    PassageRole,
    PassageStatus,
    RecordedTrace,
    RouteProfile,
    ScorePointObservation,
    StopEpisode,
    Unavailability,
)

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


# ---------------------------------------------------------------------------
# Association arrêt → passage, chronologie (0010 D4.12, alinéas 3 et 4)
# ---------------------------------------------------------------------------


def episode_median(series: TraceSeries, episode: StopEpisode) -> tuple[float, float]:
    """Position lissée médiane d'un épisode (``0010`` D4.12) : ``statistics.median``
    des latitudes **lissées**, puis des longitudes lissées, des enregistrements
    ``first_record`` à ``last_record`` inclus.

    Le plan local de ``0008`` étant affine en degrés à ancre fixe, c'est la médiane
    coordonnée par coordonnée dans le repère local.
    """
    records = slice(episode.first_record, episode.last_record + 1)
    return (
        statistics.median(series.smoothed_latitude_deg[records]),
        statistics.median(series.smoothed_longitude_deg[records]),
    )


def attribute_episode(
    start_s: float, end_s: float, candidates: Sequence[tuple[int, float, float]]
) -> tuple[EpisodeOutcome, int | None]:
    """Attribution d'un épisode ``[a ; b]`` à une seule occurrence (``0010`` D4.12).

    ``candidates`` : ``(rang, t*_w, distance à la médiane)``. Aucune :
    ``(NO_CANDIDATE, None)``. Sinon, garder celles dont ``time_distance_s`` est à
    égalité (``within_tie``, 1 s) avec le minimum ; s'il en reste plusieurs, garder
    parmi **elles** celles dont la distance est à égalité (1 m) avec **leur**
    minimum. Une seule : ``(ATTRIBUTED, rang)`` ; plusieurs : ``(TIE, None)``,
    épisode « non attribué », publié.
    """
    if not candidates:
        return EpisodeOutcome.NO_CANDIDATE, None
    delays_s = [time_distance_s(t_s, start_s, end_s) for _, t_s, _ in candidates]
    best_s = min(delays_s)
    kept = [
        candidate
        for candidate, delay_s in zip(candidates, delays_s, strict=True)
        if within_tie(delay_s, best_s, ATTRIBUTION_TIME_TIE_S)
    ]
    if len(kept) > 1:
        best_m = min(distance_m for _, _, distance_m in kept)
        kept = [
            candidate
            for candidate in kept
            if within_tie(candidate[2], best_m, ATTRIBUTION_DISTANCE_TIE_M)
        ]
    if len(kept) == 1:
        return EpisodeOutcome.ATTRIBUTED, kept[0][0]
    return EpisodeOutcome.TIE, None


def chronology_violations(
    envelopes: Sequence[tuple[float, float]], final_arrival_s: float | None
) -> tuple[bool, ...]:
    """Violations de chronologie (``0010`` D4.12) : un booléen par enveloppe.

    Termes : les enveloppes ``(arrivée, départ)`` dans l'ordre donné, puis
    ``(final, final)`` si ``final_arrival_s`` est présent. Pour chaque couple de
    termes consécutifs ``(i, i + 1)`` qui ne vérifie pas ``in_order(départ_i,
    arrivée_{i+1})``, marquer ``i``, et ``i + 1`` s'il est une enveloppe — l'arrivée
    finale n'est jamais marquée. Tous les couples sont jugés sur les valeurs données.
    """
    terms = list(envelopes)
    if final_arrival_s is not None:
        terms.append((final_arrival_s, final_arrival_s))
    marks = [False] * len(envelopes)
    for i, ((_, departure_s), (arrival_s, _)) in enumerate(pairwise(terms)):
        if not in_order(departure_s, arrival_s):
            marks[i] = True
            if i + 1 < len(envelopes):
                marks[i + 1] = True
    return tuple(marks)


# ---------------------------------------------------------------------------
# Fonction d'ensemble (0010 D4.12)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Searched:
    """Une occurrence après la recherche (§ 6.4 du brief M4a-3) : rôle, statut,
    ``t*_w`` et fenêtre d'association, ces deux derniers présents si elle est
    datée."""

    role: PassageRole
    status: PassageStatus
    crossing_s: float | None
    window_s: tuple[float, float] | None


def _dated(point: ScorePointObservation) -> tuple[float, float]:
    """``(π, t*)`` d'un point daté. Tout point du préfixe comparable l'est (ses
    segments sont admis) : un point non daté ici est une incohérence du
    ``MatchResult``, ``ValueError``."""
    if point.position is None or point.time_s is None:
        raise ValueError(f"observe_passages : point {point.index} non daté.")
    return point.position, point.time_s


def _resumed(
    role: PassageRole,
    points: Sequence[ScorePointObservation],
    k: int,
    trace: RecordedTrace,
) -> _Searched:
    """Reprise du point ``k`` (``0010`` D4.12, choix 3 et 5 du brief) : son statut
    et son instant, ancrage compris ; fenêtre de ``t*_{k−1}`` (``t*_0`` si
    ``k = 0``) à l'instant du **premier point daté d'indice > k**, à défaut du
    dernier enregistrement. Seul un départ, avec ``m = 0``, reprend un point non
    daté : il n'a alors aucun instant."""
    point = points[k]
    status = PassageStatus(point.status.value)
    if point.time_s is None:
        return _Searched(role, status, None, None)
    end_s = trace.time_s[-1]
    for later in points[k + 1 :]:
        if later.time_s is not None:
            end_s = later.time_s
            break
    _, start_s = _dated(points[max(0, k - 1)])
    return _Searched(role, status, point.time_s, (start_s, end_s))


def _bracketed(
    distance_m: float,
    first: ScorePointObservation,
    second: ScorePointObservation,
    geometry: ReferenceGeometry,
    trace: RecordedTrace,
    series: TraceSeries,
    tolerance_m: float,
    radius_m: float,
) -> _Searched:
    """Occurrence encadrée par les points ``k`` et ``k + 1``, tous deux datés
    (``0010`` D4.12, choix 4) : repère en ``s_w`` (tangente indéfinie : statut du
    même nom), ``occurrence_crossing`` entre ``π_k`` et ``π_{k+1}``, ``t* = t(π)``,
    fenêtre ``[t*_k ; t*_{k+1}]``."""
    frame = frame_at(geometry, distance_m)
    if frame is None:
        return _Searched(
            PassageRole.INTERMEDIATE, PassageStatus.UNDEFINED_TANGENT, None, None
        )
    (after, start_s), (before, end_s) = _dated(first), _dated(second)
    status, position = occurrence_crossing(
        trace, series, frame, after, before, tolerance_m, radius_m
    )
    if position is None:
        return _Searched(PassageRole.INTERMEDIATE, status, None, None)
    return _Searched(
        PassageRole.INTERMEDIATE, status, time_at(trace, position), (start_s, end_s)
    )


def _availability(
    role: PassageRole,
    status: PassageStatus,
    arrival_s: float | None,
    departure_s: float | None,
    origin_s: float | None,
    prefix_end_s: float | None,
) -> tuple[bool, Unavailability | None]:
    """Maintien dans le préfixe (``0010`` D4.12, choix 12) : ``(comparable, motif)``.

    Départ : jamais comparable, sans motif. ``FOUND`` ou ``ANCHORED`` : comparable si
    ``maintained(arrivée, départ, t*_0, t*_m)``, sinon ``INSUFFICIENT_SUPPORT`` —
    on ne tronque jamais un épisode, on ne retire jamais une attribution. Autre
    statut : le motif de ``PASSAGE_STATUS_UNAVAILABILITY``.
    """
    if role is PassageRole.DEPARTURE:
        return False, None
    if status not in (PassageStatus.FOUND, PassageStatus.ANCHORED):
        return False, PASSAGE_STATUS_UNAVAILABILITY[status]
    if arrival_s is None or departure_s is None or origin_s is None:
        raise ValueError("observe_passages : occurrence datée sans instant.")
    if prefix_end_s is None:
        raise ValueError("observe_passages : occurrence datée, préfixe non daté.")
    if maintained(arrival_s, departure_s, origin_s, prefix_end_s):
        return True, None
    return False, Unavailability.INSUFFICIENT_SUPPORT


def observe_passages(
    match: MatchResult,
    geometry: ReferenceGeometry,
    profile: RouteProfile,
    trace: RecordedTrace,
    series: TraceSeries,
    partition: ClockPartition,
) -> PassageMatchResult:
    """Passages nommés et événements d'une sortie (``0010`` D4.12).

    Dans l'ordre du brief M4a-3 (choix 13) :

    1. **recherche**, pour chaque occurrence de ``profile.resolved_points`` :
       ``attach_occurrence`` sur la grille nominale ``score_grid(L, Δ)`` ; le départ
       est toujours observé (reprise du point 0) ; l'arrivée l'est si ``m == K``
       (reprise du point ``K``), sinon ``OUTSIDE_PREFIX`` ; une intermédiaire l'est
       si ``observed_in_prefix(s_w, b_0, b_m, m)``, sinon ``OUTSIDE_PREFIX`` sans
       recherche — reprise du point à moins de 1 m, ou recherche entre les deux
       points qui l'encadrent ;
    2. **association** des épisodes ``stop_episodes`` sous ``θ_c``, dans l'ordre du
       temps : candidates = occurrences ``INTERMEDIATE`` ``FOUND`` dont
       ``Q_w = position_at(s_w)`` est ``near_passage`` de la médiane de l'épisode
       (distance dans le plan de ``0008`` ancré en ``Q_w``) et dont la fenêtre
       chevauche l'épisode ; ``attribute_episode`` ;
    3. **événements** de chaque occurrence datée : ``arrivée = min(t*, a)``,
       ``départ = max(t*, b)``, ``S = math.fsum(b − a)`` sur ses épisodes
       attribués ;
    4. **chronologie** des occurrences ``INTERMEDIATE`` ``FOUND``, dans l'ordre
       ``(s_w, rang)``, suivies de l'arrivée finale ``t*_K`` si et seulement si
       ``m == K`` : une occurrence marquée passe ``AMBIGUOUS``, événements
       conservés ;
    5. **maintien** : une occurrence ``FOUND`` ou ``ANCHORED`` de rôle autre que
       départ est comparable si ``maintained(arrivée, départ, t*_0, t*_m)``, sinon
       ``INSUFFICIENT_SUPPORT`` ; les autres statuts prennent le motif de
       ``PASSAGE_STATUS_UNAVAILABILITY`` ; un départ n'est jamais comparable.

    Préconditions (``ValueError``) : ``series`` et ``partition`` construits sur
    ``trace`` (mêmes nombres d'enregistrements) ; ``match.parameters`` déclaré par
    ``MATCHING_PARAMETER_SPECS`` ; ``profile.distance_m[-1] == geometry.length_m``
    bit pour bit ; ``len(match.points) == len(score_grid(L, Δ))``.
    """
    records = len(trace.time_s)
    if len(series.realized_distance_m) != records or len(partition.time_s) != records:
        raise ValueError(
            "observe_passages : séries, partition et trace de longueurs différentes "
            f"({len(series.realized_distance_m)}, {len(partition.time_s)}, "
            f"{records})."
        )
    parameters = match.parameters
    if parameters.specs != MATCHING_PARAMETER_SPECS:
        raise ValueError(
            "observe_passages : paramètres non déclarés par MATCHING_PARAMETER_SPECS."
        )
    if profile.distance_m[-1] != geometry.length_m:
        raise ValueError(
            "observe_passages : profil et géométrie de tracés différents "
            f"({profile.distance_m[-1]} ≠ {geometry.length_m})."
        )
    grid_m = score_grid(geometry.length_m, parameters["score_step_m"])
    if len(match.points) != len(grid_m):
        raise ValueError(
            f"observe_passages : {len(match.points)} points pour une grille de "
            f"{len(grid_m)}."
        )
    tolerance_m = parameters["lateral_tolerance_m"]
    radius_m = parameters["cluster_radius_m"]
    points, coverage = match.points, match.coverage
    last = len(grid_m) - 1
    m = coverage.prefix_segment_count
    start_m, end_m = points[0].effective_m, coverage.prefix_end_m
    occurrences = profile.resolved_points

    # 1. Recherche (§ 6.4).
    searched: list[_Searched] = []
    for occurrence in occurrences:
        distance_m = occurrence.distance_m
        role, k, snapped = attach_occurrence(distance_m, grid_m)
        outside = _Searched(role, PassageStatus.OUTSIDE_PREFIX, None, None)
        if role is PassageRole.DEPARTURE:
            searched.append(_resumed(role, points, 0, trace))
        elif role is PassageRole.ARRIVAL:
            searched.append(
                _resumed(role, points, last, trace) if m == last else outside
            )
        elif not observed_in_prefix(distance_m, start_m, end_m, m):
            searched.append(outside)
        elif snapped:
            searched.append(_resumed(role, points, k, trace))
        else:
            searched.append(
                _bracketed(
                    distance_m,
                    points[k],
                    points[k + 1],
                    geometry,
                    trace,
                    series,
                    tolerance_m,
                    radius_m,
                )
            )

    # 2. Association (§ 6.5).
    candidates = [
        (rank, found, position_at(geometry, occurrences[rank].distance_m))
        for rank, found in enumerate(searched)
        if found.role is PassageRole.INTERMEDIATE
        and found.status is PassageStatus.FOUND
    ]
    attributions: list[EpisodeAttribution] = []
    for episode in stop_episodes(partition, CENTRAL_CONVENTION_INDEX):
        median = episode_median(series, episode)
        eligible: list[tuple[int, float, float]] = []
        for rank, found, anchor in candidates:
            if found.crossing_s is None or found.window_s is None:
                continue
            distance_m = math.hypot(*to_local(*anchor, *median))
            window_start_s, window_end_s = found.window_s
            if near_passage(distance_m, tolerance_m) and windows_overlap(
                window_start_s, window_end_s, episode.start_s, episode.end_s
            ):
                eligible.append((rank, found.crossing_s, distance_m))
        outcome, index = attribute_episode(episode.start_s, episode.end_s, eligible)
        attributions.append(EpisodeAttribution(episode, outcome, index, *median))

    # 3. Événements (§ 6.6).
    events: dict[int, tuple[float, float, float, int]] = {}
    for rank, found in enumerate(searched):
        if found.crossing_s is None:
            continue
        attributed = [a.episode for a in attributions if a.passage_index == rank]
        events[rank] = (
            min([found.crossing_s, *(e.start_s for e in attributed)]),
            max([found.crossing_s, *(e.end_s for e in attributed)]),
            math.fsum(e.end_s - e.start_s for e in attributed),
            len(attributed),
        )

    # 4. Chronologie (§ 6.7).
    judged = sorted(
        (rank for rank, _, _ in candidates),
        key=lambda rank: (occurrences[rank].distance_m, rank),
    )
    final_s = points[last].time_s if m == last else None
    marks = chronology_violations(
        [(events[rank][0], events[rank][1]) for rank in judged], final_s
    )
    violated = {rank for rank, mark in zip(judged, marks, strict=True) if mark}

    # 5. Maintien (§ 6.8).
    passages: list[PassageObservation] = []
    for rank, (occurrence, found) in enumerate(zip(occurrences, searched, strict=True)):
        status = PassageStatus.AMBIGUOUS if rank in violated else found.status
        arrival_s, departure_s, stop_s, count = events.get(rank, (None, None, None, 0))
        comparable, unavailability = _availability(
            found.role,
            status,
            arrival_s,
            departure_s,
            points[0].time_s,
            coverage.prefix_end_s,
        )
        passages.append(
            PassageObservation(
                point=occurrence,
                role=found.role,
                status=status,
                crossing_s=found.crossing_s,
                association_window_s=found.window_s,
                arrival_s=arrival_s,
                departure_s=departure_s,
                stop_total_s=stop_s,
                episode_count=count,
                chronology_violation=rank in violated,
                comparable=comparable,
                unavailability=unavailability,
            )
        )
    return PassageMatchResult(passages=tuple(passages), episodes=tuple(attributions))
