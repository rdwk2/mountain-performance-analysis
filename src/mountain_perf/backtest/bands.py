"""Fourchettes (``0010`` D11 et sa précision de M4d-2).

Pour une sortie scorée avec usage d'une performance ``j`` et chacun des cinq modèles du
rapport (``BAND_MODELS``), en usage et sous l'écoulé : le réservoir ``C_j`` et ses
membres (sorties contributrices, segments admis, support, ``T_c``), les résidus de jour
``Z_c = ln(T_c / P_c)`` (``P_c`` la projection de la source du modèle sur le support
admis du membre, calée par le calage du membre), leurs quantiles empiriques aux rangs
``⌈n q⌉``, les bornes ``P_k · exp(Q)`` de chaque élément du ``K`` par défaut de ``j``
(observé ou non), le score d'intervalle, la couverture, et les scores de la prévision
médiane.

Fonctions pures, sans lecture ni écriture : les documents ``OutingBands`` s'écrivent au
registre par ``just backtest`` (format 4).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date

from mountain_perf.backtest.calibration import calibrated_forecast, member_totals
from mountain_perf.backtest.metrics import is_invalid_model_output
from mountain_perf.backtest.scoring import clock_scores
from mountain_perf.schemas.bands import (
    BAND_LABEL,
    BAND_MODELS,
    BAND_PENALTY,
    BAND_QUANTILE_ORDERS,
    BandElement,
    BandQuantiles,
    ModelBand,
    OutingBands,
    ReservoirMember,
)
from mountain_perf.schemas.calibration import CalibratedPerformance, ModelKind
from mountain_perf.schemas.metrics import MetricValue
from mountain_perf.schemas.outing import Performance, Unavailability
from mountain_perf.schemas.scoring import (
    ModelForecast,
    OutingObservation,
    OutingScores,
    Scenario,
)

_ELAPSED = 0
"""Le rang de l'écoulé dans ``CLOCKS`` : les fourchettes ne se calculent que sous
l'écoulé (précision de D11)."""


# ---------------------------------------------------------------------------
# Rangs, quantiles, score d'intervalle
# ---------------------------------------------------------------------------


def quantile_rank(count: int, numerator: int, denominator: int) -> int:
    """Le rang ``⌈n·a/b⌉`` (à partir de 1) de la statistique d'ordre d'ordre ``a/b``
    parmi ``n`` valeurs, calculé en entiers : ``(n·a + b − 1) // b`` (précision de
    D11).

    Préconditions (``ValueError``), dans l'ordre : ``count >= 1`` ;
    ``0 < numerator <= denominator``.
    """
    if count < 1:
        raise ValueError(f"quantile_rank : n = {count} < 1.")
    if not 0 < numerator <= denominator:
        raise ValueError(
            f"quantile_rank : ordre {numerator}/{denominator} hors de ]0 ; 1]."
        )
    return (count * numerator + denominator - 1) // denominator


def band_quantiles(residuals: Sequence[float]) -> BandQuantiles:
    """Les quantiles empiriques des résidus disponibles (précision de D11) : dans une
    copie triée par valeur croissante, la valeur de rang ``⌈n·a/b⌉`` pour chaque
    ``(a, b)`` de ``BAND_QUANTILE_ORDERS`` — ``Q_0,1``, ``Q_0,5`` (inférieure centrale
    si ``n`` est pair), ``Q_2/3``, ``Q_0,9``. Les résidus reçus ne sont pas modifiés.

    Précondition (``ValueError``) : un résidu au moins.
    """
    if not residuals:
        raise ValueError("band_quantiles : aucun résidu.")
    ordered = sorted(residuals)
    count = len(ordered)
    low, median, prudent, high = (
        ordered[quantile_rank(count, a, b) - 1] for a, b in BAND_QUANTILE_ORDERS
    )
    return BandQuantiles(low, median, prudent, high)


def interval_score(lower_s: float, upper_s: float, observed_s: float) -> float:
    """Le score d'intervalle ``IS_k = (u − l) + 10 (l − T)₊ + 10 (T − u)₊`` (``0010``
    D11, ``2/alpha = 10``), sommé par ``fsum`` dans cet ordre : le contrat de
    ``BandElement`` le recalcule au bit."""
    return math.fsum(
        (
            upper_s - lower_s,
            BAND_PENALTY * max(lower_s - observed_s, 0.0),
            BAND_PENALTY * max(observed_s - upper_s, 0.0),
        )
    )


# ---------------------------------------------------------------------------
# Réservoir et résidus
# ---------------------------------------------------------------------------


