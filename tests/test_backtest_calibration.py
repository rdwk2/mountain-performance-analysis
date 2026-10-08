"""Le calage des modèles de référence (§ 6.4, § 7 et § 8.1, tests 2 à 7, du brief
M4c-1 ; ``0010`` D9 et ses précisions de M4c-1, D2.4, D2.5, D3, D7.1, D7.4).

- test 2, ``baseline_scores`` sur la chaîne de M4a : prévisions d'usage et de contrôle
  contre une intégration directe des allures (précision de D9.1), provenance
  (décision 7), sans référence, base de ``q_usage`` (décision 13), baseline sans
  chronologie (décision 6 : ``erreur du modèle``, jamais une exception), refus ;
- test 3, ``calibration_population`` : ``C_j`` du monde (§ 7.2 ``POPULATIONS``), bornes
  de l'origine (D2.5 ; précision de D2.4 : la fin la plus tardive des sorties), ordre
  reçu sans effet, refus ;
- test 4, ``calibrate`` : populations effectives, retraits, motifs et ``β`` du monde
  (§ 7.2 ``EFFECTIVE``, ``CALIBRATIONS`` ; décisions 10 à 12), bornes exactes de
  l'effort, l'observation avant le modèle (D7.1 ; décision 11), un membre de deux
  sorties, un temps nul jugé sur ``T_c``, une projection invalide sur une sortie
  quelconque, refus, coins du domaine (décision 14) ;
- test 5, prévisions et scores calés : niveaux du monde (§ 7.2 ``LEVELS``), prévision
  calée au bit (décision 2), absents gardés, scores calés au bit contre
  ``score_scenario``, ``q_usage`` d'un modèle calé de base v0 brut (D7.4), refus ;
- test 6, ``calibrate_performances`` : assemblage, un calage par performance, modèle et
  scénario, les scores de la source ;
- test 7, sans fuite (D9.2 : le jour évalué n'entre jamais dans son propre calage),
  par propriété, et un témoin.
"""

import functools
import math
import random
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fixtures import calibration as world
from fixtures import calibration_values as values
from fixtures import scoring
from fixtures.calibration import close
from fixtures.outings import source
from mountain_perf.backtest import (
    BASELINE_CURVE_REF,
    baseline_scores,
    calibrate,
    calibrate_performances,
    calibrated_forecast,
    calibrated_scores,
    calibration_population,
    origin,
    score_scenario,
)
from mountain_perf.gpx import PROFILE_PARAMETER_SPECS
from mountain_perf.model import BASELINES, baseline_paces
from mountain_perf.schemas import (
    CALIBRATED_MODELS,
    CLOCKS,
    CalibratedPerformance,
    CalibrationPopulation,
    ClockKind,
    ModelCalibration,
    ModelKind,
    OutingObservation,
    OutingScores,
    ParameterSet,
    Performance,
    RouteProfile,
    Scenario,
    Unavailability,
)

AT = datetime(2026, 10, 7, 8, 0, tzinfo=UTC)
"""L'instant fixe des prévisions de ``baseline_scores`` (§ 7.0)."""

CHAIN_CASES = ("Régimes", "Passages", "M05 ancré")
MOVING = tuple(i for i, clock in enumerate(CLOCKS) if clock.kind is ClockKind.MOVING)
NOT_MOVING = tuple(i for i in range(len(CLOCKS)) if i not in MOVING)


def _day(text: str) -> date:
    return date.fromisoformat(text)


def _iso(days: tuple[date, ...]) -> tuple[str, ...]:
    return tuple(day.isoformat() for day in days)


# ---------------------------------------------------------------------------
# Le monde (§ 7.1), calé une fois
# ---------------------------------------------------------------------------


@functools.cache
def _run(name: str) -> tuple[tuple[Performance, ...], dict[str, Any], tuple[Any, ...]]:
    spec = world.WORLDS[name]
    performances = world.world_performances(spec)
    scores = world.world_scores(spec)
    return performances, scores, calibrate_performances(performances, scores)


def _evaluated(name: str) -> list[tuple[str, CalibratedPerformance]]:
    """Les performances évaluées d'un monde, par jour, et leur calage."""
    performances, _, results = _run(name)
    spec = world.WORLDS[name]
    return [
        (performance.civil_date.isoformat(), result)
        for performance, result in zip(performances, results, strict=True)
        if performance.civil_date.isoformat() in spec.evaluated
    ]


def _spec(outing_id: str) -> world.OutingSpec:
    for spec in world.WORLDS["Monde"].outings:
        if spec.outing_id == outing_id:
            return spec
    raise KeyError(outing_id)


def _performance(name: str, day: str) -> CalibratedPerformance:
    return dict(_evaluated(name))[day]


def _scenario_scores(entry: Any, scenario: Scenario) -> Any:
    return entry.usage if scenario is Scenario.USAGE else entry.control


def _entry(name: str, day: str, model: ModelKind, outing_id: str | None = None) -> Any:
    """Les scores calés d'un modèle sur une sortie d'un jour évalué (la première par
    défaut)."""
    for entry in _performance(name, day).outings:
        if entry.control.model is model and outing_id in (None, entry.outing_id):
            return entry
    raise KeyError((name, day, model, outing_id))


WORLD_NAMES = list(world.WORLDS)


