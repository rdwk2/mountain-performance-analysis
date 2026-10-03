"""Fonctions pures de la référence de répétabilité (§§ 6.2, 6.3, 7.1, 7.4 et § 8.1,
tests 2 et 3, du brief M4b-3 ; précision de ``0010`` D8.3).

``two_way_fit`` : les moyennes alternées à la lettre (choix 3 du brief) — effets de
Complet, itérations **exactes** de Lent (la seule trace du report du centrage, de
chaque critère et de la limite comprise), préconditions, propriété sur des plans
tirés. ``contraction_rate`` : ``μ₂`` par Jacobi (choix 4) — valeurs du § 7.1,
certification, préconditions, propriété. Tolérance du § 7.0 :
``1e−6·max(1, |x|)``.

Les préconditions exigent ``ValueError`` **exactement** : ``ContractError`` en est une
sous-classe et passerait pour une mauvaise raison.
"""

import inspect
import math
import random

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fixtures.repeatability import (
    COMPLET,
    LENT,
    LENT_LIMITE_MAX_ITERATIONS,
    VARIANTES,
    A,
    close,
    log_cells,
    plan_cells,
)
from mountain_perf.backtest import (
    JACOBI_MAX_SWEEPS,
    JACOBI_OFF_DIAGONAL_TOLERANCE,
    MAX_ITERATIONS,
    contraction_rate,
    repeatability_reference,
    two_way_fit,
)

E, M1 = 0, 1
"""Indices de l'écoulé et de ``M θ1`` dans ``CLOCKS`` (§ 7.0)."""

LENT_ITERATIONS = {E: (91, 75, 62, 45), M1: (91, 75, 62, 46)}
"""Les itérations exactes des quatre plis de Lent (§ 7.1), dans l'ordre des jours."""


# ---------------------------------------------------------------------------
# two_way_fit (test 2)
# ---------------------------------------------------------------------------


def test_complete_plan_is_certified_in_exactly_two_iterations() -> None:
    """§ 6.2, choix 3 : un plan complet est certifié en exactement deux itérations —
    la première n'a pas d'incrément (``inf``), la seconde le trouve nul."""
    fit = two_way_fit(log_cells(COMPLET, E, A))
    assert fit.certified
    assert fit.iterations == 2
    assert fit.residuals[3] == 0.0
    assert [k for k, _ in fit.segment_effects] == [0, 1, 2]
    assert [u for u, _ in fit.day_effects] == [0, 1, 2]
    expected_a = (5.3383182973, 5.4004290806, 5.2552324213)
    expected_c = (-0.0338436099, 0.0380218386, -0.0041782287)
    for (_, value), expected in zip(fit.segment_effects, expected_a, strict=True):
        assert close(value, expected)
    for (_, value), expected in zip(fit.day_effects, expected_c, strict=True):
        assert close(value, expected)


def test_one_iteration_is_never_certified() -> None:
    """Précision de D8.3 : l'incrément se mesure d'une itération à la suivante, d'où
    au moins deux ; à la première, il vaut ``inf``."""
    fit = two_way_fit(log_cells(COMPLET, E, A), max_iterations=1)
    assert not fit.certified
    assert fit.iterations == 1
    assert fit.residuals[3] == math.inf
    assert all(value < 1e-8 for value in fit.residuals[:3])


@pytest.mark.parametrize("clock", [E, M1])
@pytest.mark.parametrize("fold", range(4))
def test_lent_iterations_are_exact(clock: int, fold: int) -> None:
    """§ 7.1 : les itérations de chaque pli de Lent, exactes — le centrage avec report
    ``a_k ← a_k + m`` (``2026-10-04`` : 45, et non 46), le critère des résidus par
    segment (``2026-10-01`` : 91, et non 89), critères évalués après le centrage."""
    fit = two_way_fit(log_cells(LENT, clock, A, without=fold))
    assert fit.certified
    assert fit.iterations == LENT_ITERATIONS[clock][fold]


@pytest.mark.parametrize("fold", [0, 3])
def test_iteration_limit_is_included(fold: int) -> None:
    """Précision de D8.3 : la limite comprend la dernière itération — certifié avec
    ``max_iterations`` égal au nombre d'itérations, non certifié avec un de moins."""
    cells = log_cells(LENT, E, A, without=fold)
    needed = LENT_ITERATIONS[E][fold]
    at_limit = two_way_fit(cells, max_iterations=needed)
    assert at_limit.certified
    assert at_limit.iterations == needed
    short = two_way_fit(cells, max_iterations=needed - 1)
    assert not short.certified
    assert short.iterations == needed - 1


@pytest.mark.parametrize(
    ("cells", "max_iterations", "message"),
    [
        ({}, 10, "aucune cellule"),
        ({(0, 0): math.nan}, 10, "valeur non finie"),
        ({(0, 0): 1.0, (1, 1): 1.0}, 10, "non connexe"),
        (log_cells(COMPLET, E, A), 0, "max_iterations doit être >= 1"),
    ],
    ids=["vide", "nan", "deux composantes", "max_iterations=0"],
)
def test_two_way_fit_preconditions(
    cells: dict[tuple[int, int], float], max_iterations: int, message: str
) -> None:
    """§ 6.2 : préconditions, ``ValueError`` exactement."""
    with pytest.raises(ValueError, match=message) as raised:
        two_way_fit(cells, max_iterations)
    assert raised.type is ValueError


