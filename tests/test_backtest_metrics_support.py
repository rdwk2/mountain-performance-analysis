"""Métriques du support et diagnostic du sous-support (§ 6.4, § 6.5, § 7.1, § 7.2 et
§ 8.1, tests 4 et 5, du brief M4b-1).

``0010`` D7.1 (erreur du modèle), D7.2 (formules, cas limites), D5.5 (temps nuls,
diagnostic), D6 (classes), D7.5 (« trop peu représenté »). Chaque champ de chaque
résultat est comparé au § 7 : valeurs à ``1e−9`` en absolu, égalités ``==`` au bit,
motifs, effectifs et booléens exacts, les **quatre** classes toujours.
"""

import math
from dataclasses import dataclass
from typing import Any

import pytest

from fixtures.metrics import SUPPORT_CASES, raises_value_error
from mountain_perf.backtest import positive_time_diagnostic, support_metrics
from mountain_perf.schemas import (
    MetricValue,
    RegimeClass,
    SupportMetrics,
    Unavailability,
)

A, F, D, X = (
    RegimeClass.ASCENT,
    RegimeClass.FLAT,
    RegimeClass.DESCENT,
    RegimeClass.MIXED,
)
INSUF = Unavailability.INSUFFICIENT_SUPPORT
ZERO = Unavailability.ZERO_TIME
ERR = Unavailability.MODEL_ERROR
LN2 = math.log(2.0)


@dataclass(frozen=True)
class Approx:
    """Valeur attendue à ``1e−9`` en absolu."""

    value: float
    count: int


@dataclass(frozen=True)
class Exact:
    """Valeur attendue exacte (``==`` du brief)."""

    value: float
    count: int


@dataclass(frozen=True)
class Missing:
    """Indisponibilité attendue, avec son effectif."""

    motif: Unavailability
    count: int


Expected = Approx | Exact | Missing

SAME_AS_A = "== A"
"""``W == A`` exactement (une seule classe présente)."""


def check(actual: MetricValue, expected: Expected) -> None:
    assert actual.count == expected.count
    if isinstance(expected, Missing):
        assert actual.value is None
        assert actual.unavailability is expected.motif
        return
    assert actual.unavailability is None
    assert actual.value is not None
    if isinstance(expected, Exact):
        assert actual.value == expected.value
    else:
        assert actual.value == pytest.approx(expected.value, abs=1e-9)


def all_(motif: Unavailability, count: int) -> tuple[Missing, ...]:
    return (Missing(motif, count),) * 5


SUPPORT: dict[str, tuple[int, bool, tuple[Expected | str, ...]]] = {
    "T12": (
        3,
        False,
        (
            Approx(0.154150679827, 3),
            Approx(0.513481680316, 3),
            Approx(0.462098120373, 3),
            Approx(0.097378807600, 3),
            Approx(0.045995247658, 3),
        ),
    ),
    "Dyadique": (
        5,
        False,
        (
            Exact(0.0, 5),
            Approx(0.942680165562, 5),
            Approx(0.582243631670, 5),
            Approx(0.914954278339, 5),
            Approx(0.554517744448, 5),
        ),
    ),
    "Quatre classes": (
        10,
        False,
        (
            Approx(-0.033522692039, 10),
            Approx(0.189728921038, 10),
            Approx(0.106508597199, 10),
            Approx(0.162884453537, 10),
            Approx(0.079664129698, 10),
        ),
    ),
    "Une classe": (
        2,
        False,
        (
            Approx(0.019868071840, 2),
            Approx(0.200000000000, 2),
            SAME_AS_A,
            Exact(0.0, 2),
            Exact(0.0, 2),
        ),
    ),
    "T11 D": (
        2,
        False,
        (
            Approx(-0.405465108108, 2),
            Approx(0.326943084337, 2),
            SAME_AS_A,
            Exact(0.0, 2),
            Exact(0.0, 2),
        ),
    ),
    "Un segment": (
        1,
        False,
        (
            Approx(-0.105360515658, 1),
            Exact(0.0, 1),
            Exact(0.0, 1),
            Exact(0.0, 1),
            Exact(0.0, 1),
        ),
    ),
    "Temps nul": (2, False, (Approx(0.693147180560, 2), *all_(ZERO, 2)[1:])),
    "Tout nul": (2, False, all_(ZERO, 2)),
    "Tout nul, erreur": (2, True, all_(ZERO, 2)),
    "T22": (3, True, all_(ERR, 3)),
    "Manquante": (3, True, all_(ERR, 3)),
    "Temps nul et erreur": (3, True, (Missing(ERR, 3), *all_(ZERO, 3)[1:])),
    "Erreur sur le nul": (3, True, (Missing(ERR, 3), *all_(ZERO, 3)[1:])),
    "Vide": (0, False, all_(INSUF, 0)),
}
"""Le tableau « Support » du § 7.1 : ``n``, drapeau, ``L``, ``A``, ``W``, ``B``,
``C_comp``."""


