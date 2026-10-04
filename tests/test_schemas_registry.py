"""Contrats du registre des expériences (§ 6.1 et § 8.1, test 1, du brief M4b-4 ;
``0010`` D14, D0, D2.5, D2.6, D7.4, D10.1, D10.3, D10.7).

Pour chaque invariant de chaque contrat de ``schemas/registry.py`` : un objet construit
à la main qui le viole (``ContractError``, message), et un objet valide à sa limite.
Constantes et énumérations exactes ; place des types dans le dictionnaire.
"""

import math
import re
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from hypothesis import given

from fixtures import scoring
from fixtures.outings import ATHLETE, PARIS_SUMMER, source
from mountain_perf.backtest import MATCHING_PARAMETER_SPECS, origin
from mountain_perf.model.curve_io import curve_reference
from mountain_perf.model.engine import ENGINE_VERSION, PROJECTION_PARAMETER_SPECS
from mountain_perf.schemas import (
    CLOCKS,
    CURVE_REF_HASH_LENGTH,
    EVENT_KIND_DESCRIPTIONS,
    EXPERIMENT_METRIC_DESCRIPTIONS,
    FAILURE_KIND_DESCRIPTIONS,
    MODEL_KIND_DESCRIPTIONS,
    REFERENCE_SOURCE_DESCRIPTIONS,
    REGISTRY_FORMAT_VERSION,
    ArtifactRef,
    ArtifactRole,
    Declaration,
    DeclaredEffect,
    DeclaredModel,
    DeclaredPerformance,
    DeclaredUsageTarget,
    EventKind,
    Exclusion,
    ExperimentDeclaration,
    ExperimentMetric,
    ExperimentTrials,
    Failure,
    FailureKind,
    FrozenReference,
    MetricValue,
    ModelKind,
    ModelResult,
    Outing,
    OutingOutcome,
    OutingResult,
    ParameterSet,
    Performance,
    ReferenceSource,
    RegistryEvent,
    RegistryLog,
    RepeatabilityRecord,
    Result,
    Scenario,
    SourceRef,
    Sport,
    TargetMember,
    TrialCounts,
    Unavailability,
)
from mountain_perf.schemas._dictionary import (
    DOCUMENTED_TYPES,
    ENUM_DESCRIPTIONS,
    render,
)
from mountain_perf.validation import ContractError
from strategies import source_refs

M = ExperimentMetric
COMMIT = "0123456789abcdef0123456789abcdef01234567"
AT = datetime(2026, 10, 3, 13, 0, tzinfo=UTC)
GENERATED_AT = datetime(2026, 2, 1, 11, 0, tzinfo=UTC)
DAY1, DAY2 = date(2026, 5, 20), date(2026, 5, 27)
HASH, OTHER_HASH = "a" * 64, "b" * 64
PARAMETERS = ParameterSet(PROJECTION_PARAMETER_SPECS)
CSV = ArtifactRef(
    source("csv", "courbe.csv", "1"), GENERATED_AT, ArtifactRole.FORECAST_INPUT
)
META = ArtifactRef(
    source("json", "courbe.meta.json", "2"), GENERATED_AT, ArtifactRole.FORECAST_INPUT
)
CURVE_REF = "courbe.csv#111111111111"
V0 = DeclaredModel(ModelKind.V0_RAW, ENGINE_VERSION, PARAMETERS, None)
RECALIBRATED = DeclaredModel(
    ModelKind.V0_RECALIBRATED, ENGINE_VERSION, PARAMETERS, "calage de D9.2"
)
CANDIDATE = DeclaredModel(ModelKind.CANDIDATE, ENGINE_VERSION, None, "calage et effet")
CALIBRATED = (V0, RECALIBRATED, CANDIDATE)


def _raises(instance: Any, fragment: str, **changes: Any) -> None:
    with pytest.raises(ContractError, match=re.escape(fragment)):
        replace(instance, **changes)


def _outing(
    outing_id: str, day: date, route: str | None = "r1", **changes: Any
) -> Outing:
    start = datetime(day.year, day.month, day.day, 8, 0, tzinfo=UTC)
    fields: dict[str, Any] = dict(
        outing_id=outing_id,
        athlete_ref=ATHLETE,
        sport=Sport.FOOT,
        start_time=start,
        end_time=start + timedelta(hours=2),
        route_id=route,
    )
    fields.update(changes)
    return Outing(**fields)


def _declared(*outings: Outing) -> DeclaredPerformance:
    day = outings[0].start_time.date()
    return DeclaredPerformance(Performance(day, outings), origin(day))


PERFORMANCES = (
    _declared(_outing("q-2026-05-20", DAY1)),
    _declared(_outing("q-2026-05-27", DAY2, route="r2")),
)
DECLARATION = Declaration(
    commit=COMMIT,
    tree_modified=False,
    protocol_record="0010",
    athlete_ref=ATHLETE,
    matching=ParameterSet(MATCHING_PARAMETER_SPECS),
    clocks=CLOCKS,
    curve_ref=CURVE_REF,
    curve=CSV,
    curve_metadata=META,
    manifest=source("manifest", "manifeste.json", "4"),
    performances=PERFORMANCES,
    exclusions=(Exclusion("velo-2026-05-27", "hors domaine : VTT"),),
    models=(V0,),
    experiment=None,
)
EFFECT = DeclaredEffect("arrêts", "temps d'arrêt ajouté", None, "règle de D9.3")
LOCAL = FrozenReference(
    M.DESCENT_LEVEL,
    CLOCKS[0],
    ReferenceSource.LOCAL,
    "r1",
    MetricValue(0.05, None, 2),
    (),
)
BORROWED = FrozenReference(
    M.DESCENT_LEVEL,
    CLOCKS[0],
    ReferenceSource.BORROWED,
    None,
    MetricValue(0.05, None, 2),
    ("r1",),
)
EXPERIMENT = ExperimentDeclaration(
    effect=EFFECT,
    target=M.DESCENT_LEVEL,
    clock=CLOCKS[0],
    scenario=Scenario.USAGE,
    base=ModelKind.V0_RECALIBRATED,
    candidate=ModelKind.CANDIDATE,
    usage_targets=(),
    frozen_references=(LOCAL, BORROWED),
    analysis_date=None,
)
MEMBERS = (TargetMember(0, False), TargetMember(2, False), TargetMember(None, True))
TARGET = DeclaredUsageTarget("r1", MEMBERS, (0.25, 0.25, 0.5))
USAGE_EXPERIMENT = replace(
    EXPERIMENT, target=M.USAGE, usage_targets=(TARGET,), frozen_references=()
)


