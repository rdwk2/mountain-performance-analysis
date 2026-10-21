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

from fixtures.processed import COMMIT, write_interim
from mountain_perf.analyse import parquet
from mountain_perf.analyse.athlete import DEFAULT_SETTINGS
from mountain_perf.analyse.parquet import (
    ACTIVITIES_FILE,
    CLIMBS_FILE,
    MISSING_TABLE,
    NO_TABLES,
    PROCESSED_DIR,
    STALE_TABLES,
    UNREADABLE_TABLE,
    VARIANTS_FILE,
    ProcessedError,
    read_tables,
    write_tables,
)
from mountain_perf.analyse.tables import Tables, build_tables
from mountain_perf.schemas.processed import (
    ActivityRow,
    ClimbFlag,
    ClimbRegime,
    ClimbRow,
    ClimbVariantRow,
    GradeStratum,
)


@pytest.fixture(scope="module")
def tables(tmp_path_factory: pytest.TempPathFactory) -> Tables:
    folder = tmp_path_factory.mktemp("interim")
    write_interim(folder)
    return build_tables(folder, DEFAULT_SETTINGS, commit=COMMIT)


THREE = ["activites.parquet", "montees.parquet", "variantes.parquet"]


def test_the_three_files_under_processed(tmp_path: Path, tables: Tables) -> None:
    activities, climbs, variants = write_tables(tmp_path, tables)
    assert activities == tmp_path / PROCESSED_DIR / ACTIVITIES_FILE
    assert climbs == tmp_path / PROCESSED_DIR / CLIMBS_FILE
    assert variants == tmp_path / PROCESSED_DIR / VARIANTS_FILE
    assert sorted(p.name for p in (tmp_path / PROCESSED_DIR).iterdir()) == THREE
    assert sorted(p.name for p in tmp_path.iterdir()) == ["processed"]


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
    assert again.variants
    for variant in again.variants:
        assert isinstance(variant.regime, ClimbRegime)
        assert isinstance(variant.grade_stratum, GradeStratum)
        assert isinstance(variant.flags, tuple)
    assert any(variant.flags for variant in again.variants)
    no_track = again.activities[2]
    assert no_track.moving_s_by_convention is None
    assert no_track.session_count == 1
    assert again.activities[3].session_count is None


def test_the_published_names_of_the_format(tables: Tables) -> None:
    """Constat 4 de la relecture de la PR #31 : ce que la docstring du module publie,
    et que liront la figure et les notebooks : la provenance sous la clé
    ``mountain_perf.provenance``, le décalage UTC d'un instant dans la colonne
    ``<nom>_utc_offset_s``."""
    climbs = parquet._table(tables.climbs, ClimbRow, tables.provenance)
    activities = parquet._table(tables.activities, ActivityRow, tables.provenance)
    variants = parquet._table(tables.variants, ClimbVariantRow, tables.provenance)
    for table in (climbs, activities, variants):
        assert list(table.schema.metadata) == [b"mountain_perf.provenance"]
    assert "local_start_time_utc_offset_s" in climbs.column_names
    assert "start_time_utc_offset_s" in activities.column_names


def test_writing_twice_gives_the_same_bytes(tmp_path: Path, tables: Tables) -> None:
    """Aucun instant de génération : le même contenu s'écrit à l'identique."""
    first = [p.read_bytes() for p in write_tables(tmp_path / "un", tables)]
    second = [p.read_bytes() for p in write_tables(tmp_path / "deux", tables)]
    assert first == second


def _fewer(tables: Tables) -> Tables:
    return dataclasses.replace(
        tables,
        climbs=(),
        variants=(),
        provenance=dataclasses.replace(
            tables.provenance, climb_count=0, variant_climb_count=0
        ),
    )


def test_a_rewrite_replaces_the_files(tmp_path: Path, tables: Tables) -> None:
    write_tables(tmp_path, tables)
    write_tables(tmp_path, _fewer(tables))
    assert read_tables(tmp_path) == _fewer(tables)
    assert sorted(p.name for p in (tmp_path / PROCESSED_DIR).iterdir()) == THREE
    assert sorted(p.name for p in tmp_path.iterdir()) == ["processed"]


