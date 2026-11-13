"""Écriture et relecture des tables de ``processed/`` en Parquet
(``mountain_perf.analyse.parquet``, ``docs/decisions/0014``, AN2-2), extra ``analyse``.

Les tables sont celles de l'``interim/`` synthétique de
``tests/fixtures/processed.py`` : une relecture rend les mêmes contrats, champ pour
champ, sans rien recalculer."""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("pyarrow")

from fixtures.day_rows import absent_row, complete_row, no_night_row
from fixtures.processed import COMMIT, write_interim
from mountain_perf.analyse import parquet
from mountain_perf.analyse.athlete import DEFAULT_SETTINGS
from mountain_perf.analyse.parquet import (
    ACTIVITIES_FILE,
    CLIMBS_FILE,
    DAYS_FILE,
    DAYS_PROVENANCE_FIELDS,
    MISSING_TABLE,
    MIXED_PROVENANCE,
    NO_TABLES,
    PROCESSED_DIR,
    STALE_DAYS_PROVENANCE,
    STALE_TABLES,
    UNREADABLE_TABLE,
    VARIANTS_FILE,
    ProcessedError,
    read_tables,
    write_tables,
)
from mountain_perf.analyse.tables import DaySummary, Tables, build_tables
from mountain_perf.schemas import NightState, ViewAbsence
from mountain_perf.schemas.processed import (
    ActivityRow,
    AdmissionRefusal,
    ClimbFlag,
    ClimbRegime,
    ClimbRow,
    ClimbVariantRow,
    DayRow,
    DayRowState,
    GradeStratum,
    JournalEventType,
    NormalAbsence,
    ProcessedProvenance,
)


@pytest.fixture(scope="module")
def tables(tmp_path_factory: pytest.TempPathFactory) -> Tables:
    folder = tmp_path_factory.mktemp("interim")
    write_interim(folder)
    built = build_tables(folder, DEFAULT_SETTINGS, commit=COMMIT)
    return dataclasses.replace(built, day_summary=None)


FOUR = ["activites.parquet", "jours.parquet", "montees.parquet", "variantes.parquet"]


def test_the_four_files_under_processed(tmp_path: Path, tables: Tables) -> None:
    activities, climbs, variants, days = write_tables(tmp_path, tables)
    assert activities == tmp_path / PROCESSED_DIR / ACTIVITIES_FILE
    assert climbs == tmp_path / PROCESSED_DIR / CLIMBS_FILE
    assert variants == tmp_path / PROCESSED_DIR / VARIANTS_FILE
    assert days == tmp_path / PROCESSED_DIR / DAYS_FILE
    assert sorted(p.name for p in (tmp_path / PROCESSED_DIR).iterdir()) == FOUR
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
    days = parquet._table(tables.days, DayRow, tables.provenance)
    for table in (climbs, activities, variants, days):
        assert list(table.schema.metadata) == [b"mountain_perf.provenance"]
    assert "night_start_utc_offset_s" in days.column_names
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
        days=(),
        provenance=dataclasses.replace(
            tables.provenance, climb_count=0, variant_climb_count=0, day_count=0
        ),
    )


def test_a_rewrite_replaces_the_files(tmp_path: Path, tables: Tables) -> None:
    write_tables(tmp_path, tables)
    write_tables(tmp_path, _fewer(tables))
    assert read_tables(tmp_path) == _fewer(tables)
    assert sorted(p.name for p in (tmp_path / PROCESSED_DIR).iterdir()) == FOUR
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
    assert sorted(p.name for p in (tmp_path / PROCESSED_DIR).iterdir()) == FOUR


