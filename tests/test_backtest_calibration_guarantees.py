"""Les garanties écrites du calage que la batterie des tests 2 à 7 ne tenait pas
(§ 6.3, § 6.4 et § 8.1 du brief M4c-1 ; ``0010`` D9.2 et sa précision de M4c-1 ;
relectures de la PR #21 et balayage de la conception) :

- ``baseline_scores`` sans chronologie : la provenance et la forme de la prévision
  (§ 6.4, étape 3) ; ``generated_at`` par défaut en UTC (étape 2) ;
- ``calibrate`` : les membres parcourus dans l'ordre de ``population.members``, jamais
  les clés de ``members`` (le jour évalué n'entre pas dans son propre calage) ; les
  totaux d'un membre sur toutes ses sorties scorées, une sortie sans usage n'arrêtant
  pas les suivantes ; l'ordre des préconditions ;
- ``calibrated_forecast`` : la provenance recopiée, ``parameters`` compris ;
- ``calibrate_performances`` : l'ordre reçu, une sortie non scorée qui n'arrête pas les
  suivantes, un membre dont une sortie seulement est scorée, l'ordre des préconditions,
  aucune lecture ni écriture de fichier (§ 6) ;
- ``calibration_population`` : la performance évaluée n'a pas à figurer dans la liste ;
- ``clock_scores`` : la base de ``q_usage`` vérifiée comme par ``score_scenario``.
"""

import builtins
import math
from dataclasses import replace
from datetime import UTC, date
from typing import Any

import pytest

from fixtures import calibration as world
from fixtures import scoring
from fixtures.calibration import close
from fixtures.outings import source
from mountain_perf.backtest import (
    BASELINE_CURVE_REF,
    baseline_scores,
    calibrate,
    calibrate_performances,
    calibrated_forecast,
    calibration_population,
    clock_scores,
    origin,
    score_scenario,
)
from mountain_perf.gpx import PROFILE_PARAMETER_SPECS
from mountain_perf.schemas import (
    CLOCKS,
    CalibrationPopulation,
    ModelCalibration,
    ModelKind,
    OutingObservation,
    OutingScores,
    ParameterSet,
    RouteProfile,
    Scenario,
)

AT = world.GENERATED_AT
J = date(2026, 6, 16)
D1, D2 = date(2026, 6, 1), date(2026, 6, 2)
V0 = ModelKind.V0_RECALIBRATED


def _spec(outing_id: str) -> world.OutingSpec:
    (spec,) = (s for s in world.MONDE.outings if s.outing_id == outing_id)
    return spec


def _extreme_profile(length_m: float) -> RouteProfile:
    """Grille ``(0 ; 0,01 ; L)`` aux altitudes ``(1000 ; 1003 ; 1000)`` : ``+300`` sur
    1 cm, où Tobler n'a pas de vitesse finie."""
    return RouteProfile(
        route_name="Pente extrême",
        source=source("gpx", "extreme.gpx", "3"),
        distance_m=(0.0, 0.01, length_m),
        elevation_m=(1000.0, 1003.0, 1000.0),
        resolved_points=(),
        step_m=0.01,
        build_parameters=ParameterSet(PROFILE_PARAMETER_SPECS),
    )


def _without_timeline(observation: OutingObservation) -> OutingScores:
    profile = _extreme_profile(observation.reference_length_m)
    return baseline_scores(
        observation, profile, profile, ModelKind.TOBLER, generated_at=AT
    )


def _member(elapsed: float, projection: float, day: str) -> OutingScores:
    """Un membre d'un segment, écoulé ``elapsed``, projection ``projection``."""
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


def _population(*days: date) -> CalibrationPopulation:
    return CalibrationPopulation(J, origin(J), days, ())


# ---------------------------------------------------------------------------
# baseline_scores (§ 6.4, étapes 2 et 3 ; décisions 6 et 7)
# ---------------------------------------------------------------------------


def test_a_baseline_without_timeline_keeps_its_provenance() -> None:
    """§ 6.4, étape 3 : sans chronologie, une prévision « de même provenance » — source
    du profil, aucun paramètre, « aucune courbe », ``baselines-v1``, ``generated_at``
    reçu — dans les deux scénarios."""
    observation = world.observation(_spec("a-0601"))
    profile = _extreme_profile(observation.reference_length_m)
    outing = _without_timeline(observation)
    assert outing.usage is not None
    for scores in (outing.usage, outing.control):
        forecast = scores.forecast
        assert forecast.source == profile.source
        assert forecast.parameters == ParameterSet(())
        assert forecast.curve_ref == BASELINE_CURVE_REF
        assert forecast.engine_version == "baselines-v1"
        assert forecast.generated_at == AT


def test_a_baseline_without_timeline_has_no_value_at_the_points() -> None:
    """§ 6.4, étape 3 : en usage, ``point_s = (None,) × len(error_points)`` ; en
    contrôle, ``()`` — sur une observation qui a des points de ``C_k``."""
    observation = scoring.observation("Passages")
    assert observation.error_points
    outing = _without_timeline(observation)
    assert outing.usage is not None
    assert outing.usage.forecast.point_s == (None,) * len(observation.error_points)
    assert outing.control.forecast.point_s == ()


