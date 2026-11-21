"""Le lecteur d'un export Strava (``ingest/strava.py``, AN1-3, § 6.3 du brief) : sur des
archives inventées, écrites par ``fixtures.strava_archive`` (règle 1)."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import sys
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from fixtures.strava_archive import STRAVA_HEADER, mark_encrypted, write_strava_export
from mountain_perf.ingest.strava import (
    MemberAbsent,
    MemberFit,
    MemberNotGzip,
    StravaExport,
    StravaExportError,
    StravaMembers,
    load_strava_export,
    strava_entry,
    strava_export_dirs,
)
from mountain_perf.schemas import IndexField, RefusalReason, RefusedEntry, SourceRef

AT = "2026-11-20T09:45:00+00:00"
NAME = "s1"


def _row(ident: str = "9001", **columns: str) -> dict[str, str]:
    """Une ligne : identifiant, date, type ; les autres colonnes nommées en plus."""
    return {
        "Activity ID": ident,
        "Activity Date": "Jun 1, 2026, 6:00:00 AM",
        "Activity Type": "Run",
        **columns,
    }


def _write(
    root: Path,
    rows: list[Any] | None = None,
    *,
    members: dict[str, bytes] | None = None,
    **options: Any,
) -> Path:
    return write_strava_export(
        root,
        NAME,
        retrieved_at=options.pop("retrieved_at", AT),
        rows=[_row()] if rows is None else rows,
        members={} if members is None else members,
        **options,
    )


def _load(root: Path, rows: list[Any] | None = None, **options: Any) -> StravaExport:
    return load_strava_export(_write(root, rows, **options))


def _error(folder: Path) -> str:
    with pytest.raises(StravaExportError) as error:
        load_strava_export(folder)
    return str(error.value)


# --- les dossiers d'exports (§ 6.3 (d)) ----------------------------------------------


def test_without_a_strava_folder_there_is_no_export(tmp_path: Path) -> None:
    assert strava_export_dirs(tmp_path / "raw") == []


def test_export_folders_by_name(tmp_path: Path) -> None:
    for name in ("s2", "s1"):
        write_strava_export(tmp_path, name, retrieved_at=AT, rows=[], members={})
    (tmp_path / "raw" / "strava" / "notes.txt").write_text("x", encoding="utf-8")
    assert [p.name for p in strava_export_dirs(tmp_path / "raw")] == ["s1", "s2"]


@pytest.mark.parametrize("name", ["acquisition.json", "export_1.ZIP"])
def test_an_archive_laid_flat_stops(tmp_path: Path, name: str) -> None:
    folder = tmp_path / "raw" / "strava"
    folder.mkdir(parents=True)
    (folder / name).write_bytes(b"x")
    with pytest.raises(StravaExportError) as error:
        strava_export_dirs(tmp_path / "raw")
    assert str(error.value) == (
        f"raw/strava/{name} : une archive Strava se range dans son dossier, "
        "raw/strava/<export>/ ; ranger celle-ci dans le sien."
    )


def test_an_export_name_outside_the_characters_stops(tmp_path: Path) -> None:
    (tmp_path / "raw" / "strava" / "mon export").mkdir(parents=True)
    with pytest.raises(StravaExportError) as error:
        strava_export_dirs(tmp_path / "raw")
    assert str(error.value) == (
        "raw/strava/mon export/ : le nom d'un export est fait de lettres et de "
        "chiffres ASCII, de « _ », « . » ou « - »."
    )


# --- acquisition.json et l'archive (§ 6.3 (e) 1 à 3) ---------------------------------

ACQUISITION = "raw/strava/s1/acquisition.json"


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (None, f"{ACQUISITION} manque : chaque dossier de raw/strava/ est un export, "
         "avec l'instant de son acquisition."),
        (b"\xff\xfe{", f"{ACQUISITION} : JSON en UTF-8 attendu."),
        (b"[]", f"{ACQUISITION} : objet {{retrieved_at, timezone}} attendu "
         "(timezone facultatif)."),
        (json.dumps({"retrieved_at": AT, "zone": "Europe/Paris"}).encode(),
         f"{ACQUISITION} : objet {{retrieved_at, timezone}} attendu "
         "(timezone facultatif)."),
        (json.dumps({"retrieved_at": "2026-11-20T09:45:00"}).encode(),
         f"{ACQUISITION} : retrieved_at doit être un instant ISO 8601 avec fuseau."),
        (json.dumps({"retrieved_at": 5}).encode(),
         f"{ACQUISITION} : retrieved_at doit être un instant ISO 8601 avec fuseau."),
        (json.dumps({"retrieved_at": AT, "timezone": "Mars/Olympus"}).encode(),
         f"{ACQUISITION} : timezone doit être un nom de fuseau IANA connu, par "
         "exemple « Europe/Paris »."),
        (json.dumps({"retrieved_at": AT, "timezone": 1}).encode(),
         f"{ACQUISITION} : timezone doit être un nom de fuseau IANA connu, par "
         "exemple « Europe/Paris »."),
    ],
)  # fmt: skip
def test_acquisition_refusals(
    tmp_path: Path, content: bytes | None, message: str
) -> None:
    folder = _write(tmp_path)
    path = folder / "acquisition.json"
    if content is None:
        path.unlink()
    else:
        path.write_bytes(content)
    assert _error(folder) == message


def test_the_timezone_key_is_read(tmp_path: Path) -> None:
    assert _load(tmp_path, timezone="America/New_York").timezone == "America/New_York"
    assert _load(tmp_path / "b").timezone is None


def test_without_a_zip_the_export_stops(tmp_path: Path) -> None:
    folder = _write(tmp_path)
    (folder / "export_1.zip").unlink()
    assert _error(folder) == (
        "raw/strava/s1/ : aucune archive .zip ; l'archive de Strava se range telle "
        "quelle à côté de acquisition.json."
    )


def test_two_zips_stop_the_export(tmp_path: Path) -> None:
    folder = _write(tmp_path)
    (folder / "copie.Zip").write_bytes((folder / "export_1.zip").read_bytes())
    assert _error(folder) == (
        "raw/strava/s1/ : plusieurs archives .zip ; un export Strava n'en a qu'une."
    )


def test_other_files_and_folders_beside_the_zip_are_ignored(tmp_path: Path) -> None:
    folder = _write(tmp_path)
    (folder / "notes.txt").write_text("x", encoding="utf-8")
    (folder / "sous").mkdir()
    (folder / "sous" / "autre.zip").write_bytes(b"x")
    assert len(load_strava_export(folder).rows) == 1


@pytest.mark.skipif(
    sys.platform == "win32", reason="« : » et « \\ » sont interdits dans un nom Windows"
)
@pytest.mark.parametrize("name", ["copie 12:00.zip", "a\\b.zip"])
def test_a_zip_name_the_report_cannot_hold_stops(tmp_path: Path, name: str) -> None:
    folder = _write(tmp_path)
    (folder / "export_1.zip").rename(folder / name)
    assert _error(folder) == (
        f"raw/strava/s1/{name} : nom de fichier que le rapport ne peut pas porter "
        "(« : » ou « \\ »)."
    )


ZIP = "raw/strava/s1/export_1.zip"


def _replace_zip(
    folder: Path, members: dict[str, bytes], encrypted: tuple[str, ...] = ()
) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    data = buffer.getvalue()
    if encrypted:
        data = mark_encrypted(data, encrypted)
    (folder / "export_1.zip").write_bytes(data)


def test_an_unreadable_zip_stops(tmp_path: Path) -> None:
    folder = _write(tmp_path)
    (folder / "export_1.zip").write_bytes(b"pas un zip")
    assert _error(folder) == f"{ZIP} : archive zip illisible."


def test_a_zip_without_the_index_stops(tmp_path: Path) -> None:
    folder = _write(tmp_path)
    _replace_zip(folder, {"profile.csv": b"x"})
    assert _error(folder) == f"{ZIP} : activities.csv manque dans l'archive."


def test_an_unreadable_index_stops(tmp_path: Path) -> None:
    folder = _write(tmp_path)
    _replace_zip(folder, {"activities.csv": b"x"}, encrypted=("activities.csv",))
    assert _error(folder) == f"{ZIP} : activities.csv illisible dans l'archive."


def test_an_index_that_is_not_utf8_stops(tmp_path: Path) -> None:
    folder = _write(tmp_path)
    _replace_zip(folder, {"activities.csv": b"Activity ID\xff\n"})
    assert _error(folder) == f"{ZIP} : activities.csv : texte en UTF-8 attendu."


# --- l'en-tête (§ 6.3 (e) 4) ---------------------------------------------------------


def _header_message(n: int, i: int) -> str:
    return (
        f"{ZIP} : l'en-tête d'activities.csv n'est pas celui qu'attend l'ingestion "
        f"({n} colonnes, 104 attendues ; première différence à la colonne {i}) : la "
        "forme de l'archive de Strava a changé."
    )


def _swapped(first: int, second: int) -> list[str]:
    header = list(STRAVA_HEADER)
    header[first], header[second] = header[second], header[first]
    return header


@pytest.mark.parametrize(
    ("header", "n", "i"),
    [
        ([*STRAVA_HEADER[:3], "Activity Typ", *STRAVA_HEADER[4:]], 104, 3),
        ([*STRAVA_HEADER, "Nouvelle colonne"], 105, 104),
        (list(STRAVA_HEADER[:100]), 100, 100),
        (_swapped(6, 7), 104, 6),
    ],
)
def test_a_different_header_stops(
    tmp_path: Path, header: list[str], n: int, i: int
) -> None:
    folder = _write(tmp_path, [], header=header)
    assert _error(folder) == _header_message(n, i)


def test_swapping_the_two_distances_changes_nothing(tmp_path: Path) -> None:
    assert STRAVA_HEADER[6] == STRAVA_HEADER[17] == "Distance"
    assert len(_load(tmp_path, header=_swapped(6, 17)).rows) == 1


def test_an_empty_index_stops(tmp_path: Path) -> None:
    folder = _write(tmp_path)
    _replace_zip(folder, {"activities.csv": b""})
    assert _error(folder) == _header_message(0, 0)


# --- les lignes (§ 6.3 (e) 5, (f), (g)) ----------------------------------------------


@pytest.mark.parametrize(
    ("text", "instant"),
    [
        ("Nov 18, 2026, 6:30:00 AM", datetime(2026, 11, 18, 6, 30, tzinfo=UTC)),
        ("Jul 13, 2024, 12:05:09 PM", datetime(2024, 7, 13, 12, 5, 9, tzinfo=UTC)),
        ("Jan 1, 2025, 12:00:00 AM", datetime(2025, 1, 1, 0, 0, tzinfo=UTC)),
        ("Dec 31, 2025, 11:59:59 PM", datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC)),
        ("Feb 30, 2025, 1:00:00 AM", None),
        ("Jul 13, 2024, 05:02:03 AM", None),
        ("13 Jul 2024 05:02", None),
    ],
)
def test_activity_dates(tmp_path: Path, text: str, instant: datetime | None) -> None:
    export = _load(tmp_path, [_row(**{"Activity Date": text})])
    if instant is None:
        assert export.rows == ()
        assert export.refused == (RefusedEntry(0, RefusalReason.UNUSABLE_ENTRY),)
    else:
        (row,) = export.rows
        assert row.start_utc == instant
        assert row.start_utc.utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    ("column", "text", "field", "value", "omitted"),
    [
        ("Elapsed Time", "3600.0", "elapsed_duration_s", 3600.0, False),
        ("Elapsed Time", "", "elapsed_duration_s", None, False),
        ("Elapsed Time", "abc", "elapsed_duration_s", None, True),
        ("Elapsed Time", "0", "elapsed_duration_s", None, True),
        ("Elapsed Time", "nan", "elapsed_duration_s", None, True),
        ("Moving Time", "0", "moving_duration_s", 0.0, False),
        ("Distance", "inf", "distance_m", None, True),
        ("Distance", "10450.5", "distance_m", 10450.5, False),
        ("Elevation Gain", "-1", "ascent_m", None, True),
        ("Elevation Loss", "798.25", "descent_m", 798.25, False),
        ("Max Heart Rate", "251", "max_hr_bpm", None, True),
        ("Average Heart Rate", "141", "average_hr_bpm", 141.0, False),
    ],
)
def test_numbers(
    tmp_path: Path,
    column: str,
    text: str,
    field: str,
    value: float | None,
    omitted: bool,
) -> None:
    (row,) = _load(tmp_path, [_row(**{column: text})]).rows
    assert getattr(row, field) == value
    assert (IndexField(field) in row.omitted_fields) is omitted


def test_the_read_ranks_of_the_doubled_names(tmp_path: Path) -> None:
    """Les premières ``Elapsed Time``, ``Distance`` et ``Max Heart Rate`` (plausibles)
    ne sont pas lues : seules les secondes."""
    (row,) = _load(tmp_path).rows
    assert (row.elapsed_duration_s, row.distance_m, row.max_hr_bpm) == (None,) * 3


def test_a_duplicated_identifier_refuses_all_its_rows(tmp_path: Path) -> None:
    export = _load(tmp_path, [_row("9011"), _row("9011"), _row("9012")])
    assert export.refused == (
        RefusedEntry(0, RefusalReason.DUPLICATE_ENTRY),
        RefusedEntry(1, RefusalReason.DUPLICATE_ENTRY),
    )
    assert [row.activity_ref for row in export.rows] == ["strava-9012"]


def test_unusable_rows(tmp_path: Path) -> None:
    short = ["9002", "Jun 1, 2026, 6:00:00 AM", "Sortie", "Run"] + [""] * 99
    assert len(short) == 103
    export = _load(
        tmp_path,
        [
            short,
            _row("9003", **{"Activity Type": "  "}),
            _row("x9004"),
            _row("9005"),
        ],
    )
    assert export.refused == tuple(
        RefusedEntry(rank, RefusalReason.UNUSABLE_ENTRY) for rank in (0, 1, 2)
    )
    assert [row.activity_ref for row in export.rows] == ["strava-9005"]


def test_bad_filename_kept_without_file(tmp_path: Path) -> None:
    export = _load(
        tmp_path,
        [
            _row("9001", Filename="../x.fit.gz"),
            _row("9002", Filename="activities/9002.fit.gz"),
            _row("9003", Filename="C:\\x.fit.gz"),
            _row("9004", Filename=""),
        ],
    )
    assert [row.filename for row in export.rows] == [
        None,
        "activities/9002.fit.gz",
        None,
        None,
    ]
    assert export.named_files == 1


def test_period_start_named_files_and_provenance(tmp_path: Path) -> None:
    export = _load(
        tmp_path,
        [
            _row("9001", **{"Activity Date": "Jul 1, 2026, 6:00:00 AM"}),
            _row(
                "9002",
                Filename="activities/9002.gpx",
                **{"Activity Date": "Jun 2, 2026, 6:00:00 AM"},
            ),
        ],
    )
    assert export.period_start == datetime(2026, 6, 2, 6, tzinfo=UTC)
    assert export.named_files == 1
    assert export.name == NAME
    assert export.retrieved_at == datetime.fromisoformat(AT)
    assert export.archive.name == "export_1.zip"
    with zipfile.ZipFile(export.archive) as archive:
        index = archive.read("activities.csv")
    archive_bytes = export.archive.read_bytes()
    assert export.archive_hash == hashlib.sha256(archive_bytes).hexdigest()
    assert export.index_source == SourceRef(
        "strava_activities",
        "activities.csv",
        hashlib.sha256(index).hexdigest(),
        datetime.fromisoformat(AT),
    )


def test_without_a_kept_row_there_is_no_period(tmp_path: Path) -> None:
    export = _load(tmp_path, [])
    assert (export.rows, export.period_start, export.named_files) == ((), None, 0)


def test_a_row_after_the_acquisition_stops(tmp_path: Path) -> None:
    late = _row(**{"Activity Date": "Nov 20, 2026, 9:45:01 AM"})
    assert _error(_write(tmp_path, [late])) == (
        "raw/strava/s1/ : une activité de l'index part après l'instant d'acquisition "
        "de l'export ; acquisition.json est faux."
    )
    at = _row(**{"Activity Date": "Nov 20, 2026, 9:45:00 AM"})
    assert len(_load(tmp_path / "b", [at]).rows) == 1


# --- l'entrée d'index (§ 6.3 (h)) ----------------------------------------------------


PARIS = "Europe/Paris"
NEW_YORK = "America/New_York"


@pytest.mark.parametrize(
    ("date", "offset_s", "zone", "start", "default"),
    [
        ("Nov 18, 2026, 6:30:00 AM", 3600, None, "2026-11-18T07:30:00+01:00", False),
        ("Jul 13, 2024, 12:05:09 PM", None, PARIS, "2024-07-13T14:05:09+02:00", False),
        ("Jul 13, 2024, 12:05:09 PM", None, None, "2024-07-13T14:05:09+02:00", True),
        (
            "Jan 1, 2025, 12:00:00 AM",
            None,
            NEW_YORK,
            "2024-12-31T19:00:00-05:00",
            False,
        ),
        (
            "Nov 18, 2026, 6:30:00 AM",
            3600,
            NEW_YORK,
            "2026-11-18T07:30:00+01:00",
            False,
        ),
        ("Mar 30, 2025, 12:59:59 AM", None, None, "2025-03-30T01:59:59+01:00", True),
        ("Mar 30, 2025, 1:00:00 AM", None, None, "2025-03-30T03:00:00+02:00", True),
    ],
    ids=[
        "fit",
        "paris",
        "defaut",
        "new-york",
        "new-york-fit",
        "avant-heure-ete",
        "heure-ete",
    ],
)
def test_strava_entry(
    tmp_path: Path,
    date: str,
    offset_s: int | None,
    zone: str | None,
    start: str,
    default: bool,
) -> None:
    export = _load(
        tmp_path,
        [_row(**{"Activity Date": date, "Elevation Gain": "12.5"})],
        timezone=zone,
    )
    (row,) = export.rows
    entry, by_default = strava_entry(row, export, offset_s)
    expected = datetime.fromisoformat(start)
    assert entry.start_time == expected
    assert entry.start_time.utcoffset() == expected.utcoffset()
    assert by_default is default
    assert entry.activity_ref == row.activity_ref
    assert entry.source_activity_type == "Run"
    assert entry.ascent_m == 12.5
    assert (entry.elevation_corrected, entry.training_load) == (None, None)
    assert entry.has_recording is False
    assert entry.source == export.index_source


# --- ce qui s'ouvre dans le zip (§ 6.3 (i), (k)) -------------------------------------


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Les noms que ``ZipFile.open`` ouvre (``ZipFile.read`` l'appelle)."""
    names: list[str] = []
    real = zipfile.ZipFile.open

    def recorded(self: zipfile.ZipFile, name: Any, *args: Any, **kwargs: Any) -> Any:
        names.append(name if isinstance(name, str) else name.filename)
        return real(self, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "open", recorded)
    return names


