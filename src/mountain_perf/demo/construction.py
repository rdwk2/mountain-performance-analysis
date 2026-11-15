"""La construction d'un dossier de démo (M5-3, ``docs/decisions/0022``) : les entrées
brutes, puis la chaîne des vraies commandes, puis la marque ; la racine du dépôt, les
contrôles de la commande et l'interface.

Le module n'importe pas ``cli`` : la commande lui passe ``main`` (``run``). Il ne lit
jamais l'horloge (T0 lui est donné) et ne supprime rien.
"""

import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

import mountain_perf
from mountain_perf.demo.constantes import DEMO_VERSION
from mountain_perf.demo.jours import write_days, write_journal
from mountain_perf.demo.personnages import Character
from mountain_perf.demo.sorties import write_export, write_routes
from mountain_perf.validation import ContractError

DATA_DIR_VARIABLE: Final = "MPA_DATA_DIR"
"""La variable du dossier des données, posée autour de chaque commande de la chaîne."""

MARK_FILE: Final = "demo.json"
"""La marque d'un dossier construit, écrite en dernier."""

CURVE_NAME: Final = "plage"
"""Le nom de la courbe de plage de ``reference/``."""

EXTRAS_ERROR: Final = (
    "mperf demo demande les extras ingest et analyse (et tableau pour --interface) : "
    "uv run --extra ingest --extra analyse --extra tableau mperf demo {name} "
    "--interface."
)
"""Le message d'un extra manquant ; ``{name}``, le personnage."""

NOT_A_CLONE_ERROR: Final = (
    "mperf demo se lance depuis un clone du dépôt : {root} n'en est pas un "
    "(pyproject.toml ou .git manque)."
)
"""Le message d'une racine qui n'est pas un clone."""

STOPPED_ERROR: Final = (
    "la construction s'arrête à « mperf {command} » (code {code}) : le dossier reste "
    "sans marque ; supprime-le avant de relancer."
)
"""Le message d'une commande de la chaîne qui rend un code non nul."""


class DemoError(Exception):
    """Une faute de ``mperf demo`` : le message dit quoi faire."""


@dataclass(frozen=True)
class InputsSummary:
    """Ce que :func:`generate_inputs` a écrit : le premier et le dernier jour de
    l'historique, le nombre de sorties, et si c'est la version réduite."""

    first_day: date
    last_day: date
    outings: int
    reduced: bool


def generate_inputs(
    person: Character, folder: Path, t0: date, *, reduced: bool = False
) -> InputsSummary:
    """Les entrées brutes du personnage dans ``folder``, créé ici (``ContractError``
    s'il existe) : les préparés, l'export Garmin (activités et jours), la trace
    témoin et le journal."""
    if folder.exists():
        raise ContractError(f"le dossier existe déjà : {folder}")
    folder.mkdir(parents=True)
    write_routes(folder)
    summary = write_export(person, folder, t0, reduced=reduced)
    write_days(person, folder, t0, reduced=reduced)
    write_journal(person, folder, t0, reduced=reduced)
    return InputsSummary(summary.first_day, summary.last_day, summary.outings, reduced)


@contextmanager
def data_folder_env(folder: Path) -> Iterator[None]:
    """``MPA_DATA_DIR`` posé sur ``folder`` le temps du bloc ; à la sortie, même sur
    une exception, la valeur d'avant, ou l'absence."""
    before = os.environ.get(DATA_DIR_VARIABLE)
    os.environ[DATA_DIR_VARIABLE] = str(folder)
    try:
        yield
    finally:
        if before is None:
            os.environ.pop(DATA_DIR_VARIABLE, None)
        else:
            os.environ[DATA_DIR_VARIABLE] = before