def reservoir_member(
    day: date, outings: Sequence[OutingScores], window: tuple[date, date]
) -> ReservoirMember:
    """Le membre ``c`` du réservoir au jour ``day`` (précision de D11 ; totaux de la
    précision de D9.2), indépendant du modèle.

    ``outings`` : les scores **de v0 brut** des sorties scorées du membre, dans l'ordre
    de leur rang. Ses sorties contributrices sont celles qui ont l'usage ; ses segments,
    leurs segments admis ; son support, ``fsum(end_m − start_m)`` de ces segments ;
    ``T_c``, le total sous l'écoulé de ``member_totals``, ou son motif (``support
    insuffisant``, ``temps nul``). « Dans la fenêtre » : ``window[0] <= day <=
    window[1]``, bornes comprises (D2.2).
    """
    contributing = [outing for outing in outings if outing.usage is not None]
    segments = [
        segment for outing in contributing for segment in outing.observation.segments
    ]
    support_m = math.fsum(segment.end_m - segment.start_m for segment in segments)
    totals = member_totals(outings, Scenario.USAGE, _ELAPSED)
    observed_s: float | None = None
    unavailability: Unavailability | None = None
    if isinstance(totals, Unavailability):
        unavailability = totals
    else:
        observed_s = totals[0]
    first, last = window
    return ReservoirMember(
        civil_date=day,
        in_window=first <= day <= last,
        outing_count=len(contributing),
        segment_count=len(segments),
        support_m=support_m,
        observed_s=observed_s,
        unavailability=unavailability,
    )


def member_residual(
    model: ModelKind,
    member: ReservoirMember,
    outings: Sequence[OutingScores],
    calibrated: CalibratedPerformance | None,
) -> tuple[MetricValue, float | None]:
    """Le résidu ``(Z_c, P_c)`` d'un membre pour un modèle (précision de D11,
    « Résidus »), d'effectif le nombre de segments du membre.

    ``outings`` : les scores **non calés de la source du modèle** (v0 brut pour v0 brut
    et v0 + effort recalé ; la baseline pour une baseline) sur les sorties scorées du
    membre, dans l'ordre de leur rang ; ``calibrated`` : le calage **de la performance
    du membre** (inutile pour v0 brut). Dans l'ordre : membre indisponible, son motif ;
    une projection de la source absente ou invalide, ``erreur du modèle`` ; pour un
    modèle calé, le calage du membre en usage sous l'écoulé — ``non calé`` ou ``erreur
    du modèle`` donne ce statut, sinon ``P_c = P_c^src / effort`` ou ``P_c^src ·
    facteur`` ; ``P_c`` invalide, ``erreur du modèle`` ; sinon ``Z_c = ln(T_c / P_c)``,
    le logarithme du quotient flottant (comme les termes du ``β`` de D9.2).
    """
    count = member.segment_count
    if member.unavailability is not None:
        return MetricValue(None, member.unavailability, count), None
    totals = member_totals(outings, Scenario.USAGE, _ELAPSED)
    assert not isinstance(totals, Unavailability)  # le membre est disponible
    observed_s, source_s = totals
    if source_s is None:
        return MetricValue(None, Unavailability.MODEL_ERROR, count), None
    projected_s = source_s
    if model is not ModelKind.V0_RAW:
        assert calibrated is not None  # un modèle calé lit le calage du membre
        entry = next(
            (
                outing.usage
                for outing in calibrated.outings
                if outing.control.model is model and outing.usage is not None
            ),
            None,
        )
        assert entry is not None  # un membre disponible a une sortie avec usage
        calibration = entry.clocks[_ELAPSED].calibration
        if calibration.unavailability is not None:
            return MetricValue(None, calibration.unavailability, count), None
        if calibration.effort is not None:
            projected_s = source_s / calibration.effort
        else:
            assert calibration.factor is not None  # un calage disponible a son facteur
            projected_s = source_s * calibration.factor
    if is_invalid_model_output(projected_s):
        return MetricValue(None, Unavailability.MODEL_ERROR, count), None
    return MetricValue(math.log(observed_s / projected_s), None, count), projected_s


# ---------------------------------------------------------------------------
# Fourchette d'un modèle
# ---------------------------------------------------------------------------


