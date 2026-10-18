"""Comparaisons de la sensibilité (``0010`` D13 ; précision de M4d-3 ; vue composée de
D10.6) : la bibliothèque, par l'API publique de ``mountain_perf.backtest``.

Valeurs d'un modèle sous une horloge (``usage_clock_scores``, ``sensitivity_value`` :
statut du calage d'effectif nul avant tout motif de l'observation, ``support
insuffisant`` sans erreurs aux passages ou sans cible) ; les trois axes d'une métrique
(``compare_metric`` : disponibilité dans ses quatre états, chaque composante du
support qui change seule et leur ordre, la population d'un modèle calé seulement, les
temps nuls même hors de la classe, l'écart au bit) ; une performance
(``compare_performance``, et l'ordre des motifs par ``compare_configuration``) ; une
expérience (``compare_gains``, ``evaluability_lost``, ``configuration_outcome`` et ses
quatre réserves, chacune déclenchée seule, et les cas limites) ; le document
(``sensitivity_outcome``) et la vue composée (``qualify_sensitivity``). Propriétés :
une configuration comparée à elle-même n'a ni perte, ni gain, ni composante changée,
ni écart non nul. Les préconditions (``ValueError``) sont vérifiées par leur type
seul. Mondes construits par ``fixtures.sensitivity`` : rien de réel.
"""

import math
import struct
from dataclasses import replace
from datetime import date, datetime
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import mountain_perf.backtest as backtest
from fixtures.outings import PARIS_SUMMER, PREPARED, outing_at
from fixtures.registry import declaration
from fixtures.sensitivity import (
    DAYS,
    EPSILON,
    ERR,
    HISTORY,
    MODEL_ERROR,
    NOT_CALIBRATED,
    PROFILE,
    STANDARD_POINTS,
    A,
    Calage,
    Calibrated,
    D,
    Decision,
    F,
    GainSpec,
    assessments,
    decision,
    expected_class,
    gain_comparison,
    observation,
    outcome,
    performance_comparison,
    point,
    raw_scores,
    segment,
    standard_observation,
    standard_segments,
    standard_targets,
    target,
)
from mountain_perf.backtest import (
    SENSITIVITY_CONFIGURATIONS,
    SensitivityQualification,
    SensitivityStatus,
    Side,
    compare_configuration,
    compare_gains,
    compare_metric,
    compare_performance,
    configuration_outcome,
    declared_performance,
    evaluability_lost,
    qualify_sensitivity,
    sensitivity_outcome,
    sensitivity_value,
    support_signature,
    usage_clock_scores,
)
from mountain_perf.schemas import (
    CLOCKS,
    Admission,
    AdmissionVerdict,
    Availability,
    CalibratedOutingScores,
    CalibrationWithdrawal,
    ClockScores,
    CommonSet,
    ConfigurationOutcome,
    ExperimentMetric,
    GainComparison,
    GuardStatus,
    MetricComparison,
    MetricValue,
    ModelKind,
    NonEvaluable,
    OutingOutcome,
    OutingScores,
    Performance,
    PerformanceComparison,
    PerformanceMotif,
    RegimeClass,
    ReserveEntry,
    SensitivityMetric,
    SensitivityOutcome,
    SensitivityReserve,
    SupportComponent,
    Unavailability,
)

C = SupportComponent
SM = SensitivityMetric
R = SensitivityReserve
G = GuardStatus
NE = NonEvaluable
EM = ExperimentMetric
U = Unavailability
V0 = ModelKind.V0_RAW
BASE = ModelKind.V0_RECALIBRATED
CONSTANT = ModelKind.CONSTANT_SPEED
CONFIGS = SENSITIVITY_CONFIGURATIONS
CENTRAL = 4
"""Le rang du comparateur ``(250, 30, écoulé)``."""
NEXT_UP = math.nextafter(EPSILON, math.inf)
ID = "s-0701"
REGIME_METRICS = tuple(SM)[1:7]
NON_REGIME = (SM.MAX_ABS_PASSAGE_ERROR, SM.USAGE)


# ---------------------------------------------------------------------------
# Aides de lecture (d'après la règle)
# ---------------------------------------------------------------------------


_REGIME: dict[SensitivityMetric, tuple[RegimeClass, str]] = {
    SM.ASCENT_LEVEL: (RegimeClass.ASCENT, "log_ratio"),
    SM.FLAT_LEVEL: (RegimeClass.FLAT, "log_ratio"),
    SM.DESCENT_LEVEL: (RegimeClass.DESCENT, "log_ratio"),
    SM.ASCENT_DISPERSION: (RegimeClass.ASCENT, "dispersion"),
    SM.FLAT_DISPERSION: (RegimeClass.FLAT, "dispersion"),
    SM.DESCENT_DISPERSION: (RegimeClass.DESCENT, "dispersion"),
}


def _scores(
    made: OutingOutcome, model: ModelKind
) -> OutingScores | CalibratedOutingScores:
    return next(scores for kind, scores in made.scores if kind is model)


def _clock(made: OutingOutcome, model: ModelKind, i: int) -> ClockScores | None:
    """Les scores d'usage sous l'horloge ``i`` : ceux de v0 brut, ou les scores calés
    (``None`` sans calage sous l'horloge)."""
    scores = _scores(made, model)
    assert scores.usage is not None
    if isinstance(scores, CalibratedOutingScores):
        return scores.usage.clocks[i].scores
    return scores.usage.clocks[i]


def read(
    made: OutingOutcome, model: ModelKind, metric: SensitivityMetric, i: int
) -> MetricValue:
    """La valeur d'usage d'une métrique, lue dans les scores de la sortie (précision de
    D13, « Trois axes ») : sans calage, le statut d'effectif nul ; ``max |C_k|`` sans
    erreur aux passages et ``q_usage`` sans cible, ``support insuffisant``."""
    scores = _scores(made, model)
    clock = _clock(made, model, i)
    if clock is None:
        assert isinstance(scores, CalibratedOutingScores)
        assert scores.usage is not None
        status = scores.usage.clocks[i].calibration.unavailability
        assert status is not None
        return MetricValue(None, status, 0)
    if metric is SM.LEVEL:
        return clock.support.log_ratio
    if metric in _REGIME:
        regime, name = _REGIME[metric]
        classes = {c.regime_class: c for c in clock.support.classes}
        value: MetricValue = getattr(classes[regime], name)
        return value
    if metric is SM.MAX_ABS_PASSAGE_ERROR:
        if clock.passage_errors is None:
            return MetricValue(None, U.INSUFFICIENT_SUPPORT, 0)
        return clock.passage_errors.max_abs_error_s
    if clock.usage_target is None:
        return MetricValue(None, U.INSUFFICIENT_SUPPORT, 0)
    return clock.usage_target.q_usage


def same_bits(first: float | None, second: float | None) -> bool:
    """Deux flottants égaux au bit (le signe d'un zéro compris), ou deux absences."""
    if first is None or second is None:
        return first is None and second is None
    return struct.pack("<d", first) == struct.pack("<d", second)


def compare(
    model: ModelKind,
    metric: SensitivityMetric,
    comparator: OutingOutcome,
    side: OutingOutcome,
    comparator_clock: int = 0,
    side_clock: int = 0,
) -> MetricComparison:
    """``compare_metric`` de deux sorties, chacune sous son horloge."""
    return compare_metric(
        model,
        metric,
        Side(comparator, CLOCKS[comparator_clock]),
        Side(side, CLOCKS[side_clock]),
    )


def supports(
    comparator: OutingOutcome,
    side: OutingOutcome,
    model: ModelKind = V0,
    comparator_clock: int = 0,
    side_clock: int = 0,
) -> dict[SensitivityMetric, tuple[SupportComponent, ...]]:
    """Les composantes changées de chaque métrique."""
    return {
        metric: compare(
            model, metric, comparator, side, comparator_clock, side_clock
        ).support
        for metric in SM
    }


