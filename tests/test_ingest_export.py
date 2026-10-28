"""L'ingestion d'exports synthétiques, de bout en bout (``ingest/export.py``, ``mperf
ingest``) : un export rangé dans son dossier, ``raw/garmin/<export>/`` (AN2-0) ; les
cas à plusieurs exports sont à la fin."""

from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fitdecode")

from fixtures.fit_activity import Sample, activity_fit
from mountain_perf.cli import main
from mountain_perf.ingest.export import (
    ACQUISITION_FILE,
    IngestError,
    IngestionSummary,
    ingest_export,
    read_acquisition,
)
from mountain_perf.ingest.interim import (
    ACTIVITIES_DIR,
    read_index,
    read_recording,
    read_report,
)
from mountain_perf.schemas import (
    FieldDifferenceCount,
    IndexDifference,
    IndexField,
    RecordingMismatch,
    RefusalReason,
    RetiredActivity,
    ViewRefusal,
    ViewRefusalCount,
)
from test_ingest_index import item

AT = "2024-04-01T12:34:56+02:00"
EXPORT = "garmin_a"


def _zip(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)


def make_export(
    root: Path,
    *,
    acquisition: Any = None,
    items: list[Any] | None = None,
    name: str = EXPORT,
) -> Path:
    raw = root / "raw" / "garmin" / name
    (raw / "activities").mkdir(parents=True)
    (raw / "activity_fit").mkdir()
    if acquisition is not False:
        content = {"retrieved_at": AT} if acquisition is None else acquisition
        (raw / "acquisition.json").write_text(json.dumps(content), encoding="utf-8")
    entries = (
        items
        if items is not None
        else [
            item(activityId=1),
            item(
                activityId=2,
                startTimeLocal="2024-03-10 09:00:00",
                startTimeGMT="2024-03-10 08:00:00",
            ),
            item(activityId=3, activityType={"typeKey": "golf"}),
            item(activityId=4),
        ]
    )
    (raw / "activities" / "activities.json").write_text(
        json.dumps(entries), encoding="utf-8"
    )
    good = activity_fit(
        [Sample(t, lat=45.0, lon=6.0 + t / 1e4, heart_rate=100) for t in range(3)]
    )
    _zip(raw / "activity_fit" / "1.zip", {"1_ACTIVITY.fit": good})
    _zip(
        raw / "activity_fit" / "2.zip",
        {"2_ACTIVITY.fit": activity_fit([Sample(0, heart_rate=90)], corrupt_crc=True)},
    )
    _zip(raw / "activity_fit" / "3.zip", {"a.fit": good, "b.fit": good})
    _zip(raw / "activity_fit" / "9.zip", {"9_ACTIVITY.fit": good})
    return root


def test_ingestion_writes_index_recordings_and_report(tmp_path: Path) -> None:
    summary = ingest_export(make_export(tmp_path))
    assert (
        summary.activities,
        summary.recordings,
        summary.refused_files,
        summary.refused_entries,
        summary.entries_without_archive,
        summary.mismatches,
    ) == (4, 1, 3, 0, 1, 1)
    assert summary.view_refusals == (ViewRefusalCount(ViewRefusal.NO_SPORT, "golf", 1),)
    index = read_index(tmp_path)
    assert [(e.activity_ref, e.has_recording) for e in index.entries] == [
        ("1", True),
        ("3", False),
        ("4", False),
        ("2", False),
    ]
    (source,) = index.exports
    assert source.kind == "garmin_activities"
    assert source.identifier == "activities.json"
    assert source.retrieved_at.isoformat() == "2024-04-01T10:34:56+00:00"
    assert {e.source for e in index.entries} == {source}
    rec = read_recording(tmp_path, "1")
    assert rec.source.kind == "garmin_fit"
    assert rec.source.identifier == "1.zip"
    assert (
        rec.source.content_hash
        == __import__("hashlib")
        .sha256(
            (
                tmp_path / "raw" / "garmin" / EXPORT / "activity_fit" / "1.zip"
            ).read_bytes()
        )
        .hexdigest()
    )
    report = read_report(tmp_path)
    assert [f.name for f in report.read] == [
        f"garmin/{EXPORT}/acquisition.json",
        f"garmin/{EXPORT}/activities/activities.json",
        f"garmin/{EXPORT}/activity_fit/1.zip",
        f"garmin/{EXPORT}/activity_fit/2.zip",
        f"garmin/{EXPORT}/activity_fit/3.zip",
        f"garmin/{EXPORT}/activity_fit/9.zip",
    ]
    assert [(f.name, f.reason) for f in report.refused_files] == [
        (f"garmin/{EXPORT}/activity_fit/2.zip", RefusalReason.UNREADABLE_FIT),
        (f"garmin/{EXPORT}/activity_fit/3.zip", RefusalReason.NOT_ONE_FIT),
        (f"garmin/{EXPORT}/activity_fit/9.zip", RefusalReason.NOT_IN_INDEX),
    ]
    assert report.view_refusals == summary.view_refusals
    # le FIT part à 07:30 UTC pour 60 s ; l'entrée, à 08:30 UTC pour 3 723,5 s
    assert report.mismatches == (RecordingMismatch("1", -3600.0, 60.0, 3723.5),)


def test_two_ingestions_write_the_same_bytes(tmp_path: Path) -> None:
    make_export(tmp_path)
    ingest_export(tmp_path)
    first = {
        p.relative_to(tmp_path): p.read_bytes()
        for p in (tmp_path / ACTIVITIES_DIR).rglob("*")
        if p.is_file()
    }
    ingest_export(tmp_path)
    second = {
        p.relative_to(tmp_path): p.read_bytes()
        for p in (tmp_path / ACTIVITIES_DIR).rglob("*")
        if p.is_file()
    }
    assert first == second


def test_raw_is_not_written(tmp_path: Path) -> None:
    make_export(tmp_path)
    before = {
        p: (p.stat().st_mtime_ns, p.read_bytes())
        for p in (tmp_path / "raw").rglob("*")
        if p.is_file()
    }
    ingest_export(tmp_path)
    after = {
        p: (p.stat().st_mtime_ns, p.read_bytes())
        for p in (tmp_path / "raw").rglob("*")
        if p.is_file()
    }
    assert before == after


@pytest.mark.parametrize(
    ("acquisition", "message"),
    [
        (False, "acquisition.json manque"),
        ({"retrieved_at": "2024-04-01T12:34:56"}, "fuseau"),
        ({"retrieved_at": "hier"}, "fuseau"),
        ({"retrieved_at": AT, "autre": 1}, "retrieved_at"),
        ([AT], "retrieved_at"),
    ],
)
def test_export_without_acquisition_instant_is_refused(
    tmp_path: Path, acquisition: Any, message: str
) -> None:
    make_export(tmp_path, acquisition=acquisition)
    with pytest.raises(IngestError, match=message):
        ingest_export(tmp_path)
    assert not (tmp_path / "interim").exists()


