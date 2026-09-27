"""Appariement d'une trace aux points de score du tracé de référence (M4a-2a).

``0010`` D4.2 (grille de score, bornes effectives des extrémités) et D4.5 à D4.9
(franchissements, recherche ordonnée, regroupement, extrémités, trous).

Chaque seuil est jugé par un **prédicat nommé** de ce module, et seulement par lui :
le code de recherche n'en réécrit aucune comparaison. C'est ce qui permet de tester
les égalités de seuil sur des valeurs exactement représentables, jamais à travers
une trace.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from mountain_perf.backtest.geometry import (
    LocalFrame,
    ReferenceGeometry,
    frame_at,
    project_restricted,
)
from mountain_perf.backtest.series import TraceSeries
from mountain_perf.schemas import (
    ParameterSet,
    ParameterSpec,
    PointStatus,
    RecordedTrace,
    ScorePointObservation,
)

MATCHING_PARAMETER_SPECS: tuple[ParameterSpec, ...] = (
    ParameterSpec(
        name="score_step_m",
        unit="m",
        default=250.0,
        minimum=10.0,
        maximum=5000.0,
        description="Δ, pas de la grille de score (0010 D4.2).",
    ),
    ParameterSpec(
        name="lateral_tolerance_m",
        unit="m",
        default=30.0,
        minimum=1.0,
        maximum=200.0,
        description="ε, tolérance latérale et d'ancrage (0010 D4.5, D4.8).",
    ),
    ParameterSpec(
        name="cluster_radius_m",
        unit="m",
        default=15.0,
        minimum=0.0,
        maximum=100.0,
        description="r_c, rayon de regroupement des candidats (0010 D4.7).",
    ),
)
"""Les trois paramètres déclaratifs de l'appariement, défauts de ``0010``.

``r_c`` est fixe dans la sensibilité (``0010`` D13) ; tous les autres seuils sont
des constantes de ce module, fixes au M4.
"""

WINDOW_FACTOR = 2.5
"""Facteur de la fenêtre de recherche (``0010`` D4.6) : la borne s'élargit de
``2,5·Δ`` par point depuis le dernier point daté."""

WINDOW_SLACK_M = 300.0
"""Marge de la fenêtre de recherche (m, ``0010`` D4.6)."""


def score_grid(length_m: float, step_m: float) -> tuple[float, ...]:
    """Grille de score ``s_k = k·Δ`` pour ``k·Δ < L``, plus ``L`` (``0010`` D4.2).

    Le produit ``k·Δ`` est calculé à chaque rang, jamais par additions successives :
    une somme cumulée de ``0,1`` rend ``0,7999999999999999`` au neuvième rang.
    ``step_m <= 0`` : ``ValueError``.
    """
    if not step_m > 0:
        raise ValueError(f"score_grid : pas non positif {step_m}.")
    grid_m: list[float] = []
    k = 0
    while k * step_m < length_m:
        grid_m.append(k * step_m)
        k += 1
    grid_m.append(length_m)
    return tuple(grid_m)


# ---------------------------------------------------------------------------
# Prédicats de seuil (0010 D4.5 à D4.8)
# ---------------------------------------------------------------------------


def crosses(h_before_m: float, h_after_m: float, *, closed: bool) -> bool:
    """Franchissement orienté de la normale entre deux enregistrements.

    Ouvert : ``h_before <= 0 < h_after`` (``0010`` D4.5). Fermé, au point
    d'arrivée : ``h_before <= 0 <= h_after`` et ``(h_before, h_after) != (0, 0)``
    (D4.8) — une trace qui longe la ligne d'arrivée ne la franchit pas.
    """
    if closed:
        return h_before_m <= 0 <= h_after_m and (h_before_m, h_after_m) != (0, 0)
    return h_before_m <= 0 < h_after_m


def crossing_fraction(h_before_m: float, h_after_m: float) -> float:
    """``f`` du franchissement (``0010`` D4.5) : ``0`` si ``h_before == 0``, sinon
    ``−h_before / (h_after − h_before)``."""
    if h_before_m == 0:
        return 0.0
    return -h_before_m / (h_after_m - h_before_m)


def within_tolerance(lateral_m: float, tolerance_m: float) -> bool:
    """Candidat admissible : écart latéral ``abs(lateral) < ε``, strictement
    (``0010`` D4.5)."""
    return abs(lateral_m) < tolerance_m


def window_bound_m(realized_m: float, step_m: float, k: int, k_last: int) -> float:
    """Borne de la fenêtre de recherche du point ``k`` (``0010`` D4.6) :
    ``d_r(π_cur) + 2,5·Δ·(k − k_der) + 300`` m."""
    return realized_m + WINDOW_FACTOR * step_m * (k - k_last) + WINDOW_SLACK_M


def within_window(realized_m: float, bound_m: float) -> bool:
    """Abscisse réalisée dans la fenêtre : ``d_r <= D`` (``0010`` D4.6)."""
    return realized_m <= bound_m


def within_cluster(distance_m: float, radius_m: float) -> bool:
    """Point du sous-chemin à ``<= r_c`` de ``Q`` (``0010`` D4.7)."""
    return distance_m <= radius_m


def departure_anchorable(h_m: float, lateral_m: float, tolerance_m: float) -> bool:
    """Premier enregistrement ancrable au départ (``0010`` D4.8) :
    ``0 < h_0 <= ε`` et ``abs(lateral) < ε``."""
    return 0 < h_m <= tolerance_m and within_tolerance(lateral_m, tolerance_m)


def arrival_anchorable(h_m: float, lateral_m: float, tolerance_m: float) -> bool:
    """Dernier enregistrement ancrable à l'arrivée (``0010`` D4.8) :
    ``−ε <= h < 0`` et ``abs(lateral) < ε``."""
    return -tolerance_m <= h_m < 0 and within_tolerance(lateral_m, tolerance_m)


def departure_offset_ok(s_m: float, tolerance_m: float, next_nominal_m: float) -> bool:
    """Projection d'ancrage du départ retenue (``0010`` D4.8) : ``s'_0 <= ε``, et
    ``s'_0 < s_1`` pour des bornes effectives strictement croissantes."""
    return s_m <= tolerance_m and s_m < next_nominal_m


