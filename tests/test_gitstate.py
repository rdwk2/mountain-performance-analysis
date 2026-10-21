"""L'état git commun (``mountain_perf.gitstate``, AN1-2c) : le commit du dépôt qui
contient un dossier, l'arbre modifié ou non, et l'erreur qui dit pourquoi l'état ne se
lit pas. Les tests de ``backtest/execution.py`` restent ceux du moteur ; ceux-ci
lisent le module commun directement, dans des dépôts synthétiques."""

from __future__ import annotations

import codecs
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from mountain_perf import gitstate
from mountain_perf.backtest import execution
from mountain_perf.backtest.execution import BacktestError
from mountain_perf.gitstate import GitFailure, GitState, GitStateError, git_state

COMMIT = "0123456789abcdef" * 2 + "01234567"
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git absent")


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return completed.stdout


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    """Un dépôt synthétique : un fichier suivi, un commit fait sans dépendre de
    l'identité ni de la signature de la machine, un sous-dossier."""
    repository = tmp_path / "depot"
    (repository / "sous-dossier").mkdir(parents=True)
    _git(repository, "init", "-q")
    (repository / "suivi.txt").write_bytes(b"suivi\n")
    _git(repository, "add", "suivi.txt")
    _git(
        repository,
        "-c",
        "user.name=Synthetique",
        "-c",
        "user.email=synthetique@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-q",
        "-m",
        "commit synthétique",
    )
    return repository


@needs_git
def test_commit_and_clean_tree(repository: Path) -> None:
    state = git_state(repository / "sous-dossier")
    assert state == GitState(_git(repository, "rev-parse", "HEAD").strip(), False)
    assert re.fullmatch(r"[0-9a-f]{40}", state.commit)


@needs_git
def test_untracked_then_tracked_modification(repository: Path) -> None:
    (repository / "non-suivi.txt").write_bytes(b"x\n")
    assert git_state(repository).modified is False
    (repository / "suivi.txt").write_bytes(b"modifie\n")
    assert git_state(repository).modified is True
    _git(repository, "add", "suivi.txt")
    assert git_state(repository).modified is True


@needs_git
def test_outside_a_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outside = tmp_path / "hors"
    outside.mkdir()
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    with pytest.raises(GitStateError) as raised:
        git_state(outside)
    assert raised.value.failure is GitFailure.NOT_A_REPOSITORY
    assert str(raised.value) == "le code exécuté n'est pas dans un dépôt git"


def test_without_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "")
    with pytest.raises(GitStateError) as raised:
        git_state(tmp_path)
    assert raised.value.failure is GitFailure.GIT_MISSING
    assert str(raised.value) == "git introuvable"


def test_the_error_is_a_runtime_error_not_a_backtest_error() -> None:
    """L'erreur commune ne dépend pas du moteur : ``analyse/`` n'importe jamais
    ``backtest/``."""
    error = GitStateError(GitFailure.GIT_MISSING)
    assert isinstance(error, RuntimeError)
    assert not isinstance(error, BacktestError)
    assert [f.value for f in GitFailure] == ["git_missing", "not_a_repository"]


def test_the_two_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``git rev-parse HEAD``, puis ``git --no-optional-locks status --porcelain
    --untracked-files=no`` ; une sortie non vide du statut : modifié."""
    calls: list[list[str]] = []

    def fake(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        stdout = f"{COMMIT}\n" if "rev-parse" in arguments else " M suivi.txt\n"
        return subprocess.CompletedProcess(arguments, 0, stdout, "")

    monkeypatch.setattr(subprocess, "run", fake)
    assert git_state(tmp_path) == GitState(COMMIT, True)
    directory = str(tmp_path)
    assert calls == [
        ["git", "-C", directory, "rev-parse", "HEAD"],
        [
            "git",
            "-C",
            directory,
            "--no-optional-locks",
            "status",
            "--porcelain",
            "--untracked-files=no",
        ],
    ]


def test_git_is_read_in_utf8_on_every_system(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La sortie de git se lit en UTF-8, pas dans l'encodage du système (cp1252 sous
    Windows, où un chemin non ASCII écrit sans échappement par ``core.quotePath=false``
    pourrait faire échouer la lecture)."""
    seen: list[dict[str, Any]] = []

    def fake(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen.append(kwargs)
        stdout = f"{COMMIT}\n" if "rev-parse" in arguments else ""
        return subprocess.CompletedProcess(arguments, 0, stdout, "")

    monkeypatch.setattr(subprocess, "run", fake)
    assert git_state(tmp_path) == GitState(COMMIT, False)
    assert len(seen) == 2
    for kwargs in seen:
        assert codecs.lookup(kwargs["encoding"]).name == "utf-8"


def test_a_failing_status_is_outside_a_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le commit se lit, le statut échoue : la même erreur que hors d'un dépôt."""

    def fake(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        code = 0 if "rev-parse" in arguments else 128
        return subprocess.CompletedProcess(arguments, code, f"{COMMIT}\n", "")

    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(GitStateError) as raised:
        git_state(tmp_path)
    assert raised.value.failure is GitFailure.NOT_A_REPOSITORY


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (
            GitFailure.GIT_MISSING,
            "git introuvable : just backtest enregistre le commit du code exécuté.",
        ),
        (
            GitFailure.NOT_A_REPOSITORY,
            "le code exécuté n'est pas dans un dépôt git : just backtest enregistre "
            "son commit (0010 D14).",
        ),
    ],
)
def test_the_backtest_keeps_its_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: GitFailure, message: str
) -> None:
    """``backtest/execution.py`` convertit chaque échec du module commun en
    ``BacktestError``, avec ses messages d'avant AN1-2c, sans chaîner l'erreur
    commune."""

    def fails(directory: Path) -> GitState:
        raise GitStateError(failure)

    monkeypatch.setattr(execution, "common_git_state", fails)
    with pytest.raises(BacktestError) as raised:
        execution.git_state(tmp_path)
    assert type(raised.value) is BacktestError
    assert str(raised.value) == message
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True


def test_the_backtest_reexports_the_common_state() -> None:
    assert execution.GitState is GitState
    assert vars(execution)["common_git_state"] is gitstate.git_state
