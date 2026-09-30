"""Scores de v0 brut sur une sortie : observation, prévisions, scores (M4b-2).

``0010`` D3, D4.2, D4.8, D4.11, D4.12, D5.3 à D5.5, D7. L'observation d'une sortie
(:func:`observe_outing`) ne dépend d'aucun modèle (D7.1 : le support est déterminé
par l'observation seule) ; les prévisions projettent un modèle dans les scénarios de
D3 ; les scores appellent les fonctions pures de M4b-1 sur les vecteurs assemblés.

**Une seule écriture de chaque temps observé** (brief M4b-2, § 3, choix 1) :
``clock_duration_s`` sous les onze horloges de ``CLOCKS``, dans leur ordre — de
``t*_k`` à ``t*_{k+1}`` pour un segment admis, de ``t*_0`` à l'instant pour un cumulé.

**Une entrée d'observation fausse lève ``ValueError`` ; une sortie de modèle fausse
est un statut** (choix 11) : jugée par les fonctions de M4b-1, jamais une exception.
"""

from mountain_perf.backtest.clocks import clock_duration_s
from mountain_perf.backtest.metrics import default_targets
from mountain_perf.schemas import (
    CLOCKS,
    AdmittedSegment,
    ClockPartition,
    MatchResult,
    ObservedPoint,
    OutingObservation,
    PassageMatchResult,
    PassageObservation,
    PassageRole,
    PassageStatus,
    PointStatus,
    ScorePointObservation,
    ScoreSegmentObservation,
    TargetMember,
    Unavailability,
)

# ---------------------------------------------------------------------------
# Observation d'une sortie (brief M4b-2, § 6.3)
# ---------------------------------------------------------------------------


def _clock_times(
    partition: ClockPartition, start_s: float, end_s: float
) -> tuple[float, ...]:
    """Le temps de ``[start_s ; end_s]`` sous les onze horloges, dans l'ordre de
    ``CLOCKS`` : la seule écriture d'un temps observé (``0010`` D5.3 ; choix 1)."""
    return tuple(clock_duration_s(partition, clock, start_s, end_s) for clock in CLOCKS)


def _present(value: float | None, what: str) -> float:
    """Une valeur que les contrats de M4a garantissent présente ; son absence est une
    entrée d'observation fausse (choix 11)."""
    if value is None:
        raise ValueError(f"observe_outing : {what} absent.")
    return value


def _admitted(
    partition: ClockPartition, segment: ScoreSegmentObservation
) -> AdmittedSegment:
    """Un segment admis, ses bornes recopiées, ses temps de ``t*_k`` à ``t*_{k+1}``
    (``0010`` D4.2, D5.3, D7.1)."""
    start_s = _present(segment.start_s, f"t*_{segment.index} d'un segment admis")
    end_s = _present(segment.end_s, f"t*_{segment.index + 1} d'un segment admis")
    return AdmittedSegment(
        segment.index,
        segment.nominal_start_m,
        segment.nominal_end_m,
        segment.start_m,
        segment.end_m,
        _present(segment.realized_start_m, "d_r d'un segment admis"),
        _present(segment.realized_end_m, "d_r d'un segment admis"),
        segment.regime_class,
        _clock_times(partition, start_s, end_s),
    )


def _cumulated(
    partition: ClockPartition, origin_s: float | None, at_s: float | None
) -> tuple[float, ...]:
    """``T_k`` : de ``t*_0`` à l'instant, sous les onze horloges (``0010`` D4.12,
    « temps observés ``T_k`` des métriques » ; choix 1 et 2)."""
    return _clock_times(
        partition, _present(origin_s, "t*_0"), _present(at_s, "instant observé")
    )


def _observed_place(
    partition: ClockPartition,
    origin_s: float | None,
    passage: PassageObservation,
    rank: int,
) -> ObservedPoint:
    """Un lieu, en ``s_w`` : ses temps au **départ** de son événement s'il est
    comparable, sinon son motif (``0010`` D4.12 ; choix 2 et 3, décision 3). La même
    écriture pour un point de ``C_k`` et pour un élément de ``K``."""
    if passage.comparable:
        return ObservedPoint(
            passage.point.distance_m,
            None,
            rank,
            None,
            _cumulated(partition, origin_s, passage.departure_s),
        )
    return ObservedPoint(
        passage.point.distance_m, None, rank, passage.unavailability, None
    )


