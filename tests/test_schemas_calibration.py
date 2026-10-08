"""Contrats du calage (§ 6.2 et § 8.1, test 8, du brief M4c-1 ; ``0010`` D2.4, D2.5,
D9.1, D9.2 ; décisions 5, 8 et 15).

Pour chaque contrat de ``schemas/calibration.py`` : des objets valides, puis une
violation par invariant, refusée par ``ContractError`` avec le fragment du message du
§ 6.2. La relation de ``ModelCalibration`` à ``β`` (facteur d'une baseline, effort de
v0, saturation) se vérifie à ``τ = METRIC_RELATIVE_TOLERANCE`` près, jamais au bit
(décision 15) : elle est éprouvée de part et d'autre de ``τ``. Les calages valides
calculent effort, facteur et saturation par la formule (§ 7.0), sauf les cas aux
bornes exactes. Aussi : ``β`` hors du domaine d'``exp`` (précision 4 de la relecture du
plan), le déplacement de ``ModelKind`` (décision 5), les énumérations,
``EFFORT_BOUNDS`` relié au paramètre ``effort`` du moteur, la place des types dans le
dictionnaire. Les scores calés valides viennent du monde du § 7.1
(``calibrate_performances``) : la vitesse constante du 16 juin, les huit entrées du
18 juin.
"""

import functools
import math
import re
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

import pytest

import mountain_perf.schemas.calibration as calibration_module
import mountain_perf.schemas.registry as registry_module
from fixtures import calibration as world
from mountain_perf.backtest import calibrate_performances
from mountain_perf.model import MODEL_PARAMETER_SPECS
from mountain_perf.schemas import (
    CALIBRATED_MODELS,
    CLOCKS,
    EFFORT_BOUNDS,
    MODEL_KIND_DESCRIPTIONS,
    POPULATION_EXCLUSION_DESCRIPTIONS,
    CalibratedClockScores,
    CalibratedOutingScores,
    CalibratedPerformance,
    CalibratedScenarioScores,
    CalibrationPopulation,
    CalibrationWithdrawal,
    ContractError,
    ModelCalibration,
    ModelKind,
    PopulationExclusion,
    PopulationExclusionReason,
    Scenario,
    Unavailability,
)
from mountain_perf.schemas._dictionary import (
    DOCUMENTED_TYPES,
    ENUM_DESCRIPTIONS,
    render,
)

J = date(2026, 6, 16)
ORIGIN = datetime(2026, 6, 8, 22, 0, tzinfo=UTC)
D1, D2, D3 = date(2026, 6, 1), date(2026, 6, 2), date(2026, 6, 3)
LN2 = math.log(2.0)


def _raises(fragment: str, build: Any, **changes: Any) -> None:
    with pytest.raises(ContractError, match=re.escape(fragment)):
        build(**changes)


# ---------------------------------------------------------------------------
# PopulationExclusion, CalibrationPopulation (D2.4, D2.5)
# ---------------------------------------------------------------------------


def _population(**changes: Any) -> CalibrationPopulation:
    fields: dict[str, Any] = {
        "civil_date": J,
        "origin": ORIGIN,
        "members": (D1, D2),
        "excluded": (PopulationExclusion(D3, PopulationExclusionReason.RACE),),
    }
    return CalibrationPopulation(**(fields | changes))


def test_valid_population_and_exclusion() -> None:
    """D2.4 : une exclusion n'a pas d'invariant au-delà des types ; une population
    valide, et une population vide."""
    exclusion = PopulationExclusion(D3, PopulationExclusionReason.UNLABELLED)
    assert exclusion.reason is PopulationExclusionReason.UNLABELLED
    assert _population().members == (D1, D2)
    assert _population(members=(), excluded=()).members == ()


