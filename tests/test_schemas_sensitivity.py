"""Contrats de la sensibilité (``0010`` D13 ; précision de M4d-3 ; D14, format 5) :
``schemas/sensitivity.py``.

Pour chaque contrat : des objets valides construits à la main, puis chaque refus de la
rubrique « Invariants », par ``ContractError`` et son message exact. Énumérations,
descriptions, ``METRIC_COMPONENTS``, ``DOCUMENT_RESERVES`` ; ``sign_class`` aux bornes
exactes ``±ε`` (classe zéro) et juste au-delà (``math.nextafter``) ; ``common_set``
(entrantes, sortantes, moyennes ``math.fsum``) ; ``guards_lost`` (passages compris,
sans décision au comparateur) ; les cinq invariants de ``SensitivityOutcome``.
Propriétés (Hypothesis) : ``sign_class`` symétrique et monotone, ``common_set``
invariant par permutation des gains d'un jour à l'autre. Aucune donnée réelle : des
jours de juillet 2026 inventés (``fixtures.sensitivity``).
"""

import math
import re
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fixtures.sensitivity import (
    DAYS,
    EPSILON,
    ERR,
    GainSpec,
    admission,
    assessments,
    expected_class,
    gain_comparison,
    metric_comparison,
    performance_comparison,
)
from mountain_perf.backtest import SENSITIVITY_CONFIGURATIONS
from mountain_perf.schemas import (
    AVAILABILITY_DESCRIPTIONS,
    CLOCKS,
    DOCUMENT_RESERVES,
    METRIC_COMPONENTS,
    NUMERIC_TOLERANCE,
    PERFORMANCE_MOTIF_DESCRIPTIONS,
    SENSITIVITY_METRIC_DESCRIPTIONS,
    SENSITIVITY_RESERVE_DESCRIPTIONS,
    SUPPORT_COMPONENT_DESCRIPTIONS,
    Admission,
    AdmissionVerdict,
    Availability,
    CommonSet,
    ConfigurationOutcome,
    ContractError,
    ExperimentMetric,
    GainComparison,
    GuardStatus,
    MetricComparison,
    MetricValue,
    ModelKind,
    NonEvaluable,
    PerformanceMotif,
    ReserveEntry,
    SensitivityMetric,
    SensitivityOutcome,
    SensitivityReserve,
    SupportComponent,
    Unavailability,
)
from mountain_perf.schemas._dictionary import ENUM_DESCRIPTIONS
from mountain_perf.schemas.sensitivity import common_set, guards_lost, sign_class

C = SupportComponent
SM = SensitivityMetric
R = SensitivityReserve
G = GuardStatus
NE = NonEvaluable
EM = ExperimentMetric
D1, D2, D3 = DAYS[:3]
V0 = ModelKind.V0_RAW
VALUE = MetricValue(0.25, None, 4)
OTHER = MetricValue(0.5, None, 4)
ABSENT = MetricValue(None, Unavailability.INSUFFICIENT_SUPPORT, 0)
"""Une valeur indisponible, ``support insuffisant``."""
NEXT_UP = math.nextafter(EPSILON, math.inf)
"""Le premier flottant au-delà de ``ε``."""
NEXT_DOWN = math.nextafter(EPSILON, 0.0)
"""Le dernier flottant sous ``ε``."""
CONFIGS = SENSITIVITY_CONFIGURATIONS


def _raises(instance: Any, fragment: str, **changes: Any) -> None:
    with pytest.raises(ContractError, match=re.escape(fragment)):
        replace(instance, **changes)


# ---------------------------------------------------------------------------
# Énumérations, descriptions, composantes, réserves de document
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("enum", "values"),
    [
        (Availability, ["both_available", "lost", "gained", "both_unavailable"]),
        (
            SupportComponent,
            ["segments", "zero_times", "points", "targets", "population"],
        ),
        (
            SensitivityMetric,
            [
                "level",
                "ascent_level",
                "flat_level",
                "descent_level",
                "ascent_dispersion",
                "flat_dispersion",
                "descent_dispersion",
                "max_abs_passage_error_s",
                "q_usage",
            ],
        ),
        (PerformanceMotif, ["not_scored", "no_reference", "multi_outing_day"]),
        (
            SensitivityReserve,
            [
                "sensitivity_sign_changed",
                "sensitivity_verdict_changed",
                "sensitivity_evaluability_lost",
                "sensitivity_sign_unverifiable",
            ],
        ),
    ],
)
def test_enum_members_are_closed_and_in_order(enum: Any, values: list[str]) -> None:
    """Contrats de M4d-3 : énumérations fermées, membres et valeurs stockées, dans
    l'ordre de la publication (métriques : ``L``, ``E_R`` montée, plat, descente, puis
    ``D_R`` de même, ``max |C_k|``, ``q_usage`` — précision de D13)."""
    assert [member.value for member in enum] == values


@pytest.mark.parametrize(
    ("enum", "descriptions"),
    [
        (Availability, AVAILABILITY_DESCRIPTIONS),
        (SupportComponent, SUPPORT_COMPONENT_DESCRIPTIONS),
        (SensitivityMetric, SENSITIVITY_METRIC_DESCRIPTIONS),
        (PerformanceMotif, PERFORMANCE_MOTIF_DESCRIPTIONS),
        (SensitivityReserve, SENSITIVITY_RESERVE_DESCRIPTIONS),
    ],
)
def test_enum_descriptions_cover_every_member(enum: Any, descriptions: Any) -> None:
    """Contrats de M4d-3 : une description non vide par membre, dans l'ordre, publiée
    au dictionnaire."""
    assert list(descriptions) == list(enum)
    assert all(text.strip() for text in descriptions.values())
    assert ENUM_DESCRIPTIONS[enum] is descriptions


def test_metric_components_follow_the_rule() -> None:
    """Précision de D13, axe 2 : ``L``, ``E_R``, ``D_R`` — segments, temps nuls ;
    ``max |C_k|`` — points ; ``q_usage`` — éléments de ``K`` ; la population en
    dernier (modèle calé)."""
    regime = (C.SEGMENTS, C.ZERO_TIMES, C.POPULATION)
    assert list(METRIC_COMPONENTS) == list(SensitivityMetric)
    for metric in list(SM)[:7]:
        assert METRIC_COMPONENTS[metric] == regime
    assert METRIC_COMPONENTS[SM.MAX_ABS_PASSAGE_ERROR] == (C.POINTS, C.POPULATION)
    assert METRIC_COMPONENTS[SM.USAGE] == (C.TARGETS, C.POPULATION)


def test_metric_components_are_ordered_subsequences() -> None:
    """``METRIC_COMPONENTS`` : chaque tuple suit l'ordre de ``SupportComponent``,
    sans doublon, la population en dernier."""
    order = list(SupportComponent)
    for components in METRIC_COMPONENTS.values():
        assert isinstance(components, tuple)
        ranks = [order.index(c) for c in components]
        assert ranks == sorted(set(ranks))
        assert components[-1] is C.POPULATION


def test_document_reserves_are_the_four_of_d13_in_order() -> None:
    """Précision de D13, « Réserves » : quatre réserves de document, dans cet ordre,
    et aucune autre — « sensibilité incomplète » est un état de la vue composée
    (D10.6), jamais une réserve stockée."""
    assert DOCUMENT_RESERVES == (
        R.SIGN_CHANGED,
        R.VERDICT_CHANGED,
        R.EVALUABILITY_LOST,
        R.SIGN_UNVERIFIABLE,
    )
    assert tuple(R) == DOCUMENT_RESERVES


