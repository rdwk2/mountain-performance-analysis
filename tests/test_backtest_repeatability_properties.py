"""Propriétés exactes de la référence de répétabilité, sur les seize cas (§ 7.4 et
§ 8.1, test 6, du brief M4b-3 ; ``0010`` D8.4).

- **Réemploi au bit** (choix 7) : ``support_metrics`` appliquée aux prévisions
  publiées, aux temps et aux classes **des jours d'entrée** sur ces indices, rend
  (``==``) ``L`` et les scores de classe publiés.
- **``F`` = moyenne des plis** : ``math.fsum`` des valeurs publiées qui comptent,
  divisée par leur nombre.
- **Ordre des entrées**, **substitution d'horloge** (dix horloges, l'écoulé gardé),
  **``μ₂`` commun** aux onze horloges.

Ces tests recalculent avec les mêmes fonctions que le code : c'est leur objet (§ 8,
« ce qui ne compte pas comme test ») — ils vérifient **quelles valeurs** vont à quelle
fonction ; les valeurs de l'oracle sont exigées par le test 4.
"""

import math
from dataclasses import replace

import pytest

from fixtures.repeatability import (
    CASE_NAMES,
    COMPLET,
    REFERENCE,
    build_day,
    case_days,
    case_max_iterations,
    case_reference,
    case_specs,
    days_of,
)
from mountain_perf.backtest import repeatability_reference, support_metrics
from mountain_perf.schemas import (
    CLOCKS,
    AdmittedSegment,
    RegimeClass,
    RepeatabilityDay,
)


def _cells(name: str) -> dict[str, dict[int, AdmittedSegment]]:
    """Les cellules de chaque jour éligible d'entrée, par date ISO."""
    return {
        str(day.performance.civil_date): {
            segment.index: segment
            for segment in day.segments
            if segment.start_m == segment.nominal_start_m
            and segment.end_m == segment.nominal_end_m
        }
        for day in case_days(name)
        if day.segments is not None
    }


@pytest.mark.parametrize("name", CASE_NAMES)
def test_published_scores_reuse_support_metrics_at_the_bit(name: str) -> None:
    """Choix 7, précision de D8.4 : ``L`` et, pour chaque classe sans motif,
    ``E_R`` et ``D_R`` sont ceux de ``support_metrics`` sur les prévisions publiées
    (``forecast_s``), les temps du jour retiré et leurs classes, au bit ; les clés de
    ``forecast_s`` sont des cellules du jour retiré."""
    reference = case_reference(name)
    cells = _cells(name)
    checked = 0
    for index, clock_reference in enumerate(reference.clocks):
        for fold in clock_reference.folds:
            if not fold.forecast_s:
                continue
            left = cells[str(fold.day)]
            keys = [k for k, _ in fold.forecast_s]
            assert set(keys) <= set(left)
            metrics = support_metrics(
                [p for _, p in fold.forecast_s],
                [left[k].times_s[index] for k in keys],
                [left[k].regime_class for k in keys],
            )
            if fold.level.available:
                assert fold.level.value == metrics.log_ratio.value
            for score, computed in zip(fold.classes, metrics.classes, strict=True):
                if score.log_ratio.available:
                    assert score.log_ratio.value == computed.log_ratio.value
                    assert score.dispersion.value == computed.dispersion.value
            checked += 1
    if reference.days and name not in ("Un jour", "Disjoints"):
        assert checked > 0


@pytest.mark.parametrize("name", CASE_NAMES)
def test_f_is_the_mean_of_the_published_folds(name: str) -> None:
    """Précision de D8.4 : ``F_q`` est la moyenne arithmétique, à poids égal par jour,
    des ``|L|``, des ``|E_R|`` et des ``D_R`` contributifs ; son effectif est leur
    nombre."""
    for clock_reference in case_reference(name).clocks:
        folds = clock_reference.folds
        levels = [abs(v) for fold in folds if (v := fold.level.value) is not None]
        _check_mean(clock_reference.level.value, clock_reference.level.count, levels)
        for i in range(len(RegimeClass)):
            scores = [fold.classes[i] for fold in folds if fold.classes[i].contributes]
            log_ratios = [
                abs(v) for s in scores if (v := s.log_ratio.value) is not None
            ]
            dispersions = [v for s in scores if (v := s.dispersion.value) is not None]
            assert len(log_ratios) == len(dispersions) == len(scores)
            log_ratio, dispersion = (
                clock_reference.log_ratios[i],
                clock_reference.dispersions[i],
            )
            _check_mean(log_ratio.value, log_ratio.count, log_ratios)
            _check_mean(dispersion.value, dispersion.count, dispersions)


def _check_mean(value: float | None, count: int, values: list[float]) -> None:
    assert count == len(values)
    if value is not None:
        assert value == math.fsum(values) / len(values)


@pytest.mark.parametrize("name", CASE_NAMES)
def test_input_order_does_not_matter(name: str) -> None:
    """§ 6.4, étape 1 : les jours sont triés par date ; l'ordre d'entrée, inversé ou
    décalé d'un rang, donne la même référence."""
    days = case_days(name)
    expected = case_reference(name)
    max_iterations = case_max_iterations(name)
    for order in (days[::-1], days[1:] + days[:1]):
        reference = repeatability_reference(
            REFERENCE, order, max_iterations=max_iterations
        )
        assert reference == expected


