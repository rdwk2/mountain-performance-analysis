"""Le calage des modèles de référence : baselines, population ``C_j``, ``β``,
prévisions et scores calés (M4c-1).

``0010`` D9 (et ses précisions de M4c-1), D2.4, D2.5, D3, D7.1, D7.4. Pour la
performance évaluée ``j`` et chaque modèle calé, un seul paramètre d'échelle ``β``
(D9.2), appris sur les entraînements terminés avant l'origine ``o_j`` de ``j``, dans la
même horloge et le même scénario que le score évalué. La prévision calée est la
prévision non calée multipliée par ``exp(β)`` (baseline), ou divisée par l'effort borné
(v0) ; elle se refait depuis le calage, qui ne la porte pas (décision 2 du brief
M4c-1).

Le calage n'utilise que des totaux du support admis déjà observés : **il ne relit
aucune trace**, et aucune fonction de ce module ne lit ni n'écrit de fichier. Une
sortie de modèle invalide est un statut (``erreur du modèle``), jamais une exception ni
un retrait (D7.1, D9.2) ; une entrée d'appel incohérente lève ``ValueError``.
"""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime

from mountain_perf.backtest.calendar import available_at_origin, origin
from mountain_perf.backtest.metrics import is_invalid_model_output
from mountain_perf.backtest.scoring import (
    clock_scores,
    control_forecast,
    score_outing,
    score_scenario,
    usage_forecast,
)
from mountain_perf.model.baselines import (
    BASELINE_VERSION,
    BASELINES,
    baseline_timeline,
)
from mountain_perf.schemas import (
    CALIBRATED_MODELS,
    CLOCKS,
    EFFORT_BOUNDS,
    CalibratedClockScores,
    CalibratedOutingScores,
    CalibratedPerformance,
    CalibratedScenarioScores,
    CalibrationPopulation,
    CalibrationWithdrawal,
    ModelCalibration,
    ModelForecast,
    ModelKind,
    OutingLabel,
    OutingObservation,
    OutingScores,
    ParameterSet,
    Performance,
    PopulationExclusion,
    PopulationExclusionReason,
    RouteProfile,
    Scenario,
    Unavailability,
)

BASELINE_CURVE_REF = "aucune courbe"
"""Le ``curve_ref`` des prévisions d'une baseline : elle ne lit pas la courbe
(décision 7 du brief M4c-1)."""

_UNSCALED: tuple[ModelKind, ...] = (ModelKind.V0_RAW, *BASELINES)
"""Les quatre modèles non calés d'une sortie scorée : v0 brut et les baselines."""


# ---------------------------------------------------------------------------
# Scores non calés d'une baseline (brief M4c-1, § 6.4)
# ---------------------------------------------------------------------------


def _baseline_forecast(
    observation: OutingObservation,
    profile: RouteProfile,
    baseline: ModelKind,
    scenario: Scenario,
    generated_at: datetime,
) -> ModelForecast:
    """La prévision d'une baseline dans un scénario ; sans chronologie (décision 6),
    une prévision de même provenance sans aucune valeur."""
    timeline = baseline_timeline(profile, baseline)
    parameters = ParameterSet(())
    if timeline is not None:
        project = usage_forecast if scenario is Scenario.USAGE else control_forecast
        return project(
            observation,
            timeline,
            source=profile.source,
            curve_ref=BASELINE_CURVE_REF,
            parameters=parameters,
            generated_at=generated_at,
            engine_version=BASELINE_VERSION,
        )
    usage = scenario is Scenario.USAGE
    return ModelForecast(
        scenario=scenario,
        source=profile.source,
        curve_ref=BASELINE_CURVE_REF,
        parameters=parameters,
        engine_version=BASELINE_VERSION,
        generated_at=generated_at,
        segment_s=(None,) * len(observation.segments),
        point_s=(None,) * len(observation.error_points) if usage else (),
        target_s=(None,) * len(observation.targets) if usage else (),
    )