@pytest.mark.parametrize(
    ("fragment", "changes"),
    [
        ("origin doit porter un fuseau", {"origin": datetime(2026, 6, 8, 22)}),
        ("members doit être une séquence immuable", {"members": [D1, D2]}),
        ("excluded doit être une séquence immuable", {"excluded": []}),
        ("members doit être strictement croissant", {"members": (D2, D1)}),
        ("members doit être strictement croissant", {"members": (D1, D1)}),
        ("doit précéder le jour évalué", {"members": (D1, J)}),
        (
            "excluded doit être strictement croissant",
            {
                "excluded": (
                    PopulationExclusion(D3, PopulationExclusionReason.RACE),
                    PopulationExclusion(D2, PopulationExclusionReason.RACE),
                )
            },
        ),
        (
            "doit précéder le jour évalué",
            {
                "excluded": (
                    PopulationExclusion(
                        date(2026, 6, 17), PopulationExclusionReason.RACE
                    ),
                )
            },
        ),
        ("à la fois membre et exclu", {"members": (D1, D3)}),
    ],
)
def test_population_invariants(fragment: str, changes: dict[str, Any]) -> None:
    """§ 6.2, ``CalibrationPopulation`` : une violation par invariant, dans l'ordre
    (D9.2 : le jour évalué n'entre jamais dans son propre calage)."""
    _raises(fragment, _population, **changes)


# ---------------------------------------------------------------------------
# CalibrationWithdrawal (D9.2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reason", [Unavailability.INSUFFICIENT_SUPPORT, Unavailability.ZERO_TIME]
)
def test_withdrawal_reasons_accepted(reason: Unavailability) -> None:
    assert CalibrationWithdrawal(D1, reason).reason is reason