@pytest.mark.parametrize("name", [CLIMBS_FILE, VARIANTS_FILE, DAYS_FILE])
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
    message = "Les quatre tables de processed/ n'ont pas la même provenance."
    assert message == MIXED_PROVENANCE
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
    """Sans ``processed/``, ou sans aucune de ses quatre tables : le message dit de
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


ALL_FILES = (ACTIVITIES_FILE, CLIMBS_FILE, VARIANTS_FILE, DAYS_FILE)


@pytest.mark.parametrize("failing_call", [1, 2, 3, 4])
def test_a_failed_write_keeps_the_previous_tables(
    tmp_path: Path,
    tables: Tables,
    monkeypatch: pytest.MonkeyPatch,
    failing_call: int,
) -> None:
    """Si l'écriture d'un des quatre fichiers échoue, les quatre tables d'avant restent,
    et ``processed.nouveau/`` est supprimé."""
    write_tables(tmp_path, tables)
    before = [(tmp_path / PROCESSED_DIR / name).read_bytes() for name in ALL_FILES]
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
    after = [(tmp_path / PROCESSED_DIR / name).read_bytes() for name in ALL_FILES]
    assert after == before
    assert [where.name for where in calls] == list(ALL_FILES[:failing_call])
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
        (DAYS_FILE, ACTIVITIES_FILE),
    ],
)
def test_a_single_table_left_is_not_an_empty_folder(
    tmp_path: Path, tables: Tables, left: str, missing: str
) -> None:
    """Une seule des quatre tables reste : ce n'est pas « aucune table », la
    première qui manque est nommée."""
    write_tables(tmp_path, tables)
    for name in ALL_FILES:
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


# --- la quatrième table, jours (AN2-2) -----------------------------------------------


def world_rows() -> tuple[DayRow, ...]:
    """Les quatre lignes d'une sorte chacune."""
    return (
        absent_row(),
        complete_row(),
        no_night_row(
            day=date(2000, 1, 7),
            device_ranks=(1, 2),
            uncertain_device=True,
            body_battery_series_versions=(),
            journal_types=(JournalEventType.ILLNESS,),
        ),
        complete_row(
            day=date(2000, 1, 8),
            state=DayRowState.TRUNCATED,
            night_short=None,
            night_short_absence=ViewAbsence.NO_MEASURED_SLEEP,
            stress_measured_s=None,
            stress_valid=None,
            ts_vo2_max_instant=datetime(2000, 1, 8, 12, tzinfo=UTC),
            ts_vo2_max_ml_kg_min=50.0,
        ),
    )


def with_rows(tables: Tables, rows: tuple[DayRow, ...]) -> Tables:
    return dataclasses.replace(
        tables,
        days=rows,
        provenance=dataclasses.replace(tables.provenance, day_count=len(rows)),
    )


INSTANTS = (
    "window_start",
    "data_end",
    "night_start",
    "night_end",
    "readiness_instant",
    "ts_status_instant",
    "ts_load_balance_instant",
    "ts_vo2_max_instant",
    "ts_heat_instant",
    "ts_altitude_instant",
    "lowest_heart_rate_window_midpoint",
)


def test_the_days_table_reads_as_it_is_written(tmp_path: Path, tables: Tables) -> None:
    rows = world_rows()
    written = with_rows(tables, rows)
    write_tables(tmp_path, written)
    again = read_tables(tmp_path)
    assert again == written
    assert again.days == rows
    for before, after in zip(rows, again.days, strict=True):
        assert type(after.day) is date
        assert isinstance(after.state, DayRowState)
        assert isinstance(after.night_state, NightState)
        for name in INSTANTS:
            old, new = getattr(before, name), getattr(after, name)
            assert (new is None) == (old is None)
            if new is not None:
                assert new.utcoffset() == old.utcoffset()
                assert new.replace(tzinfo=None) == old.replace(tzinfo=None)
        assert isinstance(after.device_ranks, tuple)
        assert all(type(rank) is int for rank in after.device_ranks)
        assert all(isinstance(kind, JournalEventType) for kind in after.journal_types)
    absent, full, no_night, truncated = again.days
    assert absent.device_ranks == ()
    assert absent.body_battery_series_versions == ()
    assert absent.journal_types == ()
    assert absent.window_start is None
    assert no_night.device_ranks == (1, 2)
    assert full.body_battery_series_versions == (3, 4)
    assert full.journal_types == (JournalEventType.RACE, JournalEventType.TRAVEL)
    assert full.ts_status_instant is not None
    assert full.ts_status_instant.utcoffset() == timedelta(0)
    assert full.ts_heat_instant is not None
    assert full.ts_heat_instant.utcoffset() == timedelta(hours=2)
    assert full.lowest_heart_rate_window_midpoint is not None
    assert full.lowest_heart_rate_window_midpoint.utcoffset() == timedelta(hours=1)
    assert full.night_shifted is None
    assert full.night_shifted_absence is ViewAbsence.BELOW_USUAL_MINIMUM
    assert full.night_short is False
    assert full.stress_valid is True
    assert full.night_respiration_refusal is AdmissionRefusal.NO_VALUE
    assert full.night_stress_normal_absence is NormalAbsence.TOO_FEW_ADMITTED_DAYS
    assert truncated.stress_valid is None


