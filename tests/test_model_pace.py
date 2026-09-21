"""Modèle d'allure : la table du brief, le piège de l'interpolation, les propriétés.

Tolérance des allures : ``1e-12`` en absolu. Le brief ne fixe une tolérance que sur
les **temps** (``1e-9``) ; ``1e-12`` reste trois ordres de grandeur en dessous et
absorbe le seul écart mesuré — ``p(−5 %)`` tombe à 1 ulp de ``11/30``, qui n'est pas
représentable en binaire.
"""

import math

import pytest
from hypothesis import given

from fixtures.curves import SUPPORT_CURVE
from mountain_perf.model.pace import MAX_SAFE_GRADE, PaceModel
from mountain_perf.schemas import PaceCurve
from strategies import finite_floats, model_pace_curves

PACE_TOLERANCE = 1e-12
MODEL = PaceModel(SUPPORT_CURVE)

# Vitesse verticale minimale garantie par le lecteur : (0,01 / 3,6) × 0,01 m/s.
MAX_SAFE_PACE_S_PER_M = MAX_SAFE_GRADE * 36_000


# ---------------------------------------------------------------------------
# La table du brief
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("grade", "expected", "regime"),
    [
        (-0.20, 0.5, "nœud, bord bas"),
        (-0.10, 0.4, "nœud"),
        (0.0, 1 / 3, "nœud"),
        (0.10, 2 / 3, "nœud"),
        (0.20, 1.0, "nœud, bord haut"),
        (0.05, 1 / 2, "interpolation"),
        (-0.05, 11 / 30, "interpolation"),
        (0.40, 2.0, "prolongement, C₊ = 0,2 m/s"),
        (-0.40, 1.0, "prolongement, C₋ = 0,4 m/s"),
    ],
)
def test_pace_table(grade: float, expected: float, regime: str) -> None:
    assert MODEL.pace_s_per_m(grade) == pytest.approx(expected, abs=PACE_TOLERANCE)


def test_nodes_are_exact_not_merely_close() -> None:
    """Deux pentes égales doivent donner le même bit, pas seulement la même valeur."""
    for grade, speed_ms in zip(
        SUPPORT_CURVE.grade, SUPPORT_CURVE.speed_ms, strict=True
    ):
        assert MODEL.pace_s_per_m(grade) == 1.0 / speed_ms


def test_interpolation_is_in_pace_not_in_speed() -> None:
    """Le piège de D3, et la seule chose qui distingue les deux conventions.

    À +5 %, entre les nœuds +0 % (3 m/s) et +10 % (1,5 m/s) : en interpolant
    l'**allure** on obtient 0,5 s/m ; en interpolant la **vitesse** on obtiendrait
    ``1 / 2,25 = 0,444…`` s/m. Un test qui ne les sépare pas ne vérifie rien de ce
    que D3 décide.
    """
    speed_convention = 1.0 / ((3.0 + 1.5) / 2)
    assert speed_convention == pytest.approx(1 / 2.25, abs=PACE_TOLERANCE)
    assert MODEL.pace_s_per_m(0.05) == pytest.approx(0.5, abs=PACE_TOLERANCE)
    assert abs(MODEL.pace_s_per_m(0.05) - speed_convention) > 0.05


def test_speed_is_the_inverse_of_the_pace() -> None:
    assert MODEL.speed_ms(0.0) == pytest.approx(3.0)
    assert MODEL.speed_ms(0.05) == pytest.approx(2.0)
    # Prolongement : la vitesse verticale reste 0,2 m/s, la vitesse horizontale suit.
    assert MODEL.speed_ms(0.40) == pytest.approx(0.5)
    assert MODEL.speed_ms(0.40) * 0.40 == pytest.approx(0.2)
    assert MODEL.speed_ms(-0.40) * 0.40 == pytest.approx(0.4)


@pytest.mark.parametrize("grade", [0.5, 1.0, 3.0, 10.0, 100.0])
def test_extrapolation_freezes_the_vertical_speed_however_far(grade: float) -> None:
    """D4, littéralement : ``|v(g) × g| == C±``, loin du bord comme près.

    Seul le voisinage du bord était vérifié : plafonner ``|g|`` à 3 dans la branche
    hors support passait. Les vitesses verticales de bord de la courbe synthétique
    valent ``C₋ = 2,0 × 0,20 = 0,4`` m/s et ``C₊ = 1,0 × 0,20 = 0,2`` m/s.
    """
    assert abs(MODEL.speed_ms(grade) * grade) == 0.2
    assert abs(MODEL.speed_ms(-grade) * -grade) == 0.4


@given(model_pace_curves(), finite_floats(1.5, 500.0))
def test_vertical_speed_is_the_invariant_of_the_extrapolation(
    curve: PaceCurve, multiplier: float
) -> None:
    """La même propriété sur des courbes quelconques, et de chaque côté.

    La pente d'essai est un multiple du bord, jamais le bord lui-même : à
    ``g = g_b`` on est encore dans le support. Le multiple reste dans le domaine
    garanti, ``|g_b| <= 2`` et le facteur ``<= 500``.
    """
    model = PaceModel(curve)
    for edge, speed_ms in (
        (curve.grade[-1], curve.speed_ms[-1]),
        (curve.grade[0], curve.speed_ms[0]),
    ):
        at = edge * multiplier
        assert model.is_extrapolated(at)
        vertical = abs(model.speed_ms(at) * at)
        assert vertical == pytest.approx(abs(speed_ms * edge), rel=1e-12)


