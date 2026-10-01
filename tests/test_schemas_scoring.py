"""Contrats des scores de v0 (§ 6.2 et § 8.1, test 2, du brief M4b-2 ; ``0010`` D3,
D4.12, D5.4, D5.5, D7 ; décision 1 de rdw, Q2).

Pour chaque invariant de ``AdmittedSegment``, ``ObservedPoint``,
``OutingObservation``, ``ModelForecast``, ``ClockScores``, ``ScenarioScores`` et
``OutingScores`` : un objet construit à la main qui le viole (``ContractError``), et un
objet valide à sa limite. Les objets de M4b-1 sont produits par ses fonctions sur des
vecteurs courts. ``Scenario`` et ``OBSERVATION_UNAVAILABILITY`` exacts.
"""

import math
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from mountain_perf.backtest import (
    is_invalid_model_output,
    log_ratio_envelope,
    passage_errors,
    positive_time_diagnostic,
    support_metrics,
    usage_target,
)
from mountain_perf.model import PROJECTION_PARAMETER_SPECS
from mountain_perf.schemas import (
    CLOCKS,
    OBSERVATION_UNAVAILABILITY,
    SCENARIO_DESCRIPTIONS,
    AdmittedSegment,
    ClockScores,
    LogRatioEnvelope,
    ModelForecast,
    ObservedPoint,
    OutingObservation,
    OutingScores,
    ParameterSet,
    RegimeClass,
    Scenario,
    ScenarioScores,
    SourceRef,
    TargetMember,
    Unavailability,
)
from mountain_perf.validation import ContractError

FLAT, ASCENT = RegimeClass.FLAT, RegimeClass.ASCENT
USAGE, CONTROL = Scenario.USAGE, Scenario.CONTROL
TIMES = (10.0,) * len(CLOCKS)
AT = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
SOURCE = SourceRef(
    kind="gpx", identifier="reference.gpx", content_hash="1" * 64, retrieved_at=AT
)
V0 = ParameterSet(PROJECTION_PARAMETER_SPECS)
ARRIVAL = TargetMember(None, True)


def _segment(**changes: Any) -> AdmittedSegment:
    values: dict[str, Any] = {
        "index": 0,
        "nominal_start_m": 0.0,
        "nominal_end_m": 250.0,
        "start_m": 0.0,
        "end_m": 250.0,
        "realized_start_m": 0.0,
        "realized_end_m": 250.0,
        "regime_class": FLAT,
        "times_s": TIMES,
    }
    return AdmittedSegment(**{**values, **changes})


def _point(**changes: Any) -> ObservedPoint:
    values: dict[str, Any] = {
        "distance_m": 250.0,
        "score_index": 1,
        "passage_index": None,
        "unavailability": None,
        "times_s": TIMES,
    }
    return ObservedPoint(**{**values, **changes})


def _arrival(**changes: Any) -> ObservedPoint:
    return _point(**{"distance_m": 1000.0, "score_index": 4, **changes})


def _observation(**changes: Any) -> OutingObservation:
    values: dict[str, Any] = {
        "reference_length_m": 1000.0,
        "origin_m": 0.0,
        "origin_s": 0.0,
        "segments": (_segment(),),
        "error_points": (_point(),),
        "members": (ARRIVAL,),
        "targets": (_arrival(),),
        "arrival_anchor_gap_m": None,
    }
    return OutingObservation(**{**values, **changes})


def _forecast(scenario: Scenario = USAGE, **changes: Any) -> ModelForecast:
    usage = scenario is USAGE
    values: dict[str, Any] = {
        "scenario": scenario,
        "source": SOURCE,
        "curve_ref": "courbe.csv#0123456789ab",
        "parameters": V0,
        "engine_version": "projection-v0",
        "generated_at": AT,
        "segment_s": (100.0,),
        "point_s": (50.0,) if usage else (),
        "target_s": (60.0,) if usage else (),
    }
    return ModelForecast(**{**values, **changes})