# ---------------------------------------------------------------------------
# Constantes, énumérations, dictionnaire
# ---------------------------------------------------------------------------


def test_registry_format_version_is_1() -> None:
    """``0010`` D14 : la version du format des événements et des documents."""
    assert REGISTRY_FORMAT_VERSION == 1


def test_curve_ref_hash_length_is_the_m3_rule() -> None:
    """Décision 2 : ``curve_ref`` recopie 12 caractères de l'empreinte, comme
    ``curve_reference`` de M3."""
    assert CURVE_REF_HASH_LENGTH == 12


@pytest.mark.parametrize(
    ("enum", "values"),
    [
        (EventKind, ["declaration", "result", "failure"]),
        (
            ModelKind,
            [
                "v0_raw",
                "v0_recalibrated",
                "constant_speed",
                "naismith",
                "tobler",
                "candidate",
            ],
        ),
        (
            ExperimentMetric,
            [
                "level",
                "ascent_level",
                "flat_level",
                "descent_level",
                "ascent_dispersion",
                "flat_dispersion",
                "descent_dispersion",
                "usage",
            ],
        ),
        (ReferenceSource, ["local", "borrowed"]),
        (FailureKind, ["technical", "not_evaluable"]),
    ],
)
def test_enum_members_in_order(enum: Any, values: list[str]) -> None:
    """``0010`` D14, D9.1, D10.1, D10.3 : membres et valeurs, dans l'ordre."""
    assert [member.value for member in enum] == values


@pytest.mark.parametrize(
    ("enum", "descriptions"),
    [
        (EventKind, EVENT_KIND_DESCRIPTIONS),
        (ModelKind, MODEL_KIND_DESCRIPTIONS),
        (ExperimentMetric, EXPERIMENT_METRIC_DESCRIPTIONS),
        (ReferenceSource, REFERENCE_SOURCE_DESCRIPTIONS),
        (FailureKind, FAILURE_KIND_DESCRIPTIONS),
    ],
)
def test_enum_descriptions_cover_every_member(enum: Any, descriptions: Any) -> None:
    assert list(descriptions) == list(enum)
    assert all(text.strip() for text in descriptions.values())
    assert ENUM_DESCRIPTIONS[enum] is descriptions


NEW_TYPES = (
    EventKind,
    ModelKind,
    ExperimentMetric,
    ReferenceSource,
    FailureKind,
    DeclaredPerformance,
    Exclusion,
    DeclaredModel,
    DeclaredEffect,
    DeclaredUsageTarget,
    FrozenReference,
    ExperimentDeclaration,
    Declaration,
    ModelResult,
    OutingResult,
    RepeatabilityRecord,
    Result,
    Failure,
    RegistryEvent,
    RegistryLog,
    OutingOutcome,
    ExperimentTrials,
    TrialCounts,
)


def test_new_types_follow_repeatability_reference_in_the_dictionary() -> None:
    """§ 6.1 : les 23 types, dans l'ordre du brief, après ``RepeatabilityReference``."""
    names = [cls.__name__ for cls in DOCUMENTED_TYPES]
    start = names.index("RepeatabilityReference") + 1
    assert tuple(DOCUMENTED_TYPES[start : start + len(NEW_TYPES)]) == NEW_TYPES
    text = render()
    for cls in NEW_TYPES:
        assert f"## `{cls.__name__}`" in text


# ---------------------------------------------------------------------------
# DeclaredPerformance (D2.5)
# ---------------------------------------------------------------------------


def test_declared_performance_origin_equal_to_departure_is_refused() -> None:
    """D2.5 : l'origine précède **strictement** le départ de la première sortie."""
    declared = PERFORMANCES[0]
    start = declared.performance.outings[0].start_time
    _raises(declared, "doit précéder strictement le départ", origin=start)


def test_declared_performance_origin_one_microsecond_before_is_accepted() -> None:
    declared = PERFORMANCES[0]
    start = declared.performance.outings[0].start_time
    early = replace(declared, origin=start - timedelta(microseconds=1))
    assert early.origin == start - timedelta(microseconds=1)


def test_declared_performance_origin_after_departure_is_refused() -> None:
    declared = PERFORMANCES[0]
    start = declared.performance.outings[0].start_time
    _raises(declared, "doit précéder strictement", origin=start + timedelta(hours=1))


def test_declared_performance_origin_is_normalized_to_utc() -> None:
    declared = replace(
        PERFORMANCES[0], origin=datetime(2026, 5, 13, 0, 0, tzinfo=PARIS_SUMMER)
    )
    assert declared.origin == datetime(2026, 5, 12, 22, 0, tzinfo=UTC)
    assert declared.origin.tzinfo is UTC


def test_declared_performance_naive_origin_is_refused() -> None:
    _raises(
        PERFORMANCES[0], "origin doit porter un fuseau", origin=datetime(2026, 5, 13)
    )


# ---------------------------------------------------------------------------
# Exclusion, DeclaredModel, DeclaredEffect
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["outing_id", "reason"])
def test_exclusion_texts_not_empty(name: str) -> None:
    _raises(Exclusion("x", "motif"), f"{name} ne doit pas être vide", **{name: " "})


def test_declared_model_needs_parameters_or_rule() -> None:
    """D14 : paramètres fixés ou règle d'estimation, au moins un des deux."""
    _raises(
        V0, "paramètres fixés, une règle d'estimation, ou les deux", parameters=None
    )


def test_declared_model_parameters_alone_rule_alone_or_both() -> None:
    assert V0.estimation_rule is None
    assert replace(V0, parameters=None, estimation_rule="règle").parameters is None
    assert replace(V0, estimation_rule="règle").parameters == PARAMETERS


