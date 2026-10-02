"""Contrats de la référence de répétabilité (§ 6.1 et § 8.1, test 1, du brief M4b-3 ;
``0010`` D8).

Pour chaque invariant de ``TwoWayFit``, ``RepeatabilityDay``, ``ClassFit``,
``ClassScore``, ``FoldScores``, ``ClockReference`` et ``RepeatabilityReference`` : un
objet construit à la main qui le viole (``ContractError``), et un objet valide à sa
limite. Constantes exactes : ``CERTIFICATION_TOLERANCE``, ``MIN_CONTRIBUTING_SEGMENTS``
(égal à ``UNDERREPRESENTED_BELOW`` de M4b-1), ``FIT_UNAVAILABILITY``.
"""

import math
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any

import pytest

from fixtures.outings import PARIS_SUMMER, outing_at, source
from mountain_perf.backtest import UNDERREPRESENTED_BELOW
from mountain_perf.schemas import (
    CERTIFICATION_TOLERANCE,
    CLOCKS,
    FIT_UNAVAILABILITY,
    MIN_CONTRIBUTING_SEGMENTS,
    AdmittedSegment,
    ClassFit,
    ClassScore,
    ClockReference,
    FoldScores,
    MetricValue,
    Performance,
    RegimeClass,
    RepeatabilityDay,
    RepeatabilityReference,
    TwoWayFit,
    Unavailability,
)
from mountain_perf.validation import ContractError

A, F, D, X = RegimeClass
INSUF = Unavailability.INSUFFICIENT_SUPPORT
UNIDENTIFIED = Unavailability.UNIDENTIFIED_REFERENCE
ZERO = Unavailability.ZERO_TIME
NON_CONV = Unavailability.NON_CONVERGENCE
ERR = Unavailability.MODEL_ERROR
ZEROS4 = (0.0, 0.0, 0.0, 0.0)
DAY1, DAY2, DAY3 = date(2026, 5, 1), date(2026, 5, 8), date(2026, 5, 15)
REFERENCE = source("gpx", "parcours.gpx", "7")


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------


def test_certification_tolerance_is_1e_8() -> None:
    """``0010`` D8.3 : les quatre critères sous ``1e−8``."""
    assert CERTIFICATION_TOLERANCE == 1e-8


def test_min_contributing_segments_is_underrepresented_below() -> None:
    """Précision de D8.4 (D7.5, D10.2) : trois segments, le seuil de M4b-1."""
    assert MIN_CONTRIBUTING_SEGMENTS == 3 == UNDERREPRESENTED_BELOW


def test_fit_unavailability_is_exact() -> None:
    assert frozenset({INSUF, UNIDENTIFIED, ZERO, NON_CONV, ERR}) == FIT_UNAVAILABILITY


# ---------------------------------------------------------------------------
# TwoWayFit
# ---------------------------------------------------------------------------


def _fit(**changes: Any) -> TwoWayFit:
    values: dict[str, Any] = {
        "segment_effects": ((0, 5.0), (1, 5.1)),
        "day_effects": ((0, -0.1), (1, 0.1)),
        "iterations": 2,
        "residuals": ZEROS4,
        "certified": True,
    }
    values.update(changes)
    return TwoWayFit(**values)


def test_two_way_fit_valid() -> None:
    assert _fit().certified


@pytest.mark.parametrize("name", ["segment_effects", "day_effects", "residuals"])
def test_two_way_fit_sequences_are_tuples(name: str) -> None:
    value = list(getattr(_fit(), name))
    with pytest.raises(ContractError, match=f"{name} doit être une séquence immuable"):
        _fit(**{name: value})


def test_two_way_fit_iterations_at_least_one() -> None:
    with pytest.raises(ContractError, match="iterations doit être >= 1"):
        _fit(iterations=0, residuals=(0.0, 0.0, 0.0, math.inf), certified=False)
    assert (
        _fit(
            iterations=1, residuals=(0.0, 0.0, 0.0, math.inf), certified=False
        ).iterations
        == 1
    )


@pytest.mark.parametrize("name", ["segment_effects", "day_effects"])
def test_two_way_fit_effects_not_empty(name: str) -> None:
    with pytest.raises(ContractError, match=f"{name} ne doit pas être vide"):
        _fit(**{name: ()})
    assert len(getattr(_fit(**{name: ((3, 1.0),)}), name)) == 1