def _clock_scores(
    clock_index: int,
    forecast: ModelForecast,
    observed_s: tuple[float, ...],
    classes: tuple[RegimeClass, ...],
) -> ClockScores:
    """Des ``ClockScores`` valides, par les fonctions de M4b-1."""
    support = support_metrics(forecast.segment_s, observed_s, classes)
    diagnostic = None
    if support.dispersion.unavailability is Unavailability.ZERO_TIME:
        diagnostic = positive_time_diagnostic(forecast.segment_s, observed_s, classes)
    if forecast.scenario is CONTROL:
        return ClockScores(CLOCKS[clock_index], support, diagnostic, None, None)
    points, targets = len(forecast.point_s), len(forecast.target_s)
    return ClockScores(
        CLOCKS[clock_index],
        support,
        diagnostic,
        passage_errors(forecast.point_s, (40.0,) * points, (None,) * points),
        usage_target(
            forecast.target_s, forecast.target_s, (55.0,) * targets, (None,) * targets
        ),
    )


def _envelope(
    forecast: ModelForecast,
    observed_s: tuple[float, ...],
    members: list[int],
) -> LogRatioEnvelope | None:
    if not members:
        return None
    projected = forecast.segment_s
    total_s = math.fsum(observed_s[i] for i in members)
    if any(is_invalid_model_output(p) for p in projected):
        return log_ratio_envelope(None, total_s, total_s)
    return log_ratio_envelope(
        math.fsum(p for i in members if (p := projected[i]) is not None),
        total_s,
        total_s,
    )


def _scenario(
    scenario: Scenario = USAGE,
    observed_s: tuple[float, ...] = (80.0,),
    classes: tuple[RegimeClass, ...] = (FLAT,),
    **forecast_changes: Any,
) -> ScenarioScores:
    """Des ``ScenarioScores`` valides : mêmes temps sous les onze horloges."""
    forecast = _forecast(scenario, **forecast_changes)
    clocks = tuple(
        _clock_scores(i, forecast, observed_s, classes) for i in range(len(CLOCKS))
    )
    return ScenarioScores(
        scenario,
        forecast,
        _envelope(forecast, observed_s, list(range(len(observed_s)))),
        tuple(
            _envelope(
                forecast,
                observed_s,
                [i for i, c in enumerate(classes) if c is regime],
            )
            for regime in RegimeClass
        ),
        clocks,
    )


# ---------------------------------------------------------------------------
# Scenario, OBSERVATION_UNAVAILABILITY
# ---------------------------------------------------------------------------


def test_scenario_members_are_those_of_d3() -> None:
    """``0010`` D3 : usage et contrôle, décrits."""
    assert [(s.name, s.value) for s in Scenario] == [
        ("USAGE", "usage"),
        ("CONTROL", "control"),
    ]
    assert set(SCENARIO_DESCRIPTIONS) == set(Scenario)


def test_observation_unavailability_is_that_of_m4a3() -> None:
    """Les motifs d'une observation de M4a-3 (``0010`` D4.12) : jamais un motif de
    métrique."""
    assert (
        frozenset(
            {
                Unavailability.ABSENT,
                Unavailability.AMBIGUOUS,
                Unavailability.UNDEFINED_TANGENT,
                Unavailability.INSUFFICIENT_SUPPORT,
            }
        )
        == OBSERVATION_UNAVAILABILITY
    )


# ---------------------------------------------------------------------------
# AdmittedSegment
# ---------------------------------------------------------------------------

ABSCISSAS = (
    "nominal_start_m",
    "nominal_end_m",
    "start_m",
    "end_m",
    "realized_start_m",
    "realized_end_m",
)


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        ({"index": -1}, "index doit être >= 0"),
        *(({name: math.nan}, f"{name} doit être fini") for name in ABSCISSAS),
        *(({name: -1.0}, f"{name} doit être >= 0") for name in ABSCISSAS),
        ({"nominal_end_m": 0.0}, "nominal_start_m .* doit être < nominal_end_m"),
        ({"end_m": 0.0}, "start_m .* doit être < end_m"),
        ({"realized_start_m": 250.5}, "realized_start_m .* doit être <="),
        ({"regime_class": "flat"}, "regime_class doit être une RegimeClass"),
        ({"times_s": list(TIMES)}, "times_s doit être une séquence immuable"),
        ({"times_s": TIMES[:-1]}, "un temps par horloge"),
        ({"times_s": (*TIMES[:-1], math.nan)}, r"times_s\[10\] doit être fini"),
        ({"times_s": (*TIMES[:-1], -1.0)}, r"times_s\[10\] doit être >= 0"),
        ({"times_s": (0.0, *TIMES[1:])}, "l'écoulé d'un segment admis est > 0"),
    ],
)
def test_admitted_segment_invariants(changes: dict[str, Any], match: str) -> None:
    with pytest.raises(ContractError, match=match):
        _segment(**changes)


