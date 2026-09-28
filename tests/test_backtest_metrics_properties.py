"""Propriétés des métriques (§ 8.1, test 8, du brief M4b-1 ; ``0010`` D5.5, D7).

Stratégie :func:`strategies.support_cases` — supports de 0 à 40 segments dans le
domaine promis (§ 3, choix 12), ingrédients étiquetés —, et les fixtures du § 7.1 en
exemples fixés. Propriétés :

1. le contrat accepte tout résultat (identité et ``C_comp >= −τ·S`` comprises) ;
2. indépendance à l'ordre, au bit : permuter les segments (avec leurs classes) ne
   change aucun champ ;
3. invariances de D7.2, sans temps nul ni erreur : ``D_R`` sous une multiplication des
   ``p_i`` d'une classe, ``E_R − L`` sous une multiplication globale ;
4. une seule classe présente : ``W == A``, ``B == 0.0``, ``C_comp == 0.0`` ;
5. l'observation d'abord : d'autres sorties du modèle, valides ou invalides, ne
   changent ni effectif, ni « trop peu », ni motif ``insufficient_support`` ou
   ``zero_time`` ;
6. ``E_R`` entre le plus petit et le plus grand ``r_i`` de sa classe, ``L`` entre le
   plus petit et le plus grand ``E_R`` (à ``1e−12`` près) ;
7. sans temps nul, le diagnostic égale le support principal ;
8. ``usage_target`` aux poids par défaut, tous éléments disponibles
   (:func:`strategies.usage_cases`) : ``q_usage`` égale ``Σ |P − T| / Σ P^(0)`` à
   ``τ`` relatif près, ne dépend pas de l'ordre de ``K`` au bit, et
   ``q_usage | préfixe`` l'égale à ``τ`` relatif près ;
9. ``passage_errors`` (:func:`strategies.passage_error_cases`) :
   ``max_abs_error_s == max(|max_error_s|, |min_error_s|)`` ;
10. avec temps nul et sans sortie invalide, le diagnostic égale ``support_metrics``
    des segments de masque vrai.

Un test vérifie, par ``hypothesis.find``, que chaque étiquette produit le cas qu'elle
vise.
"""

import math
from collections.abc import Callable
from dataclasses import replace

import pytest
from hypothesis import Phase, example, find, given, settings
from hypothesis import strategies as st

from fixtures.metrics import SUPPORT_CASES, SupportCase, bits
from mountain_perf.backtest import (
    passage_errors,
    positive_time_diagnostic,
    support_metrics,
    usage_target,
)
from mountain_perf.schemas import (
    METRIC_RELATIVE_TOLERANCE,
    MetricValue,
    SupportMetrics,
    Unavailability,
)
from strategies import (
    PROMISED_MAX,
    PROMISED_MIN,
    SUPPORT_FEATURES,
    invalid_model_outputs,
    passage_error_cases,
    promised_outputs,
    support_cases,
    usage_cases,
)

TAU = METRIC_RELATIVE_TOLERANCE
OBSERVATION_MOTIFS = frozenset(
    {Unavailability.INSUFFICIENT_SUPPORT, Unavailability.ZERO_TIME}
)


def with_fixtures(test: Callable[..., None]) -> Callable[..., None]:
    """Les quatorze fixtures du § 7.1 en ``@example``, exercées à chaque exécution."""
    for case in SUPPORT_CASES.values():
        test = example(case)(test)
    return test


def metrics_of(case: SupportCase) -> SupportMetrics:
    return support_metrics(case.projected_s, case.observed_s, case.classes)


def outputs(case: SupportCase) -> list[float]:
    """Les sorties d'un cas sans erreur du modèle, typées ``float``."""
    values = [p for p in case.projected_s if p is not None]
    assert len(values) == len(case.projected_s)
    return values


@settings(deadline=None)
@given(support_cases())
@with_fixtures
def test_contracts_accept_every_result(case: SupportCase) -> None:
    """Propriété 1 : ``0010`` D7.2, choix 7 de rdw — le résultat se construit, identité
    et ``C_comp >= −τ·S`` comprises, et le diagnostic aussi."""
    metrics = metrics_of(case)
    assert metrics.segment_count == len(case.observed_s)
    diagnostic = positive_time_diagnostic(
        case.projected_s, case.observed_s, case.classes
    )
    assert len(diagnostic.mask) == len(case.observed_s)