def test_a_days_table_without_a_row(tmp_path: Path, tables: Tables) -> None:
    write_tables(tmp_path, with_rows(tables, ()))
    assert read_tables(tmp_path).days == ()


def test_the_rows_the_table_produces_read_back_equal(
    tmp_path: Path, tables: Tables
) -> None:
    assert len(tables.days) == 4
    assert tables.days[2].state is DayRowState.ABSENT
    write_tables(tmp_path, tables)
    assert read_tables(tmp_path).days == tables.days


def _expected_columns() -> list[str]:
    names: list[str] = []
    for field in dataclasses.fields(DayRow):
        names.append(field.name)
        if field.name in INSTANTS:
            names.append(f"{field.name}_utc_offset_s")
    return names


def _world_table(tables: Tables, rows: tuple[DayRow, ...]) -> Any:
    return parquet._table(rows, DayRow, tables.provenance)


def test_the_columns_of_the_days_table(tables: Tables) -> None:
    table = _world_table(tables, world_rows())
    assert table.column_names == _expected_columns()
    types = {field.name: str(field.type) for field in table.schema}
    assert types["day"] == "date32[day]"
    for name in INSTANTS:
        assert types[name] == "timestamp[us]"
        assert types[f"{name}_utc_offset_s"] == "int32"
    assert types["device_ranks"] == "list<item: int64>"
    assert types["body_battery_series_versions"] == "list<item: int64>"
    assert types["journal_types"] == "list<item: string>"
    assert types["state"] == "string"
    assert types["hrv_refusal"] == "string"
    assert types["night_short"] == "bool"
    assert types["nap_count"] == "int64"
    assert types["deep_s"] == "double"
    assert all(field.nullable for field in table.schema)
    assert _world_table(tables, ()).schema.equals(table.schema)


def test_an_absent_instant_makes_two_null_columns(tables: Tables) -> None:
    table = _world_table(tables, (absent_row(), complete_row()))
    assert table.column("night_start").to_pylist()[0] is None
    assert table.column("night_start_utc_offset_s").to_pylist() == [None, 3600]


def _replace_column(table: Any, name: str, source: Any) -> Any:
    index = table.schema.get_field_index(name)
    return table.set_column(index, table.schema.field(index), source.column(name))


def _write_one_day(tmp_path: Path, tables: Tables, table: Any) -> None:
    write_tables(tmp_path, with_rows(tables, (complete_row(),)))
    parquet._write(table, tmp_path / PROCESSED_DIR / DAYS_FILE)


def _unreadable(tmp_path: Path, name: str) -> None:
    message = UNREADABLE_TABLE.format(name=name)
    assert message == f"{name} ne se relit pas : relancer just process"
    with pytest.raises(ProcessedError, match=f"^{re.escape(message)}$"):
        read_tables(tmp_path)


@pytest.mark.parametrize("column", ["night_start", "night_start_utc_offset_s"])
def test_one_null_column_of_the_night_is_unreadable(
    tmp_path: Path, tables: Tables, column: str
) -> None:
    provenance = dataclasses.replace(tables.provenance, day_count=1)
    full = parquet._table((complete_row(),), DayRow, provenance)
    nulls = parquet._table((no_night_row(),), DayRow, provenance)
    _write_one_day(tmp_path, tables, _replace_column(full, column, nulls))
    _unreadable(tmp_path, DAYS_FILE)


