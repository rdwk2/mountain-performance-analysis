"""Les versions réduites des profils de démo, construites une fois par processus de
tests (M5-3, § 6.4 (a) du brief) et partagées par les fichiers qui en ont besoin.

``built(name, factory)`` construit la version réduite d'un personnage à T0 =
2026-11-13 par ``build_folder``, dans ``factory.mktemp("demo") / name``, l'état git du
paquet remplacé par un clone propre le temps de la construction, ``MPA_DATA_DIR``
rétabli à la sortie ; ``run`` enveloppe ``main`` et garde la sortie standard de chaque
commande. N'importe ni Streamlit ni fitdecode.
"""

from __future__ import annotations

import contextlib
import io
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from mountain_perf import gitstate
from mountain_perf.cli import main
from mountain_perf.config import DATA_DIR_ENV_VAR
from mountain_perf.demo.construction import InputsSummary, build_folder
from mountain_perf.demo.personnages import character
from mountain_perf.gitstate import GitState

T0 = date(2026, 11, 13)
"""Le jour de construction des versions réduites des tests."""

COMMIT = "0" * 40
"""Le commit du clone propre que voit la construction."""


@dataclass(frozen=True)
class DemoBuild:
    """Une version réduite construite : son dossier, le résumé que rend
    ``build_folder``, la sortie standard de chaque commande de la chaîne (par nom)."""

    folder: Path
    summary: InputsSummary
    outputs: dict[str, str]


_BUILT: dict[str, DemoBuild] = {}


def built(name: str, factory: pytest.TempPathFactory) -> DemoBuild:
    """La version réduite du personnage ``name``, construite au premier appel du
    processus, puis rendue telle quelle."""
    found = _BUILT.get(name)
    if found is not None:
        return found
    folder = factory.mktemp("demo") / name
    outputs: dict[str, str] = {}

    def run(arguments: Sequence[str]) -> int:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(list(arguments))
        outputs[arguments[0]] = buffer.getvalue()
        return code

    before = os.environ.get(DATA_DIR_ENV_VAR)
    with patch.object(gitstate, "git_state", lambda directory: GitState(COMMIT, False)):
        summary = build_folder(character(name), folder, T0, run, reduced=True)
    assert os.environ.get(DATA_DIR_ENV_VAR) == before
    _BUILT[name] = DemoBuild(folder, summary, outputs)
    return _BUILT[name]