def baseline_scores(
    observation: OutingObservation,
    reference: RouteProfile | None,
    realized: RouteProfile,
    baseline: ModelKind,
    *,
    base: ModelForecast | None = None,
    generated_at: datetime | None = None,
) -> OutingScores:
    """Les scores **non calés** d'une baseline sur une sortie, par la chaîne de v0
    brut (``0010`` D9.1 et sa précision, D3).

    Contrôle sur ``realized``, le profil de la trace ; usage sur ``reference`` si elle
    est présente. Provenance : ``engine_version`` ``BASELINE_VERSION``, aucun paramètre,
    ``curve_ref`` ``BASELINE_CURVE_REF`` (décision 7). Une baseline sans chronologie
    sur un profil (une allure non finie, décision 6) y a une prévision sans aucune
    valeur : ``erreur du modèle`` sous toute horloge où le support admis n'est pas
    vide, par les fonctions de M4b-1 (D7.1). ``base`` ne sert qu'à l'usage : la
    prévision d'usage de v0 brut, dénominateur de ``q_usage`` au rapport (D7.4 ;
    décision 13) ; absente, la prévision elle-même. ``generated_at`` absent :
    maintenant, en UTC.

    Précondition (``ValueError``) : ``baseline`` est l'une de ``BASELINES``.
    """
    if baseline not in BASELINES:
        raise ValueError(f"baseline_scores : {baseline} n'est pas une baseline (D9.1).")
    at = datetime.now(UTC) if generated_at is None else generated_at
    control = _baseline_forecast(observation, realized, baseline, Scenario.CONTROL, at)
    usage = None
    if reference is not None:
        usage = _baseline_forecast(observation, reference, baseline, Scenario.USAGE, at)
    return score_outing(
        observation,
        score_scenario(observation, control),
        None if usage is None else score_scenario(observation, usage, base=base),
    )


# ---------------------------------------------------------------------------
# Population C_j (brief M4c-1, § 6.4 ; D2.4, D2.5)
# ---------------------------------------------------------------------------


def calibration_population(
    performance: Performance, performances: Sequence[Performance]
) -> CalibrationPopulation:
    """``C_j`` de ``performance`` (``0010`` D2.4, D2.5 et la précision de D2.4).

    Candidates : les performances de ``performances`` dont l'instant de fin le plus
    tardif des sorties (``end_time``) est strictement antérieur à ``o_j`` ; membres,
    celles dont toutes les sorties sont étiquetées entraînement (``all_training``) ;
    exclues, les autres candidates, motif « course » si l'une de leurs sorties est une
    course, sinon « étiquette manquante ». Dans l'ordre des jours : le résultat ne
    dépend pas de l'ordre reçu. Le jour évalué n'entre jamais dans son propre calage
    (D9.2) : il ne finit jamais avant sa propre origine.

    Précondition (``ValueError``) : des jours distincts dans ``performances``.
    """
    days = [candidate.civil_date for candidate in performances]
    if len(set(days)) != len(days):
        raise ValueError("calibration_population : deux performances du même jour.")
    o_j = origin(performance.civil_date)
    members: list[date] = []
    excluded: list[PopulationExclusion] = []
    for candidate in sorted(performances, key=lambda p: p.civil_date):
        if not available_at_origin(candidate.end_time, o_j):
            continue
        if candidate.all_training:
            members.append(candidate.civil_date)
        elif any(outing.label is OutingLabel.RACE for outing in candidate.outings):
            excluded.append(
                PopulationExclusion(
                    candidate.civil_date, PopulationExclusionReason.RACE
                )
            )
        else:
            excluded.append(
                PopulationExclusion(
                    candidate.civil_date, PopulationExclusionReason.UNLABELLED
                )
            )
    return CalibrationPopulation(
        performance.civil_date, o_j, tuple(members), tuple(excluded)
    )


# ---------------------------------------------------------------------------
# Calage (brief M4c-1, § 6.4 ; D9.2)
# ---------------------------------------------------------------------------