# ---------------------------------------------------------------------------
# Test 2 — baseline_scores sur la chaîne de M4a (§ 6.4, § 7.4)
# ---------------------------------------------------------------------------


def _integral(profile: RouteProfile, baseline: ModelKind, x: float) -> float:
    """``P(x)`` par intégration directe : ``fsum`` des recouvrements
    ``[d_i ; d_{i+1}] ∩ [0 ; x]`` fois l'allure."""
    paces = baseline_paces(profile, baseline)
    d = profile.distance_m
    return math.fsum(
        max(0.0, min(d[i + 1], x) - d[i]) * pace for i, pace in enumerate(paces)
    )


def _chain_scores(name: str, baseline: ModelKind, **kwargs: Any) -> OutingScores:
    c = scoring.chain(name)
    usage = scoring.scores(name).usage
    base = None if usage is None else usage.forecast
    return baseline_scores(
        scoring.observation(name),
        c.profile if scoring.SCORING_CASES[name].with_reference else None,
        scoring.trace_profile(c.case.trace),
        baseline,
        **({"base": base, "generated_at": AT} | kwargs),
    )


@pytest.mark.parametrize("baseline", BASELINES)
@pytest.mark.parametrize("name", CHAIN_CASES)
def test_baseline_forecasts_integrate_the_paces(name: str, baseline: ModelKind) -> None:
    """Précision de D9.1, D3 : en usage, ``p_i = P(b_{i+1}) − P(b_i)`` et chaque cumulé
    de ``C_k`` et de ``K`` vaut ``P(s) − P(b_0)`` ; en contrôle, sur le profil de la
    trace et les bornes réalisées, ni point ni ``K`` — à ``1e−9`` relatif d'une
    intégration directe des allures (§ 7.0)."""
    c = scoring.chain(name)
    observation = scoring.observation(name)
    outing = _chain_scores(name, baseline)
    assert outing.observation is observation
    assert outing.usage is not None
    usage = outing.usage.forecast
    reference = c.profile
    for segment, p in zip(observation.segments, usage.segment_s, strict=True):
        expected = _integral(reference, baseline, segment.end_m) - _integral(
            reference, baseline, segment.start_m
        )
        assert scoring.close(p, expected)
    origin_s = _integral(reference, baseline, observation.origin_m)
    for point, p in zip(observation.error_points, usage.point_s, strict=True):
        assert scoring.close(
            p, _integral(reference, baseline, point.distance_m) - origin_s
        )
    for target, p in zip(observation.targets, usage.target_s, strict=True):
        assert scoring.close(
            p, _integral(reference, baseline, target.distance_m) - origin_s
        )
    realized = scoring.trace_profile(c.case.trace)
    control = outing.control.forecast
    for segment, p in zip(observation.segments, control.segment_s, strict=True):
        expected = _integral(realized, baseline, segment.realized_end_m) - _integral(
            realized, baseline, segment.realized_start_m
        )
        assert scoring.close(p, expected)
    assert control.point_s == ()
    assert control.target_s == ()


@pytest.mark.parametrize("baseline", BASELINES)
def test_baseline_forecasts_provenance(baseline: ModelKind) -> None:
    """Décision 7 : version ``baselines-v1``, aucun paramètre, ``curve_ref`` « aucune
    courbe », ``generated_at`` reçu, ``source`` celle du profil projeté."""
    c = scoring.chain("Passages")
    outing = _chain_scores("Passages", baseline)
    assert outing.usage is not None
    for forecast, profile in (
        (outing.usage.forecast, c.profile),
        (outing.control.forecast, scoring.trace_profile(c.case.trace)),
    ):
        assert forecast.engine_version == "baselines-v1"
        assert forecast.curve_ref == "aucune courbe" == BASELINE_CURVE_REF
        assert forecast.parameters == ParameterSet(())
        assert forecast.generated_at == AT
        assert forecast.source == profile.source


def test_baseline_without_reference_has_no_usage() -> None:
    """D3 : une sortie sans référence n'a pas de scénario d'usage."""
    outing = _chain_scores("Régimes sans référence", ModelKind.NAISMITH)
    assert outing.usage is None


@pytest.mark.parametrize("baseline", BASELINES)
def test_baseline_base_of_q_usage(baseline: ModelKind) -> None:
    """D7.4, décision 13 : ``base`` (l'usage de v0 brut) sert à l'usage ; chaque ligne
    vaut au bit celle de ``score_scenario(…, base=base)``, et sans base celle de
    ``score_scenario(…)`` ; les deux ``q_usage`` diffèrent (sur Passages, ``q_usage``
    de tout ``K`` est indisponible, support insuffisant : c'est ``q_usage | préfixe``
    qui porte une valeur)."""
    observation = scoring.observation("Passages")
    v0_usage = scoring.scores("Passages").usage
    assert v0_usage is not None
    base = v0_usage.forecast
    with_base = _chain_scores("Passages", baseline)
    without = _chain_scores("Passages", baseline, base=None)
    assert with_base.usage is not None
    assert without.usage is not None
    forecast = with_base.usage.forecast
    assert with_base.usage == score_scenario(observation, forecast, base=base)
    assert without.usage == score_scenario(observation, forecast)
    for a, b in zip(with_base.usage.clocks, without.usage.clocks, strict=True):
        assert a.usage_target is not None
        assert b.usage_target is not None
        assert a.usage_target.q_usage_prefix.value is not None
        assert a.usage_target.q_usage_prefix != b.usage_target.q_usage_prefix


