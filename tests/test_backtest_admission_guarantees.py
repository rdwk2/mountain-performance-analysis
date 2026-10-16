"""Garanties de la règle d'admission (M4c-3, ``backtest/admission.py``) que les tests
joints ne tenaient pas — correctifs de la relecture de la PR #25 (balayage de mutation
de la conception, relecture C).

- ``_guard`` : une classe de moins de trois segments n'entre pas au garde-fou de régime,
  les performances suivantes y restent ; l'empruntée ne sert qu'à une performance
  comparable (D10.3, D10.4) ;
- ``_passages`` : une performance sans passage comparable n'y entre pas, les suivantes
  si ; le ``K`` déclaré ; « observé avec ``T_k > 0`` » (D10.4, P11) ;
- ``_worst`` : une prévision invalide, non absente, rend le pire dommage absent ;
- ``_usage_values`` : (0) en erreur du modèle sous ``q_usage`` ;
- ``_calibrated_metric`` : le repli sur l'observation pour « support insuffisant »
  (choix 21) ;
- ``metric_value`` : sa précondition.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date

import pytest

from fixtures.admission import (
    EVALUATED,
    A,
    D,
    F,
    UsageK,
    X,
    borrowed,
    day,
    experiment,
    history,
    inputs,
    local,
)
from mountain_perf.backtest import metric_value
from mountain_perf.schemas import (
    DeclaredUsageTarget,
    ExperimentMetric,
    ObservedPoint,
    TargetMember,
    Unavailability,
)
from mountain_perf.schemas.admission import (
    NUMERIC_TOLERANCE,
    GuardStatus,
    ThresholdSource,
)
from test_backtest_admission import _admit

M = ExperimentMetric.DESCENT_LEVEL
USAGE = ExperimentMetric.USAGE
J1, J2 = date(2026, 6, 10), date(2026, 6, 11)


def test_regime_guard_skips_a_short_class_and_keeps_the_next_day() -> None:
    """D10.4, P8 : une évaluable dont la classe compte moins de trois segments — aucun
    de plat, **deux** de descente — n'entre pas à ces garde-fous de régime, et la
    suivante y reste ; la montée (sept segments) les garde toutes deux."""
    short = (A,) * 7 + (D,) * 2
    days = [
        history(),
        day("j1", EVALUATED["j1"], [100.0] * 9, [104.0] * 9, [102.0] * 9, short),
        day("j2", EVALUATED["j2"], [100.0] * 9, [104.0] * 9, [102.0] * 9),
    ]
    admission = _admit(days, experiment(USAGE))
    assert admission.evaluable == 2
    guards = {guard.metric: guard for guard in admission.guards}
    for metric in (
        ExperimentMetric.FLAT_LEVEL,
        ExperimentMetric.DESCENT_LEVEL,
        ExperimentMetric.FLAT_DISPERSION,
        ExperimentMetric.DESCENT_DISPERSION,
    ):
        assert [v.civil_date for v in guards[metric].values] == [J2]
    for metric in (ExperimentMetric.ASCENT_LEVEL, ExperimentMetric.ASCENT_DISPERSION):
        assert [v.civil_date for v in guards[metric].values] == [J1, J2]


def test_guard_threshold_borrows_only_for_a_comparable_performance() -> None:
    """D10.3, D10.4, P6 : sans locale du parcours, l'empruntée est la référence du
    garde-fou d'une performance **comparable** ; le seuil fixe, celui d'une performance
    non comparable (D+/km hors des bornes)."""
    level = ExperimentMetric.LEVEL
    refs = (local(level, 0.4, "b"), borrowed(level, 0.4))
    days = [
        history(),
        day("j1", EVALUATED["j1"], [100.0] * 9, [104.0] * 9, [102.0] * 9),
        day(
            "j2",
            EVALUATED["j2"],
            [100.0] * 9,
            [104.0] * 9,
            [102.0] * 9,
            dplus_per_km=200.0,
        ),
    ]
    admission = _admit(days, experiment(references=refs), refs)
    assert [a.comparable for a in admission.performances[1:]] == [True, False]
    (guard,) = [g for g in admission.guards if g.metric is level]
    assert [(v.source, v.reference) for v in guard.values] == [
        (ThresholdSource.BORROWED, 0.4),
        (ThresholdSource.FIXED, None),
    ]
    assert [v.local_unavailability for v in guard.values] == [Unavailability.ABSENT] * 2


def test_passages_skip_a_day_without_comparable_passage_and_keep_the_next() -> None:
    """D10.4, P11 : une évaluable sans passage observé (arrivée non observée, cible de
    régime) n'entre pas au garde-fou des passages, et la suivante y reste."""
    days = [
        history(),
        day(
            "j1",
            EVALUATED["j1"],
            [100.0] * 9,
            [104.0] * 9,
            [102.0] * 9,
            no_arrival=True,
        ),
        day("j2", EVALUATED["j2"], [100.0] * 9, [104.0] * 9, [102.0] * 9),
    ]
    admission = _admit(days, experiment(M))
    assert admission.evaluable == 2
    assert [(v.civil_date, v.passages) for v in admission.passages.values] == [(J2, 1)]
    assert admission.passages.status is GuardStatus.SATISFIED


_MEMBERS = (TargetMember(0, False), TargetMember(None, True))
_PASSAGE = ObservedPoint(100.0, None, 0, None, (100.0,) + (0.0,) * 10)
_ARRIVAL = ObservedPoint(400.0, 4, None, None, (400.0,) + (240.0,) * 10)


