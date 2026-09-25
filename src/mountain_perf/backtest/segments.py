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
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from mountain_perf.backtest.clocks import cumulative_s, trace_totals
from mountain_perf.backtest.geometry import (
    ReferenceGeometry,
    position_at,
    project_restricted,
    to_local,
)
from mountain_perf.backtest.matching import (
    MATCHING_PARAMETER_SPECS,
    gap_between,
    match_points,
    raw_position_at,
)
from mountain_perf.backtest.series import TraceSeries
from mountain_perf.gpx.geo import haversine_m
from mountain_perf.schemas import (
    CLOCK_CONVENTIONS,
    AdmittedTotals,
    ClockPartition,
    Coverage,
    IntervalState,
    MatchResult,
    ParameterSet,
    RecordedTrace,
    Regime,
    RegimeClass,
    ResolvedPoint,
    RouteProfile,
    ScorePointObservation,
    ScoreSegmentObservation,
    SegmentExclusion,
)

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


# ---------------------------------------------------------------------------
# Chemin réalisé, rapport de longueur, contrôle intérieur (0010 D4.10, D4.3)
# ---------------------------------------------------------------------------


def realized_path(
    trace: RecordedTrace,
    series: TraceSeries,
    first_position: float,
    second_position: float,
) -> tuple[tuple[float, float], ...]:
    """Chemin réalisé d'un segment, en ``(latitude, longitude)`` (``0010`` D4.10).

    Le point de franchissement ``P(π_k)`` (position **brute**, l'enregistrement
    lui-même quand ``π_k`` est entier), puis les positions **lissées** des
    enregistrements d'indice entier ``π_k < j < π_{k+1}``, dans l'ordre, puis
    ``P(π_{k+1})``. ``first > second`` : ``ValueError``.
    """
    if first_position > second_position:
        raise ValueError(
            f"realized_path : positions décroissantes {first_position} > "
            f"{second_position}."
        )
    interior = range(math.floor(first_position) + 1, math.ceil(second_position))
    return (
        raw_position_at(trace, first_position),
        *(
            (series.smoothed_latitude_deg[j], series.smoothed_longitude_deg[j])
            for j in interior
        ),
        raw_position_at(trace, second_position),
    )


def realized_length_m(path: Sequence[tuple[float, float]]) -> float:
    """Longueur du chemin réalisé (m) : somme des ``haversine_m`` entre points
    consécutifs (``0010`` D4.3)."""
    return math.fsum(haversine_m(*a, *b) for a, b in pairwise(path))