def _extreme_profile(length_m: float) -> RouteProfile:
    """Grille ``(0 ; 0,01 ; L)`` aux altitudes ``(1000 ; 1003 ; 1000)`` : ``+300`` sur
    1 cm."""
    return RouteProfile(
        route_name="Pente extrême",
        source=source("gpx", "extreme.gpx", "3"),
        distance_m=(0.0, 0.01, length_m),
        elevation_m=(1000.0, 1003.0, 1000.0),
        resolved_points=(),
        step_m=0.01,
        build_parameters=ParameterSet(PROFILE_PARAMETER_SPECS),
    )


def _a0601() -> OutingObservation:
    return world.observation(_spec("a-0601"))


def _no_timeline_scores(baseline: ModelKind) -> OutingScores:
    observation = _a0601()
    profile = _extreme_profile(observation.reference_length_m)
    return baseline_scores(observation, profile, profile, baseline, generated_at=AT)


def test_a_baseline_without_timeline_is_a_model_error() -> None:
    """Décision 6, D7.1 : Tobler sans chronologie (pente extrême) — une prévision sans
    aucune valeur, ``erreur du modèle`` du support sous les onze horloges, dans les
    deux scénarios ; jamais une exception. Naismith, sur le même profil, n'est pas en
    erreur."""
    outing = _no_timeline_scores(ModelKind.TOBLER)
    assert outing.usage is not None
    usage, control = outing.usage.forecast, outing.control.forecast
    assert usage.segment_s == (None,) * 3 == control.segment_s
    assert usage.target_s == (None,)
    assert control.target_s == ()
    assert usage.point_s == () == control.point_s
    for scenario in (outing.usage, outing.control):
        for row in scenario.clocks:
            assert row.support.log_ratio.unavailability is Unavailability.MODEL_ERROR
    naismith = _no_timeline_scores(ModelKind.NAISMITH)
    assert naismith.control.clocks[0].support.log_ratio.value is not None


@pytest.mark.parametrize("model", [ModelKind.V0_RAW, ModelKind.V0_RECALIBRATED])
def test_baseline_scores_refuses_a_model_that_is_not_a_baseline(
    model: ModelKind,
) -> None:
    """D9.1 : refusé par le message de ``baseline_scores``, pas par celui de
    ``baseline_paces``."""
    with pytest.raises(
        ValueError, match=r"^baseline_scores : .* n'est pas une baseline"
    ):
        _chain_scores("Passages", model)


def test_baseline_scores_generated_at_defaults_to_now() -> None:
    """§ 6.4 : ``generated_at`` absent, maintenant en UTC."""
    before = datetime.now(UTC)
    outing = _chain_scores("Passages", ModelKind.TOBLER, generated_at=None)
    after = datetime.now(UTC)
    assert outing.usage is not None
    assert before <= outing.control.forecast.generated_at <= after
    assert outing.usage.forecast.generated_at == outing.control.forecast.generated_at


# ---------------------------------------------------------------------------
# Test 3 — la population (D2.4, D2.5 ; § 7.2 POPULATIONS)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", WORLD_NAMES)
def test_population_of_each_evaluated_day(name: str) -> None:
    """D2.4, D2.5, précision de D2.4 : membres et exclus (avec motif) de ``C_j``, et
    ``o_j``, pour chaque jour évalué."""
    for day, result in _evaluated(name):
        members, excluded = values.POPULATIONS[(name, day)]
        population = result.population
        assert _iso(population.members) == members
        assert (
            tuple(
                (e.civil_date.isoformat(), e.reason.value) for e in population.excluded
            )
            == excluded
        )
        assert population.origin == origin(_day(day))


def _members(day: str) -> tuple[str, ...]:
    performances, _, _ = _run("Monde")
    (performance,) = (p for p in performances if p.civil_date == _day(day))
    return _iso(calibration_population(performance, performances).members)


def test_population_boundaries_of_the_origin() -> None:
    """D2.5 (strictement avant ``o_j``) ; D0, D2.4 (une performance est terminée quand
    toutes ses sorties le sont) : K (10 juin) membre le 19, pas le 18 ; M (11 juin,
    finie à 0 h pile) membre le 20, pas le 19 ; N (12 juin, seconde sortie finie le 13
    à 0 h 30) pas membre le 20."""
    assert "2026-06-10" not in _members("2026-06-18")
    assert "2026-06-10" in _members("2026-06-19")
    assert "2026-06-11" not in _members("2026-06-19")
    assert "2026-06-11" in _members("2026-06-20")
    assert "2026-06-12" not in _members("2026-06-20")


def test_population_does_not_depend_on_the_order_received() -> None:
    """§ 6.4 : dans l'ordre des jours, quel que soit l'ordre reçu."""
    performances, _, _ = _run("Monde")
    shuffled = list(performances)
    random.Random(20261007).shuffle(shuffled)
    assert shuffled != list(performances)
    for performance in performances:
        assert calibration_population(performance, shuffled) == calibration_population(
            performance, performances
        )


