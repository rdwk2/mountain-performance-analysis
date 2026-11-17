"""Les exécutions de Q2 des tests de bout en bout (AN3-3b, C20, C21) : un monde inventé
écrit dans ``processed/``, des paramètres réduits (``power_draws = 3``,
``bootstrap_draws = 9``), une grille réduite à ``0`` et ``delta`` (validée par la
conception : la grille complète est tenue par les tests unitaires), un clone propre
et une date fixée. Les fonctions sont de premier niveau : un processus neuf ou un
processus « spawn » les importe."""

from __future__ import annotations

import dataclasses
import os
from datetime import date
from pathlib import Path

from fixtures.processed import COMMIT
from fixtures.q2_world import small_world
from mountain_perf.analyse.q2.parameters import Q2_PARAMETER_SPECS
from mountain_perf.analyse.q2.power import PowerGrids
from mountain_perf.analyse.tables import Tables
from mountain_perf.schemas import ParameterSet

DAY = date(2026, 11, 16)
REDUCED = {"power_draws": 3.0, "bootstrap_draws": 9.0}
BLAS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")


def reduced_parameters() -> ParameterSet:
    """Les seuils de Q2 aux tirages réduits."""
    return ParameterSet(Q2_PARAMETER_SPECS, REDUCED)


def reduced_grids(parameters: ParameterSet) -> PowerGrids:
    """La grille réduite des tests de bout en bout : ``0`` et ``delta``."""
    delta = parameters["delta"]
    return PowerGrids({1: (0.0, delta), 2: (0.0,), 3: (0.0, delta), 4: (0.0, delta)})


def world_tables(seed: int = 11, *, reverse: bool = False) -> Tables:
    """Les tables du monde des tests de bout en bout ; ``reverse`` : leurs lignes dans
    l'ordre inverse."""
    tables = small_world(seed)
    if not reverse:
        return tables
    return dataclasses.replace(
        tables,
        activities=tuple(reversed(tables.activities)),
        climbs=tuple(reversed(tables.climbs)),
    )


def write_world(data_dir: Path, seed: int = 11, *, reverse: bool = False) -> None:
    """Écrit les tables du monde dans ``data_dir/processed/``."""
    from mountain_perf.analyse.parquet import write_tables

    write_tables(data_dir, world_tables(seed, reverse=reverse))


def install() -> None:
    """Remplace, dans ce processus, l'état git (clone propre), la date du jour, les
    seuils et la grille de Q2 par ceux des tests."""
    from mountain_perf import cli, gitstate
    from mountain_perf.analyse.q2 import parameters, power
    from mountain_perf.gitstate import GitState

    gitstate.git_state = lambda directory: GitState(COMMIT, False)
    cli._today = lambda: DAY
    parameters.q2_parameters = reduced_parameters
    power.power_grids = reduced_grids


def run_power_in_new_process(data_dir: str, processus: int, reverse: bool) -> None:
    """Le corps d'un processus neuf de C20 : le monde, puis ``mperf q2 puissance``."""
    from mountain_perf.cli import main

    os.environ["MPA_DATA_DIR"] = data_dir
    write_world(Path(data_dir), reverse=reverse)
    install()
    code = main(["q2", "puissance", "--processus", str(processus)])
    raise SystemExit(code)


def blas_environment(_: int) -> tuple[str | None, ...]:
    """Les trois variables BLAS vues par le processus qui l'exécute."""
    return tuple(os.environ.get(name) for name in BLAS)