def _standard(*models: Calibrated, **changes: Any) -> OutingOutcome:
    """La sortie de référence (``standard_observation``), au profil ``PROFILE`` ;
    ``changes`` : les parties de l'observation remplacées, ou ``ratio``."""
    ratio = changes.pop("ratio", 1.1)
    return outcome(
        ID, standard_observation(**changes), *models, ratio=ratio, profile=PROFILE
    )


REFERENCE = _standard(Calibrated(BASE), Calibrated(CONSTANT, 1.2))
"""La sortie de référence : v0 brut, (0) et vitesse constante, calés partout."""


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "Side",
        "SensitivityStatus",
        "SensitivityQualification",
        "usage_clock_scores",
        "sensitivity_value",
        "support_signature",
        "compare_metric",
        "compare_performance",
        "compare_gains",
        "evaluability_lost",
        "configuration_outcome",
        "sensitivity_outcome",
        "qualify_sensitivity",
        "compare_configuration",
        "SENSITIVITY_CONFIGURATIONS",
    ],
)
def test_comparison_api_is_exported(name: str) -> None:
    """Précision de D13, M4d-3 : les fonctions de comparaison sont publiques, dans
    ``mountain_perf.backtest``."""
    assert hasattr(backtest, name)
    assert name in backtest.__all__


# ---------------------------------------------------------------------------
# usage_clock_scores, sensitivity_value
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("i", range(len(CLOCKS)))
def test_usage_clock_scores_of_raw_v0(i: int) -> None:
    """Précision de D13 : la valeur de v0 brut sous l'horloge est lue dans ses scores
    d'usage sous cette horloge."""
    raw = _scores(REFERENCE, V0)
    assert raw.usage is not None
    assert usage_clock_scores(raw, CLOCKS[i]) == raw.usage.clocks[i]


@pytest.mark.parametrize("i", [0, 1, 6, 10])
def test_usage_clock_scores_of_a_calibrated_model(i: int) -> None:
    """Précision de D13 : un modèle calé vaut sa valeur calée sous l'horloge, lue dans
    ses scores calés (pas ceux de v0 brut)."""
    calibrated = _scores(REFERENCE, CONSTANT)
    result = usage_clock_scores(calibrated, CLOCKS[i])
    assert result == _clock(REFERENCE, CONSTANT, i)
    assert result != _clock(REFERENCE, V0, i)


@pytest.mark.parametrize(
    "calage", [NOT_CALIBRATED, MODEL_ERROR], ids=["not-calibrated", "model-error"]
)
def test_usage_clock_scores_without_calibration_is_its_status(calage: Calage) -> None:
    """Précision de D13 : sans calage sous l'horloge, le statut (``non calé``,
    ``erreur du modèle``) ; les autres horloges restent calées."""
    made = _standard(Calibrated(BASE, calages={3: calage}))
    scores = _scores(made, BASE)
    assert usage_clock_scores(scores, CLOCKS[3]) is calage.status
    assert isinstance(usage_clock_scores(scores, CLOCKS[2]), ClockScores)


def test_usage_clock_scores_requires_usage() -> None:
    """Précondition : la sortie a l'usage (D3)."""
    made = outcome(ID, standard_observation(), Calibrated(BASE), usage=False)
    for model in (V0, BASE):
        with pytest.raises(ValueError):  # noqa: PT011 — texte réécrit
            usage_clock_scores(_scores(made, model), CLOCKS[0])


@pytest.mark.parametrize("metric", list(SM))
@pytest.mark.parametrize("i", [0, 2, 7])
def test_sensitivity_value_reads_each_metric(metric: SensitivityMetric, i: int) -> None:
    """Précision de D13, « Trois axes » : ``L`` ; ``E_R`` et ``D_R`` de la classe ;
    ``max |C_k|`` ; ``q_usage`` — lus tels quels dans les scores de l'horloge."""
    clock = _clock(REFERENCE, BASE, i)
    assert clock is not None
    assert sensitivity_value(clock, metric) == read(REFERENCE, BASE, metric, i)


def test_regime_values_differ_by_class() -> None:
    """Le monde de référence distingue les classes : une classe lue pour une autre se
    verrait."""
    clock = _clock(REFERENCE, V0, 0)
    assert clock is not None
    levels = [sensitivity_value(clock, m).value for m in REGIME_METRICS[:3]]
    dispersions = [sensitivity_value(clock, m).value for m in REGIME_METRICS[3:]]
    assert len(set(levels)) == 3
    assert len(set(dispersions)) == 3


@pytest.mark.parametrize("metric", list(SM))
@pytest.mark.parametrize("status", [U.NOT_CALIBRATED, U.MODEL_ERROR])
def test_sensitivity_value_of_a_status(
    metric: SensitivityMetric, status: Unavailability
) -> None:
    """Précision de D13 : sans calage, le statut, d'effectif nul."""
    assert sensitivity_value(status, metric) == MetricValue(None, status, 0)


def test_sensitivity_value_without_passage_errors_or_target() -> None:
    """Précision de D13 : ``max |C_k|`` sans erreur aux passages et ``q_usage`` sans
    cible d'usage, ``support insuffisant`` d'effectif nul ; ``L`` reste lu."""
    control = raw_scores(standard_observation()).control.clocks[0]
    assert control.passage_errors is None
    assert control.usage_target is None
    insufficient = MetricValue(None, U.INSUFFICIENT_SUPPORT, 0)
    assert sensitivity_value(control, SM.MAX_ABS_PASSAGE_ERROR) == insufficient
    assert sensitivity_value(control, SM.USAGE) == insufficient
    assert sensitivity_value(control, SM.LEVEL) == control.support.log_ratio


def test_calibrated_q_usage_is_read_not_recomputed() -> None:
    """Précision de D13 : ``q_usage`` d'un modèle calé est lu dans ses scores (au
    dénominateur, la prévision d'usage de v0 brut, D9.2), jamais recalculé."""
    made = _standard(Calibrated(CONSTANT, 1.4))
    comparison = compare(CONSTANT, SM.USAGE, made, made)
    stored = read(made, CONSTANT, SM.USAGE, 0)
    own_base = _clock(
        outcome(ID, standard_observation(), ratio=1.4, profile=PROFILE), V0, 0
    )
    assert own_base is not None
    assert own_base.usage_target is not None
    assert comparison.value == stored
    assert stored != own_base.usage_target.q_usage


# ---------------------------------------------------------------------------
# compare_metric — valeurs, écart, disponibilité
# ---------------------------------------------------------------------------


OTHER_RATIO = _standard(Calibrated(BASE), Calibrated(CONSTANT, 1.2), ratio=1.3)
"""La même observation, v0 brut au rapport 1,3 : mêmes supports, autres valeurs."""


@pytest.mark.parametrize("metric", list(SM))
@pytest.mark.parametrize("model", [V0, BASE, CONSTANT])
def test_compare_metric_values_and_difference(
    model: ModelKind, metric: SensitivityMetric
) -> None:
    """Précision de D13, axes 1 et 3 : la valeur sous la configuration (son exécution,
    son horloge) et celle du comparateur ; l'écart ``valeur − comparateur``, au
    bit."""
    comparison = compare(model, metric, REFERENCE, OTHER_RATIO, 0, 5)
    comparator = read(REFERENCE, model, metric, 0)
    value = read(OTHER_RATIO, model, metric, 5)
    assert comparison.model is model
    assert comparison.metric is metric
    assert comparison.comparator == comparator
    assert comparison.value == value
    assert comparison.availability is Availability.BOTH
    assert comparator.value is not None
    assert value.value is not None
    assert same_bits(comparison.difference, value.value - comparator.value)
    assert comparison.support == ()


