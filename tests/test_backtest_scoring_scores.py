"""Scores par scénario et horloge : ``score_scenario`` (§ 6.5 et § 8.1, tests 6 à 9,
du brief M4b-2 ; ``0010`` D5.4, D5.5, D7.1 à D7.4 ; choix 8 à 11).

- test 6 : les valeurs de l'oracle du § 7.3 sous ``E`` et, en usage, sous ``M θc`` ;
  les enveloppes des quatre cas qui les listent ;
- test 7 : réemploi au bit — chaque objet publié égale la fonction de M4b-1 appliquée
  aux vecteurs assemblés, sur les treize cas, les deux scénarios et les onze horloges ;
  chaque enveloppe égale ``log_ratio_envelope(P, a, b)`` du choix 9 ;
- test 8 : ``lower <= upper`` et l'encadrement exact de ``L`` sous les dix horloges
  ``M_θ`` et ``M_θ + U_θ``, sur les treize cas et Ligne droite à 2,9 s ;
- test 9 : des prévisions faites à la main sur l'observation de Passages — sorties de
  modèle invalides (des statuts), base distincte, préconditions (des ``ValueError``).

Le test 7 recalcule par la même écriture que le code : c'est son objet (quels vecteurs
vont à quelle fonction) ; il ne remplace pas les valeurs du test 6 (§ 8, vigilance 4).
"""

import math
from dataclasses import replace

import pytest

from fixtures.metrics import raises_value_error
from fixtures.scoring import (
    CONSTRUCTED,
    SCORING_CASES,
    close,
    observation,
    run_chain,
    run_scores,
    scores,
    straight_line,
)
from fixtures.scoring_values import VALUES, K, M, U
from mountain_perf.backtest import (
    is_invalid_model_output,
    log_ratio_envelope,
    passage_errors,
    positive_time_diagnostic,
    score_scenario,
    support_metrics,
    usage_target,
)
from mountain_perf.schemas import (
    CLOCKS,
    ClockKind,
    ClockScores,
    LogRatioEnvelope,
    MetricValue,
    ModelForecast,
    OutingObservation,
    OutingScores,
    RegimeClass,
    Scenario,
    ScenarioScores,
    Unavailability,
)

ELAPSED, MOVING_C = 0, 2
"""Indices dans ``CLOCKS`` de ``E`` et ``M θc`` (§ 7.0)."""

SCENARIO_CLOCKS = [i for i, c in enumerate(CLOCKS) if c.kind is not ClockKind.ELAPSED]
"""Les dix horloges ``M_θ`` et ``M_θ + U_θ`` de D5.4."""

ZERO = Unavailability.ZERO_TIME
MODEL_ERROR = Unavailability.MODEL_ERROR


def _scenarios(outing: OutingScores) -> list[ScenarioScores]:
    return [s for s in (outing.control, outing.usage) if s is not None]


# ---------------------------------------------------------------------------
# Test 6 : valeurs de l'oracle (§ 7.3)
# ---------------------------------------------------------------------------


def _check_metric(actual: MetricValue, expected: M) -> None:
    assert actual.unavailability is expected.motif
    assert actual.count == expected.count
    assert close(actual.value, expected.value)


def _check_clock(actual: ClockScores, expected: K, gap_m: float | None) -> None:
    support, row = actual.support, expected.support
    for value, wanted in zip(
        (
            support.log_ratio,
            support.dispersion,
            support.within,
            support.between,
            support.compensation,
        ),
        (row.level, row.dispersion, row.within, row.between, row.compensation),
        strict=True,
    ):
        _check_metric(value, wanted)
    if expected.diagnostic is None:
        assert actual.diagnostic is None
    else:
        assert actual.diagnostic is not None
        assert actual.diagnostic.mask == expected.diagnostic.mask
        _check_metric(actual.diagnostic.metrics.log_ratio, expected.diagnostic.level)
        _check_metric(
            actual.diagnostic.metrics.dispersion, expected.diagnostic.dispersion
        )
    if expected.passages is None:
        assert actual.passage_errors is None
    else:
        errors = actual.passage_errors
        assert errors is not None
        _check_metric(errors.max_abs_error_s, expected.passages.max_abs)
        _check_metric(errors.max_error_s, expected.passages.max)
        _check_metric(errors.min_error_s, expected.passages.min)
        assert errors.model_error is expected.passages.model_error
    if expected.target is None:
        assert actual.usage_target is None
    else:
        target = actual.usage_target
        assert target is not None
        _check_metric(target.q_usage, expected.target.q_usage)
        _check_metric(target.q_usage_prefix, expected.target.q_prefix)
        assert target.comparable == expected.target.comparable
        if expected.target.weights is None:
            assert target.weights is None
        else:
            assert target.weights is not None
            assert len(target.weights) == len(expected.target.weights)
            assert all(
                close(w, e)
                for w, e in zip(target.weights, expected.target.weights, strict=True)
            )
        assert target.arrival_anchor_gap_m == gap_m