def _without_bounds(
    model: ModelKind,
    residuals: tuple[MetricValue, ...],
    projected_s: tuple[float | None, ...],
    quantiles: BandQuantiles | None,
    status: Unavailability,
) -> ModelBand:
    """Une fourchette sans bornes : ni éléments, ni scores, ni couverture, ni
    médiane."""
    return ModelBand(
        model=model,
        residuals=residuals,
        projected_s=projected_s,
        quantiles=quantiles,
        elements=(),
        interval_score_s=None,
        normalised_score=None,
        coverage=None,
        all_covered=None,
        median_usage_target=None,
        median_max_abs_error_s=None,
        unavailability=status,
    )


def model_band(
    model: ModelKind,
    residuals: Sequence[tuple[MetricValue, float | None]],
    observation: OutingObservation,
    forecast: ModelForecast | Unavailability,
    base: ModelForecast,
    weights: Sequence[float] | None,
) -> ModelBand:
    """La fourchette d'un modèle pour une sortie (précision de D11, « Statut »,
    « Bornes », « Score d'intervalle et couverture », « Médiane »).

    ``residuals`` : un couple ``(Z_c, P_c)`` par membre de ``C_j``, dans l'ordre des
    membres ; ``observation`` : celle de la sortie ; ``forecast`` : la prévision d'usage
    du modèle calée à ``o_j`` (v0 brut : sa prévision), ou le statut du calage de
    ``j`` ; ``base`` : la prévision d'usage de v0 brut ; ``weights`` : les poids de
    D7.4, ceux du ``q_usage`` de v0 brut sous l'écoulé. Statuts, dans l'ordre : un
    résidu en ``erreur du modèle`` ; aucun résidu disponible, ``support insuffisant`` ;
    puis, quantiles publiés : la prévision de ``j`` indisponible ; des poids absents, un
    ``P_k`` ou un ``P⁰_k`` invalide, un ``exp(Q)`` qui déborde, une borne non finie ou
    ``<= 0``, ``erreur du modèle``. Sinon les bornes de chaque élément de ``K``
    (observé ou non), ``IS_k`` et « couvert » (jamais pour ``n = 1``), les agrégats
    (indisponibles au motif du premier élément non observé), et les scores de la
    prévision médiane — la prévision ``forecast`` multipliée par ``exp(Q_0,5)``, sous
    l'écoulé, base v0 brut.
    """
    values = tuple(residual for residual, _ in residuals)
    projected = tuple(p for _, p in residuals)
    if any(r.unavailability is Unavailability.MODEL_ERROR for r in values):
        return _without_bounds(
            model, values, projected, None, Unavailability.MODEL_ERROR
        )
    available = [r.value for r in values if r.value is not None]
    if not available:
        return _without_bounds(
            model, values, projected, None, Unavailability.INSUFFICIENT_SUPPORT
        )
    quantiles = band_quantiles(available)
    if isinstance(forecast, Unavailability):
        return _without_bounds(model, values, projected, quantiles, forecast)
    if (
        weights is None
        or any(is_invalid_model_output(p) for p in forecast.target_s)
        or any(is_invalid_model_output(p0) for p0 in base.target_s)
    ):
        return _without_bounds(
            model, values, projected, quantiles, Unavailability.MODEL_ERROR
        )
    targets = [p for p in forecast.target_s if p is not None]
    bases = [p0 for p0 in base.target_s if p0 is not None]
    try:
        factors = tuple(math.exp(q) for q in quantiles.values)
    except OverflowError:
        return _without_bounds(
            model, values, projected, quantiles, Unavailability.MODEL_ERROR
        )
    single = len(available) == 1
    elements: list[BandElement] = []
    for p, p0, w, target in zip(
        targets, bases, weights, observation.targets, strict=True
    ):
        bounds = tuple(p * f for f in factors)
        if any(not math.isfinite(b) or b <= 0 for b in bounds):
            return _without_bounds(
                model, values, projected, quantiles, Unavailability.MODEL_ERROR
            )
        lower, median, prudent, upper = bounds
        observed = None if target.times_s is None else target.times_s[_ELAPSED]
        score_s = None
        covered = None
        if observed is not None:
            score_s = interval_score(lower, upper, observed)
            if not single:
                covered = lower <= observed <= upper
        elements.append(
            BandElement(
                forecast_s=p,
                weight=w,
                base_s=p0,
                lower_s=lower,
                median_s=median,
                prudent_s=prudent,
                upper_s=upper,
                width_s=upper - lower,
                observed_s=observed,
                observation=target.unavailability,
                score_s=score_s,
                covered=covered,
            )
        )
    interval_score_s, normalised_score, coverage, all_covered = _aggregates(
        elements, single
    )
    median_usage_target, median_max_abs_error_s = _median_scores(
        observation, forecast, base, factors[1]
    )
    return ModelBand(
        model=model,
        residuals=values,
        projected_s=projected,
        quantiles=quantiles,
        elements=tuple(elements),
        interval_score_s=interval_score_s,
        normalised_score=normalised_score,
        coverage=coverage,
        all_covered=all_covered,
        median_usage_target=median_usage_target,
        median_max_abs_error_s=median_max_abs_error_s,
        unavailability=None,
    )


