"""Valeurs de la référence de répétabilité (§§ 6.4, 7.3 et § 8.1, tests 4 et 5, du
brief M4b-3 ; ``0010`` D8 et ses précisions de M4b-3, D5.5, D7.5).

Un test par cas du § 7.2, nommé par le cas : les jours éligibles, les jours
multi-sorties et « un seul contraste » de l'en-tête (précision 1 de la relecture du
plan) ; chaque champ des lignes de pli sous ``E`` (``CLOCKS[0]``) et ``M θ1``
(``CLOCKS[1]``), classes absentes de la ligne comprises ; les ``F`` sous
``CLOCKS[0]``, ``[1]``, ``[3]``, ``[8]``. Horloges et plis lus **par position** —
lus par clé, un ordre inversé passerait, contrats neutralisés. Puis les trois tests
nommés (Total nul non vu, Zéros croisés, Jour isolé) et Lent limité.

Valeurs de l'oracle (``fixtures.repeatability_values``), tolérance
``1e−6·max(1, |x|)`` (§ 7.0) ; le reste exact, dont les nombres d'itérations.
"""

from fixtures.repeatability import (
    CASE_NAMES,
    DEUX_JOURS,
    JOUR_ISOLE,
    REFERENCE,
    TOTAL_NUL_NON_VU,
    ZEROS_CROISES,
    case_reference,
    close,
    days_of,
)
from fixtures.repeatability_values import (
    ORACLE_LINES,
    VALUES,
    Fit,
    Fold,
    Fq,
    Row,
    Value,
    render_fold,
    render_header,
    render_row,
)
from mountain_perf.backtest import repeatability_reference
from mountain_perf.schemas import (
    CLOCKS,
    ClassFit,
    ClassScore,
    ClockReference,
    FoldScores,
    MetricValue,
    RegimeClass,
    Unavailability,
)

INSUF = Unavailability.INSUFFICIENT_SUPPORT
ZERO = Unavailability.ZERO_TIME
UNIDENTIFIED = Unavailability.UNIDENTIFIED_REFERENCE
NON_CONV = Unavailability.NON_CONVERGENCE
MOVING = range(1, 6)
"""Les cinq ``M_θ`` dans ``CLOCKS``."""


def test_oracle_lines_are_read_whole() -> None:
    """Le lecteur des valeurs lit chaque ligne du § 7.3 en entier : réécrite, elle est
    identique au caractère près (16 en-têtes, 90 plis, 64 lignes de tableau)."""
    folds = rows = 0
    for name, case in VALUES.items():
        lines = ORACLE_LINES[name]
        assert render_header(case) == lines["header"][0]
        for clock, key in ((0, "E"), (1, "M1")):
            assert len(case.folds[clock]) == len(lines[key])
            for fold, line in zip(case.folds[clock], lines[key], strict=True):
                assert render_fold(fold) == line
                folds += 1
        assert tuple(case.table) == (0, 1, 3, 8)
        for line, (clock, row) in zip(lines["table"], case.table.items(), strict=True):
            assert render_row(clock, row) == line
            rows += 1
    assert (len(VALUES), folds, rows) == (16, 90, 64)


# ---------------------------------------------------------------------------
# Comparaison à l'oracle
# ---------------------------------------------------------------------------


def _check_value(metric: MetricValue, expected: Value, count: int) -> None:
    assert metric.count == count
    if isinstance(expected, Unavailability):
        assert metric.value is None
        assert metric.unavailability is expected
    else:
        assert metric.unavailability is None
        assert close(metric.value, expected), (metric.value, expected)