def test_declared_model_empty_rule_and_version_are_refused() -> None:
    _raises(V0, "estimation_rule ne doit pas être vide", estimation_rule="")
    _raises(V0, "engine_version ne doit pas être vide", engine_version=" ")


def test_declared_effect_needs_parameters_or_rule() -> None:
    """D10.1 : l'effet porte ses paramètres ou sa règle d'estimation."""
    _raises(EFFECT, "un effet déclaré porte des paramètres", estimation_rule=None)
    assert replace(EFFECT, parameters=PARAMETERS).estimation_rule == "règle de D9.3"
    alone = replace(EFFECT, parameters=PARAMETERS, estimation_rule=None)
    assert alone.parameters == PARAMETERS


@pytest.mark.parametrize("name", ["name", "description", "estimation_rule"])
def test_declared_effect_texts_not_empty(name: str) -> None:
    _raises(EFFECT, f"{name} ne doit pas être vide", **{name: ""})


# ---------------------------------------------------------------------------
# DeclaredUsageTarget (D7.4, D10.1)
# ---------------------------------------------------------------------------


def test_usage_target_valid_with_and_without_weights() -> None:
    assert TARGET.weights == (0.25, 0.25, 0.5)
    assert replace(TARGET, weights=None).weights is None


def test_usage_target_form() -> None:
    _raises(TARGET, "route_id ne doit pas être vide", route_id="")
    _raises(TARGET, "members doit être une séquence immuable", members=list(MEMBERS))
    _raises(TARGET, "weights doit être une séquence immuable", weights=[0.5, 0.5, 0.0])


def test_usage_target_members_not_empty() -> None:
    _raises(TARGET, "members ne doit pas être vide", members=(), weights=None)


@pytest.mark.parametrize(
    ("members", "ranks"),
    [
        ((TargetMember(None, True), TargetMember(0, False)), "[0] sur 2"),
        ((TargetMember(0, True), TargetMember(None, True)), "[0, 1] sur 2"),
        ((TargetMember(0, False), TargetMember(1, False)), "[] sur 2"),
    ],
    ids=["arrival-first", "two-arrivals", "no-arrival"],
)
def test_usage_target_arrival_is_last_and_only(
    members: tuple[TargetMember, ...], ranks: str
) -> None:
    """D7.4 : le dernier élément est l'arrivée, et lui seul (la règle et le message
    d'``OutingObservation``)."""
    _raises(
        TARGET,
        f"le dernier membre de K est l'arrivée, et lui seul, reçu l'arrivée aux rangs "
        f"{ranks}",
        members=members,
        weights=None,
    )


def test_usage_target_equal_ranks_are_refused() -> None:
    members = (TargetMember(2, False), TargetMember(2, False), TargetMember(None, True))
    _raises(TARGET, "strictement croissants, reçu 2 puis 2", members=members)


def test_usage_target_arrival_rank_must_increase() -> None:
    members = (TargetMember(0, False), TargetMember(2, False), TargetMember(2, True))
    _raises(TARGET, "strictement croissants, reçu 2 puis 2", members=members)


def test_usage_target_increasing_ranks_with_ranked_arrival_are_accepted() -> None:
    members = (TargetMember(0, False), TargetMember(2, False), TargetMember(3, True))
    assert replace(TARGET, members=members).members == members


def test_usage_target_weights_length() -> None:
    _raises(
        TARGET, "weights (2) et members (3) ont la même longueur", weights=(0.5, 0.5)
    )


def test_usage_target_negative_weight() -> None:
    _raises(TARGET, "weights[1] doit être >= 0", weights=(0.75, -0.25, 0.5))


@pytest.mark.parametrize("bad", [math.nan, math.inf])
def test_usage_target_non_finite_weight(bad: float) -> None:
    _raises(TARGET, "weights[2] doit être fini", weights=(0.25, 0.25, bad))


def test_usage_target_weight_sum_tolerance() -> None:
    """D7.4 : somme à 1 à ``WEIGHT_SUM_TOLERANCE`` près, écrite comme ``UsageTarget``
    de M4b-1 : ``1 + 4e−9`` refusée, ``1 + 5e−10`` acceptée."""
    _raises(
        TARGET, "les poids somment à 1 à 1e-09 près", weights=(0.25, 0.25, 0.5 + 4e-9)
    )
    accepted = replace(TARGET, weights=(0.25, 0.25, 0.5 + 5e-10))
    assert accepted.weights == (0.25, 0.25, 0.5 + 5e-10)


# ---------------------------------------------------------------------------
# FrozenReference (D10.3)
# ---------------------------------------------------------------------------


def test_frozen_reference_valid_local_and_borrowed() -> None:
    assert LOCAL.route_id == "r1"
    assert BORROWED.donors == ("r1",)


def test_frozen_reference_q_usage_is_refused() -> None:
    """D10.3 : ``q_usage`` a un seuil fixe, pas de référence figée."""
    _raises(LOCAL, "q_usage n'a pas de référence figée", metric=M.USAGE)


def test_frozen_reference_local_needs_a_route() -> None:
    _raises(LOCAL, "une référence locale nomme son parcours", route_id=None)
    _raises(LOCAL, "route_id ne doit pas être vide", route_id=" ")


def test_frozen_reference_local_has_no_donor() -> None:
    _raises(LOCAL, "une référence locale n'a pas de donneur", donors=("r2",))


def test_frozen_reference_borrowed_has_no_route() -> None:
    _raises(BORROWED, "une référence empruntée ne nomme pas de parcours", route_id="r2")


def test_frozen_reference_borrowed_needs_donors() -> None:
    _raises(BORROWED, "une référence empruntée a au moins un donneur", donors=())


def test_frozen_reference_donors_named_and_distinct() -> None:
    _raises(
        BORROWED,
        "les donneurs sont distincts, reçu 'r1' deux fois",
        donors=("r1", "r1"),
    )
    _raises(BORROWED, "donors[1] ne doit pas être vide", donors=("r1", ""))
    _raises(BORROWED, "donors doit être une séquence immuable", donors=["r1"])


# ---------------------------------------------------------------------------
# ExperimentDeclaration (D10.1, D10.3, D10.7)
# ---------------------------------------------------------------------------