@settings(deadline=None)
@given(st.data())
def test_result_does_not_depend_on_the_order_at_the_bit(data: st.DataObject) -> None:
    """Propriété 2 : choix 1 du brief (``math.fsum``, une seule écriture) —
    permuter les segments ne change aucun champ, au bit."""
    case = data.draw(support_cases())
    order = data.draw(st.permutations(range(len(case.observed_s))))
    permuted = SupportCase(
        tuple(case.projected_s[i] for i in order),
        tuple(case.observed_s[i] for i in order),
        tuple(case.classes[i] for i in order),
    )
    assert bits(metrics_of(permuted)) == bits(metrics_of(case))


def _scale(case: SupportCase, factor: float, members: set[int]) -> SupportCase | None:
    """``p_i · factor`` sur ``members`` ; ``None`` si le cas sort du domaine promis."""
    scaled = [p * factor if i in members else p for i, p in enumerate(outputs(case))]
    if not all(PROMISED_MIN <= p <= PROMISED_MAX for p in scaled):
        return None
    return replace(case, projected_s=tuple(scaled))


def _value(metric: MetricValue) -> float:
    assert metric.value is not None
    return metric.value


@settings(deadline=None)
@given(
    support_cases(min_size=1, zero_time=False, model_error=False),
    st.floats(-3.0, 3.0),
    st.data(),
)
def test_invariances_of_d7_2(
    case: SupportCase, log_factor: float, data: st.DataObject
) -> None:
    """Propriété 3 : ``0010`` D7.2 — ``D_R`` ne change pas si l'on multiplie les ``p_i``
    d'un régime par une constante ; ``E_R − L`` ne change pas sous une multiplication
    globale ; à ``τ·max(1, |E_R|, |E'_R|, D_R)`` et ``τ·max(1, |E_R|, |E'_R|, |L|,
    |L'|)`` près."""
    factor = math.exp(log_factor)
    metrics = metrics_of(case)
    regime = data.draw(st.sampled_from(sorted(set(case.classes))))
    members = {i for i, c in enumerate(case.classes) if c is regime}
    one_class = _scale(case, factor, members)
    if one_class is not None:
        before = next(c for c in metrics.classes if c.regime_class is regime)
        after = next(
            c for c in metrics_of(one_class).classes if c.regime_class is regime
        )
        e, e_prime = _value(before.log_ratio), _value(after.log_ratio)
        d, d_prime = _value(before.dispersion), _value(after.dispersion)
        assert abs(d_prime - d) <= TAU * max(1.0, abs(e), abs(e_prime), d)
    everything = _scale(case, factor, set(range(len(case.classes))))
    if everything is not None:
        scaled = metrics_of(everything)
        level, level_prime = _value(metrics.log_ratio), _value(scaled.log_ratio)
        for before, after in zip(metrics.classes, scaled.classes, strict=True):
            if before.segment_count == 0:
                continue
            e, e_prime = _value(before.log_ratio), _value(after.log_ratio)
            bound = TAU * max(1.0, abs(e), abs(e_prime), abs(level), abs(level_prime))
            assert abs(_value(after.shape) - _value(before.shape)) <= bound


@settings(deadline=None)
@given(support_cases(min_size=1, zero_time=False, model_error=False, single_class=True))
@example(SUPPORT_CASES["Une classe"])
@example(SUPPORT_CASES["T11 D"])
@example(SUPPORT_CASES["Un segment"])
def test_one_class_gives_an_exact_identity(case: SupportCase) -> None:
    """Propriété 4 : choix 1 du brief — une seule classe présente : ``W == A``,
    ``B == 0.0``, ``C_comp == 0.0``."""
    metrics = metrics_of(case)
    assert metrics.within.value == metrics.dispersion.value
    assert metrics.between.value == 0.0
    assert metrics.compensation.value == 0.0