def unavailable(count: int, under: bool, motif: Unavailability) -> tuple[object, ...]:
    return (
        count,
        under,
        Missing(motif, count),
        Missing(motif, count),
        Missing(motif, count),
    )


CLASSES: dict[str, dict[RegimeClass, tuple[object, ...]]] = {
    "T12": {
        A: (
            2,
            True,
            Approx(0.223143551314, 2),
            Approx(0.693147180560, 2),
            Approx(0.068992871487, 2),
        ),
        X: (1, True, Exact(0.0, 1), Exact(0.0, 1), Approx(-0.154150679827, 1)),
    },
    "Dyadique": {
        A: (
            2,
            True,
            Approx(0.693147180560, 2),
            Approx(0.693147180560, 2),
            Approx(0.693147180560, 2),
        ),
        F: (1, True, Exact(0.0, 1), Exact(0.0, 1), Exact(0.0, 1)),
        D: (
            2,
            True,
            Approx(-1.386294361120, 2),
            Approx(0.693147180560, 2),
            Approx(-1.386294361120, 2),
        ),
    },
    "Quatre classes": {
        A: (
            3,
            False,
            Approx(0.147920130077, 3),
            Approx(0.104287273732, 3),
            Approx(0.181442822115, 3),
        ),
        F: (
            2,
            True,
            Exact(0.0, 2),
            Approx(0.071933231176, 2),
            Approx(0.033522692039, 2),
        ),
        D: (
            3,
            False,
            Approx(-0.246860077932, 3),
            Approx(0.075363100486, 3),
            Approx(-0.213337385893, 3),
        ),
        X: (
            2,
            True,
            Approx(-0.154150679827, 2),
            Approx(0.254827328511, 2),
            Approx(-0.120627987789, 2),
        ),
    },
    "Une classe": {
        A: (2, True, Approx(0.019868071840, 2), Approx(0.2, 2), Exact(0.0, 2)),
    },
    "T11 D": {
        D: (
            2,
            True,
            Approx(-0.405465108108, 2),
            Approx(0.326943084337, 2),
            Exact(0.0, 2),
        ),
    },
    "Un segment": {
        D: (1, True, Approx(-0.105360515658, 1), Exact(0.0, 1), Exact(0.0, 1)),
    },
    "Temps nul": {A: unavailable(1, True, ZERO), D: unavailable(1, True, ZERO)},
    "Tout nul": {A: unavailable(2, True, ZERO)},
    "Tout nul, erreur": {A: unavailable(2, True, ZERO)},
    "T22": {A: unavailable(3, False, ERR)},
    "Manquante": {A: unavailable(1, True, ERR), D: unavailable(2, True, ERR)},
    "Temps nul et erreur": {
        A: unavailable(1, True, ZERO),
        D: unavailable(2, True, ZERO),
    },
    "Erreur sur le nul": {A: unavailable(1, True, ZERO), D: unavailable(2, True, ZERO)},
    "Vide": {},
}
"""Le tableau « Classes » du § 7.1 : classes présentes seulement ; toute autre classe
est absente, ``insuf. (0)``, « trop peu » faux."""


def check_support(
    metrics: SupportMetrics,
    n: int,
    model_error: bool,
    values: tuple[Expected | str, ...],
    classes: dict[RegimeClass, tuple[object, ...]],
) -> None:
    """Chaque champ : effectif, drapeau, les cinq valeurs, les quatre classes."""
    assert metrics.segment_count == n
    assert metrics.model_error is model_error
    published = (
        metrics.log_ratio,
        metrics.dispersion,
        metrics.within,
        metrics.between,
        metrics.compensation,
    )
    for actual, expected in zip(published, values, strict=True):
        if expected == SAME_AS_A:
            assert actual.count == n
            assert actual.value is not None
            assert actual.value == metrics.dispersion.value
        else:
            assert not isinstance(expected, str)
            check(actual, expected)
    assert [c.regime_class for c in metrics.classes] == list(RegimeClass)
    for regime_metrics in metrics.classes:
        row = classes.get(regime_metrics.regime_class)
        if row is None:
            row = unavailable(0, False, INSUF)
        count, under, *expected_values = row
        assert regime_metrics.segment_count == count
        assert regime_metrics.underrepresented is under
        published_class = (
            regime_metrics.log_ratio,
            regime_metrics.dispersion,
            regime_metrics.shape,
        )
        for actual, wanted in zip(published_class, expected_values, strict=True):
            assert isinstance(wanted, Approx | Exact | Missing)
            check(actual, wanted)