def _member_totals(
    outings: Sequence[OutingScores], scenario: Scenario, clock_index: int
) -> Unavailability | tuple[float, float | None]:
    """Les totaux d'un membre (précision de D9.2 ; décisions 10 et 11) : ``T_c`` et
    ``P_c`` sommés par ``fsum`` sur les segments admis de toutes ses sorties scorées,
    dans l'ordre reçu ; une sortie sans ce scénario ne contribue rien. Dans l'ordre :
    support vide, motif ``INSUFFICIENT_SUPPORT`` ; ``T_c`` nul, motif ``ZERO_TIME`` ;
    une projection invalide, ``(T_c, None)`` ; sinon ``(T_c, P_c)``."""
    times: list[float] = []
    projections: list[float | None] = []
    for outing in outings:
        scores = outing.usage if scenario is Scenario.USAGE else outing.control
        if scores is None:
            continue
        for segment, projected in zip(
            outing.observation.segments, scores.forecast.segment_s, strict=True
        ):
            times.append(segment.times_s[clock_index])
            projections.append(projected)
    if not times:
        return Unavailability.INSUFFICIENT_SUPPORT
    t_total = math.fsum(times)
    if not t_total > 0:
        return Unavailability.ZERO_TIME
    valid: list[float] = []
    for projected in projections:
        if projected is None or is_invalid_model_output(projected):
            return t_total, None
        valid.append(projected)
    return t_total, math.fsum(valid)


def calibrate(
    population: CalibrationPopulation,
    model: ModelKind,
    scenario: Scenario,
    clock_index: int,
    members: Mapping[date, Sequence[OutingScores]],
) -> ModelCalibration:
    """Le calage d'un modèle pour une performance, dans un scénario et sous l'horloge
    ``CLOCKS[clock_index]`` (``0010`` D9.2 et sa précision ; décisions 10 à 12).

    ``members[c]`` : les scores **non calés** du modèle (v0 brut pour v0 + effort
    recalé) sur les sorties scorées du membre ``c``, dans l'ordre de leur rang. Pour
    chaque membre, dans l'ordre de ``population.members`` : support vide, retrait
    ``insufficient_support`` ; ``T_c`` nul, retrait ``zero_time`` ; sinon il est dans
    la population effective, et une projection invalide rend le calage ``erreur du
    modèle`` (l'observation passe avant le modèle, D7.1). Population effective vide :
    ``non calé``. Sinon ``β = fsum(ln(T_c / P_c)) / |C_j^eff|`` ; v0 : effort
    ``min(max(exp(−β), 0,5), 1,5)``, facteur ``1 / effort``, saturé si et seulement si
    ``exp(−β)`` est hors de ``[0,5 ; 1,5]`` ; baseline : facteur ``exp(β)``.

    Préconditions (``ValueError``) : ``model`` dans ``CALIBRATED_MODELS`` ;
    ``0 <= clock_index < len(CLOCKS)`` ; une entrée de ``members`` pour chaque membre.

    Non promis : hors du domaine des métriques de M4b-1 (temps et projections dans
    ``[1e−6 ; 1e12]``, décision 14), un rapport ``T_c / P_c`` peut sous-dépasser ou
    déborder, et ``fsum`` lever ``OverflowError``, au lieu d'un statut.
    """
    if model not in CALIBRATED_MODELS:
        raise ValueError(f"calibrate : {model} n'est pas un modèle calé (D9.1).")
    if not 0 <= clock_index < len(CLOCKS):
        raise ValueError(
            f"calibrate : clock_index {clock_index} hors de [0 ; {len(CLOCKS)}[."
        )
    missing = [day for day in population.members if day not in members]
    if missing:
        listed = ", ".join(day.isoformat() for day in missing)
        raise ValueError(f"calibrate : aucune entrée pour les membres [{listed}].")
    effective: list[date] = []
    withdrawals: list[CalibrationWithdrawal] = []
    logs: list[float] = []
    model_error = False
    for day in population.members:
        totals = _member_totals(members[day], scenario, clock_index)
        if isinstance(totals, Unavailability):
            withdrawals.append(CalibrationWithdrawal(day, totals))
            continue
        effective.append(day)
        t_total, p_total = totals
        if p_total is None:
            model_error = True
        else:
            logs.append(math.log(t_total / p_total))
    unavailability = None
    if not effective:
        unavailability = Unavailability.NOT_CALIBRATED
    elif model_error:
        unavailability = Unavailability.MODEL_ERROR
    beta = effort = factor = None
    saturated = False
    if unavailability is None:
        beta = math.fsum(logs) / len(logs)
        if model is ModelKind.V0_RECALIBRATED:
            low, high = EFFORT_BOUNDS
            unbounded = math.exp(-beta)
            effort = min(max(unbounded, low), high)
            factor = 1.0 / effort
            saturated = not low <= unbounded <= high
        else:
            factor = math.exp(beta)
    return ModelCalibration(
        model=model,
        scenario=scenario,
        clock=CLOCKS[clock_index],
        population=tuple(effective),
        withdrawals=tuple(withdrawals),
        beta=beta,
        effort=effort,
        factor=factor,
        saturated=saturated,
        unavailability=unavailability,
    )