@pytest.mark.parametrize(
    "reason",
    [
        member
        for member in Unavailability
        if member not in (Unavailability.INSUFFICIENT_SUPPORT, Unavailability.ZERO_TIME)
    ],
)
def test_withdrawal_other_reasons_refused(reason: Unavailability) -> None:
    """D9.2 : un retrait a pour motif le support vide ou le temps nul, rien d'autre
    (une projection invalide n'est jamais un retrait, D7.1)."""
    _raises(
        "insufficient_support ou zero_time",
        CalibrationWithdrawal,
        civil_date=D1,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# ModelCalibration (D9.2 ; décision 15)
# ---------------------------------------------------------------------------


def _baseline(**changes: Any) -> ModelCalibration:
    """Un calage valide : Tobler, contrôle, première horloge, ``β = 0,25``."""
    fields: dict[str, Any] = {
        "model": ModelKind.TOBLER,
        "scenario": Scenario.CONTROL,
        "clock": CLOCKS[0],
        "population": (D1,),
        "withdrawals": (),
        "beta": 0.25,
        "effort": None,
        "factor": math.exp(0.25),
        "saturated": False,
        "unavailability": None,
    }
    return ModelCalibration(**(fields | changes))


def _v0_fields(beta: float) -> dict[str, Any]:
    """v0 + effort recalé à ``β`` : effort, facteur et saturation par la formule."""
    low, high = EFFORT_BOUNDS
    unbounded = math.exp(-beta)
    effort = min(max(unbounded, low), high)
    return {
        "model": ModelKind.V0_RECALIBRATED,
        "beta": beta,
        "effort": effort,
        "factor": 1.0 / effort,
        "saturated": not low <= unbounded <= high,
    }


def _v0(beta: float, **changes: Any) -> ModelCalibration:
    return _baseline(**(_v0_fields(beta) | changes))


def _unavailable(unavailability: Unavailability, **changes: Any) -> ModelCalibration:
    fields: dict[str, Any] = {
        "beta": None,
        "factor": None,
        "unavailability": unavailability,
        "population": () if unavailability is Unavailability.NOT_CALIBRATED else (D1,),
    }
    return _baseline(**(fields | changes))


@pytest.mark.parametrize("beta", [0.0, 0.2, LN2, 1.0, -math.log(1.5), -0.6])
def test_valid_v0_calibrations(beta: float) -> None:
    """D9.2 : v0 + effort recalé, effort ``exp(−β)`` borné, facteur ``1 / effort``,
    saturé si ``exp(−β)`` est hors de ``[0,5 ; 1,5]``."""
    calibration = _v0(beta)
    assert calibration.effort is not None
    assert calibration.factor == 1.0 / calibration.effort


def test_valid_baseline_not_calibrated_and_in_error() -> None:
    """D9.2 : un calage de baseline, un ``non calé`` (population vide, retraits
    publiés), une ``erreur du modèle`` (population non vide)."""
    assert _baseline().factor == math.exp(0.25)
    withdrawal = CalibrationWithdrawal(D1, Unavailability.INSUFFICIENT_SUPPORT)
    not_calibrated = _unavailable(
        Unavailability.NOT_CALIBRATED, withdrawals=(withdrawal,)
    )
    assert not_calibrated.population == ()
    assert _unavailable(Unavailability.MODEL_ERROR).population == (D1,)


VIOLATIONS: list[tuple[str, dict[str, Any]]] = [
    # 1. le modèle
    ("model doit être un modèle calé", {"model": ModelKind.V0_RAW}),
    ("model doit être un modèle calé", {"model": ModelKind.CANDIDATE}),
    # 2. population et retraits
    ("population doit être une séquence immuable", {"population": [D1]}),
    ("withdrawals doit être une séquence immuable", {"withdrawals": []}),
    ("population doit être strictement croissant", {"population": (D2, D1)}),
    (
        "withdrawals doit être strictement croissant",
        {
            "withdrawals": (
                CalibrationWithdrawal(D3, Unavailability.ZERO_TIME),
                CalibrationWithdrawal(D2, Unavailability.ZERO_TIME),
            )
        },
    ),
    (
        "à la fois dans la population et retiré",
        {"withdrawals": (CalibrationWithdrawal(D1, Unavailability.ZERO_TIME),)},
    ),
    # 3. le motif
    *[
        ("unavailability vaut", {"unavailability": member})
        for member in Unavailability
        if member not in (Unavailability.NOT_CALIBRATED, Unavailability.MODEL_ERROR)
    ],
    # 4. non calé si et seulement si la population effective est vide
    ("not_calibrated si et seulement si", {"population": ()}),
    (
        "not_calibrated si et seulement si",
        {"beta": None, "factor": None, "unavailability": Unavailability.NOT_CALIBRATED},
    ),
    (
        "not_calibrated si et seulement si",
        {
            "beta": None,
            "factor": None,
            "population": (),
            "unavailability": Unavailability.MODEL_ERROR,
        },
    ),
    # 5. calé
    ("porte beta et factor", {"beta": None}),
    ("porte beta et factor", {"factor": None}),
    ("beta doit être fini", {"beta": math.nan}),
    ("factor doit être fini", {"factor": math.inf}),
    ("factor doit être > 0", {"factor": 0.0}),
    ("factor doit être > 0", {"factor": -1.0}),
    ("une baseline n'a ni effort ni saturation", {"effort": 1.0}),
    ("une baseline n'a ni effort ni saturation", {"saturated": True}),
    ("exp(beta)", {"factor": math.exp(0.25) * (1 + 1e-9)}),
    ("exp(beta)", {"factor": 5.0}),
    ("effort doit être dans", _v0_fields(0.2) | {"effort": None}),
    (
        "effort doit être dans",
        _v0_fields(LN2)
        | {
            "effort": math.nextafter(0.5, 0.0),
            "factor": 1.0 / math.nextafter(0.5, 0.0),
        },
    ),
    (
        "effort doit être dans",
        _v0_fields(-0.6)
        | {
            "effort": math.nextafter(1.5, 2.0),
            "factor": 1.0 / math.nextafter(1.5, 2.0),
        },
    ),
    (
        "1 / effort",
        _v0_fields(0.2) | {"factor": math.nextafter(1.0 / math.exp(-0.2), math.inf)},
    ),
    ("une saturation met l'effort à une borne", _v0_fields(0.2) | {"saturated": True}),
    ("une saturation met l'effort à une borne", _v0_fields(-0.2) | {"saturated": True}),
    (
        "effort doit valoir",
        _v0_fields(0.2)
        | {
            "effort": math.exp(-0.2) * (1 + 1e-9),
            "factor": 1.0 / (math.exp(-0.2) * (1 + 1e-9)),
        },
    ),
    (
        "effort doit valoir",
        _v0_fields(0.2) | {"effort": 0.5, "factor": 2.0, "saturated": True},
    ),
    ("saturated vaut vrai", _v0_fields(1.0) | {"saturated": False}),
    ("saturated vaut vrai", _v0_fields(-0.6) | {"saturated": False}),
    (
        "saturated vaut vrai",
        _v0_fields(-math.log(0.5 - 2e-12)) | {"saturated": False},
    ),
    # 6. non calé ou en erreur
    (
        "ni beta, ni effort, ni facteur",
        {"population": (), "unavailability": Unavailability.NOT_CALIBRATED},
    ),
    (
        "ni beta, ni effort, ni facteur",
        {"beta": None, "unavailability": Unavailability.MODEL_ERROR},
    ),
    (
        "ni beta, ni effort, ni facteur",
        {
            "beta": None,
            "factor": None,
            "saturated": True,
            "unavailability": Unavailability.MODEL_ERROR,
        },
    ),
    (
        "ni beta, ni effort, ni facteur",
        {
            "beta": None,
            "factor": None,
            "effort": 1.0,
            "unavailability": Unavailability.MODEL_ERROR,
        },
    ),
]


@pytest.mark.parametrize(("fragment", "changes"), VIOLATIONS)
def test_model_calibration_invariants(fragment: str, changes: dict[str, Any]) -> None:
    """§ 6.2, ``ModelCalibration`` : une violation par invariant, dans l'ordre (D9.2 ;
    D9.1 pour le modèle ; décision 15 pour la relation à ``β``, à ``τ`` près)."""
    _raises(fragment, _baseline, **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"beta": 710.0, "factor": 1.0},
        {
            "model": ModelKind.V0_RECALIBRATED,
            "beta": -710.0,
            "effort": 1.5,
            "factor": 1.0 / 1.5,
            "saturated": True,
        },
        {
            "model": ModelKind.V0_RECALIBRATED,
            "beta": 710.0,
            "effort": 0.5,
            "factor": 2.0,
            "saturated": True,
        },
    ],
)
def test_a_beta_outside_the_domain_of_exp_is_refused(
    changes: dict[str, object],
) -> None:
    """Un ``β`` fini dont ``exp(±β)`` déborde : ``ContractError``, jamais
    ``OverflowError`` (le relecteur d'un registre ne convertit que la première)."""
    with pytest.raises(ContractError, match="beta hors du domaine d'exp"):
        _baseline(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"factor": math.nextafter(math.exp(0.25), math.inf)},
        _v0_fields(0.2)
        | {
            "effort": math.nextafter(math.exp(-0.2), math.inf),
            "factor": 1.0 / math.nextafter(math.exp(-0.2), math.inf),
        },
        _v0_fields(LN2) | {"effort": 0.5, "factor": 2.0, "saturated": True},
        _v0_fields(LN2) | {"effort": 0.5, "factor": 2.0, "saturated": False},
        _v0_fields(-math.log(0.5 - 7e-13))
        | {"effort": 0.5, "factor": 2.0, "saturated": False},
        _v0_fields(-math.log(0.5 + 7e-13))
        | {"effort": 0.5, "factor": 2.0, "saturated": True},
    ],
)
def test_the_relation_to_beta_is_checked_within_tau(changes: dict[str, Any]) -> None:
    """Décision 15 : la relation à ``β`` est vérifiée à ``τ = 1e−12`` près, pas au bit —
    un facteur ou un effort d'un ulp acceptés ; la saturation indifférente quand
    ``exp(−β)`` est à une borne à ``τ`` près."""
    assert _baseline(**changes).unavailability is None