@pytest.mark.parametrize("name", ["segment_effects", "day_effects"])
def test_two_way_fit_keys_strictly_increasing(name: str) -> None:
    with pytest.raises(ContractError, match=f"les clés de {name} sont strictement"):
        _fit(**{name: ((1, 5.0), (1, 5.1))})
    with pytest.raises(ContractError, match=f"les clés de {name} sont strictement"):
        _fit(**{name: ((2, 5.0), (1, 5.1))})
    assert _fit(**{name: ((1, 5.0), (7, 5.1))})


@pytest.mark.parametrize("name", ["segment_effects", "day_effects"])
@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_two_way_fit_effects_finite(name: str, bad: float) -> None:
    with pytest.raises(ContractError, match=rf"{name}\[1\] doit être fini"):
        _fit(**{name: ((0, 5.0), (1, bad))})


def test_two_way_fit_four_residuals() -> None:
    with pytest.raises(ContractError, match="residuals porte les quatre critères"):
        _fit(residuals=(0.0, 0.0, 0.0))


@pytest.mark.parametrize("bad", [-1e-12, math.nan, -math.inf])
@pytest.mark.parametrize("i", range(4))
def test_two_way_fit_residuals_non_negative_not_nan(i: int, bad: float) -> None:
    residuals = list(ZEROS4)
    residuals[i] = bad
    with pytest.raises(ContractError, match=rf"residuals\[{i}\] doit être >= 0"):
        _fit(residuals=tuple(residuals), certified=False)


def test_two_way_fit_infinite_increment_only_at_first_iteration() -> None:
    """Brief § 6.1 : ``residuals[3] = inf`` accepté à ``iterations == 1``, refusé à
    2 ; aucun autre critère infini."""
    first = _fit(iterations=1, residuals=(0.0, 0.0, 0.0, math.inf), certified=False)
    assert first.residuals[3] == math.inf
    with pytest.raises(ContractError, match=r"residuals\[3\] doit être fini"):
        _fit(iterations=2, residuals=(0.0, 0.0, 0.0, math.inf), certified=False)
    with pytest.raises(ContractError, match=r"residuals\[0\] doit être fini"):
        _fit(iterations=1, residuals=(math.inf, 0.0, 0.0, math.inf), certified=False)


@pytest.mark.parametrize("i", range(4))
def test_two_way_fit_certified_iff_four_criteria_below(i: int) -> None:
    """``0010`` D8.3, choix 3 : certifié **si et seulement si** les quatre critères
    sont strictement sous ``CERTIFICATION_TOLERANCE``."""
    at_threshold = list(ZEROS4)
    at_threshold[i] = CERTIFICATION_TOLERANCE
    with pytest.raises(ContractError, match="certified si et seulement si"):
        _fit(residuals=tuple(at_threshold), certified=True)
    assert not _fit(residuals=tuple(at_threshold), certified=False).certified
    below = list(ZEROS4)
    below[i] = math.nextafter(CERTIFICATION_TOLERANCE, 0.0)
    assert _fit(residuals=tuple(below), certified=True).certified
    with pytest.raises(ContractError, match="certified si et seulement si"):
        _fit(residuals=tuple(below), certified=False)


# ---------------------------------------------------------------------------
# RepeatabilityDay
# ---------------------------------------------------------------------------


def _performance(day: date, *, multi: bool = False) -> Performance:
    start = datetime(day.year, day.month, day.day, 9, 0, tzinfo=PARIS_SUMMER)
    outings = [outing_at(f"s-{day}", start, 3600.0)]
    if multi:
        outings.append(outing_at(f"s2-{day}", start + timedelta(hours=2), 1800.0))
    return Performance(day, tuple(outings))


def _segment(k: int) -> AdmittedSegment:
    low, high = 250.0 * k, 250.0 * (k + 1)
    return AdmittedSegment(k, low, high, low, high, low, high, A, (100.0,) * 11)


def test_repeatability_day_valid() -> None:
    day = RepeatabilityDay(_performance(DAY1), REFERENCE, (_segment(0), _segment(2)))
    assert day.segments is not None
    assert RepeatabilityDay(_performance(DAY1), REFERENCE, ()).segments == ()
    multi = RepeatabilityDay(_performance(DAY1, multi=True), REFERENCE, None)
    assert multi.segments is None


