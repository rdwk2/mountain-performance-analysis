"""Garanties de la commande et de l'exécution glissantes (OG-2, § 6.7 à § 6.9) que la
suite de la PR #44 ne tenait pas : les contre-exemples de la relecture C du bloc 2
(constats A-1 à A-7), chacun vert sur la tête et rouge sous la mutation qu'il vise."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from fixtures.backtest_world import ATHLETE
from mountain_perf.backtest.rolling import ROLLING_ACTIVITY_TYPES
from mountain_perf.config import data_dir
from mountain_perf.estimation.origin import ALL_PAST
from mountain_perf.runs import load_curve_corpus
from mountain_perf.schemas import CurveStatus, FrozenCurve, ModelKind
from test_og1_origin import activity_pair
from test_og2_evaluation import evaluate
from test_og2_rolling import (
    FIRST_DAY,
    FORM_CHANGE,
    LAST_DAY,
    _frozen_with,
    activities,
    build_world,
    edit_manifest,
    fix_world,
    freeze_reads,
    journal,
    prepare,
    rolling,
)


@pytest.fixture(autouse=True)
def _world(monkeypatch: pytest.MonkeyPatch) -> None:
    fix_world(monkeypatch)


def _reports() -> list[str]:
    folder = data_dir() / "rapports"
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def test_the_comparison_report_read_by_a_second_way(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§ 6.9 (b) 4 : la paire « 56 jours − 28 jours », sur les couvertes sous toutes :
    la moyenne des différences de ``|L|`` (``W_k − W_i``) et celle du ``q_usage`` à
    dénominateur commun (``P⁽⁰⁾`` de tout le passé), recalculées ici depuis les entrées
    du rapport ; puis, au rapport D15 de 28 jours, le compte de l'ensemble « au-delà du
    repère »."""
    from mountain_perf import cli
    from mountain_perf.backtest.report import (
        ClockRole,
        ReportMetric,
        command_sets,
        common_usage_target,
        paired_difference,
        performance_values,
        rolling_scored_performances,
        usage_elements,
        window_sets,
    )
    from mountain_perf.backtest.rolling import run_rolling
    from mountain_perf.schemas import Scenario
    from test_og2_evaluation import RECORDED_AT

    freeze_reads(monkeypatch)
    manifest = build_world(tmp_path)
    preparation = prepare(manifest, [28, 56, ALL_PAST])
    runs = run_rolling(preparation, tmp_path / "glissant", recorded_at=RECORDED_AT)
    text = "\n".join(cli._comparison_report(runs, preparation.common.manifest))

    def entries(run: Any) -> dict[Any, Any]:
        evaluation = run.evaluation
        found = rolling_scored_performances(
            evaluation.window.declaration,
            evaluation.outings,
            [(i.traced.outing.outing_id, i.traced.match) for i in evaluation.no_curve],
            evaluation.calibration,
            evaluation.bands,
        )
        return {e.civil_date: e for e in found}

    per_window = [entries(run) for run in runs]
    declarations = [run.evaluation.window.declaration for run in runs]
    days = [d.performance.civil_date for d in declarations[0].performances]
    rollings = [d.rolling for d in declarations]
    assert all(r is not None for r in rollings)
    sets = command_sets(days, [r for r in rollings if r is not None])
    key = (ReportMetric.ABS_LEVEL, None)

    def value(window: int, day: Any) -> Any:
        return performance_values(
            per_window[window][day], Scenario.USAGE, ClockRole.ELAPSED, ModelKind.V0_RAW
        )[key]

    couples = [
        (value(0, d), value(1, d))
        for d in sets.covered_under_all
        if not isinstance(value(0, d), str) and not isinstance(value(1, d), str)
    ]
    level = paired_difference(couples)
    common = []
    for d in sets.covered_under_all:
        scores = [per_window[w][d].scores for w in (0, 1, 2)]
        if any(s is None for s in scores):
            continue
        try:
            base = usage_elements(scores[2])[0]
            p_i, t_i = usage_elements(scores[0])
            p_k, t_k = usage_elements(scores[1])
        except ValueError:
            continue
        common.append(
            (common_usage_target(p_i, t_i, base), common_usage_target(p_k, t_k, base))
        )
    target = paired_difference(common)
    block = text.split("paire        56 jours − 28 jours")[1].split("commun (")[0]
    view = cli._rolling_view(runs[0].evaluation, preparation.common.manifest)
    assert declarations[0].rolling is not None
    beyond = len(window_sets(days, declarations[0].rolling).beyond)
    set_lines = cli._rolling_set_lines(view, cli._rolling_entries(view))
    assert f"|L| : n {level.count}, moyenne {level.mean:+.4f}" in block
    assert f"q_usage commun : n {target.count}, moyenne {target.mean:+.4f}" in block
    assert any(
        line.endswith(f"au-delà du repère : {beyond} performances")
        for line in set_lines
    )