@pytest.mark.parametrize(
    "column", ["ts_status_instant", "ts_status_instant_utc_offset_s"]
)
def test_one_null_column_of_an_optional_instant_is_unreadable(
    tmp_path: Path, tables: Tables, column: str
) -> None:
    provenance = dataclasses.replace(tables.provenance, day_count=1)
    full = parquet._table((complete_row(),), DayRow, provenance)
    nulls = parquet._table((complete_row(ts_status_instant=None),), DayRow, provenance)
    _write_one_day(tmp_path, tables, _replace_column(full, column, nulls))
    _unreadable(tmp_path, DAYS_FILE)


@pytest.mark.parametrize(
    ("file", "column", "rows", "cls"),
    [
        (ACTIVITIES_FILE, "start_time", "activities", ActivityRow),
        (CLIMBS_FILE, "local_start_time", "climbs", ClimbRow),
    ],
)
def test_a_mandatory_instant_never_reads_as_absent(
    tmp_path: Path, tables: Tables, file: str, column: str, rows: str, cls: type
) -> None:
    write_tables(tmp_path, tables)
    lines = getattr(tables, rows)
    table = parquet._table(lines, cls, tables.provenance)
    absent = parquet._table(
        tuple(absent_row() for _ in lines), DayRow, tables.provenance
    )
    for target, source in (
        (column, "night_start"),
        (f"{column}_utc_offset_s", "night_start_utc_offset_s"),
    ):
        index = table.schema.get_field_index(target)
        table = table.set_column(
            index, table.schema.field(index), absent.column(source)
        )
    parquet._write(table, tmp_path / PROCESSED_DIR / file)
    _unreadable(tmp_path, file)


def test_a_climbs_table_without_the_heart_rate_columns_is_unreadable(
    tmp_path: Path, tables: Tables
) -> None:
    """Un ``montees.parquet`` d'avant AN3-1a, avec une montée, ne se relit pas : il
    manque les colonnes de la FC décalée (``0014``, précisions d'AN3-1a)."""
    assert tables.climbs
    write_tables(tmp_path, tables)
    table = parquet._table(tables.climbs, ClimbRow, tables.provenance)
    older = table.drop_columns(["lagged_moving_heart_rate_bpm"])
    parquet._write(older, tmp_path / PROCESSED_DIR / CLIMBS_FILE)
    _unreadable(tmp_path, CLIMBS_FILE)


def test_a_climbs_table_without_the_positions_is_unreadable(
    tmp_path: Path, tables: Tables
) -> None:
    """Un ``montees.parquet`` d'avant AN3-3a, avec une montée, ne se relit pas : il
    manque les positions des bornes (``0014``, précisions d'AN3-3a)."""
    assert tables.climbs
    write_tables(tmp_path, tables)
    table = parquet._table(tables.climbs, ClimbRow, tables.provenance)
    older = table.drop_columns(["start_latitude_deg"])
    parquet._write(older, tmp_path / PROCESSED_DIR / CLIMBS_FILE)
    _unreadable(tmp_path, CLIMBS_FILE)


def test_a_days_table_without_the_lowest_window_is_unreadable(
    tmp_path: Path, tables: Tables
) -> None:
    """Un ``jours.parquet`` d'avant AN3-3a, avec une ligne, ne se relit pas : il manque
    les deux colonnes de l'instant de la demi-heure de FC la plus basse (``0019``)."""
    provenance = dataclasses.replace(tables.provenance, day_count=1)
    table = parquet._table((complete_row(),), DayRow, provenance)
    older = table.drop_columns(
        [
            "lowest_heart_rate_window_midpoint",
            "lowest_heart_rate_window_midpoint_utc_offset_s",
        ]
    )
    _write_one_day(tmp_path, tables, older)
    _unreadable(tmp_path, DAYS_FILE)