# ---------------------------------------------------------------------------
# sign_class (« Signes et ensembles »)
# ---------------------------------------------------------------------------


def test_epsilon_is_that_of_d10_3() -> None:
    """Précision de D13 : ``ε = 10⁻⁶`` (D10.3)."""
    assert NUMERIC_TOLERANCE == EPSILON == 1e-6


@pytest.mark.parametrize(
    ("gain", "klass"),
    [
        (EPSILON, 0),
        (-EPSILON, 0),
        (NEXT_UP, 1),
        (-NEXT_UP, -1),
        (NEXT_DOWN, 0),
        (-NEXT_DOWN, 0),
        (0.0, 0),
        (-0.0, 0),
        (2e-6, 1),
        (-2e-6, -1),
        (0.5, 1),
        (-0.5, -1),
        (1e300, 1),
        (-1e300, -1),
    ],
)
def test_sign_class_at_the_exact_bounds(gain: float, klass: int) -> None:
    """Précision de D13 : ``+1`` si ``g > ε``, ``−1`` si ``g < −ε``, ``0`` sinon ;
    les bornes ``±ε`` sont dans la classe zéro, le flottant suivant non."""
    result = sign_class(gain)
    assert type(result) is int
    assert result == klass


@settings(max_examples=60, deadline=None)
@given(st.floats(allow_nan=False, allow_infinity=False))
def test_sign_class_is_odd(gain: float) -> None:
    """Précision de D13 : la classe est symétrique, ``class(−g) = −class(g)``."""
    assert sign_class(-gain) == -sign_class(gain)
    assert sign_class(gain) == expected_class(gain)


@settings(max_examples=60, deadline=None)
@given(
    st.floats(allow_nan=False, allow_infinity=False),
    st.floats(allow_nan=False, allow_infinity=False),
)
def test_sign_class_is_monotone(first: float, second: float) -> None:
    """Précision de D13 : la classe croît avec le gain."""
    low, high = sorted((first, second))
    assert sign_class(low) <= sign_class(high)


# ---------------------------------------------------------------------------
# MetricComparison
# ---------------------------------------------------------------------------


BOTH = metric_comparison(V0, SM.LEVEL, VALUE, OTHER, (C.SEGMENTS,))
"""Disponible des deux côtés, écart ``0,5 − 0,25``, segments changés."""


@pytest.mark.parametrize(
    ("comparator", "value", "availability", "difference"),
    [
        (VALUE, OTHER, Availability.BOTH, 0.25),
        (VALUE, ABSENT, Availability.LOST, None),
        (ABSENT, OTHER, Availability.GAINED, None),
        (ABSENT, ABSENT, Availability.NEITHER, None),
    ],
    ids=["both", "lost", "gained", "neither"],
)
def test_metric_comparison_accepted_in_each_availability(
    comparator: MetricValue,
    value: MetricValue,
    availability: Availability,
    difference: float | None,
) -> None:
    """Précision de D13, axes 1 et 3 : la disponibilité se lit sur les deux présences ;
    l'écart ``valeur − comparateur`` existe quand les deux valeurs existent."""
    comparison = MetricComparison(
        V0, SM.LEVEL, comparator, value, availability, (), difference
    )
    assert comparison.availability is availability
    assert comparison.difference == difference


@pytest.mark.parametrize(
    ("model", "metric", "support"),
    [
        (V0, SM.LEVEL, (C.SEGMENTS, C.ZERO_TIMES)),
        (V0, SM.FLAT_DISPERSION, (C.ZERO_TIMES,)),
        (V0, SM.MAX_ABS_PASSAGE_ERROR, (C.POINTS,)),
        (V0, SM.USAGE, (C.TARGETS,)),
        (ModelKind.V0_RECALIBRATED, SM.LEVEL, (C.SEGMENTS, C.ZERO_TIMES, C.POPULATION)),
        (ModelKind.CANDIDATE, SM.USAGE, (C.TARGETS, C.POPULATION)),
        (ModelKind.TOBLER, SM.MAX_ABS_PASSAGE_ERROR, (C.POPULATION,)),
    ],
)
def test_metric_comparison_support_accepted(
    model: ModelKind, metric: SensitivityMetric, support: tuple[SupportComponent, ...]
) -> None:
    """Contrat : ``support`` est une sous-suite ordonnée de ``METRIC_COMPONENTS`` ; la
    population pour un modèle calé (le candidat compris)."""
    assert metric_comparison(model, metric, VALUE, OTHER, support).support == support


def test_metric_comparison_difference_is_value_minus_comparator() -> None:
    """Précision de D13, axe 3 : ``valeur − comparateur``, au bit, dans ce sens."""
    comparison = metric_comparison(V0, SM.USAGE, MetricValue(0.3, None, 2), VALUE)
    assert comparison.difference == 0.25 - 0.3
    assert comparison.difference is not None
    assert comparison.difference < 0


METRIC_VIOLATIONS: list[tuple[str, dict[str, Any]]] = [
    (
        "availability vaut both_available, reçu lost (D13).",
        {"availability": Availability.LOST},
    ),
    (
        "availability vaut lost, reçu both_available (D13).",
        {"value": ABSENT, "difference": None},
    ),
    (
        "availability vaut gained, reçu both_available (D13).",
        {"comparator": ABSENT, "difference": None},
    ),
    (
        "availability vaut both_unavailable, reçu both_available (D13).",
        {"comparator": ABSENT, "value": ABSENT, "difference": None},
    ),
    (
        "support doit être une séquence immuable : passer un tuple, reçu list.",
        {"support": [C.SEGMENTS]},
    ),
    (
        "points n'est pas une composante du support de level (['segments', "
        "'zero_times', 'population']).",
        {"support": (C.POINTS,)},
    ),
    (
        "targets n'est pas une composante du support de level (['segments', "
        "'zero_times', 'population']).",
        {"support": (C.SEGMENTS, C.TARGETS)},
    ),
    (
        "segments n'est pas une composante du support de max_abs_passage_error_s "
        "(['points', 'population']).",
        {"metric": SM.MAX_ABS_PASSAGE_ERROR},
    ),
    (
        "points n'est pas une composante du support de q_usage (['targets', "
        "'population']).",
        {"metric": SM.USAGE, "support": (C.POINTS,)},
    ),
    (
        "support suit l'ordre de METRIC_COMPONENTS, sans doublon.",
        {"support": (C.ZERO_TIMES, C.SEGMENTS)},
    ),
    (
        "support suit l'ordre de METRIC_COMPONENTS, sans doublon.",
        {"support": (C.SEGMENTS, C.SEGMENTS)},
    ),
    (
        "v0_raw n'est pas calé : sa population ne change pas (D9.2).",
        {"support": (C.SEGMENTS, C.POPULATION)},
    ),
    (
        "difference est présent si et seulement si les deux valeurs le sont.",
        {"difference": None},
    ),
    (
        "difference est présent si et seulement si les deux valeurs le sont.",
        {"value": ABSENT, "availability": Availability.LOST},
    ),
    ("difference doit être fini, reçu nan.", {"difference": math.nan}),
    (
        "difference doit être fini, reçu inf.",
        {
            "comparator": MetricValue(-1e308, None, 1),
            "value": MetricValue(1e308, None, 1),
            "difference": math.inf,
        },
    ),
    (
        "difference vaut value − comparator, au bit, reçu "
        f"{math.nextafter(0.25, 1.0)!r}.",
        {"difference": math.nextafter(0.25, 1.0)},
    ),
    ("difference vaut value − comparator, au bit, reçu -0.25.", {"difference": -0.25}),
]