def test_experiment_valid_with_analysis_date() -> None:
    """D10.7 : une date d'analyse fixée d'avance est acceptée."""
    dated = replace(EXPERIMENT, analysis_date=date(2026, 12, 1))
    assert dated.analysis_date == date(2026, 12, 1)


@pytest.mark.parametrize("name", ["usage_targets", "frozen_references"])
def test_experiment_sequences_are_tuples(name: str) -> None:
    _raises(EXPERIMENT, f"{name} doit être une séquence immuable", **{name: []})


def test_experiment_level_is_not_a_target() -> None:
    """D10.1 : ``|L|`` n'est pas une cible."""
    _raises(EXPERIMENT, "|L| n'est pas une cible (D10.1).", target=M.LEVEL)


def test_experiment_base_is_v0_recalibrated() -> None:
    """D10.1 : base ``(0)`` = v0 + effort recalé."""
    _raises(EXPERIMENT, "la base (0) est v0 + effort recalé", base=ModelKind.V0_RAW)


def test_experiment_candidate_is_candidate() -> None:
    _raises(
        EXPERIMENT,
        "le candidat (1) est CANDIDATE (D10.1), reçu v0_recalibrated",
        candidate=ModelKind.V0_RECALIBRATED,
    )


def test_experiment_k_only_for_q_usage() -> None:
    """D10.1 : ``K`` et poids si ``q_usage``."""
    _raises(
        EXPERIMENT,
        "un K déclaré n'existe que pour la cible q_usage",
        usage_targets=(TARGET,),
    )


def test_experiment_q_usage_only_in_usage() -> None:
    """D7.4 : ``q_usage`` ne se calcule qu'en usage ; refusée sous le contrôle."""
    _raises(
        USAGE_EXPERIMENT,
        "la cible q_usage ne se calcule qu'en usage (D7.4), reçu le scénario control",
        scenario=Scenario.CONTROL,
    )


def test_experiment_q_usage_in_usage_and_descent_in_control_are_accepted() -> None:
    assert USAGE_EXPERIMENT.usage_targets == (TARGET,)
    control = replace(EXPERIMENT, scenario=Scenario.CONTROL)
    assert control.target is M.DESCENT_LEVEL


def test_experiment_k_routes_distinct() -> None:
    _raises(
        USAGE_EXPERIMENT,
        "les K déclarés portent sur des parcours distincts, reçu 'r1' deux fois",
        usage_targets=(TARGET, TARGET),
    )


def test_experiment_frozen_reference_keys_distinct() -> None:
    _raises(
        EXPERIMENT,
        "les références figées ont des clés (metric, clock, source, route_id) "
        "distinctes",
        frozen_references=(LOCAL, replace(LOCAL, value=MetricValue(0.07, None, 3))),
    )


def test_experiment_same_route_two_metrics_are_distinct_keys() -> None:
    ascent = replace(LOCAL, metric=M.ASCENT_LEVEL)
    assert (
        len(replace(EXPERIMENT, frozen_references=(LOCAL, ascent)).frozen_references)
        == 2
    )


DONOR_MESSAGE = "le donneur 'r1' de la référence empruntée de descent_level sous "


def test_experiment_donor_without_local_reference() -> None:
    """D10.3 : chaque donneur a une référence locale disponible, même métrique et même
    horloge."""
    _raises(EXPERIMENT, DONOR_MESSAGE, frozen_references=(BORROWED,))


def test_experiment_donor_with_unavailable_local_reference() -> None:
    unavailable = replace(
        LOCAL, value=MetricValue(None, Unavailability.INSUFFICIENT_SUPPORT, 1)
    )
    _raises(EXPERIMENT, DONOR_MESSAGE, frozen_references=(unavailable, BORROWED))


def test_experiment_donor_with_local_reference_under_another_clock() -> None:
    other_clock = replace(LOCAL, clock=CLOCKS[1])
    _raises(EXPERIMENT, DONOR_MESSAGE, frozen_references=(other_clock, BORROWED))


def test_experiment_donor_with_local_reference_of_another_metric() -> None:
    other_metric = replace(LOCAL, metric=M.DESCENT_DISPERSION)
    _raises(EXPERIMENT, DONOR_MESSAGE, frozen_references=(other_metric, BORROWED))


# ---------------------------------------------------------------------------
# Declaration (D14, D2.6, D10.1)
# ---------------------------------------------------------------------------


def test_declaration_valid_and_properties() -> None:
    """D14 : la déclaration de v0 brut ; sorties et parcours déclarés."""
    assert DECLARATION.outing_ids == ("q-2026-05-20", "q-2026-05-27")
    assert DECLARATION.route_ids == frozenset({"r1", "r2"})
    assert DECLARATION.artifacts == (CSV, META)


def test_declaration_with_experiment_is_valid() -> None:
    declaration = replace(DECLARATION, models=CALIBRATED, experiment=EXPERIMENT)
    assert declaration.experiment == EXPERIMENT


@pytest.mark.parametrize("name", ["protocol_record", "athlete_ref", "curve_ref"])
def test_declaration_texts_not_empty(name: str) -> None:
    _raises(DECLARATION, f"{name} ne doit pas être vide", **{name: ""})


@pytest.mark.parametrize("name", ["clocks", "performances", "exclusions", "models"])
def test_declaration_sequences_are_tuples(name: str) -> None:
    _raises(
        DECLARATION,
        f"{name} doit être une séquence immuable",
        **{name: list(getattr(DECLARATION, name))},
    )


@pytest.mark.parametrize(
    "commit", [COMMIT[:39], COMMIT.upper(), COMMIT[:39] + "g"], ids=["39", "upper", "g"]
)
def test_declaration_commit_is_40_lowercase_hex(commit: str) -> None:
    """D14 : le commit du code exécuté, 40 caractères hexadécimaux minuscules."""
    _raises(DECLARATION, "commit doit porter 40 caractères hexadécimaux", commit=commit)


def test_declaration_clocks_not_empty() -> None:
    _raises(DECLARATION, "clocks ne doit pas être vide", clocks=())