def _segment_distance_m(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> float:
    """Distance (m) d'un point à un segment du plan, paramètre borné à ``[0 ; 1]`` ;
    segment de longueur nulle : distance à son point."""
    (px_m, py_m), (ax_m, ay_m), (bx_m, by_m) = point, start, end
    ux_m, uy_m = bx_m - ax_m, by_m - ay_m
    squared_m2 = ux_m**2 + uy_m**2
    if squared_m2 == 0:
        return math.hypot(px_m - ax_m, py_m - ay_m)
    dot_m2 = (px_m - ax_m) * ux_m + (py_m - ay_m) * uy_m
    t = min(1.0, max(0.0, dot_m2 / squared_m2))
    return math.hypot(px_m - ax_m - t * ux_m, py_m - ay_m - t * uy_m)


def _h2_references(
    geometry: ReferenceGeometry, start_m: float, end_m: float
) -> list[tuple[float, float]]:
    """Points de référence de ``H_2`` : ``position_at(b_k)``, les sommets d'abscisse
    strictement intérieure, ``position_at(b_k + 10·n)`` tant que
    ``b_k + 10·n < b_{k+1}`` (produit calculé à chaque rang), puis
    ``position_at(b_{k+1})``."""
    references = [position_at(geometry, start_m)]
    references += [
        (geometry.latitude_deg[i], geometry.longitude_deg[i])
        for i, at_m in enumerate(geometry.distance_m)
        if start_m < at_m < end_m
    ]
    n = 1
    while start_m + H2_SPACING_M * n < end_m:
        references.append(position_at(geometry, start_m + H2_SPACING_M * n))
        n += 1
    references.append(position_at(geometry, end_m))
    return references


def interior_deviations(
    geometry: ReferenceGeometry,
    path: Sequence[tuple[float, float]],
    start_m: float,
    end_m: float,
    tolerance_m: float,
) -> tuple[float, float]:
    """``(H_1, H_2)`` en mètres, dans le plan de ``0008`` ancré en
    ``A = position_at(b_k)``, le début du segment (``0010`` D4.10 point 4, D4.3).

    ``H_1`` : plus grande distance d'un point **intérieur** du chemin (sans ses deux
    extrémités) à la polyligne restreinte à ``[b_k − ε ; b_{k+1} + ε]``, bornée à
    ``[0 ; L]`` par ``project_restricted`` ; 0 sans point intérieur. ``H_2`` : plus
    grande distance d'un point de référence aux **segments** du chemin.
    """
    anchor = position_at(geometry, start_m)
    h1_m = max(
        (
            project_restricted(
                geometry, lat, lon, start_m - tolerance_m, end_m + tolerance_m, anchor
            ).offset_m
            for lat, lon in path[1:-1]
        ),
        default=0.0,
    )
    edges = list(pairwise(to_local(*anchor, lat, lon) for lat, lon in path))
    h2_m = max(
        min(_segment_distance_m(to_local(*anchor, lat, lon), a, b) for a, b in edges)
        for lat, lon in _h2_references(geometry, start_m, end_m)
    )
    return h1_m, h2_m


# ---------------------------------------------------------------------------
# Observation d'un segment (0010 D4.9, D4.10, D6)
# ---------------------------------------------------------------------------


def observe_segment(
    geometry: ReferenceGeometry,
    profile: RouteProfile,
    trace: RecordedTrace,
    series: TraceSeries,
    start: ScorePointObservation,
    end: ScorePointObservation,
    tolerance_m: float,
) -> ScoreSegmentObservation:
    """Observation du segment entre les points ``start`` (``k``) et ``end``
    (``k + 1``), dans l'ordre de ``0010`` D4.10 :

    1. fractions et classe sur les bornes **effectives**, pour tout segment ;
    2. une borne ni ``found`` ni ``anchored`` : ``UNOBSERVED_BOUND`` ;
    3. un trou entre ``π_k`` et ``π_{k+1}`` (``gap_between``) : ``GAP`` ;
    4. sinon ``rho``, ``H_1`` et ``H_2`` sont calculés et publiés, puis
       ``LENGTH_RATIO`` si ``length_ratio_ok`` échoue, sinon ``INTERIOR_DEVIATION``
       si ``interior_ok(max(H_1, H_2), ε)`` échoue, sinon admis.

    Les instants et abscisses réalisées des bornes datées sont toujours publiés.
    """
    start_m, end_m = start.effective_m, end.effective_m
    length_m = end_m - start_m
    ascent_m, flat_m, descent_m = regime_lengths(profile, start_m, end_m)
    fractions = (ascent_m / length_m, flat_m / length_m, descent_m / length_m)
    exclusion: SegmentExclusion | None = None
    ratio: float | None = None
    h1_m: float | None = None
    h2_m: float | None = None
    first, second = start.position, end.position
    if not (start.dated and end.dated) or first is None or second is None:
        exclusion = SegmentExclusion.UNOBSERVED_BOUND
    elif gap_between(series, first, second):
        exclusion = SegmentExclusion.GAP
    else:
        path = realized_path(trace, series, first, second)
        ratio = realized_length_m(path) / length_m
        h1_m, h2_m = interior_deviations(geometry, path, start_m, end_m, tolerance_m)
        if not length_ratio_ok(ratio):
            exclusion = SegmentExclusion.LENGTH_RATIO
        elif not interior_ok(max(h1_m, h2_m), tolerance_m):
            exclusion = SegmentExclusion.INTERIOR_DEVIATION
    return ScoreSegmentObservation(
        index=start.index,
        nominal_start_m=start.nominal_m,
        nominal_end_m=end.nominal_m,
        start_m=start_m,
        end_m=end_m,
        ascent_fraction=fractions[0],
        flat_fraction=fractions[1],
        descent_fraction=fractions[2],
        regime_class=regime_class(*fractions),
        exclusion=exclusion,
        length_ratio=ratio,
        h1_m=h1_m,
        h2_m=h2_m,
        start_s=start.time_s,
        end_s=end.time_s,
        realized_start_m=start.realized_m,
        realized_end_m=end.realized_m,
    )


# ---------------------------------------------------------------------------
# Couverture et préfixe comparable (0010 D4.11, D4.2)
# ---------------------------------------------------------------------------


def last_passage(
    resolved_points: Sequence[ResolvedPoint], start_m: float, end_m: float
) -> str | None:
    """Nom du lieu résolu de plus grande abscisse dans ``[start_m ; end_m]``, bornes
    incluses, le dernier dans l'ordre du tuple à abscisse égale ; ``None`` s'il n'y en
    a pas — jamais un nom inventé (``0010`` D4.11)."""
    last: ResolvedPoint | None = None
    for resolved in resolved_points:
        inside = start_m <= resolved.distance_m <= end_m
        if inside and (last is None or resolved.distance_m >= last.distance_m):
            last = resolved
    return None if last is None else last.point.name


def comparable_prefix(segments: Sequence[ScoreSegmentObservation]) -> int:
    """``m``, nombre de segments admis consécutifs depuis le segment 0 (``0010``
    D4.11)."""
    m = 0
    while m < len(segments) and segments[m].admitted:
        m += 1
    return m


def _elapsed_s(
    segments: Sequence[ScoreSegmentObservation], exclusion: SegmentExclusion | None
) -> float:
    """Somme des ``t*_{k+1} − t*_k`` des segments d'un motif (``None`` = admis) ;
    ceux-ci sont datés par contrat."""
    return math.fsum(
        segment.end_s - segment.start_s
        for segment in segments
        if segment.exclusion is exclusion
        and segment.start_s is not None
        and segment.end_s is not None
    )


def observe_coverage(
    profile: RouteProfile,
    points: Sequence[ScorePointObservation],
    segments: Sequence[ScoreSegmentObservation],
) -> Coverage:
    """Couverture publiée d'une sortie (``0010`` D4.11, D4.2).

    Sommes ``math.fsum`` sur les segments : longueurs admises et exclues par motif,
    ``anchoring_excluded_m = b_0 + (L − b_K)`` ; longueurs de régime sur ``[0 ; L]``
    et dans les segments admis (``regime_lengths``) ; écoulés admis et exclus connus ;
    préfixe comparable ``m``, sa fin ``b_m`` et ``t*_m`` (point ``m``), et le dernier
    passage nommé de ``[b_0 ; b_m]``.
    """
    length_m = profile.distance_m[-1]

    def excluded_m(exclusion: SegmentExclusion | None) -> float:
        return math.fsum(s.length_m for s in segments if s.exclusion is exclusion)

    admitted = [
        regime_lengths(profile, s.start_m, s.end_m) for s in segments if s.admitted
    ]
    ascent_m, flat_m, descent_m = regime_lengths(profile, 0.0, length_m)
    m = comparable_prefix(segments)
    first, prefix_end = points[0], points[m]
    return Coverage(
        reference_length_m=length_m,
        admitted_m=excluded_m(None),
        excluded_unobserved_bound_m=excluded_m(SegmentExclusion.UNOBSERVED_BOUND),
        excluded_gap_m=excluded_m(SegmentExclusion.GAP),
        excluded_length_ratio_m=excluded_m(SegmentExclusion.LENGTH_RATIO),
        excluded_interior_deviation_m=excluded_m(SegmentExclusion.INTERIOR_DEVIATION),
        anchoring_excluded_m=first.effective_m + (length_m - points[-1].effective_m),
        ascent_length_m=ascent_m,
        flat_length_m=flat_m,
        descent_length_m=descent_m,
        admitted_ascent_m=math.fsum(lengths[0] for lengths in admitted),
        admitted_flat_m=math.fsum(lengths[1] for lengths in admitted),
        admitted_descent_m=math.fsum(lengths[2] for lengths in admitted),
        admitted_elapsed_s=_elapsed_s(segments, None),
        excluded_gap_s=_elapsed_s(segments, SegmentExclusion.GAP),
        excluded_length_ratio_s=_elapsed_s(segments, SegmentExclusion.LENGTH_RATIO),
        excluded_interior_deviation_s=_elapsed_s(
            segments, SegmentExclusion.INTERIOR_DEVIATION
        ),
        prefix_segment_count=m,
        prefix_end_m=prefix_end.effective_m,
        prefix_end_s=prefix_end.time_s,
        prefix_last_passage=last_passage(
            profile.resolved_points, first.effective_m, prefix_end.effective_m
        ),
    )


# ---------------------------------------------------------------------------
# Totaux du support admis et extrêmes (0010 D5.4)
# ---------------------------------------------------------------------------

_STATES = (IntervalState.MOVING, IntervalState.STOPPED, IntervalState.UNDETERMINED)


def admitted_totals(
    partition: ClockPartition, segments: Sequence[ScoreSegmentObservation]
) -> tuple[AdmittedTotals, ...]:
    """Les cinq totaux du support admis, dans l'ordre de ``CLOCK_CONVENTIONS``
    (``0010`` D5.4).

    Pour un segment admis et une convention, ses temps ``M``, ``S``, ``U`` sont les
    différences ``cumulative_s(…, t*_{k+1}) − cumulative_s(…, t*_k)`` (additivité de
    D5.3) ; les totaux en sont les sommes (``math.fsum``), et ``E_A`` la somme des
    ``t*_{k+1} − t*_k``. Cinq totaux nuls sans segment admis.
    """
    spans = [
        (segment.start_s, segment.end_s)
        for segment in segments
        if segment.admitted
        and segment.start_s is not None
        and segment.end_s is not None
    ]
    elapsed_s = _elapsed_s(segments, None)
    totals: list[AdmittedTotals] = []
    for k in range(len(CLOCK_CONVENTIONS)):
        moving_s, stopped_s, undetermined_s = (
            math.fsum(
                cumulative_s(partition, k, {state}, end_s)
                - cumulative_s(partition, k, {state}, start_s)
                for start_s, end_s in spans
            )
            for state in _STATES
        )
        totals.append(AdmittedTotals(elapsed_s, moving_s, stopped_s, undetermined_s))
    return tuple(totals)


def convention_extremes(totals: Sequence[AdmittedTotals]) -> tuple[int, int]:
    """``(θ_bas, θ_haut)`` (``0010`` D5.4) : **premier** indice du minimum de
    ``moving_s``, **premier** indice du maximum de ``moving_s + undetermined_s``.
    Jamais d'extrême segment par segment."""
    indices = range(len(totals))
    low = min(indices, key=lambda k: totals[k].moving_s)
    high = max(indices, key=lambda k: totals[k].moving_s + totals[k].undetermined_s)
    return low, high


def sensitivity_range_s(totals: Sequence[AdmittedTotals]) -> tuple[float, float]:
    """``I_sens,A = (min_θ M_{θ,A} ; E_A − min_θ S_{θ,A})`` (``0010`` D5.4) : l'écoulé
    du **support**, jamais celui de la trace."""
    elapsed_s = totals[0].elapsed_s
    return (
        min(t.moving_s for t in totals),
        elapsed_s - min(t.stopped_s for t in totals),
    )


# ---------------------------------------------------------------------------
# Fonction d'ensemble
# ---------------------------------------------------------------------------


def match_trace(
    geometry: ReferenceGeometry,
    profile: RouteProfile,
    trace: RecordedTrace,
    series: TraceSeries,
    partition: ClockPartition,
    parameters: ParameterSet,
) -> MatchResult:
    """Tout ce que l'appariement observe d'une sortie (``0010`` D4, D5.4, D6).

    ``match_points`` ; un ``observe_segment`` par couple de points consécutifs ;
    couverture et préfixe ; totaux de la trace et du support admis ; ``θ_bas``,
    ``θ_haut`` et ``I_sens,A`` s'il y a au moins un segment admis ;
    ``departure_delay_s = t*_0``.

    Préconditions (``ValueError``) : ``series`` et ``partition`` construits sur
    ``trace`` (mêmes nombres d'enregistrements) ; ``parameters`` déclaré par
    ``MATCHING_PARAMETER_SPECS`` ; ``profile`` et ``geometry`` issus de la même
    ``Route`` (``profile.distance_m[-1] == geometry.length_m`` bit pour bit).
    """
    records = len(trace.time_s)
    if len(series.realized_distance_m) != records or len(partition.time_s) != records:
        raise ValueError(
            "match_trace : séries, partition et trace de longueurs différentes "
            f"({len(series.realized_distance_m)}, {len(partition.time_s)}, "
            f"{records})."
        )
    if parameters.specs != MATCHING_PARAMETER_SPECS:
        raise ValueError(
            "match_trace : paramètres non déclarés par MATCHING_PARAMETER_SPECS."
        )
    if profile.distance_m[-1] != geometry.length_m:
        raise ValueError(
            "match_trace : profil et géométrie de tracés différents "
            f"({profile.distance_m[-1]} ≠ {geometry.length_m})."
        )
    points = match_points(geometry, trace, series, parameters)
    tolerance_m = parameters["lateral_tolerance_m"]
    segments = tuple(
        observe_segment(geometry, profile, trace, series, a, b, tolerance_m)
        for a, b in pairwise(points)
    )
    totals = admitted_totals(partition, segments)
    low: int | None = None
    high: int | None = None
    interval: tuple[float, float] | None = None
    if any(segment.admitted for segment in segments):
        low, high = convention_extremes(totals)
        interval = sensitivity_range_s(totals)
    return MatchResult(
        parameters=parameters,
        points=points,
        segments=segments,
        coverage=observe_coverage(profile, points, segments),
        departure_delay_s=points[0].time_s,
        trace_totals=trace_totals(partition),
        admitted_totals=totals,
        low_convention_index=low,
        high_convention_index=high,
        admitted_sensitivity_range_s=interval,
    )
