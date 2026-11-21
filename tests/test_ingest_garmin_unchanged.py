"""Condition 1 de la piste (AN1-3, § 6.4 (n) du brief) : sur des exports Garmin seuls,
tout ce que l'ingestion et les tables écrivent dans ``interim/`` et ``processed/`` est
identique, octet pour octet, à ce qu'écrit ``main`` d'avant AN1-3 (``7bbeddb``) : mêmes
fichiers, mêmes octets, pas de fichier en plus.

Le monde n'emploie que des aides qui existent sur ``7bbeddb`` : ce fichier s'y exécute
tel quel, pour en relever les empreintes (imprimées, ``pytest -s``), recopiées ici en
liste littérale. Valeurs inventées (règle 1)."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path

import pytest

pytest.importorskip("fitdecode")
pytest.importorskip("pyarrow")

from fixtures.day_exports import write_acquisition, write_day
from fixtures.days import DAY, EXPORT_A, EXPORT_B
from fixtures.garmin_activities import write_activities_export
from fixtures.processed import COMMIT
from mountain_perf import gitstate
from mountain_perf.cli import main
from mountain_perf.config import data_dir
from mountain_perf.gitstate import GitState

EXPECTED: list[tuple[str, str]] = [
    (
        "interim/activities/index.json",
        "33911ec4e1a803c9ee4e50ad652081aa480945eb6095d73600fb2727bc59a5e3",
    ),
    (
        "interim/activities/recordings/11.json",
        "1ef98a5c47ca813bd486b02b5139e17580d57288c38cbe9be3d5665cc3e7cac1",
    ),
    (
        "interim/activities/report.json",
        "6083391434df5d7c8be67ac0cbded1b0fc03e569e39309ddac262cbde6555bff",
    ),
    (
        "interim/days/2001-03-10.json",
        "682abb7092e930dc88922b97116a82f2e4c7cfa7fd6736673f2b957e5ace0e48",
    ),
    (
        "interim/days/2001-03-11.json",
        "b6cb4aa962de29d34883e4af5b9cb1607eea49e32e75cd52eec4ddeeae0e81af",
    ),
    (
        "interim/days/report.json",
        "67aaada3272b45dcc9047b20b6669cccdb8e86d048d015a787934bba4bc07555",
    ),
    (
        "interim/days/training_status.json",
        "8283a8daaeda628579b2537847cd9e5c3fc353a5872c37ce8522b5252373dcc4",
    ),
    (
        "processed/activites.parquet",
        "d98d3fec7987dbe374041dc08287dc665e18f4943b1a36891d43c4a06a94f4ac",
    ),
    (
        "processed/jours.parquet",
        "9810229196e07d0aacdae09669a0e35d9d07f689476dcfe83889f341f8b3c227",
    ),
    (
        "processed/montees.parquet",
        "137ee9acec30506496cc8e2677d69abadb8bd1343ca90384398341451fab9cb7",
    ),
    (
        "processed/variantes.parquet",
        "a0b5903b87da152f73f1320fc93071b146a5cbe587684da7648dca62319b6070",
    ),
]
"""Les fichiers d'``interim/`` et de ``processed/`` et leurs empreintes SHA-256,
relevés sur ``7bbeddb`` dans un arbre détaché."""


def _world(root: Path) -> None:
    """Deux exports Garmin (A puis B), chacun avec ses deux activités et leurs FIT, sauf
    l'activité 12, sans archive dans aucun ; un jour de familles journalières chacun."""
    for name in (EXPORT_A, EXPORT_B):
        export = write_activities_export(root, name)
        write_acquisition(root, name)
        (export / "activity_fit" / "12.zip").unlink()
    write_day(root, DAY, EXPORT_A)
    write_day(root, DAY + timedelta(days=1), EXPORT_B)


def _fingerprints(root: Path) -> list[tuple[str, str]]:
    return sorted(
        (
            path.relative_to(root).as_posix(),
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for folder in ("interim", "processed")
        for path in (root / folder).rglob("*")
        if path.is_file()
    )


def test_garmin_alone_writes_the_bytes_of_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gitstate, "git_state", lambda directory: GitState(COMMIT, False)
    )
    root = data_dir()
    _world(root)
    assert main(["ingest"]) == 0
    assert main(["tables"]) == 0
    found = _fingerprints(root)
    print("EXPECTED = [")
    for name, digest in found:
        print(f'    ("{name}", "{digest}"),')
    print("]")
    assert not (root / "interim" / "activities" / "sources.json").exists()
    assert found == EXPECTED