@pytest.mark.parametrize("name", SUPPORT_CASES)
def test_support_metrics_reproduce_the_brief(name: str) -> None:
    """§ 7.1 : ``0010`` D7.1, D7.2, D5.5, D7.5 ; choix 1 à 5 de rdw et 1 à 4 du brief —
    chaque champ de chaque fixture."""
    case = SUPPORT_CASES[name]
    n, model_error, values = SUPPORT[name]
    metrics = support_metrics(case.projected_s, case.observed_s, case.classes)
    check_support(metrics, n, model_error, values, CLASSES[name])


def test_dyadic_values_are_fractions_of_ln2() -> None:
    """§ 7.1, Dyadique : rapports en puissances de 2 ; ``A = (34/25)·ln 2``,
    ``W = (21/25)·ln 2``, ``B = (33/25)·ln 2``, ``C_comp = (4/5)·ln 2``, et ``C_comp``
    terme à terme ``(0 + 300 + 200 + 0 + 0)·ln 2 / 625``."""
    case = SUPPORT_CASES["Dyadique"]
    metrics = support_metrics(case.projected_s, case.observed_s, case.classes)
    expected = {
        "dispersion": 34 / 25 * LN2,
        "within": 21 / 25 * LN2,
        "between": 33 / 25 * LN2,
        "compensation": 4 / 5 * LN2,
    }
    for field, wanted in expected.items():
        value: MetricValue = getattr(metrics, field)
        assert value.value == pytest.approx(wanted, abs=1e-12)
    assert metrics.compensation.value == pytest.approx(
        (0 + 300 + 200 + 0 + 0) * LN2 / 625, abs=1e-12
    )


def test_one_class_identity_is_exact() -> None:
    """Choix 1 du brief : une seule classe présente → ``W == A``, ``B == 0.0``,
    ``C_comp == 0.0`` ; une classe d'un segment → ``D_R == 0.0``."""
    for name in ("Une classe", "T11 D", "Un segment"):
        case = SUPPORT_CASES[name]
        metrics = support_metrics(case.projected_s, case.observed_s, case.classes)
        assert metrics.within.value == metrics.dispersion.value
        assert metrics.between.value == 0.0
        assert metrics.compensation.value == 0.0
    case = SUPPORT_CASES["Un segment"]
    metrics = support_metrics(case.projected_s, case.observed_s, case.classes)
    assert metrics.classes[2].dispersion.value == 0.0


# ---------------------------------------------------------------------------
# Préconditions (choix 10 du brief), une par test
# ---------------------------------------------------------------------------

FUNCTIONS = {
    "support_metrics": support_metrics,
    "positive_time_diagnostic": positive_time_diagnostic,
}


@pytest.mark.parametrize("function", FUNCTIONS)
def test_projections_and_times_have_the_same_length(function: str) -> None:
    with raises_value_error(f"{function} : longueurs différentes"):
        FUNCTIONS[function]((100.0,), (100.0, 100.0), (A, A))


@pytest.mark.parametrize("function", FUNCTIONS)
def test_classes_and_times_have_the_same_length(function: str) -> None:
    with raises_value_error(f"{function} : longueurs différentes"):
        FUNCTIONS[function]((100.0, 100.0), (100.0, 100.0), (A,))


@pytest.mark.parametrize("time_s", [-1.0, -0.0 - 1e-300, math.nan, math.inf])
@pytest.mark.parametrize("function", FUNCTIONS)
def test_observed_times_are_finite_and_not_negative(
    function: str, time_s: float
) -> None:
    """Un temps observé faux est une erreur d'appel, pas un statut."""
    with raises_value_error(rf"{function} : observed_s\[1\] doit être fini et >= 0"):
        FUNCTIONS[function]((100.0, 100.0), (100.0, time_s), (A, A))


@pytest.mark.parametrize("function", FUNCTIONS)
def test_classes_are_regime_classes(function: str) -> None:
    wrong: Any = ("ascent",)
    with raises_value_error(rf"{function} : classes\[0\] doit être une RegimeClass"):
        FUNCTIONS[function]((100.0,), (100.0,), wrong)


def test_any_model_output_is_accepted() -> None:
    """D7.1, choix 10 : une sortie de modèle fausse est un statut, jamais une
    exception, quelle que soit sa forme."""
    for bad in (None, math.nan, math.inf, -math.inf, 0.0, -0.0, -5.0):
        metrics = support_metrics((100.0, bad), (100.0, 100.0), (A, D))
        assert metrics.model_error
        assert metrics.log_ratio.unavailability is ERR


