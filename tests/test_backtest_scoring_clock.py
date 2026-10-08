"""Les deux extraits de ``backtest/scoring.py`` (§ 6.3 et § 8.1, test 9, du brief
M4c-1).

- ``clock_scores`` : les scores sous une seule horloge valent **au bit** la ligne de
  ``score_scenario`` (§ 7.0), sur les treize cas de M4b-2 (``SCORING_CASES``), avec ou
  sans base de ``q_usage`` (``0010`` D7.4) ; ses préconditions : celles de
  ``score_scenario`` d'abord, puis l'indice d'horloge dans ``[0 ; 11[`` ;
- ``realized_profile`` : le profil de la trace, celui du scénario contrôle (``0010``
  D3 ; brief M4b-2, choix 4), le même que celui de la prévision de contrôle de v0 brut.
"""

from dataclasses import replace

import pytest

from fixtures import scoring
from mountain_perf.backtest import clock_scores, realized_profile, score_scenario
from mountain_perf.schemas import CLOCKS, ModelForecast, OutingScores


def _forecasts(outing: OutingScores) -> list[ModelForecast]:
    """Les prévisions des scénarios présents : contrôle, puis usage s'il existe."""
    present = (
        [outing.control] if outing.usage is None else [outing.control, outing.usage]
    )
    return [scenario.forecast for scenario in present]


def _usage(name: str) -> ModelForecast:
    usage = scoring.scores(name).usage
    assert usage is not None
    return usage.forecast


@pytest.mark.parametrize("name", list(scoring.SCORING_CASES))
def test_clock_scores_is_the_line_of_score_scenario(name: str) -> None:
    """§ 6.3 : ``clock_scores(obs, prévision, i)`` vaut au bit
    ``score_scenario(obs, prévision).clocks[i]``, sous chaque horloge et dans chaque
    scénario présent."""
    observation = scoring.observation(name)
    for forecast in _forecasts(scoring.scores(name)):
        rows = score_scenario(observation, forecast).clocks
        for i in range(len(CLOCKS)):
            assert clock_scores(observation, forecast, i) == rows[i]


def test_clock_scores_honours_the_base_of_q_usage() -> None:
    """§ 6.3, ``0010`` D7.4 : avec une base aux cumulés doublés, chaque ligne vaut celle
    de ``score_scenario(…, base=base)`` ; sans base, l'élément ``usage_target``
    diffère."""
    observation = scoring.observation("Passages")
    forecast = _usage("Passages")
    base = replace(
        forecast,
        target_s=tuple(None if p is None else 2.0 * p for p in forecast.target_s),
    )
    rows = score_scenario(observation, forecast, base=base).clocks
    for i in range(len(CLOCKS)):
        with_base = clock_scores(observation, forecast, i, base=base)
        assert with_base == rows[i]
        without = clock_scores(observation, forecast, i)
        assert without.usage_target != with_base.usage_target


@pytest.mark.parametrize("clock_index", [-1, len(CLOCKS)])
def test_clock_scores_refuses_an_index_outside_the_clocks(clock_index: int) -> None:
    """§ 6.3 : ``0 <= clock_index < len(CLOCKS)``, sinon ``ValueError``."""
    observation = scoring.observation("Passages")
    with pytest.raises(ValueError, match="clock_scores : clock_index"):
        clock_scores(observation, _usage("Passages"), clock_index)


def test_clock_scores_checks_the_preconditions_of_score_scenario_first() -> None:
    """§ 6.3 : les préconditions de ``score_scenario`` sont vérifiées d'abord — une
    prévision d'une autre longueur lève sa ``ValueError``, même à un indice faux."""
    observation = scoring.observation("Passages")
    forecast = _usage("Passages")
    short = replace(forecast, segment_s=forecast.segment_s[:-1])
    for clock_index in (0, len(CLOCKS)):
        with pytest.raises(ValueError, match="projections pour"):
            clock_scores(observation, short, clock_index)


@pytest.mark.parametrize("name", ["Régimes", "Passages", "Régimes sans référence"])
def test_realized_profile_is_the_profile_of_the_control_scenario(name: str) -> None:
    """§ 6.3, ``0010`` D3 : ``realized_profile(trace)`` est le profil de la trace
    (``trace_profile``), dont la source est celle de la prévision de contrôle de v0
    brut."""
    trace = scoring.chain(name).case.trace
    profile = realized_profile(trace)
    assert profile == scoring.trace_profile(trace)
    assert profile.source == scoring.scores(name).control.forecast.source