def _check_envelopes(actual: ScenarioScores, expected: U) -> None:
    if expected.envelopes is None:
        return
    for envelope, row in zip(
        (actual.envelope, *actual.class_envelopes), expected.envelopes, strict=True
    ):
        if row is None:
            assert envelope is None
            continue
        assert envelope is not None
        assert envelope.unavailability is None
        assert close(envelope.lower, row.lower)
        assert close(envelope.upper, row.upper)
        assert close(envelope.min_abs, row.min_abs)


@pytest.mark.parametrize("name", CONSTRUCTED)
def test_usage_scores_under_the_elapsed_and_central_moving_clocks(name: str) -> None:
    """``0010`` D7.1 à D7.4, D5.5 ; choix 8 et 10 : métriques du support,
    diagnostic, agrégats de ``C_k``, ``q_usage``, ``q | préfixe``, comparables,
    poids et écart d'arrivée publié, sous ``E`` et ``M θc``, du § 7.3."""
    outing, expected = scores(name), VALUES[name]
    usage = outing.usage
    assert usage is not None
    assert expected.usage.moving is not None
    gap_m = outing.observation.arrival_anchor_gap_m
    _check_clock(usage.clocks[ELAPSED], expected.usage.elapsed, gap_m)
    _check_clock(usage.clocks[MOVING_C], expected.usage.moving, gap_m)


@pytest.mark.parametrize("name", SCORING_CASES)
def test_control_scores_under_the_elapsed_clock(name: str) -> None:
    """``0010`` D3, D7.1, D7.2 : métriques du support du contrôle sous ``E``, du
    § 7.3 ; ni ``C_k`` ni ``q_usage``."""
    expected = VALUES["Régimes" if name == "Régimes sans référence" else name]
    _check_clock(scores(name).control.clocks[ELAPSED], expected.control.elapsed, None)


@pytest.mark.parametrize(
    "name", ["Régimes", "Régimes déviation", "Passages", "Deux arrêts"]
)
def test_envelopes_of_the_four_cases(name: str) -> None:
    """``0010`` D5.4 ; choix 9 : les cinq enveloppes (support, puis montée, plat,
    descente, mixte) de l'usage et du contrôle, du § 7.3 ; une classe absente n'en a
    pas."""
    outing, expected = scores(name), VALUES[name]
    assert outing.usage is not None
    _check_envelopes(outing.usage, expected.usage)
    _check_envelopes(outing.control, expected.control)
    assert expected.usage.envelopes is not None
    assert expected.control.envelopes is not None


def test_regimes_without_reference_has_the_control_of_regimes() -> None:
    """« Régimes sans référence » (§ 7.2, ``0010`` D3) : pas d'usage ; le contrôle de
    Régimes, au bit."""
    alone = scores("Régimes sans référence")
    assert alone.usage is None
    assert alone.control == scores("Régimes").control


def test_diagnostic_follows_the_vector_motif_not_the_level() -> None:
    """Choix 8 (``0010`` D5.5) : sous ``M θc``, Régimes a ``L`` disponible et un
    temps nul — le diagnostic est déclenché par le motif vectoriel ``zero_time``, pas
    par celui de ``L``."""
    usage = scores("Régimes").usage
    assert usage is not None
    central = usage.clocks[MOVING_C]
    assert central.support.log_ratio.available
    assert central.support.dispersion.unavailability is ZERO
    assert central.diagnostic is not None


# ---------------------------------------------------------------------------
# Test 7 : réemploi au bit (§ 7.4)
# ---------------------------------------------------------------------------


def _envelope(
    scenario: ScenarioScores, observed: OutingObservation, members: list[int]
) -> LogRatioEnvelope | None:
    """Choix 9 : ``P`` = ``fsum`` des ``p_i`` du sous-ensemble, absent si un ``p_i``
    du support est invalide ; ``a``, ``b`` = min et max des dix sommes."""
    if not members:
        return None
    projected = scenario.forecast.segment_s
    total: float | None = None
    if not any(is_invalid_model_output(p) for p in projected):
        total = math.fsum(p for i in members if (p := projected[i]) is not None)
    sums = [
        math.fsum(observed.segments[i].times_s[k] for i in members)
        for k in SCENARIO_CLOCKS
    ]
    return log_ratio_envelope(total, min(sums), max(sums))