def _aggregates(
    elements: Sequence[BandElement], single: bool
) -> tuple[MetricValue, MetricValue, MetricValue | None, bool | None]:
    """``IS_j``, ``IS_j,norm``, la couverture (absente si ``n = 1``) et « tous
    couverts » (précision de D11) : indisponibles au motif du premier élément non
    observé, dans l'ordre de ``K``, d'effectif le nombre d'éléments observés ; sinon
    ``fsum(w_k IS_k)``, ``fsum(w_k IS_k / P⁰_k)`` et ``fsum(w_k, couverts)``, d'effectif
    ``|K|``."""
    missing = next((e for e in elements if e.observation is not None), None)
    if missing is not None:
        observed = sum(e.observation is None for e in elements)
        absent = MetricValue(None, missing.observation, observed)
        return absent, absent, None if single else absent, None
    count = len(elements)
    scores = [_score(e) for e in elements]
    interval = math.fsum(e.weight * s for e, s in zip(elements, scores, strict=True))
    normalised = math.fsum(
        e.weight * s / e.base_s for e, s in zip(elements, scores, strict=True)
    )
    interval_score_s = MetricValue(interval, None, count)
    normalised_score = MetricValue(normalised, None, count)
    if single:
        return interval_score_s, normalised_score, None, None
    coverage = math.fsum(e.weight for e in elements if e.covered)
    return (
        interval_score_s,
        normalised_score,
        MetricValue(coverage, None, count),
        all(e.covered for e in elements),
    )


def _score(element: BandElement) -> float:
    assert element.score_s is not None  # élément observé
    return element.score_s


def _median_scores(
    observation: OutingObservation,
    forecast: ModelForecast,
    base: ModelForecast,
    factor: float,
) -> tuple[MetricValue, MetricValue]:
    """Le ``q_usage`` et le ``max |C_k|`` de la prévision médiane (précision de D11,
    « Médiane ») : ``forecast`` dont chaque valeur (segments, points de D7.3, ``K``) est
    multipliée par ``exp(Q_0,5)`` — une valeur absente reste absente —, scorée sous
    l'écoulé avec la base v0 brut (D7.4, D7.3)."""

    def scaled(values: tuple[float | None, ...]) -> tuple[float | None, ...]:
        return tuple(None if p is None else p * factor for p in values)

    median = replace(
        forecast,
        segment_s=scaled(forecast.segment_s),
        point_s=scaled(forecast.point_s),
        target_s=scaled(forecast.target_s),
    )
    scores = clock_scores(observation, median, _ELAPSED, base=base)
    assert scores.usage_target is not None  # en usage
    assert scores.passage_errors is not None  # en usage
    return scores.usage_target.q_usage, scores.passage_errors.max_abs_error_s


# ---------------------------------------------------------------------------
# Document d'une sortie, fourchettes d'une exécution
# ---------------------------------------------------------------------------