def test_compare_metric_difference_sign() -> None:
    """Précision de D13, axe 3 : ``valeur − comparateur``, pas l'inverse ; ``L`` signé
    (``|L|`` n'est pas comparé à part)."""
    low = compare(V0, SM.LEVEL, REFERENCE, OTHER_RATIO)
    high = compare(V0, SM.LEVEL, OTHER_RATIO, REFERENCE)
    assert low.difference is not None
    assert high.difference is not None
    assert low.difference == -high.difference != 0.0
    assert low.value.value is not None
    assert low.comparator.value is not None
    assert low.value.value - low.comparator.value == low.difference


def _without_points() -> OutingOutcome:
    return _standard(Calibrated(BASE), points=())


@pytest.mark.parametrize(
    ("comparator", "side", "availability"),
    [
        ("full", "empty", Availability.LOST),
        ("empty", "full", Availability.GAINED),
        ("empty", "empty", Availability.NEITHER),
        ("full", "full", Availability.BOTH),
    ],
)
def test_compare_metric_availability_states(
    comparator: str, side: str, availability: Availability
) -> None:
    """Précision de D13, axe 1 : disponible des deux côtés, perdue (au comparateur
    seulement), gagnée (sous la configuration seulement), indisponible des deux côtés
    — chaque valeur indisponible à son motif publié, l'écart absent."""
    made = {"full": _standard(Calibrated(BASE)), "empty": _without_points()}
    comparison = compare(V0, SM.MAX_ABS_PASSAGE_ERROR, made[comparator], made[side])
    assert comparison.availability is availability
    insufficient = MetricValue(None, U.INSUFFICIENT_SUPPORT, 0)
    if comparator == "empty":
        assert comparison.comparator == insufficient
    if side == "empty":
        assert comparison.value == insufficient
    assert (comparison.difference is None) == (availability is not Availability.BOTH)
    assert comparison.support == (() if comparator == side else (C.POINTS,))


@pytest.mark.parametrize(
    "calage", [NOT_CALIBRATED, MODEL_ERROR], ids=["not-calibrated", "model-error"]
)
@pytest.mark.parametrize("metric", list(SM))
def test_compare_metric_lost_by_calibration(
    calage: Calage, metric: SensitivityMetric
) -> None:
    """Précision de D13 : sans calage sous l'horloge de la configuration, chaque
    métrique est perdue, au statut du calage d'effectif nul."""
    side = _standard(Calibrated(BASE, calages={6: calage}))
    comparison = compare(BASE, metric, REFERENCE, side, 0, 6)
    assert comparison.availability is Availability.LOST
    assert comparison.value == MetricValue(None, calage.status, 0)
    assert comparison.difference is None


def test_calibration_status_before_observation_motif() -> None:
    """Précision de D13 : le statut du calage passe avant tout motif de
    l'observation — sans point de ``C_k``, ``max |C_k|`` vaut ``non calé``, pas
    ``support insuffisant``."""
    side = _standard(Calibrated(BASE, calages={0: NOT_CALIBRATED}), points=())
    comparison = compare(BASE, SM.MAX_ABS_PASSAGE_ERROR, _without_points(), side)
    assert comparison.comparator == MetricValue(None, U.INSUFFICIENT_SUPPORT, 0)
    assert comparison.value == MetricValue(None, U.NOT_CALIBRATED, 0)
    assert comparison.availability is Availability.NEITHER


def test_compare_metric_gained_by_calibration() -> None:
    """Précision de D13 : calé sous la configuration seulement, gagnée ; la même
    population (``C_j^eff`` et retraits) n'est pas une composante changée — le statut
    se lit sur l'axe de la disponibilité, pas sur le support."""
    comparator = _standard(Calibrated(BASE, calages={0: MODEL_ERROR}))
    comparison = compare(BASE, SM.LEVEL, comparator, REFERENCE)
    assert comparison.availability is Availability.GAINED
    assert comparison.comparator == MetricValue(None, U.MODEL_ERROR, 0)
    assert comparison.support == ()


# ---------------------------------------------------------------------------
# compare_metric — support effectif (axe 2)
# ---------------------------------------------------------------------------


def test_effective_bound_changes_segments_only() -> None:
    """Précision de D13, axe 2 : une borne effective déplacée change les segments de
    ``L`` et de la classe du segment, seuls ; un effectif égal ne dit pas qu'un support
    l'est."""
    side = _standard(
        Calibrated(BASE),
        segments=standard_segments(s1=segment(1, A, 110.0, bounds=(100.0, 180.0))),
    )
    changed = supports(_standard(Calibrated(BASE)), side)
    assert changed[SM.LEVEL] == (C.SEGMENTS,)
    assert changed[SM.ASCENT_LEVEL] == (C.SEGMENTS,)
    assert changed[SM.ASCENT_DISPERSION] == (C.SEGMENTS,)
    for metric in (SM.FLAT_LEVEL, SM.DESCENT_LEVEL, SM.FLAT_DISPERSION, *NON_REGIME):
        assert changed[metric] == ()
    level = compare(V0, SM.LEVEL, REFERENCE, side)
    assert level.comparator.count == level.value.count == 6


def test_class_swap_at_equal_counts_changes_segments() -> None:
    """Précision de D13, axe 2 : la classe de chaque segment est une entrée — deux
    classes échangées, à effectifs égaux, changent les segments de ``L`` et des deux
    classes, pas de la troisième."""
    side = _standard(
        segments=standard_segments(s1=segment(1, F, 110.0), s2=segment(2, A, 60.0))
    )
    changed = supports(_standard(), side)
    for metric in (SM.LEVEL, SM.ASCENT_LEVEL, SM.FLAT_LEVEL, SM.FLAT_DISPERSION):
        assert changed[metric] == (C.SEGMENTS,)
    assert changed[SM.DESCENT_LEVEL] == ()
    assert changed[SM.DESCENT_DISPERSION] == ()
    ascent = compare(V0, SM.ASCENT_LEVEL, _standard(), side)
    assert ascent.comparator.count == ascent.value.count == 2


def test_only_effective_bounds_and_class_are_segment_entries() -> None:
    """Précision de D13, axe 2 : un segment se lit par son début et sa fin effectifs et
    sa classe — un autre rang, d'autres bornes nominales ou réalisées ne changent
    rien."""
    shifted = tuple(
        replace(
            s,
            index=s.index + 3,
            nominal_start_m=s.nominal_start_m + 7.0,
            nominal_end_m=s.nominal_end_m + 7.0,
            realized_start_m=s.realized_start_m + 2.0,
            realized_end_m=s.realized_end_m + 3.0,
        )
        for s in standard_segments()
    )
    side = _standard(Calibrated(BASE), segments=shifted)
    for model in (V0, BASE):
        for metric in SM:
            comparison = compare(model, metric, _standard(Calibrated(BASE)), side)
            assert comparison.support == ()
            assert same_bits(comparison.difference, 0.0)


def _zero_on_descent(clock: int = 1) -> OutingOutcome:
    return _standard(
        Calibrated(BASE),
        segments=standard_segments(s4=segment(4, D, 50.0, zero=(clock,))),
    )


def test_zero_time_changes_zero_times_even_outside_the_class() -> None:
    """Précision de D13, axe 2 : un segment de temps nul sous l'horloge change les
    temps nuls de ``L`` et de chaque métrique de régime, même hors de sa classe ; ni
    les segments, ni ``max |C_k|``, ni ``q_usage``."""
    changed = supports(_standard(Calibrated(BASE)), _zero_on_descent(1), V0, 1, 1)
    for metric in (SM.LEVEL, *REGIME_METRICS):
        assert changed[metric] == (C.ZERO_TIMES,)
    for metric in NON_REGIME:
        assert changed[metric] == ()


def test_zero_time_is_read_under_each_side_clock() -> None:
    """Précision de D13, axe 2 : « de temps nul sous l'horloge » — sous l'écoulé des
    deux côtés, rien ne change ; la même observation lue sous deux horloges diffère
    par ses temps nuls."""
    zero = _zero_on_descent(1)
    assert set(supports(_standard(Calibrated(BASE)), zero, V0, 0, 0).values()) == {()}
    across = supports(zero, zero, V0, 0, 1)
    assert across[SM.LEVEL] == (C.ZERO_TIMES,)
    assert across[SM.ASCENT_LEVEL] == (C.ZERO_TIMES,)
    assert across[SM.USAGE] == ()