def test_grade_range_and_extrapolation_flag() -> None:
    assert MODEL.grade_range == (-0.20, 0.20)
    # Les bords font partie du support : ils sont interpolés, pas prolongés.
    assert not MODEL.is_extrapolated(-0.20)
    assert not MODEL.is_extrapolated(0.0)
    assert not MODEL.is_extrapolated(0.20)
    assert MODEL.is_extrapolated(-0.2000001)
    assert MODEL.is_extrapolated(0.2000001)


# ---------------------------------------------------------------------------
# Propriétés
# ---------------------------------------------------------------------------


@given(model_pace_curves(), finite_floats(-MAX_SAFE_GRADE, MAX_SAFE_GRADE))
def test_pace_is_finite_and_positive_on_the_guaranteed_domain(
    curve: PaceCurve, grade: float
) -> None:
    """Propriété 2 : au-delà de |g| <= 1000, c'est la représentation qui lâche."""
    pace = PaceModel(curve).pace_s_per_m(grade)
    assert math.isfinite(pace)
    assert pace > 0
    # Le facteur absorbe l'arrondi du produit v·g à la borne, pas un dépassement.
    assert pace <= MAX_SAFE_PACE_S_PER_M * (1 + 1e-9)


@given(model_pace_curves())
def test_extrapolation_joins_interpolation_exactly_at_both_edges(
    curve: PaceCurve,
) -> None:
    """Propriété 3 : égalité **au nœud**, pas au voisinage du nœud."""
    model = PaceModel(curve)
    for grade, speed_ms in (
        (curve.grade[0], curve.speed_ms[0]),
        (curve.grade[-1], curve.speed_ms[-1]),
    ):
        extended = abs(grade) / abs(speed_ms * grade)
        assert model.pace_s_per_m(grade) == pytest.approx(extended, rel=1e-12)


@given(model_pace_curves(), finite_floats(0.0, 0.01))
def test_pace_varies_at_the_local_slope_on_each_side(
    curve: PaceCurve, epsilon: float
) -> None:
    """Le voisinage des bords, **chaque côté avec sa propre pente locale**.

    À l'extérieur, l'allure varie de ``K_out = 1/C±`` par unité de pente. À
    l'intérieur, rien ne borne la pente de l'interpolation par ``1/C±`` : sur une
    courbe dont la dernière tranche intérieure est raide, ``K_in`` la dépasse, et
    un test qui n'utiliserait que ``K_out`` rejetterait une implémentation exacte.
    """
    model = PaceModel(curve)
    low, high = curve.grade[0], curve.grade[-1]
    pace_low, pace_high = 1.0 / curve.speed_ms[0], 1.0 / curve.speed_ms[-1]

    def bounded(reference: float, at: float, slope: float, step: float) -> None:
        gap = abs(model.pace_s_per_m(at) - reference)
        assert gap <= slope * step * (1 + 1e-9) + 1e-12

    bounded(pace_low, low - epsilon, 1.0 / abs(curve.speed_ms[0] * low), epsilon)
    bounded(pace_high, high + epsilon, 1.0 / abs(curve.speed_ms[-1] * high), epsilon)
    # À l'intérieur, le pas est borné par la tranche voisine : au-delà, la pente
    # locale n'est plus celle de cet intervalle-là.
    inner_low = min(epsilon, curve.grade[1] - low)
    width_low = curve.grade[1] - low
    bounded(
        pace_low,
        low + inner_low,
        abs(pace_low - 1.0 / curve.speed_ms[1]) / width_low,
        inner_low,
    )
    inner_high = min(epsilon, high - curve.grade[-2])
    width_high = high - curve.grade[-2]
    bounded(
        pace_high,
        high - inner_high,
        abs(pace_high - 1.0 / curve.speed_ms[-2]) / width_high,
        inner_high,
    )


@given(model_pace_curves(), finite_floats(-2.0, 2.0))
def test_pace_and_speed_are_inverse_of_each_other(
    curve: PaceCurve, grade: float
) -> None:
    model = PaceModel(curve)
    assert model.speed_ms(grade) == pytest.approx(1.0 / model.pace_s_per_m(grade))


@given(model_pace_curves(), finite_floats(-MAX_SAFE_GRADE, MAX_SAFE_GRADE))
def test_model_has_no_memory(curve: PaceCurve, grade: float) -> None:
    """Aucun cache : deux appels identiques rendent le même bit, dans les deux sens."""
    model = PaceModel(curve)
    first = model.pace_s_per_m(grade)
    model.pace_s_per_m(-grade)
    assert model.pace_s_per_m(grade) == first