def _check_reuse(
    scenario: ScenarioScores,
    observed: OutingObservation,
    base_s: tuple[float | None, ...],
) -> None:
    forecast = scenario.forecast
    classes = tuple(s.regime_class for s in observed.segments)
    for i, clock_scores in enumerate(scenario.clocks):
        t = tuple(s.times_s[i] for s in observed.segments)
        support = support_metrics(forecast.segment_s, t, classes)
        assert clock_scores.support == support
        diagnostic = None
        if support.dispersion.unavailability is ZERO:
            diagnostic = positive_time_diagnostic(forecast.segment_s, t, classes)
        assert clock_scores.diagnostic == diagnostic
        if scenario.scenario is Scenario.CONTROL:
            assert clock_scores.passage_errors is None
            assert clock_scores.usage_target is None
            continue
        points, targets = observed.error_points, observed.targets
        assert clock_scores.passage_errors == passage_errors(
            forecast.point_s,
            [None if p.times_s is None else p.times_s[i] for p in points],
            [p.unavailability for p in points],
        )
        assert clock_scores.usage_target == usage_target(
            forecast.target_s,
            base_s,
            [None if p.times_s is None else p.times_s[i] for p in targets],
            [p.unavailability for p in targets],
            arrival_anchor_gap_m=observed.arrival_anchor_gap_m,
        )
    assert scenario.envelope == _envelope(
        scenario, observed, list(range(len(observed.segments)))
    )
    assert scenario.class_envelopes == tuple(
        _envelope(scenario, observed, [i for i, c in enumerate(classes) if c is r])
        for r in RegimeClass
    )


@pytest.mark.parametrize("name", SCORING_CASES)
def test_published_objects_are_the_m4b1_functions_at_the_bit(name: str) -> None:
    """§ 7.4 ; ``0010`` D5.4, D5.5, D7 ; choix 8 à 10 : sous les onze horloges et
    dans les deux scénarios, chaque objet publié (support, diagnostic, erreurs aux
    passages, cible d'usage de base la prévision elle-même) égale la fonction de
    M4b-1 appliquée aux vecteurs assemblés ; chaque enveloppe égale
    ``log_ratio_envelope(P, a, b)``."""
    outing = scores(name)
    for scenario in _scenarios(outing):
        _check_reuse(scenario, outing.observation, scenario.forecast.target_s)


# ---------------------------------------------------------------------------
# Test 8 : enveloppes et L (§ 7.4)
# ---------------------------------------------------------------------------


def _check_bracketing(outing: OutingScores) -> None:
    """Choix 9 : ``lower <= upper`` ; le ``L`` du support et celui de chaque classe,
    disponibles sous une horloge ``M_θ`` ou ``M_θ + U_θ``, dans ``[lower ; upper]``."""
    for scenario in _scenarios(outing):
        envelopes = (scenario.envelope, *scenario.class_envelopes)
        for envelope in envelopes:
            if envelope is not None and envelope.lower is not None:
                assert envelope.upper is not None
                assert envelope.lower <= envelope.upper
        for i in SCENARIO_CLOCKS:
            support = scenario.clocks[i].support
            levels = (
                support.log_ratio.value,
                *(regime.log_ratio.value for regime in support.classes),
            )
            for level, envelope in zip(levels, envelopes, strict=True):
                if level is None or envelope is None or envelope.lower is None:
                    continue
                assert envelope.upper is not None
                assert envelope.lower <= level <= envelope.upper


@pytest.mark.parametrize("name", SCORING_CASES)
def test_envelopes_bracket_the_level_on_the_cases(name: str) -> None:
    """``0010`` D5.4 : l'enveloppe encadre ``L`` sous les dix horloges scénarios."""
    _check_bracketing(scores(name))


@pytest.mark.parametrize("speed_ms", [1.0, 1.3])
def test_envelopes_on_a_straight_line_at_2_9_s(speed_ms: float) -> None:
    """Cas de régression Ligne droite à 2,9 s (§ 7.2 ; B2 de la passe 1, choix 9) :
    aucun arrêt, mais des sommes ``M`` et ``M + U`` qui diffèrent d'un ulp ; ``a`` et
    ``b`` pris sur les dix sommes, ``v0_scores`` ne lève pas et l'encadrement tient."""
    outing = run_scores(run_chain(straight_line(speed_ms)))
    assert outing.usage is not None
    assert outing.observation.segments
    _check_bracketing(outing)


# ---------------------------------------------------------------------------
# Test 9 : prévisions faites à la main, sur l'observation de Passages
# ---------------------------------------------------------------------------


def _passages() -> tuple[OutingObservation, ModelForecast]:
    usage = scores("Passages").usage
    assert usage is not None
    return observation("Passages"), usage.forecast