def test_repeatability_day_types() -> None:
    not_a_performance: Any = DAY1
    not_a_source: Any = "parcours.gpx"
    with pytest.raises(ContractError, match="performance doit être une Performance"):
        RepeatabilityDay(not_a_performance, REFERENCE, ())
    with pytest.raises(ContractError, match="reference doit être un SourceRef"):
        RepeatabilityDay(_performance(DAY1), not_a_source, ())


def test_repeatability_day_segments_absent_iff_multi_outing() -> None:
    """``0010`` D8.1 : un jour multi-sorties n'a pas de segments."""
    with pytest.raises(ContractError, match="segments est absent si et seulement si"):
        RepeatabilityDay(_performance(DAY1), REFERENCE, None)
    with pytest.raises(ContractError, match="segments est absent si et seulement si"):
        RepeatabilityDay(_performance(DAY1, multi=True), REFERENCE, ())


def test_repeatability_day_segments_tuple() -> None:
    segments: Any = [_segment(0)]
    with pytest.raises(ContractError, match="segments doit être une séquence immuable"):
        RepeatabilityDay(_performance(DAY1), REFERENCE, segments)


def test_repeatability_day_indices_strictly_increasing() -> None:
    with pytest.raises(ContractError, match="strictement croissants, reçu 1 puis 1"):
        RepeatabilityDay(_performance(DAY1), REFERENCE, (_segment(1), _segment(1)))
    with pytest.raises(ContractError, match="strictement croissants, reçu 2 puis 1"):
        RepeatabilityDay(_performance(DAY1), REFERENCE, (_segment(2), _segment(1)))


# ---------------------------------------------------------------------------
# ClassFit
# ---------------------------------------------------------------------------


def _class_fit(**changes: Any) -> ClassFit:
    values: dict[str, Any] = {
        "regime_class": A,
        "unavailability": None,
        "left_count": 3,
        "seen_count": 3,
        "training_days": 2,
        "training_segments": 3,
        "training_cells": 6,
        "zero_cells": (),
        "iterations": 2,
        "residuals": ZEROS4,
        "contraction": 0.0,
        "contraction_unavailability": None,
    }
    values.update(changes)
    return ClassFit(**values)


NO_COMPONENT: dict[str, Any] = {
    "training_days": 0,
    "training_segments": 0,
    "training_cells": 0,
    "iterations": None,
    "residuals": None,
    "contraction": None,
}


def _insufficient(**changes: Any) -> ClassFit:
    values: dict[str, Any] = {"unavailability": INSUF, "seen_count": 0}
    return _class_fit(**{**values, **NO_COMPONENT, **changes})


def test_class_fit_valid() -> None:
    assert _class_fit().unavailability is None
    assert _insufficient().seen_count == 0
    assert _insufficient(left_count=0).left_count == 0
    assert _class_fit(unavailability=UNIDENTIFIED, **NO_COMPONENT).seen_count == 3


def test_class_fit_zero_cells_tuple() -> None:
    with pytest.raises(ContractError, match="zero_cells doit être une séquence"):
        _class_fit(zero_cells=[])


def test_class_fit_motif_in_fit_unavailability() -> None:
    with pytest.raises(ContractError, match="motif d'ajustement hors de la liste"):
        _class_fit(unavailability=Unavailability.ABSENT)


def test_class_fit_seen_count_between_zero_and_left_count() -> None:
    with pytest.raises(ContractError, match="seen_count"):
        _class_fit(seen_count=4)
    with pytest.raises(ContractError, match="seen_count"):
        _insufficient(seen_count=-1)
    assert _class_fit(seen_count=3, left_count=3).seen_count == 3
    assert _class_fit(seen_count=1, left_count=3).seen_count == 1


def test_class_fit_insufficient_support_iff_no_segment_seen() -> None:
    """Précision de D8.2 : ``S_jR`` vide, ``support insuffisant`` ; et seulement
    alors."""
    with pytest.raises(ContractError, match="insufficient_support si et seulement si"):
        _class_fit(seen_count=0)
    with pytest.raises(ContractError, match="insufficient_support si et seulement si"):
        _class_fit(unavailability=INSUF, seen_count=1, **NO_COMPONENT)


def test_class_fit_component_counts() -> None:
    with pytest.raises(ContractError, match="une composante ajustée a au moins"):
        _class_fit(training_days=0)
    with pytest.raises(ContractError, match="une composante ajustée a au moins"):
        _class_fit(training_segments=0)
    with pytest.raises(ContractError, match="une composante ajustée a au moins"):
        _class_fit(training_days=2, training_segments=3, training_cells=2)
    with pytest.raises(ContractError, match="une composante ajustée a au moins"):
        _class_fit(training_days=4, training_segments=3, training_cells=3)
    at_limit = _class_fit(training_days=2, training_segments=3, training_cells=3)
    assert at_limit.training_cells == 3