def arrival_offset_ok(
    s_m: float, length_m: float, tolerance_m: float, previous_bound_m: float
) -> bool:
    """Projection d'ancrage de l'arrivée retenue (``0010`` D4.8) :
    ``L − s'_K <= ε``, et ``s'_K > b_{K−1}`` pour des bornes effectives strictement
    croissantes."""
    return length_m - s_m <= tolerance_m and s_m > previous_bound_m


# ---------------------------------------------------------------------------
# Positions fractionnaires dans la trace (0010 D4.4)
# ---------------------------------------------------------------------------


def _segment(count: int, position: float) -> tuple[int, float]:
    """``(i, f)`` de ``π = i + f``, avec ``i = min(⌊π⌋, n − 2)`` : ``f = 1`` au
    dernier enregistrement. ``π`` hors de ``[0 ; n − 1]`` : ``ValueError``."""
    if not 0 <= position <= count - 1:
        raise ValueError(f"Position {position} hors de [0 ; {count - 1}].")
    i = min(math.floor(position), count - 2)
    return i, position - i


def _interpolate(values: Sequence[float], position: float) -> float:
    i, f = _segment(len(values), position)
    return (1 - f) * values[i] + f * values[i + 1]


def time_at(trace: RecordedTrace, position: float) -> float:
    """``t(π)`` (s) : instant à la position ``π``, exact en ``π`` entier.

    ``π = i + f``, ``i = min(⌊π⌋, n − 2)``, interpolation ``(1 − f)·a + f·b``.
    ``π`` hors de ``[0 ; n − 1]`` : ``ValueError``.
    """
    return _interpolate(trace.time_s, position)


def realized_at(series: TraceSeries, position: float) -> float:
    """``d_r(π)`` (m) : abscisse réalisée à la position ``π``, exacte en ``π``
    entier ; mêmes conventions que ``time_at``."""
    return _interpolate(series.realized_distance_m, position)


def raw_position_at(trace: RecordedTrace, position: float) -> tuple[float, float]:
    """``P(π)`` : latitude et longitude **brutes** à la position ``π``, exactes en
    ``π`` entier ; mêmes conventions que ``time_at``."""
    i, f = _segment(len(trace.time_s), position)
    lat, lon = trace.latitude_deg, trace.longitude_deg
    return (1 - f) * lat[i] + f * lat[i + 1], (1 - f) * lon[i] + f * lon[i + 1]


# ---------------------------------------------------------------------------
# Franchissements, recherche, regroupement (0010 D4.5 à D4.7, D4.9)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrossingCandidate:
    """Candidat admissible d'un point de score (``0010`` D4.5).

    - ``position`` : ``π = i + f`` du franchissement ;
    - ``lateral_m`` : écart latéral signé, interpolé ``(1 − f)·a + f·b`` entre ceux
      des deux enregistrements, **avant** toute valeur absolue.
    """

    position: float
    lateral_m: float