def test_passages_guard_uses_the_declared_k() -> None:
    """P11 : les éléments du ``K`` **déclaré** du parcours — ici le seul passage —, pas
    ceux du ``K`` par défaut (le passage et l'arrivée, tous deux observés)."""
    days = [
        replace(history(regimes=(X, A, F, D)), route="h"),
        day(
            "j",
            EVALUATED["j"],
            [100.0] * 4,
            [100.0] * 4,
            [90.0] * 4,
            (X, A, F, D),
            usage_k=UsageK(
                _MEMBERS, (_PASSAGE, _ARRIVAL), (100.0, 400.0), (90.0, 360.0)
            ),
        ),
    ]
    prefix = DeclaredUsageTarget("a", (TargetMember(0, False),), (1.0,))
    declared = _admit(days, experiment(USAGE, usage_targets=(prefix,)))
    assert [v.passages for v in declared.passages.values] == [1]
    default = _admit(days, experiment(USAGE))
    assert [v.passages for v in default.passages.values] == [2]


def test_a_passage_time_below_one_second_is_still_positive() -> None:
    """P11 : « observé avec ``T_k > 0`` » — une arrivée à 0,9 s compte."""
    times = [0.1] * 9
    days = [
        history(),
        day("j", EVALUATED["j"], times, times, [1.02 * t for t in times]),
    ]
    admission = _admit(days, experiment(M))
    assert [v.passages for v in admission.passages.values] == [1]
    assert admission.passages.status is GuardStatus.VIOLATED


def test_an_invalid_candidate_forecast_leaves_the_passages_unavailable() -> None:
    """§ 6.4, ``_worst`` ; précision de D10.4 : (1) calé — sa population, l'historique,
    est valide —, mais sa prévision du jour nulle à l'arrivée, une prévision
    **invalide** et non absente : le pire dommage est absent, le garde-fou des passages
    indisponible."""
    days = [history(), day("j", EVALUATED["j"], [100.0] * 9, [100.0] * 9, [0.0] * 9)]
    entry = inputs(days)[-1]
    assert entry.candidate is not None
    assert entry.candidate.clocks[0].calibration.unavailability is None
    admission = _admit(days, experiment(M))
    assert [(v.passages, v.worst) for v in admission.passages.values] == [(1, None)]
    assert admission.passages.status is GuardStatus.UNAVAILABLE


def test_usage_target_with_the_base_in_model_error() -> None:
    """§ 6.4, ``_usage_values`` : (0) en erreur du modèle sous l'horloge déclarée (une
    projection de v0 absente à l'historique) — les trois ``q_usage`` indisponibles au
    motif de son calage, effectif 0 ; la performance reste évaluable."""
    broken = replace(history(), v0=(None,) + (100.0,) * 8)
    days = [broken, day("j", EVALUATED["j"], [100.0] * 9, [106.0] * 9, [100.0] * 9)]
    assessed = _admit(days, experiment(USAGE)).performances[-1]
    assert assessed.motif is None
    for value in (assessed.base, assessed.candidate, assessed.raw):
        assert value is not None
        assert (value.value, value.unavailability, value.count) == (
            None,
            Unavailability.MODEL_ERROR,
            0,
        )
    assert assessed.gain is None
    assert assessed.raw_gain is None


def test_insufficient_support_wins_over_a_failed_calibration() -> None:
    """Choix 21, § 6.4 : sous ``q_usage``, une évaluable sans segment admis dont (1)
    est en erreur du modèle — son ``|L|`` au garde-fou est indisponible au motif de
    l'observation (« support insuffisant »), pas à celui du calage."""
    broken = replace(history(), candidate=(None,) + (100.0,) * 8)
    arrival = ObservedPoint(400.0, 0, None, None, (400.0,) + (240.0,) * 10)
    k = UsageK((TargetMember(None, True),), (arrival,), (420.0,), (400.0,))
    days = [broken, day("j", EVALUATED["j"], [], [], [], (), usage_k=k)]
    admission = _admit(days, experiment(USAGE))
    assert admission.performances[-1].motif is None
    (value,) = admission.guards[0].values
    assert value.candidate.unavailability is Unavailability.INSUFFICIENT_SUPPORT
    assert value.base.unavailability is Unavailability.INSUFFICIENT_SUPPORT


def test_metric_value_refuses_usage() -> None:
    """Précondition de ``metric_value`` (§ 6.4) : ``q_usage`` n'est pas une métrique du
    support."""
    days = [history(), day("j", EVALUATED["j"], [100.0] * 9, [100.0] * 9, [100.0] * 9)]
    entry = inputs(days)[-1]
    assert entry.raw is not None
    with pytest.raises(
        ValueError, match=re.escape("q_usage n'est pas une métrique du support.")
    ):
        metric_value(entry.raw.clocks[0], USAGE)


def test_a_gain_of_exactly_epsilon_is_not_a_success() -> None:
    """Décision E2, précision de D10.3 : « un succès est un ``G_j > ε`` ». Sous
    ``q_usage``, l'arrivée observée à 999 999 s, (0) à 1 000 000 s et (1) à 999 999 s,
    calés au facteur 1 par un historique neutre : le gain vaut exactement le flottant
    ``1e−6`` et ne compte pas au vote (relecture C d'Astra, C3)."""
    days = [
        history(),
        day(
            "j",
            EVALUATED["j"],
            [111111.0] * 9,
            [111111.0] * 8 + [111112.0],
            [111111.0] * 9,
        ),
    ]
    admission = _admit(days, experiment(USAGE))
    (assessed,) = [a for a in admission.performances if a.motif is None]
    assert assessed.gain == NUMERIC_TOLERANCE
    assert admission.positive == 0