def test_cli_ingest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_export(tmp_path)
    monkeypatch.setenv("MPA_DATA_DIR", str(tmp_path))
    assert main(["ingest"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "Exports : 1",
        f"  {EXPORT} : acquis le 2024-04-01T10:34:56+00:00, 4 entrées gardées, "
        "0 refusées, 4 archives",
        "Activités dans l'index : 4",
        "Enregistrements : 1",
        "Fichiers refusés : 3",
        "Entrées de l'index refusées : 0",
        "Entrées sans archive : 1",
        "Enregistrements en désaccord avec l'index : 1",
        "Activités sans vue Activity : 1",
        "  no_sport : golf (1)",
        "Activités retirées de la source : 0",
        "Champs de l'index qui diffèrent d'un export à l'autre : 0",
        "Activités aux FIT différents d'un export à l'autre : 0",
        "Enregistrements tirés d'un autre export que leur entrée : 0",
    ]


def test_cli_ingest_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_export(tmp_path, acquisition=False)
    monkeypatch.setenv("MPA_DATA_DIR", str(tmp_path))
    assert main(["ingest"]) == 1
    assert capsys.readouterr().err.startswith(
        f"Erreur : raw/garmin/{EXPORT}/acquisition.json manque"
    )


# --- compléments du balayage par mutation ----------------------------------------


def test_archive_cases(tmp_path: Path) -> None:
    make_export(tmp_path)
    fit_dir = tmp_path / "raw" / "garmin" / EXPORT / "activity_fit"
    good = (fit_dir / "1.zip").read_bytes()
    (fit_dir / "0.zip").write_bytes(good)  # absente de l'index, triée en tête
    _zip(
        fit_dir / "4.zip",
        {"4.fit": activity_fit([Sample(0, heart_rate=90)]), "x.txt": b"x"},
    )
    (fit_dir / "5.zip").write_bytes(b"pas une archive")
    (fit_dir / "0-dossier").mkdir()  # trié avant toute archive
    summary = ingest_export(tmp_path)
    refused = {f.name: f.reason for f in read_report(tmp_path).refused_files}
    assert refused[f"garmin/{EXPORT}/activity_fit/0.zip"] is RefusalReason.NOT_IN_INDEX
    assert refused[f"garmin/{EXPORT}/activity_fit/4.zip"] is RefusalReason.NOT_ONE_FIT
    assert refused[f"garmin/{EXPORT}/activity_fit/5.zip"] is RefusalReason.NOT_IN_INDEX
    assert summary.recordings == 1
    assert f"garmin/{EXPORT}/activity_fit/0-dossier" not in {
        f.name for f in read_report(tmp_path).read
    }


def test_not_a_zip_is_refused(tmp_path: Path) -> None:
    make_export(tmp_path)
    (tmp_path / "raw" / "garmin" / EXPORT / "activity_fit" / "4.zip").write_bytes(
        b"pas une archive"
    )
    ingest_export(tmp_path)
    refused = {f.name: f.reason for f in read_report(tmp_path).refused_files}
    assert refused[f"garmin/{EXPORT}/activity_fit/4.zip"] is RefusalReason.NOT_ONE_FIT


def test_export_without_fit_folder(tmp_path: Path) -> None:
    make_export(tmp_path)
    for path in (tmp_path / "raw" / "garmin" / EXPORT / "activity_fit").iterdir():
        path.unlink()
    (tmp_path / "raw" / "garmin" / EXPORT / "activity_fit").rmdir()
    summary = ingest_export(tmp_path)
    assert dataclasses.replace(summary, exports=()) == IngestionSummary(
        exports=(),
        activities=4,
        recordings=0,
        refused_files=0,
        refused_entries=0,
        entries_without_archive=4,
        mismatches=0,
        view_refusals=(ViewRefusalCount(ViewRefusal.NO_SPORT, "golf", 1),),
        retired=0,
        index_differences=(),
        fit_differences=0,
        recordings_from_other_export=0,
    )
    assert summary.exports[0].archives == 0


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("absent", f"raw/garmin/{EXPORT}/activities/activities.json manque."),
        (
            "objet",
            f"raw/garmin/{EXPORT}/activities/activities.json : liste d'activités "
            "attendue.",
        ),
        (
            "acquisition",
            f"raw/garmin/{EXPORT}/acquisition.json : JSON en UTF-8 attendu.",
        ),
        (
            "sans",
            f"raw/garmin/{EXPORT}/acquisition.json manque : chaque dossier de "
            "raw/garmin/ est un export, avec l'instant de son acquisition.",
        ),
        (
            "nombre",
            f"raw/garmin/{EXPORT}/acquisition.json : retrieved_at doit être un instant "
            "ISO 8601 avec fuseau.",
        ),
        (
            "cle",
            f"raw/garmin/{EXPORT}/acquisition.json : objet {{retrieved_at}} attendu.",
        ),
    ],
)
def test_export_errors_have_exact_messages(
    tmp_path: Path, change: str, message: str
) -> None:
    make_export(tmp_path)
    raw = tmp_path / "raw" / "garmin" / EXPORT
    if change == "absent":
        (raw / "activities" / "activities.json").unlink()
    elif change == "objet":
        (raw / "activities" / "activities.json").write_text("{}", encoding="utf-8")
    elif change == "sans":
        (raw / "acquisition.json").unlink()
    elif change == "acquisition":
        (raw / "acquisition.json").write_text("{", encoding="utf-8")
    elif change == "cle":
        (raw / "acquisition.json").write_text(
            json.dumps({"retrieved_at": AT, "x": 1}), encoding="utf-8"
        )
    else:
        (raw / "acquisition.json").write_text('{"retrieved_at": 5}', encoding="utf-8")
    with pytest.raises(IngestError) as error:
        ingest_export(tmp_path)
    assert str(error.value) == message


def test_acquisition_written_with_a_byte_order_mark_is_read(tmp_path: Path) -> None:
    """Un fichier écrit à la main sous Windows commence souvent par une marque d'ordre
    des octets : elle est admise ; l'UTF-16, non."""
    make_export(tmp_path)
    path = tmp_path / "raw" / "garmin" / EXPORT / ACQUISITION_FILE
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"retrieved_at": AT}).encode())
    assert read_acquisition(tmp_path / "raw" / "garmin" / EXPORT).isoformat() == AT
    path.write_bytes(json.dumps({"retrieved_at": AT}).encode("utf-16"))
    with pytest.raises(IngestError) as error:
        read_acquisition(tmp_path / "raw" / "garmin" / EXPORT)
    assert (
        str(error.value)
        == f"raw/garmin/{EXPORT}/acquisition.json : JSON en UTF-8 attendu."
    )


def _fits_for(root: Path, refs: list[int]) -> None:
    """Remplace les archives par un FIT lisible (départ ``START``, 60 s) par
    identifiant."""
    fit_dir = root / "raw" / "garmin" / EXPORT / "activity_fit"
    for path in fit_dir.iterdir():
        path.unlink()
    good = activity_fit(
        [Sample(t, lat=45.0, lon=6.0, heart_rate=100) for t in range(3)]
    )
    for ref in refs:
        _zip(fit_dir / f"{ref}.zip", {f"{ref}_ACTIVITY.fit": good})


def test_mismatches_beyond_one_second(tmp_path: Path) -> None:
    """Le FIT part à 07:30:00 UTC pour 60 s (une session) ; écart de 1 s toléré, au
    départ comme au temps écoulé ; sans temps écoulé dans l'index, seul le départ
    compte."""

    def at(ref: int, gmt: str, **changes: Any) -> dict[str, Any]:
        local = f"2024-03-09 {int(gmt[:2]) + 1:02d}{gmt[2:]}"
        return item(
            activityId=ref,
            startTimeGMT=f"2024-03-09 {gmt}",
            startTimeLocal=local,
            **changes,
        )

    items = [
        at(1, "07:30:00", elapsedDuration=61.0),
        at(2, "07:30:01", elapsedDuration=60.0),
        at(3, "07:29:58", elapsedDuration=60.0),
        at(4, "07:30:00", elapsedDuration=61.5),
        at(5, "07:30:00", elapsedDuration=None),
        at(6, "07:30:02", elapsedDuration=None),
    ]
    make_export(tmp_path, items=items)
    _fits_for(tmp_path, [1, 2, 3, 4, 5, 6])
    summary = ingest_export(tmp_path)
    assert summary.mismatches == 3
    assert read_report(tmp_path).mismatches == (
        RecordingMismatch("3", 2.0, 60.0, 60.0),
        RecordingMismatch("4", 0.0, 60.0, 61.5),
        RecordingMismatch("6", -2.0, 60.0, None),
    )


def test_view_refusals_are_counted_by_reason_and_type(tmp_path: Path) -> None:
    items = [
        item(activityId=1, activityType={"typeKey": "golf"}),
        item(activityId=2, activityType={"typeKey": "sailing"}),
        item(activityId=3, activityType={"typeKey": "golf"}),
        item(activityId=4, movingDuration=None),
        item(activityId=5, averageHR=180.0),
        item(activityId=6, movingDuration=None, activityType={"typeKey": "hiking"}),
        item(activityId=7),
    ]
    make_export(tmp_path, items=items)
    _fits_for(tmp_path, [])
    summary = ingest_export(tmp_path)
    expected = (
        ViewRefusalCount(ViewRefusal.INVARIANT, "trail_running", 1),
        ViewRefusalCount(ViewRefusal.MISSING_FIELD, "hiking", 1),
        ViewRefusalCount(ViewRefusal.MISSING_FIELD, "trail_running", 1),
        ViewRefusalCount(ViewRefusal.NO_SPORT, "golf", 2),
        ViewRefusalCount(ViewRefusal.NO_SPORT, "sailing", 1),
    )
    assert summary.view_refusals == expected
    assert read_report(tmp_path).view_refusals == expected
    assert summary.entries_without_archive == 7


def test_cli_lists_the_view_refusals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    items = [
        item(activityId=1, activityType={"typeKey": "golf"}),
        item(activityId=2, averageHR=180.0),
        item(activityId=3, activityType={"typeKey": "golf"}),
    ]
    make_export(tmp_path, items=items)
    _fits_for(tmp_path, [])
    monkeypatch.setenv("MPA_DATA_DIR", str(tmp_path))
    assert main(["ingest"]) == 0
    out = capsys.readouterr().out.splitlines()
    first = out.index("Activités sans vue Activity : 3")
    assert out[first : first + 3] == [
        "Activités sans vue Activity : 3",
        "  invariant : trail_running (1)",
        "  no_sport : golf (2)",
    ]


