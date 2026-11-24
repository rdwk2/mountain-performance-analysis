"""La règle en couches dans les commandes, le backtest glissant et le registre au
format 7 (M6b-3, § 8.2 du brief, ``docs/decisions/0025``) : L1 à L4 et les textes.

Les commandes se lancent par ``main([...])`` sur le monde synthétique de
``test_og2_rolling`` (des trails quotidiens), l'état git et l'horloge fixés ; le
registre du format 6 est celui que ``main`` (``4b7e5fe``) a écrit pour une exécution
``--rolling 28`` de ce monde, figé sous ``tests/fixtures/registre_format6/``."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import test_og2_accord as t
from fixtures.backtest_world import COMMIT
from fixtures.registry import ATHLETE, V0_RAW, declaration
from mountain_perf import cli, gitstate
from mountain_perf.backtest import canonical_bytes, encode_document
from mountain_perf.backtest import registry as registry_module
from mountain_perf.backtest.codec import decode_document
from mountain_perf.backtest.registry import (
    EVENTS_FILE,
    RegistryError,
    _line,
    append_declaration,
    read_registry,
    verify_registry,
)
from mountain_perf.backtest.rolling import window_label
from mountain_perf.config import data_dir
from mountain_perf.estimation.curve import LAYERED_METHOD
from mountain_perf.estimation.decision import LAYERED, PARIS
from mountain_perf.gitstate import GitState
from mountain_perf.reports import origin_summary_lines
from mountain_perf.runs import (
    FOLDER_ATHLETE,
    course_origin,
    curve_selection,
    load_curve_corpus,
    origin_curve,
)
from mountain_perf.schemas import (
    AbsentCurve,
    LayeredRollingRule,
    RollingDeclaration,
    RollingRule,
)
from test_m6b3_rule import ORIGIN, R, provider, run, season_r
from test_og1_origin import activity_pair, corpus
from test_og2_rolling import (
    activities,
    build_world,
    declarations,
    events,
    fix_world,
    registry,
)
from test_og2_rolling import rolling as rolling_command
from test_og2_rolling import run as backtest

FIXTURES = Path(__file__).parent / "fixtures"
ROUTE = FIXTURES / "mini_11.gpx"
FORMAT_6 = FIXTURES / "registre_format6"
DECLARATION_SHA256 = "d8ec131b74d473e6fae235c924586c8a4d07cd0c7fc90c4d010990c228b1ac93"
RESULT_SHA256 = "1a72589e3dc91c51ef7f3e4225d77f0a3a6c5928c76fba84620a5f6f577f3850"
RULE_SHA256 = "66c49bffc5d11448be266477c206de44f93a6eca1c0ab25097589e60d371e188"
LABEL = "en couches (forme 365 jours, niveau 56 jours, κ = 0,5)"
DAY = "2026-06-20"


@pytest.fixture(autouse=True)
def _world(monkeypatch: pytest.MonkeyPatch) -> None:
    fix_world(monkeypatch)
    monkeypatch.setattr(
        gitstate, "git_state", lambda directory: GitState(COMMIT, False)
    )


def _main(capsys: pytest.CaptureFixture[str], *arguments: str) -> tuple[int, str, str]:
    code = cli.main(list(arguments))
    out, err = capsys.readouterr()
    return code, out, err


def _long_world(tmp_path: Path) -> Path:
    """Le monde de ``test_og2_rolling`` commencé le 2026-02-01 : à l'origine du
    2026-06-13, des trails avant et après la borne de 56 jours (le 2026-04-18)."""
    return build_world(tmp_path, activities(first=date(2026, 2, 1)))


# --- L1 : --window layered ----------------------------------------------------------


def test_window_layered_in_curve_and_project(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _long_world(tmp_path)
    code, _, err = _main(
        capsys, "curve", "couches", "--athlete", "x", "--at", DAY, "--window", "layered"
    )
    assert code == 0, err
    reference = data_dir() / "reference"
    assert (reference / "couches.csv").exists()
    companion = json.loads((reference / "couches.meta.json").read_bytes())
    estimation = companion["estimation"]
    origin = estimation["origin"]
    assert list(origin)[:4] == ["origin", "window", "lower_bound", "level_layer"]
    assert origin["window"] == "layered"
    layer = origin["level_layer"]
    assert layer["level_lower_bound"] == "2026-04-17T22:00:00+00:00"
    assert (layer["level_window_days"], layer["kappa"]) == (56, 0.5)
    assert 0 < layer["recent_count"] < layer["fit_count"]
    assert layer["delta"] is not None
    assert estimation["method"] == LAYERED_METHOD
    assert companion["estimator"].startswith(
        f"mperf curve --at (OG-1) : règle à l'origine, {LABEL} ; "
    )
    code, out, err = _main(
        capsys, "project", str(ROUTE), "--at", DAY, "--window", "layered"
    )
    assert code == 0, err
    lines = out.splitlines()
    assert lines[0] == (
        "jour 2026-06-20 : origine 2026-06-13 00:00 à Paris ; règle en couches (forme "
        "365 jours, niveau 56 jours, κ = 0,5), fins depuis le 2025-06-13 00:00 à Paris"
    )
    course = course_origin(date(2026, 6, 20), date(2026, 10, 4))
    found = origin_curve(
        load_curve_corpus(
            data_dir(),
            FOLDER_ATHLETE,
            curve_selection().source_activity_types,
            course.origin,
            LAYERED,
        ),
        course,
        LAYERED,
        generated_at=datetime(2026, 10, 4, 12, tzinfo=UTC),
    )
    assert found.curve is not None
    assert found.curve.name == "origine-2026-06-20-layered.csv"
    level = found.result.level_layer
    assert level is not None
    assert level.delta is not None
    assert lines[1] == (
        f"niveau à mi-chemin : Δ = {level.delta:+.4f}, {level.recent_count} activités "
        f"récentes sur {level.fit_count} (fins depuis le 2026-04-18 00:00 à Paris) ; "
        f"vitesses de la courbe d'un an × {level.speed_factor:.4f}"
    )
    for value in ("couches", "layered2"):
        with pytest.raises(SystemExit) as stopped:
            cli.main(["curve", "o", "--at", DAY, "--athlete", "x", "--window", value])
        assert stopped.value.code == 2
        assert (
            f"fenêtre invalide {value!r} : un nombre entier de jours, au moins 1, all "
            "ou layered"
        ) in capsys.readouterr().err


# --- L2 : --rolling 56,layered ------------------------------------------------------


def _stored(sha: str) -> bytes:
    return (registry() / "documents" / f"{sha}.json").read_bytes()


def test_rolling_56_and_layered(tmp_path: Path) -> None:
    manifest = build_world(tmp_path)
    outcome = rolling_command(manifest, "56,layered")
    assert outcome.code == 0, outcome.err
    first, second = (d.rolling for d in declarations())
    assert first is not None
    assert second is not None
    assert (second.window_days, second.level_window_days, second.level_kappa) == (
        365,
        56,
        0.5,
    )
    assert second.command_windows == first.command_windows == (56, 365)
    assert second.command_level_windows == first.command_level_windows == (None, 56)
    assert (first.level_window_days, first.level_kappa) == (None, None)
    rule = decode_document(_stored(second.rule), LayeredRollingRule)
    assert (rule.window_days, rule.level_window_days, rule.level_kappa) == (
        365,
        56,
        0.5,
    )
    assert type(decode_document(_stored(first.rule), RollingRule)) is RollingRule
    assert all(e.format_version == 7 for e in events())
    curves = [e.curve_ref for e in second.performances if e.curve_ref is not None]
    assert curves
    assert all("-layered.csv#" in ref for ref in curves)
    reports = "".join(
        p.read_text(encoding="utf-8") for p in (data_dir() / "rapports").iterdir()
    )
    assert f"fenêtre {LABEL} : déclaration" in reports
    assert f"mode glissant, fenêtre {LABEL} ; " in reports
    alone = rolling_command(manifest, "56")
    assert alone.code == 0, alone.err
    third = declarations()[2].rolling
    assert third is not None
    assert third.rule == first.rule
    assert _stored(third.rule) == _stored(first.rule)
    assert third.command_level_windows == (None,)
    assert cli._rolling_windows("365,layered") == (365, LAYERED)
    refused = backtest(str(tmp_path / "m.json"), "--rolling=layered,layered")
    assert refused.code == 2
    assert (
        "--rolling : une liste de fenêtres attendue (des jours ≥ 1, all ou layered, "
        "distincts), reçu 'layered,layered'."
    ) in refused.err


def test_365_and_layered_are_two_rules() -> None:
    """``--rolling 365,layered`` : deux paires distinctes, (365, None) et (365, 56)."""
    found = t.world()
    base = t.rolling_declaration(found).rolling
    assert base is not None
    for window, level, kappa in ((365, None, None), (365, 56, 0.5)):
        assert dataclasses.replace(
            base,
            window_days=window,
            command_windows=(365, 365),
            level_window_days=level,
            level_kappa=kappa,
            command_level_windows=(None, 56),
        ).command_windows == (365, 365)
    with pytest.raises(Exception, match="donnée deux fois"):
        dataclasses.replace(
            base,
            window_days=365,
            command_windows=(365, 365),
            level_window_days=56,
            level_kappa=0.5,
            command_level_windows=(56, 56),
        )


# --- L3 : le registre du format 6, relu et réécrit à l'octet ------------------------


def _format_6_copy(tmp_path: Path) -> Path:
    root = tmp_path / "registre"
    shutil.copytree(FORMAT_6, root)
    return root


def test_format_6_rewritten_to_the_byte(tmp_path: Path) -> None:
    root = _format_6_copy(tmp_path)
    data = (root / EVENTS_FILE).read_bytes()
    lines = data.split(b"\n")[:-1]
    assert [hashlib.sha256(line).hexdigest() for line in lines] == [
        DECLARATION_SHA256,
        RESULT_SHA256,
    ]
    log = verify_registry(root)
    assert [e.format_version for e in log.events] == [6, 6]
    for event, line in zip(log.events, lines, strict=True):
        assert _line(event) == line
    rolling = log.events[0].declaration
    assert rolling is not None
    assert rolling.rolling is not None
    found = rolling.rolling
    assert (found.level_window_days, found.level_kappa) == (None, None)
    assert found.command_level_windows is None
    assert found.rule == RULE_SHA256
    rule_bytes = (root / "documents" / f"{RULE_SHA256}.json").read_bytes()
    assert hashlib.sha256(rule_bytes).hexdigest() == RULE_SHA256
    rule = decode_document(rule_bytes, RollingRule, 6)
    assert encode_document(rule, 6) == rule_bytes
    raw = json.loads(lines[0])
    raw["declaration"]["rolling"]["level_window_days"] = None
    (root / EVENTS_FILE).write_bytes(canonical_bytes(raw) + b"\n" + lines[1] + b"\n")
    with pytest.raises(
        RegistryError, match="champ inconnu au format 6 : 'level_window_days'"
    ):
        read_registry(root)
    root = _format_6_copy(tmp_path / "neuf")
    last = verify_registry(root).events[-1].recorded_at
    written = append_declaration(
        root, declaration(), recorded_at=last + timedelta(minutes=1)
    )
    assert written.format_version == 7
    assert [e.format_version for e in verify_registry(root).events] == [6, 6, 7]


# --- L4 : l'accord sur une exécution en couches ---------------------------------------


def _layered_season() -> Any:
    """Douze trails de deux heures, du 14 au 25 mai 2026 à 08:00 UTC : à l'origine de
    Q20 (le 2026-05-13), aucune candidate (une absence) ; Q27 et P03 ont une courbe."""
    pairs = [
        activity_pair(
            f"m{day:02d}",
            datetime(2026, 5, day, 8, tzinfo=UTC),
            index_elapsed_s=None,
            recording_s=7200.0,
        )
        for day in range(14, 26)
    ]
    return corpus(pairs, athlete=ATHLETE)


def _layered_rule(level_window_days: int = 56) -> LayeredRollingRule:
    fields = {
        f.name: getattr(t.rule(), f.name) for f in dataclasses.fields(RollingRule)
    }
    return LayeredRollingRule(
        **{**fields, "window_days": 365},
        level_window_days=level_window_days,
        level_kappa=0.5,
    )


def _layered_world(
    monkeypatch: pytest.MonkeyPatch, mutate: t.Mutation | None = None
) -> t.World:
    with monkeypatch.context() as patch:
        patch.setattr(t, "WINDOW", LAYERED)
        patch.setattr(t, "season", _layered_season)
        return t.world(mutate)


def _agree_layered(built: t.World, rule: LayeredRollingRule) -> None:
    rolling = RollingDeclaration(
        rule=t._sha(_layered_rule()),
        window_days=365,
        command_windows=(365,),
        covered_threshold=0.1,
        beyond_marker=0.5,
        coverage_tolerance_s=60.0,
        index_sha256="b" * 64,
        platform="plateforme de test",
        performances=tuple(built.entries),
        level_window_days=56,
        level_kappa=0.5,
        command_level_windows=(56,),
    )
    declared = declaration(
        models=(V0_RAW, t.COMPARATOR),
        curve_ref=None,
        curve=None,
        curve_metadata=None,
        rolling=rolling,
    )
    stored = {t._sha(_layered_rule()): encode_document(rule)}
    for curve in built.curves:
        stored[t._sha(curve)] = encode_document(curve)
    registry_module._agree_rolling_documents(
        declared, rolling, stored.__getitem__, "", "", 7
    )


def _section(k: int, document: dict[str, Any]) -> dict[str, Any]:
    estimation = document.get("estimation")
    found: dict[str, Any] = (
        document["origin"] if estimation is None else estimation["origin"]
    )
    return found


def test_the_accord_on_layered(monkeypatch: pytest.MonkeyPatch) -> None:
    built = _layered_world(monkeypatch)
    statuses = [entry.status.value for entry in built.entries]
    assert statuses[0] == "absent"
    assert "absent" not in statuses[1:]
    first = built.curves[0]
    assert isinstance(first, AbsentCurve)
    assert json.loads(first.document)["origin"]["level_layer"] is None
    _agree_layered(built, _layered_rule())

    def kappa(k: int, document: dict[str, Any]) -> None:
        if k == 1:
            _section(k, document)["level_layer"]["kappa"] = 1.0

    def shifted(k: int, document: dict[str, Any]) -> None:
        if k == 1:
            layer = _section(k, document)["level_layer"]
            moved = datetime.fromisoformat(layer["level_lower_bound"])
            layer["level_lower_bound"] = (moved - timedelta(days=1)).isoformat()

    for mutate in (kappa, shifted):
        with pytest.raises(RegistryError, match="condition 2 ter"):
            _agree_layered(_layered_world(monkeypatch, mutate), _layered_rule())
    with pytest.raises(RegistryError, match="condition R"):
        _agree_layered(built, _layered_rule(level_window_days=28))

    def carried(k: int, document: dict[str, Any]) -> None:
        if k == 0:
            _section(k, document)["level_layer"] = None

    window = t.world(carried)
    window_declaration = t.rolling_declaration(window)
    window_rolling = window_declaration.rolling
    stored = {t._sha(t.rule()): encode_document(t.rule())}
    for curve in window.curves:
        stored[t._sha(curve)] = encode_document(curve)
    with pytest.raises(RegistryError, match="condition 2 ter"):
        registry_module._agree_rolling_documents(
            window_declaration, window_rolling, stored.__getitem__, "", "", 7
        )


# --- Les textes sous layered --------------------------------------------------------


def test_layered_texts_everywhere() -> None:
    result, season = run(season_r(), LAYERED)
    lines = origin_summary_lines(result, date(2024, 4, 8))
    assert "règle en couches" in lines[0]
    assert "fenêtre tout le passé" not in lines[0]
    assert lines[1].startswith("niveau à mi-chemin : Δ = -0.0635, 1 activités récentes")
    course = course_origin(date(2024, 4, 8), date(2024, 4, 8))
    assert course.origin == ORIGIN
    found = origin_curve(
        season,
        course,
        LAYERED,
        generated_at=datetime(2024, 4, 8, tzinfo=PARIS),
        intervals_of=provider(R),
    )
    assert found.curve is not None
    assert found.curve.name.endswith("-layered.csv")
    assert not found.curve.name.endswith("-all.csv")
    companion = json.loads(found.curve.companion)
    assert "en couches" in companion["estimator"]
    assert "fenêtre all" not in companion["estimator"]
    assert window_label(LAYERED) == "layered"
    assert f"og2-2026-06-03-{window_label(LAYERED)}.csv" == "og2-2026-06-03-layered.csv"
    rolling = t.rolling_declaration(t.world()).rolling
    assert rolling is not None
    layered = dataclasses.replace(
        rolling,
        window_days=365,
        command_windows=(365,),
        level_window_days=56,
        level_kappa=0.5,
        command_level_windows=(56,),
    )
    assert cli._rule_label(layered) == LABEL