def outing_bands(
    outing_id: str,
    performance: Performance,
    calibrated: CalibratedPerformance,
    members: Sequence[ReservoirMember],
    residuals: Mapping[ModelKind, Sequence[tuple[MetricValue, float | None]]],
    scores: Mapping[ModelKind, OutingScores],
    window: tuple[date, date],
) -> OutingBands:
    """Le document des fourchettes d'une sortie scorée avec usage (précision de D11 ;
    D14, format 4).

    ``performance`` : celle de la sortie ; ``calibrated`` : son calage ; ``members`` :
    le réservoir ``C_j`` ; ``residuals`` : les couples ``(Z_c, P_c)`` de chaque modèle,
    un par membre ; ``scores`` : les scores non calés de la sortie (v0 brut et les trois
    baselines) ; ``window`` : la fenêtre de la courbe. Base et poids : la prévision
    d'usage de v0 brut et les poids de son ``q_usage`` sous l'écoulé. Pour chaque modèle
    de ``BAND_MODELS`` : v0 brut, sa prévision ; un modèle calé, la prévision d'usage
    de sa source calée par le calage de ``j`` en usage sous l'écoulé, ou le statut de
    ce calage.

    Précondition (``ValueError``) : la sortie a l'usage de v0 brut.
    """
    raw = scores[ModelKind.V0_RAW]
    if raw.usage is None:
        raise ValueError(f"outing_bands : {outing_id} n'a pas d'usage.")
    base = raw.usage.forecast
    target = raw.usage.clocks[_ELAPSED].usage_target
    weights = None if target is None else target.weights
    bands: list[ModelBand] = []
    for model in BAND_MODELS:
        forecast: ModelForecast | Unavailability = base
        if model is not ModelKind.V0_RAW:
            entry = next(
                outing.usage
                for outing in calibrated.outings
                if outing.outing_id == outing_id and outing.control.model is model
            )
            assert entry is not None  # la sortie a l'usage
            calibration = entry.clocks[_ELAPSED].calibration
            if calibration.unavailability is not None:
                forecast = calibration.unavailability
            else:
                forecast = calibrated_forecast(entry.forecast, calibration)
        bands.append(
            model_band(
                model, residuals[model], raw.observation, forecast, base, weights
            )
        )
    first, last = window
    return OutingBands(
        outing_id=outing_id,
        window_from=first,
        window_to=last,
        label=BAND_LABEL,
        multi_outing=performance.is_multi_outing,
        members=tuple(members),
        models=tuple(bands),
    )


def _source(model: ModelKind) -> ModelKind:
    """Le modèle non calé dont un modèle reprend les projections : v0 brut pour
    v0 + effort recalé, le modèle lui-même sinon (D9.1)."""
    return ModelKind.V0_RAW if model is ModelKind.V0_RECALIBRATED else model


def evaluation_bands(
    performances: Sequence[Performance],
    scores: Mapping[str, Mapping[ModelKind, OutingScores]],
    calibration: Sequence[CalibratedPerformance],
    window: tuple[date, date],
) -> tuple[OutingBands, ...]:
    """Les fourchettes d'une exécution (précision de D11) : un document par sortie
    scorée avec usage, performance par performance, dans l'ordre de leurs sorties.

    ``scores[outing_id]`` : les scores non calés d'une sortie scorée (comme pour
    ``calibrate_performances``) ; ``calibration`` : le calage de chaque performance,
    dans l'ordre des performances ; ``window`` : le premier et le dernier jour de la
    fenêtre de la courbe. Pour chaque performance ``j`` : un membre par jour de
    ``C_j`` (``calibration[j].population.members``), sur les scores de v0 brut des
    sorties scorées de ce jour ; pour chaque modèle, les résidus sur les scores de sa
    source et le calage **de la performance du membre** ; puis les fourchettes de
    chaque sortie de ``j`` scorée et avec usage. Une sortie non scorée ou sans usage
    n'en a pas. Le calcul ne dépend que des arguments.

    Précondition (``ValueError``) : un calage par performance, de même jour, dans
    l'ordre.
    """
    if len(calibration) != len(performances) or any(
        calibrated.population.civil_date != performance.civil_date
        for performance, calibrated in zip(performances, calibration, strict=True)
    ):
        raise ValueError(
            "evaluation_bands : un calage par performance, dans l'ordre des "
            "performances."
        )
    by_day = {
        performance.civil_date: (performance, calibrated)
        for performance, calibrated in zip(performances, calibration, strict=True)
    }
    documents: list[OutingBands] = []
    for performance, calibrated in zip(performances, calibration, strict=True):
        members: list[ReservoirMember] = []
        residuals: dict[ModelKind, list[tuple[MetricValue, float | None]]] = {
            model: [] for model in BAND_MODELS
        }
        for day in calibrated.population.members:
            member_performance, member_calibration = by_day[day]
            scored = [
                outing.outing_id
                for outing in member_performance.outings
                if outing.outing_id in scores
            ]
            member = reservoir_member(
                day, [scores[i][ModelKind.V0_RAW] for i in scored], window
            )
            members.append(member)
            for model in BAND_MODELS:
                source = _source(model)
                residuals[model].append(
                    member_residual(
                        model,
                        member,
                        [scores[i][source] for i in scored],
                        member_calibration,
                    )
                )
        for outing in performance.outings:
            by_model = scores.get(outing.outing_id)
            if by_model is None or by_model[ModelKind.V0_RAW].usage is None:
                continue
            documents.append(
                outing_bands(
                    outing.outing_id,
                    performance,
                    calibrated,
                    members,
                    residuals,
                    by_model,
                    window,
                )
            )
    return tuple(documents)