def crossing_candidates(
    trace: RecordedTrace,
    series: TraceSeries,
    frame: LocalFrame,
    current_position: float,
    bound_m: float,
    *,
    closed: bool,
    tolerance_m: float,
    departure: bool,
    end_position: float | None = None,
) -> tuple[tuple[CrossingCandidate, ...], int]:
    """Candidats admissibles d'un point, et nombre de franchissements orientés.

    Intervalles ``i`` de ``⌊π_cur⌋`` à ``n − 2``, **tant que** ``d_r(i)`` est dans la
    fenêtre ``bound_m`` (``0010`` D4.6). Franchissement orienté : ``crosses`` sur les
    ``h`` des positions **brutes** (condition fermée à l'arrivée), hors d'un trou
    (D4.9), en ``π > π_cur`` (``π >= 0`` au départ), et ``d_r(π)`` dans la fenêtre.
    Admissible si ``within_tolerance`` sur l'écart latéral interpolé (D4.5). Tous
    les candidats de la fenêtre sont énumérés ; ceux de même ``π`` sont confondus
    (D4.7). Rend les candidats triés par ``π`` et le nombre de franchissements
    orientés, qui départage ``hors ε`` et ``absent``.

    ``end_position`` (M4a-3, passages nommés de D4.12) : borne haute **stricte** de
    la recherche. Un franchissement de position ``π >= end_position`` n'est ni
    compté parmi les franchissements orientés, ni candidat ; le parcours s'arrête au
    premier intervalle ``i >= end_position``, dont tout franchissement serait en
    ``π >= i``. ``None`` : aucune borne haute, comportement de M4a-2a.
    """
    lat, lon = trace.latitude_deg, trace.longitude_deg
    realized_m = series.realized_distance_m
    admissible: dict[float, CrossingCandidate] = {}
    oriented = 0
    start = math.floor(current_position)
    h_before_m, lateral_before_m = frame.coordinates(lat[start], lon[start])
    for i in range(start, len(lat) - 1):
        if not within_window(realized_m[i], bound_m):
            break
        if end_position is not None and i >= end_position:
            break
        h_after_m, lateral_after_m = frame.coordinates(lat[i + 1], lon[i + 1])
        if crosses(h_before_m, h_after_m, closed=closed) and not series.gap_after[i]:
            f = crossing_fraction(h_before_m, h_after_m)
            position = i + f
            ordered = position >= 0 if departure else position > current_position
            if end_position is not None:
                ordered = ordered and position < end_position
            if ordered and within_window(realized_at(series, position), bound_m):
                oriented += 1
                lateral_m = (1 - f) * lateral_before_m + f * lateral_after_m
                if within_tolerance(lateral_m, tolerance_m):
                    admissible.setdefault(
                        position, CrossingCandidate(position, lateral_m)
                    )
        h_before_m, lateral_before_m = h_after_m, lateral_after_m
    ordered_candidates = sorted(admissible.values(), key=lambda c: c.position)
    return tuple(ordered_candidates), oriented


def gap_between(
    series: TraceSeries, first_position: float, second_position: float
) -> bool:
    """Un intervalle de trou entre deux positions (``0010`` D4.7, D4.9).

    Vrai s'il existe un intervalle de trou d'indice ``i`` avec
    ``⌊first⌋ <= i <= ⌈second⌉ − 1``. ``first > second`` : ``ValueError``.
    """
    if first_position > second_position:
        raise ValueError(
            f"gap_between : positions décroissantes {first_position} > "
            f"{second_position}."
        )
    return any(
        series.gap_after[i]
        for i in range(math.floor(first_position), math.ceil(second_position))
    )


def _same_event(
    trace: RecordedTrace,
    series: TraceSeries,
    frame: LocalFrame,
    first: float,
    second: float,
    radius_m: float,
) -> bool:
    """Même bloc, et sous-chemin fermé de ``P(π_a)`` à ``P(π_b)`` à ``<= r_c`` de
    ``Q`` ; vérifier les sommets suffit, le disque est convexe (``0010`` D4.7)."""
    if gap_between(series, first, second):
        return False
    points = [
        raw_position_at(trace, first),
        *(
            (trace.latitude_deg[j], trace.longitude_deg[j])
            for j in range(math.floor(first) + 1, math.ceil(second))
        ),
        raw_position_at(trace, second),
    ]
    return all(within_cluster(frame.distance_m(*point), radius_m) for point in points)


