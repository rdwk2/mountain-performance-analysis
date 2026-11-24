"""L'ajustement joint des niveaux et l'écart récent (M6b-3, § 8.2 du brief,
``docs/decisions/0025``).

Deux tranches suffisent : ``k = 17`` (de 0 à 2,5 %) et ``k = 25`` (de 20 à 22,5 %) ; au
niveau 0, le plat va à 3 m/s, la montée à 1 m/s. Deux références par cas : la forme
close, calculée à la main (``abs=1e-9``, facteurs ``rel=1e-9``), et la valeur de
l'oracle de la conception (le même algorithme, mêmes ordres de sommes ; ``abs=1e-12``).
Les comptes d'itérations sont exacts."""

from __future__ import annotations

import math

import pytest

from mountain_perf.estimation.levels import (
    MAX_ITERATIONS,
    TOLERANCE,
    ActivityBins,
    fit_joint_levels,
    level_shift,
)
from mountain_perf.validation import ContractError

FLAT, CLIMB = 17, 25
LN3 = math.log(3.0)


def row(ref: str, cells: dict[int, tuple[float, float]]) -> ActivityBins:
    return ActivityBins(ref, tuple((k, *cells[k]) for k in sorted(cells)))


A = row("A", {FLAT: (3000.0, 1000.0), CLIMB: (1000.0, 1000.0)})
B = row("B", {FLAT: (6000.0, 2000.0)})
N2 = (A, B, row("C", {FLAT: (3300.0, 1000.0), CLIMB: (1100.0, 1000.0)}))
N3 = (
    A,
    B,
    row("C", {FLAT: (1800.0, 500.0), CLIMB: (600.0, 500.0)}),
    row("D", {FLAT: (4500.0, 1500.0), CLIMB: (1500.0, 1500.0)}),
)
N4 = (
    row("A", {FLAT: (3000.0, 1000.0)}),
    row("B", {FLAT: (3300.0, 1000.0), CLIMB: (500.0, 600.0)}),
)
N5 = (
    row("X", {1: (1000.0, 500.0)}),
    row("Y", {1: (10.0, 4.0), 2: (1000.0, 300.0)}),
    row("Z", {2: (1000.0, 600.0)}),
)


def _oracle(levels: tuple[float, ...], expected: list[float]) -> None:
    assert levels == pytest.approx(expected, abs=1e-12)


def test_the_constants() -> None:
    assert (TOLERANCE, MAX_ITERATIONS) == (1e-10, 1000)


def test_n1_one_activity() -> None:
    fit = fit_joint_levels((A,))
    assert fit.levels[0] == pytest.approx(-0.5 * LN3, abs=1e-9)
    _oracle(fit.levels, [-0.5493061443340549])
    assert (fit.iterations, fit.converged) == (1, True)


def test_n2_three_activities() -> None:
    fit = fit_joint_levels(N2)
    old = -2 / 3 * LN3
    assert fit.levels == pytest.approx([old, old, old - math.log(1.1)], abs=1e-9)
    _oracle(
        fit.levels,
        [-0.7324081924417108, -0.7324081924527978, -0.8277183722460357],
    )
    assert (fit.iterations, fit.converged) == (15, True)


def test_n3_the_weights() -> None:
    fit = fit_joint_levels(N3)
    base = -5 / 8 * LN3
    assert fit.levels == pytest.approx(
        [base, base, base - math.log(1.2), base], abs=1e-9
    )
    _oracle(
        fit.levels,
        [
            -0.6866326804162474,
            -0.6866326804215324,
            -0.8689542372102018,
            -0.6866326804162474,
        ],
    )
    assert (fit.iterations, fit.converged) == (13, True)


def test_n4_saturated() -> None:
    fit = fit_joint_levels(N4)
    # Au plat de A pris à 3 m/s (f₁₇ = ln 3), ln e_A = 0 : λ_A = −c₀.
    offset = (2000 * LN3 + 600 * (math.log(5 / 6) - math.log(1.1))) / 2600
    assert fit.levels[1] - fit.levels[0] == pytest.approx(-math.log(1.1), abs=1e-9)
    assert fit.levels[0] == pytest.approx(-offset, abs=1e-9)
    assert fit.levels[1] == pytest.approx(-offset - math.log(1.1), abs=1e-9)
    _oracle(fit.levels, [-0.7810175136103487, -0.8763276934086395])
    assert (fit.iterations, fit.converged) == (13, True)


def test_n5_not_converged() -> None:
    fit = fit_joint_levels(N5)
    assert (fit.iterations, fit.converged) == (MAX_ITERATIONS, False)
    _oracle(
        fit.levels,
        [-0.8775581719625373, -1.1007026369580726, -0.40755546858053915],
    )