@pytest.mark.parametrize(("fragment", "changes"), METRIC_VIOLATIONS)
def test_metric_comparison_invariants(fragment: str, changes: dict[str, Any]) -> None:
    """Contrat ``MetricComparison`` : disponibilité des présences ; ``support`` tuple,
    sous-suite ordonnée sans doublon, population d'un modèle calé seulement ; écart
    présent si et seulement si les deux valeurs le sont, fini, au bit."""
    _raises(BOTH, fragment, **changes)


# ---------------------------------------------------------------------------
# PerformanceComparison
# ---------------------------------------------------------------------------


TWO_MODELS = performance_comparison(D1, VALUE, OTHER, (V0, ModelKind.NAISMITH))
WITH_MOTIF = performance_comparison(
    D2, VALUE, VALUE, motif=PerformanceMotif.MULTI_OUTING
)


def test_performance_comparison_accepted() -> None:
    """Précision de D13 : une performance porte son motif sans valeur comparée, ou
    chaque modèle avec ses neuf métriques dans l'ordre ; ``models`` dans l'ordre."""
    assert TWO_MODELS.models == (V0, ModelKind.NAISMITH)
    assert [c.metric for c in TWO_MODELS.metrics] == list(SM) * 2
    assert WITH_MOTIF.metrics == ()
    assert WITH_MOTIF.models == ()


def _swapped(metrics: tuple[MetricComparison, ...]) -> tuple[MetricComparison, ...]:
    return (metrics[1], metrics[0], *metrics[2:])


ONE_MODEL = performance_comparison(D1, VALUE, OTHER)
PERFORMANCE_VIOLATIONS: list[tuple[str, dict[str, Any]]] = [
    ("outing_id ne doit pas être vide.", {"outing_id": ""}),
    ("outing_id ne doit pas être vide.", {"outing_id": "  "}),
    (
        "metrics doit être une séquence immuable : passer un tuple, reçu list.",
        {"metrics": list(ONE_MODEL.metrics)},
    ),
    (
        "motif est présent si et seulement si metrics est vide, reçu "
        "motif=not_scored et 9 comparaisons.",
        {"motif": PerformanceMotif.NOT_SCORED},
    ),
    (
        "motif est présent si et seulement si metrics est vide, reçu motif=None et 0 "
        "comparaisons.",
        {"metrics": ()},
    ),
    (
        "metrics porte 9 métriques par modèle, reçu 8 comparaisons.",
        {"metrics": ONE_MODEL.metrics[:8]},
    ),
    (
        "metrics : le groupe 0 mêle plusieurs modèles.",
        {
            "metrics": (
                *ONE_MODEL.metrics[:8],
                replace(ONE_MODEL.metrics[8], model=ModelKind.TOBLER),
            )
        },
    ),
    (
        "metrics : les métriques de v0_raw suivent l'ordre de SensitivityMetric, "
        "toutes.",
        {"metrics": _swapped(ONE_MODEL.metrics)},
    ),
    (
        "metrics : les métriques de v0_raw suivent l'ordre de SensitivityMetric, "
        "toutes.",
        {"metrics": (ONE_MODEL.metrics[0],) * 9},
    ),
    (
        "metrics : v0_raw porté deux fois.",
        {"metrics": ONE_MODEL.metrics * 2},
    ),
]


@pytest.mark.parametrize(("fragment", "changes"), PERFORMANCE_VIOLATIONS)
def test_performance_comparison_invariants(
    fragment: str, changes: dict[str, Any]
) -> None:
    """Contrat ``PerformanceComparison`` : sortie non vide ; ``metrics`` tuple ; motif
    si et seulement si aucune comparaison ; groupes d'un modèle, les neuf métriques
    dans l'ordre ; des modèles distincts."""
    _raises(ONE_MODEL, fragment, **changes)


# ---------------------------------------------------------------------------
# GainComparison
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("comparator", "value", "comparable", "changed"),
    [
        (0.5, 0.4, True, False),
        (0.5, -0.4, True, True),
        (0.5, EPSILON, True, True),
        (EPSILON, -EPSILON, True, False),
        (EPSILON, NEXT_UP, True, True),
        (0.0, -NEXT_UP, True, True),
        (0.5, ERR, False, False),
        (ERR, -0.5, False, False),
        (NE.UNSCORED, 0.5, False, False),
        (0.5, NE.PASSAGE_UNAVAILABLE, False, False),
        (ERR, ERR, False, False),
        (NE.EXCLUDED, NE.MULTI_OUTING, False, False),
    ],
)
def test_gain_comparison_accepted(
    comparator: GainSpec, value: GainSpec, comparable: bool, changed: bool
) -> None:
    """Précision de D13 : comparable si et seulement si les deux gains existent ; une
    valeur absente n'est jamais un zéro ; un passage de zéro à non nul est un
    changement de classe."""
    gain = gain_comparison(D1, comparator, value)
    assert gain.comparable is comparable
    assert gain.class_changed is changed


GAIN = gain_comparison(D1, 0.5, 0.4)
GAIN_VIOLATIONS: list[tuple[str, dict[str, Any]]] = [
    (
        "comparator_gain absent : sa classe de signe l'est aussi.",
        {"comparator_gain": None},
    ),
    ("gain absent : sa classe de signe l'est aussi.", {"gain": None}),
    (
        "la classe de gain vaut 1, reçu -1.",
        {
            "comparator_gain": None,
            "comparator_motif": NE.UNSCORED,
            "comparator_class": None,
            "gain_class": -1,
        },
    ),
    (
        "comparator_gain doit être fini, reçu nan.",
        {"comparator_gain": math.nan},
    ),
    ("gain doit être fini, reçu inf.", {"gain": math.inf}),
    (
        "comparator_gain présent : la performance est évaluable de ce côté, reçu le "
        "motif unscored.",
        {"comparator_motif": NE.UNSCORED},
    ),
    (
        "gain présent : la performance est évaluable de ce côté, reçu le motif "
        "excluded.",
        {"motif": NE.EXCLUDED},
    ),
    ("la classe de comparator_gain vaut 1, reçu 0.", {"comparator_class": 0}),
    ("la classe de comparator_gain vaut 1, reçu None.", {"comparator_class": None}),
    ("la classe de gain vaut 0, reçu 1.", {"gain": EPSILON}),
    ("la classe de gain vaut -1, reçu 1.", {"gain": -NEXT_UP}),
]


@pytest.mark.parametrize(("fragment", "changes"), GAIN_VIOLATIONS)
def test_gain_comparison_invariants(fragment: str, changes: dict[str, Any]) -> None:
    """Contrat ``GainComparison`` : un gain présent est fini, sans motif de ce côté ;
    chaque classe présente si et seulement si son gain l'est, et vaut sa classe de
    signe (bornes ``±ε`` comprises)."""
    _raises(GAIN, fragment, **changes)


def test_gain_absent_with_its_motif_accepted() -> None:
    """Précision de D13 : chaque côté publie ce qu'il a — son motif, ou, évaluable, son
    gain absent."""
    gain = GainComparison(D1, None, NE.UNSCORED, None, None, None, None)
    assert not gain.comparable
    assert gain.comparator_motif is NE.UNSCORED
    assert gain.motif is None