@pytest.mark.parametrize(
    "points",
    [
        (point(250.0, 230.0, index=2), STANDARD_POINTS[1]),
        (point(200.0, None, index=2), STANDARD_POINTS[1]),
        (point(200.0, 230.0, index=2, zero=(2,)), STANDARD_POINTS[1]),
        STANDARD_POINTS[:1],
        (*STANDARD_POINTS, point(600.0, 500.0, index=6)),
    ],
    ids=["abscissa", "motif", "zero-time", "removed", "added"],
)
def test_points_change_alone(points: tuple[Any, ...]) -> None:
    """Précision de D13, axe 2 : les points de ``C_k``, dans leur ordre (abscisse,
    motif, temps nul sous l'horloge) ne changent que ``max |C_k|``."""
    changed = supports(REFERENCE, _standard(points=points), V0, 2, 2)
    assert changed[SM.MAX_ABS_PASSAGE_ERROR] == (C.POINTS,)
    for metric in SM:
        if metric is not SM.MAX_ABS_PASSAGE_ERROR:
            assert changed[metric] == ()


def test_point_entries_are_abscissa_motif_and_zero() -> None:
    """Précision de D13, axe 2 : un autre temps non nul, un autre indice ne changent pas
    le point ; un autre motif d'indisponibilité, si ; « s'il a des temps » — sans
    temps, pas de drapeau de temps nul ; un temps nul ne compte que sous son
    horloge."""
    retimed = (STANDARD_POINTS[0], point(400.0, 380.0, index=4))
    reindexed = (point(200.0, 230.0, index=3), point(400.0, 360.0, index=5))
    other_motif = (point(200.0, None, index=2), STANDARD_POINTS[1])
    ambiguous = (point(200.0, None, index=2, motif=U.AMBIGUOUS), STANDARD_POINTS[1])
    zero = (point(200.0, 230.0, index=2, zero=(2,)), STANDARD_POINTS[1])
    metric = SM.MAX_ABS_PASSAGE_ERROR
    timed = compare(V0, metric, REFERENCE, _standard(points=retimed))
    assert timed.support == ()
    assert timed.difference != 0.0
    assert compare(V0, metric, REFERENCE, _standard(points=reindexed)).support == ()
    assert compare(
        V0, metric, _standard(points=other_motif), _standard(points=ambiguous)
    ).support == (C.POINTS,)
    assert compare(V0, metric, REFERENCE, _standard(points=zero), 0, 0).support == ()
    assert compare(V0, metric, REFERENCE, _standard(points=zero), 2, 2).support == (
        C.POINTS,
    )


@pytest.mark.parametrize(
    "first",
    [
        target(300.0, 300.0, occurrence=1),
        target(320.0, 300.0, occurrence=0),
        target(300.0, None, occurrence=0),
        target(300.0, 300.0, occurrence=0, zero=(3,)),
    ],
    ids=["member", "abscissa", "motif", "zero-time"],
)
def test_targets_change_alone(first: Any) -> None:
    """Précision de D13, axe 2 : les éléments de ``K``, dans leur ordre (membre,
    abscisse, motif, temps nul sous l'horloge) ne changent que ``q_usage``."""
    side = _standard(targets=(first, standard_targets()[1]))
    changed = supports(REFERENCE, side, V0, 3, 3)
    assert changed[SM.USAGE] == (C.TARGETS,)
    for metric in SM:
        if metric is not SM.USAGE:
            assert changed[metric] == ()


def test_target_entries_ignore_a_non_zero_time() -> None:
    """Précision de D13, axe 2 : un autre cumul observé non nul ne change pas
    l'élément ; un temps nul ne compte que sous son horloge."""
    retimed = _standard(
        targets=(target(300.0, 330.0, occurrence=0), standard_targets()[1])
    )
    zero = _standard(
        targets=(target(300.0, 300.0, occurrence=0, zero=(3,)), standard_targets()[1])
    )
    assert compare(V0, SM.USAGE, REFERENCE, retimed).support == ()
    assert compare(V0, SM.USAGE, REFERENCE, zero, 0, 0).support == ()
    assert compare(V0, SM.USAGE, REFERENCE, zero, 3, 0).support == ()
    assert compare(V0, SM.USAGE, REFERENCE, zero, 0, 3).support == (C.TARGETS,)


WITHDRAWAL = CalibrationWithdrawal(date(2026, 6, 3), U.ZERO_TIME)


@pytest.mark.parametrize(
    "calage",
    [
        Calage((HISTORY, date(2026, 6, 2))),
        Calage(withdrawals=(WITHDRAWAL,)),
        NOT_CALIBRATED,
        Calage((date(2026, 6, 2),), status=U.MODEL_ERROR),
    ],
    ids=["population", "withdrawal", "not-calibrated", "model-error-other-days"],
)
def test_population_changes_alone_for_a_calibrated_model(calage: Calage) -> None:
    """Précision de D13, axe 2 : pour un modèle calé, en dernier, sa population de
    calage sous l'horloge en usage (``C_j^eff`` et ses retraits) ; jamais pour v0
    brut."""
    side = _standard(Calibrated(BASE, calages={0: calage}))
    for metric in SM:
        assert compare(BASE, metric, REFERENCE, side).support == (C.POPULATION,)
        assert compare(V0, metric, REFERENCE, side).support == ()


def test_population_is_read_under_each_side_clock() -> None:
    """Précision de D13, axe 2 : la population sous l'horloge de chaque côté — un
    calage différent sous une autre horloge ne change rien."""
    side = _standard(Calibrated(BASE, calages={5: Calage(withdrawals=(WITHDRAWAL,))}))
    assert compare(BASE, SM.LEVEL, REFERENCE, side, 0, 0).support == ()
    assert compare(BASE, SM.LEVEL, REFERENCE, side, 5, 5).support == (C.POPULATION,)
    assert compare(BASE, SM.LEVEL, side, side, 0, 5).support == (C.POPULATION,)


def test_support_components_are_published_in_order() -> None:
    """Précision de D13, axe 2 : les composantes changées, dans l'ordre — segments,
    temps nuls, population ; points, population ; éléments de ``K``, population."""
    side = _standard(
        Calibrated(BASE, calages={1: Calage(withdrawals=(WITHDRAWAL,))}),
        segments=standard_segments(
            s0=segment(0, A, 120.0, bounds=(10.0, 100.0)),
            s4=segment(4, D, 50.0, zero=(1,)),
        ),
        points=STANDARD_POINTS[:1],
        targets=(target(310.0, 300.0, occurrence=0), standard_targets()[1]),
    )
    changed = supports(REFERENCE, side, BASE, 1, 1)
    assert changed[SM.LEVEL] == (C.SEGMENTS, C.ZERO_TIMES, C.POPULATION)
    assert changed[SM.ASCENT_LEVEL] == (C.SEGMENTS, C.ZERO_TIMES, C.POPULATION)
    assert changed[SM.FLAT_LEVEL] == (C.ZERO_TIMES, C.POPULATION)
    assert changed[SM.MAX_ABS_PASSAGE_ERROR] == (C.POINTS, C.POPULATION)
    assert changed[SM.USAGE] == (C.TARGETS, C.POPULATION)
    raw = supports(REFERENCE, side, V0, 1, 1)
    assert raw[SM.LEVEL] == (C.SEGMENTS, C.ZERO_TIMES)
    assert raw[SM.USAGE] == (C.TARGETS,)