def test_the_leftovers_of_an_interrupted_write_are_removed(
    tmp_path: Path, tables: Tables
) -> None:
    """Un ``processed.nouveau/`` ou un ``processed.ancien/`` laissés par une écriture
    interrompue sont supprimés avant d'écrire."""
    for name in ("processed.nouveau", "processed.ancien"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "reste.parquet").write_bytes(b"x")
    write_tables(tmp_path, tables)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["processed"]
    assert read_tables(tmp_path) == tables


def test_a_leftover_old_folder_beside_processed_is_removed_first(
    tmp_path: Path, tables: Tables
) -> None:
    """Une écriture arrêtée après la mise en place, avant la suppression de l'ancien
    dossier, laisse ``processed/`` et ``processed.ancien/``. L'écriture suivante
    supprime d'abord ``processed.ancien/`` : sans cela, ``processed/`` ne pourrait
    pas prendre son nom."""
    write_tables(tmp_path, _fewer(tables))
    (tmp_path / "processed.ancien").mkdir()
    (tmp_path / "processed.ancien" / "reste.parquet").write_bytes(b"x")
    write_tables(tmp_path, tables)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["processed"]
    assert read_tables(tmp_path) == tables


def test_what_was_in_processed_does_not_stay(tmp_path: Path, tables: Tables) -> None:
    """``processed/`` se régénère en entier : un fichier qui y traînait part avec
    l'ancien dossier."""
    write_tables(tmp_path, tables)
    (tmp_path / PROCESSED_DIR / "note.txt").write_text("x", encoding="utf-8")
    write_tables(tmp_path, tables)
    assert sorted(p.name for p in (tmp_path / PROCESSED_DIR).iterdir()) == THREE


@pytest.mark.parametrize("name", [CLIMBS_FILE, VARIANTS_FILE])
def test_tables_of_different_provenance_are_refused(
    tmp_path: Path, tables: Tables, name: str
) -> None:
    write_tables(tmp_path / "un", tables)
    other = dataclasses.replace(
        tables, provenance=dataclasses.replace(tables.provenance, package_version="x")
    )
    write_tables(tmp_path / "deux", other)
    (tmp_path / "un" / PROCESSED_DIR / name).write_bytes(
        (tmp_path / "deux" / PROCESSED_DIR / name).read_bytes()
    )
    message = "Les trois tables de processed/ n'ont pas la même provenance."
    with pytest.raises(ProcessedError, match=f"^{re.escape(message)}$"):
        read_tables(tmp_path / "un")


def test_tables_from_before_the_variants_are_refused(
    tmp_path: Path, tables: Tables
) -> None:
    """Des tables d'avant AN1-2c n'ont pas ``variantes.parquet`` : le message dit de
    relancer ``just process``."""
    write_tables(tmp_path, tables)
    (tmp_path / PROCESSED_DIR / VARIANTS_FILE).unlink()
    message = STALE_TABLES.format(name="variantes.parquet")
    assert message == (
        "les tables de processed/ datent d'avant AN1-2c (sans variantes.parquet) : "
        "relancer just process"
    )
    with pytest.raises(ProcessedError, match=f"^{re.escape(message)}$"):
        read_tables(tmp_path)


