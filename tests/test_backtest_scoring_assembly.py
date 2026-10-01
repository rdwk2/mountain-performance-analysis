"""Horloges du rapport et assemblage de v0 : ``report_clocks``, ``v0_scores``,
``score_outing`` (§ 6.6 et § 8.1, tests 10 et 11, du brief M4b-2 ; ``0010`` D3, D5.4,
D9.1 ; choix 4, 5 et 12).
"""

from datetime import UTC, datetime

import pytest

from fixtures.scoring import (
    GENERATED_AT,
    SCORING_CASES,
    chain,
    curve_read,
    scores,
    trace_profile,
)
from mountain_perf.backtest import (
    control_forecast,
    observe_outing,
    report_clocks,
    score_outing,
    score_scenario,
    usage_forecast,
    v0_scores,
)
from mountain_perf.model import PROJECTION_PARAMETER_SPECS, projected_timeline
from mountain_perf.schemas import CLOCKS, Clock, ClockKind, ParameterSet, Scenario

E = CLOCKS[0]


def _m(theta: int) -> Clock:
    return Clock(ClockKind.MOVING, theta - 1)


def _mu(theta: int) -> Clock:
    return Clock(ClockKind.MOVING_OR_UNDETERMINED, theta - 1)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Départ non daté", (E,)),
        ("Régimes", (E, _m(1), _mu(1))),
        ("Deux arrêts", (E, _m(3), _mu(5))),
        ("Passages", (E, _m(3), _mu(1))),
    ],
)
def test_report_clocks(name: str, expected: tuple[Clock, ...]) -> None:
    """Choix 12 (``0010`` D5.4) : l'écoulé, ``M`` sous ``θ_bas``, ``M + U`` sous
    ``θ_haut`` du ``MatchResult`` ; l'écoulé seul sans segment admis."""
    assert report_clocks(chain(name).match) == expected


@pytest.mark.parametrize("name", SCORING_CASES)
def test_v0_scores_is_the_composition_by_hand(name: str) -> None:
    """§ 6.6 ; choix 4 et 5 : ``v0_scores`` égale (``==``) ``observe_outing``, les
    deux prévisions de v0 brut sur ``projected_timeline`` (profil de la trace en
    contrôle, référence en usage), ``score_scenario`` et ``score_outing``, à
    ``generated_at`` égal."""
    c, read = chain(name), curve_read()
    with_reference = SCORING_CASES[name].with_reference
    parameters = ParameterSet(PROJECTION_PARAMETER_SPECS)
    observed = observe_outing(c.match, c.passages, c.partition)
    realized = trace_profile(c.case.trace)
    control = control_forecast(
        observed,
        projected_timeline(realized, read.curve, parameters),
        source=realized.source,
        curve_ref=read.curve_ref,
        parameters=parameters,
        generated_at=GENERATED_AT,
    )
    usage = None
    if with_reference:
        usage = score_scenario(
            observed,
            usage_forecast(
                observed,
                projected_timeline(c.profile, read.curve, parameters),
                source=c.profile.source,
                curve_ref=read.curve_ref,
                parameters=parameters,
                generated_at=GENERATED_AT,
            ),
        )
    expected = score_outing(observed, score_scenario(observed, control), usage)
    assert scores(name) == expected


def test_v0_scores_without_reference_has_no_usage() -> None:
    """``0010`` D3 (sortie sans référence) : ``reference=None`` — pas de scénario
    d'usage ; le contrôle porte la source de la trace."""
    outing = scores("Régimes sans référence")
    assert outing.usage is None
    assert outing.control.scenario is Scenario.CONTROL
    assert outing.control.forecast.source == chain("Régimes").case.trace.sources[0]


@pytest.mark.parametrize("name", ["Passages", "Régimes"])
def test_v0_scores_sources_and_parameters(name: str) -> None:
    """Choix 4 et 5 : source du contrôle = celle de la trace, de l'usage = celle de
    la référence ; v0 brut aux paramètres par défaut (effort 1)."""
    outing, c = scores(name), chain(name)
    assert outing.usage is not None
    assert outing.control.forecast.source == c.case.trace.sources[0]
    assert outing.usage.forecast.source == c.profile.source
    for scenario in (outing.control, outing.usage):
        assert scenario.forecast.parameters == ParameterSet(PROJECTION_PARAMETER_SPECS)
        assert scenario.forecast.parameters["effort"] == 1.0
        assert scenario.forecast.curve_ref == curve_read().curve_ref
        assert scenario.forecast.generated_at == GENERATED_AT


def test_v0_scores_dates_now_by_default() -> None:
    """§ 6.6 : ``generated_at`` absent — maintenant, avec fuseau."""
    c, read = chain("Passages"), curve_read()
    before = datetime.now(UTC)
    outing = v0_scores(
        c.profile,
        c.case.trace,
        c.match,
        c.passages,
        c.partition,
        read.curve,
        curve_ref=read.curve_ref,
    )
    after = datetime.now(UTC)
    for scenario in (outing.control, outing.usage):
        assert scenario is not None
        at = scenario.forecast.generated_at
        assert at.utcoffset() is not None
        assert before <= at <= after