def _substituted(days: list[RepeatabilityDay], clock: int) -> list[RepeatabilityDay]:
    """Les dix temps hors écoulé de chaque segment remplacés par son temps sous
    ``CLOCKS[clock]``, l'écoulé gardé (un temps nul recopié dans l'écoulé ferait un
    ``AdmittedSegment`` invalide)."""
    substituted = []
    for day in days:
        if day.segments is None:
            substituted.append(day)
            continue
        segments = tuple(
            replace(
                segment,
                times_s=(segment.times_s[0], *(segment.times_s[clock],) * 10),
            )
            for segment in day.segments
        )
        substituted.append(replace(day, segments=segments))
    return substituted


@pytest.mark.parametrize("clock", [0, 1, 3, 8])
@pytest.mark.parametrize("name", CASE_NAMES)
def test_clock_substitution(name: str, clock: int) -> None:
    """``0010`` D8 : la référence se calcule sous chaque horloge avec les temps de
    cette horloge, et rien d'autre — sous chacune des dix horloges hors écoulé, les
    temps substitués donnent la ``ClockReference`` de ``CLOCKS[clock]`` sur les
    données d'origine (champ ``clock`` mis à part)."""
    expected = case_reference(name).clocks[clock]
    reference = repeatability_reference(
        REFERENCE,
        _substituted(case_days(name), clock),
        max_iterations=case_max_iterations(name),
    )
    for clock_reference in reference.clocks[1:]:
        assert replace(clock_reference, clock=expected.clock) == expected


@pytest.mark.parametrize("name", CASE_NAMES)
def test_contraction_is_common_to_the_eleven_clocks(name: str) -> None:
    """Précision de D8.3 : ``μ₂`` ne dépend que du plan ; il est le même sous les
    onze horloges, pour chaque pli et chaque classe, motif ``temps nul`` compris."""
    reference = case_reference(name)
    assert len(reference.clocks) == len(CLOCKS)
    for j in range(len(reference.days)):
        for i in range(len(RegimeClass)):
            values = [
                clock_reference.folds[j].fits[i].contraction
                for clock_reference in reference.clocks
            ]
            assert values == [values[0]] * len(CLOCKS)


# ---------------------------------------------------------------------------
# Correctifs de la relecture de la PR #18
# ---------------------------------------------------------------------------


def _distinct_times(elapsed: float) -> tuple[float, ...]:
    """Onze temps tous différents : l'écoulé, puis ``écoulé − 1`` à ``écoulé − 10``."""
    return (elapsed, *(elapsed - i for i in range(1, 11)))


def _swap_clock_times(
    days: list[RepeatabilityDay], i: int, j: int
) -> list[RepeatabilityDay]:
    swapped = []
    for day_ in days:
        assert day_.segments is not None
        segments = []
        for segment in day_.segments:
            times = list(segment.times_s)
            times[i], times[j] = times[j], times[i]
            segments.append(replace(segment, times_s=tuple(times)))
        swapped.append(replace(day_, segments=tuple(segments)))
    return swapped


@pytest.mark.parametrize(("i", "j"), [(1, 5), (2, 4), (6, 7), (6, 9), (3, 8)])
def test_each_clock_reads_its_own_times(i: int, j: int) -> None:
    """``0010`` D8, onze horloges : chacune lit ses propres temps. Dans les données du
    § 7.2, ``M θ1 = M θ5``, ``M θ2 = M θ4`` et ``(M+U) θ1, θ2, θ4, θ5`` valent
    l'écoulé ; ici, Complet avec onze temps distincts : échanger dans l'entrée les temps
    de deux horloges échange leurs ``ClockReference``."""
    specs = [
        replace(
            s, cells={k: (c, _distinct_times(t[0])) for k, (c, t) in s.cells.items()}
        )
        for s in COMPLET
    ]
    original = repeatability_reference(REFERENCE, days_of(specs))
    swapped = repeatability_reference(
        REFERENCE, _swap_clock_times(days_of(specs), i, j)
    )
    for a, b in ((i, j), (j, i)):
        assert swapped.clocks[a] == replace(original.clocks[b], clock=CLOCKS[a])


@pytest.mark.parametrize("name", CASE_NAMES)
def test_fold_forecasts_ignore_the_left_out_day(name: str) -> None:
    """D8.1, D8.4 : le gabarit d'un pli s'apprend sur les **autres** jours. Multiplier
    par 1,37 les temps du jour retiré ne change ni ses ajustements ni ses prévisions,
    sous les onze horloges, sur les seize cas."""
    specs = case_specs(name)
    limit = case_max_iterations(name)
    base = repeatability_reference(REFERENCE, case_days(name), max_iterations=limit)
    eligible = sorted(
        (n for n, spec in enumerate(specs) if not spec.multi),
        key=lambda n: specs[n].date,
    )
    for j, n in enumerate(eligible):
        cells = {
            k: (c, tuple(1.37 * t for t in times))
            for k, (c, times) in specs[n].cells.items()
        }
        scaled = replace(specs[n], cells=cells)
        days = [build_day(scaled if m == n else spec) for m, spec in enumerate(specs)]
        changed = repeatability_reference(REFERENCE, days, max_iterations=limit)
        for clock, expected in zip(changed.clocks, base.clocks, strict=True):
            assert clock.folds[j].fits == expected.folds[j].fits
            assert clock.folds[j].forecast_s == expected.folds[j].forecast_s
