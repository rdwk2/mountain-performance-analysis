"""La commande glissante, un processus, le cache, le figement (OG-2, § 6.7 du brief
OG-2).

Le monde : le manifeste et les GPX de ``tests/fixtures/backtest_world.py`` (performances
de juin 2026), et un ``interim/`` synthétique sous ``MPA_DATA_DIR`` : un trail par jour
du 2026-04-20 au 2026-06-19 à 06:00 UTC, sans écoulé d'index, d'une heure jusqu'au
2026-05-24 et de 66 minutes ensuite (deux « formes ») ; son index est trié comme celui
de l'ingestion. La commande se lance par ``main([...])`` ; l'état git et l'horloge sont
fixés par :func:`fix_world`, appelée par une fixture ``autouse`` de chaque fichier
``test_og2_*`` qui lance la commande."""

from __future__ import annotations

import contextlib
import dataclasses
import io
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from fixtures.backtest_world import ATHLETE, COMMIT, write_world
from mountain_perf import cli
from mountain_perf.backtest.registry import EVENTS_FILE, read_registry
from mountain_perf.backtest.rolling import (
    ROLLING_ACTIVITY_TYPES,
    RollingPreparation,
    RollingSettings,
    intervals_cache,
    prepare_rolling,
    rolling_selection,
)
from mountain_perf.config import data_dir
from mountain_perf.estimation.curve import CURVE_ESTIMATION_PARAMETER_SPECS
from mountain_perf.estimation.origin import (
    ALL_PAST,
    OriginWindow,
    estimate_at_origin,
    origin_companion,
)
from mountain_perf.gitstate import GitState
from mountain_perf.gpx import PROFILE_PARAMETER_SPECS, build_profile, read_gpx
from mountain_perf.ingest.interim import read_recording_with_sha256, write_activities
from mountain_perf.model.curve_io import (
    curve_documents,
    freeze_companion,
    read_curve_documents,
)
from mountain_perf.model.engine import (
    PROJECTION_PARAMETER_SPECS,
    portion_out_of_support_time_share,
)
from mountain_perf.runs import load_curve_corpus
from mountain_perf.schemas import (
    ActivityIndex,
    ActivityRecording,
    CurveStatus,
    Declaration,
    FrozenCurve,
    IndexedActivity,
    ParameterSet,
    RegistryEvent,
    RollingPerformance,
    Sport,
)
from test_ingest_interim import REPORT
from test_og1_origin import activity_pair
from test_schemas_interim import SOURCE

NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)
"""L'horloge du monde : l'instant de la préparation glissante."""

FIRST_DAY = date(2026, 4, 20)
LAST_DAY = date(2026, 6, 19)
FORM_CHANGE = date(2026, 5, 25)


def fix_world(monkeypatch: pytest.MonkeyPatch) -> None:
    """L'état git propre au commit des fixtures (``cli.git_state``, que lit ``mperf
    backtest``) et l'horloge de la préparation (``cli._now``) à :data:`NOW`."""
    monkeypatch.setattr(cli, "git_state", lambda directory: GitState(COMMIT, False))
    monkeypatch.setattr(cli, "_now", lambda: NOW)


@pytest.fixture(autouse=True)
def _world(monkeypatch: pytest.MonkeyPatch) -> None:
    fix_world(monkeypatch)


def activities(
    first: date = FIRST_DAY,
    last: date = LAST_DAY,
    *,
    extra: Sequence[tuple[IndexedActivity, ActivityRecording]] = (),
) -> list[tuple[IndexedActivity, ActivityRecording]]:
    """Un trail par jour de ``first`` à ``last`` (06:00 UTC), et ``extra``."""
    pairs = []
    day = first
    while day <= last:
        seconds = 3600.0 if day < FORM_CHANGE else 3960.0
        pairs.append(
            activity_pair(
                f"t{day.isoformat()}",
                datetime(day.year, day.month, day.day, 6, tzinfo=UTC),
                index_elapsed_s=None,
                recording_s=seconds,
            )
        )
        day += timedelta(days=1)
    return [*pairs, *extra]


def write_interim(
    folder: Path, pairs: Sequence[tuple[IndexedActivity, ActivityRecording]]
) -> None:
    """``interim/activities/`` de ``pairs`` sous ``folder``, l'index trié comme celui de
    l'ingestion (instant de départ, puis référence)."""
    entries = sorted(
        (pair[0] for pair in pairs),
        key=lambda item: (item.start_time.timestamp(), item.activity_ref),
    )
    write_activities(
        folder,
        ActivityIndex(tuple(entries), (SOURCE,)),
        [pair[1] for pair in pairs],
        REPORT,
    )


