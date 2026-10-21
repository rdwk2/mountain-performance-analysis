"""``mperf q1`` (AN1-2c, ``docs/decisions/0015``) : ``MPA_DATA_DIR/processed`` →
``MPA_DATA_DIR/resultats/Q1/<date>_<empreinte>/``, sur les tables que ``mperf tables``
écrit depuis l'``interim/`` synthétique de ``tests/fixtures/processed.py``. Le dossier
des données est celui que ``conftest.py`` pose pour chaque test ; l'état git du paquet
et la date du jour sont fixés, sauf dans les tests qui les changent."""

from __future__ import annotations

import dataclasses
import json
import re
import sys
import types
from datetime import date
from pathlib import Path, PureWindowsPath

import pytest

import mountain_perf
import mountain_perf.analyse
from fixtures.figure import activity, climb, same_in_every_variant, start, tables_of
from fixtures.processed import COMMIT, write_interim
from mountain_perf import cli, gitstate
from mountain_perf.analyse import q1 as q1_module
from mountain_perf.analyse import results as results_module
from mountain_perf.cli import main
from mountain_perf.config import data_dir
from mountain_perf.gitstate import GitFailure, GitState, GitStateError
from mountain_perf.schemas.processed import GradeStratum

DAY = date(2026, 10, 19)
OTHER_COMMIT = "b" * 40
RESULTS = Path("resultats") / "Q1"
REAL_TODAY = cli._today
"""``cli._today`` avant que ``fixed_world`` ne le fixe."""


