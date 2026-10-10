"""Les invariants des scores calés (§ 6.2 et § 8.1, test 2, du brief M4c-2 ; ``0010``
D7.1, D7.3, D7.4, D9.2 ; décision Q2 de M4c-2 ; ligne de ``BACKLOG.md`` « (M4c-2,
avant le brief) Les contrats des scores calés… »).

Trois invariants neufs, recopiés des homologues de M4b-2 : sous chaque horloge calée
de ``CalibratedScenarioScores``, les supports et les erreurs aux passages de
``ScenarioScores`` (une horloge non calée n'entre dans aucune comparaison) ; les
longueurs d'usage d'``OutingScores`` pour ``CalibratedOutingScores`` ; une seule
observation par sortie dans ``CalibratedPerformance``. Les scores calés sont construits
depuis les cas de ``test_schemas_scoring.py`` (``_scenario``), chaque horloge calée à
``β = 0`` ; ``CalibratedPerformance`` sur le monde de M4c-1, recalculé à chaque appel,
sans cache.
"""

import re
from dataclasses import replace
from datetime import date

import pytest

from fixtures import calibration as world
from mountain_perf.backtest import calibrate_performances, support_metrics
from mountain_perf.schemas import (
    CLOCKS,
    CalibratedClockScores,
    CalibratedOutingScores,
    CalibratedPerformance,
    CalibratedScenarioScores,
    ClockScores,
    ModelCalibration,
    ModelKind,
    Scenario,
    ScenarioScores,
    Unavailability,
)
from mountain_perf.validation import ContractError
from test_schemas_scoring import ASCENT, CONTROL, FLAT, USAGE, _observation, _scenario

MODEL = ModelKind.TOBLER
DAY = date(2026, 6, 1)


def _calibrated_clock(scores: ClockScores, scenario: Scenario) -> CalibratedClockScores:
    """Une horloge calée à ``β = 0`` (facteur 1) et ses scores."""
    calibration = ModelCalibration(
        MODEL, scenario, scores.clock, (DAY,), (), 0.0, None, 1.0, False, None
    )
    return CalibratedClockScores(calibration, scores)


def _uncalibrated_clock(index: int, scenario: Scenario) -> CalibratedClockScores:
    """Une horloge non calée : ``C_j^eff`` vide, sans scores."""
    calibration = ModelCalibration(
        MODEL,
        scenario,
        CLOCKS[index],
        (),
        (),
        None,
        None,
        None,
        False,
        Unavailability.NOT_CALIBRATED,
    )
    return CalibratedClockScores(calibration, None)


def _calibrated(
    scores: ScenarioScores, uncalibrated: frozenset[int] = frozenset()
) -> CalibratedScenarioScores:
    """Les scores calés de ``scores`` : la même prévision non calée, chaque horloge
    calée à ``β = 0`` sauf celles d'``uncalibrated``."""
    return CalibratedScenarioScores(
        MODEL,
        scores.scenario,
        scores.forecast,
        tuple(
            _uncalibrated_clock(i, scores.scenario)
            if i in uncalibrated
            else _calibrated_clock(clock, scores.scenario)
            for i, clock in enumerate(scores.clocks)
        ),
    )


def _scores(scores: CalibratedScenarioScores, i: int) -> ClockScores:
    """Les scores de l'horloge ``i``, calée."""
    clock = scores.clocks[i].scores
    assert clock is not None
    return clock


def _with(
    scores: CalibratedScenarioScores, i: int, clock: ClockScores
) -> CalibratedScenarioScores:
    """``scores``, les scores de l'horloge ``i`` remplacés par ``clock``."""
    clocks = list(scores.clocks)
    clocks[i] = replace(clocks[i], scores=clock)
    return replace(scores, clocks=tuple(clocks))


# ---------------------------------------------------------------------------
# CalibratedScenarioScores, invariant 5 : les supports
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scenario", [USAGE, CONTROL])
def test_calibrated_scenario_scores_are_accepted(scenario: Scenario) -> None:
    """Des scores calés valides, en usage et en contrôle."""
    scores = _calibrated(_scenario(scenario))
    assert all(entry.scores is not None for entry in scores.clocks)


def test_support_count_follows_the_forecast() -> None:
    """Invariant 5 : ``support.segment_count == len(forecast.segment_s)`` sous chaque
    horloge calée."""
    scores = _calibrated(_scenario(CONTROL))
    forecast = replace(scores.forecast, segment_s=(100.0, 100.0))
    with pytest.raises(
        ContractError,
        match=re.escape(
            f"support.segment_count (1) sous {CLOCKS[0]} doit valoir "
            "len(forecast.segment_s) (2)."
        ),
    ):
        replace(scores, forecast=forecast)


def test_class_counts_are_those_of_the_other_clocks() -> None:
    """Invariant 5 : les mêmes effectifs de classe sous chaque horloge calée."""
    scores = _calibrated(_scenario(CONTROL))
    other = replace(
        _scores(scores, 1),
        support=support_metrics((100.0,), (80.0,), (ASCENT,)),
    )
    with pytest.raises(
        ContractError,
        match=re.escape(
            f"les effectifs de classe sous {CLOCKS[1]} doivent être ceux des autres "
            "horloges."
        ),
    ):
        _with(scores, 1, other)


def test_model_error_is_that_of_the_other_clocks() -> None:
    """Invariant 5, D7.1 : le même ``support.model_error`` sous chaque horloge calée."""
    scores = _calibrated(_scenario(CONTROL))
    flagged = replace(
        _scores(scores, 1), support=support_metrics((None,), (80.0,), (FLAT,))
    )
    with pytest.raises(
        ContractError,
        match=re.escape(
            f"support.model_error sous {CLOCKS[1]} doit être celui des autres "
            "horloges (D7.1)."
        ),
    ):
        _with(scores, 1, flagged)