def test_population_refuses_two_performances_of_the_same_day() -> None:
    performances, _, _ = _run("Monde")
    with pytest.raises(ValueError, match="deux performances du même jour"):
        calibration_population(performances[0], [*performances, performances[1]])


# ---------------------------------------------------------------------------
# Test 4 — calibrate (D9.2 ; § 7.2 EFFECTIVE, CALIBRATIONS)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", WORLD_NAMES)
def test_calibrations_of_the_world(name: str) -> None:
    """D9.2 et sa précision, décisions 10 à 12 : pour chaque sortie, chaque scénario et
    chaque horloge, la population effective, les retraits, le motif, ``β``, l'effort et
    la saturation ; calé, le facteur vaut ``exp(β)`` (baseline) ou ``1 / effort``
    (v0)."""
    for day, result in _evaluated(name):
        for entry in result.outings:
            for scenario in Scenario:
                scores = _scenario_scores(entry, scenario)
                if scores is None:
                    continue
                key = (name, day, scores.model.value, scenario.value)
                effective = values.EFFECTIVE[(name, day, scenario.value)]
                expected = values.CALIBRATIONS[key]
                for i, row in enumerate(scores.clocks):
                    calibration = row.calibration
                    assert calibration.clock == CLOCKS[i]
                    population, withdrawals = effective[i]
                    assert _iso(calibration.population) == population
                    assert (
                        tuple(
                            (w.civil_date.isoformat(), w.reason.value)
                            for w in calibration.withdrawals
                        )
                        == withdrawals
                    )
                    motif, beta, effort, saturated = expected[i]
                    got = calibration.unavailability
                    assert (None if got is None else got.value) == motif
                    assert close(calibration.beta, beta)
                    assert close(calibration.effort, effort)
                    assert calibration.saturated is saturated
                    if calibration.beta is None:
                        continue
                    if calibration.effort is None:
                        assert close(calibration.factor, math.exp(calibration.beta))
                    else:
                        assert close(calibration.factor, 1.0 / calibration.effort)


@pytest.mark.parametrize(
    ("day", "effort", "factor", "saturated"),
    [
        ("2026-07-09", 0.5, 2.0, False),
        ("2026-07-18", 0.5, 2.0, True),
        ("2026-07-27", 1.5, 1.0 / 1.5, True),
    ],
)
def test_effort_bounds(day: str, effort: float, factor: float, saturated: bool) -> None:
    """D9.2, précision : l'effort à la borne exacte n'est pas saturé (9 juillet,
    ``exp(−β) = 0,5``) ; sous et au-dessus, saturé et borné (§ 7.0, au bit)."""
    entry = _entry("Saturation", day, ModelKind.V0_RECALIBRATED)
    calibration = entry.control.clocks[0].calibration
    assert calibration.effort == effort
    assert calibration.factor == factor
    assert calibration.saturated is saturated


def _member(elapsed: float, projection: float, day: str = "2026-06-01") -> OutingScores:
    """Un membre d'un segment : écoulé ``elapsed``, projection ``projection`` (sous
    l'écoulé ; les autres horloges du monde, ``clock_times``)."""
    spec = world.OutingSpec(
        f"z-{day}",
        day,
        world.TRAINING,
        ((world.A, elapsed),),
        control={model: (1.0,) for model in world.UNSCALED},
    )
    observation = world.observation(spec)
    forecast = replace(
        world.forecast(spec, ModelKind.V0_RAW, Scenario.CONTROL),
        segment_s=(projection,),
    )
    return OutingScores(observation, score_scenario(observation, forecast), None)


J = _day("2026-06-16")
D1, D2 = _day("2026-06-01"), _day("2026-06-02")


def _population_of(*days: date) -> CalibrationPopulation:
    return CalibrationPopulation(J, origin(J), days, ())


def test_effort_exact_upper_bound() -> None:
    """D9.2, § 7.0 : deux membres de rapports ``T / P`` ``0.6666666666666666`` et
    ``0.6666666666666667`` — ``β == −ln 1,5`` au bit, ``exp(−β) == 1,5``, effort
    ``1.5``, facteur ``1 / 1,5``, non saturé."""
    members = {
        D1: (_member(0.6666666666666666, 1.0),),
        D2: (_member(0.6666666666666667, 1.0, "2026-06-02"),),
    }
    calibration = calibrate(
        _population_of(D1, D2), ModelKind.V0_RECALIBRATED, Scenario.CONTROL, 0, members
    )
    assert calibration.beta == -math.log(1.5)
    assert math.exp(-calibration.beta) == 1.5
    assert calibration.effort == 1.5
    assert calibration.factor == 1.0 / 1.5
    assert calibration.saturated is False


def test_the_observation_comes_before_the_model() -> None:
    """D7.1, décision 11 (16 juin, Naismith, usage) : sous les cinq ``M θ``, le 8 juin
    est retiré (``zero_time``) avant que sa projection invalide ne compte, et Naismith
    est calé ; sous l'écoulé et les ``(M+U) θ``, le 8 juin est dans la population
    effective et Naismith en ``erreur du modèle``."""
    entry = _entry("Monde", "2026-06-16", ModelKind.NAISMITH)
    h = _day("2026-06-08")
    for i, row in enumerate(entry.usage.clocks):
        calibration = row.calibration
        if i in MOVING:
            assert calibration.unavailability is None
            assert h not in calibration.population
            assert (h, Unavailability.ZERO_TIME) in {
                (w.civil_date, w.reason) for w in calibration.withdrawals
            }
        else:
            assert calibration.unavailability is Unavailability.MODEL_ERROR
            assert h in calibration.population