def _observation(metrics: SupportMetrics) -> object:
    """Ce que seule l'observation fixe : effectifs, « trop peu », et les motifs
    ``insufficient_support`` et ``zero_time`` à leur place."""

    def motif(value: MetricValue) -> object:
        observed = value.unavailability in OBSERVATION_MOTIFS
        return (value.count, value.unavailability if observed else None)

    support = (
        metrics.log_ratio,
        metrics.dispersion,
        metrics.within,
        metrics.between,
        metrics.compensation,
    )
    return (
        metrics.segment_count,
        tuple(motif(value) for value in support),
        tuple(
            (
                c.segment_count,
                c.underrepresented,
                motif(c.log_ratio),
                motif(c.dispersion),
                motif(c.shape),
            )
            for c in metrics.classes
        ),
    )


OTHER_OUTPUTS = st.lists(
    st.one_of(promised_outputs(), invalid_model_outputs()), min_size=40, max_size=40
)
"""Quarante sorties de remplacement, valides ou invalides ; un cas prend les siennes."""

FIXED_OUTPUTS = (123.0, None, math.nan, 0.0, 1e11, -2.0, math.inf, 7.5) * 5
"""Les sorties de remplacement des exemples fixés."""


def observation_examples(test: Callable[..., None]) -> Callable[..., None]:
    for case in SUPPORT_CASES.values():
        test = example(case, FIXED_OUTPUTS)(test)
    return test


@settings(deadline=None)
@given(support_cases(), OTHER_OUTPUTS)
@observation_examples
def test_observation_comes_before_the_model(
    case: SupportCase, other: tuple[float | None, ...]
) -> None:
    """Propriété 5 : choix 5 de rdw — remplacer les ``p_i`` par d'autres valeurs du
    domaine promis, ou par l'une des cinq formes invalides, ne change ni effectif, ni
    ``underrepresented``, ni motif ``insufficient_support`` ou ``zero_time``."""
    changed = replace(case, projected_s=tuple(other[: len(case.projected_s)]))
    assert _observation(metrics_of(changed)) == _observation(metrics_of(case))


@settings(deadline=None)
@given(support_cases(min_size=1, zero_time=False, model_error=False))
@example(SUPPORT_CASES["T12"])
@example(SUPPORT_CASES["Dyadique"])
@example(SUPPORT_CASES["Quatre classes"])
def test_levels_lie_between_their_ratios(case: SupportCase) -> None:
    """Propriété 6 : ``0010`` D7.2 — ``E_R`` entre le plus petit et le plus grand
    ``r_i`` de sa classe, ``L`` entre le plus petit et le plus grand ``E_R``, à
    ``1e−12`` près."""
    metrics = metrics_of(case)
    p = outputs(case)
    levels = []
    for regime in metrics.classes:
        members = [i for i, c in enumerate(case.classes) if c is regime.regime_class]
        if not members:
            continue
        ratios = [math.log(p[i] / case.observed_s[i]) for i in members]
        level = _value(regime.log_ratio)
        assert min(ratios) - 1e-12 <= level <= max(ratios) + 1e-12
        levels.append(level)
    assert min(levels) - 1e-12 <= _value(metrics.log_ratio) <= max(levels) + 1e-12


@settings(deadline=None)
@given(support_cases(zero_time=False))
@example(SUPPORT_CASES["Quatre classes"])
@example(SUPPORT_CASES["T22"])
@example(SUPPORT_CASES["Vide"])
def test_diagnostic_without_zero_time_is_the_support(case: SupportCase) -> None:
    """Propriété 7 : ``0010`` D5.5, choix 5 du brief — sans temps nul, le diagnostic
    égale le support principal (``==``), masque tout vrai."""
    diagnostic = positive_time_diagnostic(
        case.projected_s, case.observed_s, case.classes
    )
    assert diagnostic.mask == (True,) * len(case.observed_s)
    assert diagnostic.metrics == metrics_of(case)


def _close(a: float, b: float) -> bool:
    """``a`` et ``b`` égaux à ``τ`` relatif près."""
    return abs(a - b) <= TAU * max(abs(a), abs(b))