def test_admitted_segment_at_its_limits() -> None:
    """Indice et bornes à 0, abscisses réalisées égales, écoulé minimal, temps nuls
    sous les autres horloges (un segment peut n'avoir aucun temps en mouvement)."""
    segment = _segment(
        realized_start_m=0.0,
        realized_end_m=0.0,
        times_s=(5e-324, *(0.0,) * (len(CLOCKS) - 1)),
    )
    assert segment.index == 0


# ---------------------------------------------------------------------------
# ObservedPoint
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        ({"distance_m": math.nan}, "distance_m doit être fini"),
        ({"distance_m": -1.0}, "distance_m doit être >= 0"),
        ({"score_index": None}, "au moins un de score_index et passage_index"),
        ({"score_index": -1}, "score_index doit être >= 0"),
        ({"passage_index": -1}, "passage_index doit être >= 0"),
        (
            {"unavailability": Unavailability.ABSENT},
            "présent si et seulement si unavailability est absent",
        ),
        ({"times_s": None}, "présent si et seulement si unavailability est absent"),
        (
            {"times_s": None, "unavailability": Unavailability.MODEL_ERROR},
            "motif d'observation hors de la liste",
        ),
        (
            {"times_s": None, "unavailability": Unavailability.ZERO_TIME},
            "motif d'observation hors de la liste",
        ),
        ({"times_s": list(TIMES)}, "times_s doit être une séquence immuable"),
        ({"times_s": (*TIMES, 1.0)}, "un temps par horloge"),
        ({"times_s": (math.inf, *TIMES[1:])}, r"times_s\[0\] doit être fini"),
        ({"times_s": (-1.0, *TIMES[1:])}, r"times_s\[0\] doit être >= 0"),
    ],
)
def test_observed_point_invariants(changes: dict[str, Any], match: str) -> None:
    with pytest.raises(ContractError, match=match):
        _point(**changes)


@pytest.mark.parametrize("motif", sorted(OBSERVATION_UNAVAILABILITY))
def test_observed_point_at_its_limits(motif: Unavailability) -> None:
    """Abscisse et indices à 0, les deux indices (l'arrivée désignée par un lieu), un
    ``T_k`` nul ; chaque motif d'observation admis."""
    point = _point(distance_m=0.0, score_index=0, passage_index=0, times_s=(0.0,) * 11)
    assert point.available
    missing = _point(
        score_index=None, passage_index=0, unavailability=motif, times_s=None
    )
    assert not missing.available


# ---------------------------------------------------------------------------
# OutingObservation
# ---------------------------------------------------------------------------