# ---------------------------------------------------------------------------
# CommonSet et common_set
# ---------------------------------------------------------------------------


COMMON = CommonSet((D1, D3), (D2,), (DAYS[4],), 0.35, 0.1)


def test_common_set_accepted() -> None:
    """Contrat ``CommonSet`` : des jours croissants, les moyennes avec des jours."""
    assert COMMON.days == (D1, D3)
    empty = CommonSet((), (D1,), (), None, None)
    assert empty.mean is None


COMMON_VIOLATIONS: list[tuple[str, dict[str, Any]]] = [
    *[
        (
            f"{name} doit être une séquence immuable : passer un tuple, reçu list.",
            {name: [D1]},
        )
        for name in ("days", "entering", "leaving")
    ],
    ("days : jours strictement croissants.", {"days": (D3, D1)}),
    ("days : jours strictement croissants.", {"days": (D1, D1)}),
    ("entering : jours strictement croissants.", {"entering": (D2, D2)}),
    ("leaving : jours strictement croissants.", {"leaving": (D3, D2)}),
    (
        "comparator_mean est présent si et seulement si days n'est pas vide.",
        {"comparator_mean": None},
    ),
    ("mean est présent si et seulement si days n'est pas vide.", {"mean": None}),
    (
        "comparator_mean est présent si et seulement si days n'est pas vide.",
        {"days": ()},
    ),
    ("comparator_mean doit être fini, reçu nan.", {"comparator_mean": math.nan}),
    ("mean doit être fini, reçu -inf.", {"mean": -math.inf}),
]


@pytest.mark.parametrize(("fragment", "changes"), COMMON_VIOLATIONS)
def test_common_set_contract_invariants(fragment: str, changes: dict[str, Any]) -> None:
    """Contrat ``CommonSet`` : trois tuples de jours strictement croissants ; les
    moyennes présentes si et seulement si ``days`` n'est pas vide, finies."""
    _raises(COMMON, fragment, **changes)


def test_common_set_days_entering_leaving_and_means() -> None:
    """Précision de D13 : l'ensemble commun — les jours où les deux ``G_j`` existent,
    les deux moyennes sur ces seuls jours, les entrantes (évaluables sous la
    configuration, pas au comparateur), les sortantes (l'inverse)."""
    gains = (
        gain_comparison(DAYS[0], 0.5, 0.4),
        gain_comparison(DAYS[1], NE.UNSCORED, 0.9),
        gain_comparison(DAYS[2], 0.3, NE.PASSAGE_UNAVAILABLE),
        gain_comparison(DAYS[3], ERR, 0.7),
        gain_comparison(DAYS[4], NE.NO_USAGE, ERR),
        gain_comparison(DAYS[5], ERR, NE.EXCLUDED),
        gain_comparison(DAYS[6], -0.2, 0.1),
        gain_comparison(DAYS[7], NE.EXCLUDED, NE.EXCLUDED),
    )
    common = common_set(gains)
    assert common == CommonSet(
        (DAYS[0], DAYS[6]),
        (DAYS[1], DAYS[4]),
        (DAYS[2], DAYS[5]),
        math.fsum((0.5, -0.2)) / 2,
        math.fsum((0.4, 0.1)) / 2,
    )


def test_common_set_means_use_fsum() -> None:
    """Précision de D13 : moyennes ``fsum`` à poids égal — ``1e8, 1e−8, −1e8`` donne
    ``1e−8 / 3``, pas la somme naïve de gauche à droite."""
    gains = tuple(
        gain_comparison(day, value, value)
        for day, value in zip(DAYS, (1e8, 1e-8, -1e8), strict=False)
    )
    naive = 0.0
    for value in (1e8, 1e-8, -1e8):
        naive += value
    common = common_set(gains)
    assert common.comparator_mean == 1e-8 / 3
    assert common.mean == 1e-8 / 3
    assert common.mean != naive / 3


def test_common_set_without_common_day() -> None:
    """Précision de D13 : sans gain comparable, ni jour commun ni moyenne."""
    gains = (gain_comparison(D1, ERR, 0.5), gain_comparison(D2, 0.1, ERR))
    assert common_set(gains) == CommonSet((), (), (), None, None)
    assert common_set(()) == CommonSet((), (), (), None, None)


_SPECS = st.one_of(
    st.floats(min_value=-1.0, max_value=1.0, allow_nan=False),
    st.sampled_from([EPSILON, -EPSILON, NEXT_UP, 0.0, ERR]),
    st.sampled_from([NE.UNSCORED, NE.EXCLUDED, NE.PASSAGE_UNAVAILABLE]),
)


@settings(max_examples=40, deadline=None)
@given(st.lists(st.tuples(_SPECS, _SPECS), min_size=1, max_size=8), st.randoms())
def test_common_set_is_invariant_by_permutation(
    pairs: list[tuple[GainSpec, GainSpec]], random: Any
) -> None:
    """Précision de D13 : les moyennes ``fsum`` ne dépendent pas de l'ordre — les
    mêmes couples de gains, permutés d'un jour à l'autre, donnent les mêmes moyennes
    au bit et les mêmes effectifs ; jours, entrantes et sortantes sont disjoints."""
    shuffled = list(pairs)
    random.shuffle(shuffled)
    first = common_set(
        tuple(gain_comparison(DAYS[k], *pair) for k, pair in enumerate(pairs))
    )
    second = common_set(
        tuple(gain_comparison(DAYS[k], *pair) for k, pair in enumerate(shuffled))
    )
    assert (first.comparator_mean, first.mean) == (second.comparator_mean, second.mean)
    assert len(first.days) == len(second.days)
    assert len(first.entering) == len(second.entering)
    assert len(first.leaving) == len(second.leaving)
    days, entering, leaving = map(set, (first.days, first.entering, first.leaving))
    assert not days & entering
    assert not days & leaving
    assert not entering & leaving


# ---------------------------------------------------------------------------
# ReserveEntry
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("reserve", DOCUMENT_RESERVES)
def test_reserve_entry_accepted(reserve: SensitivityReserve) -> None:
    """Contrat ``ReserveEntry`` : une réserve de document, des rangs croissants."""
    assert ReserveEntry(reserve, (0, 3, 18)).configurations == (0, 3, 18)


ENTRY = ReserveEntry(R.SIGN_CHANGED, (1, 4))
ENTRY_VIOLATIONS: list[tuple[str, dict[str, Any]]] = [
    (
        "configurations doit être une séquence immuable : passer un tuple, reçu list.",
        {"configurations": [1, 4]},
    ),
    ("configurations ne doit pas être vide.", {"configurations": ()}),
    ("configurations : des rangs >= 0.", {"configurations": (-1, 4)}),
    ("configurations : rangs strictement croissants.", {"configurations": (4, 4)}),
    ("configurations : rangs strictement croissants.", {"configurations": (4, 1)}),
]


@pytest.mark.parametrize(("fragment", "changes"), ENTRY_VIOLATIONS)
def test_reserve_entry_invariants(fragment: str, changes: dict[str, Any]) -> None:
    """Contrat ``ReserveEntry`` : un tuple non vide de rangs ``>= 0`` strictement
    croissants."""
    _raises(ENTRY, fragment, **changes)


# ---------------------------------------------------------------------------
# guards_lost (réserve 3, D13-C)
# ---------------------------------------------------------------------------