def test_a_session_without_elapsed_time_compares_the_start_only(tmp_path: Path) -> None:
    """Une session sans temps écoulé : pas de temps écoulé de l'enregistrement (None),
    et seul le départ se compare ; une session au temps écoulé nul compte pour 0 s."""
    make_export(
        tmp_path,
        items=[
            item(
                activityId=1,
                startTimeGMT="2024-03-09 07:30:00",
                startTimeLocal="2024-03-09 08:30:00",
                elapsedDuration=500.0,
            ),
            item(
                activityId=2,
                startTimeGMT="2024-03-09 07:29:57",
                startTimeLocal="2024-03-09 08:29:57",
                elapsedDuration=500.0,
            ),
            item(
                activityId=3,
                startTimeGMT="2024-03-09 07:30:00",
                startTimeLocal="2024-03-09 08:30:00",
                elapsedDuration=1.5,
            ),
        ],
    )
    fit_dir = tmp_path / "raw" / "garmin" / EXPORT / "activity_fit"
    for path in fit_dir.iterdir():
        path.unlink()
    samples = [Sample(t, heart_rate=100) for t in range(2)]
    no_elapsed = activity_fit(
        samples, sessions=((0, "running", "trail", None, 60.0, 1.0),)
    )
    zero = activity_fit(samples, sessions=((0, "running", "trail", 0.0, 0.0, 1.0),))
    _zip(fit_dir / "1.zip", {"1_ACTIVITY.fit": no_elapsed})
    _zip(fit_dir / "2.zip", {"2_ACTIVITY.fit": no_elapsed})
    _zip(fit_dir / "3.zip", {"3_ACTIVITY.fit": zero})
    ingest_export(tmp_path)
    assert read_recording(tmp_path, "1").sessions[0].elapsed_duration_s is None
    assert read_report(tmp_path).mismatches == (
        RecordingMismatch("2", 3.0, None, 500.0),
        RecordingMismatch("3", 0.0, 0.0, 1.5),
    )


def test_archives_with_the_same_identifier_are_all_refused(tmp_path: Path) -> None:
    """Deux fichiers de ``activity_fit/`` au même nom sans extension : tous refusés, et
    l'activité n'a pas d'enregistrement."""
    make_export(tmp_path)
    fit_dir = tmp_path / "raw" / "garmin" / EXPORT / "activity_fit"
    (fit_dir / "1.bak").write_bytes((fit_dir / "1.zip").read_bytes())
    summary = ingest_export(tmp_path)
    assert summary.recordings == 0
    refused = {f.name: f.reason for f in read_report(tmp_path).refused_files}
    assert (
        refused[f"garmin/{EXPORT}/activity_fit/1.bak"]
        is RefusalReason.DUPLICATE_ARCHIVE
    )
    assert (
        refused[f"garmin/{EXPORT}/activity_fit/1.zip"]
        is RefusalReason.DUPLICATE_ARCHIVE
    )
    assert not read_index(tmp_path).entries[0].has_recording


def test_a_duplicate_archive_is_refused_before_the_index_is_checked(
    tmp_path: Path,
) -> None:
    """``9`` n'est pas dans l'index : ses deux fichiers sont des doublons d'abord."""
    make_export(tmp_path)
    fit_dir = tmp_path / "raw" / "garmin" / EXPORT / "activity_fit"
    for name in ("9.zip", "9.bak"):
        (fit_dir / name).write_bytes((fit_dir / "1.zip").read_bytes())
    ingest_export(tmp_path)
    refused = {f.name: f.reason for f in read_report(tmp_path).refused_files}
    assert (
        refused[f"garmin/{EXPORT}/activity_fit/9.bak"]
        is RefusalReason.DUPLICATE_ARCHIVE
    )
    assert (
        refused[f"garmin/{EXPORT}/activity_fit/9.zip"]
        is RefusalReason.DUPLICATE_ARCHIVE
    )


@pytest.mark.skipif(
    sys.platform == "win32", reason="« : » et « \\ » sont interdits dans un nom Windows"
)
@pytest.mark.parametrize("name", ["copie 12:00.zip", "a\\b.zip"])
def test_a_name_the_report_cannot_hold_stops_the_ingestion(
    tmp_path: Path, name: str
) -> None:
    make_export(tmp_path)
    (tmp_path / "raw" / "garmin" / EXPORT / "activity_fit" / name).write_bytes(b"x")
    with pytest.raises(IngestError) as error:
        ingest_export(tmp_path)
    assert str(error.value) == (
        f"raw/garmin/{EXPORT}/activity_fit/{name} : nom de fichier que le rapport ne "
        "peut pas porter (« : » ou « \\ »)."
    )
    assert not (tmp_path / "interim").exists()