def test_an_instant_reads_from_its_two_columns(tmp_path: Path, tables: Tables) -> None:
    written = with_rows(tables, (complete_row(),))
    write_tables(tmp_path, written)
    (row,) = read_tables(tmp_path).days
    assert row.night_end is not None
    assert row.night_end.replace(tzinfo=None) == datetime(2000, 1, 6, 7)
    assert row.night_end.utcoffset() == timedelta(hours=1)


def test_an_optional_instant_absent_reads_absent(
    tmp_path: Path, tables: Tables
) -> None:
    write_tables(tmp_path, with_rows(tables, (absent_row(),)))
    again = read_tables(tmp_path)
    assert all(getattr(again.days[0], name) is None for name in INSTANTS)
    assert again.activities == tables.activities


def test_the_summary_of_the_days_is_not_written(tmp_path: Path, tables: Tables) -> None:
    written = dataclasses.replace(tables, day_summary=DaySummary(0, 0, 0, 0, 0, 0))
    write_tables(tmp_path, written)
    again = read_tables(tmp_path)
    assert again.day_summary is None
    assert dataclasses.replace(again, day_summary=written.day_summary) == written


def test_a_missing_days_file_is_named(tmp_path: Path, tables: Tables) -> None:
    write_tables(tmp_path, tables)
    (tmp_path / PROCESSED_DIR / DAYS_FILE).unlink()
    message = MISSING_TABLE.format(name=DAYS_FILE)
    assert message == "jours.parquet manque dans processed/ : relancer just process"
    with pytest.raises(ProcessedError, match=f"^{re.escape(message)}$"):
        read_tables(tmp_path)


def _without(monkeypatch: pytest.MonkeyPatch, *keys: str) -> None:
    from mountain_perf.codec import encode_contract as real

    def old(provenance: object) -> object:
        data = real(provenance)
        assert isinstance(data, dict)
        return {k: v for k, v in data.items() if k not in keys}

    monkeypatch.setattr(parquet, "encode_contract", old)


def _stale(fields: str) -> str:
    return (
        f"la provenance de activites.parquet date d'avant AN2-2 (sans {fields}) : "
        "relancer just process"
    )


ALL_DAYS_FIELDS = "interim_days_sha256, journal_sha256, day_count, acquired_at"


@pytest.mark.parametrize(
    ("removed", "fields"),
    [
        (DAYS_PROVENANCE_FIELDS, ALL_DAYS_FIELDS),
        (("acquired_at",), "acquired_at"),
        (("day_count", "interim_days_sha256"), "interim_days_sha256, day_count"),
    ],
)
def test_a_provenance_from_before_the_days_is_refused(
    tmp_path: Path,
    tables: Tables,
    monkeypatch: pytest.MonkeyPatch,
    removed: tuple[str, ...],
    fields: str,
) -> None:
    _without(monkeypatch, *removed)
    write_tables(tmp_path, tables)
    with pytest.raises(ProcessedError, match=f"^{re.escape(_stale(fields))}$"):
        read_tables(tmp_path)


def test_the_constants_of_the_stale_provenance() -> None:
    filled = STALE_DAYS_PROVENANCE.format(
        name="activites.parquet", fields=", ".join(DAYS_PROVENANCE_FIELDS)
    )
    assert filled == _stale(ALL_DAYS_FIELDS)
    names = [f.name for f in dataclasses.fields(ProcessedProvenance)]
    assert tuple(names[-4:]) == DAYS_PROVENANCE_FIELDS


def test_tables_from_before_the_days_are_refused_by_their_provenance(
    tmp_path: Path, tables: Tables, monkeypatch: pytest.MonkeyPatch
) -> None:
    _without(monkeypatch, *DAYS_PROVENANCE_FIELDS)
    write_tables(tmp_path, tables)
    (tmp_path / PROCESSED_DIR / DAYS_FILE).unlink()
    with pytest.raises(ProcessedError, match=f"^{re.escape(_stale(ALL_DAYS_FIELDS))}$"):
        read_tables(tmp_path)


