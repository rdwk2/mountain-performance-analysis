"""Préconditions, erreur du modèle et ``μ₂`` non certifié (§ 6.4 et § 8.1, tests 7
et 10, du brief M4b-3 ; choix 5 ; précisions de ``0010`` D8.1, D8.3, D8.4).

Test 7 : chaque jeu refusé lève ``ValueError`` **exactement** (``ContractError`` en
est une sous-classe : sans le contrôle du producteur, un contrat la lèverait pour une
autre raison), avec le message de sa précondition ; le jeu accepté ; les entrées
dégénérées.

Test 10 : ``two_way_fit`` et ``contraction_rate`` remplacés **dans le module**
``mountain_perf.backtest.repeatability`` ; chaque référence, d'origine comme
remplacée, est calculée par ``repeatability_reference`` directement, sans le cache
des cas (précision 2 de la relecture du plan).
"""

from collections.abc import Callable, Mapping
from dataclasses import replace

import pytest

import mountain_perf.backtest.repeatability as repeatability_module
from fixtures.repeatability import (
    COMPLET,
    DEUX_JOURS,
    OTHER_REFERENCE,
    REFERENCE,
    VARIANTES,
    anchored_segment,
    build_day,
    cell_segment,
    day,
    days_of,
    segments_of,
    tm,
)
from mountain_perf.backtest import repeatability_reference
from mountain_perf.schemas import (
    CLOCKS,
    AdmittedSegment,
    MetricValue,
    RepeatabilityDay,
    RepeatabilityReference,
    TwoWayFit,
    Unavailability,
)

INSUF = Unavailability.INSUFFICIENT_SUPPORT
UNIDENTIFIED = Unavailability.UNIDENTIFIED_REFERENCE
NON_CONV = Unavailability.NON_CONVERGENCE
ERR = Unavailability.MODEL_ERROR
FIRST, SECOND = DEUX_JOURS
MULTI_DAY = day("2026-05-24", {0: ("ascent", tm(280))}, multi=True)


def _second_with(*segments: AdmittedSegment) -> list[RepeatabilityDay]:
    """Deux jours, le second avec les segments donnés."""
    return [build_day(FIRST), replace(build_day(SECOND), segments=segments)]


def _second_with_edge(
    regime: str = "ascent",
    *,
    nominal: tuple[float, float] | None = None,
    effective: tuple[float, float] | None = None,
) -> list[RepeatabilityDay]:
    """Deux jours, le second avec, à la place de sa cellule 0, un bord ancré d'indice
    0 (§ 7.0)."""
    edge = anchored_segment(0, regime, nominal=nominal, effective=effective)
    return _second_with(edge, *segments_of(SECOND)[1:])


# ---------------------------------------------------------------------------
# Préconditions (test 7)
# ---------------------------------------------------------------------------

SHORT_CELL = replace(
    cell_segment(1, "ascent", tm(305)),
    nominal_end_m=499.0,
    end_m=499.0,
    realized_end_m=499.0,
)
"""Une cellule d'indice 1 de bornes nominales ``[250 ; 499]`` (le premier jour :
``[250 ; 500]``)."""

REFUSED: Mapping[str, tuple[list[RepeatabilityDay], int, str]] = {
    "autre référence": (
        [build_day(FIRST), build_day(SECOND, OTHER_REFERENCE)],
        10,
        "le jour 2026-05-27 a une autre référence",
    ),
    "même date": (
        [build_day(FIRST), build_day(FIRST)],
        10,
        "deux jours à la date 2026-05-20",
    ),
    "classe incohérente": (
        _second_with(cell_segment(0, "descent", tm(171))),
        10,
        "l'indice 0 a deux classes sur ses cellules",
    ),
    "bornes incohérentes": (
        _second_with(SHORT_CELL),
        10,
        "l'indice 1 a deux couples de bornes nominales",
    ),
    "max_iterations=0": (days_of(DEUX_JOURS), 0, "max_iterations doit être >= 1"),
    "multi-sorties sous une autre référence": (
        [*days_of(DEUX_JOURS), build_day(MULTI_DAY, OTHER_REFERENCE)],
        10,
        "le jour 2026-05-24 a une autre référence",
    ),
    "multi-sorties à la date d'un jour éligible": (
        [*days_of(DEUX_JOURS), build_day(replace(MULTI_DAY, date="2026-05-20"))],
        10,
        "deux jours à la date 2026-05-20",
    ),
    "bord ancré de bornes incohérentes": (
        _second_with_edge(nominal=(0.0, 249.0), effective=(5.0, 249.0)),
        10,
        "l'indice 0 a deux couples de bornes nominales",
    ),
}
"""Les huit jeux refusés du test 7, sur les jours de Deux jours."""