def test_the_comparison_report_name_is_checked_before_any_write(
    tmp_path: Path,
) -> None:
    """§ 6.7 (a) : les noms des rapports prévus refusés s'ils existent, « puis le
    rapport de comparaison » ; avant tout écrit."""
    manifest = build_world(tmp_path)
    reports = data_dir() / "rapports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "comparaison-0004.txt").write_text("ancien\n", encoding="utf-8")
    outcome = rolling(manifest, "28,56")
    assert outcome.code == 1
    assert "rapports/comparaison-0004.txt existe déjà" in outcome.err
    assert journal() == b""


def test_the_given_order_is_the_order_of_the_runs(tmp_path: Path) -> None:
    """§ 6.7 (a) : « l'ordre donné est l'ordre des exécutions »."""
    from test_og2_rolling import declarations

    manifest = build_world(tmp_path)
    outcome = rolling(manifest, "all,28")
    assert outcome.code == 0, outcome.err
    windows = [d.rolling.window_days for d in declarations() if d.rolling]
    assert windows == [None, 28]


def test_the_default_diagnostic_support_threshold(tmp_path: Path) -> None:
    """§ 6.7 (a) : ``--rule-support-threshold`` (minutes, défaut
    ``DEFAULT_SUPPORT_THRESHOLD_MIN``, 10) ; le document de règle l'écrit."""
    from test_og2_rolling import declarations, document

    manifest = build_world(tmp_path)
    outcome = rolling(manifest, "28")
    assert outcome.code == 0, outcome.err
    (declared,) = declarations()
    assert declared.rolling is not None
    rule = document(declared.rolling.rule)
    assert rule["diagnostic_support_threshold_min"] == 10.0


def test_the_platform_written_by_another_way(tmp_path: Path) -> None:
    """§ 6.7 (b) 8 : ``platform`` = « {platform.system()} {platform.release()},
    Python {platform.python_version()} », recalculé ici sans ``platform_label``."""
    import platform

    from test_og2_rolling import declarations

    manifest = build_world(tmp_path)
    outcome = rolling(manifest, "28")
    assert outcome.code == 0, outcome.err
    (declared,) = declarations()
    assert declared.rolling is not None
    expected = (
        f"{platform.system()} {platform.release()}, Python {platform.python_version()}"
    )
    assert declared.rolling.platform == expected


def test_the_prefix_says_insufficient_support_before_no_curve() -> None:
    """Message du plan, point 1 (1) : « pour le préfixe, « aucun disponible » et « somme
    nulle des poids » (``insufficient_support``) avant » « sans courbe »."""
    from mountain_perf.backtest.metrics import usage_target
    from mountain_perf.schemas import Unavailability

    none_observed = usage_target(
        (100.0, 300.0),
        (100.0, 300.0),
        (None, None),
        (Unavailability.ABSENT, Unavailability.ABSENT),
        base_unavailability=Unavailability.NO_CURVE,
    )
    assert none_observed.q_usage_prefix.unavailability is (
        Unavailability.INSUFFICIENT_SUPPORT
    )
    assert none_observed.q_usage_prefix.count == 0
    zero_weight = usage_target(
        (100.0, 300.0),
        (100.0, 300.0),
        (110.0, None),
        (None, Unavailability.ABSENT),
        weights=(0.0, 1.0),
        base_unavailability=Unavailability.NO_CURVE,
    )
    assert zero_weight.q_usage_prefix.unavailability is (
        Unavailability.INSUFFICIENT_SUPPORT
    )


