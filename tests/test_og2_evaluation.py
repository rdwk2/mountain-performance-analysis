"""Le calage (a), le réservoir (a), D7.4 et ``q_usage`` avec ``κ_j`` (OG-2, § 6.8 du
brief OG-2).

L'oracle général : la ligne ``j`` d'une exécution glissante est égale, au bit, à la
ligne ``j`` de l'exécution « courbe déclarée » lancée avec le fichier de ``κ_j``, aux
mêmes modèles déclarés. Le monde est celui de ``test_og2_rolling.py`` ; « à deux
formes » : à partir du 2026-05-25, les trails n'ont plus leur descente (une autre forme
de courbe, pas seulement un autre niveau) ; « à forme constante » : le monde par
défaut, dont les deux périodes ne diffèrent que d'un facteur de temps."""

from __future__ import annotations

import dataclasses
import json
import math
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from fixtures.backtest_world import COMMIT, COURBE
from mountain_perf.backtest import rolling as rolling_module
from mountain_perf.backtest.execution import (
    BacktestEvaluation,
    prepare_backtest,
    run_backtest,
)
from mountain_perf.backtest.metrics import usage_target
from mountain_perf.backtest.registry import EVENTS_FILE, read_registry
from mountain_perf.backtest.rolling import (
    RollingEvaluation,
    RollingPreparation,
    run_rolling,
)
from mountain_perf.config import data_dir
from mountain_perf.estimation.origin import ALL_PAST, OriginWindow
from mountain_perf.schemas import (
    ActivityRecording,
    CalibratedOutingScores,
    CurveStatus,
    FrozenCurve,
    IndexedActivity,
    ModelKind,
    Unavailability,
)
from test_og1_origin import activity_pair
from test_og2_rolling import (
    FIRST_DAY,
    FORM_CHANGE,
    LAST_DAY,
    activities,
    build_world,
    fix_world,
    freeze_reads,
    prepare,
    write_interim,
)

RECORDED_AT = datetime(2026, 10, 4, 12, 30, tzinfo=UTC)
WINDOWS: tuple[OriginWindow, ...] = (28, ALL_PAST)


@pytest.fixture(autouse=True)
def _world(monkeypatch: pytest.MonkeyPatch) -> None:
    fix_world(monkeypatch)
    freeze_reads(monkeypatch)


def two_forms() -> list[tuple[IndexedActivity, ActivityRecording]]:
    """Un trail par jour, d'une heure ; sans descente à partir du 2026-05-25."""
    pairs = []
    day = FIRST_DAY
    while day <= LAST_DAY:
        pairs.append(
            activity_pair(
                f"t{day.isoformat()}",
                datetime(day.year, day.month, day.day, 6, tzinfo=UTC),
                index_elapsed_s=None,
                recording_s=3600.0,
                descent=day < FORM_CHANGE,
            )
        )
        day += timedelta(days=1)
    return pairs


def evaluate(
    preparation: RollingPreparation, root: Path
) -> tuple[RollingEvaluation, ...]:
    """L'exécution enregistrée, ses calculs gardés, datée de :data:`RECORDED_AT`."""
    found: list[RollingEvaluation] = []
    run_rolling(preparation, root, recorded_at=RECORDED_AT, before_result=found.append)
    return tuple(found)