def build_world(
    root: Path,
    pairs: Sequence[tuple[IndexedActivity, ActivityRecording]] | None = None,
) -> Path:
    """Le monde : ``interim/`` sous ``MPA_DATA_DIR``, le manifeste et ses GPX sous
    ``root / "monde"`` ; rend le chemin du manifeste."""
    write_interim(data_dir(), activities() if pairs is None else pairs)
    return write_world(root / "monde")


@dataclasses.dataclass
class Run:
    """Un appel de la commande : son code et ses deux sorties."""

    code: int
    out: str
    err: str


def run(*arguments: str) -> Run:
    """``mperf backtest <arguments>`` ; une erreur d'argparse rend son code (2)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(["backtest", *arguments])
        except SystemExit as stopped:
            code = int(stopped.code or 0)
    return Run(code, out.getvalue(), err.getvalue())


def rolling(manifest: Path, windows: str, *options: str) -> Run:
    return run(
        str(manifest),
        "--rolling",
        windows,
        "--covered-threshold",
        "0.1",
        "--coverage-tolerance",
        "60",
        *options,
    )


def registry() -> Path:
    return data_dir() / "registre"


def events() -> tuple[RegistryEvent, ...]:
    return read_registry(registry()).events


def declarations() -> list[Declaration]:
    return [e.declaration for e in events() if e.declaration is not None]


def document(sha: str) -> dict[str, Any]:
    """Le contenu (``data``) d'un document du registre."""
    path = registry() / "documents" / f"{sha}.json"
    loaded: dict[str, Any] = json.loads(path.read_bytes())["data"]
    return loaded


def journal() -> bytes:
    path = registry() / EVENTS_FILE
    return path.read_bytes() if path.exists() else b""


SETTINGS = RollingSettings(0.1, 0.5, 10.0, 60.0)


def prepare(
    manifest: Path,
    windows: Sequence[OriginWindow],
    settings: RollingSettings = SETTINGS,
) -> RollingPreparation:
    """``prepare_rolling`` sur le monde, à l'horloge et au commit du monde."""
    folder = data_dir()
    return prepare_rolling(
        manifest,
        folder,
        windows,
        settings,
        commit=COMMIT,
        tree_modified=False,
        prepared_at=NOW,
        read_recording=lambda ref: read_recording_with_sha256(folder, ref),
    )


def entry_of(declaration: Declaration, day: date) -> RollingPerformance:
    rolling_ = declaration.rolling
    assert rolling_ is not None
    for declared, entry in zip(
        declaration.performances, rolling_.performances, strict=True
    ):
        if declared.performance.civil_date == day:
            return entry
    raise AssertionError(day)


def edit_manifest(manifest: Path, outing_id: str, **fields: object) -> None:
    data = json.loads(manifest.read_text(encoding="utf-8"))
    for outing in data["outings"]:
        if outing["id"] == outing_id:
            outing.update(fields)
    manifest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# --- La commande à trois fenêtres -----------------------------------------------------


def test_three_windows_give_three_declarations(tmp_path: Path) -> None:
    manifest = build_world(tmp_path)
    outcome = rolling(manifest, "28,56,all")
    assert outcome.code == 0, outcome.err
    assert [e.kind.value for e in events()] == ["declaration", "result"] * 3
    found = declarations()
    assert len(found) == 3
    assert {d.commit for d in found} == {COMMIT}
    windows = [d.rolling.window_days if d.rolling else -1 for d in found]
    assert windows == [28, 56, None]
    rules = []
    for declared in found:
        assert declared.rolling is not None
        assert declared.rolling.command_windows == (28, 56, None)
        assert declared.curve_ref is None
        rule = document(declared.rolling.rule)
        rule.pop("window_days")
        rules.append(rule)
    assert rules[0] == rules[1] == rules[2]
    assert len({d.rolling.index_sha256 for d in found if d.rolling}) == 1
    assert found[0].performances == found[1].performances == found[2].performances
    assert outcome.out.count("enregistrée ; dernière ligne sha256") == 3


# --- Les options -----------------------------------------------------------------


@pytest.mark.parametrize(
    "option",
    [
        "--covered-threshold",
        "--coverage-tolerance",
        "--beyond-marker",
        "--rule-support-threshold",
    ],
)
def test_the_rolling_options_need_rolling(tmp_path: Path, option: str) -> None:
    outcome = run(str(tmp_path / "m.json"), "--curve", "c.csv", option, "1")
    assert outcome.code == 2
    assert f"{option} n'existe qu'avec --rolling." in outcome.err
    assert journal() == b""


