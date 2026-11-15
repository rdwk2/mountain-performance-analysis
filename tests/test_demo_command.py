"""La commande des profils de démo (M5-3, § 6.3 du brief), testée par ``main([...])`` :
la racine du dépôt remplacée par un dossier temporaire ``R`` (un ``pyproject.toml``
vide et un dossier ``.git``), l'état git par un clone propre, l'horloge des commandes
par T0 = 2026-11-13 12:00 UTC, et les entrées par la version réduite. La commande ne se
lance jamais sur la vraie racine ni sur le vrai dossier des données. Puis le
déterminisme du générateur, dans deux sous-processus, et l'absence d'horloge."""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from importlib.machinery import ModuleSpec
from pathlib import Path
from typing import Any

import pytest

import mountain_perf
from demo_world import DemoBuild, built
from mountain_perf import cli, gitstate
from mountain_perf.cli import main
from mountain_perf.config import DATA_DIR_ENV_VAR, data_dir
from mountain_perf.demo import construction
from mountain_perf.demo.constantes import CHARACTER_NAMES
from mountain_perf.demo.construction import (
    DemoError,
    InputsSummary,
    Mark,
    generate_inputs,
    read_mark,
    repository_root,
)
from mountain_perf.demo.personnages import character
from mountain_perf.gitstate import GitFailure, GitState, GitStateError

pytest.importorskip("fitdecode")
pytest.importorskip("pyarrow")

T0 = date(2026, 11, 13)
NOW = datetime(2026, 11, 13, 12, tzinfo=UTC)
COMMIT = "0" * 40
GENERATE = construction.generate_inputs
SOURCE = Path(mountain_perf.__file__).parent
DETERMINISTIC_MODULES = (
    "constantes.py",
    "personnages.py",
    "parcours.py",
    "gpx.py",
    "fit.py",
    "sorties.py",
    "jours.py",
)
"""Les modules du § 6.0 (« Le déterminisme »)."""

EXTRAS = (
    "Erreur : mperf demo demande les extras ingest et analyse (et tableau pour "
    "--interface) : uv run --extra ingest --extra analyse --extra tableau mperf demo "
    "{name} --interface.\n"
)
MODIFIED = (
    "Erreur : mperf demo construit le dossier par les commandes du dépôt, qui refusent "
    "un arbre modifié : un fichier suivi est modifié (git status) ; rien n'est écrit.\n"
)
REGENERATE = " ; pour le régénérer, supprime-le"
STEEP_LINE = "la course raide (le 2026-11-18) est passée"
TWO_PARTS_LINE = (
    "la course à deux parties (le 2026-12-04) est à 7 jours ou moins : son origine "
    "n'est plus bornée"
)
WINDOW_LINE = (
    "au jour par défaut, la fenêtre de 56 jours ne contient plus aucune activité"
)