# ---------------------------------------------------------------------------
# ModelKind (décision 5), énumérations, constantes
# ---------------------------------------------------------------------------


def test_model_kind_moved_to_the_calibration_contracts() -> None:
    """Décision 5 : ``ModelKind`` change de module, pas de forme ; le registre le
    réimporte."""
    assert vars(registry_module)["ModelKind"] is calibration_module.ModelKind
    assert ModelKind is calibration_module.ModelKind
    assert ModelKind.__module__ == "mountain_perf.schemas.calibration"
    assert "MODEL_KIND_DESCRIPTIONS" not in vars(registry_module)
    assert [member.value for member in ModelKind] == [
        "v0_raw",
        "v0_recalibrated",
        "constant_speed",
        "naismith",
        "tobler",
        "candidate",
    ]


def test_calibrated_models_in_the_order_of_the_protocol() -> None:
    """D9.1 : les quatre modèles calés, dans l'ordre du protocole."""
    assert CALIBRATED_MODELS == (
        ModelKind.V0_RECALIBRATED,
        ModelKind.CONSTANT_SPEED,
        ModelKind.NAISMITH,
        ModelKind.TOBLER,
    )


def test_population_exclusion_reasons() -> None:
    """D2.4 : course, étiquette manquante ; décrites, publiées au dictionnaire."""
    assert [member.value for member in PopulationExclusionReason] == [
        "race",
        "unlabelled",
    ]
    assert list(POPULATION_EXCLUSION_DESCRIPTIONS) == list(PopulationExclusionReason)
    assert ENUM_DESCRIPTIONS[PopulationExclusionReason] is (
        POPULATION_EXCLUSION_DESCRIPTIONS
    )
    assert ENUM_DESCRIPTIONS[ModelKind] is MODEL_KIND_DESCRIPTIONS


