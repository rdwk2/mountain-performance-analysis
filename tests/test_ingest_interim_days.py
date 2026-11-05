"""Les documents d'``interim/days/`` (AN2-1) : écriture, relecture, mise en place, sur
le modèle des tests de ``write_activities`` ; ``interim/activities/`` n'est pas
touché."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from fixtures.days import (
    DAY,
    EMPTY_HISTORY,
    day_record,
    days_report,
    empty_day,
    history,
    truncated_day,
)
from mountain_perf.codec import CodecError
from mountain_perf.ingest.interim import (
    ACTIVITIES_DIR,
    DAYS_DIR,
    DAYS_REPORT_FILE,
    INTERIM_DOCUMENT_FIRST_FORMAT,
    TRAINING_STATUS_FILE,
    InterimError,
    decode_interim,
    encode_interim,
    read_days,
    read_days_report,
    read_index,
    read_training_status,
    write_activities,
    write_days,
)
from mountain_perf.schemas import (
    INTERIM_FORMAT_VERSION,
    DayRecord,
    DaysReport,
    TrainingStatusHistory,
)
from test_ingest_interim import INDEX, REPORT
from test_schemas_interim import recording

RECORDS = (
    day_record(DAY),
    truncated_day(DAY + timedelta(days=1)),
    empty_day(DAY + timedelta(days=2)),
)
ALL = RECORDS
HISTORY = history()
REPORT_DAYS = days_report()
RUN = "lancer `mperf " + "ingest`."


def _write(root: Path, records: object = RECORDS) -> None:
    write_days(root, records, HISTORY, REPORT_DAYS)  # type: ignore[arg-type]


def _names(root: Path) -> list[str]:
    return sorted(path.name for path in (root / "interim").iterdir())


def _bytes(folder: Path) -> dict[str, bytes]:
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in folder.rglob("*")
        if path.is_file()
    }


def test_paths_and_format() -> None:
    assert Path("interim") / "days" == DAYS_DIR
    assert TRAINING_STATUS_FILE == "training_status.json"
    assert DAYS_REPORT_FILE == "report.json"
    assert INTERIM_FORMAT_VERSION == 2
    for cls in (DayRecord, TrainingStatusHistory, DaysReport):
        assert INTERIM_DOCUMENT_FIRST_FORMAT[cls] == 2


@pytest.mark.parametrize("value", [*ALL, HISTORY, EMPTY_HISTORY, REPORT_DAYS])
def test_round_trip_is_exact(value: object) -> None:
    data = encode_interim(value)
    assert decode_interim(data, type(value)) == value
    assert encode_interim(decode_interim(data, type(value))) == data


@pytest.mark.parametrize(
    ("value", "name"),
    [
        (RECORDS[0], "DayRecord"),
        (HISTORY, "TrainingStatusHistory"),
        (REPORT_DAYS, "DaysReport"),
    ],
)
def test_document_envelope_starts_with_type_and_format(
    value: object, name: str
) -> None:
    assert encode_interim(value).startswith(
        b'{"type":"' + name.encode() + b'","format":2,"data":{'
    )


def test_a_day_document_of_format_one_is_refused() -> None:
    data = encode_interim(RECORDS[0]).replace(b'"format":2', b'"format":1', 1)
    with pytest.raises(CodecError, match="format 1, 2 attendu"):
        decode_interim(data, DayRecord)


def test_write_then_read(tmp_path: Path) -> None:
    _write(tmp_path)
    folder = tmp_path / DAYS_DIR
    assert sorted(path.name for path in folder.iterdir()) == [
        "2001-03-10.json",
        "2001-03-11.json",
        "2001-03-12.json",
        "report.json",
        "training_status.json",
    ]
    assert read_days(tmp_path) == RECORDS
    assert read_training_status(tmp_path) == HISTORY
    assert read_days_report(tmp_path) == REPORT_DAYS
    assert (folder / "2001-03-10.json").read_bytes() == encode_interim(RECORDS[0])
    assert _names(tmp_path) == ["days"]


def test_records_may_come_from_a_generator(tmp_path: Path) -> None:
    def generate() -> Iterator[DayRecord]:
        yield from RECORDS

    _write(tmp_path, generate())
    assert read_days(tmp_path) == RECORDS


def test_no_day_is_admitted(tmp_path: Path) -> None:
    _write(tmp_path, ())
    assert read_days(tmp_path) == ()
    assert read_training_status(tmp_path) == HISTORY


def test_two_writes_give_the_same_bytes(tmp_path: Path) -> None:
    _write(tmp_path)
    first = _bytes(tmp_path / DAYS_DIR)
    _write(tmp_path)
    assert _bytes(tmp_path / DAYS_DIR) == first


def test_rewriting_replaces_everything(tmp_path: Path) -> None:
    _write(tmp_path)
    stale = tmp_path / DAYS_DIR / "2001-01-01.json"
    stale.write_bytes(b"x")
    _write(tmp_path, RECORDS[:1])
    assert not stale.exists()
    assert read_days(tmp_path) == RECORDS[:1]
    assert _names(tmp_path) == ["days"]


@pytest.mark.parametrize(
    "records",
    [
        (RECORDS[1], RECORDS[0]),
        (RECORDS[0], RECORDS[0]),
        (RECORDS[0], RECORDS[2], RECORDS[1]),
        (RECORDS[0], dataclasses.replace(RECORDS[0], wellness_data=None)),
    ],
)
def test_days_must_be_sorted_without_duplicate(
    tmp_path: Path, records: tuple[DayRecord, ...]
) -> None:
    _write(tmp_path)
    before = _bytes(tmp_path / DAYS_DIR)
    with pytest.raises(ValueError, match="jours") as error:
        _write(tmp_path, records)
    assert type(error.value) is ValueError
    assert str(error.value) == (
        "Les jours doivent venir triés par date, chacun une seule fois."
    )
    assert _bytes(tmp_path / DAYS_DIR) == before
    assert _names(tmp_path) == ["days"]


def test_a_wrong_document_type_is_a_programming_error(tmp_path: Path) -> None:
    wrong = RECORDS[0].night
    with pytest.raises(TypeError, match="n'est pas un type de document"):
        write_days(tmp_path, RECORDS, wrong, REPORT_DAYS)  # type: ignore[arg-type]
    assert _names(tmp_path) == []


def test_leftovers_of_an_interrupted_write_are_removed(tmp_path: Path) -> None:
    for name in ("days.nouveau", "days.ancien"):
        leftover = tmp_path / "interim" / name
        leftover.mkdir(parents=True)
        (leftover / "2001-01-01.json").write_bytes(b"x")
    _write(tmp_path)
    assert _names(tmp_path) == ["days"]
    assert read_days(tmp_path) == RECORDS


def _refuse_rename(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    real = Path.rename

    def refused(self: Path, target: Path) -> Path:
        if self.name == name:
            raise PermissionError("fichier ouvert")
        return real(self, target)

    monkeypatch.setattr(Path, "rename", refused)


def test_a_refused_swap_keeps_the_previous_days(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path)
    _refuse_rename(monkeypatch, "days")
    with pytest.raises(PermissionError, match=r"^fichier ouvert$"):
        _write(tmp_path, RECORDS[:1])
    monkeypatch.undo()
    assert read_days(tmp_path) == RECORDS
    _write(tmp_path, RECORDS[:1])
    assert read_days(tmp_path) == RECORDS[:1]
    assert _names(tmp_path) == ["days"]


def test_a_refused_second_rename_puts_the_previous_days_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path)
    _refuse_rename(monkeypatch, "days.nouveau")
    with pytest.raises(PermissionError, match=r"^fichier ouvert$"):
        _write(tmp_path, RECORDS[:1])
    monkeypatch.undo()
    assert read_days(tmp_path) == RECORDS
    assert _names(tmp_path) == ["days", "days.nouveau"]
    _write(tmp_path, RECORDS[:1])
    assert read_days(tmp_path) == RECORDS[:1]
    assert _names(tmp_path) == ["days"]


def test_a_refused_first_swap_raises_its_own_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _refuse_rename(monkeypatch, "days.nouveau")
    with pytest.raises(PermissionError, match=r"^fichier ouvert$"):
        _write(tmp_path)
    monkeypatch.undo()
    assert _names(tmp_path) == ["days.nouveau"]
    _write(tmp_path)
    assert read_days(tmp_path) == RECORDS
    assert _names(tmp_path) == ["days"]


def test_an_interrupted_second_rename_puts_the_previous_days_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path)
    real = Path.rename

    def interrupted(self: Path, target: Path) -> Path:
        if self.name == "days.nouveau":
            raise KeyboardInterrupt
        return real(self, target)

    monkeypatch.setattr(Path, "rename", interrupted)
    with pytest.raises(KeyboardInterrupt):
        _write(tmp_path, RECORDS[:1])
    monkeypatch.undo()
    assert read_days(tmp_path) == RECORDS


def test_days_and_activities_do_not_touch_each_other(tmp_path: Path) -> None:
    """Deux échanges, pas un : écrire les jours laisse ``interim/activities/`` à
    l'octet, et écrire les activités laisse ``interim/days/`` à l'octet."""
    write_activities(tmp_path, INDEX, [recording()], REPORT)
    activities = _bytes(tmp_path / ACTIVITIES_DIR)
    _write(tmp_path)
    assert _bytes(tmp_path / ACTIVITIES_DIR) == activities
    days = _bytes(tmp_path / DAYS_DIR)
    write_activities(tmp_path, INDEX, [recording()], REPORT)
    assert _bytes(tmp_path / DAYS_DIR) == days
    assert read_index(tmp_path) == INDEX
    assert _names(tmp_path) == ["activities", "days"]


def test_a_missing_folder_says_to_run_the_ingestion(tmp_path: Path) -> None:
    for read in (read_days, read_training_status, read_days_report):
        with pytest.raises(InterimError) as error:
            read(tmp_path)
        assert str(error.value) == f"days/ manque dans interim/ : {RUN}"


@pytest.mark.parametrize(
    ("name", "read"),
    [
        ("training_status.json", read_training_status),
        ("report.json", read_days_report),
    ],
)
def test_a_missing_file_says_to_run_the_ingestion(
    tmp_path: Path, name: str, read: Callable[[Path], object]
) -> None:
    _write(tmp_path)
    (tmp_path / DAYS_DIR / name).unlink()
    with pytest.raises(InterimError) as error:
        read(tmp_path)
    assert str(error.value) == f"days/{name} manque dans interim/ : {RUN}"


INCOHERENT_NAME = (
    "interim/ incohérent : un jour porte une autre date que son nom de fichier. "
    "Lancer `mperf " + "ingest`."
)


def test_a_day_under_another_name_is_refused(tmp_path: Path) -> None:
    _write(tmp_path, RECORDS[:1])
    folder = tmp_path / DAYS_DIR
    (folder / "2001-03-10.json").rename(folder / "2001-03-11.json")
    with pytest.raises(InterimError) as error:
        read_days(tmp_path)
    assert str(error.value) == INCOHERENT_NAME


def test_a_file_not_named_by_its_date_is_refused(tmp_path: Path) -> None:
    _write(tmp_path, RECORDS[:1])
    folder = tmp_path / DAYS_DIR
    (folder / "2001-03-10.json").rename(folder / "notes.json")
    with pytest.raises(InterimError) as error:
        read_days(tmp_path)
    assert str(error.value) == INCOHERENT_NAME


def test_a_folder_inside_the_days_is_refused(tmp_path: Path) -> None:
    _write(tmp_path)
    (tmp_path / DAYS_DIR / "2001-03-13.json").mkdir()
    with pytest.raises(InterimError) as error:
        read_days(tmp_path)
    assert str(error.value) == (
        "interim/ incohérent : interim/days/ porte autre chose que des documents. "
        "Lancer `mperf " + "ingest`."
    )


def test_another_document_under_a_day_name_is_refused(tmp_path: Path) -> None:
    _write(tmp_path, RECORDS[:1])
    (tmp_path / DAYS_DIR / "2001-03-11.json").write_bytes(encode_interim(HISTORY))
    with pytest.raises(CodecError, match="document de type 'TrainingStatusHistory'"):
        read_days(tmp_path)


def test_read_days_ignores_only_the_two_reserved_documents(tmp_path: Path) -> None:
    _write(tmp_path, RECORDS[:1])
    assert read_days(tmp_path) == RECORDS[:1]
    (tmp_path / DAYS_DIR / "notes.txt").write_bytes(b"x")
    with pytest.raises(CodecError, match="document illisible"):
        read_days(tmp_path)