def test_support_signature_tells_components_apart() -> None:
    """Précision de D13, axe 2 : deux signatures égales, c'est la même composante — la
    signature d'une composante ne bouge que si l'une de ses entrées change ; celle de
    la population de v0 brut ne change jamais."""
    moved = standard_observation(
        standard_segments(s1=segment(1, A, 110.0, bounds=(100.0, 180.0)))
    )
    obs = standard_observation()
    raw, other = _scores(REFERENCE, V0), raw_scores(moved, 1.3)
    for metric, same in ((SM.LEVEL, False), (SM.FLAT_LEVEL, True)):
        assert (
            support_signature(C.SEGMENTS, metric, obs, raw, CLOCKS[0])
            == support_signature(C.SEGMENTS, metric, moved, other, CLOCKS[0])
        ) is same
    assert support_signature(
        C.POPULATION, SM.LEVEL, obs, raw, CLOCKS[0]
    ) == support_signature(C.POPULATION, SM.LEVEL, moved, other, CLOCKS[4])


# ---------------------------------------------------------------------------
# compare_performance, et l'ordre des motifs (compare_configuration)
# ---------------------------------------------------------------------------


def test_compare_performance_models_and_metrics_in_order() -> None:
    """Précision de D13, « Trois axes » : chaque modèle (dans l'ordre de la sortie,
    celui de la déclaration), chaque métrique dans l'ordre ; chaque comparaison est
    celle de ``compare_metric``."""
    comparator, side = Side(REFERENCE, CLOCKS[0]), Side(OTHER_RATIO, CLOCKS[2])
    comparison = compare_performance(DAYS[0], ID, None, comparator, side)
    assert comparison.motif is None
    assert comparison.models == (V0, BASE, CONSTANT)
    assert [(c.model, c.metric) for c in comparison.metrics] == [
        (model, metric) for model in (V0, BASE, CONSTANT) for metric in SM
    ]
    for item in comparison.metrics:
        assert item == compare_metric(item.model, item.metric, comparator, side)


@pytest.mark.parametrize("motif", list(PerformanceMotif))
def test_compare_performance_with_a_motif(motif: PerformanceMotif) -> None:
    """Précision de D13 : une performance à motif n'a pas de valeur comparée et porte
    son motif."""
    comparison = compare_performance(DAYS[1], "s-0702", motif, None, None)
    assert comparison == PerformanceComparison(DAYS[1], "s-0702", motif, ())


def _renamed(made: OutingOutcome, outing_id: str) -> OutingOutcome:
    scores = tuple(
        (kind, replace(s, outing_id=outing_id))
        if isinstance(s, CalibratedOutingScores)
        else (kind, s)
        for kind, s in made.scores
    )
    return OutingOutcome(outing_id, made.coverage, scores)


@pytest.mark.parametrize(
    ("motif", "comparator", "side"),
    [
        (PerformanceMotif.NOT_SCORED, REFERENCE, REFERENCE),
        (PerformanceMotif.NOT_SCORED, None, REFERENCE),
        (PerformanceMotif.NO_REFERENCE, REFERENCE, None),
        (None, None, REFERENCE),
        (None, REFERENCE, None),
        (None, None, None),
        (None, REFERENCE, _renamed(REFERENCE, "autre")),
        (None, _renamed(REFERENCE, "autre"), REFERENCE),
        (None, REFERENCE, _standard(Calibrated(BASE))),
        (None, _standard(Calibrated(CONSTANT, 1.2), Calibrated(BASE)), REFERENCE),
    ],
    ids=[
        "motif-two-sides",
        "motif-side",
        "motif-comparator",
        "no-comparator",
        "no-side",
        "no-sides",
        "other-outing",
        "other-comparator-outing",
        "other-models",
        "other-model-order",
    ],
)
def test_compare_performance_preconditions(
    motif: PerformanceMotif | None,
    comparator: OutingOutcome | None,
    side: OutingOutcome | None,
) -> None:
    """Précondition : un motif sans côté ; sans motif, les deux côtés, de la même
    sortie et des mêmes modèles, dans le même ordre."""
    with pytest.raises(ValueError):  # noqa: PT011 — texte réécrit
        compare_performance(
            DAYS[0],
            ID,
            motif,
            None if comparator is None else Side(comparator, CLOCKS[0]),
            None if side is None else Side(side, CLOCKS[0]),
        )


def _outing(name: str, day: date, hour: int = 9, *, reference: bool = True) -> Any:
    made = outing_at(
        name, datetime(day.year, day.month, day.day, hour, tzinfo=PARIS_SUMMER), 3600.0
    )
    return replace(made, route_id="r", reference=PREPARED) if reference else made


def test_performance_motifs_in_their_order() -> None:
    """Précision de D13 : le motif d'une performance, dans cet ordre — jour de
    plusieurs sorties (D0), même si sa première sortie n'est ni scorée ni à
    référence ; première sortie non scorée, même sans référence ; sortie sans
    référence (pas d'usage, D3)."""
    performances = (
        Performance(
            DAYS[0],
            (_outing("m1", DAYS[0], reference=False), _outing("m2", DAYS[0], 13)),
        ),
        Performance(DAYS[1], (_outing("u", DAYS[1], reference=False),)),
        Performance(DAYS[2], (_outing("n", DAYS[2], reference=False),)),
        Performance(DAYS[3], (_outing("ok", DAYS[3]),)),
    )
    declared = declaration(
        performances=tuple(declared_performance(p) for p in performances)
    )
    obs = standard_observation()
    outcomes = {
        "m2": outcome("m2", obs),
        "n": outcome("n", obs, usage=False),
        "ok": outcome("ok", obs),
    }
    result = compare_configuration(
        declared, CONFIGS[0], outcomes, CONFIGS[CENTRAL], outcomes
    )
    assert [(p.civil_date, p.outing_id, p.motif) for p in result] == [
        (DAYS[0], "m1", PerformanceMotif.MULTI_OUTING),
        (DAYS[1], "u", PerformanceMotif.NOT_SCORED),
        (DAYS[2], "n", PerformanceMotif.NO_REFERENCE),
        (DAYS[3], "ok", None),
    ]
    assert [len(p.metrics) for p in result] == [0, 0, 0, len(SM)]


# ---------------------------------------------------------------------------
# compare_gains, evaluability_lost
# ---------------------------------------------------------------------------


def test_compare_gains_publishes_each_side() -> None:
    """Précision de D13, « Signes et ensembles » : chaque gain et son motif, tels
    quels, et leurs classes ; un gain absent n'est jamais un zéro ; dans l'ordre des
    performances."""
    comparator = decision((EPSILON, 0.5, ERR, NE.UNSCORED, -0.5, 0.0))
    config = decision((NEXT_UP, NE.PASSAGE_UNAVAILABLE, 0.3, 0.4, ERR, -EPSILON))
    gains = compare_gains(comparator, config)
    assert gains == (
        GainComparison(DAYS[0], EPSILON, None, NEXT_UP, None, 0, 1),
        GainComparison(DAYS[1], 0.5, None, None, NE.PASSAGE_UNAVAILABLE, 1, None),
        GainComparison(DAYS[2], None, None, 0.3, None, None, 1),
        GainComparison(DAYS[3], None, NE.UNSCORED, 0.4, None, None, 1),
        GainComparison(DAYS[4], -0.5, None, None, None, -1, None),
        GainComparison(DAYS[5], 0.0, None, -EPSILON, None, 0, 0),
    )
    assert [g.comparable for g in gains] == [True, False, False, False, False, True]
    assert [g.class_changed for g in gains] == [True, False, False, False, False, False]


def test_compare_gains_without_decisions() -> None:
    """Précision de D13 : sans performance évaluable d'un côté, ses motifs."""
    comparator = assessments((NE.UNSCORED, NE.EXCLUDED))
    config = decision((0.2, NE.EXCLUDED))
    gains = compare_gains(comparator, config)
    assert gains == (
        GainComparison(DAYS[0], None, NE.UNSCORED, 0.2, None, None, 1),
        GainComparison(DAYS[1], None, NE.EXCLUDED, None, NE.EXCLUDED, None, None),
    )
    assert compare_gains(config, comparator)[0] == GainComparison(
        DAYS[0], 0.2, None, None, NE.UNSCORED, 1, None
    )