def test_effort_bounds_are_those_of_the_engine_parameter() -> None:
    """D9.2, ``0009`` : ``EFFORT_BOUNDS`` vaut ``(0,5 ; 1,5)``, les bornes du paramètre
    ``effort`` du moteur."""
    (effort,) = (spec for spec in MODEL_PARAMETER_SPECS if spec.name == "effort")
    assert EFFORT_BOUNDS == (0.5, 1.5)
    assert (effort.minimum, effort.maximum) == EFFORT_BOUNDS


NEW_TYPES = (
    PopulationExclusionReason,
    PopulationExclusion,
    CalibrationPopulation,
    CalibrationWithdrawal,
    ModelCalibration,
    CalibratedClockScores,
    CalibratedScenarioScores,
    CalibratedOutingScores,
    CalibratedPerformance,
)


def test_new_types_follow_trial_counts_in_the_dictionary() -> None:
    """§ 6.5 : les neuf types, dans l'ordre du brief, après ``TrialCounts`` ;
    ``ModelKind`` garde sa place et change de module."""
    names = [cls.__name__ for cls in DOCUMENTED_TYPES]
    start = names.index("TrialCounts") + 1
    assert tuple(DOCUMENTED_TYPES[start : start + len(NEW_TYPES)]) == NEW_TYPES
    assert names.index("ModelKind") == names.index("EventKind") + 1
    text = render()
    for cls in NEW_TYPES:
        assert f"## `{cls.__name__}`" in text
    assert "*`mountain_perf.schemas.calibration` · énumération*" in text


# ---------------------------------------------------------------------------
# Scores calés (D9.2 ; décision 8) : objets valides du monde (§ 7.1)
# ---------------------------------------------------------------------------


@functools.cache
def _monde() -> dict[date, CalibratedPerformance]:
    spec = world.WORLDS["Monde"]
    results = calibrate_performances(
        world.world_performances(spec), world.world_scores(spec)
    )
    return {result.population.civil_date: result for result in results}


def _outing(model: ModelKind = ModelKind.CONSTANT_SPEED) -> CalibratedOutingScores:
    """Les scores calés d'un modèle sur ``j1-0616`` (16 juin)."""
    (entry,) = (e for e in _monde()[J].outings if e.control.model is model)
    return entry


def test_valid_scored_contracts_from_the_world() -> None:
    """Les contrats des scores calés du monde sont valides : calé et non calé, avec et
    sans usage."""
    outing = _outing()
    assert outing.usage is not None
    assert len(outing.control.clocks) == len(CLOCKS)
    assert len(_monde()[date(2026, 6, 18)].outings) == 8


def test_calibrated_clock_scores_invariants() -> None:
    """§ 6.2, ``CalibratedClockScores`` : scores absents si et seulement si le modèle
    n'est pas calé ; l'horloge des scores est celle du calage."""
    row = _outing().control.clocks[0]
    assert row.scores is not None
    _raises(
        "scores absents si et seulement si",
        CalibratedClockScores,
        calibration=row.calibration,
        scores=None,
    )
    error = _outing(ModelKind.NAISMITH).control.clocks[0]
    assert error.calibration.unavailability is Unavailability.MODEL_ERROR
    _raises(
        "scores absents si et seulement si",
        CalibratedClockScores,
        calibration=error.calibration,
        scores=row.scores,
    )
    other = _outing().control.clocks[1].scores
    _raises(
        "doit être l'horloge du calage",
        CalibratedClockScores,
        calibration=row.calibration,
        scores=other,
    )


