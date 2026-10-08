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

import math
from collections.abc import Sequence
from datetime import UTC, datetime

from mountain_perf.backtest.clocks import clock_duration_s
from mountain_perf.backtest.geometry import trace_route
from mountain_perf.backtest.metrics import (
    default_targets,
    is_invalid_model_output,
    log_ratio_envelope,
    passage_errors,
    positive_time_diagnostic,
    support_metrics,
    usage_target,
)
from mountain_perf.gpx import PROFILE_PARAMETER_SPECS, build_profile
from mountain_perf.model import (
    ENGINE_VERSION,
    PROJECTION_PARAMETER_SPECS,
    ProjectedTimeline,
    projected_timeline,
)
from mountain_perf.schemas import (
    CLOCKS,
    AdmittedSegment,
    Clock,
    ClockKind,
    ClockPartition,
    ClockScores,
    LogRatioEnvelope,
    MatchResult,
    ModelForecast,
    ObservedPoint,
    OutingObservation,
    OutingScores,
    PaceCurve,
    ParameterSet,
    PassageMatchResult,
    PassageObservation,
    PassageRole,
    PassageStatus,
    PointStatus,
    RecordedTrace,
    RegimeClass,
    RouteProfile,
    Scenario,
    ScenarioScores,
    ScorePointObservation,
    ScoreSegmentObservation,
    SourceRef,
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


# ---------------------------------------------------------------------------
# Prévisions (brief M4b-2, § 6.4)
# ---------------------------------------------------------------------------


def usage_forecast(
    observation: OutingObservation,
    timeline: ProjectedTimeline,
    *,
    source: SourceRef,
    curve_ref: str,
    parameters: ParameterSet,
    generated_at: datetime,
    engine_version: str = ENGINE_VERSION,
) -> ModelForecast:
    """La prévision d'usage : la chronologie du profil de **référence** (``0010`` D3 ;
    choix 3 et 4).

    ``p_i = P(b_{i+1}) − P(b_i)`` sur chaque segment admis ; ``P_k = P(x_k) − P(b_0)``
    en chaque point de ``C_k`` et chaque élément de ``K`` (``b_k``, ``s_w`` ou
    ``b_K``). Les champs de provenance sont publiés tels que reçus.

    Précondition : ``timeline.length_m == observation.reference_length_m``, sinon
    ``ValueError`` (une chronologie d'un autre tracé).
    """
    if timeline.length_m != observation.reference_length_m:
        raise ValueError(
            f"usage_forecast : la chronologie a la longueur {timeline.length_m}, "
            f"l'observation L = {observation.reference_length_m} : un autre tracé."
        )
    origin_s = timeline.time_at(observation.origin_m)
    return ModelForecast(
        scenario=Scenario.USAGE,
        source=source,
        curve_ref=curve_ref,
        parameters=parameters,
        engine_version=engine_version,
        generated_at=generated_at,
        segment_s=tuple(
            timeline.time_at(segment.end_m) - timeline.time_at(segment.start_m)
            for segment in observation.segments
        ),
        point_s=tuple(
            timeline.time_at(point.distance_m) - origin_s
            for point in observation.error_points
        ),
        target_s=tuple(
            timeline.time_at(target.distance_m) - origin_s
            for target in observation.targets
        ),
    )


def control_forecast(
    observation: OutingObservation,
    timeline: ProjectedTimeline,
    *,
    source: SourceRef,
    curve_ref: str,
    parameters: ParameterSet,
    generated_at: datetime,
    engine_version: str = ENGINE_VERSION,
) -> ModelForecast:
    """La prévision de contrôle : la chronologie du profil de la **trace** (``0010``
    D3, « correspondance » ; choix 4).

    ``p_i = P_c(d_r(π_{i+1})) − P_c(d_r(π_i))`` sur chaque segment admis ; ni point
    de ``C_k`` ni élément de ``K`` (``C_k`` et ``q_usage`` en usage seulement). Une
    abscisse réalisée hors de ``[0 ; L_c]`` lève ``ValueError`` (``time_at``).
    """
    return ModelForecast(
        scenario=Scenario.CONTROL,
        source=source,
        curve_ref=curve_ref,
        parameters=parameters,
        engine_version=engine_version,
        generated_at=generated_at,
        segment_s=tuple(
            timeline.time_at(segment.realized_end_m)
            - timeline.time_at(segment.realized_start_m)
            for segment in observation.segments
        ),
        point_s=(),
        target_s=(),
    )


# ---------------------------------------------------------------------------
# Scores (brief M4b-2, § 6.5)
# ---------------------------------------------------------------------------


def _require_forecast(
    observation: OutingObservation,
    forecast: ModelForecast,
    base: ModelForecast | None,
) -> None:
    """Préconditions de ``score_scenario`` (choix 11) : des longueurs qui ne sont pas
    celles de l'observation sont une erreur d'appel, jamais un statut."""
    if len(forecast.segment_s) != len(observation.segments):
        raise ValueError(
            f"score_scenario : {len(forecast.segment_s)} projections pour "
            f"{len(observation.segments)} segments admis."
        )
    if forecast.scenario is not Scenario.USAGE:
        return
    if len(forecast.point_s) != len(observation.error_points):
        raise ValueError(
            f"score_scenario : {len(forecast.point_s)} cumulés pour "
            f"{len(observation.error_points)} points de C_k."
        )
    if len(forecast.target_s) != len(observation.targets):
        raise ValueError(
            f"score_scenario : {len(forecast.target_s)} cumulés pour "
            f"{len(observation.targets)} éléments de K."
        )
    if base is None:
        return
    if base.scenario is not Scenario.USAGE:
        raise ValueError(
            "score_scenario : la base de q_usage est une prévision d'usage, reçu "
            f"{base.scenario}."
        )
    if len(base.target_s) != len(observation.targets):
        raise ValueError(
            f"score_scenario : la base a {len(base.target_s)} cumulés pour "
            f"{len(observation.targets)} éléments de K."
        )


def _observed_times(
    points: Sequence[ObservedPoint], clock_index: int
) -> tuple[float | None, ...]:
    """``T_k`` sous une horloge, ``None`` pour un point indisponible."""
    return tuple(
        None if point.times_s is None else point.times_s[clock_index]
        for point in points
    )


def _projected_total(
    projected_s: Sequence[float | None], members: Sequence[int]
) -> float | None:
    """``P`` d'un sous-ensemble : ``fsum`` de ses ``p_i`` ; absent si **un** ``p_i``
    du support est invalide — l'erreur du modèle vaut pour la performance (``0010``
    D7.1 ; choix 9)."""
    outputs: list[float] = []
    for projected in projected_s:
        if projected is None or is_invalid_model_output(projected):
            return None
        outputs.append(projected)
    return math.fsum(outputs[i] for i in members)


def _envelope(
    projected_s: Sequence[float | None],
    segments: Sequence[AdmittedSegment],
    members: Sequence[int],
) -> LogRatioEnvelope | None:
    """L'enveloppe d'un sous-ensemble (``0010`` D5.4 ; choix 9) : ``a`` et ``b`` le
    minimum et le maximum des **dix** sommes ``fsum`` de ses temps sous les horloges
    ``M_θ`` et ``M_θ + U_θ`` ; aucune pour un sous-ensemble vide."""
    if not members:
        return None
    sums = [
        math.fsum(segments[i].times_s[k] for i in members)
        for k, clock in enumerate(CLOCKS)
        if clock.kind is not ClockKind.ELAPSED
    ]
    return log_ratio_envelope(
        _projected_total(projected_s, members), min(sums), max(sums)
    )


def _clock_scores(
    observation: OutingObservation,
    forecast: ModelForecast,
    base: ModelForecast | None,
    clock_index: int,
) -> ClockScores:
    """Les scores d'une prévision sous la seule horloge ``CLOCKS[clock_index]`` : le
    corps de la boucle de :func:`score_scenario`, inchangé (brief M4c-1, § 6.3).
    Préconditions vérifiées par l'appelant."""
    i, clock = clock_index, CLOCKS[clock_index]
    usage = forecast.scenario is Scenario.USAGE
    base_s = (forecast if base is None else base).target_s
    segments = observation.segments
    classes = tuple(segment.regime_class for segment in segments)
    point_motifs = tuple(point.unavailability for point in observation.error_points)
    target_motifs = tuple(target.unavailability for target in observation.targets)
    observed_s = tuple(segment.times_s[i] for segment in segments)
    support = support_metrics(forecast.segment_s, observed_s, classes)
    diagnostic = None
    if support.dispersion.unavailability is Unavailability.ZERO_TIME:
        diagnostic = positive_time_diagnostic(forecast.segment_s, observed_s, classes)
    errors, target = None, None
    if usage:
        errors = passage_errors(
            forecast.point_s,
            _observed_times(observation.error_points, i),
            point_motifs,
        )
        target = usage_target(
            forecast.target_s,
            base_s,
            _observed_times(observation.targets, i),
            target_motifs,
            arrival_anchor_gap_m=observation.arrival_anchor_gap_m,
        )
    return ClockScores(clock, support, diagnostic, errors, target)


def clock_scores(
    observation: OutingObservation,
    forecast: ModelForecast,
    clock_index: int,
    *,
    base: ModelForecast | None = None,
) -> ClockScores:
    """Les scores d'une prévision sous la seule horloge ``CLOCKS[clock_index]``,
    identiques au bit à ``score_scenario(observation, forecast, base=base)
    .clocks[clock_index]`` (brief M4c-1, § 6.3). Elle sert le calage (``0010`` D9.2),
    dont la prévision change d'une horloge à l'autre.

    Préconditions (``ValueError``) : celles de :func:`score_scenario`, vérifiées
    d'abord, puis ``0 <= clock_index < len(CLOCKS)``.
    """
    _require_forecast(observation, forecast, base)
    if not 0 <= clock_index < len(CLOCKS):
        raise ValueError(
            f"clock_scores : clock_index {clock_index} hors de [0 ; {len(CLOCKS)}[."
        )
    return _clock_scores(observation, forecast, base, clock_index)


def score_scenario(
    observation: OutingObservation,
    forecast: ModelForecast,
    *,
    base: ModelForecast | None = None,
) -> ScenarioScores:
    """Les scores d'une prévision sous les onze horloges, et ses enveloppes (``0010``
    D5.4, D5.5, D7 ; brief M4b-2, § 6.5).

    Sous chaque horloge de ``CLOCKS``, avec ``t`` les temps des segments admis et
    leurs classes (celles de la référence, D3) : ``support_metrics`` ; le diagnostic
    de D5.5 si et seulement si le motif vectoriel du support est ``zero_time``
    (choix 8) ; en usage, ``passage_errors`` sur les points de ``C_k`` et
    ``usage_target`` sur ``K``, de base ``base`` — la prévision elle-même si elle est
    absente (choix 10). Puis l'enveloppe du support et celle de chaque classe
    (choix 9).

    Préconditions (``ValueError``) : ``len(segment_s) == len(segments)`` ; en usage,
    ``len(point_s) == len(error_points)``, ``len(target_s) == len(targets)``, et une
    ``base`` présente est une prévision d'usage à ``len(targets)`` cumulés. Une
    sortie de modèle invalide reste un statut, jugé par les fonctions de M4b-1 (D7.1).
    """
    _require_forecast(observation, forecast, base)
    segments = observation.segments
    classes = tuple(segment.regime_class for segment in segments)
    clocks = [_clock_scores(observation, forecast, base, i) for i in range(len(CLOCKS))]
    return ScenarioScores(
        scenario=forecast.scenario,
        forecast=forecast,
        envelope=_envelope(forecast.segment_s, segments, range(len(segments))),
        class_envelopes=tuple(
            _envelope(
                forecast.segment_s,
                segments,
                [i for i, regime in enumerate(classes) if regime is regime_class],
            )
            for regime_class in RegimeClass
        ),
        clocks=tuple(clocks),
    )


def score_outing(
    observation: OutingObservation,
    control: ScenarioScores,
    usage: ScenarioScores | None = None,
) -> OutingScores:
    """Les scores d'une sortie : le contrat, sans calcul (``0010`` D3)."""
    return OutingScores(observation, control, usage)


# ---------------------------------------------------------------------------
# Horloges du rapport et assemblage de v0 (brief M4b-2, § 6.6)
# ---------------------------------------------------------------------------


def report_clocks(match: MatchResult) -> tuple[Clock, ...]:
    """Les horloges du rapport (``0010`` D5.4 ; choix 12) : l'écoulé, ``M`` sous
    ``θ_bas`` et ``M + U`` sous ``θ_haut``, lus dans le ``MatchResult`` ; l'écoulé
    seul si aucun segment n'est admis. Aucun extrême segment par segment."""
    low, high = match.low_convention_index, match.high_convention_index
    if low is None or high is None:
        return (CLOCKS[0],)
    return (
        CLOCKS[0],
        Clock(ClockKind.MOVING, low),
        Clock(ClockKind.MOVING_OR_UNDETERMINED, high),
    )


def realized_profile(trace: RecordedTrace) -> RouteProfile:
    """Le profil de la trace réalisée, celui du scénario contrôle (``0010`` D3 ; brief
    M4b-2, choix 4 ; brief M4c-1, § 6.3) : ``trace_route`` puis ``build_profile`` aux
    défauts de ``0008``. Commun à v0 brut et aux baselines."""
    return build_profile(
        trace_route(trace, trace.sources[0].identifier),
        ParameterSet(PROFILE_PARAMETER_SPECS),
    )


def v0_scores(
    reference: RouteProfile | None,
    trace: RecordedTrace,
    match: MatchResult,
    passages: PassageMatchResult,
    partition: ClockPartition,
    curve: PaceCurve,
    *,
    curve_ref: str,
    generated_at: datetime | None = None,
) -> OutingScores:
    """Les scores de **v0 brut** sur une sortie (``0010`` D3, D9.1 effort 1 ; brief
    M4b-2, § 6.6).

    v0 aux paramètres par défaut (``PROJECTION_PARAMETER_SPECS``, choix 5) ; contrôle
    sur le profil de la trace (``trace_route`` puis ``build_profile`` aux défauts de
    ``0008``, choix 4) ; usage sur ``reference`` si elle est présente — absente, la
    sortie n'a pas de scénario d'usage (sortie sans référence, D3). ``generated_at``
    absent : maintenant, en UTC.
    """
    at = datetime.now(UTC) if generated_at is None else generated_at
    parameters = ParameterSet(PROJECTION_PARAMETER_SPECS)
    observation = observe_outing(match, passages, partition)
    realized = realized_profile(trace)
    control = control_forecast(
        observation,
        projected_timeline(realized, curve, parameters),
        source=realized.source,
        curve_ref=curve_ref,
        parameters=parameters,
        generated_at=at,
    )
    usage = None
    if reference is not None:
        usage = usage_forecast(
            observation,
            projected_timeline(reference, curve, parameters),
            source=reference.source,
            curve_ref=curve_ref,
            parameters=parameters,
            generated_at=at,
        )
    return score_outing(
        observation,
        score_scenario(observation, control),
        None if usage is None else score_scenario(observation, usage),
    )