@pytest.mark.parametrize(
    ("clocks", "ranks"),
    [((CLOCKS[1], CLOCKS[0]), "1 puis 0"), ((CLOCKS[0], CLOCKS[0]), "0 puis 0")],
    ids=["inverted", "repeated"],
)
def test_declaration_clocks_follow_clocks_order(clocks: Any, ranks: str) -> None:
    """D14 : les horloges de l'exécution, sous-suite de ``CLOCKS`` sans doublon."""
    _raises(DECLARATION, f"sans doublon, reçu les rangs {ranks}", clocks=clocks)


def test_declaration_clock_outside_clocks_is_refused() -> None:
    _raises(DECLARATION, "n'est pas une des onze horloges", clocks=("elapsed",))


def test_declaration_clock_subsequence_is_accepted() -> None:
    assert replace(DECLARATION, clocks=(CLOCKS[0], CLOCKS[3])).clocks[1] == CLOCKS[3]


@pytest.mark.parametrize("name", ["curve", "curve_metadata"])
def test_declaration_curve_roles_are_forecast_inputs(name: str) -> None:
    """D2.6, décision 2 : la courbe et son compagnon sont des entrées de prévision."""
    observation = replace(
        getattr(DECLARATION, name), role=ArtifactRole.EVALUATION_OBSERVATION
    )
    _raises(DECLARATION, f"{name}.role doit être FORECAST_INPUT", **{name: observation})


def test_declaration_curve_ref_names_the_declared_csv() -> None:
    """Décision 2 : ``curve_ref`` d'une autre empreinte est refusé."""
    _raises(
        DECLARATION,
        "curve_ref ('courbe.csv#222222222222') doit nommer le CSV déclaré",
        curve_ref="courbe.csv#222222222222",
    )


@given(source_refs())
def test_declaration_curve_ref_rule_is_curve_reference(csv_source: SourceRef) -> None:
    """Décision 2 : la règle de ``curve_ref`` est celle de ``curve_reference`` (M3)
    pour toute source ; une autre empreinte est refusée."""
    csv = ArtifactRef(csv_source, GENERATED_AT, ArtifactRole.FORECAST_INPUT)
    declaration = replace(DECLARATION, curve=csv, curve_ref=curve_reference(csv_source))
    assert declaration.curve_ref == curve_reference(csv_source)
    digest = csv_source.content_hash
    other = replace(
        csv_source, content_hash=("1" if digest[0] == "0" else "0") + digest[1:]
    )
    _raises(declaration, "doit nommer le CSV déclaré", curve_ref=curve_reference(other))


def test_declaration_two_performances_same_day() -> None:
    """D0 : une performance par jour civil, jours strictement croissants."""
    twin = _declared(_outing("autre", DAY1))
    _raises(
        DECLARATION,
        "par jour civil strictement croissant, reçu 2026-05-20 puis 2026-05-20",
        performances=(PERFORMANCES[0], twin),
    )


def test_declaration_performances_inverted() -> None:
    _raises(
        DECLARATION,
        "reçu 2026-05-27 puis 2026-05-20",
        performances=(PERFORMANCES[1], PERFORMANCES[0]),
    )


def test_declaration_same_outing_id_on_two_days() -> None:
    again = _declared(_outing("q-2026-05-20", DAY2))
    _raises(
        DECLARATION,
        "les identifiants de sortie sont distincts sur toutes les performances, reçu "
        "'q-2026-05-20' deux fois",
        performances=(PERFORMANCES[0], again),
    )


def test_declaration_outing_of_another_athlete() -> None:
    """D2.6 : une sortie d'un autre athlète que celui de la courbe est refusée."""
    other = _declared(_outing("q-2026-05-27", DAY2, athlete_ref="athlete-2"))
    _raises(
        DECLARATION,
        "la sortie 'q-2026-05-27' est d'un autre athlète",
        performances=(PERFORMANCES[0], other),
    )


def test_declaration_two_exclusions_of_the_same_outing() -> None:
    twice = (Exclusion("x", "motif"), Exclusion("x", "autre motif"))
    _raises(
        DECLARATION, "deux exclusions nomment la même sortie, 'x'", exclusions=twice
    )


def test_declaration_exclusion_may_name_a_declared_outing() -> None:
    """Non promis : exclue d'une règle, pas du registre."""
    declared = replace(DECLARATION, exclusions=(Exclusion("q-2026-05-20", "course"),))
    assert declared.exclusions[0].outing_id in declared.outing_ids


def test_declaration_models_not_empty_nor_repeated() -> None:
    _raises(DECLARATION, "models ne doit pas être vide", models=())
    _raises(
        DECLARATION,
        "les modèles déclarés ont des natures distinctes, reçu v0_raw deux fois",
        models=(V0, replace(V0, estimation_rule="règle")),
    )


def test_declaration_experiment_base_is_declared() -> None:
    """D10.1 : la base et le candidat sont des modèles déclarés."""
    _raises(
        DECLARATION,
        "experiment.base (v0_recalibrated) doit être un modèle déclaré",
        models=(V0, CANDIDATE),
        experiment=EXPERIMENT,
    )


def test_declaration_experiment_candidate_is_declared() -> None:
    _raises(
        DECLARATION,
        "experiment.candidate (candidate) doit être un modèle déclaré",
        models=(V0, RECALIBRATED),
        experiment=EXPERIMENT,
    )


def test_declaration_experiment_clock_is_declared() -> None:
    _raises(
        DECLARATION,
        "l'horloge de la cible (",
        clocks=(CLOCKS[0],),
        models=CALIBRATED,
        experiment=replace(EXPERIMENT, clock=CLOCKS[1]),
    )


def test_declaration_frozen_reference_clock_is_declared() -> None:
    later = replace(LOCAL, clock=CLOCKS[2])
    _raises(
        DECLARATION,
        "l'horloge de la référence figée 0 (",
        clocks=(CLOCKS[0], CLOCKS[1]),
        models=CALIBRATED,
        experiment=replace(EXPERIMENT, frozen_references=(later,)),
    )


def test_declaration_k_route_is_declared() -> None:
    _raises(
        DECLARATION,
        "le K du parcours 'r9' doit porter sur un parcours des performances déclarées",
        models=CALIBRATED,
        experiment=replace(
            USAGE_EXPERIMENT, usage_targets=(replace(TARGET, route_id="r9"),)
        ),
    )