def _score_point(
    partition: ClockPartition, origin_s: float | None, point: ScorePointObservation
) -> ObservedPoint:
    """Un point de score du préfixe, en ``b_k``, à ``t*_k`` (choix 2 et 3)."""
    return ObservedPoint(
        point.effective_m,
        point.index,
        None,
        None,
        _cumulated(partition, origin_s, point.time_s),
    )


def _error_points(
    match: MatchResult, passages: PassageMatchResult, partition: ClockPartition
) -> tuple[ObservedPoint, ...]:
    """Les points de ``C_k`` (``0010`` D4.11, D4.12, D7.3 ; décision 3) : les points
    de score ``1`` à ``m`` du préfixe (origine exclue), les lieux intermédiaires qui
    ne sont pas hors préfixe ; par abscisse, le point de score avant le lieu, puis les
    lieux dans l'ordre des passages (choix 6)."""
    points, origin_s = match.points, match.points[0].time_s
    keyed = [
        ((points[k].effective_m, 0, k), _score_point(partition, origin_s, points[k]))
        for k in range(1, match.coverage.prefix_segment_count + 1)
    ]
    keyed += [
        (
            (passage.point.distance_m, 1, rank),
            _observed_place(partition, origin_s, passage, rank),
        )
        for rank, passage in enumerate(passages.passages)
        if passage.role is PassageRole.INTERMEDIATE
        and passage.status is not PassageStatus.OUTSIDE_PREFIX
    ]
    return tuple(point for _, point in sorted(keyed, key=lambda item: item[0]))


def _target(
    match: MatchResult,
    passages: PassageMatchResult,
    partition: ClockPartition,
    member: TargetMember,
) -> ObservedPoint:
    """Un élément de ``K`` (``0010`` D4.8, D4.12, D7.4 ; décision 3) : un lieu
    intermédiaire comme au point de ``C_k`` ; l'arrivée en ``b_K`` à ``t*_K``,
    disponible si et seulement si le préfixe atteint l'arrivée (``m = K``), sinon
    ``support insuffisant``."""
    points, origin_s = match.points, match.points[0].time_s
    if not member.arrival:
        rank = member.occurrence_index
        if rank is None:
            raise ValueError("observe_outing : élément intermédiaire sans occurrence.")
        return _observed_place(partition, origin_s, passages.passages[rank], rank)
    final = points[-1]
    last = len(points) - 1
    if match.coverage.prefix_segment_count == last:
        return ObservedPoint(
            final.effective_m,
            last,
            member.occurrence_index,
            None,
            _cumulated(partition, origin_s, final.time_s),
        )
    return ObservedPoint(
        final.effective_m,
        last,
        member.occurrence_index,
        Unavailability.INSUFFICIENT_SUPPORT,
        None,
    )


def observe_outing(
    match: MatchResult, passages: PassageMatchResult, partition: ClockPartition
) -> OutingObservation:
    """Ce qu'une sortie observe, indépendamment de tout modèle (``0010`` D4.11,
    D4.12, D5.3, D5.4, D7.1, D7.3, D7.4 ; brief M4b-2, § 6.3).

    Les segments admis, dans l'ordre, leurs bornes recopiées du ``MatchResult`` et
    leur temps sous les onze horloges ; les points de ``C_k`` ; ``K`` par défaut
    (``default_targets``) et un élément observé par membre ; l'écart
    ``L − b_K = −anchoring_offset_m`` d'une arrivée ancrée, **même hors du préfixe**
    (choix 7). Les cumulés partent de l'origine ``(t*_0, b_0)``. Un départ non daté
    donne ``m = 0`` : aucun point, tous les lieux hors préfixe (M4a-3).

    ``match``, ``passages`` et ``partition`` viennent de la même chaîne de M4a
    (``match_trace``, ``observe_passages``, ``clock_partition``) ; une entrée
    incohérente lève ``ValueError`` ou ``ContractError``.
    """
    points = match.points
    origin, final = points[0], points[-1]
    members = default_targets([passage.role for passage in passages.passages])
    gap_m = None
    if final.status is PointStatus.ANCHORED:
        gap_m = 0.0 - final.anchoring_offset_m
    return OutingObservation(
        reference_length_m=match.coverage.reference_length_m,
        origin_m=origin.effective_m,
        origin_s=origin.time_s,
        segments=tuple(
            _admitted(partition, segment)
            for segment in match.segments
            if segment.admitted
        ),
        error_points=_error_points(match, passages, partition),
        members=members,
        targets=tuple(
            _target(match, passages, partition, member) for member in members
        ),
        arrival_anchor_gap_m=gap_m,
    )