def declared_mode(
    manifest: Path, curve: FrozenCurve, name: str, folder: Path
) -> BacktestEvaluation:
    """L'exécution « courbe déclarée » lancée avec le fichier de la courbe figée : son
    CSV, et son compagnon auquel l'instant de l'estimation est rendu."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(curve.csv.encode("utf-8"))
    companion = json.loads(curve.companion)
    companion["generated_at"] = RECORDED_AT.isoformat()
    path.with_name(f"{path.stem}.meta.json").write_text(
        json.dumps(companion, ensure_ascii=False), encoding="utf-8"
    )
    preparation = prepare_backtest(manifest, path, commit=COMMIT, tree_modified=False)
    found: list[BacktestEvaluation] = []
    run_backtest(
        preparation,
        folder / "registre",
        recorded_at=RECORDED_AT,
        before_result=found.append,
    )
    (evaluation,) = found
    return evaluation


def _scores(outings: Sequence[Any], ids: set[str]) -> dict[str, Any]:
    return {
        run.outing.outing_id: (run.scores, run.baselines)
        for run in outings
        if run.outing.outing_id in ids
    }


def test_the_general_oracle(tmp_path: Path) -> None:
    """Pour chaque fenêtre et chaque performance ``curve`` : les scores de v0 brut et
    des baselines, le calage sous les onze horloges et les deux scénarios, les
    fourchettes — égaux au bit à ceux de l'exécution « courbe déclarée » avec ``κ_j``.
    Précondition (réservoir) : au moins un membre est ``curve`` sous la même fenêtre,
    avec une autre courbe que celle de ``j``."""
    manifest = build_world(tmp_path, two_forms())
    preparation = prepare(manifest, WINDOWS)
    evaluations = evaluate(preparation, tmp_path / "glissant")
    performances = preparation.common.performances
    witnessed = False
    compared = 0
    for window, evaluation in zip(preparation.windows, evaluations, strict=True):
        shas = [curve.entry.curve_sha256 for curve in window.curves]
        for j, (performance, curve) in enumerate(
            zip(performances, window.curves, strict=True)
        ):
            if curve.curve is None or performance.is_multi_outing:
                continue
            members = evaluation.populations[j].members
            index = {p.civil_date: k for k, p in enumerate(performances)}
            if any(
                window.curves[index[day]].curve is not None
                and shas[index[day]] != shas[j]
                for day in members
            ):
                witnessed = True
            assert isinstance(curve.document, FrozenCurve)
            name = curve.entry.curve_ref
            assert name is not None
            declared = declared_mode(
                manifest,
                curve.document,
                name.split("#")[0],
                tmp_path / f"declare-{compared}",
            )
            ids = {outing.outing_id for outing in performance.outings}
            assert _scores(evaluation.outings, ids) == _scores(declared.outings, ids)
            assert evaluation.calibration[j] == declared.calibration[j]
            ours = [b for b in evaluation.bands if b.outing_id in ids]
            theirs = [b for b in declared.bands if b.outing_id in ids]
            assert ours == theirs
            compared += 1
    assert compared >= 4
    assert witnessed


def test_the_reservoir_b_changes_only_residuals_and_bands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(b) rajouté en un point : la courbe d'un membre devient la sienne ; seuls les
    résidus et les fourchettes changent, pas le calage de ``j``."""
    manifest = build_world(tmp_path, two_forms())
    preparation = prepare(manifest, [28])
    (plain,) = evaluate(preparation, tmp_path / "a")
    original = rolling_module.member_curve

    def own_curve(window: Any, j: int, c: int) -> Any:
        mine = window.curves[c].curve
        return original(window, j, c) if mine is None else mine

    monkeypatch.setattr(rolling_module, "member_curve", own_curve)
    (changed,) = evaluate(preparation, tmp_path / "b")
    assert plain.calibration == changed.calibration
    assert plain.outings == changed.outings
    assert plain.bands != changed.bands


def test_b2_the_comparator_level_does_not_depend_on_the_window(
    tmp_path: Path,
) -> None:
    """B2 : sur un monde à forme constante — quatre trails par jour, trois fois plus
    rapides que ceux du monde par défaut (l'effort du comparateur n'est pas borné), plus
    lents de 2 % à partir du 2026-05-25 —, le ``L`` du comparateur (usage, écoulé) est
    le même sous les trois fenêtres. Le cadrage le donne à 10⁻¹⁵ près ; ici, l'écart est
    de quelques ulp d'une valeur proche de 0,035 (1,5·10⁻¹⁵) : la borne est 10⁻¹⁴. Un
    changement de niveau de 10 % ferait classer autrement des intervalles du temps M, et
    la courbe ne changerait plus d'un seul facteur."""
    manifest = build_world(tmp_path, activities(scale=1 / 3, per_day=4, later=1.02))
    preparation = prepare(manifest, [28, 56, ALL_PAST])
    evaluations = evaluate(preparation, tmp_path / "registre")
    day = date(2026, 6, 27)
    levels = []
    for evaluation in evaluations:
        (entry,) = [
            item
            for performance in evaluation.calibration
            if performance.population.civil_date == day
            for item in performance.outings
            if item.control.model is ModelKind.V0_RECALIBRATED
        ]
        assert entry.usage is not None
        scores = entry.usage.clocks[0].scores
        assert scores is not None
        value = scores.support.log_ratio.value
        assert value is not None
        levels.append(value)
    assert max(levels) - min(levels) <= 1e-14