def test_baseline_scores_defaults_to_now_in_utc() -> None:
    """§ 6.4, étape 2 : ``generated_at`` absent, ``datetime.now(UTC)``."""
    chain = scoring.chain("Passages")
    outing = baseline_scores(
        scoring.observation("Passages"),
        chain.profile,
        scoring.trace_profile(chain.case.trace),
        ModelKind.TOBLER,
    )
    assert outing.control.forecast.generated_at.tzinfo is UTC


# ---------------------------------------------------------------------------
# calibrate (§ 6.4 ; précision de D9.2 ; décision 10)
# ---------------------------------------------------------------------------


def test_calibrate_ignores_entries_that_are_not_members() -> None:
    """§ 6.4, ``calibrate``, point 2 : une entrée de plus dans ``members`` — ici le jour
    évalué lui-même — ne change rien : le calage parcourt ``population.members`` (D9.2 :
    le jour évalué n'entre jamais dans son propre calage)."""
    population = _population(D1, D2)
    members = {
        D1: (_member(100.0, 80.0, "2026-06-01"),),
        D2: (_member(100.0, 120.0, "2026-06-02"),),
    }
    expected = calibrate(population, ModelKind.TOBLER, Scenario.CONTROL, 0, members)
    with_evaluated_day = {**members, J: (_member(100.0, 10.0, "2026-06-16"),)}
    got = calibrate(
        population, ModelKind.TOBLER, Scenario.CONTROL, 0, with_evaluated_day
    )
    assert got == expected


def test_calibrate_follows_the_order_of_the_population() -> None:
    """§ 6.4 : des entrées données dans le désordre — la population effective suit
    ``population.members``."""
    population = _population(D1, D2)
    members = {
        D2: (_member(100.0, 120.0, "2026-06-02"),),
        D1: (_member(100.0, 80.0, "2026-06-01"),),
    }
    calibration = calibrate(population, ModelKind.TOBLER, Scenario.CONTROL, 0, members)
    assert calibration.population == (D1, D2)


def test_a_member_whose_first_outing_has_no_usage() -> None:
    """Précision de D9.2 : une sortie sans scénario d'usage n'a pas de support en usage,
    et n'arrête pas les suivantes — le 2 juin, b2 (sans référence) avant b1 : en usage,
    ``β = ln(ΣT / ΣP)`` sur b1 seule."""
    b1, b2 = _spec("b1-0602"), replace(_spec("b2-0602"), hour=7)
    members = {
        D2: (
            world.outing_scores(b2, ModelKind.V0_RAW),
            world.outing_scores(b1, ModelKind.V0_RAW),
        )
    }
    for i in range(len(CLOCKS)):
        calibration = calibrate(_population(D2), V0, Scenario.USAGE, i, members)
        times = [
            world.clock_times(elapsed, zero_moving=b1.zero_moving)[i]
            for _, elapsed in b1.segments
        ]
        projections = [
            ratio * elapsed
            for ratio, (_, elapsed) in zip(
                b1.usage[ModelKind.V0_RAW], b1.segments, strict=True
            )
        ]
        assert close(
            calibration.beta, math.log(math.fsum(times) / math.fsum(projections))
        )


def test_calibrate_checks_the_model_first() -> None:
    """§ 6.4, préconditions de ``calibrate`` : le modèle avant l'indice d'horloge et
    avant les membres."""
    for clock_index in (0, len(CLOCKS)):
        with pytest.raises(ValueError, match="n'est pas un modèle calé"):
            calibrate(
                _population(D1), ModelKind.V0_RAW, Scenario.CONTROL, clock_index, {}
            )


def test_calibrate_lists_every_member_without_an_entry() -> None:
    """§ 6.4 : « aucune entrée pour les membres [<jours>] », tous les jours manquants,
    avant tout calcul."""
    with pytest.raises(
        ValueError, match=r"aucune entrée pour les membres \[2026-06-01, 2026-06-02\]"
    ):
        calibrate(_population(D1, D2), ModelKind.TOBLER, Scenario.CONTROL, 0, {})


# ---------------------------------------------------------------------------
# calibrated_forecast (§ 6.4, point 3 ; décision 2)
# ---------------------------------------------------------------------------


def test_calibrated_forecast_keeps_the_parameters_of_v0_raw() -> None:
    """§ 6.4 : la provenance est recopiée telle quelle — ``parameters`` compris, que les
    prévisions du monde (``ParameterSet(())``) ne départagent pas."""
    usage = scoring.scores("Passages").usage
    assert usage is not None
    forecast = usage.forecast
    assert forecast.parameters != ParameterSet(())
    effort = math.exp(-0.25)
    calibration = ModelCalibration(
        V0,
        Scenario.USAGE,
        CLOCKS[0],
        (D1,),
        (),
        0.25,
        effort,
        1.0 / effort,
        False,
        None,
    )
    assert calibrated_forecast(forecast, calibration).parameters == forecast.parameters