@st.composite
def connected_plans(draw: st.DrawFn) -> dict[tuple[int, int], float]:
    """§ 8.1, test 2 : de 2 à 5 jours, de 2 à 6 segments, chaque jour observe le
    segment 0 et une partie tirée des autres, ``y`` tiré dans ``[3 ; 7]``."""
    day_count = draw(st.integers(2, 5))
    segment_count = draw(st.integers(2, 6))
    cells: dict[tuple[int, int], float] = {}
    for u in range(day_count):
        others = draw(st.sets(st.integers(1, segment_count - 1)))
        for k in (0, *sorted(others)):
            cells[u, k] = draw(st.floats(3.0, 7.0))
    return cells


@settings(deadline=None)
@given(connected_plans())
def test_two_way_fit_certifies_drawn_plans(cells: dict[tuple[int, int], float]) -> None:
    """§ 7.4 : sur des plans tirés connexes, l'ajustement est certifié en au moins
    deux itérations, et les critères de D8.3 recalculés depuis les effets publiés
    sont sous ``1e−8``."""
    fit = two_way_fit(cells)
    assert fit.certified
    assert fit.iterations >= 2
    a, c = dict(fit.segment_effects), dict(fit.day_effects)
    residual = {(u, k): (y - a[k]) - c[u] for (u, k), y in cells.items()}
    for k in a:
        values = [e for (_, kk), e in residual.items() if kk == k]
        assert abs(math.fsum(values) / len(values)) < 1e-8
    for u in c:
        values = [e for (uu, _), e in residual.items() if uu == u]
        assert abs(math.fsum(values) / len(values)) < 1e-8
    assert abs(math.fsum(c.values())) < 1e-8


# ---------------------------------------------------------------------------
# contraction_rate (test 3)
# ---------------------------------------------------------------------------


def test_complete_plan_has_zero_contraction() -> None:
    """Précision de D8.3 : ``μ₂ = 0`` pour un plan complet (Complet, montée)."""
    assert close(contraction_rate(plan_cells(COMPLET, A)), 0.0)


def test_one_day_has_exactly_zero_contraction() -> None:
    """Précision de D8.3 : ``0`` pour un seul jour, exactement."""
    assert contraction_rate({(0, 1), (0, 2)}) == 0.0


def test_two_days_sharing_one_segment() -> None:
    """§ 7.1 : deux jours de 40 segments qui n'en partagent qu'un, ``μ₂ = 39/40`` —
    des jours mal reliés donnent ``μ₂`` proche de 1."""
    cells = {(0, k) for k in range(40)} | {(1, k) for k in range(39, 79)}
    assert close(contraction_rate(cells), 0.975)


@pytest.mark.parametrize(
    ("fold", "expected"),
    [(0, 0.8612987560), (1, 0.8605551275), (2, 0.8061960132), (3, 0.7333333333)],
)
def test_lent_contraction(fold: int, expected: float) -> None:
    assert close(contraction_rate(plan_cells(LENT, A, without=fold)), expected)


def test_variantes_contraction() -> None:
    assert close(contraction_rate(plan_cells(VARIANTES, A)), 0.2222222222)


def test_uncertified_jacobi_is_none() -> None:
    """Précision de D8.3, choix 4 : un calcul de ``μ₂`` non certifié est publié
    indisponible, jamais ``0``."""
    assert contraction_rate(plan_cells(VARIANTES, A), max_sweeps=0) is None


def test_repeated_cell_counts_once() -> None:
    """Docstring de ``contraction_rate`` : une cellule répétée compte une fois."""
    cells = sorted(plan_cells(VARIANTES, A))
    assert contraction_rate(cells + cells[:3]) == contraction_rate(cells)


@pytest.mark.parametrize(
    ("cells", "message"),
    [(set(), "aucune cellule"), ({(0, 0), (1, 1)}, "non connexe")],
    ids=["vide", "deux composantes"],
)
def test_contraction_rate_preconditions(
    cells: set[tuple[int, int]], message: str
) -> None:
    """§ 6.3 : préconditions, ``ValueError`` exactement."""
    with pytest.raises(ValueError, match=message) as raised:
        contraction_rate(cells)
    assert raised.type is ValueError


@settings(deadline=None)
@given(connected_plans(), st.randoms(use_true_random=False))
def test_contraction_rate_properties(
    cells: dict[tuple[int, int], float], rng: random.Random
) -> None:
    """§ 7.4 : ``μ₂`` dans ``[0 ; 1]`` ; inchangé à ``1e−12`` près quand on
    renumérote les jours et les segments (il ne dépend que du plan) ; ``0`` à
    ``1e−12`` près pour le plan complet sur les mêmes jours et segments."""
    plan = set(cells)
    value = contraction_rate(plan)
    assert value is not None
    assert 0.0 <= value <= 1.0
    days = sorted({u for u, _ in plan})
    segments = sorted({k for _, k in plan})
    new_days = rng.sample(range(100), len(days))
    new_segments = rng.sample(range(100), len(segments))
    day_map = dict(zip(days, new_days, strict=True))
    segment_map = dict(zip(segments, new_segments, strict=True))
    renumbered = contraction_rate({(day_map[u], segment_map[k]) for u, k in plan})
    assert renumbered is not None
    assert abs(renumbered - value) <= 1e-12
    complete = contraction_rate({(u, k) for u in days for k in segments})
    assert complete is not None
    assert abs(complete) <= 1e-12