PASSING = [0.5, 0.5]


@pytest.mark.parametrize(
    ("comparator", "configuration", "lost"),
    [
        ({EM.LEVEL: G.SATISFIED}, {EM.LEVEL: G.SATISFIED}, False),
        ({EM.LEVEL: G.SATISFIED}, {EM.LEVEL: G.VIOLATED}, False),
        ({EM.LEVEL: G.VIOLATED}, {EM.LEVEL: G.SATISFIED}, False),
        ({EM.LEVEL: G.SATISFIED}, {EM.LEVEL: G.UNAVAILABLE}, True),
        ({EM.LEVEL: G.VIOLATED}, {EM.LEVEL: G.UNAVAILABLE}, True),
        ({EM.FLAT_LEVEL: G.SATISFIED}, {}, True),
        ({EM.DESCENT_DISPERSION: G.VIOLATED}, {}, True),
        ({EM.LEVEL: G.UNAVAILABLE}, {EM.LEVEL: G.SATISFIED}, False),
        ({EM.LEVEL: G.UNAVAILABLE}, {EM.LEVEL: G.UNAVAILABLE}, False),
        ({}, {EM.ASCENT_LEVEL: G.SATISFIED}, False),
    ],
    ids=[
        "satisfied-kept",
        "satisfied-to-violated",
        "violated-to-satisfied",
        "satisfied-to-unavailable",
        "violated-to-unavailable",
        "satisfied-to-not-applicable",
        "violated-to-not-applicable",
        "unavailable-to-satisfied",
        "unavailable-kept",
        "not-applicable-to-computed",
    ],
)
def test_guards_lost_on_metric_guards(
    comparator: dict[ExperimentMetric, GuardStatus],
    configuration: dict[ExperimentMetric, GuardStatus],
    lost: bool,
) -> None:
    """Précision de D13, réserve 3 : un garde-fou calculé au comparateur (satisfait ou
    violé) qui ne l'est plus (indisponible, non applicable) ; jamais l'inverse."""
    assert (
        guards_lost(
            admission(PASSING, guards=comparator),
            admission(PASSING, guards=configuration),
        )
        is lost
    )


@pytest.mark.parametrize(
    ("comparator", "configuration", "lost"),
    [
        (G.SATISFIED, G.SATISFIED, False),
        (G.SATISFIED, G.VIOLATED, False),
        (G.VIOLATED, G.SATISFIED, False),
        (G.SATISFIED, G.UNAVAILABLE, True),
        (G.VIOLATED, G.NOT_EVALUABLE, True),
        (G.UNAVAILABLE, G.NOT_EVALUABLE, False),
        (G.NOT_EVALUABLE, G.SATISFIED, False),
    ],
)
def test_guards_lost_counts_the_passages(
    comparator: GuardStatus, configuration: GuardStatus, lost: bool
) -> None:
    """Précision de D13, réserve 3 : le garde-fou des passages compris."""
    assert (
        guards_lost(
            admission(PASSING, passages=comparator),
            admission(PASSING, passages=configuration),
        )
        is lost
    )


def test_guards_lost_without_decision() -> None:
    """Précision de D13, réserve 3 : sans décision sous la configuration, tout
    garde-fou calculé au comparateur est perdu ; sans décision au comparateur,
    jamais."""
    computed = admission(PASSING)
    assert guards_lost(computed, None) is True
    assert guards_lost(None, computed) is False
    assert guards_lost(None, None) is False
    nothing = admission(
        PASSING, guards={EM.LEVEL: G.UNAVAILABLE}, passages=G.NOT_EVALUABLE
    )
    assert guards_lost(nothing, None) is False


# ---------------------------------------------------------------------------
# ConfigurationOutcome
# ---------------------------------------------------------------------------


PERFORMANCES = (
    performance_comparison(D1, VALUE, VALUE),
    performance_comparison(D2, VALUE, VALUE),
    performance_comparison(D3, VALUE, VALUE, motif=PerformanceMotif.NOT_SCORED),
)
"""Trois performances : deux comparées (v0 brut, la valeur du comparateur sous chaque
configuration), une non scorée."""
BASELINE = (0.5, 0.2, NE.UNSCORED)
"""Le comparateur des expériences construites : ``Ḡ = 0,35``, provisoire."""


def _gains(
    specs: Sequence[GainSpec], comparator: Sequence[GainSpec] = BASELINE
) -> tuple[GainComparison, ...]:
    return tuple(
        gain_comparison(day, theirs, mine)
        for day, theirs, mine in zip(DAYS, comparator, specs, strict=False)
    )


def _experiment(
    rank: int,
    specs: Sequence[GainSpec],
    *,
    comparator: Sequence[GainSpec] = BASELINE,
    flags: tuple[bool, bool, bool] = (False, False, False),
    comparator_mean_class: int | None = 1,
    **options: Any,
) -> ConfigurationOutcome:
    """La configuration ``rank`` d'une expérience : sa décision sur ``specs``, les
    gains comparés à ``comparator``, l'ensemble commun, les classes de ``Ḡ`` et ses
    réserves (``flags`` : signe, verdict, évaluabilité ; la quatrième déduite)."""
    clock = CONFIGS[rank].clock
    evaluable = any(not isinstance(s, NonEvaluable) for s in specs)
    made = admission(specs, clock=clock, **options) if evaluable else None
    gains = _gains(specs, comparator)
    mean = None if made is None else made.mean_gain
    return ConfigurationOutcome(
        CONFIGS[rank],
        PERFORMANCES,
        made,
        None if evaluable else assessments(specs),
        gains,
        common_set(gains),
        expected_class(mean),
        comparator_mean_class,
        *flags,
        not any(g.comparable for g in gains),
    )


COMPARATOR = _experiment(4, BASELINE)
"""Le comparateur ``(250, 30, écoulé)``, comparé à lui-même."""
SIGN_AND_VERDICT = _experiment(3, (0.5, -0.3, NE.UNSCORED), flags=(True, True, False))
"""``G_2`` passe de ``+1`` à ``−1`` ; vote et perte : rejetée."""
LEAVING = _experiment(5, (0.5, NE.PASSAGE_UNAVAILABLE, 0.4), flags=(False, False, True))
"""Le 2 juillet sort, le 3 entre ; ``Ḡ = 0,45`` reste ``+1``, provisoire."""
WITHOUT_EXPERIMENT = ConfigurationOutcome(
    CONFIGS[4],
    PERFORMANCES,
    None,
    None,
    (),
    None,
    None,
    None,
    False,
    False,
    False,
    False,
)


def test_configuration_outcome_accepted() -> None:
    """Contrat ``ConfigurationOutcome`` : sans expérience, ses seules performances ;
    avec, l'admission refaite, les gains, l'ensemble commun, ses classes et réserves ;
    propriétés ``experiment``, ``assessed``, ``verdict``."""
    assert not WITHOUT_EXPERIMENT.experiment
    assert WITHOUT_EXPERIMENT.assessed == ()
    assert WITHOUT_EXPERIMENT.verdict is None
    assert COMPARATOR.experiment
    assert COMPARATOR.verdict is AdmissionVerdict.PROVISIONAL
    assert SIGN_AND_VERDICT.verdict is AdmissionVerdict.REJECTED
    assert SIGN_AND_VERDICT.common == CommonSet((D1, D2), (), (), 0.35, 0.1)
    assert LEAVING.common == CommonSet((D1,), (D3,), (D2,), 0.5, 0.5)
    assert isinstance(COMPARATOR.admission, Admission)
    assert COMPARATOR.assessed == COMPARATOR.admission.performances