# ---------------------------------------------------------------------------
# calibrate_performances et calibration_population (§ 6.4 ; § 6)
# ---------------------------------------------------------------------------


def test_calibrate_performances_keeps_the_order_received() -> None:
    """§ 6.4 : « pour chaque performance, dans l'ordre reçu » — ici l'ordre inverse des
    jours."""
    spec = world.SATURATION
    performances = tuple(reversed(world.world_performances(spec)))
    results = calibrate_performances(performances, world.world_scores(spec))
    assert [r.population.civil_date for r in results] == [
        p.civil_date for p in performances
    ]


def test_an_unscored_outing_does_not_stop_the_next() -> None:
    """§ 6.4 : une sortie absente de ``scores`` est sautée ; la suivante de la même
    performance est calée — le 2 juin sans b1 : b2 seule."""
    performances = world.world_performances(world.MONDE)
    scores = world.world_scores(world.MONDE)
    kept = {k: v for k, v in scores.items() if k != "b1-0602"}
    results = calibrate_performances(performances, kept)
    (june_2,) = (r for r in results if r.population.civil_date == D2)
    assert {entry.outing_id for entry in june_2.outings} == {"b2-0602"}


def test_a_member_with_an_unscored_outing_keeps_its_scored_ones() -> None:
    """Décision 10, précision de D9.2 : ``T_c`` et ``P_c`` sur toutes les sorties
    scorées du membre ; une sortie non scorée n'a pas de support, elle ne retire pas
    le membre."""
    scored = world.OutingSpec(
        "u1-0601",
        "2026-06-01",
        world.TRAINING,
        ((world.A, 400.0),),
        control={model: (0.8,) for model in world.UNSCALED},
    )
    unscored = world.OutingSpec(
        "u2-0601",
        "2026-06-01",
        world.TRAINING,
        ((world.F, 300.0),),
        control={model: (1.0,) for model in world.UNSCALED},
        hour=13,
    )
    evaluated = world.OutingSpec(
        "j-0616",
        "2026-06-16",
        world.TRAINING,
        ((world.A, 500.0),),
        control={model: (1.0,) for model in world.UNSCALED},
    )
    spec = world.WorldSpec(
        outings=(scored, unscored, evaluated),
        unscored=frozenset({"u2-0601"}),
        evaluated=("2026-06-16",),
    )
    results = calibrate_performances(
        world.world_performances(spec), world.world_scores(spec)
    )
    (result,) = (r for r in results if r.population.civil_date == J)
    assert result.population.members == (D1,)
    for entry in result.outings:
        calibration = entry.control.clocks[0].calibration
        assert calibration.population == (D1,)
        assert calibration.withdrawals == ()
        assert close(calibration.beta, math.log(1.0 / 0.8))


def test_calibrate_performances_checks_the_four_models_first() -> None:
    """§ 6.4 : « quatre modèles » avant les préconditions de ``calibration_population``
    (deux performances du même jour **et** une sortie sans ses quatre modèles)."""
    performances = world.world_performances(world.MONDE)
    scores = world.world_scores(world.MONDE)
    partial = dict(scores)
    partial["a-0601"] = {
        model: s
        for model, s in scores["a-0601"].items()
        if model is not ModelKind.TOBLER
    }
    with pytest.raises(ValueError, match="a-0601 sans les modèles"):
        calibrate_performances([*performances, performances[1]], partial)


def test_calibrate_performances_reads_and_writes_no_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§ 6 : « aucune fonction de cette PR ne lit ni n'écrit de fichier » — ``open``
    refusé pendant l'assemblage du monde ``Retraits`` (le fuseau de Paris, que
    ``origin`` peut lire au premier appel, chargé avant)."""
    performances = world.world_performances(world.RETRAITS)
    scores = world.world_scores(world.RETRAITS)
    origin(J)

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"open appelé : {args!r}")

    monkeypatch.setattr(builtins, "open", refuse)
    assert calibrate_performances(performances, scores)


def test_the_evaluated_performance_need_not_be_in_the_list() -> None:
    """§ 6.4, ``calibration_population`` : « ``performance`` n'a pas à figurer dans
    ``performances`` »."""
    performances = world.world_performances(world.MONDE)
    (june_16,) = (p for p in performances if p.civil_date == J)
    others = [p for p in performances if p.civil_date != J]
    assert calibration_population(june_16, others) == calibration_population(
        june_16, performances
    )


# ---------------------------------------------------------------------------
# clock_scores (§ 6.3)
# ---------------------------------------------------------------------------


def test_clock_scores_checks_the_base_too() -> None:
    """§ 6.3 : les préconditions de ``score_scenario``, base de ``q_usage`` comprise —
    une prévision de contrôle refusée en base."""
    observation = scoring.observation("Passages")
    scores = scoring.scores("Passages")
    assert scores.usage is not None
    with pytest.raises(ValueError, match="la base de q_usage"):
        clock_scores(
            observation, scores.usage.forecast, 0, base=scores.control.forecast
        )
