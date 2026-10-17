"""Les valeurs des fourchettes au rapport (``0010`` D11 et D15, leurs précisions de
M4d-2) : ``band_values``, ``band_table``, ``band_common_row``, ``band_window_counts``.

Les entrées du rapport sont des ``ScoredPerformance`` construites ici, leurs
fourchettes des ``OutingBands`` valides des aides de ``test_schemas_bands.py`` ; les
scores portés sont ceux d'une sortie du registre (``fixtures.registry``), que les
fonctions testées ne lisent pas au-delà de leur présence. Aucune donnée réelle.
"""

import math
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from fixtures.backtest_world import run_world
from fixtures.registry import v0_of
from mountain_perf.backtest import (
    NO_REFERENCE,
    NOT_SCORED,
    REPORT_MODELS,
    SINGLE_RESIDUAL,
    Aggregate,
    BacktestRun,
    BandMetric,
    ScoredPerformance,
    band_common_row,
    band_table,
    band_values,
    band_window_counts,
    load_outcomes,
    read_registry,
    scored_performances,
)
from mountain_perf.schemas import (
    BAND_MODELS,
    DataSet,
    ModelBand,
    ModelKind,
    OutingBands,
    Unavailability,
)
from test_schemas_bands import band, bands

U = Unavailability
SCORES = v0_of("q-2026-05-20")
DEV, CONF = DataSet.DEVELOPMENT, DataSet.CONFIRMATION
METRICS = tuple(BandMetric)


def _entry(
    day: int,
    value: OutingBands | None,
    datasets: tuple[DataSet, ...] = (DEV,),
    missing: str | None = None,
) -> ScoredPerformance:
    """Une performance du rapport : son jour (juin 2026), ses jeux, des scores
    (``missing`` absent) ou le motif qui les remplace, ses fourchettes."""
    scores = None if missing is not None else SCORES
    return ScoredPerformance(
        date(2026, 6, day), datasets, (), scores, (), missing, (), None, value
    )


def _with(index: int, model_band: ModelBand) -> OutingBands:
    """Les fourchettes valides de ``bands()``, le modèle de rang ``index`` remplacé."""
    base = bands()
    models = list(base.models)
    models[index] = model_band
    return replace(base, models=tuple(models))


def _numbers(value: OutingBands, index: int) -> dict[BandMetric, float]:
    """Les cinq métriques d'un modèle, lues sur ses fourchettes."""
    model = value.models[index]
    cells = {
        BandMetric.INTERVAL_SCORE: model.interval_score_s,
        BandMetric.NORMALISED_SCORE: model.normalised_score,
        BandMetric.COVERAGE: model.coverage,
        BandMetric.MEDIAN_USAGE_TARGET: model.median_usage_target,
        BandMetric.MEDIAN_MAX_ABS_ERROR: model.median_max_abs_error_s,
    }
    numbers: dict[BandMetric, float] = {}
    for metric, cell in cells.items():
        assert cell is not None
        assert cell.value is not None
        numbers[metric] = cell.value
    return numbers


# ---------------------------------------------------------------------------
# band_values
# ---------------------------------------------------------------------------


def test_metrics_in_the_order_of_d11() -> None:
    """Précision de D11 (« Agrégats ») : ``IS_j``, ``IS_j,norm``, la couverture, le
    ``q_usage`` et le ``max |C_k|`` de la médiane ; les modèles du rapport sont ceux
    des fourchettes, dans le même ordre."""
    assert [m.value for m in BandMetric] == [
        "interval_score_s",
        "normalised_score",
        "coverage",
        "median_q_usage",
        "median_max_abs_passage_error_s",
    ]
    assert tuple(REPORT_MODELS) == BAND_MODELS