def group_events(
    trace: RecordedTrace,
    series: TraceSeries,
    frame: LocalFrame,
    candidates: Sequence[CrossingCandidate],
    radius_m: float,
) -> tuple[tuple[CrossingCandidate, ...], ...]:
    """Regroupe des candidats triés par ``π`` en **événements** (``0010`` D4.7).

    Deux candidats consécutifs ``a``, ``b`` sont dans le même événement si aucun
    intervalle de trou n'est compris entre ``⌊π_a⌋`` et ``⌈π_b⌉ − 1`` (même bloc), et
    si ``P(π_a)``, ``P(π_b)`` et les enregistrements bruts d'indice ``π_a < j < π_b``
    vérifient tous ``within_cluster`` autour de ``Q``.
    """
    events: list[list[CrossingCandidate]] = []
    for candidate in candidates:
        if events and _same_event(
            trace, series, frame, events[-1][-1].position, candidate.position, radius_m
        ):
            events[-1].append(candidate)
        else:
            events.append([candidate])
    return tuple(tuple(event) for event in events)


# ---------------------------------------------------------------------------
# Points de score (0010 D4.2, D4.5 à D4.9)
# ---------------------------------------------------------------------------


def _undated(
    k: int, s_m: float, status: PointStatus, candidates: int = 0, events: int = 0
) -> ScorePointObservation:
    return ScorePointObservation(
        index=k,
        nominal_m=s_m,
        effective_m=s_m,
        status=status,
        position=None,
        time_s=None,
        lateral_m=None,
        realized_m=None,
        candidate_count=candidates,
        event_count=events,
    )


def _unobserved(k: int, s_m: float, oriented: int) -> ScorePointObservation:
    """Ni candidat admissible ni ancrage : ``hors ε`` s'il existait un franchissement
    orienté dans la fenêtre, ``absent`` sinon (``0010`` D4.7, *précision*, appliquée
    aux extrémités de D4.8)."""
    status = PointStatus.OUT_OF_TOLERANCE if oriented > 0 else PointStatus.ABSENT
    return _undated(k, s_m, status)


@dataclass(frozen=True)
class _Search:
    """Ce que la datation d'un point lit : référence, trace, repère, ``ε``, et le
    nombre de franchissements orientés de sa fenêtre."""

    geometry: ReferenceGeometry
    trace: RecordedTrace
    series: TraceSeries
    frame: LocalFrame
    tolerance_m: float
    oriented: int

    def dated(
        self,
        k: int,
        s_m: float,
        status: PointStatus,
        position: float,
        lateral_m: float,
        effective_m: float | None = None,
        candidates: int = 0,
    ) -> ScorePointObservation:
        """Point daté en ``π`` : ``t*`` et ``d_r`` lus en ``π`` (§ 5a.5)."""
        return ScorePointObservation(
            index=k,
            nominal_m=s_m,
            effective_m=s_m if effective_m is None else effective_m,
            status=status,
            position=position,
            time_s=time_at(self.trace, position),
            lateral_m=lateral_m,
            realized_m=realized_at(self.series, position),
            candidate_count=candidates,
            event_count=1 if status is PointStatus.FOUND else 0,
        )


def _departure(search: _Search, grid_m: Sequence[float]) -> ScorePointObservation:
    """Départ sans candidat admissible (``0010`` D4.8) : ancrage par le premier
    enregistrement, projeté sur ``[0 ; min(2ε, L)]`` ; ``s_1`` borne ``s'_0``."""
    trace, frame, tolerance_m = search.trace, search.frame, search.tolerance_m
    lat_deg, lon_deg = trace.latitude_deg[0], trace.longitude_deg[0]
    h_m, lateral_m = frame.coordinates(lat_deg, lon_deg)
    if departure_anchorable(h_m, lateral_m, tolerance_m):
        projection = project_restricted(
            search.geometry,
            lat_deg,
            lon_deg,
            0.0,
            min(2 * tolerance_m, search.geometry.length_m),
            (frame.anchor_lat_deg, frame.anchor_lon_deg),
        )
        if projection.ambiguous:
            return _undated(0, grid_m[0], PointStatus.AMBIGUOUS)
        if departure_offset_ok(projection.distance_along_m, tolerance_m, grid_m[1]):
            return search.dated(
                0,
                grid_m[0],
                PointStatus.ANCHORED,
                0.0,
                lateral_m,
                effective_m=projection.distance_along_m,
            )
    return _unobserved(0, grid_m[0], search.oriented)