def _scores_of(*specs: world.OutingSpec, model: ModelKind) -> tuple[OutingScores, ...]:
    return tuple(world.outing_scores(spec, model) for spec in specs)


def _totals(
    specs: tuple[world.OutingSpec, ...], model: ModelKind, scenario: Scenario, i: int
) -> tuple[float, float]:
    """``ΣT`` et ``ΣP`` d'un membre recalculés depuis le monde."""
    times: list[float] = []
    projections: list[float] = []
    for spec in specs:
        ratios = spec.usage if scenario is Scenario.USAGE else spec.control
        if not ratios:
            continue
        for ratio, (_, elapsed) in zip(ratios[model], spec.segments, strict=True):
            times.append(world.clock_times(elapsed, zero_moving=spec.zero_moving)[i])
            projections.append(ratio * elapsed)
    return math.fsum(times), math.fsum(projections)


B1, B2 = _spec("b1-0602"), _spec("b2-0602")


@pytest.mark.parametrize("scenario", list(Scenario))
def test_a_member_of_two_outings(scenario: Scenario) -> None:
    """Précision de D9.2, décision 10 : le 2 juin seul membre — en contrôle,
    ``β = ln(ΣT / ΣP)`` sur ses deux sorties, un seul logarithme ; en usage, sur sa
    seule sortie à référence."""
    members = {D2: _scores_of(B1, B2, model=ModelKind.V0_RAW)}
    for i in range(len(CLOCKS)):
        calibration = calibrate(
            _population_of(D2), ModelKind.V0_RECALIBRATED, scenario, i, members
        )
        t, p = _totals((B1, B2), ModelKind.V0_RAW, scenario, i)
        assert close(calibration.beta, math.log(t / p))


def test_a_zero_time_is_judged_on_the_total() -> None:
    """Décision 11 : b2 à temps nuls sous les ``M θ`` — sous chacune, v0 + effort
    recalé en contrôle est calé, sans retrait, ``β = ln(ΣT / ΣP)`` (``T`` de b1 seule,
    ``P`` des deux sorties)."""
    b2 = replace(B2, zero_moving=True)
    members = {D2: _scores_of(B1, b2, model=ModelKind.V0_RAW)}
    for i in MOVING:
        calibration = calibrate(
            _population_of(D2), ModelKind.V0_RECALIBRATED, Scenario.CONTROL, i, members
        )
        assert calibration.unavailability is None
        assert calibration.withdrawals == ()
        t, p = _totals((B1, b2), ModelKind.V0_RAW, Scenario.CONTROL, i)
        assert close(calibration.beta, math.log(t / p))
    first = calibrate(
        _population_of(D2), ModelKind.V0_RECALIBRATED, Scenario.CONTROL, 1, members
    )
    assert close(first.beta, -1.1440390495751132)


def _naismith_without(spec: world.OutingSpec, ratios: tuple[float, ...]) -> Any:
    return replace(spec, control={**spec.control, ModelKind.NAISMITH: ratios})


@pytest.mark.parametrize(
    "specs",
    [
        (_naismith_without(B1, (math.nan, 1.50)), B2),
        (B1, _naismith_without(B2, (math.nan,))),
    ],
    ids=["b1", "b2"],
)
def test_an_invalid_projection_on_any_outing(specs: tuple[Any, Any]) -> None:
    """D7.1, décision 11 : une projection invalide sur une sortie quelconque du membre
    (b1 départage « la dernière sortie seule », b2 « la première sortie seule ») rend
    le calage ``erreur du modèle``, le membre dans la population effective, aucun
    retrait."""
    members = {D2: _scores_of(*specs, model=ModelKind.NAISMITH)}
    for i in range(len(CLOCKS)):
        calibration = calibrate(
            _population_of(D2), ModelKind.NAISMITH, Scenario.CONTROL, i, members
        )
        assert calibration.unavailability is Unavailability.MODEL_ERROR
        assert calibration.population == (D2,)
        assert calibration.withdrawals == ()


def test_calibrate_preconditions() -> None:
    """§ 6.4 : un modèle calé, un indice d'horloge dans ``[0 ; 11[``, une entrée pour
    chaque membre."""
    members = {D2: _scores_of(B1, model=ModelKind.V0_RAW)}
    population = _population_of(D2)
    for model in (ModelKind.V0_RAW, ModelKind.CANDIDATE):
        with pytest.raises(ValueError, match="n'est pas un modèle calé"):
            calibrate(population, model, Scenario.CONTROL, 0, members)
    for clock_index in (-1, len(CLOCKS)):
        with pytest.raises(ValueError, match="clock_index"):
            calibrate(
                population, ModelKind.TOBLER, Scenario.CONTROL, clock_index, members
            )
    with pytest.raises(ValueError, match="aucune entrée pour les membres"):
        calibrate(
            _population_of(D1, D2), ModelKind.TOBLER, Scenario.CONTROL, 0, members
        )