INTERMEDIATE = TargetMember(0, False)
PLACE = _point(distance_m=375.0, score_index=None, passage_index=0)


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        ({"reference_length_m": math.nan}, "reference_length_m doit être fini"),
        ({"reference_length_m": 0.0}, "reference_length_m doit être > 0"),
        ({"origin_m": math.nan}, "origin_m doit être fini"),
        ({"origin_m": -1.0}, "origin_m doit être dans"),
        ({"origin_m": 1000.0}, "origin_m doit être dans"),
        ({"origin_s": math.inf}, "origin_s doit être fini"),
        ({"origin_s": -1.0}, "origin_s doit être >= 0"),
        ({"segments": [_segment()]}, "segments doit être une séquence immuable"),
        ({"error_points": [_point()]}, "error_points doit être une séquence immuable"),
        ({"members": [ARRIVAL]}, "members doit être une séquence immuable"),
        ({"targets": [_arrival()]}, "targets doit être une séquence immuable"),
        ({"segments": (_segment(), _segment())}, "strictement croissants"),
        (
            {"origin_m": 1.0, "segments": (_segment(),)},
            r"doit être dans \[b_0 ; L\]",
        ),
        (
            {"segments": (_segment(end_m=1000.5, nominal_end_m=1000.5),)},
            r"doit être dans \[b_0 ; L\]",
        ),
        (
            {"error_points": (_point(passage_index=0),)},
            "exactement un de score_index et passage_index",
        ),
        ({"error_points": (_point(score_index=0),)}, "l'origine est exclue"),
        (
            {"origin_m": 300.0, "segments": (), "error_points": (_point(),)},
            r"error_points\[0\].distance_m .* dans \[b_0 ; L\]",
        ),
        (
            {"error_points": (_point(distance_m=1000.5),)},
            r"error_points\[0\].distance_m .* dans \[b_0 ; L\]",
        ),
        (
            {"error_points": (_point(distance_m=500.0, score_index=2), _point())},
            "abscisse non décroissante",
        ),
        ({"members": (INTERMEDIATE, ARRIVAL)}, "même longueur"),
        ({"members": (), "targets": ()}, "K n'est jamais vide"),
        (
            {"members": (ARRIVAL, INTERMEDIATE), "targets": (_arrival(), PLACE)},
            "le dernier membre de K est l'arrivée, et lui seul",
        ),
        (
            {"members": (INTERMEDIATE,), "targets": (PLACE,)},
            "le dernier membre de K est l'arrivée, et lui seul",
        ),
        (
            {
                "members": (ARRIVAL, ARRIVAL),
                "targets": (_arrival(), _arrival()),
            },
            "le dernier membre de K est l'arrivée, et lui seul",
        ),
        (
            {
                "members": (INTERMEDIATE, ARRIVAL),
                "targets": (replace(PLACE, passage_index=1), _arrival()),
            },
            r"targets\[0\].passage_index \(1\) doit valoir",
        ),
        (
            {
                "members": (INTERMEDIATE, ARRIVAL),
                "targets": (replace(PLACE, score_index=2), _arrival()),
            },
            r"targets\[0\] : score_index présent si et seulement si",
        ),
        (
            {"targets": (_arrival(score_index=None, passage_index=0),)},
            r"targets\[0\].passage_index \(0\) doit valoir",
        ),
        (
            {
                "members": (TargetMember(2, True),),
                "targets": (_arrival(score_index=None, passage_index=2),),
            },
            r"targets\[0\] : score_index présent si et seulement si",
        ),
        (
            {"members": (TargetMember(2, True),)},
            r"targets\[0\].passage_index \(None\) doit valoir",
        ),
        (
            {"origin_s": None, "segments": ()},
            "départ non daté : aucun point de C_k",
        ),
        (
            {"origin_s": None, "segments": (), "error_points": ()},
            "départ non daté : aucun élément de K disponible",
        ),
        ({"arrival_anchor_gap_m": math.nan}, "arrival_anchor_gap_m doit être fini"),
        ({"arrival_anchor_gap_m": -1.0}, "arrival_anchor_gap_m doit être >= 0"),
    ],
)
def test_outing_observation_invariants(changes: dict[str, Any], match: str) -> None:
    with pytest.raises(ContractError, match=match):
        _observation(**changes)


def test_outing_observation_at_its_limits() -> None:
    """Segments à ``b_0`` et à ``L``, points aux deux bornes et d'abscisses égales, un
    lieu intermédiaire puis l'arrivée désignée par un lieu, écart nul."""
    observation = _observation(
        origin_m=0.0,
        segments=(
            _segment(),
            _segment(
                index=3,
                nominal_start_m=750.0,
                nominal_end_m=1000.0,
                start_m=750.0,
                end_m=1000.0,
            ),
        ),
        error_points=(
            _point(distance_m=0.0, score_index=None, passage_index=0),
            _point(distance_m=250.0),
            _point(distance_m=250.0, score_index=None, passage_index=1),
            _point(distance_m=1000.0, score_index=4),
        ),
        members=(TargetMember(1, False), TargetMember(2, True)),
        targets=(
            _point(distance_m=250.0, score_index=None, passage_index=1),
            _arrival(passage_index=2),
        ),
        arrival_anchor_gap_m=0.0,
    )
    assert len(observation.targets) == 2