def test_the_rolling_row_is_the_declared_row_at_a_diagnostic_threshold_of_5(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§ 0, règle 2 : la ligne ``j`` est celle de l'exécution « courbe déclarée » avec
    le fichier de ``κ_j``, **aux mêmes modèles déclarés** (dont le seuil de lecture de
    v0). L'oracle de la PR ne tourne qu'au seuil des diagnostics de 10 min, égal à la
    lecture ; ici, 5 min, sur le cas de
    ``test_the_share_is_read_at_the_reading_threshold`` (W = 7, le 2026-06-03 : les
    parts à 5 et à 10 min diffèrent)."""
    from mountain_perf.backtest.rolling import RollingSettings
    from test_og2_evaluation import _scores, declared_mode

    freeze_reads(monkeypatch)
    manifest = build_world(tmp_path)
    preparation = prepare(manifest, [7], RollingSettings(0.1, 0.5, 5.0, 60.0))
    (evaluation,) = evaluate(preparation, tmp_path / "glissant")
    (window,) = preparation.windows
    performances = preparation.common.performances
    j = next(k for k, p in enumerate(performances) if p.civil_date == date(2026, 6, 3))
    curve = window.curves[j]
    assert curve.entry.status is CurveStatus.CURVE
    assert isinstance(curve.document, FrozenCurve)
    assert curve.entry.curve_ref is not None
    declared = declared_mode(
        manifest, curve.document, curve.entry.curve_ref.split("#")[0], tmp_path / "d"
    )
    ids = {o.outing_id for o in performances[j].outings}
    assert _scores(evaluation.outings, ids) == _scores(declared.outings, ids)
    assert evaluation.calibration[j] == declared.calibration[j]


def test_the_common_set_when_the_longer_window_loses_a_curve() -> None:
    """Piège 4 : le support n'est pas monotone en ``W``. Ici la performance du premier
    jour a une courbe sous 28 et 56 jours, aucune sous tout le passé (les données de
    ``test_beyond_without_curve_under_all_leaves_n``) : elle sort du commun."""
    from mountain_perf.backtest.report import command_sets
    from test_og2_format6 import absent_performance, no_read_performance
    from test_og2_report import DAYS, declared, share

    w28 = declared(share(0.7), share(0.6), share(0.05), share(0.05))
    w56 = declared(share(0.3), share(0.3), share(0.05), share(0.05))
    everything = declared(
        absent_performance(), share(0.2), share(0.05), no_read_performance()
    )
    assert command_sets(DAYS, [w28, w56, everything]).common == (DAYS[1], DAYS[2])


def test_the_common_set_with_the_real_windows() -> None:
    """Les trois DÉCLARATIONS portent leurs vraies fenêtres (28, 56, tout le passé) —
    le constructeur des tests écrit 56 partout — et le support n'est pas monotone dans
    les deux sens : le premier jour sans courbe sous tout le passé seulement, le
    dernier sous 28 jours seulement. Le commun : les deux jours du milieu."""
    from mountain_perf.backtest.report import command_sets
    from test_og2_format6 import absent_performance, rolling
    from test_og2_report import DAYS, MARKER, S, share

    def declared(window: int | None, *entries: Any) -> Any:
        return rolling(
            performances=entries,
            covered_threshold=S,
            beyond_marker=MARKER,
            window_days=window,
        )

    w28 = declared(28, share(0.05), share(0.05), share(0.05), absent_performance())
    w56 = declared(56, share(0.05), share(0.05), share(0.05), share(0.05))
    everything = declared(
        None, absent_performance(), share(0.05), share(0.05), share(0.05)
    )
    assert command_sets(DAYS, [w28, w56, everything]).common == (DAYS[1], DAYS[2])


def test_the_q_usage_of_calibrated_baselines_without_curve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§ 6.8 (d), piège 10 : sans courbe, le ``q_usage`` porte « sans courbe », jamais
    le dénominateur de repli — pour les scores non calés **et** pour les scores calés
    des baselines (``calibrate_performances`` reçoit ``base_unavailability``)."""
    from mountain_perf.backtest.rolling import RollingSettings

    freeze_reads(monkeypatch)
    manifest = build_world(tmp_path, activities(first=date(2026, 6, 3)))
    preparation = prepare(manifest, [28], RollingSettings(0.1, 0.5, 5.0, 60.0))
    (window,) = preparation.windows
    performances = preparation.common.performances
    j = next(k for k, p in enumerate(performances) if p.civil_date == date(2026, 6, 14))
    assert window.curves[j].entry.status is not CurveStatus.CURVE
    (evaluation,) = evaluate(preparation, tmp_path / "glissant")
    first = performances[j].outings[0].outing_id
    seen = []
    for entry in evaluation.calibration[j].outings:
        if entry.outing_id != first or entry.usage is None:
            continue
        for clock in entry.usage.clocks:
            if clock.scores is None or clock.scores.usage_target is None:
                continue
            target = clock.scores.usage_target.q_usage
            seen.append(
                (str(entry.control.model), target.value, str(target.unavailability))
            )
    assert seen, "aucun score calé en usage : cas sans objet"
    assert all(value is None and motif == "no_curve" for _, value, motif in seen)


def test_the_status_follows_the_read_threshold(tmp_path: Path) -> None:
    """Seuil des diagnostics à 15 min, lecture à 10 : le statut ``curve`` d'une
    performance se décide au seuil de lecture (§ 6.7 (b) 6), quel que soit le seuil
    des diagnostics. Cherche une fenêtre où le support du CSV figé diffère entre 10 et
    15 min (sinon le cas est sans objet)."""
    from mountain_perf.backtest.rolling import RollingSettings
    from mountain_perf.model.curve_io import curve_csv_support

    manifest = build_world(tmp_path)
    settings = RollingSettings(0.1, 0.5, 15.0, 60.0)
    found: list[Any] = []
    for window in (3, 4, 5, 6, 7, 8, 10, 14):
        (prepared,) = prepare(manifest, [window], settings).windows
        for curve in prepared.curves:
            if not isinstance(curve.document, FrozenCurve):
                continue
            csv = curve.document.csv.encode("utf-8")
            at_10 = curve_csv_support(csv, 10.0)[1] is None
            at_15 = curve_csv_support(csv, 15.0)[1] is None
            if at_10 != at_15:
                found.append((window, str(curve.entry.status), at_10, at_15))
            assert (curve.entry.status is CurveStatus.CURVE) == at_10
    assert found, "aucune fenêtre ne distingue 10 et 15 min : cas sans objet"


def test_a_portion_longer_than_the_route_is_refused_before_any_write(
    tmp_path: Path,
) -> None:
    """§ 6.7 (b) 7 : « sortie {id} : portion_m ({a:g}, {b:g}) dépasse la longueur du
    profil de sa référence ({L:g} m). », avant tout écrit (performance ``curve``)."""
    manifest = build_world(tmp_path)
    edit_manifest(manifest, "a-2026-06-06", portion_m=[0.0, 1.0e9])
    outcome = rolling(manifest, "28")
    assert outcome.code == 1
    assert (
        "sortie a-2026-06-06 : portion_m (0, 1e+09) dépasse la longueur" in outcome.err
    )
    assert journal() == b""


def _with_index_elapsed() -> list[Any]:
    """Le monde par défaut, mais chaque entrée d'index porte son écoulé : l'index seul
    décide alors (``decide_on_index``), et le corpus dépend de son origine."""
    pairs = []
    day = FIRST_DAY
    while day <= LAST_DAY:
        seconds = 3600.0 * (1.0 if day < FORM_CHANGE else 1.1)
        pairs.append(
            activity_pair(
                f"t{day.isoformat()}",
                datetime(day.year, day.month, day.day, 6, tzinfo=UTC),
                index_elapsed_s=seconds,
                recording_s=seconds,
            )
        )
        day += timedelta(days=1)
    return pairs


def test_a4_on_an_index_that_carries_the_elapsed_times(tmp_path: Path) -> None:
    """A4 (§ 6.7, cas) quand l'index porte les écoulés : le corpus unique (la plus
    tardive des origines) et un corpus par origine donnent les mêmes courbes figées ;
    ici les corpus diffèrent vraiment (comptés), ce que le monde de ``test_og2_rolling``
    (« sans écoulé d'index ») ne permet pas."""
    manifest = build_world(tmp_path, _with_index_elapsed())
    preparation = prepare(manifest, [28])
    (window,) = preparation.windows
    sizes = []
    for declared, curve in zip(
        window.declaration.performances, window.curves, strict=True
    ):
        alone = load_curve_corpus(
            data_dir(), ATHLETE, ROLLING_ACTIVITY_TYPES, declared.origin, 28
        )
        sizes.append(len(alone.recordings))
        assert isinstance(curve.document, FrozenCurve)
        got = (
            curve.document.csv.encode("utf-8")
            + b"\x00"
            + curve.document.companion.encode("utf-8")
        )
        assert got == _frozen_with(alone, declared.origin, 28)
    assert all(size < len(preparation.corpus.recordings) for size in sizes)