def test_a_provenance_from_before_the_variants_is_refused(
    tmp_path: Path, tables: Tables, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Une provenance sans le compte des variantes (écrite avant AN1-2c) ne se relit
    pas : le même message."""
    from mountain_perf.codec import encode_contract as real

    def old(provenance: object) -> object:
        data = real(provenance)
        assert isinstance(data, dict)
        return {k: v for k, v in data.items() if k != "variant_climb_count"}

    monkeypatch.setattr(parquet, "encode_contract", old)
    write_tables(tmp_path, tables)
    message = STALE_TABLES.format(name="provenance lisible dans activites.parquet")
    with pytest.raises(ProcessedError, match=f"^{re.escape(message)}$"):
        read_tables(tmp_path)


def test_without_tables(tmp_path: Path) -> None:
    """Sans ``processed/``, ou sans aucune de ses trois tables : le message dit de
    lancer la régénération."""
    message = "aucune table dans processed/ : lancer just process"
    assert message == NO_TABLES
    with pytest.raises(FileNotFoundError, match=f"^{re.escape(message)}$"):
        read_tables(tmp_path)
    (tmp_path / PROCESSED_DIR).mkdir()
    with pytest.raises(FileNotFoundError, match=f"^{re.escape(message)}$"):
        read_tables(tmp_path)


def test_a_column_type_the_tables_do_not_have_is_refused() -> None:
    """Les contrats n'ont que du texte, des énumérations, des nombres, des booléens,
    des listes et des instants ; tout autre type de champ est une erreur, à
    l'écriture comme à la relecture."""
    with pytest.raises(TypeError, match=r"^type de colonne non pris en charge : "):
        parquet._arrow_type(dict)
    with pytest.raises(TypeError, match=r"^liste attendue, reçu 'x'$"):
        parquet._value(tuple[float, ...], "x")


@pytest.mark.parametrize("failing_call", [1, 2, 3])
def test_a_failed_write_keeps_the_previous_tables(
    tmp_path: Path,
    tables: Tables,
    monkeypatch: pytest.MonkeyPatch,
    failing_call: int,
) -> None:
    """Si l'écriture d'un des trois fichiers échoue, les trois tables d'avant restent,
    et ``processed.nouveau/`` est supprimé."""
    write_tables(tmp_path, tables)
    before = [
        (tmp_path / PROCESSED_DIR / name).read_bytes()
        for name in (ACTIVITIES_FILE, CLIMBS_FILE, VARIANTS_FILE)
    ]
    real = parquet._write
    calls: list[Path] = []

    def failing(table: object, where: Path) -> None:
        calls.append(where)
        if len(calls) == failing_call:
            raise OSError("disque plein")
        real(table, where)

    monkeypatch.setattr(parquet, "_write", failing)
    with pytest.raises(OSError, match=r"^disque plein$"):
        write_tables(tmp_path, _fewer(tables))
    assert all(where.parent.name == "processed.nouveau" for where in calls)
    after = [
        (tmp_path / PROCESSED_DIR / name).read_bytes()
        for name in (ACTIVITIES_FILE, CLIMBS_FILE, VARIANTS_FILE)
    ]
    assert after == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["processed"]


def test_a_refused_swap_keeps_the_previous_tables(
    tmp_path: Path, tables: Tables, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si ``processed/`` ne se renomme pas (un fichier ouvert ailleurs, sous Windows),
    les tables d'avant restent en place ; l'écriture suivante nettoie."""
    write_tables(tmp_path, tables)
    real = Path.rename

    def refused(self: Path, target: Path) -> Path:
        if self.name == "processed":
            raise PermissionError("fichier ouvert")
        return real(self, target)

    monkeypatch.setattr(Path, "rename", refused)
    with pytest.raises(PermissionError, match=r"^fichier ouvert$"):
        write_tables(tmp_path, _fewer(tables))
    monkeypatch.undo()
    assert read_tables(tmp_path) == tables
    write_tables(tmp_path, _fewer(tables))
    assert read_tables(tmp_path) == _fewer(tables)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["processed"]


def test_a_refused_second_rename_puts_the_previous_tables_back(
    tmp_path: Path, tables: Tables, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si ``processed.nouveau/`` ne prend pas la place de ``processed/`` (un fichier
    neuf tenu ailleurs, sous Windows), l'ancien dossier reprend la sienne : les tables
    d'avant restent lisibles ; l'écriture suivante nettoie."""
    write_tables(tmp_path, tables)
    real = Path.rename

    def refused(self: Path, target: Path) -> Path:
        if self.name == "processed.nouveau":
            raise PermissionError("fichier ouvert")
        return real(self, target)

    monkeypatch.setattr(Path, "rename", refused)
    with pytest.raises(PermissionError, match=r"^fichier ouvert$"):
        write_tables(tmp_path, _fewer(tables))
    monkeypatch.undo()
    assert read_tables(tmp_path) == tables
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "processed",
        "processed.nouveau",
    ]
    write_tables(tmp_path, _fewer(tables))
    assert read_tables(tmp_path) == _fewer(tables)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["processed"]


def test_a_refused_first_swap_raises_its_own_error(
    tmp_path: Path, tables: Tables, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Une première écriture, sans tables d'avant : si ``processed.nouveau/`` ne prend
    pas la place de ``processed/``, il n'y a rien à remettre en place, et l'erreur se
    propage telle quelle ; l'écriture suivante nettoie."""
    real = Path.rename

    def refused(self: Path, target: Path) -> Path:
        if self.name == "processed.nouveau":
            raise PermissionError("fichier ouvert")
        return real(self, target)

    monkeypatch.setattr(Path, "rename", refused)
    with pytest.raises(PermissionError, match=r"^fichier ouvert$"):
        write_tables(tmp_path, tables)
    monkeypatch.undo()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["processed.nouveau"]
    write_tables(tmp_path, tables)
    assert read_tables(tmp_path) == tables
    assert sorted(p.name for p in tmp_path.iterdir()) == ["processed"]


@pytest.mark.parametrize("name", [ACTIVITIES_FILE, CLIMBS_FILE])
def test_a_missing_table_of_an1_2b_is_named(
    tmp_path: Path, tables: Tables, name: str
) -> None:
    """``activites.parquet`` ou ``montees.parquet`` manque, les autres tables sont
    là : elles ne datent pas d'avant AN1-2c, le message dit laquelle manque et de
    relancer la régénération."""
    write_tables(tmp_path, tables)
    (tmp_path / PROCESSED_DIR / name).unlink()
    message = MISSING_TABLE.format(name=name)
    assert message == f"{name} manque dans processed/ : relancer just process"
    with pytest.raises(ProcessedError, match=f"^{re.escape(message)}$"):
        read_tables(tmp_path)


@pytest.mark.parametrize(
    ("left", "missing"),
    [
        (ACTIVITIES_FILE, CLIMBS_FILE),
        (CLIMBS_FILE, ACTIVITIES_FILE),
        (VARIANTS_FILE, ACTIVITIES_FILE),
    ],
)
def test_a_single_table_left_is_not_an_empty_folder(
    tmp_path: Path, tables: Tables, left: str, missing: str
) -> None:
    """Une seule des trois tables reste : ce n'est pas « aucune table », la
    première qui manque est nommée."""
    write_tables(tmp_path, tables)
    for name in (ACTIVITIES_FILE, CLIMBS_FILE, VARIANTS_FILE):
        if name != left:
            (tmp_path / PROCESSED_DIR / name).unlink()
    message = MISSING_TABLE.format(name=missing)
    with pytest.raises(ProcessedError, match=f"^{re.escape(message)}$"):
        read_tables(tmp_path)


def test_a_truncated_table_is_an_error_not_a_trace(
    tmp_path: Path, tables: Tables
) -> None:
    write_tables(tmp_path, tables)
    path = tmp_path / PROCESSED_DIR / CLIMBS_FILE
    path.write_bytes(path.read_bytes()[:200])
    message = UNREADABLE_TABLE.format(name=CLIMBS_FILE)
    assert message == "montees.parquet ne se relit pas : relancer just process"
    with pytest.raises(ProcessedError, match=f"^{re.escape(message)}$"):
        read_tables(tmp_path)


def test_rows_that_do_not_fit_their_contract_are_an_error(
    tmp_path: Path, tables: Tables
) -> None:
    """``variantes.parquet`` porte la bonne provenance, mais les colonnes d'une
    autre table : il ne se relit pas."""
    write_tables(tmp_path, tables)
    parquet._write(
        parquet._table(tables.activities, ActivityRow, tables.provenance),
        tmp_path / PROCESSED_DIR / VARIANTS_FILE,
    )
    message = UNREADABLE_TABLE.format(name=VARIANTS_FILE)
    with pytest.raises(ProcessedError, match=f"^{re.escape(message)}$"):
        read_tables(tmp_path)