@pytest.mark.parametrize("name", list(REFUSED))
def test_refused_inputs_raise_value_error_exactly(name: str) -> None:
    """Choix 5 du brief : chaque jeu refusé lève ``ValueError`` exactement, jamais
    ``ContractError``, avec le message de sa précondition — dates distinctes et même
    référence pour tous les jours, multi-sorties compris ; un indice, un seul couple
    de bornes nominales sur tous ses segments (bords ancrés compris) et une seule
    classe sur ses cellules (précision de D8.1)."""
    days, max_iterations, message = REFUSED[name]
    with pytest.raises(ValueError, match=message) as raised:
        repeatability_reference(REFERENCE, days, max_iterations=max_iterations)
    assert raised.type is ValueError


def test_anchored_edge_class_is_not_compared() -> None:
    """Précision de D8.1, choix 1 : la classe d'un bord ancré se calcule sur ses
    bornes effectives et n'est pas comparée à celle de la cellule de même indice ; elle
    n'entre nulle part (référence égale à celle d'un bord en montée)."""
    mixed = repeatability_reference(REFERENCE, _second_with_edge("mixed"))
    ascent = repeatability_reference(REFERENCE, _second_with_edge("ascent"))
    assert mixed == ascent


def _assert_empty(reference: RepeatabilityReference) -> None:
    assert reference.days == ()
    assert reference.single_contrast is False
    assert tuple(c.clock for c in reference.clocks) == CLOCKS
    absent = MetricValue(None, INSUF, 0)
    for clock_reference in reference.clocks:
        assert clock_reference.folds == ()
        assert clock_reference.level == absent
        assert clock_reference.log_ratios == (absent,) * 4
        assert clock_reference.dispersions == (absent,) * 4


def test_no_day() -> None:
    """§ 6.4 : aucun jour, onze horloges, aucun pli, tous les ``F`` en ``support
    insuffisant`` d'effectif 0."""
    reference = repeatability_reference(REFERENCE, [])
    _assert_empty(reference)
    assert reference.multi_outing_days == ()


def test_only_a_multi_outing_day() -> None:
    """``0010`` D8.1 : un jour multi-sorties est exclu et publié ; seul, la référence
    est vide."""
    reference = repeatability_reference(REFERENCE, [build_day(MULTI_DAY)])
    _assert_empty(reference)
    assert [str(d) for d in reference.multi_outing_days] == ["2026-05-24"]


# ---------------------------------------------------------------------------
# Erreur du modèle et μ₂ non certifié (test 10)
# ---------------------------------------------------------------------------

ORIGINAL_FIT = repeatability_module.two_way_fit
FitFunction = Callable[[Mapping[tuple[int, int], float], int], TwoWayFit]


def _shifted_ascent(delta: float) -> FitFunction:
    """``two_way_fit`` d'origine, ``delta`` ajouté à chaque ``a_k`` quand les cellules
    sont celles de la montée de Complet (indices 0 à 2)."""

    def fit(
        log_times: Mapping[tuple[int, int], float], max_iterations: int
    ) -> TwoWayFit:
        result = ORIGINAL_FIT(log_times, max_iterations)
        if {k for _, k in log_times} != {0, 1, 2}:
            return result
        effects = tuple((k, a + delta) for k, a in result.segment_effects)
        return replace(result, segment_effects=effects)

    return fit