@pytest.mark.parametrize(
    ("elapsed", "projection", "effort"), [(1e-6, 1e12, 1.5), (1e12, 1e-6, 0.5)]
)
def test_corners_of_the_domain(
    elapsed: float, projection: float, effort: float
) -> None:
    """Décision 14 : aux coins du domaine (un membre d'un segment), ``|β| = ln(1e18)``,
    l'effort saturé à sa borne, le facteur de Tobler fini et ``> 0``."""
    members = {D1: (_member(elapsed, projection),)}
    v0 = calibrate(
        _population_of(D1), ModelKind.V0_RECALIBRATED, Scenario.CONTROL, 0, members
    )
    assert v0.beta is not None
    assert close(abs(v0.beta), math.log(1e18))
    assert v0.effort == effort
    assert v0.saturated is True
    tobler = calibrate(
        _population_of(D1), ModelKind.TOBLER, Scenario.CONTROL, 0, members
    )
    assert tobler.factor is not None
    assert math.isfinite(tobler.factor)
    assert tobler.factor > 0


# ---------------------------------------------------------------------------
# Test 5 — prévisions et scores calés (§ 7.2 LEVELS ; décision 2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", WORLD_NAMES)
def test_levels_of_the_calibrated_forecasts(name: str) -> None:
    """D9.2, D7.2 : ``L`` de la prévision calée sous chaque horloge, pour chaque sortie
    évaluée, modèle et scénario ; scores absents là où le modèle n'est pas calé."""
    for _, result in _evaluated(name):
        for entry in result.outings:
            for scenario in Scenario:
                scores = _scenario_scores(entry, scenario)
                if scores is None:
                    continue
                key = (name, entry.outing_id, scores.model.value, scenario.value)
                for row, level in zip(scores.clocks, values.LEVELS[key], strict=True):
                    if level is None:
                        assert row.scores is None
                    else:
                        assert row.scores is not None
                        assert close(row.scores.support.log_ratio.value, level)


def _scaled(p: float | None, calibration: ModelCalibration) -> float | None:
    if p is None:
        return None
    if calibration.effort is not None:
        return p / calibration.effort
    assert calibration.factor is not None
    return p * calibration.factor


def test_calibrated_forecast_divides_or_multiplies_at_the_bit() -> None:
    """Décision 2 : ``p / effort`` (v0), ``p · factor`` (baseline), au bit ; absents
    gardés ; ``point_s`` vide ; provenance recopiée champ par champ."""
    checked = 0
    for entry in _performance("Monde", "2026-06-16").outings:
        for scores in (entry.control, entry.usage):
            if scores is None:
                continue
            forecast = scores.forecast
            for row in scores.clocks:
                calibration = row.calibration
                if calibration.unavailability is not None:
                    continue
                calibrated = calibrated_forecast(forecast, calibration)
                assert calibrated.segment_s == tuple(
                    _scaled(p, calibration) for p in forecast.segment_s
                )
                assert calibrated.target_s == tuple(
                    _scaled(p, calibration) for p in forecast.target_s
                )
                assert calibrated.point_s == ()
                for field in (
                    "scenario",
                    "source",
                    "curve_ref",
                    "parameters",
                    "engine_version",
                    "generated_at",
                ):
                    assert getattr(calibrated, field) == getattr(forecast, field)
                checked += 1
    assert checked > 0


def _calibration(
    model: ModelKind, scenario: Scenario, beta: float, clock_index: int = 0
) -> ModelCalibration:
    """Un calage construit à ``β`` : effort et facteur par la formule (§ 7.0)."""
    effort = factor = None
    if model is ModelKind.V0_RECALIBRATED:
        effort = math.exp(-beta)
        factor = 1.0 / effort
    else:
        factor = math.exp(beta)
    return ModelCalibration(
        model,
        scenario,
        CLOCKS[clock_index],
        (D1,),
        (),
        beta,
        effort,
        factor,
        False,
        None,
    )


def test_calibrated_forecast_scales_the_passages_too() -> None:
    """Décision 2 : les cumulés des points de ``C_k`` sont multipliés aussi (Passages,
    Tobler calé à ``β = 0,25``)."""
    outing = _chain_scores("Passages", ModelKind.TOBLER)
    assert outing.usage is not None
    forecast = outing.usage.forecast
    calibration = _calibration(ModelKind.TOBLER, Scenario.USAGE, 0.25)
    calibrated = calibrated_forecast(forecast, calibration)
    assert forecast.point_s
    assert calibrated.point_s == tuple(
        _scaled(p, calibration) for p in forecast.point_s
    )


@pytest.mark.parametrize("model", [ModelKind.V0_RECALIBRATED, ModelKind.TOBLER])
def test_an_absent_value_stays_absent(model: ModelKind) -> None:
    """Décision 2, D7.1 : la prévision d'usage de Tobler sans chronologie, calée à
    ``β = 0,25`` — ni ``nan`` ni ``0`` : ``None`` partout ; ses scores calés sont
    présents et en ``erreur du modèle`` du support sous les onze horloges."""
    outing = _no_timeline_scores(ModelKind.TOBLER)
    assert outing.usage is not None
    forecast = outing.usage.forecast
    calibrated = calibrated_forecast(
        forecast, _calibration(model, Scenario.USAGE, 0.25)
    )
    assert calibrated.segment_s == (None,) * 3
    assert calibrated.target_s == (None,)
    assert calibrated.point_s == ()
    calibrations = [
        _calibration(model, Scenario.USAGE, 0.25, i) for i in range(len(CLOCKS))
    ]
    result = calibrated_scores(outing.observation, forecast, calibrations)
    for row in result.clocks:
        assert row.scores is not None
        assert row.scores.support.log_ratio.unavailability is (
            Unavailability.MODEL_ERROR
        )