def test_values_of_a_performance_without_bands() -> None:
    """Le motif de la performance l'emporte (``jour multi-sorties`` : hors des
    agrégats, D0) ; une performance non scorée, ``not_scored`` ; une sortie scorée
    sans référence, ``no_reference`` ; pour chaque modèle et chaque métrique — le motif
    de la performance l'emporte même sur des scores et des fourchettes présents."""
    multi = U.MULTI_OUTING_DAY.value
    masked = ScoredPerformance(
        date(2026, 6, 2), (DEV,), (), SCORES, (), multi, (), None, bands()
    )
    cases = (
        (_entry(3, bands(), missing=multi), multi),
        (masked, multi),
        (_entry(4, None, missing=NOT_SCORED), NOT_SCORED),
        (_entry(5, None), NO_REFERENCE),
    )
    for entry, motif in cases:
        for model in REPORT_MODELS:
            assert band_values(entry, model) == dict.fromkeys(METRICS, motif)


def test_values_follow_the_band_of_each_model() -> None:
    """Chaque modèle lit sa propre fourchette (``models[rang]``) : ses cinq métriques,
    nombres de ses ``MetricValue`` ; v0 brut et les modèles calés n'ont pas les mêmes
    valeurs (``P_k`` différents)."""
    value = bands()
    entry = _entry(3, value)
    for index, model in enumerate(REPORT_MODELS):
        assert band_values(entry, model) == _numbers(value, index)
    assert _numbers(value, 0) != _numbers(value, 1)


def test_values_of_a_band_without_bounds() -> None:
    """Une fourchette sans bornes donne son statut à ses cinq métriques : ``non calé``
    (quantiles publiés), ``support insuffisant`` (aucun résidu), ``erreur du
    modèle``."""
    cases = (
        (band(model=ModelKind.NAISMITH, status=U.NOT_CALIBRATED), U.NOT_CALIBRATED),
        (
            band([U.NOT_CALIBRATED] * 3, model=ModelKind.NAISMITH),
            U.INSUFFICIENT_SUPPORT,
        ),
        (
            band([0.1, U.MODEL_ERROR, 0.0], model=ModelKind.NAISMITH),
            U.MODEL_ERROR,
        ),
    )
    for model_band, status in cases:
        entry = _entry(3, _with(3, model_band))
        assert band_values(entry, ModelKind.NAISMITH) == dict.fromkeys(
            METRICS, status.value
        )


def test_values_of_a_single_residual_and_of_an_unobserved_element() -> None:
    """``n = 1`` : la couverture vaut ``single_residual``, les quatre autres sont des
    nombres ; un élément non observé : ``IS_j``, ``IS_j,norm`` et la couverture au
    motif de l'élément, la médiane en nombres."""
    single = band(
        [0.05, U.NOT_CALIBRATED, U.NOT_CALIBRATED],
        model=ModelKind.TOBLER,
        forecasts=(380.0, 950.0),
        bases=(400.0, 1000.0),
    )
    values = band_values(_entry(3, _with(4, single)), ModelKind.TOBLER)
    assert values[BandMetric.COVERAGE] == SINGLE_RESIDUAL
    others = [values[m] for m in METRICS if m is not BandMetric.COVERAGE]
    assert all(isinstance(v, float) for v in others)
    unobserved = bands(
        models=tuple(
            band(
                model=kind,
                forecasts=(400.0, 1000.0)
                if kind is ModelKind.V0_RAW
                else (380.0, 950.0),
                bases=(400.0, 1000.0),
                observed=(420.0, None),
            )
            for kind in BAND_MODELS
        )
    )
    values = band_values(_entry(3, unobserved), ModelKind.V0_RAW)
    absent = U.ABSENT.value
    assert values[BandMetric.INTERVAL_SCORE] == absent
    assert values[BandMetric.NORMALISED_SCORE] == absent
    assert values[BandMetric.COVERAGE] == absent
    assert isinstance(values[BandMetric.MEDIAN_USAGE_TARGET], float)
    assert isinstance(values[BandMetric.MEDIAN_MAX_ABS_ERROR], float)


# ---------------------------------------------------------------------------
# band_table, band_common_row
# ---------------------------------------------------------------------------


def _entries() -> list[ScoredPerformance]:
    """Quatre performances : deux de développement à bornes (la seconde, Naismith
    ``non calé``), une de développement et confirmation à bornes, une de
    développement sans référence."""
    naismith = band(model=ModelKind.NAISMITH, status=U.NOT_CALIBRATED)
    return [
        _entry(3, bands()),
        _entry(4, _with(3, naismith)),
        _entry(5, bands(), datasets=(DEV, CONF)),
        _entry(6, None),
    ]