def test_a_provenance_from_before_the_variants_keeps_its_message(
    tmp_path: Path, tables: Tables, monkeypatch: pytest.MonkeyPatch
) -> None:
    _without(monkeypatch, "variant_climb_count", *DAYS_PROVENANCE_FIELDS)
    write_tables(tmp_path, tables)
    message = STALE_TABLES.format(name="provenance lisible dans activites.parquet")
    with pytest.raises(ProcessedError, match=f"^{re.escape(message)}$"):
        read_tables(tmp_path)


@pytest.mark.parametrize("value", [5, "une provenance", [1, 2]])
def test_a_provenance_that_is_not_an_object(
    tmp_path: Path, tables: Tables, monkeypatch: pytest.MonkeyPatch, value: object
) -> None:
    monkeypatch.setattr(parquet, "encode_contract", lambda provenance: value)
    write_tables(tmp_path, tables)
    message = STALE_TABLES.format(name="provenance lisible dans activites.parquet")
    with pytest.raises(ProcessedError, match=f"^{re.escape(message)}$"):
        read_tables(tmp_path)


# --- deux décalages dans une colonne, provenance illisible, ordre de relecture -------

SAME_INSTANT = (
    datetime(2000, 1, 6, 12, tzinfo=timezone(timedelta(hours=1))),
    datetime(2000, 1, 6, 13, tzinfo=timezone(timedelta(hours=2))),
)
"""Un même instant, à +01:00 (l'hiver) et à +02:00 (l'été)."""

WALLS_AND_OFFSETS = [
    (datetime(2000, 1, 6, 12), timedelta(hours=1)),
    (datetime(2000, 1, 6, 13), timedelta(hours=2)),
]
"""Ce que chacune des deux lignes doit garder : son heure murale, son décalage."""


def _wall_and_offset(instant: datetime | None) -> tuple[datetime, timedelta | None]:
    assert instant is not None
    return instant.replace(tzinfo=None), instant.utcoffset()


def test_each_row_of_the_days_keeps_its_own_offset(
    tmp_path: Path, tables: Tables
) -> None:
    winter, summer = SAME_INSTANT
    rows = (
        complete_row(ts_status_instant=winter),
        complete_row(day=date(2000, 1, 7), ts_status_instant=summer),
    )
    write_tables(tmp_path, with_rows(tables, rows))
    again = read_tables(tmp_path).days
    assert again == rows
    assert [_wall_and_offset(r.ts_status_instant) for r in again] == WALLS_AND_OFFSETS


def test_each_row_of_the_activities_keeps_its_own_offset(
    tmp_path: Path, tables: Tables
) -> None:
    first, second, *others = tables.activities
    rows = (
        dataclasses.replace(first, start_time=SAME_INSTANT[0]),
        dataclasses.replace(second, start_time=SAME_INSTANT[1]),
        *others,
    )
    write_tables(tmp_path, dataclasses.replace(tables, activities=rows))
    again = read_tables(tmp_path).activities
    assert again == rows
    assert [_wall_and_offset(r.start_time) for r in again[:2]] == WALLS_AND_OFFSETS


def _table_of(tables: Tables, name: str) -> Any:
    sources: dict[str, tuple[Sequence[object], type]] = {
        ACTIVITIES_FILE: (tables.activities, ActivityRow),
        CLIMBS_FILE: (tables.climbs, ClimbRow),
        VARIANTS_FILE: (tables.variants, ClimbVariantRow),
        DAYS_FILE: (tables.days, DayRow),
    }
    rows, cls = sources[name]
    return parquet._table(rows, cls, tables.provenance)


@pytest.mark.parametrize("name", ALL_FILES)
@pytest.mark.parametrize(
    "metadata",
    [{}, {parquet.PROVENANCE_KEY: b"{pas du json"}],
    ids=["sans la clé", "illisible"],
)
def test_a_provenance_absent_or_unreadable_is_stale(
    tmp_path: Path, tables: Tables, name: str, metadata: dict[bytes, bytes]
) -> None:
    write_tables(tmp_path, tables)
    damaged = _table_of(tables, name).replace_schema_metadata(metadata)
    parquet._write(damaged, tmp_path / PROCESSED_DIR / name)
    message = STALE_TABLES.format(name=f"provenance lisible dans {name}")
    with pytest.raises(ProcessedError, match=f"^{re.escape(message)}$"):
        read_tables(tmp_path)