def test_undated_origin_at_its_limits() -> None:
    """Départ non daté (``0010`` D4.12) : aucun point, des éléments de ``K``
    indisponibles."""
    observation = _observation(
        origin_s=None,
        segments=(),
        error_points=(),
        targets=(
            _arrival(times_s=None, unavailability=Unavailability.INSUFFICIENT_SUPPORT),
        ),
    )
    assert observation.origin_s is None


# ---------------------------------------------------------------------------
# ModelForecast
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("scenario", "changes", "match"),
    [
        (USAGE, {"curve_ref": " "}, "curve_ref ne doit pas être vide"),
        (USAGE, {"engine_version": ""}, "engine_version ne doit pas être vide"),
        (
            USAGE,
            {"generated_at": datetime(2026, 9, 30, 12, 0)},
            "generated_at doit porter un fuseau",
        ),
        (USAGE, {"segment_s": [100.0]}, "segment_s doit être une séquence immuable"),
        (USAGE, {"point_s": [50.0]}, "point_s doit être une séquence immuable"),
        (USAGE, {"target_s": [60.0]}, "target_s doit être une séquence immuable"),
        (CONTROL, {"point_s": (50.0,)}, "une prévision de contrôle n'a ni point"),
        (CONTROL, {"target_s": (60.0,)}, "une prévision de contrôle n'a ni point"),
    ],
)
def test_model_forecast_invariants(
    scenario: Scenario, changes: dict[str, Any], match: str
) -> None:
    with pytest.raises(ContractError, match=match):
        _forecast(scenario, **changes)


def test_model_forecast_values_are_not_validated() -> None:
    """Non promis : les valeurs sont des sorties de modèle, jugées par D7.1 dans les
    scores, jamais refusées par le contrat ; séquences vides permises."""
    forecast = _forecast(
        segment_s=(None, math.nan, -1.0, 0.0, math.inf), point_s=(None,), target_s=()
    )
    assert forecast.segment_s[0] is None
    assert _forecast(CONTROL, segment_s=()).point_s == ()


# ---------------------------------------------------------------------------
# ClockScores
# ---------------------------------------------------------------------------


def test_clock_scores_diagnostic_if_and_only_if_zero_time() -> None:
    """``0010`` D5.5, choix 8 : le diagnostic accompagne un motif vectoriel
    ``zero_time``, et seulement lui."""
    p, classes = (10.0, 10.0), (FLAT, FLAT)
    positive = support_metrics(p, (5.0, 5.0), classes)
    zero = support_metrics(p, (0.0, 5.0), classes)
    with pytest.raises(ContractError, match="diagnostic présent si et seulement si"):
        ClockScores(
            CLOCKS[0],
            positive,
            positive_time_diagnostic(p, (5.0, 5.0), classes),
            None,
            None,
        )
    with pytest.raises(ContractError, match="diagnostic présent si et seulement si"):
        ClockScores(CLOCKS[0], zero, None, None, None)
    with pytest.raises(ContractError, match="le masque du diagnostic"):
        ClockScores(
            CLOCKS[0],
            zero,
            positive_time_diagnostic((10.0,), (5.0,), (FLAT,)),
            None,
            None,
        )
    scores = ClockScores(
        CLOCKS[0], zero, positive_time_diagnostic(p, (0.0, 5.0), classes), None, None
    )
    assert scores.diagnostic is not None
    assert scores.diagnostic.mask == (False, True)


def test_clock_scores_usage_objects_go_together() -> None:
    support = support_metrics((10.0,), (5.0,), (FLAT,))
    errors = passage_errors((1.0,), (2.0,), (None,))
    target = usage_target((1.0,), (1.0,), (2.0,), (None,))
    for pair in ((errors, None), (None, target)):
        with pytest.raises(ContractError, match="tous deux présents"):
            ClockScores(CLOCKS[0], support, None, *pair)
    assert ClockScores(CLOCKS[0], support, None, errors, target).usage_target
    assert ClockScores(CLOCKS[0], support, None, None, None).passage_errors is None


# ---------------------------------------------------------------------------
# ScenarioScores
# ---------------------------------------------------------------------------