def _check_class(fit: ClassFit, score: ClassScore, expected: Fit | None) -> None:
    """Une classe d'un pli : ``ClassFit`` et ``ClassScore``. Absente de la ligne :
    aucune cellule du jour retiré, ``insufficient_support`` d'effectif 0."""
    regime = fit.regime_class
    if expected is None:
        assert fit == ClassFit(regime, INSUF, 0, 0, 0, 0, 0, (), None, None, None, None)
        absent = MetricValue(None, INSUF, 0)
        assert score == ClassScore(regime, 0, absent, absent, False)
        return
    assert expected.regime is regime
    assert fit.unavailability is expected.motif
    assert (fit.seen_count, fit.left_count) == (expected.seen, expected.left)
    training = (fit.training_days, fit.training_segments, fit.training_cells)
    assert training == (expected.training or (0, 0, 0))
    if expected.contraction is None:
        assert fit.contraction is None
    else:
        assert close(fit.contraction, expected.contraction)
        if fit.training_days == 1:
            assert fit.contraction == 0.0
    assert fit.contraction_unavailability is None
    assert fit.zero_cells == expected.zero_cells
    assert fit.iterations == expected.iterations
    assert (fit.residuals is None) == (expected.iterations is None)
    assert score.regime_class is regime
    assert score.segment_count == expected.seen
    if expected.seen == 0:
        absent = MetricValue(None, INSUF, 0)
        assert (score.log_ratio, score.dispersion) == (absent, absent)
    else:
        assert expected.log_ratio is not None
        assert expected.dispersion is not None
        _check_value(score.log_ratio, expected.log_ratio, expected.seen)
        _check_value(score.dispersion, expected.dispersion, expected.seen)
    assert score.contributes is expected.contributes


def _check_fold(fold: FoldScores, expected: Fold) -> None:
    assert fold.day == expected.day
    assert (fold.support_count, fold.predicted_count) == (
        expected.support,
        expected.predicted,
    )
    _check_value(fold.level, expected.level, expected.support)
    written = {fit.regime: fit for fit in expected.classes}
    assert [fit.regime for fit in expected.classes] == [
        regime for regime in RegimeClass if regime in written
    ]
    for fit, score in zip(fold.fits, fold.classes, strict=True):
        _check_class(fit, score, written.get(fit.regime_class))


def _check_f(metric: MetricValue, expected: Fq) -> None:
    assert metric.count == expected.count
    if expected.value is None:
        assert metric.value is None
        assert metric.unavailability is expected.motif
    else:
        assert metric.unavailability is None
        assert close(metric.value, expected.value), (metric.value, expected.value)


def _check_row(reference: ClockReference, row: Row) -> None:
    _check_f(reference.level, row.level)
    for i, (log_ratio, dispersion) in enumerate(row.classes):
        _check_f(reference.log_ratios[i], log_ratio)
        _check_f(reference.dispersions[i], dispersion)


def _check_case(name: str) -> None:
    """Un cas du § 7.3 : en-tête, plis sous ``E`` et ``M θ1``, tableau des ``F`` ;
    horloges et plis par position."""
    reference = case_reference(name)
    expected = VALUES[name]
    assert reference.days == expected.days
    assert reference.multi_outing_days == expected.multi_outing_days
    assert reference.single_contrast is expected.single_contrast
    assert len(reference.clocks) == len(CLOCKS)
    for clock, folds in expected.folds.items():
        published = reference.clocks[clock].folds
        assert len(published) == len(folds) == len(expected.days)
        for fold, expected_fold in zip(published, folds, strict=True):
            _check_fold(fold, expected_fold)
    for clock, row in expected.table.items():
        _check_row(reference.clocks[clock], row)
    for clock_reference in reference.clocks:
        assert tuple(fold.day for fold in clock_reference.folds) == expected.days
    assert (
        tuple(clock_reference.clock for clock_reference in reference.clocks) == CLOCKS
    )


# ---------------------------------------------------------------------------
# Les cas (test 4)
# ---------------------------------------------------------------------------


def test_complet() -> None:
    """Plan complet : 2 itérations, ``μ₂ = 0``, ``F`` de classe sur trois segments
    (montée, descente), plat de deux segments et mixte d'un segment publiés sans
    contribuer (précision de D8.4, D7.5) ; ``L`` et ``E_R`` signés par pli, ``F`` sur
    leurs valeurs absolues (choix 6)."""
    _check_case("Complet")