def test_the_tables_are_read_in_order_and_the_first_fault_stops(
    tmp_path: Path, tables: Tables
) -> None:
    """``variantes.parquet`` manque et ``jours.parquet`` est abîmé : la troisième table
    se relit avant la quatrième, et son défaut seul est dit."""
    write_tables(tmp_path, tables)
    (tmp_path / PROCESSED_DIR / VARIANTS_FILE).unlink()
    days = tmp_path / PROCESSED_DIR / DAYS_FILE
    days.write_bytes(days.read_bytes()[:200])
    message = STALE_TABLES.format(name=VARIANTS_FILE)
    with pytest.raises(ProcessedError, match=f"^{re.escape(message)}$"):
        read_tables(tmp_path)


# --- le schéma figé des trois tables d'AN1-2 -----------------------------------------

FROZEN_ACTIVITIES = [
    ("activity_ref", "string"),
    ("source_activity_type", "string"),
    ("sport", "string"),
    ("view_refusal", "string"),
    ("start_time", "timestamp[us]"),
    ("start_time_utc_offset_s", "int32"),
    ("index_elapsed_s", "double"),
    ("index_moving_s", "double"),
    ("index_distance_m", "double"),
    ("index_ascent_m", "double"),
    ("index_descent_m", "double"),
    ("index_elevation_corrected", "bool"),
    ("index_average_heart_rate_bpm", "double"),
    ("index_max_heart_rate_bpm", "double"),
    ("has_recording", "bool"),
    ("has_track", "bool"),
    ("session_count", "int64"),
    ("track_offset_s", "double"),
    ("track_elapsed_s", "double"),
    ("profile_distance_m", "double"),
    ("profile_ascent_m", "double"),
    ("profile_descent_m", "double"),
    ("moving_s_by_convention", "list<item: double>"),
    ("stopped_s_by_convention", "list<item: double>"),
    ("undetermined_s_by_convention", "list<item: double>"),
    ("step_s", "double"),
    ("longest_step_s", "double"),
    ("gap_count", "int64"),
    ("gap_s", "double"),
    ("timer_stop_count", "int64"),
    ("auto_pause_count", "int64"),
    ("position_gap_ascent_m", "double"),
    ("loop", "bool"),
    ("closure_elevation_m", "double"),
    ("closure_rate_ms", "double"),
    ("altimetric_drift", "bool"),
    ("device_manufacturer", "string"),
    ("device_product", "int64"),
    ("software_version", "double"),
    ("barometer", "bool"),
    ("barometric", "bool"),
    ("external_heart_rate_sensor", "bool"),
    ("mean_heart_rate_bpm", "double"),
    ("heart_rate_coverage", "double"),
    ("mean_temperature_c", "double"),
    ("climb_count", "int64"),
    ("short_climb_count", "int64"),
    ("intermediate_count", "int64"),
    ("long_climb_count", "int64"),
    ("ski_touring_count", "int64"),
    ("short_ski_touring_count", "int64"),
    ("other_sport_count", "int64"),
    ("flagged_climb_count", "int64"),
    ("unstable_climb_count", "int64"),
]
FROZEN_CLIMBS = [
    ("activity_ref", "string"),
    ("start_offset_s", "double"),
    ("end_offset_s", "double"),
    ("rank", "int64"),
    ("source_activity_type", "string"),
    ("sport", "string"),
    ("local_start_time", "timestamp[us]"),
    ("local_start_time_utc_offset_s", "int32"),
    ("device_manufacturer", "string"),
    ("device_product", "int64"),
    ("software_version", "double"),
    ("barometric", "bool"),
    ("profile_start_m", "double"),
    ("profile_end_m", "double"),
    ("profile_gain_m", "double"),
    ("raw_profile_gain_m", "double"),
    ("profile_ascent_m", "double"),
    ("gain_m", "double"),
    ("moving_gain_m_by_convention", "list<item: double>"),
    ("stopped_gain_m_by_convention", "list<item: double>"),
    ("undetermined_gain_m_by_convention", "list<item: double>"),
    ("gap_gain_m", "double"),
    ("elapsed_s", "double"),
    ("moving_s_by_convention", "list<item: double>"),
    ("stopped_s_by_convention", "list<item: double>"),
    ("undetermined_s_by_convention", "list<item: double>"),
    ("slow_moving_s", "double"),
    ("vertical_speed_ms", "double"),
    ("moving_or_undetermined_vertical_speed_ms", "double"),
    ("vertical_speed_low_ms", "double"),
    ("vertical_speed_high_ms", "double"),
    ("moving_distance_m", "double"),
    ("grade", "double"),
    ("net_displacement_m", "double"),
    ("sinuosity", "double"),
    ("low_elevation_m", "double"),
    ("high_elevation_m", "double"),
    ("moving_mean_elevation_m", "double"),
    ("step_s", "double"),
    ("longest_step_s", "double"),
    ("gap_count", "int64"),
    ("gap_s", "double"),
    ("timer_stop_count", "int64"),
    ("auto_pause_count", "int64"),
    ("max_vertical_rate_ms", "double"),
    ("outside_moving_gain_fraction", "double"),
    ("slow_moving_fraction", "double"),
    ("flags", "list<item: string>"),
    ("found_fraction", "double"),
    ("max_relative_deviation", "double"),
    ("stable", "bool"),
    ("regime", "string"),
    ("grade_stratum", "string"),
    ("altitude_stratum", "string"),
    ("preceding_moving_s", "double"),
    ("preceding_ascent_m", "double"),
    ("preceding_descent_m", "double"),
    ("moving_mean_heart_rate_bpm", "double"),
    ("moving_heart_rate_coverage", "double"),
    ("second_half_mean_heart_rate_bpm", "double"),
    ("external_heart_rate_sensor", "bool"),
    ("moving_mean_temperature_c", "double"),
    ("lagged_moving_heart_rate_bpm", "double"),
    ("lagged_moving_heart_rate_coverage", "double"),
    ("unlagged_moving_heart_rate_bpm", "double"),
    ("unlagged_moving_heart_rate_coverage", "double"),
    ("lagged_second_half_heart_rate_bpm", "double"),
    ("lagged_second_half_heart_rate_coverage", "double"),
    ("lagged_elapsed_heart_rate_bpm", "double"),
    ("lagged_elapsed_heart_rate_coverage", "double"),
    ("start_latitude_deg", "double"),
    ("start_longitude_deg", "double"),
    ("end_latitude_deg", "double"),
    ("end_longitude_deg", "double"),
]
FROZEN_VARIANTS = [
    ("activity_ref", "string"),
    ("variant", "string"),
    ("start_offset_s", "double"),
    ("end_offset_s", "double"),
    ("gain_m", "double"),
    ("moving_gain_m", "double"),
    ("moving_s", "double"),
    ("regime", "string"),
    ("grade_stratum", "string"),
    ("altitude_stratum", "string"),
    ("flags", "list<item: string>"),
]


def test_the_fourth_table_changes_nothing_to_the_three_others(
    tmp_path: Path, tables: Tables, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = parquet._write
    seen: dict[str, Any] = {}

    def spying(table: Any, where: Path) -> None:
        seen[where.name] = table
        real(table, where)

    monkeypatch.setattr(parquet, "_write", spying)
    paths = write_tables(tmp_path, tables)
    assert [path.name for path in paths] == list(ALL_FILES)
    assert all(path.exists() for path in paths)
    for name, expected in (
        (ACTIVITIES_FILE, FROZEN_ACTIVITIES),
        (CLIMBS_FILE, FROZEN_CLIMBS),
        (VARIANTS_FILE, FROZEN_VARIANTS),
    ):
        schema = seen[name].schema
        assert [(field.name, str(field.type)) for field in schema] == expected
        assert all(field.nullable for field in schema)
