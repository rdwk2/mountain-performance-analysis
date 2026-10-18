"""Écriture et relecture des tables de ``processed/`` en Parquet
(``mountain_perf.analyse.parquet``, ``docs/decisions/0014``), extra ``analyse``.

Les tables sont celles de l'``interim/`` synthétique de
``tests/fixtures/processed.py`` : une relecture rend les mêmes contrats, champ pour
champ, sans rien recalculer."""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")

from fixtures.processed import write_interim
from mountain_perf.analyse import parquet
from mountain_perf.analyse.athlete import DEFAULT_SETTINGS
from mountain_perf.analyse.parquet import (
    ACTIVITIES_FILE,
    CLIMBS_FILE,
    PROCESSED_DIR,
    read_tables,
    write_tables,
)
from mountain_perf.analyse.tables import Tables, build_tables
from mountain_perf.schemas.processed import ClimbFlag, ClimbRegime


@pytest.fixture(scope="module")
def tables(tmp_path_factory: pytest.TempPathFactory) -> Tables:
    folder = tmp_path_factory.mktemp("interim")
    write_interim(folder)
    return build_tables(folder, DEFAULT_SETTINGS)


def test_the_two_files_under_processed(tmp_path: Path, tables: Tables) -> None:
    activities, climbs = write_tables(tmp_path, tables)
    assert activities == tmp_path / PROCESSED_DIR / ACTIVITIES_FILE
    assert climbs == tmp_path / PROCESSED_DIR / CLIMBS_FILE
    assert sorted(p.name for p in (tmp_path / PROCESSED_DIR).iterdir()) == [
        "activites.parquet",
        "montees.parquet",
    ]


def test_reading_back_gives_the_same_contracts(tmp_path: Path, tables: Tables) -> None:
    write_tables(tmp_path, tables)
    again = read_tables(tmp_path)
    assert again == tables
    for before, after in zip(tables.climbs, again.climbs, strict=True):
        assert after.local_start_time.utcoffset() == before.local_start_time.utcoffset()
        assert after.local_start_time.replace(tzinfo=None) == (
            before.local_start_time.replace(tzinfo=None)
        )
    for written, read in zip(tables.activities, again.activities, strict=True):
        assert read.start_time.utcoffset() == written.start_time.utcoffset()


def test_the_round_trip_keeps_enums_lists_and_missing_values(
    tmp_path: Path, tables: Tables
) -> None:
    write_tables(tmp_path, tables)
    again = read_tables(tmp_path)
    assert any(row.flags for row in again.climbs)
    for row in again.climbs:
        assert isinstance(row.regime, ClimbRegime)
        assert isinstance(row.flags, tuple)
        assert all(isinstance(flag, ClimbFlag) for flag in row.flags)
        assert isinstance(row.moving_s_by_convention, tuple)
    no_track = again.activities[2]
    assert no_track.moving_s_by_convention is None
    assert no_track.session_count == 1
    assert again.activities[3].session_count is None


def test_writing_twice_gives_the_same_bytes(tmp_path: Path, tables: Tables) -> None:
    """Aucun instant de génération : le même contenu s'écrit à l'identique."""
    first = [p.read_bytes() for p in write_tables(tmp_path / "un", tables)]
    second = [p.read_bytes() for p in write_tables(tmp_path / "deux", tables)]
    assert first == second


def test_a_rewrite_replaces_the_files(tmp_path: Path, tables: Tables) -> None:
    write_tables(tmp_path, tables)
    fewer = dataclasses.replace(
        tables,
        climbs=(),
        provenance=dataclasses.replace(tables.provenance, climb_count=0),
    )
    write_tables(tmp_path, fewer)
    assert read_tables(tmp_path) == fewer
    assert sorted(p.name for p in (tmp_path / PROCESSED_DIR).iterdir()) == [
        "activites.parquet",
        "montees.parquet",
    ]


def test_two_files_of_different_provenance_are_refused(
    tmp_path: Path, tables: Tables
) -> None:
    write_tables(tmp_path / "un", tables)
    other = dataclasses.replace(
        tables, provenance=dataclasses.replace(tables.provenance, package_version="x")
    )
    write_tables(tmp_path / "deux", other)
    (tmp_path / "un" / PROCESSED_DIR / CLIMBS_FILE).write_bytes(
        (tmp_path / "deux" / PROCESSED_DIR / CLIMBS_FILE).read_bytes()
    )
    message = "Les deux tables de processed/ n'ont pas la même provenance."
    with pytest.raises(ValueError, match=f"^{re.escape(message)}$"):
        read_tables(tmp_path / "un")


def test_a_column_type_the_tables_do_not_have_is_refused() -> None:
    """Les contrats n'ont que du texte, des énumérations, des nombres, des booléens,
    des listes et des instants ; tout autre type de champ est une erreur, à
    l'écriture comme à la relecture."""
    with pytest.raises(TypeError, match=r"^type de colonne non pris en charge : "):
        parquet._arrow_type(dict)
    with pytest.raises(TypeError, match=r"^liste attendue, reçu 'x'$"):
        parquet._value(tuple[float, ...], "x")


def test_a_failed_write_keeps_the_previous_tables(
    tmp_path: Path, tables: Tables, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si l'écriture du second fichier échoue, les deux tables d'avant restent, et
    aucun fichier temporaire."""
    write_tables(tmp_path, tables)
    before = [
        (tmp_path / PROCESSED_DIR / name).read_bytes()
        for name in (ACTIVITIES_FILE, CLIMBS_FILE)
    ]
    real = parquet._write
    calls: list[Path] = []

    def failing(table: object, where: Path) -> None:
        calls.append(where)
        if len(calls) == 2:
            raise OSError("disque plein")
        real(table, where)

    monkeypatch.setattr(parquet, "_write", failing)
    fewer = dataclasses.replace(
        tables,
        climbs=(),
        provenance=dataclasses.replace(tables.provenance, climb_count=0),
    )
    with pytest.raises(OSError, match=r"^disque plein$"):
        write_tables(tmp_path, fewer)
    after = [
        (tmp_path / PROCESSED_DIR / name).read_bytes()
        for name in (ACTIVITIES_FILE, CLIMBS_FILE)
    ]
    assert after == before
    assert sorted(p.name for p in (tmp_path / PROCESSED_DIR).iterdir()) == [
        "activites.parquet",
        "montees.parquet",
    ]