# ---------------------------------------------------------------------------
# Prévision et scores calés (brief M4c-1, § 6.4 ; D9.2, D7.4)
# ---------------------------------------------------------------------------


def calibrated_forecast(
    forecast: ModelForecast, calibration: ModelCalibration
) -> ModelForecast:
    """La prévision calée (``0010`` D9.2 et sa précision ; décision 2) : chaque valeur
    de ``segment_s``, ``point_s`` et ``target_s`` divisée par l'effort (v0, ``p /
    effort``, jamais ``p · factor``) ou multipliée par le facteur (baseline) ; une
    valeur absente reste absente. La provenance est recopiée telle quelle : l'effort et
    le facteur sont dans le calage, pas dans ``parameters``.

    Préconditions (``ValueError``) : le modèle est calé ; même scénario.
    """
    effort, factor = calibration.effort, calibration.factor
    if calibration.unavailability is not None or factor is None:
        raise ValueError(
            f"calibrated_forecast : modèle non calé ({calibration.unavailability})."
        )
    if calibration.scenario is not forecast.scenario:
        raise ValueError(
            f"calibrated_forecast : prévision {forecast.scenario}, calage "
            f"{calibration.scenario}."
        )
    scale: Callable[[float], float]
    if effort is not None:

        def scale(p: float) -> float:
            return p / effort

    else:

        def scale(p: float) -> float:
            return p * factor

    def scaled(values: tuple[float | None, ...]) -> tuple[float | None, ...]:
        return tuple(None if p is None else scale(p) for p in values)

    return replace(
        forecast,
        segment_s=scaled(forecast.segment_s),
        point_s=scaled(forecast.point_s),
        target_s=scaled(forecast.target_s),
    )


def calibrated_scores(
    observation: OutingObservation,
    forecast: ModelForecast,
    calibrations: Sequence[ModelCalibration],
    *,
    base: ModelForecast | None = None,
) -> CalibratedScenarioScores:
    """Les scores calés d'un modèle sur une sortie, dans un scénario (``0010`` D9.2,
    D7 ; décisions 8 et 13) : sous chaque horloge calée, les scores
    (``clock_scores``) de la prévision calée de ce calage ; pas de scores sous une
    horloge non calée ou en erreur. ``forecast`` est la prévision **non calée** ;
    ``base``, en usage, la prévision d'usage de v0 brut (dénominateur de ``q_usage``,
    D7.4). Aucune enveloppe (D5.4 ; décision 8).

    Préconditions (``ValueError``) : les horloges des calages sont ``CLOCKS``, dans
    l'ordre ; un seul modèle ; puis, calage par calage, le scénario de ``forecast``,
    et les préconditions de ``clock_scores``.
    """
    if tuple(calibration.clock for calibration in calibrations) != CLOCKS:
        raise ValueError("calibrated_scores : onze calages, dans l'ordre de CLOCKS.")
    models = sorted({calibration.model for calibration in calibrations})
    if len(models) > 1:
        raise ValueError(
            f"calibrated_scores : plusieurs modèles [{', '.join(models)}]."
        )
    entries: list[CalibratedClockScores] = []
    for i, calibration in enumerate(calibrations):
        if calibration.scenario is not forecast.scenario:
            raise ValueError(
                f"calibrated_scores : calage {calibration.scenario}, prévision "
                f"{forecast.scenario}."
            )
        scores = None
        if calibration.unavailability is None:
            scores = clock_scores(
                observation, calibrated_forecast(forecast, calibration), i, base=base
            )
        entries.append(CalibratedClockScores(calibration, scores))
    return CalibratedScenarioScores(
        calibrations[0].model, forecast.scenario, forecast, tuple(entries)
    )


# ---------------------------------------------------------------------------
# Assemblage (brief M4c-1, § 6.4)
# ---------------------------------------------------------------------------