def build_folder(
    person: Character,
    folder: Path,
    t0: date,
    run: Callable[[Sequence[str]], int],
    *,
    reduced: bool = False,
) -> InputsSummary:
    """Construit le dossier de démo : les entrées, puis, ``MPA_DATA_DIR`` sur
    ``folder``, ``mperf ingest``, ``mperf tables``, ``mperf q1`` et la courbe de
    plage ; un code non nul arrête tout
    (``DemoError``) ; en dernier, la marque. Rend le résumé des entrées."""
    summary = generate_inputs(person, folder, t0, reduced=reduced)
    steps: tuple[list[str], ...] = (
        ["ingest"],
        ["tables"],
        ["q1"],
        [
            "curve",
            CURVE_NAME,
            "--from",
            summary.first_day.isoformat(),
            "--to",
            summary.last_day.isoformat(),
            "--athlete",
            person.name,
        ],
    )
    with data_folder_env(folder):
        for arguments in steps:
            code = run(arguments)
            if code != 0:
                raise DemoError(STOPPED_ERROR.format(command=arguments[0], code=code))
    mark = {
        "built_on": t0.isoformat(),
        "character": person.name,
        "generator": DEMO_VERSION,
        "reduced": summary.reduced,
        "seed": person.seed,
    }
    (folder / MARK_FILE).write_text(
        json.dumps(mark, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return summary


@dataclass(frozen=True)
class Mark:
    """La marque d'un dossier construit : le jour de la construction (T0), le
    personnage, la version du générateur, la version réduite ou non, la graine."""

    built_on: date
    character: str
    generator: int
    reduced: bool
    seed: int


def read_mark(folder: Path) -> Mark | None:
    """La marque de ``folder`` ; ``None`` sans fichier ; ``DemoError`` pour un JSON qui
    n'a pas ses cinq clés, de leurs types."""
    path = folder / MARK_FILE
    if not path.exists():
        return None
    unreadable = DemoError(f"marque illisible : {path}")
    try:
        loaded = json.loads(path.read_bytes().decode("utf-8"))
        built_on = date.fromisoformat(loaded["built_on"])
        character, generator = loaded["character"], loaded["generator"]
        reduced, seed = loaded["reduced"], loaded["seed"]
    except (ValueError, KeyError, TypeError):
        raise unreadable from None
    if not (
        isinstance(character, str)
        and isinstance(generator, int)
        and not isinstance(generator, bool)
        and isinstance(reduced, bool)
        and isinstance(seed, int)
        and not isinstance(seed, bool)
    ):
        raise unreadable
    return Mark(built_on, character, generator, reduced, seed)


def repository_root() -> Path:
    """La racine du dépôt qui contient le paquet (la mise en page ``src/``)."""
    return Path(mountain_perf.__file__).resolve().parents[2]


def require_clone(root: Path) -> None:
    """``DemoError`` si ``root`` n'a pas de ``pyproject.toml`` ou de ``.git`` (un
    fichier dans un ``git worktree``) : un paquet installé hors d'un clone."""
    if not (root / "pyproject.toml").exists() or not (root / ".git").exists():
        raise DemoError(NOT_A_CLONE_ERROR.format(root=root))


def require_modules(names: Sequence[str], name: str) -> None:
    """``DemoError`` si l'un des modules ``names`` (ceux des extras) ne se trouve pas ;
    ``name``, le personnage, entre dans le message."""
    for module in names:
        if importlib.util.find_spec(module) is None:
            raise DemoError(EXTRAS_ERROR.format(name=name))


def launch_interface(root: Path, folder: Path, port: int) -> int:
    """L'interface sur ``folder`` : Streamlit lancé depuis ``root`` (sa configuration
    ``.streamlit/config.toml``), ``MPA_DATA_DIR`` sur ``folder`` dans l'environnement
    du sous-processus, sur ``port`` ; son code. Ctrl+C : « interface arrêtée », 0."""
    app = Path(mountain_perf.__file__).resolve().parent / "ui" / "app.py"
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app),
        "--server.port",
        str(port),
    ]
    try:
        return subprocess.run(
            command,
            cwd=root,
            env={**os.environ, DATA_DIR_VARIABLE: str(folder)},
            check=False,
        ).returncode
    except KeyboardInterrupt:
        print("interface arrêtée")
        return 0