@pytest.mark.parametrize(
    ("given", "missing"),
    [
        (["--coverage-tolerance", "60"], "--covered-threshold"),
        (["--covered-threshold", "0.1"], "--coverage-tolerance"),
    ],
)
def test_rolling_requires_its_two_options(
    tmp_path: Path, given: list[str], missing: str
) -> None:
    outcome = run(str(tmp_path / "m.json"), "--rolling", "28", *given)
    assert outcome.code == 2
    assert f"--rolling demande {missing}." in outcome.err


@pytest.mark.parametrize("text", ["28,28", "0", "28,x", "all,28,all", "", "-3"])
def test_a_malformed_window_list_is_refused(tmp_path: Path, text: str) -> None:
    outcome = run(str(tmp_path / "m.json"), f"--rolling={text}")
    assert outcome.code == 2
    assert (
        "--rolling : une liste de fenêtres attendue (des jours ≥ 1 ou all, "
        f"distincts), reçu {text!r}."
    ) in outcome.err


def test_curve_and_rolling_exclude_each_other(tmp_path: Path) -> None:
    outcome = run(str(tmp_path / "m.json"), "--curve", "c.csv", "--rolling", "28")
    assert outcome.code == 2
    assert "not allowed with argument" in outcome.err or "pas permis" in outcome.err


def test_the_sensitivity_is_refused_in_rolling_mode(tmp_path: Path) -> None:
    outcome = rolling(tmp_path / "m.json", "28", "--sensitivity")
    assert outcome.code == 2
    assert (
        "la sensibilité de D13 n'existe pas en mode glissant : hors du jalon (0010 "
        "D13, précision OG-2)."
    ) in outcome.err


def test_neither_curve_nor_rolling_is_today_s_refusal(tmp_path: Path) -> None:
    outcome = run(str(tmp_path / "m.json"))
    assert outcome.code == 1
    assert cli.BACKTEST_CURVE_ERROR in outcome.err


# --- Les deux seuils (R1) et la part --------------------------------------------------


def test_r1_projectable_for_the_rule_without_read_support(tmp_path: Path) -> None:
    """R1, joué « diagnostics 5, lecture 10 » (accord de la conception) : le seuil de
    lecture n'est plus une option depuis la révision 1 du brief, c'est le paramètre
    déclaré ``curve_min_support_min`` de v0, à son défaut de 10 min ; le seuil des
    diagnostics de la règle, lui, se règle (``--rule-support-threshold``), à 5. Sur 4
    jours, la courbe est projetable au seuil des diagnostics et n'a aucune tranche au
    seuil de lecture : « sans courbe » à la lecture, et l'exécution continue."""
    manifest = build_world(tmp_path)
    outcome = rolling(manifest, "4", "--rule-support-threshold", "5")
    assert outcome.code == 0, outcome.err
    (declared,) = declarations()
    entry = entry_of(declared, date(2026, 6, 3))
    assert entry.status is CurveStatus.NO_READ_SUPPORT
    companion = json.loads(document(entry.document)["companion"])
    assert companion["diagnostic_support_threshold_min"] == 5.0
    assert companion["estimation"]["projectable"] is True
    assert [e.kind.value for e in events()] == ["declaration", "result"]


def test_the_share_is_read_at_the_reading_threshold(tmp_path: Path) -> None:
    """La part se prend sur ``κ_j`` relue au seuil de lecture (10 min), pas au seuil des
    diagnostics (5 min) ; précondition : les deux parts diffèrent."""
    manifest = build_world(tmp_path)
    assert rolling(manifest, "7", "--rule-support-threshold", "5").code == 0
    (declared,) = declarations()
    entry = entry_of(declared, date(2026, 6, 3))
    assert entry.status is CurveStatus.CURVE
    frozen = document(entry.document)
    csv = frozen["csv"].encode("utf-8")
    companion = frozen["companion"].encode("utf-8")
    profile = build_profile(
        read_gpx(manifest.parent / "gpx" / "a" / "prepare.gpx").route,
        ParameterSet(PROFILE_PARAMETER_SPECS),
    )
    projection = ParameterSet(PROJECTION_PARAMETER_SPECS)

    def share_at(threshold: float) -> float:
        parameters = ParameterSet(
            PROJECTION_PARAMETER_SPECS, {"curve_min_support_min": threshold}
        )
        curve = read_curve_documents(
            csv, companion, "og2.csv", parameters, generated_at=NOW
        )
        return portion_out_of_support_time_share(profile, curve.curve, projection, None)

    assert share_at(10.0) != share_at(5.0)
    assert entry.out_of_support_share == share_at(10.0)


# --- Un corpus, un cache (A4, A5) -----------------------------------------------------