def test_variantes() -> None:
    """Couvertures partielles, une composante par classe, ``μ₂`` non nuls ; segment
    vu par le seul dernier jour, hors ``S_j`` (précision de D8.2) ; bord ancré, jamais
    cellule (précision de D8.1, choix 1)."""
    _check_case("Variantes")


def test_deux_composantes() -> None:
    """Montée vue dans deux composantes : ``référence non identifiée`` (D8.2) ;
    ``|L|`` strict (décision 5) ; descente à un jour d'apprentissage (``μ₂ == 0``) ;
    cellule nulle d'une autre composante, ignorée (précision de D8.2) ; jour sans
    segment vu."""
    _check_case("Deux composantes")


def test_zeros() -> None:
    """Temps nul du jour retiré sur ``S_j`` : propagé à toutes les classes (D5.5,
    décision 6) ; cellule nulle d'apprentissage : ``temps nul``, cellules publiées
    (D8.3, décision 4) ; cellule nulle hors ``S_j``, sans effet ; ``F`` absent en
    ``support insuffisant``."""
    _check_case("Zéros")


def test_zero_retire() -> None:
    """Seul le jour retiré a un temps nul : ajustement réussi, ``L`` calculable,
    régimes ``temps nul`` (D5.5) ; ``F`` d'un seul pli : indisponible (D8.4)."""
    _check_case("Zéro retiré")


def test_zero_hors_pli() -> None:
    """Cellule nulle dans la composante ajustée sans que le jour retiré voie son
    segment : ``temps nul`` (précision de D8.3) ; ``μ₂`` du plan, cellule nulle
    comprise."""
    _check_case("Zéro hors pli")


def test_deux_echecs() -> None:
    """Deux classes en échec : le motif de ``L`` est celui de la première dans l'ordre
    montée, plat, descente, mixte (précision de D8.4)."""
    _check_case("Deux échecs")


def test_total_nul() -> None:
    """Total nul sur ``S_j`` avant l'échec d'une classe (priorité de ``L``,
    précision de D8.4) ; cellules nulles de la composante, toutes publiées."""
    _check_case("Total nul")


def test_nulle_non_identifiee() -> None:
    """Montée vue dans deux composantes dont l'une porte une cellule nulle :
    ``référence non identifiée`` — l'identification précède la cellule nulle
    (précisions de D8.2, D8.3)."""
    _check_case("Nulle non identifiée")


def test_deux_jours() -> None:
    """Un seul contraste (précision de D8.4) ; ``S_jR`` plus petit que les cellules du
    jour retiré (D8.2)."""
    _check_case("Deux jours")


def test_multi_sorties() -> None:
    """Le jour multi-sorties exclu et publié (D8.1)."""
    _check_case("Multi-sorties")


def test_lent() -> None:
    """Convergence lente : ``μ₂`` de 0,73 à 0,86, itérations exactes (D8.3, choix 3)."""
    _check_case("Lent")


def test_vide() -> None:
    """Aucun jour : onze horloges, aucun pli, ``F`` en ``support insuffisant``
    d'effectif 0."""
    _check_case("Vide")


def test_un_jour() -> None:
    """Un seul jour : aucun segment vu à l'apprentissage, ``support insuffisant``
    partout (précision de D8.2)."""
    _check_case("Un jour")


def test_disjoints() -> None:
    """Deux jours sans cellule commune : aucun segment vu, pas de contraste
    (précision de D8.4)."""
    _check_case("Disjoints")


# ---------------------------------------------------------------------------
# Les trois tests nommés (test 4)
# ---------------------------------------------------------------------------