def _arrival(
    search: _Search,
    grid_m: Sequence[float],
    current_position: float,
    bound_m: float,
    previous_bound_m: float,
) -> ScorePointObservation:
    """Arrivée sans candidat admissible (``0010`` D4.8) : ancrage par le dernier
    enregistrement, dans la fenêtre et après ``π_cur``, projeté sur
    ``[max(0, L − 2ε) ; L]`` ; ``previous_bound_m`` est ``b_{K−1}``."""
    trace, frame, tolerance_m = search.trace, search.frame, search.tolerance_m
    k, length_m = len(grid_m) - 1, search.geometry.length_m
    j = len(trace.time_s) - 1
    lat_deg, lon_deg = trace.latitude_deg[j], trace.longitude_deg[j]
    h_m, lateral_m = frame.coordinates(lat_deg, lon_deg)
    if (
        arrival_anchorable(h_m, lateral_m, tolerance_m)
        and within_window(search.series.realized_distance_m[j], bound_m)
        and j > current_position
    ):
        projection = project_restricted(
            search.geometry,
            lat_deg,
            lon_deg,
            max(0.0, length_m - 2 * tolerance_m),
            length_m,
            (frame.anchor_lat_deg, frame.anchor_lon_deg),
        )
        if projection.ambiguous:
            return _undated(k, grid_m[k], PointStatus.AMBIGUOUS)
        if arrival_offset_ok(
            projection.distance_along_m, length_m, tolerance_m, previous_bound_m
        ):
            return search.dated(
                k,
                grid_m[k],
                PointStatus.ANCHORED,
                float(j),
                lateral_m,
                effective_m=projection.distance_along_m,
            )
    return _unobserved(k, grid_m[k], search.oriented)


def match_points(
    geometry: ReferenceGeometry,
    trace: RecordedTrace,
    series: TraceSeries,
    parameters: ParameterSet,
) -> tuple[ScorePointObservation, ...]:
    """Observe chaque point de la grille de score, dans l'ordre (``0010`` D4.2–D4.9).

    État du chercheur ``(π_cur, k_der) = (0, 0)``. Pour chaque point ``k`` : repère,
    dont la tangente indéfinie laisse l'état inchangé ; borne de fenêtre depuis
    ``d_r(π_cur)`` ; candidats admissibles et événements. Un événement : ``FOUND``,
    daté par son dernier candidat, par son premier à l'arrivée ; l'état avance. Deux
    ou plus : ``AMBIGUOUS``. Aucun : ancrage au départ et à l'arrivée, sinon
    ``hors ε`` ou ``absent``. Hors ``FOUND`` et ``ANCHORED``, l'état est inchangé.

    Préconditions (``ValueError``) : ``series`` construit sur ``trace`` (même nombre
    d'enregistrements) ; ``parameters`` déclaré par ``MATCHING_PARAMETER_SPECS``.
    """
    if len(series.realized_distance_m) != len(trace.time_s):
        raise ValueError(
            "match_points : séries et trace de longueurs différentes "
            f"({len(series.realized_distance_m)} ≠ {len(trace.time_s)})."
        )
    if parameters.specs != MATCHING_PARAMETER_SPECS:
        raise ValueError(
            "match_points : paramètres non déclarés par MATCHING_PARAMETER_SPECS."
        )
    step_m = parameters["score_step_m"]
    tolerance_m = parameters["lateral_tolerance_m"]
    radius_m = parameters["cluster_radius_m"]
    grid_m = score_grid(geometry.length_m, step_m)
    last = len(grid_m) - 1
    current_position, k_last = 0.0, 0
    observations: list[ScorePointObservation] = []
    for k, s_m in enumerate(grid_m):
        frame = frame_at(geometry, s_m)
        if frame is None:
            observations.append(_undated(k, s_m, PointStatus.UNDEFINED_TANGENT))
            continue
        bound_m = window_bound_m(
            realized_at(series, current_position), step_m, k, k_last
        )
        candidates, oriented = crossing_candidates(
            trace,
            series,
            frame,
            current_position,
            bound_m,
            closed=k == last,
            tolerance_m=tolerance_m,
            departure=k == 0,
        )
        events = group_events(trace, series, frame, candidates, radius_m)
        search = _Search(geometry, trace, series, frame, tolerance_m, oriented)
        if len(events) == 1:
            chosen = events[0][0] if k == last else events[0][-1]
            observation = search.dated(
                k,
                s_m,
                PointStatus.FOUND,
                chosen.position,
                chosen.lateral_m,
                candidates=len(candidates),
            )
        elif events:
            observation = _undated(
                k, s_m, PointStatus.AMBIGUOUS, len(candidates), len(events)
            )
        elif k == 0:
            observation = _departure(search, grid_m)
        elif k == last:
            observation = _arrival(
                search, grid_m, current_position, bound_m, observations[-1].effective_m
            )
        else:
            observation = _unobserved(k, s_m, oriented)
        if observation.position is not None:
            current_position, k_last = observation.position, k
        observations.append(observation)
    return tuple(observations)