def test_table_means_each_set_on_its_own_count() -> None:
    """D15 : par métrique, par jeu (ordre de ``DataSet``) et par modèle, la moyenne à
    poids égal par performance (``fsum`` sur l'effectif), les manquants comptés par
    motif ; un jeu sans performance, ``— (0)``."""
    entries = _entries()
    table = band_table(entries)
    assert [row.metric for row in table] == list(BandMetric)
    sets = list(DataSet)
    full = _numbers(bands(), 0)
    for row in table:
        repeat, development, confirmation = (
            row.by_set[sets.index(s)] for s in (DataSet.REPEATABILITY, DEV, CONF)
        )
        assert repeat == tuple(Aggregate(None, 0, ()) for _ in REPORT_MODELS)
        v0 = full[row.metric]
        assert development[0] == Aggregate(
            math.fsum([v0] * 3) / 3, 3, ((NO_REFERENCE, 1),)
        )
        assert development[3].count == 2
        assert development[3].missing == (
            (U.NOT_CALIBRATED.value, 1),
            (NO_REFERENCE, 1),
        )
        assert confirmation[0] == Aggregate(v0, 1, ())


def test_common_row_keeps_performances_with_five_values() -> None:
    """Précision de D11 : ``IS_j,norm`` sur l'ensemble commun de chaque jeu — les
    performances où les cinq modèles ont un nombre ; même effectif pour les cinq."""
    entries = _entries()
    rows = band_common_row(entries, BandMetric.NORMALISED_SCORE)
    development = rows[list(DataSet).index(DEV)]
    assert [cell.count for cell in development] == [2] * 5
    assert all(cell.missing == () for cell in development)
    expected = _numbers(bands(), 3)[BandMetric.NORMALISED_SCORE]
    assert development[3].value == math.fsum([expected] * 2) / 2
    confirmation = rows[list(DataSet).index(CONF)]
    assert [cell.count for cell in confirmation] == [1] * 5


# ---------------------------------------------------------------------------
# band_window_counts
# ---------------------------------------------------------------------------


def test_window_counts_count_available_residuals() -> None:
    """Précision de D11 : ``n`` se lit dans / hors de la fenêtre sur les résidus
    **disponibles** — un membre dans la fenêtre au résidu indisponible n'y compte pas.
    Les membres de ``bands()`` : deux dans la fenêtre, le troisième hors."""
    naismith = band([0.1, U.NOT_CALIBRATED, 0.0], model=ModelKind.NAISMITH)
    value = _with(3, naismith)
    assert [m.in_window for m in value.members] == [True, True, False]
    assert band_window_counts(value, value.models[0]) == (2, 1)
    assert band_window_counts(value, value.models[3]) == (1, 1)


# ---------------------------------------------------------------------------
# Le monde de M4b-5 : l'exécution garde ses fourchettes
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, BacktestRun]:
    root = tmp_path_factory.mktemp("monde")
    return root, run_world(root)


def test_run_keeps_the_bands_of_its_result(world: tuple[Path, BacktestRun]) -> None:
    """L'exécution rend les fourchettes de son RÉSULTAT (``BacktestRun.bands``) : une
    par sortie scorée avec usage, dans l'ordre, égales à celles que le registre relit ;
    le rapport les attache à chaque performance d'une sortie
    (``scored_performances``)."""
    root, run = world
    registry = root / "registre"
    log = read_registry(registry)
    number = log.events[-1].number
    stored = [o.bands for o in load_outcomes(registry, log, number)]
    with_usage = [o.outing.outing_id for o in run.outings if o.scores.usage is not None]
    assert [b.outing_id for b in run.bands] == with_usage
    assert list(run.bands) == [b for b in stored if b is not None]
    for entry in scored_performances(run):
        if entry.missing is None and entry.scores is not None:
            assert entry.bands in (*run.bands, None)
    assert any(e.bands is not None for e in scored_performances(run))