def _weights(rows: tuple[ActivityBins, ...]) -> list[float]:
    return [r.moving_s for r in rows]


def test_s1_one_activity() -> None:
    assert level_shift([0.1], [1000.0], [True]) is None


def test_s2_no_recent() -> None:
    levels = fit_joint_levels(N2).levels
    assert level_shift(levels, _weights(N2), [False, False, False]) is None


def test_s3_all_recent() -> None:
    levels = fit_joint_levels(N2).levels
    shift = level_shift(levels, _weights(N2), [True, True, True])
    assert shift == 0.0
    assert isinstance(shift, float)


def test_s4_one_recent() -> None:
    levels = fit_joint_levels(N2).levels
    assert _weights(N2) == [2000.0, 2000.0, 2000.0]
    shift = level_shift(levels, _weights(N2), [False, False, True])
    assert shift is not None
    assert shift == pytest.approx(-2 / 3 * math.log(1.1), abs=1e-9)
    assert shift == pytest.approx(-0.0635401199, abs=1e-9)
    assert math.exp(-0.5 * shift) == pytest.approx(1.1 ** (1 / 3), rel=1e-9)
    assert math.exp(-0.5 * shift) == pytest.approx(1.0322801155, rel=1e-9)


def test_s5_weighted() -> None:
    levels = fit_joint_levels(N3).levels
    assert _weights(N3) == [2000.0, 2000.0, 1000.0, 3000.0]
    shift = level_shift(levels, _weights(N3), [False, False, True, True])
    assert shift is not None
    assert shift == pytest.approx(-math.log(1.2) / 8, abs=1e-9)
    assert shift == pytest.approx(-0.0227901946, abs=1e-9)
    assert math.exp(-0.5 * shift) == pytest.approx(1.2 ** (1 / 16), rel=1e-9)
    assert math.exp(-0.5 * shift) == pytest.approx(1.0114602687, rel=1e-9)


def test_s6_saturated() -> None:
    levels = fit_joint_levels(N4).levels
    assert _weights(N4) == [1000.0, 1600.0]
    shift = level_shift(levels, _weights(N4), [False, True])
    assert shift == pytest.approx(-10 / 26 * math.log(1.1), abs=1e-9)
    assert shift == pytest.approx(-0.0366577615, abs=1e-9)


def test_the_order_of_rows_changes_no_difference() -> None:
    forward = fit_joint_levels(N3).levels
    order = (2, 0, 3, 1)
    backward = fit_joint_levels(tuple(N3[i] for i in order)).levels
    by_ref = {N3[i].activity_ref: backward[j] for j, i in enumerate(order)}
    moved = [by_ref[r.activity_ref] for r in N3]
    for i in range(1, len(N3)):
        assert moved[i] - moved[0] == pytest.approx(forward[i] - forward[0], abs=1e-9)


@pytest.mark.parametrize(
    ("ref", "bins", "fragment"),
    [
        ("", ((17, 1.0, 1.0),), "activity_ref"),
        ("A", (), "au moins une cellule"),
        ("A", ((38, 1.0, 1.0),), "une tranche entière"),
        ("A", ((-1, 1.0, 1.0),), "une tranche entière"),
        ("A", ((True, 1.0, 1.0),), "une tranche entière"),
        ("A", ((18, 1.0, 1.0), (17, 1.0, 1.0)), "strictement croissantes"),
        ("A", ((17, 1.0, 1.0), (17, 1.0, 1.0)), "strictement croissantes"),
        ("A", ((17, 0.0, 1.0),), "length_moving_m doit être > 0"),
        ("A", ((17, 1.0, -1.0),), "moving_s doit être > 0"),
        ("A", ((17, math.inf, 1.0),), "length_moving_m doit être fini"),
        ("A", ((17, 1.0, math.nan),), "moving_s doit être fini"),
    ],
)
def test_the_contracts(
    ref: str, bins: tuple[tuple[int, float, float], ...], fragment: str
) -> None:
    with pytest.raises(ContractError, match=fragment):
        ActivityBins(ref, bins)


def test_the_contracts_of_the_functions() -> None:
    with pytest.raises(ContractError, match="au moins une activité"):
        fit_joint_levels(())
    with pytest.raises(ContractError, match="deux fois"):
        fit_joint_levels((A, A))
    with pytest.raises(ContractError, match="même longueur"):
        level_shift([0.0, 0.0], [1.0], [True, False])
    with pytest.raises(ContractError, match="même longueur"):
        level_shift([0.0], [1.0], [True, False])
    with pytest.raises(ContractError, match="poids > 0"):
        level_shift([0.0, 0.0], [1.0, 0.0], [True, False])
    with pytest.raises(ContractError, match="fini"):
        level_shift([0.0, 0.0], [1.0, math.inf], [True, False])