@pytest.mark.parametrize("motif", [INSUF, UNIDENTIFIED])
def test_class_fit_without_component_counts_null(motif: Unavailability) -> None:
    seen = 0 if motif is INSUF else 2
    base = {**NO_COMPONENT, "unavailability": motif, "seen_count": seen}
    for name in ("training_days", "training_segments", "training_cells"):
        with pytest.raises(ContractError, match="sans composante"):
            _class_fit(**{**base, name: 1})
    with pytest.raises(ContractError, match="sans composante"):
        _class_fit(**base, zero_cells=((DAY1, 0),))


def test_class_fit_zero_time_iff_zero_cells() -> None:
    """``0010`` D8.3 : cellule nulle, ``temps nul`` ; et seulement alors."""
    zero = {"unavailability": ZERO, "iterations": None, "residuals": None}
    with pytest.raises(ContractError, match="zero_time si et seulement si"):
        _class_fit(**zero)
    with pytest.raises(ContractError, match="zero_time si et seulement si"):
        _class_fit(zero_cells=((DAY1, 0),))
    valid = _class_fit(**zero, zero_cells=((DAY1, 0), (DAY2, 1)))
    assert valid.zero_cells == ((DAY1, 0), (DAY2, 1))


@pytest.mark.parametrize("name", ["iterations", "residuals"])
def test_class_fit_iterations_present_iff_fitted(name: str) -> None:
    for motif in (None, NON_CONV, ERR):
        with pytest.raises(ContractError, match=f"{name} est présent si et seulement"):
            _class_fit(unavailability=motif, **{name: None})
    zero = {
        "unavailability": ZERO,
        "zero_cells": ((DAY1, 0),),
        "iterations": None,
        "residuals": None,
    }
    with pytest.raises(ContractError, match=f"{name} est présent si et seulement"):
        _class_fit(**{**zero, name: getattr(_class_fit(), name)})
    with pytest.raises(ContractError, match=f"{name} est présent si et seulement"):
        _class_fit(
            unavailability=UNIDENTIFIED,
            **{**NO_COMPONENT, name: getattr(_class_fit(), name)},
        )
    assert _class_fit(unavailability=NON_CONV, iterations=70).iterations == 70
    assert _class_fit(unavailability=ERR).residuals == ZEROS4


def test_class_fit_iterations_at_least_one() -> None:
    with pytest.raises(ContractError, match="iterations doit être >= 1"):
        _class_fit(iterations=0)
    assert _class_fit(iterations=1).iterations == 1


def test_class_fit_contraction_in_unit_interval() -> None:
    for bad in (-1e-12, 1.0 + 1e-12, math.nan):
        with pytest.raises(ContractError, match="contraction doit être dans"):
            _class_fit(contraction=bad)
    assert _class_fit(contraction=1.0).contraction == 1.0


def test_class_fit_contraction_unavailability_is_non_convergence() -> None:
    with pytest.raises(ContractError, match="absent ou non_convergence"):
        _class_fit(contraction=None, contraction_unavailability=ZERO)
    fit = _class_fit(contraction=None, contraction_unavailability=NON_CONV)
    assert fit.contraction_unavailability is NON_CONV


def test_class_fit_exactly_one_contraction_with_component() -> None:
    with pytest.raises(ContractError, match="exactement un de contraction"):
        _class_fit(contraction=None)
    with pytest.raises(ContractError, match="exactement un de contraction"):
        _class_fit(contraction=0.5, contraction_unavailability=NON_CONV)


def test_class_fit_no_contraction_without_component() -> None:
    with pytest.raises(ContractError, match="ni contraction ni"):
        _insufficient(contraction=0.0)
    with pytest.raises(ContractError, match="ni contraction ni"):
        _insufficient(contraction_unavailability=NON_CONV)