def test_the_v0_residuals_average_to_beta(tmp_path: Path) -> None:
    """L'identité de M4d-2 au bit : la moyenne des résidus de v0 brut des fourchettes de
    ``j`` vaut le ``β`` du comparateur de ``j`` (usage, écoulé)."""
    manifest = build_world(tmp_path, two_forms())
    (evaluation,) = evaluate(prepare(manifest, [28]), tmp_path / "registre")
    checked = 0
    for bands in evaluation.bands:
        v0 = bands.models[0]
        assert v0.model is ModelKind.V0_RAW
        values = [r.value for r in v0.residuals if r.value is not None]
        if not values:
            continue
        (comparator,) = [
            entry
            for performance in evaluation.calibration
            for entry in performance.outings
            if entry.outing_id == bands.outing_id
            and entry.control.model is ModelKind.V0_RECALIBRATED
        ]
        assert comparator.usage is not None
        calibration = comparator.usage.clocks[0].calibration
        assert calibration.beta == math.fsum(values) / len(values)
        checked += 1
    assert checked >= 1


def test_a_first_performance_is_not_calibrated(tmp_path: Path) -> None:
    """La première performance n'a aucun membre : ``C_j`` vide, le comparateur « non
    calé »."""
    manifest = build_world(tmp_path)
    (evaluation,) = evaluate(prepare(manifest, [28]), tmp_path / "registre")
    first = evaluation.calibration[0]
    assert first.population.members == ()
    comparator = [
        entry
        for entry in first.outings
        if entry.control.model is ModelKind.V0_RECALIBRATED
    ]
    assert comparator
    for entry in comparator:
        status = entry.control.clocks[0].calibration.unavailability
        assert status is Unavailability.NOT_CALIBRATED


def test_a_performance_without_curve(tmp_path: Path) -> None:
    """Sans courbe : v0 brut et le comparateur absents de ses sorties ; le ``q_usage``
    des trois baselines « sans courbe » ; leur calage présent ; ``L`` d'une baseline
    égal au bit à celui de l'exécution « courbe déclarée »."""
    manifest = build_world(tmp_path, activities(first=date(2026, 5, 28)))
    preparation = prepare(manifest, [28])
    (window,) = preparation.windows
    assert window.curves[0].entry.status is CurveStatus.ABSENT
    (evaluation,) = evaluate(preparation, tmp_path / "glissant")
    first = preparation.common.performances[0].outings[0].outing_id
    (run,) = [r for r in evaluation.no_curve if r.traced.outing.outing_id == first]
    assert [kind for kind, _ in run.baselines] == [
        ModelKind.CONSTANT_SPEED,
        ModelKind.NAISMITH,
        ModelKind.TOBLER,
    ]
    for _, scores in run.baselines:
        assert scores.usage is not None
        target = scores.usage.clocks[0].usage_target
        assert target is not None
        assert target.q_usage.unavailability is Unavailability.NO_CURVE
    assert all(r.outing.outing_id != first for r in evaluation.outings)
    calibrated = evaluation.calibration[0]
    assert {e.control.model for e in calibrated.outings} == {
        ModelKind.CONSTANT_SPEED,
        ModelKind.NAISMITH,
        ModelKind.TOBLER,
    }
    events = read_registry(tmp_path / "glissant").events
    result = events[1].result
    assert result is not None
    (scored,) = [o for o in result.outings if o.outing_id == first]
    assert {m.model for m in scored.models} == {
        ModelKind.CONSTANT_SPEED,
        ModelKind.NAISMITH,
        ModelKind.TOBLER,
    }
    assert scored.bands is None
    declared = declared_mode(
        manifest, _any_curve(), "courbe_synthetique.csv", tmp_path / "declare"
    )
    (theirs,) = [r for r in declared.outings if r.outing.outing_id == first]
    for (kind, ours), (other, reference) in zip(
        run.baselines, theirs.baselines, strict=True
    ):
        assert kind is other
        assert ours.usage is not None
        assert reference.usage is not None
        assert (
            ours.usage.clocks[0].support.log_ratio
            == reference.usage.clocks[0].support.log_ratio
        )


def _any_curve() -> FrozenCurve:
    companion = json.loads(
        COURBE.with_name("courbe_synthetique.meta.json").read_text(encoding="utf-8")
    )
    companion.pop("generated_at")
    return FrozenCurve(
        COURBE.read_text(encoding="utf-8"), json.dumps(companion, ensure_ascii=False)
    )


# --- L'ordre des motifs de usage_target (précision 7 de la conception) ---------------