def test_configuration_outcome_without_decision_accepted() -> None:
    """Précision de D13 : sans performance évaluable, la configuration n'a que ses
    évaluations, sans décision ni ``Ḡ``."""
    outcome = _experiment(
        3, (NE.UNSCORED, NE.EXCLUDED, NE.UNSCORED), flags=(False, True, True)
    )
    assert outcome.admission is None
    assert outcome.verdict is None
    assert outcome.mean_class is None
    assert [a.motif for a in outcome.assessed] == [
        NE.UNSCORED,
        NE.EXCLUDED,
        NE.UNSCORED,
    ]
    assert outcome.sign_unverifiable


WITHOUT_FIELDS = (
    "sans expérience (gains vide), ni admission, ni évaluations, ni ensemble commun, "
    "ni classe, ni réserve ; reçu "
)
CONFIGURATION_VIOLATIONS: list[tuple[str, ConfigurationOutcome, dict[str, Any]]] = [
    # 1. formes
    (
        "performances doit être une séquence immuable : passer un tuple, reçu list.",
        WITHOUT_EXPERIMENT,
        {"performances": list(PERFORMANCES)},
    ),
    (
        "gains doit être une séquence immuable : passer un tuple, reçu list.",
        WITHOUT_EXPERIMENT,
        {"gains": []},
    ),
    ("performances ne doit pas être vide.", WITHOUT_EXPERIMENT, {"performances": ()}),
    (
        "performances : jours civils strictement croissants.",
        WITHOUT_EXPERIMENT,
        {"performances": (PERFORMANCES[1], PERFORMANCES[0])},
    ),
    (
        "performances : jours civils strictement croissants.",
        WITHOUT_EXPERIMENT,
        {"performances": (PERFORMANCES[0], PERFORMANCES[0])},
    ),
    # 2. sans expérience
    (
        WITHOUT_FIELDS + "['admission'].",
        WITHOUT_EXPERIMENT,
        {"admission": COMPARATOR.admission},
    ),
    (
        WITHOUT_FIELDS + "['assessments'].",
        WITHOUT_EXPERIMENT,
        {"assessments": assessments((NE.UNSCORED,) * 3)},
    ),
    (
        WITHOUT_FIELDS + "['common'].",
        WITHOUT_EXPERIMENT,
        {"common": CommonSet((), (), (), None, None)},
    ),
    (WITHOUT_FIELDS + "['mean_class'].", WITHOUT_EXPERIMENT, {"mean_class": 0}),
    (
        WITHOUT_FIELDS + "['comparator_mean_class'].",
        WITHOUT_EXPERIMENT,
        {"comparator_mean_class": 1},
    ),
    *[
        (WITHOUT_FIELDS + f"['{flag}'].", WITHOUT_EXPERIMENT, {flag: True})
        for flag in (
            "sign_changed",
            "verdict_changed",
            "evaluability_lost",
            "sign_unverifiable",
        )
    ],
    # 3. avec expérience
    (
        "une expérience porte exactement une de admission et assessments.",
        COMPARATOR,
        {"admission": None},
    ),
    (
        "une expérience porte exactement une de admission et assessments.",
        COMPARATOR,
        {"assessments": assessments((NE.UNSCORED,) * 3)},
    ),
    (
        f"l'admission est sous {CLOCKS[0]}, l'horloge de la configuration "
        f"({CLOCKS[1]}) attendue.",
        COMPARATOR,
        {"configuration": CONFIGS[9]},
    ),
    (
        "gains porte les jours des performances, dans l'ordre.",
        COMPARATOR,
        {"gains": COMPARATOR.gains[:2]},
    ),
    (
        "gains porte les jours des performances, dans l'ordre.",
        COMPARATOR,
        {"gains": (COMPARATOR.gains[1], COMPARATOR.gains[0], COMPARATOR.gains[2])},
    ),
    (
        "le gain du 2026-07-02 n'est pas celui de son évaluation sous la "
        "configuration.",
        COMPARATOR,
        {"gains": _gains((0.5, 0.3, NE.UNSCORED))},
    ),
    (
        "le gain du 2026-07-03 n'est pas celui de son évaluation sous la "
        "configuration.",
        COMPARATOR,
        {"gains": _gains((0.5, 0.2, NE.EXCLUDED))},
    ),
    (
        "mean_class vaut 1 (classe de Ḡ), reçu 0.",
        COMPARATOR,
        {"mean_class": 0},
    ),
    (
        "mean_class vaut 1 (classe de Ḡ), reçu None.",
        COMPARATOR,
        {"mean_class": None},
    ),
    (
        "common n'est pas l'ensemble commun des gains.",
        COMPARATOR,
        {"common": CommonSet((D1, D2), (), (), 0.35, 0.36)},
    ),
    (
        "common n'est pas l'ensemble commun des gains.",
        COMPARATOR,
        {"common": None},
    ),
    (
        "sign_unverifiable vaut False (aucun gain comparable).",
        COMPARATOR,
        {"sign_unverifiable": True},
    ),
]


@pytest.mark.parametrize(("fragment", "valid", "changes"), CONFIGURATION_VIOLATIONS)
def test_configuration_outcome_invariants(
    fragment: str, valid: ConfigurationOutcome, changes: dict[str, Any]
) -> None:
    """Contrat ``ConfigurationOutcome``, invariants 1 à 3 : formes ; sans expérience,
    rien que les performances ; avec, une admission (sous l'horloge de la
    configuration) ou des évaluations, les gains de ses évaluations aux jours des
    performances, la classe de ``Ḡ``, l'ensemble commun, « aucun gain comparable »."""
    _raises(valid, fragment, **changes)


def test_configuration_outcome_needs_an_assessment_of_each_gain_day() -> None:
    """Contrat ``ConfigurationOutcome``, invariant 3 : chaque jour des gains a son
    évaluation sous la configuration."""
    made = admission((0.5, 0.2), clock=CLOCKS[0])
    performances = (PERFORMANCES[0], replace(PERFORMANCES[2], civil_date=D3))
    gains = (gain_comparison(D1, 0.5, 0.5), gain_comparison(D3, 0.2, 0.2))
    with pytest.raises(
        ContractError,
        match=re.escape("aucune évaluation du 2026-07-03 sous la configuration."),
    ):
        ConfigurationOutcome(
            CONFIGS[4],
            performances,
            made,
            None,
            gains,
            common_set(gains),
            1,
            1,
            False,
            False,
            False,
            False,
        )


def test_configuration_outcome_assessments_must_be_a_tuple() -> None:
    """Contrat ``ConfigurationOutcome``, invariant 3 : ``assessments`` est un tuple."""
    specs = (NE.UNSCORED, NE.EXCLUDED, NE.UNSCORED)
    valid = _experiment(3, specs, flags=(False, True, True))
    _raises(
        valid,
        "assessments doit être une séquence immuable : passer un tuple, reçu list.",
        assessments=list(assessments(specs)),
    )


def test_configuration_mean_class_absent_without_decision() -> None:
    """Contrat ``ConfigurationOutcome`` : sans admission, pas de classe de ``Ḡ``."""
    valid = _experiment(
        3, (NE.UNSCORED, NE.EXCLUDED, NE.UNSCORED), flags=(False, True, True)
    )
    with pytest.raises(
        ContractError, match=re.escape("mean_class vaut None (classe de Ḡ), reçu 1.")
    ):
        replace(valid, mean_class=1)