def test_declaration_k_route_declared_is_accepted() -> None:
    declared = replace(DECLARATION, models=CALIBRATED, experiment=USAGE_EXPERIMENT)
    assert declared.experiment is not None


# ---------------------------------------------------------------------------
# ModelResult, OutingResult, RepeatabilityRecord, Result, Failure
# ---------------------------------------------------------------------------

MODEL_RESULT = ModelResult(ModelKind.V0_RAW, HASH, OTHER_HASH)
COVERAGE = scoring.chain("Régimes").match.coverage
OUTING_RESULT = OutingResult("q-2026-05-20", COVERAGE, HASH, (MODEL_RESULT,))


def test_model_result_hashes() -> None:
    assert replace(MODEL_RESULT, usage=None).usage is None
    _raises(MODEL_RESULT, "control doit être un sha256", control="A" * 64)
    _raises(MODEL_RESULT, "usage doit être un sha256", usage="a" * 63)


def test_outing_result_form() -> None:
    _raises(OUTING_RESULT, "outing_id ne doit pas être vide", outing_id="")
    _raises(OUTING_RESULT, "observation doit être un sha256", observation="x")
    _raises(
        OUTING_RESULT, "models doit être une séquence immuable", models=[MODEL_RESULT]
    )


def test_outing_result_models_not_empty_and_distinct() -> None:
    _raises(OUTING_RESULT, "models ne doit pas être vide", models=())
    _raises(
        OUTING_RESULT,
        "les modèles d'une sortie scorée sont distincts, reçu v0_raw deux fois",
        models=(MODEL_RESULT, MODEL_RESULT),
    )


def test_outing_result_usage_for_all_models_or_none() -> None:
    """D3 : l'usage existe pour tous les modèles d'une sortie ou pour aucun."""
    naismith = ModelResult(ModelKind.NAISMITH, HASH, None)
    _raises(
        OUTING_RESULT,
        "l'usage est présent pour tous les modèles ou pour aucun",
        models=(MODEL_RESULT, naismith),
    )
    both = (replace(MODEL_RESULT, usage=None), naismith)
    assert replace(OUTING_RESULT, models=both).models == both


def test_repeatability_record_form() -> None:
    record = RepeatabilityRecord("r1", HASH)
    _raises(record, "route_id ne doit pas être vide", route_id="")
    _raises(record, "reference doit être un sha256", reference="b" * 65)


RESULT = Result((OUTING_RESULT,), (Exclusion("p-2026-06-03", "trace illisible"),), ())


@pytest.mark.parametrize("name", ["outings", "unscored", "references"])
def test_result_sequences_are_tuples(name: str) -> None:
    _raises(RESULT, f"{name} doit être une séquence immuable", **{name: []})


def test_result_outing_scored_and_unscored_is_refused() -> None:
    """D0 : une sortie déclarée a un sort, un seul."""
    _raises(
        RESULT,
        "une sortie est scorée ou écartée, une seule fois, reçu 'q-2026-05-20' deux "
        "fois",
        unscored=(Exclusion("q-2026-05-20", "motif"),),
    )
    _raises(
        RESULT, "reçu 'q-2026-05-20' deux fois", outings=(OUTING_RESULT, OUTING_RESULT)
    )


def test_result_reference_routes_distinct() -> None:
    record = RepeatabilityRecord("r1", HASH)
    _raises(
        RESULT,
        "les références D8 portent sur des parcours distincts, reçu 'r1' deux fois",
        references=(record, replace(record, reference=OTHER_HASH)),
    )
    assert replace(RESULT, references=(record,)).references == (record,)


def test_failure_reason_not_empty() -> None:
    """D14 : un ÉCHEC dit son motif."""
    failure = Failure(FailureKind.NOT_EVALUABLE, "aucune performance évaluable")
    _raises(failure, "reason ne doit pas être vide", reason=" ")
    assert replace(failure, kind=FailureKind.TECHNICAL).kind is FailureKind.TECHNICAL


# ---------------------------------------------------------------------------
# RegistryEvent (D14)
# ---------------------------------------------------------------------------

FAILURE = Failure(FailureKind.TECHNICAL, "trace illisible")


def _event(
    number: int,
    kind: EventKind,
    *,
    answers: int | None = None,
    corrects: int | None = None,
    reason: str | None = None,
    at: datetime = AT,
) -> RegistryEvent:
    return RegistryEvent(
        format_version=REGISTRY_FORMAT_VERSION,
        number=number,
        kind=kind,
        recorded_at=at,
        previous_hash=None if number == 1 else HASH,
        answers=answers,
        corrects=corrects,
        correction_reason=reason,
        declaration=DECLARATION if kind is EventKind.DECLARATION else None,
        result=RESULT if kind is EventKind.RESULT else None,
        failure=FAILURE if kind is EventKind.FAILURE else None,
    )


DECLARED = _event(1, EventKind.DECLARATION)
ANSWER = _event(2, EventKind.RESULT, answers=1)
CORRECTION = _event(3, EventKind.RESULT, answers=1, corrects=2, reason="erreur")


def test_event_valid_limits() -> None:
    """D14 : une réponse à la déclaration qui la précède, une correction de
    l'événement qui la précède."""
    assert ANSWER.answers == ANSWER.number - 1
    assert CORRECTION.corrects == CORRECTION.number - 1
    assert _event(2, EventKind.FAILURE, answers=1).failure == FAILURE


def test_event_recorded_at_is_normalized_to_utc() -> None:
    event = replace(
        DECLARED, recorded_at=datetime(2026, 10, 3, 15, 0, tzinfo=PARIS_SUMMER)
    )
    assert event.recorded_at == AT
    assert event.recorded_at.tzinfo is UTC