def test_only_named_members_are_opened(tmp_path: Path, opened: list[str]) -> None:
    fit = gzip.compress(b"octets", mtime=0)
    folder = _write(
        tmp_path,
        [
            _row("9001", Filename="activities/9001.fit.gz"),
            _row("9002", Filename="../x.fit.gz"),
            _row("9003", Filename="activities/9003.gpx"),
        ],
        members={"activities/9001.fit.gz": fit, "activities/9003.gpx": b"<gpx/>"},
    )
    opened.clear()  # l'écriture de l'archive ouvre ses membres en écriture
    export = load_strava_export(folder)
    with StravaMembers(export) as members:
        for row in export.rows:
            if row.filename is not None:
                members.read(row.filename)
    allowed = {"activities.csv"} | {
        row.filename for row in export.rows if row.filename is not None
    }
    assert opened
    assert set(opened) <= allowed
    assert "../x.fit.gz" not in opened
    assert set(opened) == allowed


def test_members_read_has_three_outcomes(tmp_path: Path) -> None:
    fit = b"un FIT invente"
    export = _load(
        tmp_path,
        members={
            "activities/1.fit.gz": gzip.compress(fit, mtime=0),
            "activities/2.fit.gz": fit,
        },
    )
    with StravaMembers(export) as members:
        assert members.read("activities/1.fit.gz") == MemberFit(
            gzip.compress(fit, mtime=0), fit
        )
        assert members.read("activities/2.fit.gz") == MemberNotGzip(fit)
        assert members.read("activities/3.fit.gz") == MemberAbsent()
        assert members.read("profile.csv") == MemberAbsent()