def _with_clock(scores: ScenarioScores, i: int, clock: ClockScores) -> ScenarioScores:
    clocks = list(scores.clocks)
    clocks[i] = clock
    return replace(scores, clocks=tuple(clocks))


def test_scenario_scores_forecast_scenario() -> None:
    scores = _scenario(USAGE)
    with pytest.raises(ContractError, match=r"forecast\.scenario"):
        replace(scores, scenario=CONTROL)


def _raises(instance: Any, match: str, **changes: Any) -> None:
    with pytest.raises(ContractError, match=match):
        replace(instance, **changes)


def test_scenario_scores_are_tuples() -> None:
    scores = _scenario()
    envelopes, clocks = list(scores.class_envelopes), list(scores.clocks)
    _raises(scores, "class_envelopes doit être une séquence", class_envelopes=envelopes)
    _raises(scores, "clocks doit être une séquence", clocks=clocks)


def test_scenario_scores_carry_the_eleven_clocks_in_order() -> None:
    """``0010`` D5.4 : les onze horloges, dans l'ordre de ``CLOCKS``."""
    scores = _scenario()
    for clocks in (scores.clocks[::-1], scores.clocks[:-1], ()):
        with pytest.raises(ContractError, match="dans l'ordre de CLOCKS"):
            replace(scores, clocks=clocks)


def test_scenario_scores_share_one_support() -> None:
    """``0010`` D7.1 : même support sous toutes les horloges — effectif égal à celui
    de la prévision, mêmes effectifs de classe, même drapeau d'erreur du modèle."""
    scores = _scenario(CONTROL)
    with pytest.raises(ContractError, match=r"doit valoir len\(forecast.segment_s\)"):
        replace(scores, forecast=_forecast(CONTROL, segment_s=(100.0, 100.0)))
    other_class = replace(
        scores.clocks[1], support=support_metrics((100.0,), (80.0,), (ASCENT,))
    )
    with pytest.raises(ContractError, match="les effectifs de classe"):
        _with_clock(scores, 1, other_class)
    flagged = replace(
        scores.clocks[1], support=support_metrics((None,), (80.0,), (FLAT,))
    )
    with pytest.raises(ContractError, match=r"support\.model_error sous"):
        _with_clock(scores, 1, flagged)


def test_scenario_scores_passages_in_usage_only() -> None:
    """``0010`` D7.3, D7.4 ; décision 4 (Q4 a) : ``C_k`` et ``q_usage`` en usage
    seulement, aux longueurs de la prévision."""
    usage, control = _scenario(USAGE), _scenario(CONTROL)
    bare = replace(usage.clocks[3], passage_errors=None, usage_target=None)
    with pytest.raises(ContractError, match="présent si et seulement si le scénario"):
        _with_clock(usage, 3, bare)
    dressed = replace(
        control.clocks[3],
        passage_errors=usage.clocks[3].passage_errors,
        usage_target=usage.clocks[3].usage_target,
    )
    with pytest.raises(ContractError, match="présent si et seulement si le scénario"):
        _with_clock(control, 3, dressed)
    with pytest.raises(ContractError, match="une erreur par point"):
        replace(usage, forecast=replace(usage.forecast, point_s=(50.0, 51.0)))
    with pytest.raises(ContractError, match="un élément par cumulé de K"):
        replace(usage, forecast=replace(usage.forecast, target_s=(60.0, 61.0)))


def test_scenario_scores_envelope_absent_iff_empty_support() -> None:
    """``0010`` D5.4 : pas d'enveloppe sur un support vide, une sinon."""
    scores = _scenario(CONTROL)
    with pytest.raises(ContractError, match="envelope est absente si et seulement si"):
        replace(scores, envelope=None)
    empty = _scenario(CONTROL, observed_s=(), classes=(), segment_s=())
    assert empty.envelope is None
    assert empty.class_envelopes == (None,) * 4
    with pytest.raises(ContractError, match="envelope est absente si et seulement si"):
        replace(empty, envelope=log_ratio_envelope(1.0, 1.0, 1.0))