def test_no_curve_with_every_element_observed() -> None:
    """Tout ``K`` observé, une baseline valide : « sans courbe », jamais
    ``model_error`` ; les poids sont ceux de la baseline."""
    target = usage_target(
        (100.0, 300.0),
        (100.0, 300.0),
        (110.0, 290.0),
        (None, None),
        base_unavailability=Unavailability.NO_CURVE,
    )
    assert target.q_usage.unavailability is Unavailability.NO_CURVE
    assert target.q_usage_prefix.unavailability is Unavailability.NO_CURVE
    assert not target.model_error
    assert target.weights == (0.25, 0.75)


def test_an_unobserved_element_passes_before_no_curve() -> None:
    target = usage_target(
        (100.0, 300.0),
        (100.0, 300.0),
        (None, 290.0),
        (Unavailability.ABSENT, None),
        base_unavailability=Unavailability.NO_CURVE,
    )
    assert target.q_usage.unavailability is Unavailability.ABSENT
    assert target.q_usage_prefix.unavailability is Unavailability.NO_CURVE


def test_an_invalid_baseline_is_no_curve_with_the_model_error_flag() -> None:
    target = usage_target(
        (100.0, None),
        (100.0, None),
        (110.0, 290.0),
        (None, None),
        base_unavailability=Unavailability.NO_CURVE,
    )
    assert target.q_usage.unavailability is Unavailability.NO_CURVE
    assert target.q_usage_prefix.unavailability is Unavailability.NO_CURVE
    assert target.model_error
    assert target.weights is None


# --- Deux propriétés transversales (§ 8.2) ------------------------------------------


def test_an_activity_after_every_origin_changes_no_score(tmp_path: Path) -> None:
    """Une activité finie après la plus tardive des origines ne change aucun score,
    aucun CSV, aucune part."""
    manifest = build_world(tmp_path)
    before = prepare(manifest, [28])
    first = evaluate(before, tmp_path / "a")
    later = activity_pair(
        "apres",
        datetime(2026, 6, 25, 6, tzinfo=UTC),
        index_elapsed_s=None,
        recording_s=3600.0,
    )
    write_interim(data_dir(), activities(extra=[later]))
    after = prepare(manifest, [28])
    second = evaluate(after, tmp_path / "b")
    for one, two in zip(before.windows[0].curves, after.windows[0].curves, strict=True):
        assert one.entry.curve_sha256 == two.entry.curve_sha256
        assert one.entry.out_of_support_share == two.entry.out_of_support_share
    assert [r.scores for r in first[0].outings] == [r.scores for r in second[0].outings]
    assert first[0].calibration == second[0].calibration


def test_permuted_outings_change_only_the_manifest(tmp_path: Path) -> None:
    """Permuter les sorties du manifeste ne change aucun document, ni aucune ligne hors
    du champ ``manifest`` de la DÉCLARATION (et de l'enchaînement des lignes)."""
    manifest = build_world(tmp_path)
    evaluate(prepare(manifest, [28]), tmp_path / "a")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["outings"] = list(reversed(data["outings"]))
    manifest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    evaluate(prepare(manifest, [28]), tmp_path / "b")
    documents = [
        sorted(p.name for p in (tmp_path / side / "documents").iterdir())
        for side in ("a", "b")
    ]
    assert documents[0] == documents[1]
    lines = [read_registry(tmp_path / side).events for side in ("a", "b")]
    for one, two in zip(*lines, strict=True):
        if one.declaration is not None:
            assert two.declaration is not None
            one = dataclasses.replace(
                one,
                declaration=dataclasses.replace(
                    one.declaration, manifest=two.declaration.manifest
                ),
            )
        assert dataclasses.replace(one, previous_hash=two.previous_hash) == two
    assert (tmp_path / "a" / EVENTS_FILE).read_bytes() != (
        tmp_path / "b" / EVENTS_FILE
    ).read_bytes()


def test_the_comparator_scores_are_calibrated(tmp_path: Path) -> None:
    """Une performance tardive : le comparateur est calé (``C_j`` non vide)."""
    manifest = build_world(tmp_path)
    (evaluation,) = evaluate(prepare(manifest, [28]), tmp_path / "registre")
    last = evaluation.calibration[-1]
    comparator = [
        entry
        for entry in last.outings
        if isinstance(entry, CalibratedOutingScores)
        and entry.control.model is ModelKind.V0_RECALIBRATED
    ]
    assert comparator
    assert comparator[0].control.clocks[0].calibration.unavailability is None