def test_class_fit_one_training_day_has_zero_contraction() -> None:
    """Précision de D8.3 : ``μ₂`` vaut ``0`` pour un seul jour."""
    one_day = {"training_days": 1, "training_segments": 3, "training_cells": 3}
    with pytest.raises(ContractError, match="μ₂ vaut 0 pour un seul jour"):
        _class_fit(**one_day, contraction=0.25)
    assert _class_fit(**one_day, contraction=0.0).contraction == 0.0
    fit = _class_fit(**one_day, contraction=None, contraction_unavailability=NON_CONV)
    assert fit.contraction is None


# ---------------------------------------------------------------------------
# ClassScore
# ---------------------------------------------------------------------------


def _score(
    regime: RegimeClass = A,
    count: int = 3,
    values: tuple[float, float] | Unavailability = (0.05, 0.02),
    contributes: bool | None = None,
) -> ClassScore:
    if isinstance(values, Unavailability):
        log_ratio = dispersion = MetricValue(None, values, count)
    else:
        log_ratio = MetricValue(values[0], None, count)
        dispersion = MetricValue(values[1], None, count)
    if contributes is None:
        contributes = log_ratio.available and count >= MIN_CONTRIBUTING_SEGMENTS
    return ClassScore(regime, count, log_ratio, dispersion, contributes)


def test_class_score_valid() -> None:
    assert _score().contributes
    assert not _score(count=0, values=INSUF).contributes
    assert not _score(count=2, values=ZERO).contributes


def test_class_score_count_non_negative() -> None:
    value = MetricValue(None, INSUF, 0)
    with pytest.raises(ContractError, match="segment_count doit être >= 0"):
        ClassScore(A, -1, value, value, False)


def test_class_score_counts_equal_segment_count() -> None:
    present = MetricValue(0.05, None, 3)
    other = MetricValue(0.02, None, 2)
    with pytest.raises(ContractError, match=r"dispersion\.count \(2\)"):
        ClassScore(A, 3, present, other, True)
    with pytest.raises(ContractError, match=r"log_ratio\.count \(2\)"):
        ClassScore(A, 3, other, present, True)


def test_class_score_both_present_or_same_motif() -> None:
    present = MetricValue(0.05, None, 3)
    with pytest.raises(ContractError, match="présents, ou absents avec le même motif"):
        ClassScore(A, 3, present, MetricValue(None, ZERO, 3), False)
    with pytest.raises(ContractError, match="présents, ou absents avec le même motif"):
        ClassScore(A, 3, MetricValue(None, ZERO, 3), MetricValue(None, ERR, 3), False)


def test_class_score_empty_class_is_insufficient_support() -> None:
    with pytest.raises(ContractError, match="sans segment vu porte le motif"):
        _score(count=0, values=ZERO)


def test_class_score_dispersion_non_negative() -> None:
    with pytest.raises(ContractError, match="dispersion doit être >= 0"):
        _score(values=(0.05, -1e-12))
    assert _score(values=(0.05, 0.0)).dispersion.value == 0.0


def test_class_score_one_segment_has_zero_dispersion() -> None:
    """``0010`` D7.2 : ``D_R = 0`` exactement pour un segment."""
    with pytest.raises(ContractError, match="D_R vaut 0 exactement"):
        _score(count=1, values=(0.05, 1e-17))
    assert _score(count=1, values=(0.05, 0.0)).dispersion.value == 0.0


def test_class_score_contributes_iff_value_and_three_segments() -> None:
    """Précision de D8.4 (D7.5, D10.2) : une valeur contribue si et seulement si elle
    est présente et sa classe a au moins trois segments dans ``S_j``."""
    with pytest.raises(ContractError, match="contributes si et seulement si"):
        _score(count=3, contributes=False)
    with pytest.raises(ContractError, match="contributes si et seulement si"):
        _score(count=2, contributes=True)
    with pytest.raises(ContractError, match="contributes si et seulement si"):
        _score(count=3, values=ZERO, contributes=True)
    assert _score(count=3, contributes=True).contributes
    assert not _score(count=2, contributes=False).contributes


# ---------------------------------------------------------------------------
# FoldScores
# ---------------------------------------------------------------------------


FORECASTS = ((0, 200.0), (1, 210.0), (2, 190.0))


def _fits(descent: ClassFit | None = None) -> tuple[ClassFit, ...]:
    return (
        _class_fit(),
        _insufficient(regime_class=F, left_count=0),
        descent or _insufficient(regime_class=D, left_count=0),
        _insufficient(regime_class=X, left_count=0),
    )


def _classes(descent: ClassScore | None = None) -> tuple[ClassScore, ...]:
    return (
        _score(),
        _score(F, 0, INSUF),
        descent or _score(D, 0, INSUF),
        _score(X, 0, INSUF),
    )