@pytest.fixture(autouse=True)
def _world(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un clone propre, l'horloge à T0 12:00 UTC, la version réduite forcée."""
    monkeypatch.setattr(
        gitstate, "git_state", lambda directory: GitState(COMMIT, False)
    )
    monkeypatch.setattr(cli, "_now", lambda: NOW)
    monkeypatch.setattr(
        construction,
        "generate_inputs",
        lambda character, folder, t0, **_: GENERATE(
            character, folder, t0, reduced=True
        ),
    )


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """La racine remplacée : un ``pyproject.toml`` vide et un dossier ``.git``."""
    found = tmp_path / "R"
    found.mkdir()
    (found / "pyproject.toml").write_text("", encoding="utf-8")
    (found / ".git").mkdir()
    monkeypatch.setattr(construction, "repository_root", lambda: found)
    return found


def _snapshot(folder: Path) -> dict[str, tuple[bytes, int]]:
    """Chaque fichier sous ``folder`` : ses octets et sa date de modification."""
    return {
        path.relative_to(folder).as_posix(): (
            path.read_bytes(),
            path.stat().st_mtime_ns,
        )
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def _listing(folder: Path) -> list[str]:
    return sorted(path.relative_to(folder).as_posix() for path in folder.rglob("*"))


def _copy(build: DemoBuild, root: Path, name: str) -> Path:
    target = root / "demo" / name
    shutil.copytree(build.folder, target)
    return target


def _at(day: int, monkeypatch: pytest.MonkeyPatch) -> None:
    moment = NOW + timedelta(days=day)
    monkeypatch.setattr(cli, "_now", lambda: moment)


def _without(missing: str, monkeypatch: pytest.MonkeyPatch) -> None:
    original: Callable[..., ModuleSpec | None] = importlib.util.find_spec

    def find_spec(name: str, package: str | None = None) -> ModuleSpec | None:
        return None if name == missing else original(name, package)

    monkeypatch.setattr(importlib.util, "find_spec", find_spec)


# --- La racine ---------------------------------------------------------------------


def test_the_real_root() -> None:
    assert (repository_root() / "pyproject.toml").exists()
    assert (repository_root() / "src" / "mountain_perf" / "cli.py").exists()


# --- Le dossier absent : la construction ------------------------------------------


def test_the_data_folder_is_never_touched(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = data_dir()
    (data / "canari.txt").write_text("canari", encoding="utf-8")
    before = _snapshot(data)
    variable = os.environ[DATA_DIR_ENV_VAR]
    assert main(["demo", "debutant"]) == 0
    folder = root / "demo" / "debutant"
    written = json.loads((folder / "demo.json").read_bytes().decode("utf-8"))
    assert written == {
        "built_on": "2026-11-13",
        "character": "debutant",
        "generator": 1,
        "reduced": True,
        "seed": 11,
    }
    assert _snapshot(data) == before
    assert os.environ[DATA_DIR_ENV_VAR] == variable
    assert sorted(p.name for p in root.iterdir()) == [".git", "demo", "pyproject.toml"]
    assert [p.name for p in (root / "demo").iterdir()] == ["debutant"]
    lines = capsys.readouterr().out.splitlines()
    assert lines[-2:] == [
        f"dossier de démo : {folder} (personnage débutant, construit le 2026-11-13)",
        "courses en vue : course_raide.gpx le 2026-11-18 ; deux_parties.gpx le "
        "2026-12-04",
    ]
    assert (folder / "reference" / "plage.csv").exists()
    mark = read_mark(folder)
    assert isinstance(mark, Mark)
    assert (mark.built_on, mark.character, mark.generator, mark.reduced, mark.seed) == (
        date(2026, 11, 13),
        "debutant",
        1,
        True,
        11,
    )


def test_a_folder_without_mark_is_refused(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = root / "demo" / "debutant"
    folder.mkdir(parents=True)
    (folder / "x").write_text("x", encoding="utf-8")
    before = _listing(root)
    assert main(["demo", "debutant"]) == 1
    assert capsys.readouterr().err == (
        f"Erreur : Le dossier {folder} existe sans la marque demo.json : construction "
        "interrompue, ou dossier étranger. Rien n'est écrit ; pour le reconstruire, "
        "supprime-le.\n"
    )
    assert _listing(root) == before


def test_an_interrupted_build_has_no_mark(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = root / "demo" / "debutant"
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(cli, "_run_curve", lambda args: 1)
        assert main(["demo", "debutant"]) == 1
    assert capsys.readouterr().err == (
        "Erreur : la construction s'arrête à « mperf curve » (code 1) : le dossier "
        "reste sans marque ; supprime-le avant de relancer.\n"
    )
    assert folder.is_dir()
    assert not (folder / "demo.json").exists()
    assert main(["demo", "debutant"]) == 1
    assert "existe sans la marque demo.json" in capsys.readouterr().err


def test_a_modified_tree_refuses_to_build(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(gitstate, "git_state", lambda directory: GitState(COMMIT, True))
    assert main(["demo", "debutant"]) == 1
    assert capsys.readouterr().err == MODIFIED
    assert not (root / "demo").exists()


def test_a_git_state_error_is_said(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def failing(directory: Path) -> GitState:
        raise GitStateError(GitFailure.NOT_A_REPOSITORY)

    monkeypatch.setattr(gitstate, "git_state", failing)
    assert main(["demo", "debutant"]) == 1
    assert capsys.readouterr().err == (
        "Erreur : le code exécuté n'est pas dans un dépôt git\n"
    )
    assert not (root / "demo").exists()


@pytest.mark.parametrize("missing", ["fitdecode", "pyarrow"])
def test_a_missing_build_extra_refuses(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    missing: str,
) -> None:
    _without(missing, monkeypatch)
    assert main(["demo", "debutant"]) == 1
    assert capsys.readouterr().err == EXTRAS.format(name="debutant")
    assert not (root / "demo").exists()


# --- Le dossier marqué : rien n'est écrit -----------------------------------------


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (5, []),
        (6, [STEEP_LINE]),
        (13, [STEEP_LINE]),
        (14, [STEEP_LINE, TWO_PARTS_LINE]),
        (61, [STEEP_LINE, TWO_PARTS_LINE]),
        (62, [STEEP_LINE, TWO_PARTS_LINE, WINDOW_LINE]),
    ],
)
def test_aging_lines(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path_factory: pytest.TempPathFactory,
    day: int,
    expected: list[str],
) -> None:
    folder = _copy(built("debutant", tmp_path_factory), root, "debutant")
    before = _snapshot(root)
    _at(day, monkeypatch)
    assert main(["demo", "debutant"]) == 0
    assert _snapshot(root) == before
    assert capsys.readouterr().out.splitlines() == [
        f"dossier de démo : {folder} (personnage débutant, construit le "
        f"2026-11-13){REGENERATE}",
        "courses en vue : course_raide.gpx le 2026-11-18 ; deux_parties.gpx le "
        "2026-12-04",
        *expected,
    ]


def test_another_generator_version_is_said(
    root: Path,
    capsys: pytest.CaptureFixture[str],
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    folder = _copy(built("debutant", tmp_path_factory), root, "debutant")
    path = folder / "demo.json"
    mark = json.loads(path.read_bytes().decode("utf-8"))
    path.write_text(json.dumps({**mark, "generator": 0}), encoding="utf-8")
    assert main(["demo", "debutant"]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == (
        "construit par une autre version du générateur (0) ; pour le régénérer, "
        "supprime-le"
    )


def test_a_marked_folder_is_reused_on_a_modified_tree(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    _copy(built("debutant", tmp_path_factory), root, "debutant")
    before = _snapshot(root)
    monkeypatch.setattr(gitstate, "git_state", lambda directory: GitState(COMMIT, True))
    assert main(["demo", "debutant"]) == 0
    assert _snapshot(root) == before


def test_an_unreadable_mark(tmp_path: Path) -> None:
    (tmp_path / "demo.json").write_text('{"built_on": "2026-11-13"}', encoding="utf-8")
    with pytest.raises(DemoError) as raised:
        read_mark(tmp_path)
    assert str(raised.value) == f"marque illisible : {tmp_path / 'demo.json'}"
    assert read_mark(tmp_path / "absent") is None


# --- Pas un clone -----------------------------------------------------------------


@pytest.mark.parametrize("removed", ["pyproject.toml", ".git"])
def test_not_a_clone(
    root: Path, capsys: pytest.CaptureFixture[str], removed: str
) -> None:
    path = root / removed
    if path.is_dir():
        path.rmdir()
    else:
        path.unlink()
    assert main(["demo", "debutant"]) == 1
    assert capsys.readouterr().err == (
        f"Erreur : mperf demo se lance depuis un clone du dépôt : {root} n'en est pas "
        "un (pyproject.toml ou .git manque).\n"
    )


def test_a_git_file_is_a_clone(
    root: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    (root / ".git").rmdir()
    (root / ".git").write_text("gitdir: ailleurs\n", encoding="utf-8")
    _copy(built("debutant", tmp_path_factory), root, "debutant")
    assert main(["demo", "debutant"]) == 0


# --- L'interface ------------------------------------------------------------------


def _spy(
    monkeypatch: pytest.MonkeyPatch, raised: BaseException | None = None
) -> list[tuple[list[str], dict[str, Any]]]:
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def run(command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        calls.append((command, options))
        if raised is not None:
            raise raised
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("mountain_perf.demo.construction.subprocess.run", run)
    return calls


def test_the_interface_runs_streamlit(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    folder = _copy(built("polyvalente", tmp_path_factory), root, "polyvalente")
    calls = _spy(monkeypatch)
    assert main(["demo", "polyvalente", "--interface"]) == 0
    ((command, options),) = calls
    app = Path(mountain_perf.__file__).resolve().parent / "ui" / "app.py"
    assert command == [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app),
        "--server.port",
        "8512",
    ]
    assert options["cwd"] == root
    assert options["env"][DATA_DIR_ENV_VAR] == str(folder)
    assert capsys.readouterr().out.splitlines()[-1] == (
        "interface : http://localhost:8512 (Ctrl+C pour l'arrêter)"
    )


def test_ctrl_c_stops_the_interface(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    _copy(built("polyvalente", tmp_path_factory), root, "polyvalente")
    _spy(monkeypatch, KeyboardInterrupt())
    assert main(["demo", "polyvalente", "--interface"]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "interface arrêtée"


@pytest.mark.parametrize("interface", [True, False])
def test_without_streamlit(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path_factory: pytest.TempPathFactory,
    interface: bool,
) -> None:
    _copy(built("polyvalente", tmp_path_factory), root, "polyvalente")
    calls = _spy(monkeypatch)
    _without("streamlit", monkeypatch)
    options = ["--interface"] if interface else []
    code = main(["demo", "polyvalente", *options])
    if interface:
        assert code == 1
        assert capsys.readouterr().err == EXTRAS.format(name="polyvalente")
    else:
        assert code == 0
    assert calls == []


def test_an_unknown_name_exits_2() -> None:
    with pytest.raises(SystemExit) as stop:
        main(["demo", "x"])
    assert stop.value.code == 2


# --- La version réduite du cache ---------------------------------------------------


def test_every_field_of_a_demo_build(tmp_path_factory: pytest.TempPathFactory) -> None:
    build = built("debutant", tmp_path_factory)
    assert build.folder.name == "debutant"
    assert (build.folder / "demo.json").exists()
    assert build.summary == InputsSummary(
        date(2026, 10, 9), date(2026, 11, 12), 12, True
    )
    assert sorted(build.outputs) == ["curve", "ingest", "q1", "tables"]
    assert "Activités dans l'index : 12" in build.outputs["ingest"].splitlines()
    assert "-> reference/plage.csv" in build.outputs["curve"]


def test_every_field_of_the_inputs_summary(tmp_path: Path) -> None:
    summary = GENERATE(character("debutant"), tmp_path / "d", T0, reduced=True)
    assert (summary.first_day, summary.last_day, summary.outings, summary.reduced) == (
        date(2026, 10, 9),
        date(2026, 11, 12),
        12,
        True,
    )
    with pytest.raises(Exception, match="existe déjà"):
        generate_inputs(character("debutant"), tmp_path / "d", T0, reduced=True)


# --- Le déterminisme ---------------------------------------------------------------

GENERATION = (
    "import sys\n"
    "from datetime import date\n"
    "from pathlib import Path\n"
    "from mountain_perf.demo.construction import generate_inputs\n"
    "from mountain_perf.demo.personnages import character\n"
    "generate_inputs(character(sys.argv[1]), Path(sys.argv[2]), "
    "date.fromisoformat(sys.argv[3]), reduced=True)\n"
)


def _generate(name: str, folder: Path, seed: str, day: date = T0) -> None:
    subprocess.run(
        [sys.executable, "-c", GENERATION, name, str(folder), day.isoformat()],
        env={**os.environ, "PYTHONHASHSEED": seed},
        check=True,
    )


def _bytes(folder: Path) -> dict[str, bytes]:
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


@pytest.mark.parametrize("name", CHARACTER_NAMES)
def test_the_inputs_are_deterministic(tmp_path: Path, name: str) -> None:
    _generate(name, tmp_path / "a", "1")
    _generate(name, tmp_path / "b", "2")
    first, second = _bytes(tmp_path / "a"), _bytes(tmp_path / "b")
    assert first
    assert first == second


def test_another_day_changes_the_acquisition(tmp_path: Path) -> None:
    GENERATE(character("debutant"), tmp_path / "a", T0, reduced=True)
    GENERATE(
        character("debutant"), tmp_path / "b", T0 + timedelta(days=1), reduced=True
    )
    path = Path("raw") / "garmin" / "demo" / "acquisition.json"
    assert (tmp_path / "a" / path).read_bytes() != (tmp_path / "b" / path).read_bytes()


def test_the_generator_reads_no_clock() -> None:
    """Ni ``math``, ni ``time``, ni ``numpy`` ; aucun appel d'un attribut ``now``,
    ``today``, ``utcnow``, ``gauss``, ``normalvariate`` ou ``expovariate``."""
    forbidden_modules = {"math", "time", "numpy"}
    forbidden_calls = {
        "now",
        "today",
        "utcnow",
        "gauss",
        "normalvariate",
        "expovariate",
    }
    for name in DETERMINISTIC_MODULES:
        tree = ast.parse((SOURCE / "demo" / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = {alias.name.split(".")[0] for alias in node.names}
                assert not modules & forbidden_modules, name
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in forbidden_modules, name
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in forbidden_calls, (name, node.func.attr)