def test_scenario_scores_one_envelope_per_present_class() -> None:
    """``0010`` D5.4 : quatre enveloppes de classe, absente si et seulement si la
    classe est vide."""
    scores = _scenario(CONTROL)
    envelopes = scores.class_envelopes
    with pytest.raises(ContractError, match="une enveloppe par classe"):
        replace(scores, class_envelopes=envelopes[:3])
    with pytest.raises(ContractError, match="l'enveloppe de flat est absente"):
        replace(scores, class_envelopes=(None, None, None, None))
    empty_class = (log_ratio_envelope(None, 0.0, 0.0), *envelopes[1:])
    with pytest.raises(ContractError, match="l'enveloppe de ascent est absente"):
        replace(scores, class_envelopes=empty_class)


def test_scenario_scores_envelope_motifs_follow_the_model_error() -> None:
    """``0010`` D7.1 : l'erreur du modèle vaut pour la performance."""
    scores = _scenario(CONTROL)
    model_error = log_ratio_envelope(None, 80.0, 80.0)
    with pytest.raises(ContractError, match=r"exige support\.model_error"):
        replace(scores, envelope=model_error)
    flagged = _scenario(CONTROL, segment_s=(None,))
    assert flagged.envelope == model_error
    with pytest.raises(ContractError, match="toute enveloppe présente a un motif"):
        replace(flagged, envelope=log_ratio_envelope(100.0, 80.0, 80.0))
    zero_time = _scenario(CONTROL, observed_s=(0.0,), segment_s=(None,))
    assert zero_time.envelope == LogRatioEnvelope(
        None, None, None, Unavailability.ZERO_TIME
    )


def test_scenario_scores_at_their_limits() -> None:
    """Usage à zéro point et un élément de ``K`` ; temps nul avec diagnostic sous
    toutes les horloges."""
    usage = _scenario(USAGE, point_s=())
    assert usage.clocks[0].passage_errors is not None
    zero = _scenario(
        CONTROL, observed_s=(0.0, 5.0), classes=(FLAT, FLAT), segment_s=(10.0, 10.0)
    )
    assert all(scores.diagnostic is not None for scores in zero.clocks)


# ---------------------------------------------------------------------------
# OutingScores
# ---------------------------------------------------------------------------


def test_outing_scores_scenarios() -> None:
    """``0010`` D3 : un contrôle, et un usage seulement avec une référence."""
    observation = _observation()
    control, usage = _scenario(CONTROL), _scenario(USAGE)
    with pytest.raises(ContractError, match="control porte le scénario contrôle"):
        OutingScores(observation, usage, None)
    with pytest.raises(ContractError, match="usage porte le scénario usage"):
        OutingScores(observation, control, control)
    assert OutingScores(observation, control, None).usage is None
    assert OutingScores(observation, control, usage).usage is usage


def test_outing_scores_lengths_follow_the_observation() -> None:
    observation = _observation()
    control = _scenario(CONTROL)
    two = _scenario(
        CONTROL, observed_s=(80.0, 80.0), classes=(FLAT, FLAT), segment_s=(1.0, 1.0)
    )
    with pytest.raises(ContractError, match="control : 2 projections pour 1"):
        OutingScores(observation, two, None)
    two_usage = _scenario(
        USAGE, observed_s=(80.0, 80.0), classes=(FLAT, FLAT), segment_s=(1.0, 1.0)
    )
    with pytest.raises(ContractError, match="usage : 2 projections pour 1"):
        OutingScores(observation, control, two_usage)
    with pytest.raises(ContractError, match="usage : 0 cumulés pour 1 points de C_k"):
        OutingScores(observation, control, _scenario(USAGE, point_s=()))
    with pytest.raises(ContractError, match="usage : 2 cumulés pour 1 éléments de K"):
        OutingScores(observation, control, _scenario(USAGE, target_s=(1.0, 2.0)))


# ---------------------------------------------------------------------------
# Correctifs de la relecture de la PR #15
# ---------------------------------------------------------------------------


def test_reference_length_at_its_limit() -> None:
    """``reference_length_m > 0`` strict : un tracé de 0,5 m est valide."""
    observation = _observation(
        reference_length_m=0.5,
        segments=(),
        error_points=(),
        targets=(_arrival(distance_m=0.5),),
    )
    assert observation.reference_length_m == 0.5
