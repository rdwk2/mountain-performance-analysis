"""Allers-retours de l'écriture canonique (§ 8.1, test 3, du brief M4b-4 ; ``0010``
D14).

Les contrats que le registre stocke, écrits puis relus : les scores des treize cas de
M4b-2 (observation, contrôle, usage), des références D8 de M4b-3, une prévision non
finie, des performances tirées par Hypothesis. Chaque fois, l'objet relu est égal à
l'objet écrit (sauf le NaN, comparé par ``math.isnan``) **et** sa réécriture donne les
mêmes octets.
"""

import json
import math
from dataclasses import replace
from datetime import date

import pytest
from hypothesis import given, settings

from fixtures import scoring
from fixtures.registry import CALIBRATED_MODELS, declaration, experiment
from fixtures.repeatability import case_reference
from mountain_perf.backtest import canonical_bytes, decode_contract, encode_contract
from mountain_perf.schemas import Performance
from strategies import performances


def _round_trip[T](value: T) -> T:
    """``value`` écrite puis relue ; la réécriture de l'objet relu redonne les
    octets."""
    data = canonical_bytes(encode_contract(value))
    back = decode_contract(type(value), json.loads(data))
    assert canonical_bytes(encode_contract(back)) == data
    return back


@pytest.mark.parametrize("name", list(scoring.SCORING_CASES))
def test_scores_of_the_m4b2_cases_round_trip(name: str) -> None:
    """D14 : observation, contrôle et usage présent de chaque cas de M4b-2."""
    scores = scoring.scores(name)
    assert _round_trip(scores.observation) == scores.observation
    assert _round_trip(scores.control) == scores.control
    if scores.usage is not None:
        assert _round_trip(scores.usage) == scores.usage


@pytest.mark.parametrize("name", ["Complet", "Lent", "Vide", "Multi-sorties"])
def test_repeatability_references_round_trip(name: str) -> None:
    """D14 (références D8 conservées) : quatre cas de M4b-3."""
    reference = case_reference(name)
    assert _round_trip(reference) == reference


def test_non_finite_forecast_round_trips() -> None:
    """D14 (prévisions conservées) : ``nan``, ``inf``, ``-inf`` et ``None`` dans
    ``segment_s`` se relisent tels quels."""
    forecast = scoring.scores("Régimes").control.forecast
    segment_s = (math.nan, math.inf, -math.inf, None, *forecast.segment_s)
    written = replace(forecast, segment_s=segment_s)
    back = _round_trip(written)
    first = back.segment_s[0]
    assert first is not None
    assert math.isnan(first)
    assert back.segment_s[1:] == segment_s[1:]
    assert replace(back, segment_s=segment_s) == written


@settings(max_examples=150, deadline=None)
@given(performances())
def test_performances_round_trip(performance: Performance) -> None:
    """D14 : une déclaration fige ses performances telles que le manifeste les
    décrit ; au moins 150 tirages."""
    assert _round_trip(performance) == performance


def test_declaration_with_an_experiment_round_trips() -> None:
    """D14, D10.7 : la déclaration du § 7.2, avec une expérience, sa date d'analyse et
    les modèles calés."""
    declared = declaration(
        models=CALIBRATED_MODELS,
        experiment=experiment(analysis_date=date(2026, 12, 1)),
    )
    assert _round_trip(declared) == declared