# ---------------------------------------------------------------------------
# Correctifs de la relecture de la PR #18
# ---------------------------------------------------------------------------


SIX_CELLS = {
    (0, 0): 81,
    (1, 0): 184,
    (1, 3): 371,
    (2, 1): 125,
    (2, 2): 104,
    (2, 3): 351,
}
TEN_CELLS = {
    (0, 0): 203,
    (1, 0): 331,
    (2, 0): 63,
    (3, 0): 361,
    (3, 1): 249,
    (3, 2): 346,
    (4, 0): 388,
    (4, 1): 479,
    (4, 2): 70,
    (5, 0): 253,
}


def test_criteria_are_evaluated_after_the_centering() -> None:
    """Choix 3, § 6.2 étape 2.4 : les critères sont évalués **après** le centrage. Sur
    ces deux plans (temps en secondes, ``y = ln t``), les évaluer avant donne une
    itération de plus (49 au lieu de 48 ; 24 au lieu de 23, donc non certifié à 23) ;
    comptes de la conception et de la relecture C, chacune par sa propre écriture du
    § 6.2."""
    six = two_way_fit({cell: math.log(t) for cell, t in SIX_CELLS.items()})
    assert (six.certified, six.iterations) == (True, 48)
    ten = two_way_fit({cell: math.log(t) for cell, t in TEN_CELLS.items()}, 23)
    assert (ten.certified, ten.iterations) == (True, 23)


def test_backtest_constants_and_defaults() -> None:
    """Décision 1 de rdw (10 000 itérations, la dernière comprise), choix 4 (50
    balayages, ``off <= 1e−24``) ; ce sont les valeurs par défaut des trois
    fonctions."""
    assert MAX_ITERATIONS == 10_000
    assert JACOBI_MAX_SWEEPS == 50
    assert JACOBI_OFF_DIAGONAL_TOLERANCE == 1e-24
    for function in (two_way_fit, repeatability_reference):
        default = inspect.signature(function).parameters["max_iterations"].default
        assert default == 10_000
    assert inspect.signature(contraction_rate).parameters["max_sweeps"].default == 50


@pytest.mark.parametrize("limit", [10_000, LENT_LIMITE_MAX_ITERATIONS])
def test_residuals_are_the_criteria_of_the_published_state(limit: int) -> None:
    """§ 6.1 ``TwoWayFit.residuals`` : les critères de D8.3 **à la dernière itération**,
    dans l'ordre (moyennes de résidus par segment, par jour, ``|Σ c_u|``, incrément
    maximal), recalculés ici sur les effets publiés et sur ceux de l'itération d'avant —
    pli ``2026-10-01`` de Lent sous ``E``, certifié (91) et non certifié (70)."""
    log_times = log_cells(LENT, 0, A, without=0)
    fit = two_way_fit(log_times, limit)
    a, c = dict(fit.segment_effects), dict(fit.day_effects)
    e = {(u, k): (y - a[k]) - c[u] for (u, k), y in log_times.items()}
    by_segment = max(
        abs(
            math.fsum(v for (_, j), v in e.items() if j == k)
            / [j for _, j in e].count(k)
        )
        for k in a
    )
    by_day = max(
        abs(
            math.fsum(v for (w, _), v in e.items() if w == u)
            / [w for w, _ in e].count(u)
        )
        for u in c
    )
    before = two_way_fit(log_times, fit.iterations - 1)
    pa, pc = dict(before.segment_effects), dict(before.day_effects)
    increment = max(abs((a[k] + c[u]) - (pa[k] + pc[u])) for u, k in log_times)
    expected = (by_segment, by_day, abs(math.fsum(c.values())), increment)
    assert fit.residuals == expected
    assert fit.certified is (limit == 10_000)


def test_the_jacobi_sweep_limit_is_counted() -> None:
    """Choix 4 : « au plus ``max_sweeps`` balayages, sinon ``None`` », contrôle avant
    chaque balayage et après le dernier. Trois jours en chaîne : trois balayages ; deux
    jours : un (comptes exacts, opérations IEEE correctement arrondies)."""
    chain = [(0, 0), (0, 1), (1, 1), (1, 2), (2, 2), (2, 3)]
    assert contraction_rate(chain, max_sweeps=2) is None
    assert contraction_rate(chain, max_sweeps=3) == pytest.approx(0.75, abs=1e-12)
    two = [(0, 0), (0, 1), (1, 1), (1, 2)]
    assert contraction_rate(two, max_sweeps=0) is None
    assert contraction_rate(two, max_sweeps=1) == pytest.approx(0.5, abs=1e-12)