def test_total_nul_non_vu() -> None:
    """Précision de D8.4 : le total nul se prend sur ``S_j``, pas sur toutes les
    cellules du jour retiré — sous les cinq ``M_θ``, ``L`` du ``2026-09-03`` est
    ``temps nul`` (son segment 5, de temps positif, n'est vu par personne) ; sous les
    six autres horloges, ``référence non identifiée``."""
    reference = repeatability_reference(REFERENCE, days_of(TOTAL_NUL_NON_VU))
    for index, clock_reference in enumerate(reference.clocks):
        fold = clock_reference.folds[2]
        assert str(fold.day) == "2026-09-03"
        motif = ZERO if index in MOVING else UNIDENTIFIED
        assert fold.level == MetricValue(None, motif, 2)
        ascent, flat = fold.fits[0], fold.fits[1]
        assert ascent.unavailability is UNIDENTIFIED
        assert (ascent.seen_count, ascent.left_count) == (2, 2)
        assert flat.unavailability is INSUF
        assert (flat.seen_count, flat.left_count) == (0, 1)


def test_zeros_croises() -> None:
    """Précision de D8.3 : les cellules nulles se publient triées par ``(date, k)`` —
    ``(2026-08-21, 5)`` avant ``(2026-08-22, 3)``."""
    reference = repeatability_reference(REFERENCE, days_of(ZEROS_CROISES))
    for index in MOVING:
        fold = reference.clocks[index].folds[2]
        assert str(fold.day) == "2026-08-23"
        descent = fold.fits[2]
        assert descent.unavailability is ZERO
        assert [(str(day), k) for day, k in descent.zero_cells] == [
            ("2026-08-21", 5),
            ("2026-08-22", 3),
        ]


def test_jour_isole() -> None:
    """Précision de D8.4 : un jour qui ne partage aucune cellule ne compte pas pour
    « un seul contraste » ; il ne change ni les ``F`` ni les plis des deux autres."""
    reference = repeatability_reference(REFERENCE, days_of(JOUR_ISOLE))
    two_days = repeatability_reference(REFERENCE, days_of(DEUX_JOURS))
    assert reference.single_contrast
    for clock_reference, expected in zip(
        reference.clocks, two_days.clocks, strict=True
    ):
        assert clock_reference.level == expected.level
        assert clock_reference.log_ratios == expected.log_ratios
        assert clock_reference.dispersions == expected.dispersions
        assert clock_reference.folds[:2] == expected.folds
        isolated = clock_reference.folds[2]
        assert (isolated.support_count, isolated.predicted_count) == (0, 0)
        assert isolated.level == MetricValue(None, INSUF, 0)
        ascent = isolated.fits[0]
        assert (ascent.seen_count, ascent.left_count) == (0, 1)


# ---------------------------------------------------------------------------
# Lent limité (test 5)
# ---------------------------------------------------------------------------


def test_lent_limite() -> None:
    """Précision de D8.3 : la limite atteinte sans certification, ``non-convergence``
    (``max_iterations=70``) — ``iterations == 70``, résidus publiés et non tous sous
    ``1e−8``, ``μ₂`` publié ; aucune contribution, ``F`` sur les deux autres plis."""
    _check_case("Lent limité")
    reference = case_reference("Lent limité")
    for clock_reference in reference.clocks:
        for fold in clock_reference.folds[:2]:
            ascent = fold.fits[0]
            assert ascent.unavailability is NON_CONV
            assert ascent.iterations == 70
            assert ascent.residuals is not None
            assert not all(value < 1e-8 for value in ascent.residuals)
            assert ascent.contraction is not None
            assert fold.forecast_s == ()
        for fold in clock_reference.folds[2:]:
            assert fold.fits[0].unavailability is None
        assert clock_reference.level.count == 2
        assert clock_reference.log_ratios[0].count == 2


def test_every_case_has_its_oracle() -> None:
    """Les seize cas du § 7.2 ont leurs valeurs au § 7.3, sous leur nom, dans le même
    ordre."""
    assert tuple(VALUES) == CASE_NAMES