@pytest.mark.parametrize(
    "other",
    [
        decision((0.5, 0.2)),
        decision((0.5, 0.2, 0.1, 0.4)),
        decision((0.5, 0.2, 0.1), days=(DAYS[0], DAYS[1], DAYS[5])),
    ],
    ids=["fewer", "more", "other-day"],
)
def test_compare_gains_precondition(other: Decision) -> None:
    """Précondition : les deux décisions évaluent les mêmes jours, dans le même
    ordre."""
    with pytest.raises(ValueError):  # noqa: PT011 — texte réécrit
        compare_gains(decision((0.5, 0.2, 0.1)), other)


@pytest.mark.parametrize(
    ("comparator", "config", "lost"),
    [
        (decision((0.5, 0.5)), decision((0.5, NE.UNSCORED)), True),
        (decision((0.5, 0.5)), decision((0.5, ERR)), False),
        (decision((0.5, NE.UNSCORED)), decision((0.5, 0.5)), False),
        (decision((0.5, 0.5)), decision((0.5, 0.5), passages=G.NOT_EVALUABLE), True),
        (decision((0.5, 0.5)), assessments((NE.UNSCORED, NE.EXCLUDED)), True),
        (assessments((NE.UNSCORED, NE.EXCLUDED)), decision((0.5, 0.5)), False),
        (
            decision((0.5, 0.5), guards={EM.DESCENT_LEVEL: G.VIOLATED}),
            decision((0.5, 0.5), guards={EM.DESCENT_LEVEL: G.UNAVAILABLE}),
            True,
        ),
    ],
    ids=[
        "performance-leaves",
        "gain-missing-still-evaluable",
        "performance-enters",
        "passages-lost",
        "no-decision-under-configuration",
        "no-decision-at-comparator",
        "metric-guard-lost",
    ],
)
def test_evaluability_lost(comparator: Decision, config: Decision, lost: bool) -> None:
    """Précision de D13, réserve 3 : une performance évaluable au comparateur ne l'est
    plus, ou un garde-fou calculé au comparateur (passages compris) ne l'est plus ;
    jamais si le comparateur n'a pas de décision."""
    gains = compare_gains(comparator, config)
    assert evaluability_lost(comparator, config, gains) is lost


# ---------------------------------------------------------------------------
# configuration_outcome
# ---------------------------------------------------------------------------


def _performances(count: int) -> tuple[PerformanceComparison, ...]:
    return tuple(
        performance_comparison(
            day,
            MetricValue(None, U.ABSENT, 0),
            MetricValue(None, U.ABSENT, 0),
            motif=PerformanceMotif.NOT_SCORED,
        )
        for day in DAYS[:count]
    )


def test_configuration_outcome_without_experiment() -> None:
    """Précision de D13 : pour ``just backtest``, la configuration n'a que ses
    performances, sans réserve."""
    performances = _performances(2)
    result = configuration_outcome(CONFIGS[0], performances)
    assert result == ConfigurationOutcome(
        CONFIGS[0],
        performances,
        None,
        None,
        (),
        None,
        None,
        None,
        False,
        False,
        False,
        False,
    )


def test_configuration_outcome_precondition() -> None:
    """Précondition : la décision et celle du comparateur, ensemble."""
    made = decision((0.5,))
    for options in ({"decision": made}, {"comparator": made}):
        with pytest.raises(ValueError):  # noqa: PT011 — texte réécrit
            configuration_outcome(CONFIGS[0], _performances(1), **options)


def _outcome(
    config: Decision, comparator: Decision, rank: int = 0
) -> ConfigurationOutcome:
    days = len(config.performances if isinstance(config, Admission) else config)
    return configuration_outcome(CONFIGS[rank], _performances(days), config, comparator)


def flags(outcome_: ConfigurationOutcome) -> tuple[bool, bool, bool, bool]:
    """Les quatre réserves de la configuration, dans l'ordre du document."""
    return (
        outcome_.sign_changed,
        outcome_.verdict_changed,
        outcome_.evaluability_lost,
        outcome_.sign_unverifiable,
    )


PROVISIONAL = (0.5, 0.5, 0.5, 0.5)
"""Quatre gains de 0,5 : ``Ḡ = 0,5``, candidat provisoire."""


@pytest.mark.parametrize(
    ("comparator", "config", "expected"),
    [
        # signe changé, seul
        (
            decision(PROVISIONAL),
            decision((0.5, 0.5, 0.5, -0.005)),
            (True, False, False, False),
        ),
        (
            decision((0.5, 0.5, 0.5, 0.0)),
            decision(PROVISIONAL),
            (True, False, False, False),
        ),
        (
            decision(PROVISIONAL),
            decision((0.5, 0.5, 0.5, 0.0)),
            (True, False, False, False),
        ),
        (
            decision((0.5, 0.5, 0.5, EPSILON)),
            decision((0.5, 0.5, 0.5, NEXT_UP)),
            (True, False, False, False),
        ),
        (
            decision((0.5, 0.5, 0.5, EPSILON)),
            decision((0.5, 0.5, 0.5, -EPSILON)),
            (False, False, False, False),
        ),
        (
            decision((0.5, NE.UNSCORED), passages=G.UNAVAILABLE),
            decision((0.5, -2.0), passages=G.UNAVAILABLE),
            (True, False, False, False),
        ),
        # verdict modifié, seul (sans changement de signe)
        (
            decision(PROVISIONAL),
            decision(PROVISIONAL, passages=G.VIOLATED),
            (False, True, False, False),
        ),
        (
            decision(PROVISIONAL),
            decision(PROVISIONAL, guards={EM.ASCENT_LEVEL: G.VIOLATED}),
            (False, True, False, False),
        ),
        (decision(PROVISIONAL), decision((0.004,) * 4), (False, True, False, False)),
        # évaluabilité perdue, seule
        (
            decision(PROVISIONAL),
            decision((0.5, 0.5, 0.5, NE.PASSAGE_UNAVAILABLE)),
            (False, False, True, False),
        ),
        (
            decision(PROVISIONAL, guards={EM.FLAT_LEVEL: G.SATISFIED}),
            decision(PROVISIONAL),
            (False, False, True, False),
        ),
        (
            decision(PROVISIONAL, guards={EM.LEVEL: G.UNAVAILABLE}),
            decision(
                PROVISIONAL, guards={EM.LEVEL: G.UNAVAILABLE}, passages=G.NOT_EVALUABLE
            ),
            (False, False, True, False),
        ),
        (
            decision(PROVISIONAL, guards={EM.LEVEL: G.UNAVAILABLE}),
            decision(
                PROVISIONAL, guards={EM.LEVEL: G.UNAVAILABLE}, passages=G.UNAVAILABLE
            ),
            (False, False, True, False),
        ),
        # signe non vérifiable, seul
        (decision((ERR, ERR)), decision((ERR, ERR)), (False, False, False, True)),
        (
            decision((ERR, NE.UNSCORED)),
            decision((ERR, 0.5)),
            (False, False, False, True),
        ),
        # aucune réserve
        (
            decision(PROVISIONAL),
            decision((0.6, 0.4, 0.5, 2e-6)),
            (False, False, False, False),
        ),
    ],
    ids=[
        "sign-individual",
        "sign-zero-to-positive",
        "sign-positive-to-zero",
        "sign-bound-epsilon-to-next",
        "sign-bounds-both-zero",
        "sign-mean-only",
        "verdict-passages-violated",
        "verdict-new-guard-violated",
        "verdict-mean-below-threshold",
        "lost-performance-leaves",
        "lost-metric-guard",
        "lost-passages-not-applicable",
        "lost-passages-unavailable",
        "unverifiable-no-gain",
        "unverifiable-entering-only",
        "none",
    ],
)
def test_each_reserve_alone(
    comparator: Decision, config: Decision, expected: tuple[bool, bool, bool, bool]
) -> None:
    """Précision de D13, « Réserves » : chaque réserve déclenchée seule — signe changé
    (classe de ``Ḡ``, ou d'un ``G_j`` comparable ; zéro ↔ non nul ; bornes ``±ε``
    dans la classe zéro), verdict modifié, évaluabilité perdue (performance ou
    garde-fou, passages compris), signe non vérifiable."""
    assert flags(_outcome(config, comparator)) == expected