@pytest.mark.parametrize(
    ("instance", "changes", "fragment"),
    [
        (DECLARED, {"format_version": 2}, "format_version vaut 1, reçu 2"),
        (
            DECLARED,
            {"number": 0, "previous_hash": HASH},
            "number est un rang à partir de 1, reçu 0",
        ),
        (
            ANSWER,
            {"previous_hash": None},
            "previous_hash est absent si et seulement si l'événement est le premier, "
            "reçu number=2 et previous_hash absent",
        ),
        (
            DECLARED,
            {"previous_hash": HASH},
            "reçu number=1 et previous_hash présent",
        ),
        (ANSWER, {"previous_hash": "A" * 64}, "previous_hash doit être un sha256"),
        (
            ANSWER,
            {"declaration": DECLARATION},
            "un événement result porte le contenu de son type, et lui seul, reçu "
            "['declaration', 'result']",
        ),
        (ANSWER, {"result": None}, "un événement result porte le contenu de son type"),
        (
            ANSWER,
            {"result": None, "failure": FAILURE},
            "un événement result porte le contenu de son type, et lui seul, reçu "
            "['failure']",
        ),
        (
            _event(2, EventKind.DECLARATION),
            {"answers": 1},
            "answers est présent si et seulement si l'événement est un résultat ou un "
            "échec, reçu declaration et answers=1",
        ),
        (ANSWER, {"answers": None}, "reçu result et answers=None"),
        (
            ANSWER,
            {"answers": 2},
            "answers (2) nomme une déclaration qui précède l'événement 2",
        ),
        (ANSWER, {"answers": 0}, "answers (0) nomme une déclaration qui précède"),
        (
            CORRECTION,
            {"corrects": 3},
            "corrects (3) nomme un événement qui précède l'événement 3",
        ),
        (CORRECTION, {"corrects": 0}, "corrects (0) nomme un événement qui précède"),
        (
            ANSWER,
            {"correction_reason": "motif"},
            "correction_reason est présent si et seulement si corrects l'est",
        ),
        (
            CORRECTION,
            {"correction_reason": None},
            "correction_reason est présent si et seulement si corrects l'est",
        ),
        (
            CORRECTION,
            {"correction_reason": " "},
            "correction_reason ne doit pas être vide",
        ),
        (
            DECLARED,
            {"recorded_at": datetime(2026, 10, 3, 13)},
            "recorded_at doit porter un fuseau",
        ),
    ],
    ids=[
        "format-2",
        "number-0",
        "hash-absent-at-2",
        "hash-present-at-1",
        "hash-malformed",
        "two-contents",
        "no-content",
        "other-content",
        "answers-on-declaration",
        "answers-absent-on-result",
        "answers-equal-number",
        "answers-zero",
        "corrects-equal-number",
        "corrects-zero",
        "reason-without-correction",
        "correction-without-reason",
        "reason-empty",
        "naive-instant",
    ],
)
def test_event_invariants(
    instance: RegistryEvent, changes: dict[str, Any], fragment: str
) -> None:
    """D14 : les huit invariants d'un événement, dans l'ordre du § 6.1."""
    _raises(instance, fragment, **changes)


# ---------------------------------------------------------------------------
# RegistryLog (D14)
# ---------------------------------------------------------------------------


def test_log_valid_and_methods() -> None:
    log = RegistryLog((DECLARED, ANSWER))
    assert log.event(2) is ANSWER
    assert log.answer(1) is ANSWER
    assert log.in_force(2)
    assert log.corrected_by(2) is None
    assert log.answer(2) is None


def test_log_events_are_a_tuple() -> None:
    _raises(
        RegistryLog(()), "events doit être une séquence immuable", events=[DECLARED]
    )


def test_log_numbers_are_ranks() -> None:
    """D14 : le numéro d'un événement est son rang dans le journal."""
    _raises(
        RegistryLog(()),
        "events[1] porte le numéro 3, 2 attendu",
        events=(DECLARED, replace(ANSWER, number=3)),
    )


def test_log_time_does_not_go_back() -> None:
    later = replace(DECLARED, recorded_at=AT + timedelta(minutes=5))
    _raises(
        RegistryLog(()),
        "recorded_at de l'événement 2 (2026-10-03T13:00:00+00:00) précède celui de "
        "l'événement 1 (2026-10-03T13:05:00+00:00)",
        events=(later, ANSWER),
    )


def test_log_equal_times_are_accepted() -> None:
    assert RegistryLog((DECLARED, ANSWER)).events[1].recorded_at == AT


def test_log_answer_to_a_result_is_refused() -> None:
    """D14 : un résultat ou un échec répond à une DÉCLARATION."""
    _raises(
        RegistryLog(()),
        "l'événement 3 répond à l'événement 2, qui n'est pas une déclaration",
        events=(DECLARED, ANSWER, _event(3, EventKind.FAILURE, answers=2)),
    )


def test_log_second_answer_is_refused() -> None:
    """Décision 4 : une déclaration reçoit au plus une réponse qui n'en corrige pas une
    autre."""
    _raises(
        RegistryLog(()),
        "la déclaration 1 a déjà une réponse (événement 2)",
        events=(DECLARED, ANSWER, _event(3, EventKind.FAILURE, answers=1)),
    )


def test_log_correction_of_another_kind_is_refused_both_ways() -> None:
    """Décision 4 : une correction est un événement du même type."""
    failure = _event(2, EventKind.FAILURE, answers=1)
    _raises(
        RegistryLog(()),
        "l'événement 3 (failure) corrige l'événement 2 (result) : une correction vise "
        "un événement du même type",
        events=(
            DECLARED,
            ANSWER,
            _event(3, EventKind.FAILURE, answers=1, corrects=2, reason="r"),
        ),
    )
    _raises(
        RegistryLog(()),
        "l'événement 3 (result) corrige l'événement 2 (failure)",
        events=(DECLARED, failure, CORRECTION),
    )
    _raises(
        RegistryLog(()),
        "l'événement 3 (declaration) corrige l'événement 2 (result)",
        events=(
            DECLARED,
            ANSWER,
            _event(3, EventKind.DECLARATION, corrects=2, reason="r"),
        ),
    )


def test_log_correction_of_an_answer_to_another_declaration_is_refused() -> None:
    second = _event(2, EventKind.DECLARATION)
    answer = _event(3, EventKind.RESULT, answers=2)
    wrong = _event(4, EventKind.RESULT, answers=1, corrects=3, reason="r")
    _raises(
        RegistryLog(()),
        "l'événement 4 répond à la déclaration 1 et corrige l'événement 3, qui répond "
        "à la déclaration 2",
        events=(DECLARED, second, answer, wrong),
    )