def _fold(**changes: Any) -> FoldScores:
    values: dict[str, Any] = {
        "day": DAY1,
        "support_count": 3,
        "predicted_count": 3,
        "fits": _fits(),
        "forecast_s": FORECASTS,
        "level": MetricValue(0.02, None, 3),
        "classes": _classes(),
    }
    values.update(changes)
    return FoldScores(**values)


UNIDENTIFIED_DESCENT = _class_fit(
    regime_class=D,
    unavailability=UNIDENTIFIED,
    seen_count=2,
    left_count=2,
    **NO_COMPONENT,
)


def _failed_fold(**changes: Any) -> FoldScores:
    """Un pli à descente non identifiée : ``S_j`` 5, ``P_j`` 3, ``L`` absent."""
    values: dict[str, Any] = {
        "support_count": 5,
        "fits": _fits(UNIDENTIFIED_DESCENT),
        "level": MetricValue(None, UNIDENTIFIED, 5),
        "classes": _classes(_score(D, 2, UNIDENTIFIED)),
    }
    values.update(changes)
    return _fold(**values)


def test_fold_scores_valid() -> None:
    assert _fold().level.available
    assert _failed_fold().predicted_count == 3


@pytest.mark.parametrize("name", ["fits", "forecast_s", "classes"])
def test_fold_scores_sequences_are_tuples(name: str) -> None:
    with pytest.raises(ContractError, match=f"{name} doit être une séquence immuable"):
        _fold(**{name: list(getattr(_fold(), name))})


def test_fold_scores_forecast_keys_strictly_increasing() -> None:
    with pytest.raises(ContractError, match="les clés de forecast_s sont strictement"):
        _fold(forecast_s=((0, 200.0), (2, 190.0), (1, 210.0)))
    with pytest.raises(ContractError, match="les clés de forecast_s sont strictement"):
        _fold(forecast_s=((0, 200.0), (0, 210.0), (2, 190.0)))


@pytest.mark.parametrize("bad", [math.inf, math.nan, 0.0, -0.0, -1.0])
def test_fold_scores_forecasts_finite_positive(bad: float) -> None:
    """Précision de D8.3 : une prévision non finie ou nulle n'est jamais publiée
    (``erreur du modèle``)."""
    with pytest.raises(ContractError, match="doit être finie et > 0"):
        _fold(forecast_s=((0, 200.0), (1, bad), (2, 190.0)))
    tiny = math.nextafter(0.0, 1.0)
    assert _fold(forecast_s=((0, tiny), (1, 210.0), (2, 190.0))).forecast_s[0][1] > 0


def test_fold_scores_one_forecast_per_predicted_segment() -> None:
    with pytest.raises(ContractError, match="une prévision par segment prévu"):
        _fold(forecast_s=FORECASTS[:2])


@pytest.mark.parametrize("name", ["fits", "classes"])
def test_fold_scores_four_classes_in_order(name: str) -> None:
    items = getattr(_fold(), name)
    swapped = (items[1], items[0], items[2], items[3])
    with pytest.raises(ContractError, match=f"{name} porte les quatre classes"):
        _fold(**{name: swapped})
    with pytest.raises(ContractError, match=f"{name} porte les quatre classes"):
        _fold(**{name: items[:3]})


def test_fold_scores_support_count_is_sum_of_seen() -> None:
    with pytest.raises(ContractError, match=r"support_count .* somme des seen_count"):
        _fold(support_count=4, level=MetricValue(0.02, None, 4))


def test_fold_scores_predicted_count_is_sum_of_fitted_seen() -> None:
    """Précision de D8.4 : ``P_j``, la partie de ``S_j`` prévue par les ajustements
    disponibles — une classe en échec n'y compte pas."""
    with pytest.raises(ContractError, match=r"predicted_count .* sans motif"):
        _failed_fold(
            predicted_count=5,
            forecast_s=((*FORECASTS, (3, 120.0), (4, 130.0))),
        )


def test_fold_scores_class_count_is_seen_count() -> None:
    with pytest.raises(ContractError, match=r"classes\[0\]\.segment_count"):
        _fold(classes=(_score(count=2, contributes=False), *_classes()[1:]))


def test_fold_scores_level_count_is_support_count() -> None:
    with pytest.raises(ContractError, match=r"level\.count \(2\)"):
        _fold(level=MetricValue(0.02, None, 2))