def test_verdict_changed_without_sign_change_keeps_classes() -> None:
    """Précision de D13 : un verdict modifié sans changement de signe — les classes de
    ``Ḡ`` et des ``G_j`` restent, le verdict non."""
    result = _outcome(decision(PROVISIONAL, passages=G.VIOLATED), decision(PROVISIONAL))
    assert result.verdict is AdmissionVerdict.REJECTED
    assert (result.mean_class, result.comparator_mean_class) == (1, 1)
    assert not any(g.class_changed for g in result.gains)


def test_no_decision_under_the_configuration() -> None:
    """Précision de D13 : sans performance évaluable, la configuration n'a que ses
    évaluations ; l'absence de décision compte comme un verdict ; les performances
    sortent, l'évaluabilité est perdue."""
    comparator = decision((0.5, 0.2, NE.MULTI_OUTING))
    config = assessments((NE.PASSAGE_UNAVAILABLE, NE.UNSCORED, NE.MULTI_OUTING))
    result = _outcome(config, comparator)
    assert result.admission is None
    assert result.assessments == config
    assert result.verdict is None
    assert (result.mean_class, result.comparator_mean_class) == (None, 1)
    assert flags(result) == (False, True, True, True)
    assert result.common == CommonSet((), (), (DAYS[0], DAYS[1]), None, None)


def test_no_decision_at_the_comparator() -> None:
    """Précision de D13 : sans décision au comparateur, jamais d'évaluabilité perdue ;
    le verdict change ; aucun gain comparable (le comparateur n'en a pas)."""
    comparator = assessments((NE.PASSAGE_UNAVAILABLE, NE.UNSCORED, NE.MULTI_OUTING))
    config = decision((0.5, 0.2, NE.MULTI_OUTING))
    result = _outcome(config, comparator)
    assert result.verdict is AdmissionVerdict.PROVISIONAL
    assert (result.mean_class, result.comparator_mean_class) == (1, None)
    assert flags(result) == (False, True, False, True)
    assert result.common == CommonSet((), (DAYS[0], DAYS[1]), (), None, None)


def test_no_decision_on_either_side() -> None:
    """Précision de D13 : deux absences de décision sont le même verdict."""
    side = assessments((NE.UNSCORED, NE.EXCLUDED))
    other = assessments((NE.EXCLUDED, NE.UNSCORED))
    assert flags(_outcome(side, other)) == (False, False, False, True)


def test_mean_gain_absent_on_one_side() -> None:
    """Précision de D13 : la classe de ``Ḡ`` se compare seulement si ``Ḡ`` est présent
    des deux côtés — une valeur absente n'est jamais un zéro."""
    comparator = decision((0.3, 0.2, ERR, 0.1))
    result = _outcome(decision((0.3, 0.2, 0.4, 0.1)), comparator)
    assert (result.mean_class, result.comparator_mean_class) == (1, None)
    assert flags(result) == (False, True, False, False)
    changed = _outcome(decision((0.3, -0.2, 0.4, 0.1)), comparator)
    assert flags(changed) == (True, True, False, False)


def test_comparator_without_any_gain() -> None:
    """Précision de D13, réserve 4 : le comparateur sans aucun gain — aucune
    configuration n'a de gain comparable, le comparateur compris."""
    comparator = decision((ERR, ERR, NE.UNSCORED))
    assert flags(_outcome(comparator, comparator, CENTRAL)) == (
        False,
        False,
        False,
        True,
    )
    assert _outcome(decision((0.5, 0.2, NE.UNSCORED)), comparator).sign_unverifiable


def test_configuration_outcome_publishes_gains_common_set_and_classes() -> None:
    """Précision de D13 : les gains comparés, l'ensemble commun (en complément), la
    classe de ``Ḡ`` de chaque admission sur son propre ensemble."""
    comparator = decision((0.5, NE.UNSCORED, 0.2, NE.PASSAGE_UNAVAILABLE, 0.1))
    config = decision((0.5, -2.0, 0.2, -1.0, NE.EXCLUDED))
    result = _outcome(config, comparator)
    assert result.gains == compare_gains(comparator, config)
    assert result.common == CommonSet(
        (DAYS[0], DAYS[2]),
        (DAYS[1], DAYS[3]),
        (DAYS[4],),
        math.fsum((0.5, 0.2)) / 2,
        math.fsum((0.5, 0.2)) / 2,
    )
    assert result.admission is config
    assert result.assessments is None
    assert isinstance(result.admission, Admission)
    assert result.admission.mean_gain == math.fsum((0.5, -2.0, 0.2, -1.0)) / 4
    assert (result.mean_class, result.comparator_mean_class) == (-1, 1)
    assert flags(result) == (True, True, True, False)


def test_mean_class_at_epsilon() -> None:
    """Précision de D13 : la classe de ``Ḡ`` a ses bornes dans la classe zéro."""
    result = _outcome(decision((EPSILON,)), decision((NEXT_UP,)))
    assert (result.mean_class, result.comparator_mean_class) == (0, 1)
    assert result.sign_changed


def test_common_set_means_use_fsum_in_configuration() -> None:
    """Précision de D13 : les moyennes de l'ensemble commun, ``fsum`` à poids égal."""
    comparator = decision((1e8, 1e-8, -1e8, NE.UNSCORED))
    result = _outcome(decision((1e8, 1e-8, -1e8, 0.4)), comparator)
    assert result.common == CommonSet(
        (DAYS[0], DAYS[1], DAYS[2]), (DAYS[3],), (), 1e-8 / 3, 1e-8 / 3
    )


def test_admission_is_under_the_configuration_clock() -> None:
    """Précision de D13 : l'admission refaite est sous l'horloge de la configuration
    (une configuration de mouvement)."""
    clock = CONFIGS[12].clock
    comparator = decision((0.5, 0.2), clock=clock)
    result = configuration_outcome(
        CONFIGS[12], _performances(2), decision((0.5, 0.3), clock=clock), comparator
    )
    assert result.admission is not None
    assert result.admission.clock == clock


# ---------------------------------------------------------------------------
# sensitivity_outcome, qualify_sensitivity
# ---------------------------------------------------------------------------


def _document(
    decisions: dict[int, Decision], comparator: int = CENTRAL
) -> SensitivityOutcome:
    """Le document des configurations ``decisions`` (rang → décision), dans l'ordre
    des rangs, comparées à celle de ``comparator``."""
    ranks = sorted(decisions)
    configurations = tuple(
        _outcome(decisions[rank], decisions[comparator], rank) for rank in ranks
    )
    return sensitivity_outcome(ranks.index(comparator), configurations)


def test_sensitivity_outcome_without_experiment() -> None:
    """Précision de D13 : pour ``just backtest``, aucune réserve — la sensibilité se
    publie configuration par configuration."""
    configurations = tuple(
        configuration_outcome(CONFIGS[rank], _performances(2))
        for rank in range(len(CONFIGS))
    )
    document = sensitivity_outcome(CENTRAL, configurations)
    assert document.reserves == ()
    assert document.comparator == CENTRAL
    assert document.configurations == configurations


def test_sensitivity_outcome_reserves_ranks_and_order() -> None:
    """Précision de D13, « Réserves » : chaque réserve dans l'ordre, avec les rangs de
    toutes les configurations qui la portent ; aucune entrée pour une réserve
    qu'aucune ne porte."""
    document = _document(
        {
            0: decision((0.5, -0.5, 0.5)),
            2: decision((0.5, 0.5, 0.5), passages=G.VIOLATED),
            4: decision((0.5, 0.5, 0.5)),
            6: decision((0.5, NE.UNSCORED, 0.5)),
            7: decision((0.5, 0.5, 0.0)),
        }
    )
    assert document.comparator == 2
    assert document.reserves == (
        ReserveEntry(R.SIGN_CHANGED, (0, 4)),
        ReserveEntry(R.VERDICT_CHANGED, (0, 1, 4)),
        ReserveEntry(R.EVALUABILITY_LOST, (3,)),
    )


