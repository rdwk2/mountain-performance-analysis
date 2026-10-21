"""L'état git du code exécuté : son commit, et si un fichier suivi est modifié (M4b-5,
``0010`` D14 ; commun au moteur et à la piste analyse depuis AN1-2c).

``just backtest`` l'écrit dans son registre (``backtest/execution.py``, qui garde ses
messages) ; la piste analyse, dans la provenance de ses tables et de ses résultats.

Bibliothèque standard seule.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class GitFailure(StrEnum):
    """Pourquoi l'état git ne se lit pas."""

    GIT_MISSING = "git_missing"
    NOT_A_REPOSITORY = "not_a_repository"


class GitStateError(RuntimeError):
    """L'état git ne se lit pas : ``failure`` dit pourquoi (git introuvable, ou le
    dossier hors d'un dépôt)."""

    def __init__(self, failure: GitFailure) -> None:
        super().__init__(
            "git introuvable"
            if failure is GitFailure.GIT_MISSING
            else "le code exécuté n'est pas dans un dépôt git"
        )
        self.failure = failure


@dataclass(frozen=True)
class GitState:
    """Le commit du code exécuté et l'état de son arbre de travail : ``modified`` si
    un fichier suivi est modifié, indexé ou non (``0010`` D14)."""

    commit: str
    modified: bool


def _git(directory: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(directory), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except OSError:
        raise GitStateError(GitFailure.GIT_MISSING) from None
    if completed.returncode != 0:
        raise GitStateError(GitFailure.NOT_A_REPOSITORY)
    return completed.stdout


def git_state(directory: Path) -> GitState:
    """L'état git du dépôt qui contient ``directory`` (précision de D14, M4b-5 ;
    décision Q7) : ``git rev-parse HEAD``, puis ``git --no-optional-locks status
    --porcelain --untracked-files=no``, modifié si sa sortie n'est pas vide — un
    fichier non suivi ne compte pas. Le statut ne rafraîchit pas l'index : aucun
    verrou ``.git/index.lock`` n'est posé (M4c-2). :class:`GitStateError` sans
    ``git``, ou hors d'un dépôt."""
    commit = _git(directory, "rev-parse", "HEAD").strip()
    # --no-optional-locks : le statut lit l'index sans le réécrire, donc sans verrou.
    status = _git(
        directory,
        "--no-optional-locks",
        "status",
        "--porcelain",
        "--untracked-files=no",
    )
    return GitState(commit, status != "")