@pytest.fixture(autouse=True)
def fixed_world(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Un clone propre au commit des fixtures, le 2026-10-19 ; rend les dossiers dont
    l'état git est lu."""
    seen: list[Path] = []

    def state(directory: Path) -> GitState:
        seen.append(directory)
        return GitState(COMMIT, False)

    monkeypatch.setattr(gitstate, "git_state", state)
    monkeypatch.setattr(cli, "_today", lambda: DAY)
    return seen


def _tables(capsys: pytest.CaptureFixture[str]) -> Path:
    """Les tables de ``processed/``, écrites par ``mperf tables`` ; la sortie de la
    commande est consommée."""
    pytest.importorskip("pyarrow")
    folder = data_dir()
    write_interim(folder)
    assert main(["tables"]) == 0
    capsys.readouterr()
    return folder


def _folders() -> list[str]:
    root = data_dir() / RESULTS
    return sorted(p.name for p in root.iterdir()) if root.exists() else []


def test_cli_q1_writes_the_results_and_says_what_it_wrote(
    capsys: pytest.CaptureFixture[str], fixed_world: list[Path]
) -> None:
    pytest.importorskip("plotly")
    folder = _tables(capsys)
    assert main(["q1"]) == 0
    (name,) = _folders()
    assert re.fullmatch(r"2026-10-19_[0-9a-f]{12}", name)
    assert capsys.readouterr().out.splitlines() == [
        "Vue principale :",
        "  long_climb : 0 points montrés, 1 cachés, 0 instables",
        "  short_climb : 0 points montrés, 1 cachés, 0 instables",
        "  ski_touring : 0 points montrés, 0 cachés, 0 instables",
        "Vue sans_instables :",
        "  long_climb : 0 points montrés, 1 cachés",
        "  short_climb : 0 points montrés, 1 cachés",
        "  ski_touring : 0 points montrés, 0 cachés",
        "Changements d'appareil : 0",
        f"-> resultats/Q1/{name}/",
    ]
    written = folder / RESULTS / name
    assert sorted(p.name for p in written.iterdir()) == [
        "figure.html",
        "flux.csv",
        "points.csv",
        "provenance.json",
    ]
    document = json.loads((written / "provenance.json").read_text(encoding="utf-8"))
    assert document["commit"] == COMMIT
    assert document["tables"]["commit"] == COMMIT
    assert document["version_du_paquet"] == mountain_perf.__version__
    assert document["genere_le"] == "2026-10-19"
    assert fixed_world == [Path(mountain_perf.__file__).resolve().parent] * 2


def test_cli_q1_says_when_the_tables_come_from_another_commit(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Les tables écrites au commit des fixtures, la figure à un autre : la figure
    s'écrit, et une ligne le dit, avec le commit des tables."""
    pytest.importorskip("plotly")
    _tables(capsys)
    monkeypatch.setattr(
        gitstate, "git_state", lambda directory: GitState(OTHER_COMMIT, False)
    )
    assert main(["q1"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[-2] == (
        f"Tables écrites par un autre commit ({COMMIT[:12]}) : relancer just process "
        "si leur calcul a changé."
    )
    (name,) = _folders()
    document = json.loads(
        (data_dir() / RESULTS / name / "provenance.json").read_text(encoding="utf-8")
    )
    assert (document["commit"], document["tables"]["commit"]) == (OTHER_COMMIT, COMMIT)


def test_cli_q1_never_rewrites_a_result(capsys: pytest.CaptureFixture[str]) -> None:
    """Le même jour, les mêmes tables et le même code : le même dossier, refusé."""
    pytest.importorskip("plotly")
    _tables(capsys)
    assert main(["q1"]) == 0
    (name,) = _folders()
    capsys.readouterr()
    assert main(["q1"]) == 1
    assert capsys.readouterr().err == (
        f"Erreur : resultats/Q1/{name}/ existe déjà : rien n'est réécrit\n"
    )
    assert _folders() == [name]


def test_cli_q1_another_day_writes_another_folder(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("plotly")
    _tables(capsys)
    assert main(["q1"]) == 0
    monkeypatch.setattr(cli, "_today", lambda: date(2026, 10, 20))
    assert main(["q1"]) == 0
    first, second = _folders()
    assert first.startswith("2026-10-19_")
    assert second.startswith("2026-10-20_")
    assert first[11:] == second[11:]


def test_cli_q1_without_tables(capsys: pytest.CaptureFixture[str]) -> None:
    pytest.importorskip("pyarrow")
    pytest.importorskip("plotly")
    assert main(["q1"]) == 1
    assert (
        capsys.readouterr().err
        == "Erreur : aucune table dans processed/ : lancer just process\n"
    )
    assert not (data_dir() / "resultats").exists()


def test_cli_q1_on_tables_from_before_the_variants(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Des tables d'avant AN1-2c (sans ``variantes.parquet``) : le message dit de
    relancer ``just process``."""
    pytest.importorskip("plotly")
    folder = _tables(capsys)
    (folder / "processed" / "variantes.parquet").unlink()
    assert main(["q1"]) == 1
    assert capsys.readouterr().err == (
        "Erreur : les tables de processed/ datent d'avant AN1-2c (sans "
        "variantes.parquet) : relancer just process\n"
    )
    assert not (data_dir() / "resultats").exists()


def test_cli_q1_refuses_a_modified_clone(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un fichier suivi modifié : le message, code 1, sans lire les tables (il n'y
    en a pas) ni rien écrire."""
    pytest.importorskip("pyarrow")
    pytest.importorskip("plotly")
    monkeypatch.setattr(gitstate, "git_state", lambda directory: GitState(COMMIT, True))
    assert main(["q1"]) == 1
    assert capsys.readouterr().err == (
        "Erreur : un fichier suivi du code exécuté est modifié : mperf q1 écrit le "
        "commit du code dans ses résultats (CHARTE, § 10). Committer ou annuler la "
        "modification.\n"
    )
    assert not (data_dir() / "resultats").exists()


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (GitFailure.GIT_MISSING, "git introuvable"),
        (GitFailure.NOT_A_REPOSITORY, "le code exécuté n'est pas dans un dépôt git"),
    ],
)
def test_cli_q1_without_a_git_state(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    failure: GitFailure,
    message: str,
) -> None:
    pytest.importorskip("plotly")
    _tables(capsys)

    def fails(directory: Path) -> GitState:
        raise GitStateError(failure)

    monkeypatch.setattr(gitstate, "git_state", fails)
    assert main(["q1"]) == 1
    assert capsys.readouterr().err == f"Erreur : {message}\n"
    assert not (data_dir() / "resultats").exists()


def test_cli_q1_without_a_data_folder(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("pyarrow")
    pytest.importorskip("plotly")
    monkeypatch.setenv("MPA_DATA_DIR", "")
    assert main(["q1"]) == 1
    assert capsys.readouterr().err.startswith("Erreur : ")


def test_cli_q1_reads_mpa_data_dir_before_the_git_state(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sans ``MPA_DATA_DIR`` et hors d'un dépôt git : ``MPA_DATA_DIR`` se lit
    d'abord, et seul son message est dit."""
    pytest.importorskip("pyarrow")
    pytest.importorskip("plotly")
    monkeypatch.setenv("MPA_DATA_DIR", "")

    def fails(directory: Path) -> GitState:
        raise GitStateError(GitFailure.NOT_A_REPOSITORY)

    monkeypatch.setattr(gitstate, "git_state", fails)
    assert main(["q1"]) == 1
    assert capsys.readouterr().err.startswith(
        "Erreur : La variable d'environnement MPA_DATA_DIR n'est pas définie."
    )


@pytest.mark.parametrize(
    ("missing", "module"),
    [
        ("pyarrow", "mountain_perf.analyse.parquet"),
        ("plotly", "mountain_perf.analyse.plot"),
    ],
)
def test_cli_q1_without_the_extra_says_how_to_install(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    missing: str,
    module: str,
) -> None:
    """pyarrow ou plotly absent (``None`` dans ``sys.modules``) : un message, code 1,
    sans rien lire ; le sous-module est retiré pour que son import soit refait
    (``tests/test_cli_tables.py``)."""
    name = module.rsplit(".", 1)[1]
    monkeypatch.delitem(sys.modules, module, raising=False)
    monkeypatch.setattr(
        mountain_perf.analyse, name, types.ModuleType(module), raising=False
    )
    monkeypatch.setitem(sys.modules, missing, None)
    assert main(["q1"]) == 1
    assert capsys.readouterr().err == (
        "Erreur : la figure de Q1 demande l'extra analyse. Installer : uv sync "
        "--extra analyse\n"
    )
    assert not (data_dir() / "resultats").exists()


@pytest.mark.parametrize(
    "module", ["mountain_perf.analyse.parquet", "mountain_perf.analyse.plot"]
)
def test_cli_q1_does_not_hide_another_missing_module(
    monkeypatch: pytest.MonkeyPatch, module: str
) -> None:
    """Un sous-module de la piste qui manque se propage ; sans pyarrow, la lecture
    des tables s'importe la première et l'extra se dit, d'où le saut."""
    pytest.importorskip("pyarrow")
    monkeypatch.setitem(sys.modules, module, None)
    with pytest.raises(ModuleNotFoundError):
        main(["q1"])


def test_mperf_help_lists_the_q1_subcommand(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("COLUMNS", "200")
    with pytest.raises(SystemExit) as stop:
        main(["--help"])
    assert stop.value.code == 0
    assert (
        "Écrire la figure de Q1 sous MPA_DATA_DIR/resultats/Q1 (AN1-2c)"
        in capsys.readouterr().out
    )


def test_the_results_are_not_written_into_tmp_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pytest.importorskip("plotly")
    _tables(capsys)
    assert main(["q1"]) == 0
    assert list(tmp_path.iterdir()) == []


# --- les relectures du prototype (AN1-2c) ----------------------------------------


def test_cli_q1_counts_the_shown_hidden_and_unstable_points(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le résumé, sur une figure qui a des points montrés, un point instable, un
    point au résumé non positif (ni montré ni caché) et un changement d'appareil : la
    figure des tables synthétiques n'en a pas, elle est remplacée par celle-ci."""
    pytest.importorskip("plotly")
    _tables(capsys)
    activities = [
        activity(f"w{i}", start(i), device_product=1 if i < 3 else 2) for i in range(5)
    ]
    climbs = [climb(f"w{i}", start(i), 600, 2400, 300, 1800) for i in range(5)]
    climbs.append(
        dataclasses.replace(
            climb("w1", start(1), 3000, 3600, 5, 600, grade=GradeStratum.STEEP),
            moving_gain_m_by_convention=(-30.0,) * 5,
        )
    )
    rows = [r for r in same_in_every_variant(climbs) if r.activity_ref != "w0"]
    figure = q1_module.q1_figure(tables_of(activities, climbs, rows))
    monkeypatch.setattr(q1_module, "q1_figure", lambda tables: figure)
    assert main(["q1"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[:4] == [
        "Vue principale :",
        "  long_climb : 5 points montrés, 0 cachés, 1 instables",
        "  short_climb : 0 points montrés, 0 cachés, 0 instables",
        "  ski_touring : 0 points montrés, 0 cachés, 0 instables",
    ]
    assert lines[5] == "  long_climb : 5 points montrés, 0 cachés"
    assert lines[8] == "Changements d'appareil : 1"


def test_cli_q1_on_a_damaged_table(capsys: pytest.CaptureFixture[str]) -> None:
    """``montees.parquet`` tronqué : « Erreur : », code 1, la table nommée, sans
    chemin absolu, rien d'écrit."""
    pytest.importorskip("plotly")
    folder = _tables(capsys)
    path = folder / "processed" / "montees.parquet"
    path.write_bytes(path.read_bytes()[:200])
    assert main(["q1"]) == 1
    assert capsys.readouterr().err == (
        "Erreur : montees.parquet ne se relit pas : relancer just process\n"
    )
    assert not (data_dir() / "resultats").exists()


def test_cli_q1_names_the_folder_with_slashes(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sous Windows, ``RESULTS_DIR / nom`` s'écrirait avec des ``\\`` : la dernière
    ligne dit ``resultats/Q1/<nom>/`` sur toutes les plateformes."""
    pytest.importorskip("plotly")
    _tables(capsys)
    monkeypatch.setattr(
        results_module, "RESULTS_DIR", PureWindowsPath("resultats", "Q1")
    )
    assert main(["q1"]) == 0
    (name,) = _folders()
    assert capsys.readouterr().out.splitlines()[-1] == f"-> resultats/Q1/{name}/"


def test_the_day_of_the_folder_is_today() -> None:
    """La date du dossier de résultats est la date locale du jour (les autres tests
    la fixent)."""
    before = date.today()
    today = REAL_TODAY()
    assert today in (before, date.today())