# ---------------------------------------------------------------------------
# Diagnostic du sous-support à temps positifs (§ 7.2)
# ---------------------------------------------------------------------------

DIAGNOSTIC: dict[
    str,
    tuple[
        tuple[bool, ...],
        int,
        bool,
        tuple[Expected | str, ...],
        dict[RegimeClass, tuple[object, ...]],
    ],
] = {
    "Temps nul": (
        (False, True),
        1,
        False,
        (Exact(0.0, 1),) * 5,
        {D: (1, True, Exact(0.0, 1), Exact(0.0, 1), Exact(0.0, 1))},
    ),
    "Erreur sur le nul": (
        (False, True, True),
        2,
        True,
        all_(ERR, 2),
        {D: unavailable(2, True, ERR)},
    ),
    "Temps nul et erreur": (
        (False, True, True),
        2,
        True,
        all_(ERR, 2),
        {D: unavailable(2, True, ERR)},
    ),
    "Quatre classes": (
        (True,) * 10,
        *SUPPORT["Quatre classes"],
        CLASSES["Quatre classes"],
    ),
    "Tout nul": ((False, False), 0, False, all_(INSUF, 0), {}),
    "Tout nul, erreur": ((False, False), 0, False, all_(INSUF, 0), {}),
    "Vide": ((), 0, False, all_(INSUF, 0), {}),
}
"""Le tableau du § 7.2 : masque, ``n``, drapeau, valeurs, classes présentes."""


@pytest.mark.parametrize("name", DIAGNOSTIC)
def test_positive_time_diagnostic_reproduces_the_brief(name: str) -> None:
    """§ 7.2 : ``0010`` D5.5 et choix 5 du brief — masque ``t > 0``, mêmes métriques
    sur le sous-support, erreur du modèle jugée sur le support principal, sous-support
    vide sans drapeau."""
    case = SUPPORT_CASES[name]
    mask, n, model_error, values, classes = DIAGNOSTIC[name]
    diagnostic = positive_time_diagnostic(
        case.projected_s, case.observed_s, case.classes
    )
    assert diagnostic.mask == mask
    check_support(diagnostic.metrics, n, model_error, values, classes)


def test_diagnostic_without_zero_time_is_the_support() -> None:
    """§ 6.5 : sans temps nul, ``metrics == support_metrics(...)``."""
    for name in ("Quatre classes", "T12", "T22", "Manquante", "Vide"):
        case = SUPPORT_CASES[name]
        diagnostic = positive_time_diagnostic(
            case.projected_s, case.observed_s, case.classes
        )
        assert diagnostic.metrics == support_metrics(
            case.projected_s, case.observed_s, case.classes
        )


def test_diagnostic_drops_the_zero_time_class() -> None:
    """§ 7.2, Temps nul : la montée, présente sur le support principal, est absente
    du diagnostic (``insufficient_support (0)``, « trop peu » faux)."""
    case = SUPPORT_CASES["Temps nul"]
    diagnostic = positive_time_diagnostic(
        case.projected_s, case.observed_s, case.classes
    )
    ascent = diagnostic.metrics.classes[0]
    assert ascent.segment_count == 0
    assert not ascent.underrepresented
    assert ascent.log_ratio.unavailability is INSUF


# ---------------------------------------------------------------------------
# Correctifs de la relecture de la PR #14
# ---------------------------------------------------------------------------


def test_diagnostic_keeps_the_projections_of_the_kept_segments() -> None:
    """§ 6.5 : le diagnostic prend les projections des segments de masque vrai. Le
    segment gardé a ``p = t = 100`` : ``L`` et ``E_descente`` valent ``0``."""
    diagnostic = positive_time_diagnostic((50.0, 100.0), (0.0, 100.0), (A, D))
    assert diagnostic.mask == (False, True)
    assert diagnostic.metrics.segment_count == 1
    assert diagnostic.metrics.log_ratio.value == 0.0
    assert diagnostic.metrics.classes[2].log_ratio.value == 0.0


def test_mask_keeps_a_small_positive_time() -> None:
    """Choix 5 et 12 : masque ``t_i > 0`` strict ; ``t = 1e−5`` s est dans le domaine
    promis, sous le ``1e−3`` de la stratégie des propriétés."""
    diagnostic = positive_time_diagnostic((2e-5, 100.0), (1e-5, 100.0), (A, D))
    assert diagnostic.mask == (True, True)
    assert diagnostic.metrics == support_metrics((2e-5, 100.0), (1e-5, 100.0), (A, D))