def test_fold_scores_strict_level() -> None:
    """Décision 5 du brief (``|L|`` strict, précision de D8.4) : ``L`` présent exige
    ``P_j = S_j``."""
    with pytest.raises(ContractError, match=r"\|L\| strict"):
        _failed_fold(level=MetricValue(0.02, None, 5))
    assert _failed_fold().level.unavailability is UNIDENTIFIED


# ---------------------------------------------------------------------------
# ClockReference
# ---------------------------------------------------------------------------


ABSENT_F = MetricValue(None, INSUF, 0)


def _clock_reference(**changes: Any) -> ClockReference:
    values: dict[str, Any] = {
        "clock": CLOCKS[0],
        "folds": (_fold(), _fold(day=DAY2)),
        "level": MetricValue(0.02, None, 2),
        "log_ratios": (MetricValue(0.05, None, 2), ABSENT_F, ABSENT_F, ABSENT_F),
        "dispersions": (MetricValue(0.02, None, 2), ABSENT_F, ABSENT_F, ABSENT_F),
    }
    values.update(changes)
    return ClockReference(**values)


def test_clock_reference_valid() -> None:
    assert _clock_reference().level.count == 2
    one = _clock_reference(
        folds=(_fold(),),
        level=MetricValue(None, INSUF, 1),
        log_ratios=(MetricValue(None, INSUF, 1), ABSENT_F, ABSENT_F, ABSENT_F),
        dispersions=(MetricValue(None, INSUF, 1), ABSENT_F, ABSENT_F, ABSENT_F),
    )
    assert one.level.count == 1


@pytest.mark.parametrize("name", ["folds", "log_ratios", "dispersions"])
def test_clock_reference_sequences_are_tuples(name: str) -> None:
    with pytest.raises(ContractError, match=f"{name} doit être une séquence immuable"):
        _clock_reference(**{name: list(getattr(_clock_reference(), name))})


@pytest.mark.parametrize("name", ["log_ratios", "dispersions"])
def test_clock_reference_four_class_values(name: str) -> None:
    with pytest.raises(ContractError, match=f"{name} porte une valeur par classe"):
        _clock_reference(**{name: getattr(_clock_reference(), name)[:3]})


def test_clock_reference_absent_f_is_insufficient_support_of_at_most_one() -> None:
    """Précision de D8.4 : ``m_q <= 1`` → ``support insuffisant``."""
    no_level = {"folds": (_failed_fold(), _failed_fold(day=DAY2))}
    with pytest.raises(ContractError, match="un F absent porte insufficient_support"):
        _clock_reference(**no_level, level=MetricValue(None, ZERO, 0))
    with pytest.raises(ContractError, match="un F absent porte insufficient_support"):
        _clock_reference(**no_level, level=MetricValue(None, INSUF, 2))


def test_clock_reference_present_f_has_two_folds_and_is_non_negative() -> None:
    with pytest.raises(ContractError, match="un F présent a un effectif >= 2"):
        _clock_reference(folds=(_fold(),), level=MetricValue(0.02, None, 1))
    with pytest.raises(ContractError, match="un F présent a un effectif >= 2"):
        _clock_reference(level=MetricValue(-1e-12, None, 2))
    assert _clock_reference(level=MetricValue(0.0, None, 2)).level.value == 0.0


def test_clock_reference_level_count_is_folds_with_level() -> None:
    three = {
        "folds": (_fold(), _fold(day=DAY2), _failed_fold(day=DAY3)),
        "log_ratios": (MetricValue(0.05, None, 3), ABSENT_F, ABSENT_F, ABSENT_F),
        "dispersions": (MetricValue(0.02, None, 3), ABSENT_F, ABSENT_F, ABSENT_F),
    }
    with pytest.raises(ContractError, match=r"level\.count .* nombre de plis où L"):
        _clock_reference(**three, level=MetricValue(0.02, None, 3))
    assert _clock_reference(**three).level.count == 2


@pytest.mark.parametrize("name", ["log_ratios", "dispersions"])
def test_clock_reference_class_counts_are_contributing_folds(name: str) -> None:
    values = list(getattr(_clock_reference(), name))
    values[0] = MetricValue(0.05, None, 3)
    with pytest.raises(ContractError, match="le nombre de plis où elle contribue"):
        _clock_reference(**{name: tuple(values)})
    values = list(getattr(_clock_reference(), name))
    values[2] = MetricValue(None, INSUF, 1)
    with pytest.raises(ContractError, match="le nombre de plis où elle contribue"):
        _clock_reference(**{name: tuple(values)})