def _scenario(**changes: Any) -> CalibratedScenarioScores:
    usage = _outing().usage
    assert usage is not None
    fields: dict[str, Any] = {
        "model": usage.model,
        "scenario": usage.scenario,
        "forecast": usage.forecast,
        "clocks": usage.clocks,
    }
    return CalibratedScenarioScores(**(fields | changes))


def _with_calibration(**changes: Any) -> tuple[CalibratedClockScores, ...]:
    """Les onze horloges de l'usage, la quatrième d'un calage altéré (valide)."""
    clocks = list(_scenario().clocks)
    row = clocks[3]
    clocks[3] = CalibratedClockScores(replace(row.calibration, **changes), row.scores)
    return tuple(clocks)


def test_calibrated_scenario_scores_invariants() -> None:
    """§ 6.2, ``CalibratedScenarioScores`` : un modèle calé ; la prévision du
    scénario ; les onze horloges dans l'ordre de ``CLOCKS`` ; chaque calage du même
    modèle et du même scénario. Aucune enveloppe (décision 8)."""
    clocks = _scenario().clocks
    _raises("model doit être un modèle calé", _scenario, model=ModelKind.V0_RAW)
    _raises("doit valoir scenario", _scenario, forecast=_outing().control.forecast)
    _raises("clocks doit être une séquence immuable", _scenario, clocks=list(clocks))
    _raises(
        "onze horloges dans l'ordre de CLOCKS",
        _scenario,
        clocks=(clocks[1], clocks[0], *clocks[2:]),
    )
    _raises("onze horloges dans l'ordre de CLOCKS", _scenario, clocks=clocks[:10])
    _raises(
        "doit porter le modèle",
        _scenario,
        clocks=_with_calibration(model=ModelKind.NAISMITH),
    )
    _raises(
        "doit porter le modèle",
        _scenario,
        clocks=_with_calibration(scenario=Scenario.CONTROL),
    )
    assert not hasattr(_scenario(), "envelope")


def _outing_with(**changes: Any) -> CalibratedOutingScores:
    outing = _outing()
    fields: dict[str, Any] = {
        "outing_id": outing.outing_id,
        "observation": outing.observation,
        "control": outing.control,
        "usage": outing.usage,
    }
    return CalibratedOutingScores(**(fields | changes))


def test_calibrated_outing_scores_invariants() -> None:
    """§ 6.2, ``CalibratedOutingScores`` : contrôle et usage dans leur scénario, du
    même modèle ; autant de projections que de segments admis."""
    outing = _outing()
    _raises("control porte le scénario contrôle", _outing_with, control=outing.usage)
    _raises("usage porte le scénario usage", _outing_with, usage=outing.control)
    _raises("même modèle", _outing_with, usage=_outing(ModelKind.TOBLER).usage)
    (other,) = (
        e
        for e in _monde()[date(2026, 6, 17)].outings
        if e.control.model is ModelKind.CONSTANT_SPEED
    )
    assert len(other.observation.segments) != len(outing.observation.segments)
    _raises(
        "projections pour",
        _outing_with,
        observation=other.observation,
        usage=None,
    )


def test_calibrated_performance_invariants() -> None:
    """§ 6.2, ``CalibratedPerformance`` : quatre modèles par sortie, dans l'ordre de
    ``CALIBRATED_MODELS`` ; une seule sortie par groupe ; deux groupes de sorties
    distinctes."""
    performance = _monde()[date(2026, 6, 18)]
    entries = performance.outings
    population = performance.population

    def build(outings: Any) -> CalibratedPerformance:
        return CalibratedPerformance(population, outings)

    assert build(entries).outings == entries
    _raises("outings doit être une séquence immuable", build, outings=list(entries))
    _raises("modèles par sortie", build, outings=entries[:7])
    swapped = (entries[1], entries[0], *entries[2:])
    _raises("suivent CALIBRATED_MODELS", build, outings=swapped)
    renamed = (*entries[:3], replace(entries[3], outing_id="j3b-0618"), *entries[4:])
    _raises("une seule sortie", build, outings=renamed)
    _raises("deux groupes", build, outings=(*entries[:4], *entries[:4]))
    assert [e.control.model for e in entries[:4]] == list(CALIBRATED_MODELS)