def _stored_zip(
    member: str, data: bytes, compression: int = zipfile.ZIP_STORED
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as zf:
        zf.writestr(member, data)
    return buffer.getvalue()


_COMPRESSIONS = {
    "crc": zipfile.ZIP_STORED,
    "compression": zipfile.ZIP_STORED,
    "chiffre": zipfile.ZIP_STORED,
    "deflate": zipfile.ZIP_DEFLATED,
    "bzip2": zipfile.ZIP_BZIP2,
    "lzma": zipfile.ZIP_LZMA,
    "repertoire": zipfile.ZIP_DEFLATED,
    "nom": zipfile.ZIP_DEFLATED,
}


@pytest.mark.parametrize("damage", list(_COMPRESSIONS))
def test_an_unreadable_member_is_not_one_fit(tmp_path: Path, damage: str) -> None:
    """Une archive ou un membre illisible (CRC faux ; méthode de compression
    inconnue ; contenu chiffré, ``RuntimeError`` ; flux deflate, bzip2 ou lzma
    corrompu, ``zlib.error``, ``OSError``, ``lzma.LZMAError`` ; répertoire central
    incohérent, nom de membre annoncé en UTF-8 qui ne l'est pas, ``ValueError``) :
    l'archive est refusée ``NOT_ONE_FIT``, et l'ingestion continue."""
    make_export(tmp_path)
    fit = activity_fit([Sample(t, heart_rate=100) for t in range(30)])
    member = "1_ACTIVITY.fit"
    archive = bytearray(_stored_zip(member, fit, _COMPRESSIONS[damage]))
    start = 30 + len(member)
    if damage == "crc":
        archive[start] ^= 0xFF
    elif damage == "compression":
        for header in (b"PK\x03\x04", b"PK\x01\x02"):
            at = archive.index(header)
            offset = 8 if header == b"PK\x03\x04" else 10
            archive[at + offset : at + offset + 2] = (99).to_bytes(2, "little")
    elif damage == "chiffre":
        for header in (b"PK\x03\x04", b"PK\x01\x02"):
            at = archive.index(header)
            archive[at + (6 if header == b"PK\x03\x04" else 8)] |= 0x01
    elif damage == "repertoire":
        # le décalage du répertoire central, dans l'enregistrement de fin d'archive
        archive[archive.index(b"PK\x05\x06") + 19] = 0x80
    elif damage == "nom":
        # nom marqué UTF-8 (bit 11 des drapeaux) dont le premier octet ne l'est pas
        for header, flags, name in ((b"PK\x03\x04", 6, 30), (b"PK\x01\x02", 8, 46)):
            at = archive.index(header)
            archive[at + flags + 1] |= 0x08
            archive[at + name] = 0xFF
    else:
        # au-delà des en-têtes du flux (celui de lzma dans un zip compte 9 octets)
        for k in range(start + 16, start + 22):
            archive[k] ^= 0xFF
    (tmp_path / "raw" / "garmin" / EXPORT / "activity_fit" / "1.zip").write_bytes(
        bytes(archive)
    )
    summary = ingest_export(tmp_path)
    assert summary.recordings == 0
    refused = {f.name: f.reason for f in read_report(tmp_path).refused_files}
    assert refused[f"garmin/{EXPORT}/activity_fit/1.zip"] is RefusalReason.NOT_ONE_FIT


# --- garanties du § 5.7 que la relecture C a mutées sans test ----------------------


def test_an_archive_whose_only_member_is_not_a_fit_is_not_one_fit(
    tmp_path: Path,
) -> None:
    make_export(tmp_path)
    fit = activity_fit([Sample(t, heart_rate=100) for t in range(3)])
    _zip(
        tmp_path / "raw" / "garmin" / EXPORT / "activity_fit" / "1.zip",
        {"1_ACTIVITY.txt": fit},
    )
    assert ingest_export(tmp_path).recordings == 0
    refused = {f.name: f.reason for f in read_report(tmp_path).refused_files}
    assert refused[f"garmin/{EXPORT}/activity_fit/1.zip"] is RefusalReason.NOT_ONE_FIT


def test_the_fit_suffix_ignores_case(tmp_path: Path) -> None:
    make_export(tmp_path)
    fit = activity_fit([Sample(t, heart_rate=100) for t in range(3)])
    _zip(
        tmp_path / "raw" / "garmin" / EXPORT / "activity_fit" / "1.zip",
        {"1_ACTIVITY.FIT": fit},
    )
    assert ingest_export(tmp_path).recordings == 1


def test_another_error_reading_the_acquisition_instant_propagates(
    tmp_path: Path,
) -> None:
    """Une autre erreur d'E/S que l'absence du fichier (ici, un dossier à sa place) :
    ``OSError``, pas « manque »."""
    make_export(tmp_path, acquisition=False)
    (tmp_path / "raw" / "garmin" / EXPORT / ACQUISITION_FILE).mkdir()
    with pytest.raises(OSError):  # noqa: PT011 - le type exact varie selon le système
        read_acquisition(tmp_path / "raw" / "garmin" / EXPORT)
    with pytest.raises(OSError):  # noqa: PT011
        ingest_export(tmp_path)


def test_the_acquisition_instant_is_read_before_the_index(tmp_path: Path) -> None:
    make_export(tmp_path, acquisition=False)
    (tmp_path / "raw" / "garmin" / EXPORT / "activities" / "activities.json").unlink()
    with pytest.raises(IngestError) as error:
        ingest_export(tmp_path)
    assert str(error.value).startswith(f"raw/garmin/{EXPORT}/acquisition.json manque")


def test_the_report_and_the_index_carry_the_hashes_of_their_files(
    tmp_path: Path,
) -> None:
    """Les empreintes d'``acquisition.json`` et de l'index, au rapport, et celle de
    l'index dans sa ``SourceRef`` (celle que les vues ``Activity`` recopient)."""
    make_export(tmp_path)
    ingest_export(tmp_path)
    raw = tmp_path / "raw" / "garmin" / EXPORT
    acquisition = hashlib.sha256((raw / ACQUISITION_FILE).read_bytes()).hexdigest()
    index_file = raw / "activities" / "activities.json"
    index_hash = hashlib.sha256(index_file.read_bytes()).hexdigest()
    assert acquisition != index_hash
    hashes = {f.name: f.content_hash for f in read_report(tmp_path).read}
    assert hashes[f"garmin/{EXPORT}/acquisition.json"] == acquisition
    assert hashes[f"garmin/{EXPORT}/activities/activities.json"] == index_hash
    assert read_index(tmp_path).exports[0].content_hash == index_hash
    assert read_index(tmp_path).entries[0].source.content_hash == index_hash


# Plusieurs exports (AN2-0) : l'ancien, b_ancien, et le récent, a_recent, nommés à
# rebours de leurs instants pour que l'ordre suive l'instant, pas le nom.

OLD, NEW = "b_ancien", "a_recent"
OLD_AT, NEW_AT = "2024-04-01T12:34:56+02:00", "2024-07-01T12:00:00+02:00"


def _entry(ref: int, gmt: str, **changes: Any) -> dict[str, Any]:
    """Une entrée qui part à ``gmt`` (« AAAA-MM-JJ HH:MM:SS », UTC), heure locale à
    UTC+1, comme le FIT de ``_fit``."""
    day, time = gmt.split()
    hour = int(time[:2]) + 1
    fields: dict[str, Any] = {
        "activityId": ref,
        "startTimeGMT": gmt,
        "startTimeLocal": f"{day} {hour:02d}{time[2:]}",
    }
    return item(**{**fields, **changes})


def _fit(gmt: str, heart_rate: int = 100) -> bytes:
    """Un FIT lisible qui part à ``gmt`` (UTC), son temps écoulé celui d'``item``."""
    return activity_fit(
        [Sample(t, lat=45.0, lon=6.0, heart_rate=heart_rate) for t in range(3)],
        start=datetime.fromisoformat(gmt).replace(tzinfo=UTC),
        sessions=((0, "running", "trail", 3723.5, 3600.0, 10450.75),),
    )


def _export(
    root: Path,
    name: str,
    at: str,
    entries: list[dict[str, Any]],
    archives: dict[str, dict[str, bytes]],
    *,
    compression: int = zipfile.ZIP_STORED,
) -> Path:
    raw = root / "raw" / "garmin" / name
    (raw / "activities").mkdir(parents=True)
    (raw / "activity_fit").mkdir()
    (raw / ACQUISITION_FILE).write_text(
        json.dumps({"retrieved_at": at}), encoding="utf-8"
    )
    (raw / "activities" / "activities.json").write_text(
        json.dumps(entries), encoding="utf-8"
    )
    for file_name, members in archives.items():
        with zipfile.ZipFile(raw / "activity_fit" / file_name, "w", compression) as zf:
            for member, data in members.items():
                zf.writestr(member, data)
    return raw


D10, D11, D12 = "2024-03-01 08:00:00", "2024-03-09 08:30:00", "2024-03-05 08:00:00"
D13, D14, D15 = "2024-03-20 08:00:00", "2024-03-25 08:00:00", "2024-06-01 08:00:00"


def two_exports(root: Path) -> Path:
    """L'ancien porte 10, 16, 11, 12, 13 et 14 (16 listée avant 11 : les retirées se
    trient) ; le récent 12, 13, 14 et 15, sa période partant au départ de 12.

    - 10 part avant la période du récent : gardée, prise à l'ancien ;
    - 11 et 16 (partie au départ même de 12, borne comprise) : couvertes par le récent,
      qui ne les porte pas : retirées de la source ;
    - 12 : entrée du récent (la distance y diffère), FIT de l'ancien, le récent n'en
      ayant pas ;
    - 13 : deux archives différentes (nom du membre, compression), un même FIT ;
    - 14 : deux FIT différents ; celui du récent est retenu ;
    - 15 : récente, sans archive.
    """
    _export(
        root,
        OLD,
        OLD_AT,
        [
            _entry(10, D10),
            _entry(16, D12),
            _entry(11, D11),
            _entry(12, D12),
            _entry(13, D13),
            _entry(14, D14),
        ],
        {
            "10.zip": {"10_ACTIVITY.fit": _fit(D10)},
            "12.zip": {"12_ACTIVITY.fit": _fit(D12)},
            "13.zip": {"13_ACTIVITY.fit": _fit(D13)},
            "14.zip": {"14_ACTIVITY.fit": _fit(D14)},
        },
    )
    _export(
        root,
        NEW,
        NEW_AT,
        [
            _entry(12, D12, distance=9999.0),
            _entry(13, D13),
            _entry(14, D14),
            _entry(15, D15),
        ],
        {
            "13.zip": {"13.fit": _fit(D13)},
            "14.zip": {"14_ACTIVITY.fit": _fit(D14, heart_rate=101)},
        },
        compression=zipfile.ZIP_DEFLATED,
    )
    return root


def _utc(gmt: str) -> datetime:
    return datetime.fromisoformat(gmt).replace(tzinfo=UTC)


def _hash(root: Path, name: str, file_name: str) -> str:
    path = root / "raw" / "garmin" / name / "activity_fit" / file_name
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_two_exports_existence_entries_and_recordings(tmp_path: Path) -> None:
    summary = ingest_export(two_exports(tmp_path))
    index = read_index(tmp_path)
    old_source, new_source = index.exports
    assert (old_source.retrieved_at, new_source.retrieved_at) == (
        datetime.fromisoformat(OLD_AT),
        datetime.fromisoformat(NEW_AT),
    )
    assert [
        (e.activity_ref, e.source, e.has_recording, e.distance_m) for e in index.entries
    ] == [
        ("10", old_source, True, 10450.75),
        ("12", new_source, True, 9999.0),
        ("13", new_source, True, 10450.75),
        ("14", new_source, True, 10450.75),
        ("15", new_source, False, 10450.75),
    ]
    report = read_report(tmp_path)
    assert report.retired == (RetiredActivity("11", NEW), RetiredActivity("16", NEW))
    assert report.index_differences == (
        FieldDifferenceCount(IndexDifference.DISTANCE, 1),
    )
    assert (report.fit_differences, report.recordings_from_other_export) == (1, 1)
    assert (report.refused_files, report.mismatches, report.view_refusals) == (
        (),
        (),
        (),
    )
    assert [
        (e.name, e.period_start, e.entries, e.refused_entries, e.archives)
        for e in report.exports
    ] == [(OLD, _utc(D10), 6, (), 4), (NEW, _utc(D12), 4, (), 2)]
    assert [f.name for f in report.read] == sorted(
        [
            f"garmin/{OLD}/acquisition.json",
            f"garmin/{OLD}/activities/activities.json",
            *(f"garmin/{OLD}/activity_fit/{n}.zip" for n in (10, 12, 13, 14)),
            f"garmin/{NEW}/acquisition.json",
            f"garmin/{NEW}/activities/activities.json",
            *(f"garmin/{NEW}/activity_fit/{n}.zip" for n in (13, 14)),
        ]
    )
    expected = {
        "10": (OLD, OLD_AT),
        "12": (OLD, OLD_AT),
        "13": (NEW, NEW_AT),
        "14": (NEW, NEW_AT),
    }
    for ref, (name, at) in expected.items():
        source = read_recording(tmp_path, ref).source
        assert source.identifier == f"{ref}.zip"
        assert source.content_hash == _hash(tmp_path, name, f"{ref}.zip")
        assert source.retrieved_at == datetime.fromisoformat(at)
    assert _hash(tmp_path, OLD, "13.zip") != _hash(tmp_path, NEW, "13.zip")
    assert (
        summary.activities,
        summary.recordings,
        summary.refused_files,
        summary.refused_entries,
        summary.entries_without_archive,
        summary.retired,
        summary.fit_differences,
        summary.recordings_from_other_export,
    ) == (5, 4, 0, 0, 1, 2, 1, 1)
    assert summary.exports == report.exports
    assert summary.index_differences == report.index_differences


def test_a_listing_in_another_order_writes_the_same_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Les mêmes exports, listés à rebours (dossiers de ``raw/`` comme fichiers de
    ``activity_fit/``), donnent les mêmes octets."""

    def written(root: Path) -> dict[Path, bytes]:
        return {
            p.relative_to(root): p.read_bytes()
            for p in (root / ACTIVITIES_DIR).rglob("*")
            if p.is_file()
        }

    first = two_exports(tmp_path / "un")
    ingest_export(first)
    second = two_exports(tmp_path / "deux")
    listing = Path.iterdir
    monkeypatch.setattr(
        Path, "iterdir", lambda self: iter(sorted(listing(self), reverse=True))
    )
    ingest_export(second)
    assert written(first) == written(second)


@pytest.mark.parametrize(
    ("where", "found"),
    [
        ("raw", "acquisition.json"),
        ("raw", "activities/"),
        ("raw/garmin", "acquisition.json"),
        ("raw/garmin", "activities/"),
    ],
)
def test_an_export_left_flat_stops_the_ingestion(
    tmp_path: Path, where: str, found: str
) -> None:
    """L'ancienne disposition, à la racine de ``raw/`` ou de ``raw/garmin/`` : son
    ``acquisition.json``, ou sinon son ``activities/``."""
    make_export(tmp_path)
    folder = tmp_path / where
    if found == "activities/":
        (folder / "activities").mkdir()
    else:
        (folder / ACQUISITION_FILE).write_text(
            json.dumps({"retrieved_at": AT}), encoding="utf-8"
        )
    with pytest.raises(IngestError) as error:
        ingest_export(tmp_path)
    assert str(error.value) == (
        f"{where}/{found} : un export Garmin se range dans son dossier, "
        "raw/garmin/<export>/ ; ranger celui-ci dans le sien."
    )
    assert not (tmp_path / ACTIVITIES_DIR).exists()


@pytest.mark.parametrize("raw", ["absent", "vide", "autre source", "fichier"])
def test_raw_without_a_garmin_export_stops_the_ingestion(
    tmp_path: Path, raw: str
) -> None:
    if raw != "absent":
        (tmp_path / "raw").mkdir()
    if raw == "autre source":
        (tmp_path / "raw" / "meteo").mkdir()
    if raw == "fichier":
        (tmp_path / "raw" / "garmin").mkdir()
        (tmp_path / "raw" / "garmin" / "desktop.ini").write_text("", encoding="utf-8")
    with pytest.raises(IngestError) as error:
        ingest_export(tmp_path)
    assert str(error.value) == (
        "raw/garmin/ ne contient aucun export : chacun se range dans "
        "raw/garmin/<export>/, avec son acquisition.json."
    )


def test_other_sources_and_files_beside_the_exports_are_ignored(
    tmp_path: Path,
) -> None:
    make_export(tmp_path)
    (tmp_path / "raw" / "garmin" / "desktop.ini").write_text("", encoding="utf-8")
    (tmp_path / "raw" / "meteo").mkdir()
    (tmp_path / "raw" / "meteo" / "a.csv").write_text("x", encoding="utf-8")
    (tmp_path / "raw" / "notes.txt").write_text("rien", encoding="utf-8")
    assert ingest_export(tmp_path).activities == 4
    assert all(
        f.name.startswith(f"garmin/{EXPORT}/") for f in read_report(tmp_path).read
    )


@pytest.mark.parametrize(
    "name",
    [
        "mon export",
        "é",
        pytest.param(
            "a:b",
            marks=pytest.mark.skipif(
                sys.platform == "win32", reason="« : » est interdit dans un nom Windows"
            ),
        ),
        "a+b",
    ],
)
def test_an_export_name_the_report_cannot_hold_stops_the_ingestion(
    tmp_path: Path, name: str
) -> None:
    make_export(tmp_path)
    make_export(tmp_path, name=name)
    with pytest.raises(IngestError) as error:
        ingest_export(tmp_path)
    assert str(error.value) == (
        f"raw/garmin/{name}/ : le nom d'un export est fait de lettres et de chiffres "
        "ASCII, de « _ », « . » ou « - »."
    )


def test_a_second_folder_without_acquisition_stops_the_ingestion(
    tmp_path: Path,
) -> None:
    make_export(tmp_path)
    make_export(tmp_path, name="garmin_b", acquisition=False)
    with pytest.raises(IngestError) as error:
        ingest_export(tmp_path)
    assert str(error.value) == (
        "raw/garmin/garmin_b/acquisition.json manque : chaque dossier de raw/garmin/ "
        "est un export, avec l'instant de son acquisition."
    )
    assert not (tmp_path / ACTIVITIES_DIR).exists()


def test_two_equal_instants_stop_the_ingestion(tmp_path: Path) -> None:
    """Le même instant écrit avec trois décalages : les deux premiers par nom sont
    nommés. Les instants se comparent, pas leur écriture ; et les exports se rangent
    par instant, pas par heure murale (celle de ``garmin_c`` vient la première)."""
    make_export(tmp_path, name="garmin_b")
    make_export(
        tmp_path, name="garmin_a", acquisition={"retrieved_at": "2024-04-01T10:34:56Z"}
    )
    make_export(
        tmp_path,
        name="garmin_c",
        acquisition={"retrieved_at": "2024-04-01T05:34:56-05:00"},
    )
    with pytest.raises(IngestError) as error:
        ingest_export(tmp_path)
    assert str(error.value) == (
        "raw/garmin/garmin_a/ et raw/garmin/garmin_b/ : même instant d'acquisition ; "
        "l'ordre des exports serait indéterminé."
    )


@pytest.mark.parametrize(("gmt", "accepted"), [("10:34:56", True), ("10:34:57", False)])
def test_an_entry_after_the_acquisition_instant_refuses_the_export(
    tmp_path: Path, gmt: str, accepted: bool
) -> None:
    """Une entrée partie à l'instant d'acquisition passe ; une seconde après, non."""
    make_export(tmp_path, items=[item(activityId=1), _entry(2, f"2024-04-01 {gmt}")])
    if accepted:
        assert ingest_export(tmp_path).activities == 2
        return
    with pytest.raises(IngestError) as error:
        ingest_export(tmp_path)
    assert str(error.value) == (
        f"raw/garmin/{EXPORT}/ : une activité de l'index part après l'instant "
        "d'acquisition de l'export ; acquisition.json est faux."
    )


def test_an_entry_refused_by_the_decisive_export_is_retired(tmp_path: Path) -> None:
    """Le récent porte 2, mais son entrée est refusée (sans type) : l'ancienne n'est
    pas reprise ; l'activité est retirée, et le refus est dans l'``ExportReport``."""
    _export(tmp_path, OLD, OLD_AT, [_entry(1, D10), _entry(2, D11)], {})
    _export(
        tmp_path,
        NEW,
        NEW_AT,
        [_entry(1, D10), _entry(2, D11, activityType=None)],
        {},
    )
    summary = ingest_export(tmp_path)
    assert [e.activity_ref for e in read_index(tmp_path).entries] == ["1"]
    report = read_report(tmp_path)
    assert report.retired == (RetiredActivity("2", NEW),)
    assert [len(e.refused_entries) for e in report.exports] == [0, 1]
    assert (summary.retired, summary.refused_entries) == (1, 1)


def test_an_archive_of_another_export_is_refused_by_its_own_index(
    tmp_path: Path,
) -> None:
    """Une archive se juge sur l'index de son export : 12 du récent, que seul l'ancien
    porte (elle part avant la période du récent), est ``NOT_IN_INDEX`` ;
    l'enregistrement vient de l'ancien."""
    _export(tmp_path, OLD, OLD_AT, [_entry(12, D12)], {"12.zip": {"12.fit": _fit(D12)}})
    _export(tmp_path, NEW, NEW_AT, [_entry(15, D15)], {"12.zip": {"12.fit": _fit(D12)}})
    summary = ingest_export(tmp_path)
    refused = {f.name: f.reason for f in read_report(tmp_path).refused_files}
    assert refused == {f"garmin/{NEW}/activity_fit/12.zip": RefusalReason.NOT_IN_INDEX}
    assert read_recording(tmp_path, "12").source.retrieved_at == datetime.fromisoformat(
        OLD_AT
    )
    assert (summary.recordings, summary.recordings_from_other_export) == (1, 0)


def test_a_decisive_archive_that_is_not_one_fit_falls_back(tmp_path: Path) -> None:
    """L'archive du récent n'est pas un FIT unique : l'enregistrement vient de
    l'ancien, le refus est inscrit."""
    _export(tmp_path, OLD, OLD_AT, [_entry(12, D12)], {"12.zip": {"12.fit": _fit(D12)}})
    _export(
        tmp_path,
        NEW,
        NEW_AT,
        [_entry(12, D12)],
        {"12.zip": {"a.fit": _fit(D12), "b.fit": _fit(D12)}},
    )
    summary = ingest_export(tmp_path)
    assert (summary.recordings, summary.recordings_from_other_export) == (1, 1)
    assert read_recording(tmp_path, "12").source.retrieved_at == datetime.fromisoformat(
        OLD_AT
    )
    refused = {f.name: f.reason for f in read_report(tmp_path).refused_files}
    assert refused == {f"garmin/{NEW}/activity_fit/12.zip": RefusalReason.NOT_ONE_FIT}
    assert summary.fit_differences == 0


@pytest.mark.parametrize("old_reads", [True, False])
def test_an_unreadable_decisive_fit_falls_back(tmp_path: Path, old_reads: bool) -> None:
    """Le FIT du récent a un CRC faux : celui de l'ancien, s'il se lit ; sinon rien.
    Chaque refus est inscrit sous le nom de son archive ; seuls les FIT essayés sont
    lus."""
    bad = activity_fit([Sample(0, heart_rate=90)], corrupt_crc=True)
    _export(
        tmp_path,
        OLD,
        OLD_AT,
        [_entry(12, D12)],
        {"12.zip": {"12.fit": _fit(D12) if old_reads else bad}},
    )
    _export(tmp_path, NEW, NEW_AT, [_entry(12, D12)], {"12.zip": {"12.fit": bad}})
    summary = ingest_export(tmp_path)
    refused = {f.name: f.reason for f in read_report(tmp_path).refused_files}
    expected = {f"garmin/{NEW}/activity_fit/12.zip": RefusalReason.UNREADABLE_FIT}
    if not old_reads:
        expected[f"garmin/{OLD}/activity_fit/12.zip"] = RefusalReason.UNREADABLE_FIT
    assert refused == expected
    assert summary.recordings == int(old_reads)
    assert summary.recordings_from_other_export == int(old_reads)
    assert read_index(tmp_path).entries[0].has_recording is old_reads


def test_a_readable_decisive_fit_is_the_only_one_decoded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le FIT du récent se lit : celui de l'ancien, différent, n'est pas décodé."""
    _export(tmp_path, OLD, OLD_AT, [_entry(12, D12)], {"12.zip": {"12.fit": _fit(D12)}})
    _export(
        tmp_path,
        NEW,
        NEW_AT,
        [_entry(12, D12)],
        {"12.zip": {"12.fit": _fit(D12, heart_rate=101)}},
    )
    decoded: list[datetime] = []
    from mountain_perf.ingest.fit import read_fit

    def spy(member: bytes, **kwargs: Any) -> Any:
        decoded.append(kwargs["source"].retrieved_at)
        return read_fit(member, **kwargs)

    monkeypatch.setattr("mountain_perf.ingest.export.read_fit", spy)
    summary = ingest_export(tmp_path)
    assert decoded == [datetime.fromisoformat(NEW_AT)]
    assert (summary.fit_differences, summary.recordings_from_other_export) == (1, 0)


def test_elevation_corrected_false_then_true(tmp_path: Path) -> None:
    """La variante de C5 : l'entrée du récent, un écart compté pour ce champ."""
    _export(tmp_path, OLD, OLD_AT, [_entry(1, D10, elevationCorrected=False)], {})
    _export(tmp_path, NEW, NEW_AT, [_entry(1, D10, elevationCorrected=True)], {})
    summary = ingest_export(tmp_path)
    assert read_index(tmp_path).entries[0].elevation_corrected is True
    assert summary.index_differences == (
        FieldDifferenceCount(IndexDifference.ELEVATION_CORRECTED, 1),
    )


@pytest.mark.parametrize(
    ("load", "expected"),
    [
        (87.25, 87.25),
        (0, 0.0),
        ("absent", None),
        (None, None),
        ("87", None),
        (-0.5, None),
    ],
)
def test_the_training_load_reaches_the_index(
    tmp_path: Path, load: Any, expected: float | None
) -> None:
    """Zéro est une charge ; absente ou ``null`` : absente, sans être nommée ; non
    numérique ou négative : absente, nommée dans ``omitted_fields``."""
    entry = item(activityId=1)
    if load == "absent":
        del entry["activityTrainingLoad"]
    else:
        entry["activityTrainingLoad"] = load
    make_export(tmp_path, items=[entry])
    ingest_export(tmp_path)
    (e,) = read_index(tmp_path).entries
    assert e.training_load == expected
    named = expected is None and load not in ("absent", None)
    assert (IndexField.TRAINING_LOAD in e.omitted_fields) is named


def test_the_is_keys_change_nothing(tmp_path: Path) -> None:
    """Le récent ajoute des clés ``is…`` (``isElevationCorrected`` à côté
    d'``elevationCorrected``, ``isManualActivity``) : mêmes entrées, aucun écart."""
    _export(tmp_path, OLD, OLD_AT, [_entry(1, D10, elevationCorrected=True)], {})
    _export(
        tmp_path,
        NEW,
        NEW_AT,
        [
            _entry(
                1,
                D10,
                elevationCorrected=True,
                isElevationCorrected=False,
                isManualActivity=True,
            )
        ],
        {},
    )
    summary = ingest_export(tmp_path)
    assert summary.index_differences == ()
    (e,) = read_index(tmp_path).entries
    assert e.elevation_corrected is True


def test_a_start_with_another_offset_is_a_difference(tmp_path: Path) -> None:
    """Le même instant de départ, écrit à UTC+1 puis à UTC+2 : le départ diffère."""
    _export(tmp_path, OLD, OLD_AT, [_entry(1, D10)], {})
    _export(
        tmp_path,
        NEW,
        NEW_AT,
        [_entry(1, D10, startTimeLocal="2024-03-01 10:00:00")],
        {},
    )
    summary = ingest_export(tmp_path)
    assert summary.index_differences == (
        FieldDifferenceCount(IndexDifference.START_TIME, 1),
    )


def test_cli_ingest_with_two_exports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    two_exports(tmp_path)
    monkeypatch.setenv("MPA_DATA_DIR", str(tmp_path))
    assert main(["ingest"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "Exports : 2",
        f"  {OLD} : acquis le 2024-04-01T10:34:56+00:00, 6 entrées gardées, "
        "0 refusées, 4 archives",
        f"  {NEW} : acquis le 2024-07-01T10:00:00+00:00, 4 entrées gardées, "
        "0 refusées, 2 archives",
        "Activités dans l'index : 5",
        "Enregistrements : 4",
        "Fichiers refusés : 0",
        "Entrées de l'index refusées : 0",
        "Entrées sans archive : 1",
        "Enregistrements en désaccord avec l'index : 0",
        "Activités sans vue Activity : 0",
        "Activités retirées de la source : 2",
        "Champs de l'index qui diffèrent d'un export à l'autre : 1",
        "  distance_m : 1 activité(s)",
        "Activités aux FIT différents d'un export à l'autre : 1",
        "Enregistrements tirés d'un autre export que leur entrée : 1",
    ]


# L'ordre écrit des contrôles (balayage d'AN2-0) : chaque paire voisine, par une entrée
# qui viole les deux règles ; le premier contrôle de la docstring parle.


def _message(root: Path) -> str:
    with pytest.raises(IngestError) as error:
        ingest_export(root)
    return str(error.value)


def test_export_dirs_checks_raw_before_raw_garmin(tmp_path: Path) -> None:
    """Un export à plat dans ``raw/`` et un autre dans ``raw/garmin/`` : ``raw/``
    parle."""
    make_export(tmp_path)
    for folder in (tmp_path / "raw", tmp_path / "raw" / "garmin"):
        (folder / ACQUISITION_FILE).write_text(
            json.dumps({"retrieved_at": AT}), encoding="utf-8"
        )
    assert _message(tmp_path).startswith("raw/acquisition.json : ")


def test_a_flat_export_names_its_acquisition_before_its_activities(
    tmp_path: Path,
) -> None:
    make_export(tmp_path)
    (tmp_path / "raw" / ACQUISITION_FILE).write_text(
        json.dumps({"retrieved_at": AT}), encoding="utf-8"
    )
    (tmp_path / "raw" / "activities").mkdir()
    assert _message(tmp_path).startswith("raw/acquisition.json : ")


def test_a_flat_export_is_named_before_an_empty_raw_garmin(tmp_path: Path) -> None:
    """``raw/garmin/`` ne porte qu'un ``acquisition.json``, aucun dossier : l'export à
    plat parle, pas l'absence d'export."""
    (tmp_path / "raw" / "garmin").mkdir(parents=True)
    (tmp_path / "raw" / "garmin" / ACQUISITION_FILE).write_text(
        json.dumps({"retrieved_at": AT}), encoding="utf-8"
    )
    assert _message(tmp_path).startswith("raw/garmin/acquisition.json : ")


def test_a_flat_export_is_named_before_a_bad_export_name(tmp_path: Path) -> None:
    make_export(tmp_path, name="mon export")
    (tmp_path / "raw" / "garmin" / "activities").mkdir()
    assert _message(tmp_path).startswith("raw/garmin/activities/ : ")


def test_load_reads_the_acquisition_before_the_index(tmp_path: Path) -> None:
    """Ni ``acquisition.json`` ni index : l'instant parle."""
    raw = make_export(tmp_path, acquisition=False) / "raw" / "garmin" / EXPORT
    (raw / "activities" / "activities.json").unlink()
    assert _message(tmp_path).endswith(
        "acquisition.json manque : chaque dossier de raw/garmin/ est un export, avec "
        "l'instant de son acquisition."
    )


@pytest.mark.skipif(
    sys.platform == "win32", reason="« : » est interdit dans un nom Windows"
)
def test_load_reads_the_index_before_the_archive_names(tmp_path: Path) -> None:
    raw = make_export(tmp_path) / "raw" / "garmin" / EXPORT
    (raw / "activities" / "activities.json").write_bytes(b"\xff")
    (raw / "activity_fit" / "a:b.zip").write_bytes(b"x")
    assert _message(tmp_path) == (
        f"raw/garmin/{EXPORT}/activities/activities.json : JSON en UTF-8 attendu."
    )


@pytest.mark.skipif(
    sys.platform == "win32", reason="« : » est interdit dans un nom Windows"
)
def test_load_checks_the_entries_before_the_archive_names(tmp_path: Path) -> None:
    """Une entrée partie après l'instant d'acquisition et une archive au nom illisible :
    l'entrée parle."""
    raw = (
        make_export(tmp_path, items=[_entry(2, "2024-04-01 10:34:57")])
        / "raw"
        / "garmin"
        / EXPORT
    )
    (raw / "activity_fit" / "a:b.zip").write_bytes(b"x")
    assert "part après l'instant d'acquisition" in _message(tmp_path)


def test_every_export_is_loaded_before_the_instants_are_compared(
    tmp_path: Path,
) -> None:
    """Deux instants égaux, et un export dont une entrée part après le sien : l'export
    fautif parle, avant la comparaison des instants."""
    make_export(tmp_path, name="garmin_a")
    make_export(tmp_path, name="garmin_b", items=[_entry(2, "2024-04-01 10:34:57")])
    assert _message(tmp_path).startswith("raw/garmin/garmin_b/ : une activité")


def test_exports_are_loaded_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deux exports fautifs, listés à rebours : le premier par nom parle."""
    make_export(tmp_path, name="garmin_b", acquisition={"retrieved_at": "x"})
    make_export(tmp_path, name="garmin_a", acquisition={"retrieved_at": "y"})
    listing = Path.iterdir
    monkeypatch.setattr(
        Path, "iterdir", lambda self: iter(sorted(listing(self), reverse=True))
    )
    assert _message(tmp_path).startswith("raw/garmin/garmin_a/acquisition.json : ")


# Les lacunes du balayage mutmut d'AN2-0.

MID, MID_AT = "c_milieu", "2024-05-15T12:00:00+02:00"


def test_an_export_without_any_entry_covers_nothing(tmp_path: Path) -> None:
    """Un export dont l'index est vide n'a pas de période : il ne couvre aucun départ,
    ne retire rien, et son rapport n'a pas de début de période ; il reste parmi les
    exports de l'index."""
    _export(tmp_path, OLD, OLD_AT, [_entry(1, D10)], {})
    _export(tmp_path, NEW, NEW_AT, [], {})
    summary = ingest_export(tmp_path)
    index = read_index(tmp_path)
    assert [e.activity_ref for e in index.entries] == ["1"]
    assert [s.retrieved_at for s in index.exports] == [
        datetime.fromisoformat(OLD_AT),
        datetime.fromisoformat(NEW_AT),
    ]
    report = read_report(tmp_path)
    assert [(e.name, e.period_start, e.entries) for e in report.exports] == [
        (OLD, _utc(D10), 1),
        (NEW, None, 0),
    ]
    assert (summary.retired, report.retired) == (0, ())


def test_the_fallback_takes_the_most_recent_readable_older_fit(tmp_path: Path) -> None:
    """Trois exports portent 12 ; le FIT du décisif ne se lit pas : celui du plus
    récent des deux autres (le milieu), pas celui du plus ancien."""
    bad = activity_fit([Sample(0, heart_rate=90)], corrupt_crc=True)
    _export(tmp_path, OLD, OLD_AT, [_entry(12, D12)], {"12.zip": {"12.fit": _fit(D12)}})
    _export(
        tmp_path,
        MID,
        MID_AT,
        [_entry(12, D12)],
        {"12.zip": {"12.fit": _fit(D12, heart_rate=102)}},
    )
    _export(tmp_path, NEW, NEW_AT, [_entry(12, D12)], {"12.zip": {"12.fit": bad}})
    summary = ingest_export(tmp_path)
    source = read_recording(tmp_path, "12").source
    assert source.retrieved_at == datetime.fromisoformat(MID_AT)
    assert source.content_hash == _hash(tmp_path, MID, "12.zip")
    assert (summary.recordings_from_other_export, summary.fit_differences) == (1, 1)


def test_index_differences_are_counted_per_activity_and_sorted_by_field(
    tmp_path: Path,
) -> None:
    """Deux activités dont la distance diffère, l'une aussi par le décalage de son
    départ : deux pour ``distance_m``, une pour ``start_time``, dans l'ordre des noms
    de champ (l'ordre de l'énumération met ``start_time`` d'abord)."""
    _export(tmp_path, OLD, OLD_AT, [_entry(1, D10), _entry(2, D11)], {})
    _export(
        tmp_path,
        NEW,
        NEW_AT,
        [
            _entry(1, D10, distance=1.0, startTimeLocal="2024-03-01 10:00:00"),
            _entry(2, D11, distance=2.0),
        ],
        {},
    )
    summary = ingest_export(tmp_path)
    assert summary.index_differences == (
        FieldDifferenceCount(IndexDifference.DISTANCE, 2),
        FieldDifferenceCount(IndexDifference.START_TIME, 1),
    )
    assert read_report(tmp_path).index_differences == summary.index_differences


# La relecture du paquet d'AN2-0 : des promesses des docstrings qu'aucun test ne
# tenait.


def test_the_mismatch_is_measured_against_the_decisive_entry(tmp_path: Path) -> None:
    """Le FIT de 12 vient de l'ancien export, son entrée du récent, qui la fait partir
    10 s plus tard : le désaccord se mesure contre l'entrée décisive (-10 s), pas contre
    celle de l'ancien, où le FIT et l'entrée s'accordent."""
    _export(tmp_path, OLD, OLD_AT, [_entry(12, D12)], {"12.zip": {"12.fit": _fit(D12)}})
    _export(tmp_path, NEW, NEW_AT, [_entry(12, "2024-03-05 08:00:10")], {})
    summary = ingest_export(tmp_path)
    assert summary.recordings_from_other_export == 1
    assert [
        (m.activity_ref, m.start_offset_s) for m in read_report(tmp_path).mismatches
    ] == [("12", -10.0)]


def test_the_start_is_read_in_the_most_recent_export_that_carries_it(
    tmp_path: Path,
) -> None:
    """20 part le 10 dans l'ancien, le 12 dans le récent, dont la période commence au
    12 ; le milieu, qui ne la porte pas, couvre le 10. Lu dans le récent, son départ est
    couvert par le récent : 20 est gardée ; lu dans l'ancien, le milieu la
    retirerait."""
    _export(tmp_path, OLD, OLD_AT, [_entry(20, "2024-03-10 08:00:00")], {})
    _export(tmp_path, MID, MID_AT, [_entry(21, "2024-03-05 08:00:00")], {})
    _export(tmp_path, NEW, NEW_AT, [_entry(20, "2024-03-12 08:00:00")], {})
    summary = ingest_export(tmp_path)
    assert [(e.activity_ref, e.start_time) for e in read_index(tmp_path).entries] == [
        ("21", _utc("2024-03-05 08:00:00")),
        ("20", _utc("2024-03-12 08:00:00")),
    ]
    assert (summary.retired, read_report(tmp_path).retired) == (0, ())


@pytest.mark.parametrize("differs", [(OLD,), (MID,), (OLD, MID)])
def test_an_index_difference_with_any_other_export_counts(
    tmp_path: Path, differs: tuple[str, ...]
) -> None:
    """Trois exports portent 1 ; l'entrée de l'ancien, celle du milieu, ou les deux,
    ont une autre distance : l'écart avec l'entrée décisive (celle du récent) compte,
    quel que soit l'export qui diffère, et une seule fois pour l'activité."""
    for name, at in ((OLD, OLD_AT), (MID, MID_AT), (NEW, NEW_AT)):
        changes = {"distance": 1.0} if name in differs else {}
        _export(tmp_path, name, at, [_entry(1, D10, **changes)], {})
    summary = ingest_export(tmp_path)
    assert summary.index_differences == (
        FieldDifferenceCount(IndexDifference.DISTANCE, 1),
    )


def test_an_entry_refused_in_the_older_export_is_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """L'ancien export a une entrée gardée et une refusée (sans type), le récent une
    gardée : chaque export compte ses seules entrées gardées, le résumé compte les refus
    de tous les exports, et, dans la sortie de la commande, la ligne de l'ancien dit son
    refus, celle du récent aucun."""
    _export(
        tmp_path, OLD, OLD_AT, [_entry(1, D10), _entry(2, D11, activityType=None)], {}
    )
    _export(tmp_path, NEW, NEW_AT, [_entry(1, D10)], {})
    summary = ingest_export(tmp_path)
    assert [(e.name, e.entries, len(e.refused_entries)) for e in summary.exports] == [
        (OLD, 1, 1),
        (NEW, 1, 0),
    ]
    assert summary.refused_entries == 1
    monkeypatch.setenv("MPA_DATA_DIR", str(tmp_path))
    assert main(["ingest"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[1] == (
        f"  {OLD} : acquis le 2024-04-01T10:34:56+00:00, 1 entrées gardées, "
        "1 refusées, 0 archives"
    )
    assert lines[2] == (
        f"  {NEW} : acquis le 2024-07-01T10:00:00+00:00, 1 entrées gardées, "
        "0 refusées, 0 archives"
    )
    assert "Entrées de l'index refusées : 1" in lines


# La relecture C de la PR AN2-0 et celle de son annexe : des règles et des comptes
# qu'aucun test ne tenait.


def test_coverage_compares_instants_not_wall_clock_times(tmp_path: Path) -> None:
    """La période du récent part de 31, à 06:30 UTC écrit à +02:00 (08:30) ; 30, que
    seul l'ancien porte, part à 06:45 UTC écrit à +01:00 (07:45) : couverte à
    l'instant, elle est retirée."""
    _export(tmp_path, OLD, OLD_AT, [_entry(30, "2024-03-05 06:45:00")], {})
    _export(
        tmp_path,
        NEW,
        NEW_AT,
        [_entry(31, "2024-03-05 06:30:00", startTimeLocal="2024-03-05 08:30:00")],
        {},
    )
    ingest_export(tmp_path)
    assert read_report(tmp_path).retired == (RetiredActivity("30", NEW),)
    assert [e.activity_ref for e in read_index(tmp_path).entries] == ["31"]


_ONE_FIELD_DIFFERS: dict[IndexDifference, dict[str, Any]] = {
    IndexDifference.SOURCE_ACTIVITY_TYPE: {"activityType": {"typeKey": "running"}},
    IndexDifference.START_TIME: {"startTimeLocal": "2024-03-01 10:00:00"},
    IndexDifference.ELAPSED_DURATION: {"elapsedDuration": 1000.0},
    IndexDifference.MOVING_DURATION: {"movingDuration": 900.0},
    IndexDifference.DISTANCE: {"distance": 1.0},
    IndexDifference.ASCENT: {"elevationGain": 1.0},
    IndexDifference.DESCENT: {"elevationLoss": 1.0},
    IndexDifference.ELEVATION_CORRECTED: {"elevationCorrected": True},
    IndexDifference.AVERAGE_HR: {"averageHR": 100.0},
    IndexDifference.MAX_HR: {"maxHR": 180.0},
    IndexDifference.TRAINING_LOAD: {"activityTrainingLoad": 12.5},
}


def test_every_compared_field_has_its_case() -> None:
    assert set(_ONE_FIELD_DIFFERS) == set(IndexDifference)


@pytest.mark.parametrize("field", list(_ONE_FIELD_DIFFERS))
def test_each_index_field_is_compared_between_exports(
    tmp_path: Path, field: IndexDifference
) -> None:
    """Un seul champ diffère entre l'entrée de l'ancien et celle du récent : un écart à
    son nom, et à aucun autre (la charge comprise)."""
    _export(tmp_path, OLD, OLD_AT, [_entry(1, D10)], {})
    _export(tmp_path, NEW, NEW_AT, [_entry(1, D10, **_ONE_FIELD_DIFFERS[field])], {})
    summary = ingest_export(tmp_path)
    assert summary.index_differences == (FieldDifferenceCount(field, 1),)


def test_a_retired_activity_counts_no_index_difference(tmp_path: Path) -> None:
    """30 est portée par l'ancien et par le milieu, avec deux distances ; le récent,
    dont la période couvre son départ, ne la porte pas : elle est retirée, et ses
    entrées ne comptent aucun écart."""
    _export(tmp_path, OLD, OLD_AT, [_entry(30, D11)], {})
    _export(tmp_path, MID, MID_AT, [_entry(30, D11, distance=1.0)], {})
    _export(tmp_path, NEW, NEW_AT, [_entry(31, D10)], {})
    summary = ingest_export(tmp_path)
    assert read_report(tmp_path).retired == (RetiredActivity("30", NEW),)
    assert summary.index_differences == ()


def test_different_fits_count_without_a_decisive_archive(tmp_path: Path) -> None:
    """Le récent, décisif, porte 12 sans archive ; l'ancien et le milieu en ont deux FIT
    différents : un FIT différent est compté, et l'enregistrement vient du milieu."""
    _export(tmp_path, OLD, OLD_AT, [_entry(12, D12)], {"12.zip": {"12.fit": _fit(D12)}})
    _export(
        tmp_path,
        MID,
        MID_AT,
        [_entry(12, D12)],
        {"12.zip": {"12.fit": _fit(D12, heart_rate=102)}},
    )
    _export(tmp_path, NEW, NEW_AT, [_entry(12, D12)], {})
    summary = ingest_export(tmp_path)
    assert (summary.fit_differences, summary.recordings_from_other_export) == (1, 1)
    source = read_recording(tmp_path, "12").source
    assert source.retrieved_at == datetime.fromisoformat(MID_AT)


def test_entries_without_archive_count_every_file_name(tmp_path: Path) -> None:
    """1 n'a, dans le récent, que deux fichiers au même nom sans extension (refusés
    ``DUPLICATE_ARCHIVE``) ; 2 n'a qu'une archive, dans l'ancien, qui ne la porte pas
    (``NOT_IN_INDEX``) ; 3 n'a aucun fichier : seule 3 est « sans archive »."""
    _export(tmp_path, OLD, OLD_AT, [_entry(3, D10)], {"2.zip": {"2.fit": _fit(D11)}})
    _export(
        tmp_path,
        NEW,
        NEW_AT,
        [_entry(1, D12), _entry(2, D11)],
        {"1.zip": {"1.fit": _fit(D12)}, "1.bak": {"1.fit": _fit(D12)}},
    )
    summary = ingest_export(tmp_path)
    assert [e.activity_ref for e in read_index(tmp_path).entries] == ["3", "1", "2"]
    assert (summary.recordings, summary.entries_without_archive) == (0, 1)


def test_a_file_named_activities_is_not_a_flat_export(tmp_path: Path) -> None:
    """Un fichier, pas un dossier, nommé ``activities``, dans ``raw/`` et dans
    ``raw/garmin/`` : ignoré, comme tout fichier posé à côté des exports."""
    make_export(tmp_path)
    (tmp_path / "raw" / "activities").write_text("", encoding="utf-8")
    (tmp_path / "raw" / "garmin" / "activities").write_text("", encoding="utf-8")
    assert ingest_export(tmp_path).activities == 4