def _source(model: ModelKind) -> ModelKind:
    """Le modèle non calé dont un modèle calé reprend les scores : v0 brut pour
    v0 + effort recalé, la baseline elle-même sinon (D9.1)."""
    return ModelKind.V0_RAW if model is ModelKind.V0_RECALIBRATED else model


def _cached(
    cache: dict[tuple[ModelKind, Scenario], tuple[ModelCalibration, ...]],
    population: CalibrationPopulation,
    model: ModelKind,
    scenario: Scenario,
    by_day: Mapping[date, Performance],
    scores: Mapping[str, Mapping[ModelKind, OutingScores]],
) -> tuple[ModelCalibration, ...]:
    """Les onze calages d'un modèle dans un scénario pour une performance, calculés
    une fois (``cache`` local à la performance, clé ``(modèle, scénario)``) :
    ``members[c]`` = les scores de la source sur les sorties de ``c`` présentes dans
    ``scores``, dans l'ordre de leur rang."""
    key = (model, scenario)
    if key not in cache:
        source = _source(model)
        members = {
            day: tuple(
                scores[outing.outing_id][source]
                for outing in by_day[day].outings
                if outing.outing_id in scores
            )
            for day in population.members
        }
        cache[key] = tuple(
            calibrate(population, model, scenario, i, members)
            for i in range(len(CLOCKS))
        )
    return cache[key]


def calibrate_performances(
    performances: Sequence[Performance],
    scores: Mapping[str, Mapping[ModelKind, OutingScores]],
) -> tuple[CalibratedPerformance, ...]:
    """Le calage de chaque performance et les scores calés de ses sorties scorées,
    dans l'ordre reçu (``0010`` D9.2 ; D7.4).

    ``scores[outing_id]`` : les scores non calés d'une sortie scorée, sous ``V0_RAW``
    et les trois baselines ; une sortie non scorée n'y figure pas. Pour chaque
    performance : ``C_j`` ; pour chaque sortie présente dans ``scores``, dans l'ordre
    de la performance, et chaque modèle de ``CALIBRATED_MODELS``, les scores non calés
    de sa source (v0 brut pour v0 + effort recalé) ; contrôle, et usage s'il est
    présent ; pour chacun, les onze calages, puis les scores calés — en usage, de base
    la prévision d'usage de v0 brut de la sortie (D7.4 ; décision 13). Un calage se
    calcule une fois par performance, modèle et scénario, et sert à toutes les sorties
    de la performance : il ne dépend que des sorties des membres, jamais de la sortie
    évaluée.

    Préconditions (``ValueError``) : chaque sortie de ``scores`` a ses quatre modèles ;
    puis celles de ``calibration_population``.
    """
    for outing_id, by_model in scores.items():
        absent = [model for model in _UNSCALED if model not in by_model]
        if absent:
            raise ValueError(
                f"calibrate_performances : {outing_id} sans les modèles "
                f"[{', '.join(absent)}]."
            )
    by_day = {performance.civil_date: performance for performance in performances}
    results: list[CalibratedPerformance] = []
    for performance in performances:
        population = calibration_population(performance, performances)
        cache: dict[tuple[ModelKind, Scenario], tuple[ModelCalibration, ...]] = {}
        outings: list[CalibratedOutingScores] = []
        for outing in performance.outings:
            if outing.outing_id not in scores:
                continue
            unscaled_by_model = scores[outing.outing_id]
            v0_usage = unscaled_by_model[ModelKind.V0_RAW].usage
            base = None if v0_usage is None else v0_usage.forecast
            for model in CALIBRATED_MODELS:
                unscaled = unscaled_by_model[_source(model)]
                observation = unscaled.observation
                control = calibrated_scores(
                    observation,
                    unscaled.control.forecast,
                    _cached(cache, population, model, Scenario.CONTROL, by_day, scores),
                )
                usage = None
                if unscaled.usage is not None:
                    usage = calibrated_scores(
                        observation,
                        unscaled.usage.forecast,
                        _cached(
                            cache, population, model, Scenario.USAGE, by_day, scores
                        ),
                        base=base,
                    )
                outings.append(
                    CalibratedOutingScores(
                        outing.outing_id, observation, control, usage
                    )
                )
        results.append(CalibratedPerformance(population, tuple(outings)))
    return tuple(results)
