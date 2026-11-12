"""Garanties d'OG-2 que la suite de la PR #44 ne tenait pas, vues par le balayage
``mutmut`` de la conception et par la contre-épreuve « Student à ``n`` dans l'IC95 »
du § 8.3 : l'intervalle et l'effet minimal détectable de Student, les petits
échantillons du rapport, et la correspondance à ses bornes. Chaque cas est écrit
contre la docstring de la fonction, pas contre son code."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from mountain_perf.backtest import registry as registry_module
from mountain_perf.backtest.correspondence import check_correspondence
from mountain_perf.backtest.registry import RegistryError
from mountain_perf.backtest.report import (
    common_usage_target,
    comparison_conclusion,
    contributor_means,
    minimum_detectable_effect,
    paired_difference,
)
from mountain_perf.backtest.student_t import student_t_quantile
from mountain_perf.estimation.origin import ActivityEnd, EndMethod
from mountain_perf.schemas import (
    CLOCKS,
    CalibrationTerm,
    ModelCalibration,
    ModelKind,
    Outing,
    Scenario,
    ScenarioClockTerms,
    Sport,
    Unavailability,
)
from mountain_perf.schemas.metrics import METRIC_RELATIVE_TOLERANCE

PARIS = ZoneInfo("Europe/Paris")
ORIGIN = datetime(2026, 6, 13, tzinfo=PARIS)


def paris(day: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 6, day, hour, minute, second, tzinfo=PARIS)


def outing(start: datetime, end: datetime, refs: tuple[str, ...]) -> Outing:
    return Outing(
        outing_id="s1",
        athlete_ref="x",
        sport=Sport.FOOT,
        start_time=start,
        end_time=end,
        activity_refs=refs,
    )


def both(ref: str, start: datetime, end: datetime) -> ActivityEnd:
    return ActivityEnd(ref, start, end, start, end, end, EndMethod.BOTH)


# --- Student (contre-épreuve du § 8.3 ; balayage) -------------------------------------


def test_student_interval_reads_n_minus_one() -> None:
    """Trois couples : t₀,₉₇₅(2) = 4,302 65… ; à n = 3, t₀,₉₇₅(3) = 3,182 45…"""
    found = paired_difference([(0.0, 0.1), (0.0, 0.2), (0.0, 0.3)])
    assert found.count == 3
    assert found.interval is not None
    low, high = found.interval
    half = 4.302652729911275 * 0.1 / math.sqrt(3)
    assert math.isclose(low, 0.2 - half, abs_tol=1e-9)
    assert math.isclose(high, 0.2 + half, abs_tol=1e-9)


def test_two_pairs_have_an_interval() -> None:
    """``None`` pour ``n < 2`` seulement : deux couples ont un IC (ddl 1)."""
    found = paired_difference([(0.0, 0.1), (0.0, 0.3)])
    assert found.count == 2
    assert found.interval is not None
    half = 12.706204736174698 * math.sqrt(0.02) / math.sqrt(2)
    assert math.isclose(found.interval[0], 0.2 - half, abs_tol=1e-9)


def test_every_field_of_the_small_samples() -> None:
    """Aucun couple : tout à zéro ; un couple : ses signes comptés, pas d'IC."""
    assert paired_difference([]) == type(paired_difference([]))(0, None, None, 0, 0, 0)
    one = paired_difference([(0.2, 0.1)])
    assert (one.count, one.interval) == (1, None)
    assert (one.later_better, one.earlier_better, one.ties) == (1, 0, 0)


def test_mde_at_two_reads_one_degree_of_freedom() -> None:
    expected = (
        (student_t_quantile(0.975, 1) + student_t_quantile(0.8, 1))
        * 0.0253
        / math.sqrt(2)
    )
    found = minimum_detectable_effect(2)
    assert found is not None
    assert math.isclose(found, expected, rel_tol=1e-12)


# --- Le rapport --------------------------------------------------------------------


def test_an_interval_that_touches_zero_contains_it() -> None:
    assert comparison_conclusion([(0.0, 0.1)]) is True
    assert comparison_conclusion([(-0.1, 0.0)]) is True


def test_common_usage_target_refuses_unequal_lengths() -> None:
    with pytest.raises(ValueError, match="zip"):
        common_usage_target([1.0, 2.0], [1.0], [1.0, 1.0])


def test_contributors_unavailable_say_zero_of_n() -> None:
    terms = [(date(2026, 6, 1), 100.0, 90.0), (date(2026, 6, 2), 100.0, 95.0)]
    members: list[tuple[date, list[tuple[str, tuple[str, ...]]]]] = [
        (date(2026, 6, 1), [("a", ("r1",))]),
        (date(2026, 6, 2), [("b", ())]),
    ]
    found = contributor_means(terms, members, frozenset({"r1"}))
    assert (found.contributors, found.members, found.unmatched) == (0, 2, ("b",))


# --- La correspondance (frontières de la docstring) ----------------------------------