def test_sensitivity_outcome_sign_unverifiable_entry() -> None:
    """Précision de D13, réserve 4 : le comparateur sans gain porte « signe non
    vérifiable », comme toute configuration."""
    document = _document({3: decision((ERR, 0.5)), 4: decision((ERR, ERR))})
    assert document.reserves == (ReserveEntry(R.SIGN_UNVERIFIABLE, (0, 1)),)


def test_sensitivity_outcome_without_reserve() -> None:
    """Précision de D13 : une expérience sans réserve n'a aucune entrée."""
    document = _document({3: decision((0.6, 0.4)), 4: decision((0.5, 0.5))})
    assert document.reserves == ()


def test_qualify_without_declared_sensitivity() -> None:
    """D10.6 (vue composée) : sans sensibilité déclarée, « centrale, sensibilité
    restante »."""
    assert qualify_sensitivity(False, None) == SensitivityQualification(
        SensitivityStatus.REMAINING, ()
    )


def test_qualify_without_result() -> None:
    """D10.6 : une sensibilité déclarée sans RÉSULTAT (ÉCHEC, ou interruption),
    « sensibilité incomplète »."""
    assert qualify_sensitivity(True, None) == SensitivityQualification(
        SensitivityStatus.INCOMPLETE, ()
    )


def test_qualify_with_reserves() -> None:
    """D10.6 : un RÉSULTAT, les réserves de son document, chacune avec les
    configurations qui la portent."""
    document = _document({0: decision((0.5, -0.5)), 4: decision((0.5, 0.5))})
    assert document.reserves
    assert qualify_sensitivity(True, document) == SensitivityQualification(
        SensitivityStatus.RESERVED, document.reserves
    )


def test_qualify_done() -> None:
    """D10.6 : un RÉSULTAT sans réserve, « sensibilité faite » — expérience, ou
    ``just backtest``."""
    done = SensitivityQualification(SensitivityStatus.DONE, ())
    experiment = _document({3: decision((0.6, 0.4)), 4: decision((0.5, 0.5))})
    plain = sensitivity_outcome(
        0, (configuration_outcome(CONFIGS[CENTRAL], _performances(1)),)
    )
    assert qualify_sensitivity(True, experiment) == done
    assert qualify_sensitivity(True, plain) == done


def test_qualify_precondition() -> None:
    """Précondition : un document demande une sensibilité déclarée."""
    plain = sensitivity_outcome(
        0, (configuration_outcome(CONFIGS[CENTRAL], _performances(1)),)
    )
    with pytest.raises(ValueError):  # noqa: PT011 — texte réécrit
        qualify_sensitivity(False, plain)


# ---------------------------------------------------------------------------
# Propriétés : une configuration comparée à elle-même
# ---------------------------------------------------------------------------


@st.composite
def observations(draw: st.DrawFn) -> Any:
    """Une observation : de 1 à 5 segments (classe, écoulé, temps nuls), des points de
    ``C_k`` (observés ou non, temps nuls), un lieu de ``K`` puis l'arrivée."""
    count = draw(st.integers(1, 5))
    clocks = st.lists(st.integers(1, len(CLOCKS) - 1), max_size=3)
    segments = [
        segment(
            k,
            draw(st.sampled_from((A, F, D, "mixed"))),
            draw(st.floats(10.0, 500.0)),
            zero=draw(clocks),
        )
        for k in range(count)
    ]
    distances = sorted(draw(st.lists(st.floats(1.0, 900.0), max_size=3)))
    points = [
        point(
            distance,
            draw(st.one_of(st.none(), st.floats(1.0, 900.0))),
            index=k + 1,
            zero=draw(clocks),
        )
        for k, distance in enumerate(distances)
    ]
    targets = [
        target(
            draw(st.floats(1.0, 900.0)),
            draw(st.one_of(st.none(), st.floats(1.0, 900.0))),
            occurrence=0,
            zero=draw(clocks),
        ),
        target(1000.0, draw(st.one_of(st.none(), st.floats(1.0, 2000.0)))),
    ]
    return observation(segments, points, targets)


@settings(max_examples=20, deadline=None)
@given(
    observations(),
    st.floats(0.5, 2.0),
    st.integers(0, len(CLOCKS) - 1),
    st.sampled_from([None, NOT_CALIBRATED, MODEL_ERROR]),
)
def test_configuration_against_itself_has_no_change(
    obs: Any, ratio: float, i: int, calage: Calage | None
) -> None:
    """Précision de D13 : le comparateur, comparé à lui-même, n'a ni perte, ni gain, ni
    composante changée, ni écart non nul."""
    calages = {} if calage is None else {i: calage}
    made = outcome(ID, obs, Calibrated(BASE, 0.8, calages), ratio=ratio)
    comparison = compare_performance(
        DAYS[0], ID, None, Side(made, CLOCKS[i]), Side(made, CLOCKS[i])
    )
    for item in comparison.metrics:
        assert item.support == ()
        assert item.comparator == item.value
        assert item.availability in (Availability.BOTH, Availability.NEITHER)
        if item.availability is Availability.BOTH:
            assert same_bits(item.difference, 0.0)
        else:
            assert item.difference is None


_GAIN_SPECS: st.SearchStrategy[GainSpec] = st.one_of(
    st.floats(-1.0, 1.0),
    st.sampled_from([EPSILON, -EPSILON, NEXT_UP, 0.0, ERR]),
    st.sampled_from([NE.UNSCORED, NE.EXCLUDED, NE.PASSAGE_UNAVAILABLE]),
)


@settings(max_examples=40, deadline=None)
@given(
    st.lists(_GAIN_SPECS, min_size=1, max_size=6),
    st.sampled_from(list(G)),
)
def test_decision_against_itself_has_no_reserve_but_unverifiable(
    specs: list[GainSpec], passages: GuardStatus
) -> None:
    """Précision de D13 : une décision comparée à elle-même n'a ni signe changé, ni
    verdict modifié, ni évaluabilité perdue ; « signe non vérifiable » si et seulement
    si elle n'a aucun gain ; ni entrante ni sortante."""
    made = decision(specs, passages=passages)
    result = _outcome(made, made)
    has_gain = any(isinstance(s, float) for s in specs)
    assert flags(result) == (False, False, False, not has_gain)
    assert result.common is not None
    assert (result.common.entering, result.common.leaving) == ((), ())
    assert result.common.comparator_mean == result.common.mean
    assert all(
        g.comparator_class == g.gain_class == expected_class(g.gain)
        for g in result.gains
    )


@settings(max_examples=40, deadline=None)
@given(st.lists(st.tuples(_GAIN_SPECS, _GAIN_SPECS), min_size=1, max_size=6))
def test_compare_gains_swaps_sides(pairs: list[tuple[GainSpec, GainSpec]]) -> None:
    """Précision de D13 : échanger le comparateur et la configuration échange les
    côtés de chaque gain ; un gain comparable d'un côté l'est de l'autre."""
    first = decision([p[0] for p in pairs])
    second = decision([p[1] for p in pairs])
    forward, backward = compare_gains(first, second), compare_gains(second, first)
    for there, back in zip(forward, backward, strict=True):
        assert (there.comparator_gain, there.comparator_motif) == (
            back.gain,
            back.motif,
        )
        assert (there.gain, there.motif) == (
            back.comparator_gain,
            back.comparator_motif,
        )
        assert there.comparable is back.comparable
        assert there.class_changed is back.class_changed
    assert forward == tuple(
        gain_comparison(day, *pair) for day, pair in zip(DAYS, pairs, strict=False)
    )