# ---------------------------------------------------------------------------
# SensitivityOutcome (cinq invariants)
# ---------------------------------------------------------------------------


def _plain(rank: int, value: MetricValue) -> ConfigurationOutcome:
    """La configuration ``rank`` sans expérience : comparateur ``VALUE``, valeur
    ``value`` sur les deux performances comparées."""
    return replace(
        WITHOUT_EXPERIMENT,
        configuration=CONFIGS[rank],
        performances=(
            performance_comparison(D1, VALUE, value),
            performance_comparison(D2, VALUE, value),
            PERFORMANCES[2],
        ),
    )


PLAIN = SensitivityOutcome(
    1, (_plain(3, OTHER), _plain(4, VALUE), _plain(5, ABSENT)), ()
)
"""``just backtest`` : trois configurations, le comparateur au rang 1."""
EXPERIMENT = SensitivityOutcome(
    1,
    (SIGN_AND_VERDICT, COMPARATOR, LEAVING),
    (
        ReserveEntry(R.SIGN_CHANGED, (0,)),
        ReserveEntry(R.VERDICT_CHANGED, (0,)),
        ReserveEntry(R.EVALUABILITY_LOST, (2,)),
    ),
)
"""Une expérience : signe et verdict au rang 0, évaluabilité au rang 2."""


def test_sensitivity_outcome_accepted() -> None:
    """Contrat ``SensitivityOutcome`` : sans expérience, aucune réserve ; avec, une
    entrée par réserve portée, dans l'ordre, avec ses rangs."""
    assert not PLAIN.experiment
    assert EXPERIMENT.experiment
    assert [e.reserve for e in EXPERIMENT.reserves] == [
        R.SIGN_CHANGED,
        R.VERDICT_CHANGED,
        R.EVALUABILITY_LOST,
    ]


def test_sensitivity_outcome_comparator_alone() -> None:
    """Contrat ``SensitivityOutcome`` : un document d'une seule configuration, le
    comparateur."""
    assert SensitivityOutcome(0, (_plain(4, VALUE),), ()).comparator == 0


def _changed_comparator_side(outcome: ConfigurationOutcome) -> ConfigurationOutcome:
    first = outcome.performances[0]
    metrics = (
        metric_comparison(V0, SM.LEVEL, OTHER, OTHER),
        *first.metrics[1:],
    )
    return replace(
        outcome,
        performances=(replace(first, metrics=metrics), *outcome.performances[1:]),
    )


def _comparator_with_support() -> ConfigurationOutcome:
    base = _plain(4, VALUE)
    first = base.performances[0]
    metrics = (
        metric_comparison(V0, SM.LEVEL, VALUE, VALUE, (C.SEGMENTS,)),
        *first.metrics[1:],
    )
    return replace(
        base, performances=(replace(first, metrics=metrics), *base.performances[1:])
    )


PLAIN_CONFIGS = PLAIN.configurations
OUTCOME_VIOLATIONS: list[tuple[str, SensitivityOutcome, dict[str, Any]]] = [
    # 1. formes
    (
        "configurations doit être une séquence immuable : passer un tuple, reçu list.",
        PLAIN,
        {"configurations": list(PLAIN_CONFIGS)},
    ),
    (
        "reserves doit être une séquence immuable : passer un tuple, reçu list.",
        PLAIN,
        {"reserves": []},
    ),
    ("configurations ne doit pas être vide.", PLAIN, {"configurations": ()}),
    ("comparator (3) est un rang de configurations.", PLAIN, {"comparator": 3}),
    ("comparator (-1) est un rang de configurations.", PLAIN, {"comparator": -1}),
    (
        "les configurations sont distinctes.",
        PLAIN,
        {"configurations": (PLAIN_CONFIGS[0], PLAIN_CONFIGS[1], PLAIN_CONFIGS[0])},
    ),
    (
        "toutes les configurations portent une expérience, ou aucune.",
        EXPERIMENT,
        {"configurations": (_plain(3, OTHER), COMPARATOR, LEAVING)},
    ),
    # 2. mêmes performances et modèles
    (
        "configuration 0 : mêmes performances (jours, sorties, motifs) et mêmes "
        "modèles que le comparateur.",
        PLAIN,
        {
            "configurations": (
                replace(
                    PLAIN_CONFIGS[0], performances=PLAIN_CONFIGS[0].performances[:2]
                ),
                *PLAIN_CONFIGS[1:],
            )
        },
    ),
    (
        "configuration 2 : mêmes performances (jours, sorties, motifs) et mêmes "
        "modèles que le comparateur.",
        PLAIN,
        {
            "configurations": (
                *PLAIN_CONFIGS[:2],
                replace(
                    PLAIN_CONFIGS[2],
                    performances=(
                        *PLAIN_CONFIGS[2].performances[:2],
                        replace(PERFORMANCES[2], motif=PerformanceMotif.NO_REFERENCE),
                    ),
                ),
            )
        },
    ),
    (
        "configuration 0 : mêmes performances (jours, sorties, motifs) et mêmes "
        "modèles que le comparateur.",
        PLAIN,
        {
            "configurations": (
                replace(
                    PLAIN_CONFIGS[0],
                    performances=(
                        replace(PLAIN_CONFIGS[0].performances[0], outing_id="autre"),
                        *PLAIN_CONFIGS[0].performances[1:],
                    ),
                ),
                *PLAIN_CONFIGS[1:],
            )
        },
    ),
    (
        "configuration 0 : mêmes performances (jours, sorties, motifs) et mêmes "
        "modèles que le comparateur.",
        PLAIN,
        {
            "configurations": (
                replace(
                    PLAIN_CONFIGS[0],
                    performances=(
                        performance_comparison(
                            D1, VALUE, OTHER, (ModelKind.CONSTANT_SPEED,)
                        ),
                        *PLAIN_CONFIGS[0].performances[1:],
                    ),
                ),
                *PLAIN_CONFIGS[1:],
            )
        },
    ),
    # 3. côté comparateur
    (
        "configuration 0, 2026-07-01, v0_raw, level : le côté comparateur n'est pas la "
        "valeur du comparateur.",
        PLAIN,
        {
            "configurations": (
                _changed_comparator_side(PLAIN_CONFIGS[0]),
                *PLAIN_CONFIGS[1:],
            )
        },
    ),
    (
        "le comparateur, comparé à lui-même, n'a aucune composante de support changée.",
        PLAIN,
        {
            "configurations": (
                PLAIN_CONFIGS[0],
                _comparator_with_support(),
                PLAIN_CONFIGS[2],
            )
        },
    ),
    # 4. côté comparateur des gains, réserves de chaque configuration
    (
        "configuration 0, 2026-07-02 : le gain du comparateur n'est pas le sien.",
        EXPERIMENT,
        {
            "configurations": (
                replace(
                    SIGN_AND_VERDICT,
                    gains=_gains((0.5, -0.3, NE.UNSCORED), (0.5, 0.25, NE.UNSCORED)),
                    common=common_set(
                        _gains((0.5, -0.3, NE.UNSCORED), (0.5, 0.25, NE.UNSCORED))
                    ),
                ),
                COMPARATOR,
                LEAVING,
            )
        },
    ),
    (
        "configuration 2, 2026-07-03 : le gain du comparateur n'est pas le sien.",
        EXPERIMENT,
        {
            "configurations": (
                SIGN_AND_VERDICT,
                COMPARATOR,
                replace(
                    LEAVING,
                    gains=_gains(
                        (0.5, NE.PASSAGE_UNAVAILABLE, 0.4), (0.5, 0.2, NE.EXCLUDED)
                    ),
                    common=common_set(
                        _gains(
                            (0.5, NE.PASSAGE_UNAVAILABLE, 0.4), (0.5, 0.2, NE.EXCLUDED)
                        )
                    ),
                ),
            )
        },
    ),
    (
        "configuration 0 : comparator_mean_class n'est pas la classe de Ḡ du "
        "comparateur.",
        EXPERIMENT,
        {
            "configurations": (
                replace(SIGN_AND_VERDICT, comparator_mean_class=0),
                COMPARATOR,
                LEAVING,
            )
        },
    ),
    (
        "configuration 1 : comparator_mean_class n'est pas la classe de Ḡ du "
        "comparateur.",
        EXPERIMENT,
        {
            "configurations": (
                SIGN_AND_VERDICT,
                replace(COMPARATOR, comparator_mean_class=None),
                LEAVING,
            )
        },
    ),
    (
        "configuration 0 : sign_changed vaut True.",
        EXPERIMENT,
        {
            "configurations": (
                replace(SIGN_AND_VERDICT, sign_changed=False),
                COMPARATOR,
                LEAVING,
            )
        },
    ),
    (
        "configuration 0 : verdict_changed vaut True.",
        EXPERIMENT,
        {
            "configurations": (
                replace(SIGN_AND_VERDICT, verdict_changed=False),
                COMPARATOR,
                LEAVING,
            )
        },
    ),
    (
        "configuration 2 : evaluability_lost vaut True.",
        EXPERIMENT,
        {
            "configurations": (
                SIGN_AND_VERDICT,
                COMPARATOR,
                replace(LEAVING, evaluability_lost=False),
            )
        },
    ),
    (
        "configuration 1 : sign_changed vaut False.",
        EXPERIMENT,
        {
            "configurations": (
                SIGN_AND_VERDICT,
                replace(COMPARATOR, sign_changed=True),
                LEAVING,
            )
        },
    ),
    (
        "configuration 2 : verdict_changed vaut False.",
        EXPERIMENT,
        {
            "configurations": (
                SIGN_AND_VERDICT,
                COMPARATOR,
                replace(LEAVING, verdict_changed=True),
            )
        },
    ),
    # 5. réserves
    *[
        (
            "reserves : une entrée par réserve portée, dans l'ordre de "
            "DOCUMENT_RESERVES, avec les rangs de toutes les configurations qui la "
            "portent.",
            EXPERIMENT,
            {"reserves": reserves},
        )
        for reserves in (
            (),
            EXPERIMENT.reserves[:2],
            (EXPERIMENT.reserves[1], EXPERIMENT.reserves[0], EXPERIMENT.reserves[2]),
            (*EXPERIMENT.reserves[:2], ReserveEntry(R.EVALUABILITY_LOST, (1, 2))),
            (*EXPERIMENT.reserves, ReserveEntry(R.SIGN_UNVERIFIABLE, (0,))),
        )
    ],
    (
        "reserves : une entrée par réserve portée, dans l'ordre de "
        "DOCUMENT_RESERVES, avec les rangs de toutes les configurations qui la "
        "portent.",
        PLAIN,
        {"reserves": (ReserveEntry(R.SIGN_CHANGED, (0,)),)},
    ),
]