def test_uncalibrated_clocks_are_not_compared() -> None:
    """Invariant 5 : une horloge non calée n'a pas de scores et n'entre dans aucune
    comparaison ; la première horloge **calée** sert de référence ; toutes non calées,
    rien n'est comparé."""
    ascent = _scenario(CONTROL, classes=(ASCENT,))
    flat = _scenario(CONTROL)
    # L'écoulé non calé ; la première calée (M θ1) en montée, comme les suivantes.
    scores = _calibrated(ascent, frozenset({0}))
    assert scores.clocks[0].scores is None
    # Une horloge calée en terrain plat après elle : nommée, contre M θ1.
    with pytest.raises(
        ContractError, match=re.escape(f"les effectifs de classe sous {CLOCKS[2]} ")
    ):
        _with(scores, 2, flat.clocks[2])
    # Seule la première horloge calée : rien à comparer au-delà d'elle.
    mixed = _calibrated(flat, frozenset(range(1, len(CLOCKS))))
    assert [entry.scores is None for entry in mixed.clocks] == [False] + [True] * 10
    # Toutes non calées : une prévision de deux segments, sans support à comparer.
    bare = _calibrated(flat, frozenset(range(len(CLOCKS))))
    two = replace(bare.forecast, segment_s=(100.0, 100.0))
    assert replace(bare, forecast=two).forecast.segment_s == (100.0, 100.0)


# ---------------------------------------------------------------------------
# CalibratedScenarioScores, invariant 6 : les passages
# ---------------------------------------------------------------------------


def test_passages_in_usage_only() -> None:
    """Invariant 6, D7.3, D7.4 : ``passage_errors`` présent sous une horloge calée si et
    seulement si le scénario est l'usage."""
    usage, control = _calibrated(_scenario(USAGE)), _calibrated(_scenario(CONTROL))
    usage_clock = _scores(usage, 3)
    bare = replace(usage_clock, passage_errors=None, usage_target=None)
    with pytest.raises(
        ContractError,
        match=re.escape(
            f"passage_errors sous {CLOCKS[3]} est présent si et seulement si le "
            "scénario est l'usage, reçu usage."
        ),
    ):
        _with(usage, 3, bare)
    control_clock = _scores(control, 3)
    dressed = replace(
        control_clock,
        passage_errors=usage_clock.passage_errors,
        usage_target=usage_clock.usage_target,
    )
    with pytest.raises(
        ContractError,
        match="est présent si et seulement si le scénario est l'usage, reçu control",
    ):
        _with(control, 3, dressed)


def test_passage_lengths_follow_the_forecast() -> None:
    """Invariant 6 : en usage, une erreur par point (``point_s``) et un élément de la
    cible par cumulé de ``K`` (``target_s``)."""
    usage = _calibrated(_scenario(USAGE))
    with pytest.raises(
        ContractError,
        match=re.escape(
            f"passage_errors sous {CLOCKS[0]} porte une erreur par point (2), reçu 1."
        ),
    ):
        replace(usage, forecast=replace(usage.forecast, point_s=(50.0, 51.0)))
    with pytest.raises(
        ContractError,
        match=re.escape(
            f"usage_target sous {CLOCKS[0]} porte un élément par cumulé de K (2), "
            "reçu 1."
        ),
    ):
        replace(usage, forecast=replace(usage.forecast, target_s=(60.0, 61.0)))


# ---------------------------------------------------------------------------
# CalibratedOutingScores, invariant 4 : les longueurs d'usage
# ---------------------------------------------------------------------------


def test_calibrated_outing_scores_usage_lengths() -> None:
    """Invariant 4, comme ``OutingScores`` : en usage, un cumulé par point de ``C_k``
    et par élément de ``K`` de l'observation."""
    observation = _observation()
    control = _calibrated(_scenario(CONTROL))
    usage = _calibrated(_scenario(USAGE))
    assert CalibratedOutingScores("x", observation, control, usage).usage is usage
    no_point = _calibrated(_scenario(USAGE, point_s=()))
    with pytest.raises(ContractError, match="usage : 0 cumulés pour 1 points de C_k"):
        CalibratedOutingScores("x", observation, control, no_point)
    two_targets = _calibrated(_scenario(USAGE, target_s=(1.0, 2.0)))
    with pytest.raises(ContractError, match="usage : 2 cumulés pour 1 éléments de K"):
        CalibratedOutingScores("x", observation, control, two_targets)


# ---------------------------------------------------------------------------
# CalibratedPerformance, invariant 3 : une observation par sortie
# ---------------------------------------------------------------------------


def _june_16() -> CalibratedPerformance:
    """Le calage du 16 juin du monde de M4c-1, calculé à chaque appel."""
    spec = world.WORLDS["Monde"]
    (performance,) = (
        result
        for result in calibrate_performances(
            world.world_performances(spec), world.world_scores(spec)
        )
        if result.population.civil_date == date(2026, 6, 16)
    )
    return performance


def test_one_observation_per_outing() -> None:
    """Invariant 3, D7.1 : les quatre modèles d'une sortie portent la même observation ;
    le groupe d'origine est accepté, une observation différente refusée."""
    performance = _june_16()
    assert CalibratedPerformance(performance.population, performance.outings)
    first, *others = performance.outings[:4]
    changed = replace(
        first.observation,
        reference_length_m=first.observation.reference_length_m + 1.0,
    )
    other = replace(first, observation=changed)
    with pytest.raises(
        ContractError,
        match=r"les quatre modèles de la sortie j1-0616 portent la même observation "
        r"\(D7\.1\)\.",
    ):
        CalibratedPerformance(performance.population, (other, *others))