def test_calibrated_forecast_preconditions() -> None:
    """§ 6.4 : un modèle calé ; le même scénario."""
    entry = _entry("Retraits", "2026-08-10", ModelKind.TOBLER)
    not_calibrated = entry.usage.clocks[0].calibration
    assert not_calibrated.unavailability is Unavailability.NOT_CALIBRATED
    with pytest.raises(ValueError, match="modèle non calé"):
        calibrated_forecast(entry.usage.forecast, not_calibrated)
    control = entry.control.clocks[0].calibration
    with pytest.raises(ValueError, match="prévision usage, calage control"):
        calibrated_forecast(entry.usage.forecast, control)


@pytest.mark.parametrize("name", WORLD_NAMES)
def test_calibrated_scores_are_the_lines_of_score_scenario(name: str) -> None:
    """D9.2, D7.4 : sous chaque horloge calée, les scores valent au bit la ligne de
    ``score_scenario`` de la prévision calée — de base l'usage de v0 brut en usage,
    aucune en contrôle."""
    _, unscaled, _ = _run(name)
    for _, result in _evaluated(name):
        for entry in result.outings:
            v0_usage = unscaled[entry.outing_id][ModelKind.V0_RAW].usage
            for scenario in Scenario:
                scores = _scenario_scores(entry, scenario)
                if scores is None:
                    continue
                base = None
                if scenario is Scenario.USAGE:
                    base = v0_usage.forecast
                for i, row in enumerate(scores.clocks):
                    if row.scores is None:
                        continue
                    forecast = calibrated_forecast(scores.forecast, row.calibration)
                    lines = score_scenario(entry.observation, forecast, base=base)
                    assert row.scores == lines.clocks[i]


def test_q_usage_of_a_calibrated_model_has_the_base_of_v0_raw() -> None:
    """D7.4, décision 13 (16 juin, vitesse constante, usage) :
    ``q_usage = |facteur · P_K − T_K| / P_K^(0)``, ``P_K^(0)`` celui de v0 brut."""
    entry = _entry("Monde", "2026-06-16", ModelKind.CONSTANT_SPEED)
    _, unscaled, _ = _run("Monde")
    v0_usage = unscaled[entry.outing_id][ModelKind.V0_RAW].usage
    (p_k,) = entry.usage.forecast.target_s
    (p_0,) = v0_usage.forecast.target_s
    (target,) = entry.observation.targets
    for i, row in enumerate(entry.usage.clocks):
        expected = abs(row.calibration.factor * p_k - target.times_s[i]) / p_0
        assert close(row.scores.usage_target.q_usage.value, expected)


def test_calibrated_scores_preconditions() -> None:
    """§ 6.4 : onze calages dans l'ordre de ``CLOCKS`` ; un seul modèle ; le scénario
    de la prévision."""
    entry = _entry("Monde", "2026-06-16", ModelKind.CONSTANT_SPEED)
    observation, forecast = entry.observation, entry.usage.forecast
    calibrations = [row.calibration for row in entry.usage.clocks]
    with pytest.raises(ValueError, match="onze calages"):
        calibrated_scores(observation, forecast, calibrations[:10])
    permuted = [calibrations[1], calibrations[0], *calibrations[2:]]
    with pytest.raises(ValueError, match="onze calages"):
        calibrated_scores(observation, forecast, permuted)
    tobler = _entry("Monde", "2026-06-16", ModelKind.TOBLER).usage.clocks[3].calibration
    mixed = [*calibrations[:3], tobler, *calibrations[4:]]
    with pytest.raises(ValueError, match="plusieurs modèles"):
        calibrated_scores(observation, forecast, mixed)
    control = [row.calibration for row in entry.control.clocks]
    with pytest.raises(ValueError, match="calage control, prévision usage"):
        calibrated_scores(observation, forecast, control)


# ---------------------------------------------------------------------------
# Test 6 — calibrate_performances (§ 6.4)
# ---------------------------------------------------------------------------


def test_calibrate_performances_assembles_each_performance() -> None:
    """§ 6.4 : une entrée par performance, dans l'ordre reçu ; le 18 juin, ``j3a``
    (avec usage) puis ``j3b`` (sans usage), ``j3c`` (non scorée) absente ; les modèles
    dans l'ordre de ``CALIBRATED_MODELS`` ; un calage par performance : les calages de
    contrôle de ``j3a`` et de ``j3b`` égaux, modèle par modèle."""
    performances, _, results = _run("Monde")
    assert [r.population.civil_date for r in results] == [
        p.civil_date for p in performances
    ]
    outings = _performance("Monde", "2026-06-18").outings
    assert [e.outing_id for e in outings] == ["j3a-0618"] * 4 + ["j3b-0618"] * 4
    assert [e.control.model for e in outings] == [*CALIBRATED_MODELS] * 2
    assert all(e.usage is not None for e in outings[:4])
    assert all(e.usage is None for e in outings[4:])
    for a, b in zip(outings[:4], outings[4:], strict=True):
        assert [row.calibration for row in a.control.clocks] == [
            row.calibration for row in b.control.clocks
        ]