# ---------------------------------------------------------------------------
# RepeatabilityReference
# ---------------------------------------------------------------------------


def _clocks(days: tuple[date, ...]) -> tuple[ClockReference, ...]:
    folds = tuple(_fold(day=day) for day in days)
    count = len(folds)
    if count >= 2:
        level, log_ratio, dispersion = (
            MetricValue(0.02, None, count),
            MetricValue(0.05, None, count),
            MetricValue(0.02, None, count),
        )
    else:
        level = log_ratio = dispersion = MetricValue(None, INSUF, count)
    return tuple(
        ClockReference(
            clock,
            folds,
            level,
            (log_ratio, ABSENT_F, ABSENT_F, ABSENT_F),
            (dispersion, ABSENT_F, ABSENT_F, ABSENT_F),
        )
        for clock in CLOCKS
    )


def _reference(**changes: Any) -> RepeatabilityReference:
    values: dict[str, Any] = {
        "reference": REFERENCE,
        "days": (DAY1, DAY3),
        "multi_outing_days": (DAY2,),
        "single_contrast": True,
        "clocks": _clocks((DAY1, DAY3)),
    }
    values.update(changes)
    return RepeatabilityReference(**values)


def test_repeatability_reference_valid() -> None:
    assert _reference().single_contrast
    empty = _reference(
        days=(), multi_outing_days=(), single_contrast=False, clocks=_clocks(())
    )
    assert empty.days == ()


@pytest.mark.parametrize("name", ["days", "multi_outing_days", "clocks"])
def test_repeatability_reference_sequences_are_tuples(name: str) -> None:
    with pytest.raises(ContractError, match=f"{name} doit être une séquence immuable"):
        _reference(**{name: list(getattr(_reference(), name))})


def test_repeatability_reference_days_strictly_increasing() -> None:
    with pytest.raises(ContractError, match="days est strictement croissant"):
        _reference(days=(DAY3, DAY1), clocks=_clocks((DAY3, DAY1)))
    with pytest.raises(ContractError, match="days est strictement croissant"):
        _reference(days=(DAY1, DAY1), clocks=_clocks((DAY1, DAY1)))
    with pytest.raises(ContractError, match="multi_outing_days est strictement"):
        _reference(multi_outing_days=(date(2026, 6, 1), DAY2))


def test_repeatability_reference_days_and_multi_outing_days_disjoint() -> None:
    with pytest.raises(ContractError, match="days et multi_outing_days sont disjoints"):
        _reference(multi_outing_days=(DAY1,))


def test_repeatability_reference_clocks_in_order() -> None:
    clocks = _clocks((DAY1, DAY3))
    with pytest.raises(ContractError, match="les onze horloges dans l'ordre"):
        _reference(clocks=clocks[::-1])
    with pytest.raises(ContractError, match="les onze horloges dans l'ordre"):
        _reference(clocks=clocks[:10])


def test_repeatability_reference_folds_are_the_days_in_order() -> None:
    with pytest.raises(ContractError, match="les plis sous"):
        _reference(clocks=_clocks((DAY3, DAY1)))
    with pytest.raises(ContractError, match="les plis sous"):
        _reference(clocks=_clocks((DAY1,)))


def test_repeatability_reference_single_contrast_needs_two_days() -> None:
    """Précision de D8.4 : « un seul contraste », deux jours au moins."""
    one = {"days": (DAY1,), "clocks": _clocks((DAY1,))}
    with pytest.raises(ContractError, match="un seul contraste"):
        _reference(**one, single_contrast=True)
    assert not _reference(**one, single_contrast=False).single_contrast


def test_repeatability_reference_common_contraction() -> None:
    """Précision de D8.3 : ``μ₂`` ne dépend que du plan, le même sous les onze
    horloges."""
    clocks = list(_clocks((DAY1, DAY3)))
    fold = clocks[5].folds[1]
    fits = (replace(fold.fits[0], contraction=0.25), *fold.fits[1:])
    clocks[5] = replace(clocks[5], folds=(clocks[5].folds[0], replace(fold, fits=fits)))
    with pytest.raises(ContractError, match="est le même sous les onze horloges"):
        _reference(clocks=tuple(clocks))