@pytest.mark.parametrize("invalid", [None, 0.0, math.nan])
def test_an_invalid_projection_is_a_model_error(invalid: float | None) -> None:
    """``0010`` D7.1 ; choix 9 et 11 : un ``p_i`` manquant, nul ou non fini est une
    sortie de modèle invalide — un statut, jamais une exception : ``model_error``
    sous chaque horloge, chaque enveloppe présente en ``model_error`` (classes
    comprises), le diagnostic selon M4b-1."""
    observed, forecast = _passages()
    bad = replace(forecast, segment_s=(invalid, *forecast.segment_s[1:]))
    scored = score_scenario(observed, bad)
    classes = tuple(s.regime_class for s in observed.segments)
    for i, clock_scores in enumerate(scored.clocks):
        assert clock_scores.support.model_error
        t = tuple(s.times_s[i] for s in observed.segments)
        if clock_scores.support.dispersion.unavailability is ZERO:
            assert clock_scores.diagnostic == positive_time_diagnostic(
                bad.segment_s, t, classes
            )
            assert clock_scores.diagnostic.metrics.model_error
        else:
            assert clock_scores.diagnostic is None
    present = [e for e in (scored.envelope, *scored.class_envelopes) if e is not None]
    assert len(present) == 2  # le support et la classe plat
    assert all(e.unavailability is MODEL_ERROR for e in present)


def test_an_invalid_point_projection_flags_the_passage_errors() -> None:
    """``0010`` D7.3 : un ``P_k`` de point à ``−1`` lève le drapeau de
    ``PassageErrors`` ; les agrégats sont ``model_error``."""
    observed, forecast = _passages()
    bad = replace(forecast, point_s=(-1.0, *forecast.point_s[1:]))
    for clock_scores in score_scenario(observed, bad).clocks:
        errors = clock_scores.passage_errors
        assert errors is not None
        assert errors.model_error
        assert errors.max_abs_error_s.unavailability is MODEL_ERROR
        assert errors.max_error_s.unavailability is MODEL_ERROR
        assert errors.min_error_s.unavailability is MODEL_ERROR


def test_an_invalid_target_projection_flags_the_usage_target() -> None:
    """``0010`` D7.4 ; choix 10 : un ``P_k`` de ``K`` absent lève le drapeau de
    ``UsageTarget`` ; la base étant la prévision elle-même, les poids sont absents."""
    observed, forecast = _passages()
    bad = replace(forecast, target_s=(None, *forecast.target_s[1:]))
    for clock_scores in score_scenario(observed, bad).clocks:
        target = clock_scores.usage_target
        assert target is not None
        assert target.model_error
        assert target.weights is None


def test_a_distinct_base_is_used_for_q_usage() -> None:
    """Choix 10 (``0010`` D7.4) : une ``base`` distincte (M4c) — ici des ``target_s``
    doublés — est la base de ``q_usage`` : le résultat égale
    ``usage_target(forecast.target_s, base.target_s, …)`` et diffère du résultat sans
    base."""
    observed, forecast = _passages()
    doubled = tuple(None if p is None else 2 * p for p in forecast.target_s)
    base = replace(forecast, target_s=doubled)
    with_base = score_scenario(observed, forecast, base=base)
    without = score_scenario(observed, forecast)
    _check_reuse(with_base, observed, base.target_s)
    for a, b in zip(with_base.clocks, without.clocks, strict=True):
        assert a.usage_target != b.usage_target


def test_preconditions_of_score_scenario() -> None:
    """Choix 11 : une base de contrôle, une base ou une prévision de mauvaise
    longueur sont des erreurs d'appel (``ValueError``), jamais un statut."""
    observed, forecast = _passages()
    control = scores("Passages").control.forecast
    with raises_value_error("la base de q_usage est une prévision d'usage"):
        score_scenario(observed, forecast, base=control)
    short = replace(forecast, target_s=forecast.target_s[:-1])
    with raises_value_error("la base a 3 cumulés pour 4 éléments de K"):
        score_scenario(observed, forecast, base=short)
    with raises_value_error("3 cumulés pour 4 éléments de K"):
        score_scenario(observed, short)
    with raises_value_error("4 cumulés pour 5 points de C_k"):
        score_scenario(observed, replace(forecast, point_s=forecast.point_s[:-1]))
    with raises_value_error("3 projections pour 4 segments admis"):
        score_scenario(observed, replace(forecast, segment_s=forecast.segment_s[:-1]))
    with raises_value_error("3 projections pour 4 segments admis"):
        score_scenario(observed, replace(control, segment_s=control.segment_s[:-1]))