@pytest.mark.parametrize("delta", [800.0, -800.0], ids=["débordement", "nulle"])
def test_model_error(monkeypatch: pytest.MonkeyPatch, delta: float) -> None:
    """Précisions de D8.3 et D8.4, § 6.4 étape 4.7 : ``exp(a_k)`` non fini (le
    débordement de ``math.exp``, ``OverflowError``, rattrapé) ou nul donne ``erreur du
    modèle`` pour le pli et la classe — sans exception ; l'ajustement garde ses
    itérations, ses résidus et ``μ₂`` ; ``P_j`` exclut la classe, ``|L|`` strict
    prend son motif ; les autres classes et leurs ``F`` ne changent pas."""
    original = repeatability_reference(REFERENCE, days_of(COMPLET))
    monkeypatch.setattr(repeatability_module, "two_way_fit", _shifted_ascent(delta))
    reference = repeatability_reference(REFERENCE, days_of(COMPLET))
    for clock_reference, expected in zip(
        reference.clocks, original.clocks, strict=True
    ):
        for fold, expected_fold in zip(
            clock_reference.folds, expected.folds, strict=True
        ):
            ascent, expected_ascent = fold.fits[0], expected_fold.fits[0]
            assert ascent.unavailability is ERR
            assert ascent.iterations == expected_ascent.iterations
            assert ascent.residuals == expected_ascent.residuals
            assert ascent.iterations is not None
            assert ascent.contraction == expected_ascent.contraction
            assert fold.fits[1:] == expected_fold.fits[1:]
            assert fold.level == MetricValue(None, ERR, 9)
            assert (fold.support_count, fold.predicted_count) == (9, 6)
            assert [k for k, _ in fold.forecast_s] == [3, 4, 5, 6, 7, 8]
            error = MetricValue(None, ERR, 3)
            assert (fold.classes[0].log_ratio, fold.classes[0].dispersion) == (
                error,
                error,
            )
            assert not fold.classes[0].contributes
            assert fold.classes[1:] == expected_fold.classes[1:]
        absent = MetricValue(None, INSUF, 0)
        assert clock_reference.log_ratios[0] == absent
        assert clock_reference.dispersions[0] == absent
        assert clock_reference.log_ratios[1:] == expected.log_ratios[1:]
        assert clock_reference.dispersions[1:] == expected.dispersions[1:]
        assert clock_reference.level == absent


def test_uncertified_contraction(monkeypatch: pytest.MonkeyPatch) -> None:
    """Précision de D8.3, § 6.4 étape 4.4 : un calcul de ``μ₂`` non certifié le publie
    indisponible (``non-convergence``), jamais ``0`` ; il ne change aucun statut —
    itérations, scores et ``F`` égaux à ceux de la référence d'origine (Variantes)."""
    original = repeatability_reference(REFERENCE, days_of(VARIANTES))

    def uncertified(cells: object, max_sweeps: int = 50) -> float | None:
        return None

    monkeypatch.setattr(repeatability_module, "contraction_rate", uncertified)
    reference = repeatability_reference(REFERENCE, days_of(VARIANTES))
    with_component = 0
    for clock_reference, expected in zip(
        reference.clocks, original.clocks, strict=True
    ):
        assert clock_reference.level == expected.level
        assert clock_reference.log_ratios == expected.log_ratios
        assert clock_reference.dispersions == expected.dispersions
        for fold, expected_fold in zip(
            clock_reference.folds, expected.folds, strict=True
        ):
            assert replace(fold, fits=expected_fold.fits) == expected_fold
            for fit, expected_fit in zip(fold.fits, expected_fold.fits, strict=True):
                if expected_fit.unavailability in (INSUF, UNIDENTIFIED):
                    assert fit == expected_fit
                    continue
                with_component += 1
                assert fit.contraction is None
                assert fit.contraction_unavailability is NON_CONV
                restored = replace(
                    fit,
                    contraction=expected_fit.contraction,
                    contraction_unavailability=None,
                )
                assert restored == expected_fit
    assert with_component > 0