@pytest.mark.parametrize(("fragment", "valid", "changes"), OUTCOME_VIOLATIONS)
def test_sensitivity_outcome_invariants(
    fragment: str, valid: SensitivityOutcome, changes: dict[str, Any]
) -> None:
    """Contrat ``SensitivityOutcome``, invariants 1 à 5 : configurations distinctes,
    toutes avec ou sans expérience, rang du comparateur ; mêmes performances et
    modèles ; côté comparateur, et le comparateur sans composante changée ; côté
    comparateur des gains et de ``Ḡ``, réserves de chaque configuration ; réserves du
    document, dans l'ordre, sans entrée vide."""
    _raises(valid, fragment, **changes)


def test_sensitivity_outcome_reserves_with_several_ranks() -> None:
    """Précision de D13, « Réserves » : une réserve porte les rangs de toutes les
    configurations qui la portent, dans l'ordre ; « signe non vérifiable » compris."""
    unverifiable = _experiment(
        0, (ERR, NE.EXCLUDED, NE.UNSCORED), flags=(False, True, True)
    )
    document = SensitivityOutcome(
        2,
        (unverifiable, SIGN_AND_VERDICT, COMPARATOR),
        (
            ReserveEntry(R.SIGN_CHANGED, (1,)),
            ReserveEntry(R.VERDICT_CHANGED, (0, 1)),
            ReserveEntry(R.EVALUABILITY_LOST, (0,)),
            ReserveEntry(R.SIGN_UNVERIFIABLE, (0,)),
        ),
    )
    assert [e.configurations for e in document.reserves] == [(1,), (0, 1), (0,), (0,)]


def test_sensitivity_outcome_sign_changed_by_the_mean_alone() -> None:
    """Contrat ``SensitivityOutcome``, invariant 4 : « signe changé » par la seule
    classe de ``Ḡ`` — une performance entrante rend ``Ḡ`` négatif, aucun ``G_j``
    comparable ne change de classe ; le contrat l'exige, et refuse son absence."""
    mean_only = _experiment(
        3,
        (0.5, 0.2, -5.0),
        comparator=(0.5, 0.2, NE.PASSAGE_UNAVAILABLE),
        flags=(True, True, False),
    )
    base = (0.5, 0.2, NE.PASSAGE_UNAVAILABLE)
    comparator = _experiment(4, base, comparator=base)
    assert not any(g.class_changed for g in mean_only.gains)
    assert (mean_only.mean_class, mean_only.comparator_mean_class) == (-1, 1)
    reserves = (
        ReserveEntry(R.SIGN_CHANGED, (0,)),
        ReserveEntry(R.VERDICT_CHANGED, (0,)),
    )
    SensitivityOutcome(1, (mean_only, comparator), reserves)
    with pytest.raises(
        ContractError, match=re.escape("configuration 0 : sign_changed")
    ):
        SensitivityOutcome(
            1,
            (replace(mean_only, sign_changed=False), comparator),
            reserves[1:],
        )


def test_sensitivity_outcome_evaluability_lost_by_a_guard_alone() -> None:
    """Contrat ``SensitivityOutcome``, invariant 4 : « évaluabilité perdue » par le seul
    garde-fou des passages, calculé au comparateur et indisponible sous la
    configuration ; aucune performance ne sort."""
    guard_only = _experiment(
        5, BASELINE, passages=GuardStatus.UNAVAILABLE, flags=(False, True, True)
    )
    assert guard_only.common is not None
    assert guard_only.common.leaving == ()
    reserves = (
        ReserveEntry(R.VERDICT_CHANGED, (1,)),
        ReserveEntry(R.EVALUABILITY_LOST, (1,)),
    )
    SensitivityOutcome(0, (COMPARATOR, guard_only), reserves)
    with pytest.raises(
        ContractError, match=re.escape("configuration 1 : evaluability_lost")
    ):
        SensitivityOutcome(
            0,
            (COMPARATOR, replace(guard_only, evaluability_lost=False)),
            reserves[:1],
        )