@settings(deadline=None)
@given(usage_cases(), st.data())
@example(((140.0, 250.0), (100.0, 300.0), (120.0, 280.0)), None)
@example(((40.0, 210.0), (50.0, 200.0), (0.0, 200.0)), None)
def test_default_usage_target(
    case: tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]],
    data: st.DataObject | None,
) -> None:
    """Propriété 8 : ``0010`` D7.4 — aux poids par défaut, ``q_usage =
    Σ |P_k − T_k| / Σ P_k^(0)`` (à ``τ`` relatif près, B2 de la passe 1) ; il ne
    dépend pas de l'ordre de ``K``, au bit ; ``q_usage | préfixe`` l'égale à ``τ``
    relatif près quand tous les éléments sont disponibles."""
    projected, base, observed = case
    n = len(observed)
    target = usage_target(projected, base, observed, (None,) * n)
    usage = _value(target.q_usage)
    short = math.fsum(abs(p - t) for p, t in zip(projected, observed, strict=True))
    assert _close(usage, short / math.fsum(base))
    assert _close(_value(target.q_usage_prefix), usage)
    order = (
        list(reversed(range(n)))
        if data is None
        else data.draw(st.permutations(range(n)))
    )
    permuted = usage_target(
        [projected[k] for k in order],
        [base[k] for k in order],
        [observed[k] for k in order],
        (None,) * n,
    )
    assert _value(permuted.q_usage).hex() == usage.hex()


@settings(deadline=None)
@given(passage_error_cases())
@example(((100.0, 200.0, 300.0, 400.0), (120.0, 240.0, 360.0, 480.0), (None,) * 4))
@example(
    (
        (90.0, 250.0, 290.0, 400.0),
        (120.0, 240.0, None, 380.0),
        (None, None, Unavailability.AMBIGUOUS, None),
    )
)
def test_max_abs_error_is_the_larger_extreme(
    case: tuple[
        tuple[float | None, ...],
        tuple[float | None, ...],
        tuple[Unavailability | None, ...],
    ],
) -> None:
    """Propriété 9 : ``0010`` D7.3 — ``max |C_k| == max(|max C_k|, |min C_k|)``, au
    bit, quand les agrégats sont présents ; le contrat accepte tout résultat."""
    errors = passage_errors(*case)
    if errors.max_abs_error_s.available:
        high, low = _value(errors.max_error_s), _value(errors.min_error_s)
        assert _value(errors.max_abs_error_s) == max(abs(high), abs(low))


_SEARCH = settings(
    max_examples=2000, database=None, deadline=None, phases=[Phase.generate]
)
"""Seule l'existence compte : pas de réduction de l'exemple trouvé."""


@pytest.mark.parametrize("feature", sorted(SUPPORT_FEATURES))
def test_support_strategy_reaches(feature: str) -> None:
    """§ 8.1, test 8 : la stratégie sait produire chacun des cas qu'elle étiquette
    (classe absente, temps nul, erreur du modèle, les deux, rapport constant, une seule
    classe, un segment)."""
    find(support_cases(), lambda case: feature in case.features, settings=_SEARCH)


@settings(deadline=None)
@given(support_cases(zero_time=True, model_error=False))
@example(SUPPORT_CASES["Temps nul"])
@example(SUPPORT_CASES["Tout nul"])
@example(SupportCase((50.0, 100.0), (0.0, 100.0), SUPPORT_CASES["Temps nul"].classes))
def test_diagnostic_is_the_support_of_the_kept_segments(case: SupportCase) -> None:
    """Propriété 10 (correctif de la relecture) : ``0010`` D5.5, § 6.5 du brief — sans
    sortie invalide, le diagnostic égale (``==``) ``support_metrics`` appliqué aux
    seuls segments de masque vrai (projections, temps et classes)."""
    diagnostic = positive_time_diagnostic(
        case.projected_s, case.observed_s, case.classes
    )
    kept = [i for i, time_s in enumerate(case.observed_s) if time_s > 0]
    assert diagnostic.mask == tuple(time_s > 0 for time_s in case.observed_s)
    assert diagnostic.metrics == support_metrics(
        [case.projected_s[i] for i in kept],
        [case.observed_s[i] for i in kept],
        [case.classes[i] for i in kept],
    )