def test_calibrate_performances_refuses_an_outing_without_its_four_models() -> None:
    performances, scores, _ = _run("Monde")
    partial = dict(scores)
    partial["a-0601"] = {
        model: s
        for model, s in scores["a-0601"].items()
        if model is not ModelKind.TOBLER
    }
    with pytest.raises(ValueError, match="a-0601 sans les modèles"):
        calibrate_performances(performances, partial)


def test_calibrate_performances_carries_the_scores_of_the_source() -> None:
    """D9.1 : prévisions non calées et observation de la source — v0 brut pour
    v0 + effort recalé, la baseline elle-même sinon."""
    _, scores, _ = _run("Monde")
    for entry in _performance("Monde", "2026-06-16").outings:
        model = entry.control.model
        source_model = ModelKind.V0_RAW if model is ModelKind.V0_RECALIBRATED else model
        unscaled = scores[entry.outing_id][source_model]
        assert entry.observation is unscaled.observation
        assert entry.control.forecast is unscaled.control.forecast
        assert unscaled.usage is not None
        assert entry.usage is not None
        assert entry.usage.forecast is unscaled.usage.forecast


def test_the_world_scores_every_scored_outing_under_four_models() -> None:
    """§ 7.1 : chaque sortie scorée a ses quatre modèles non calés, une non scorée
    aucun."""
    for spec in world.WORLDS.values():
        scores = world.world_scores(spec)
        for outing in spec.outings:
            if outing.outing_id in spec.unscored:
                assert outing.outing_id not in scores
            else:
                assert set(scores[outing.outing_id]) == set(world.UNSCALED)


# ---------------------------------------------------------------------------
# Test 7 — sans fuite (D9.2)
# ---------------------------------------------------------------------------

LATE_DAYS = frozenset(
    {
        "2026-06-09",
        "2026-06-10",
        "2026-06-11",
        "2026-06-12",
        "2026-06-16",
        "2026-06-17",
        "2026-06-18",
        "2026-06-19",
        "2026-06-20",
    }
)
"""Le jour évalué (16 juin) et les performances qui ne finissent pas avant son origine
(9 juin, 0 h) : I, K, M, N et les jours évalués suivants."""


def _scaled_spec(spec: world.OutingSpec, time: float, ratio: float) -> world.OutingSpec:
    def scale(ratios: Any) -> dict[ModelKind, tuple[float, ...]]:
        return {model: tuple(r * ratio for r in rs) for model, rs in ratios.items()}

    return replace(
        spec,
        segments=tuple((regime, elapsed * time) for regime, elapsed in spec.segments),
        control=scale(spec.control),
        usage=scale(spec.usage),
    )


def _calibrations_of_june_16(spec: world.WorldSpec) -> list[ModelCalibration]:
    performances = world.world_performances(spec)
    results = calibrate_performances(performances, world.world_scores(spec))
    (result,) = (r for r in results if r.population.civil_date == J)
    return [
        row.calibration
        for entry in result.outings
        for scores in (entry.control, entry.usage)
        if scores is not None
        for row in scores.clocks
    ]


@settings(max_examples=25, deadline=None)
@given(st.floats(min_value=0.5, max_value=2.0), st.floats(min_value=0.5, max_value=2.0))
def test_no_leak_from_the_evaluated_day(time: float, ratio: float) -> None:
    """D9.2 : le jour évalué n'entre jamais dans son propre calage — multiplier les
    écoulés et les rapports du 16 juin et de toute performance qui ne finit pas avant
    son origine ne change aucun calage du 16 juin."""
    spec = world.WORLDS["Monde"]
    changed = replace(
        spec,
        outings=tuple(
            _scaled_spec(o, time, ratio) if o.day in LATE_DAYS else o
            for o in spec.outings
        ),
    )
    assert _calibrations_of_june_16(changed) == _calibrations_of_june_16(spec)


def test_a_member_does_change_the_calibration() -> None:
    """Témoin de D9.2 : multiplier les rapports d'un membre (1er juin, × 1,5) change
    ``β``."""
    spec = world.WORLDS["Monde"]
    changed = replace(
        spec,
        outings=tuple(
            _scaled_spec(o, 1.0, 1.5) if o.day == "2026-06-01" else o
            for o in spec.outings
        ),
    )
    before = _calibrations_of_june_16(spec)
    after = _calibrations_of_june_16(changed)
    assert any(
        a.beta != b.beta
        for a, b in zip(after, before, strict=True)
        if b.beta is not None
    )


def test_june_16_has_member_days_before_its_origin_only() -> None:
    """D2.5 : tous les membres du 16 juin finissent avant ``o_j`` (9 juin, 0 h) ; le
    jeu des jours tardifs du test de propriété ne touche aucun membre."""
    population = _performance("Monde", "2026-06-16").population
    assert all(day.isoformat() not in LATE_DAYS for day in population.members)
    performances, _, _ = _run("Monde")
    for performance in performances:
        late = performance.civil_date.isoformat() in LATE_DAYS
        finished = performance.end_time < origin(J)
        assert late is not finished