def test_a_recording_that_starts_before_the_index_counts() -> None:
    """Le début de l'intervalle : le plus tôt d'``index_start`` et de
    ``recording_start``."""
    start, end = paris(12, 10), paris(12, 11)
    activity = ActivityEnd(
        "a", start + timedelta(minutes=5), end, start, end, end, EndMethod.BOTH
    )
    check_correspondence(outing(start, end, ("a",)), None, [activity], (ORIGIN,), 0.0)


def test_an_index_only_activity_starts_at_the_index() -> None:
    start, end = paris(12, 10), paris(12, 11)
    activity = ActivityEnd("a", start, end, None, None, end, EndMethod.INDEX_ONLY)
    check_correspondence(outing(start, end, ("a",)), None, [activity], (ORIGIN,), 0.0)


def test_a_zero_tolerance_is_admitted() -> None:
    start, end = paris(12, 10), paris(12, 11)
    check_correspondence(
        outing(start, end, ("a",)), None, [both("a", start, end)], (ORIGIN,), 0.0
    )


def test_one_common_instant_is_an_overlap() -> None:
    """« Un instant commun suffit » : une activité finie au premier point, une autre
    commencée au dernier."""
    start, end = paris(12, 10), paris(12, 11)
    activities = [
        both("a", paris(12, 9), start),
        both("b", start, end),
        both("c", end, paris(12, 12)),
    ]
    check_correspondence(
        outing(start, end, ("a", "b", "c")), None, activities, (ORIGIN,), 0.0
    )


def test_a_point_at_the_widened_start_is_covered() -> None:
    start, end = paris(12, 10), paris(12, 11)
    activity = both("a", start + timedelta(seconds=60), end)
    check_correspondence(outing(start, end, ("a",)), None, [activity], (ORIGIN,), 60.0)


def test_an_end_at_the_origin_is_on_the_origin_side() -> None:
    """Fin du manifeste et fin sûre toutes deux à l'origine : du même côté."""
    start = paris(12, 23)
    check_correspondence(
        outing(start, ORIGIN, ("a",)), None, [both("a", start, ORIGIN)], (ORIGIN,), 0.0
    )


# --- La condition 7, terme à terme (``_check_terms`` ; balayage) ----------------------

TAU = METRIC_RELATIVE_TOLERANCE
DAY = date(2026, 6, 1)


def _terms(observed_s: float, forecast_s: float | None) -> ScenarioClockTerms:
    return ScenarioClockTerms(
        Scenario.CONTROL, CLOCKS[0], (CalibrationTerm(DAY, observed_s, forecast_s),)
    )


def _calibrated(beta: float) -> ModelCalibration:
    """Un calage de baseline (Naismith : un facteur, pas d'effort) sur un jour."""
    return ModelCalibration(
        ModelKind.NAISMITH,
        Scenario.CONTROL,
        CLOCKS[0],
        (DAY,),
        (),
        beta,
        None,
        math.exp(beta),
        False,
        None,
    )


def test_a_model_error_without_a_missing_forecast_is_refused() -> None:
    """Un ``P_c`` absent ⟺ ``erreur du modèle`` : un calage en erreur dont tous les
    termes ont leur prévision est refusé, même quand la population n'est pas vide."""
    in_error = ModelCalibration(
        ModelKind.NAISMITH,
        Scenario.CONTROL,
        CLOCKS[0],
        (DAY,),
        (),
        None,
        None,
        None,
        False,
        Unavailability.MODEL_ERROR,
    )
    with pytest.raises(RegistryError, match="ne disent pas le statut"):
        registry_module._check_terms(in_error, _terms(3600.0, 3600.0), "")


def test_beta_at_exactly_the_tolerance_is_accepted() -> None:
    """``β`` à exactement ``τ·max(1, |β|)`` de ``fsum(ln(T_c / P_c)) / n`` (ici 0 :
    ``T_c = P_c``) : accepté, la borne est comprise."""
    registry_module._check_terms(_calibrated(TAU), _terms(3600.0, 3600.0), "")


def test_beta_beyond_the_tolerance_near_zero_is_refused() -> None:
    """Pour ``|β| < 1``, la tolérance est ``τ`` (``max(1, |β|)`` vaut 1) : un écart de
    1,5 τ est refusé."""
    with pytest.raises(RegistryError, match="n'est pas"):
        registry_module._check_terms(_calibrated(1.5 * TAU), _terms(3600.0, 3600.0), "")


def test_the_tolerance_grows_with_beta_beyond_one() -> None:
    """Pour ``|β|`` ≈ 2 (``T_c / P_c = e²``), la tolérance est ``τ·|β|`` ≈ 2 τ : un
    écart de 1,5 τ est accepté, un de 3 τ refusé."""
    observed = 3600.0 * math.exp(2.0)
    recomputed = math.log(observed / 3600.0)
    registry_module._check_terms(
        _calibrated(recomputed + 1.5 * TAU), _terms(observed, 3600.0), ""
    )
    with pytest.raises(RegistryError, match="n'est pas"):
        registry_module._check_terms(
            _calibrated(recomputed + 3.0 * TAU), _terms(observed, 3600.0), ""
        )