def _frozen_with(
    corpus: Any, origin_at: datetime, window: OriginWindow, **options: Any
) -> bytes:
    selection = rolling_selection()
    parameters = ParameterSet(CURVE_ESTIMATION_PARAMETER_SPECS)
    profile = ParameterSet(PROFILE_PARAMETER_SPECS)
    result = estimate_at_origin(
        corpus, ATHLETE, origin_at, window, selection, parameters, profile, **options
    )
    assert result.estimate is not None
    provenance, estimation = origin_companion(
        result,
        corpus,
        selection,
        parameters,
        profile,
        commit=COMMIT,
        generated_at=NOW,
    )
    documents = curve_documents(result.rows, Sport.FOOT, provenance, estimation)
    return documents.csv + b"\x00" + freeze_companion(documents.companion)


def test_one_corpus_for_all_origins_gives_the_same_companions(tmp_path: Path) -> None:
    """A4 : le corpus unique de la commande et un corpus par origine donnent les mêmes
    courbes figées, octet pour octet."""
    manifest = build_world(tmp_path)
    preparation = prepare(manifest, [28])
    (window,) = preparation.windows
    for declared, curve in zip(
        window.declaration.performances, window.curves, strict=True
    ):
        assert isinstance(curve.document, FrozenCurve)
        alone = load_curve_corpus(
            data_dir(), ATHLETE, ROLLING_ACTIVITY_TYPES, declared.origin, 28
        )
        expected = _frozen_with(alone, declared.origin, 28)
        got = (
            curve.document.csv.encode("utf-8")
            + b"\x00"
            + curve.document.companion.encode("utf-8")
        )
        assert got == expected


def test_the_cache_changes_no_byte(tmp_path: Path) -> None:
    """A5 : avec et sans cache des intervalles, les mêmes octets."""
    build_world(tmp_path)
    corpus = load_curve_corpus(
        data_dir(),
        ATHLETE,
        ROLLING_ACTIVITY_TYPES,
        datetime(2026, 6, 19, 22, tzinfo=UTC),
        ALL_PAST,
    )
    cache = intervals_cache(corpus)
    for day in (20, 27):
        origin_at = datetime(2026, 5, day, 22, tzinfo=UTC)
        assert _frozen_with(corpus, origin_at, 28) == _frozen_with(
            corpus, origin_at, 28, intervals_of=cache
        )


# --- La correspondance ----------------------------------------------------------------


def test_an_undeclared_activity_writes_nothing(tmp_path: Path) -> None:
    manifest = build_world(tmp_path)
    edit_manifest(manifest, "a-2026-06-03", activity_refs=["inconnue"])
    outcome = rolling(manifest, "28,56")
    assert outcome.code == 1
    assert (
        "Erreur : sortie a-2026-06-03 : l'activité inconnue déclarée n'est pas dans "
        "l'index."
    ) in outcome.err
    assert journal() == b""


def test_a_refused_correspondence_writes_nothing(tmp_path: Path) -> None:
    manifest = build_world(tmp_path)
    edit_manifest(manifest, "a-2026-06-03", activity_refs=["t2026-06-01"])
    outcome = rolling(manifest, "28")
    assert outcome.code == 1
    assert "ne recouvre pas la sortie" in outcome.err
    assert journal() == b""


# --- Ce qui change et ce qui ne change pas --------------------------------------------


def test_an_activity_after_every_origin_changes_companions_not_csvs(
    tmp_path: Path,
) -> None:
    """A3 : une activité finie après la plus tardive des origines change les compagnons
    figés (sa ligne d'inspectée), pas les CSV."""
    manifest = build_world(tmp_path)
    before = prepare(manifest, [28]).windows[0].curves
    later = activity_pair(
        "apres",
        datetime(2026, 6, 25, 6, tzinfo=UTC),
        index_elapsed_s=None,
        recording_s=3600.0,
    )
    write_interim(data_dir(), activities(extra=[later]))
    after = prepare(manifest, [28]).windows[0].curves
    for one, two in zip(before, after, strict=True):
        assert isinstance(one.document, FrozenCurve)
        assert isinstance(two.document, FrozenCurve)
        assert one.document.csv == two.document.csv
        assert one.document.companion != two.document.companion


def test_56_days_holding_all_the_past_give_the_csv_of_all(tmp_path: Path) -> None:
    """Le 2026-06-03 (origine le 2026-05-27), 56 jours remontent avant la première
    activité (2026-04-20) : même CSV que tout le passé, autres compagnons (la fenêtre et
    la borne basse y sont écrites)."""
    manifest = build_world(tmp_path)
    w56, everything = prepare(manifest, [56, ALL_PAST]).windows
    first, second = w56.curves[0].document, everything.curves[0].document
    assert isinstance(first, FrozenCurve)
    assert isinstance(second, FrozenCurve)
    assert first.csv == second.csv
    assert first.companion != second.companion