def test_log_second_correction_is_refused() -> None:
    again = _event(4, EventKind.RESULT, answers=1, corrects=2, reason="encore")
    _raises(
        RegistryLog(()),
        "l'événement 2 est déjà corrigé (événement 3)",
        events=(DECLARED, ANSWER, CORRECTION, again),
    )


def test_log_declaration_corrected_by_a_declaration_is_accepted() -> None:
    log = RegistryLog(
        (DECLARED, _event(2, EventKind.DECLARATION, corrects=1, reason="r"))
    )
    assert log.corrected_by(1) == 2


def test_log_methods_on_a_chain_of_two_corrections() -> None:
    """D14 : la réponse en vigueur est la dernière de la chaîne des corrections."""
    last = _event(4, EventKind.RESULT, answers=1, corrects=3, reason="encore")
    log = RegistryLog((DECLARED, ANSWER, CORRECTION, last))
    assert [log.corrected_by(n) for n in (1, 2, 3, 4)] == [None, 3, 4, None]
    assert [log.in_force(n) for n in (1, 2, 3, 4)] == [True, False, False, True]
    assert log.answer(1) is last


@pytest.mark.parametrize("number", [0, 3])
def test_log_event_and_in_force_out_of_bounds(number: int) -> None:
    log = RegistryLog((DECLARED, ANSWER))
    with pytest.raises(IndexError, match=f"aucun événement de numéro {number}"):
        log.event(number)
    with pytest.raises(IndexError, match=f"aucun événement de numéro {number}"):
        log.in_force(number)


# ---------------------------------------------------------------------------
# OutingOutcome (D7.1)
# ---------------------------------------------------------------------------

SCORES = scoring.scores("Régimes")
OUTCOME = OutingOutcome("q-2026-05-20", COVERAGE, ((ModelKind.V0_RAW, SCORES),))


def test_outcome_same_observation_under_two_models_is_accepted() -> None:
    both = ((ModelKind.V0_RAW, SCORES), (ModelKind.NAISMITH, SCORES))
    assert replace(OUTCOME, scores=both).scores == both


def test_outcome_form() -> None:
    _raises(OUTCOME, "outing_id ne doit pas être vide", outing_id="")
    _raises(
        OUTCOME, "scores doit être une séquence immuable", scores=[OUTCOME.scores[0]]
    )
    _raises(
        OUTCOME,
        "scores[0] doit être une séquence immuable",
        scores=([ModelKind.V0_RAW, SCORES],),
    )
    _raises(
        OUTCOME,
        "scores[0] est un couple (modèle, scores), reçu 3 éléments",
        scores=((ModelKind.V0_RAW, SCORES, SCORES),),
    )


def test_outcome_scores_not_empty() -> None:
    _raises(OUTCOME, "scores ne doit pas être vide", scores=())


def test_outcome_models_distinct() -> None:
    _raises(
        OUTCOME,
        "les modèles d'une sortie sont distincts, reçu v0_raw deux fois",
        scores=((ModelKind.V0_RAW, SCORES), (ModelKind.V0_RAW, SCORES)),
    )


def test_outcome_one_observation_for_all_models() -> None:
    """D7.1 : le support ne dépend que de l'observation."""
    other = scoring.scores("Passages")
    _raises(
        OUTCOME,
        "les scores de naismith portent une autre observation que ceux de v0_raw",
        scores=((ModelKind.V0_RAW, SCORES), (ModelKind.NAISMITH, other)),
    )


# ---------------------------------------------------------------------------
# ExperimentTrials, TrialCounts (décision 4)
# ---------------------------------------------------------------------------

STOPS = ExperimentTrials("arrêts", M.DESCENT_LEVEL, 2)
SLOPE = ExperimentTrials("pente", M.ASCENT_LEVEL, 1)
COUNTS = TrialCounts(4, 1, 1, (STOPS, SLOPE))


def test_experiment_trials_invariants() -> None:
    _raises(STOPS, "effect ne doit pas être vide", effect="")
    _raises(STOPS, "count doit être >= 1", count=0)
    assert replace(STOPS, count=1).count == 1


def test_trial_counts_valid() -> None:
    assert COUNTS.declarations == COUNTS.without_effect + 3


def test_trial_counts_by_experiment_is_a_tuple() -> None:
    _raises(
        COUNTS, "by_experiment doit être une séquence immuable", by_experiment=[STOPS]
    )


@pytest.mark.parametrize("name", ["declarations", "corrections", "without_effect"])
def test_trial_counts_non_negative(name: str) -> None:
    _raises(COUNTS, f"{name} doit être >= 0", **{name: -1})


def test_trial_counts_corrections_are_declarations() -> None:
    _raises(COUNTS, "corrections (5) ne dépasse pas declarations (4)", corrections=5)


def test_trial_counts_sum() -> None:
    """Décision 4 : chaque déclaration compte une fois, avec ou sans effet."""
    _raises(
        COUNTS,
        "declarations (5) doit valoir without_effect + Σ count (4)",
        declarations=5,
    )


def test_trial_counts_order_by_effect_then_target_rank() -> None:
    _raises(
        COUNTS,
        "by_experiment est ordonné par effet puis par rang de la cible dans "
        "ExperimentMetric, sans doublon, reçu ('pente', 1) puis ('arrêts', 3)",
        by_experiment=(SLOPE, STOPS),
    )
    dispersion = ExperimentTrials("arrêts", M.DESCENT_DISPERSION, 1)
    _raises(
        COUNTS,
        "reçu ('arrêts', 6) puis ('arrêts', 3)",
        by_experiment=(dispersion, replace(STOPS, count=1), SLOPE),
    )
    _raises(
        COUNTS,
        "reçu ('arrêts', 3) puis ('arrêts', 3)",
        by_experiment=(replace(STOPS, count=1), replace(STOPS, count=1), SLOPE),
    )


def test_trial_counts_same_effect_in_metric_order_is_accepted() -> None:
    dispersion = ExperimentTrials("arrêts", M.DESCENT_DISPERSION, 1)
    counts = replace(COUNTS, declarations=5, by_experiment=(STOPS, dispersion, SLOPE))
    assert counts.by_experiment[1] is dispersion
