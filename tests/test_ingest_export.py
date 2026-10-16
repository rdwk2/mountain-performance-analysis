"""L'ingestion d'un export synthétique, de bout en bout (``ingest/export.py``, ``mperf
ingest``)."""

from __future__ import annotations

import io
import json
import sys
import zipfile
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
    RecordingMismatch,
    RefusalReason,
    ViewRefusal,
    ViewRefusalCount,
)
from test_ingest_index import item

AT = "2024-04-01T12:34:56+02:00"


def _zip(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)


def make_export(
    root: Path, *, acquisition: Any = None, items: list[Any] | None = None
) -> Path:
    raw = root / "raw"
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
    assert index.source.kind == "garmin_activities"
    assert index.source.identifier == "activities.json"
    assert index.source.retrieved_at.isoformat() == "2024-04-01T10:34:56+00:00"
    rec = read_recording(tmp_path, "1")
    assert rec.source.kind == "garmin_fit"
    assert rec.source.identifier == "1.zip"
    assert (
        rec.source.content_hash
        == __import__("hashlib")
        .sha256((tmp_path / "raw/activity_fit/1.zip").read_bytes())
        .hexdigest()
    )
    report = read_report(tmp_path)
    assert [f.name for f in report.read] == [
        "acquisition.json",
        "activities/activities.json",
        "activity_fit/1.zip",
        "activity_fit/2.zip",
        "activity_fit/3.zip",
        "activity_fit/9.zip",
    ]
    assert [(f.name, f.reason) for f in report.refused_files] == [
        ("activity_fit/2.zip", RefusalReason.UNREADABLE_FIT),
        ("activity_fit/3.zip", RefusalReason.NOT_ONE_FIT),
        ("activity_fit/9.zip", RefusalReason.NOT_IN_INDEX),
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
        "Activités dans l'index : 4",
        "Enregistrements : 1",
        "Fichiers refusés : 3",
        "Entrées de l'index refusées : 0",
        "Entrées sans archive : 1",
        "Enregistrements en désaccord avec l'index : 1",
        "Activités sans vue Activity : 1",
        "  no_sport : golf (1)",
    ]


def test_cli_ingest_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_export(tmp_path, acquisition=False)
    monkeypatch.setenv("MPA_DATA_DIR", str(tmp_path))
    assert main(["ingest"]) == 1
    assert capsys.readouterr().err.startswith("Erreur : raw/acquisition.json manque")


# --- compléments du balayage par mutation ----------------------------------------


def test_archive_cases(tmp_path: Path) -> None:
    make_export(tmp_path)
    fit_dir = tmp_path / "raw" / "activity_fit"
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
    assert refused["activity_fit/0.zip"] is RefusalReason.NOT_IN_INDEX
    assert refused["activity_fit/4.zip"] is RefusalReason.NOT_ONE_FIT
    assert refused["activity_fit/5.zip"] is RefusalReason.NOT_IN_INDEX
    assert summary.recordings == 1
    assert "activity_fit/0-dossier" not in {f.name for f in read_report(tmp_path).read}


def test_not_a_zip_is_refused(tmp_path: Path) -> None:
    make_export(tmp_path)
    (tmp_path / "raw" / "activity_fit" / "4.zip").write_bytes(b"pas une archive")
    ingest_export(tmp_path)
    refused = {f.name: f.reason for f in read_report(tmp_path).refused_files}
    assert refused["activity_fit/4.zip"] is RefusalReason.NOT_ONE_FIT


def test_export_without_fit_folder(tmp_path: Path) -> None:
    make_export(tmp_path)
    for path in (tmp_path / "raw" / "activity_fit").iterdir():
        path.unlink()
    (tmp_path / "raw" / "activity_fit").rmdir()
    assert ingest_export(tmp_path) == IngestionSummary(
        4, 0, 0, 0, 4, 0, (ViewRefusalCount(ViewRefusal.NO_SPORT, "golf", 1),)
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("absent", "raw/activities/activities.json manque."),
        ("objet", "activities.json : liste d'activités attendue."),
        ("acquisition", "raw/acquisition.json : JSON en UTF-8 attendu."),
        (
            "sans",
            "raw/acquisition.json manque : l'instant d'acquisition de l'export est "
            "requis.",
        ),
        (
            "nombre",
            "raw/acquisition.json : retrieved_at doit être un instant ISO 8601 "
            "avec fuseau.",
        ),
        ("cle", "raw/acquisition.json : objet {retrieved_at} attendu."),
    ],
)
def test_export_errors_have_exact_messages(
    tmp_path: Path, change: str, message: str
) -> None:
    make_export(tmp_path)
    raw = tmp_path / "raw"
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
    path = tmp_path / "raw" / ACQUISITION_FILE
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"retrieved_at": AT}).encode())
    assert read_acquisition(tmp_path / "raw").isoformat() == AT
    path.write_bytes(json.dumps({"retrieved_at": AT}).encode("utf-16"))
    with pytest.raises(IngestError) as error:
        read_acquisition(tmp_path / "raw")
    assert str(error.value) == "raw/acquisition.json : JSON en UTF-8 attendu."


def _fits_for(root: Path, refs: list[int]) -> None:
    """Remplace les archives par un FIT lisible (départ ``START``, 60 s) par
    identifiant."""
    fit_dir = root / "raw" / "activity_fit"
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
    assert capsys.readouterr().out.splitlines()[-3:] == [
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
    fit_dir = tmp_path / "raw" / "activity_fit"
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
    fit_dir = tmp_path / "raw" / "activity_fit"
    (fit_dir / "1.bak").write_bytes((fit_dir / "1.zip").read_bytes())
    summary = ingest_export(tmp_path)
    assert summary.recordings == 0
    refused = {f.name: f.reason for f in read_report(tmp_path).refused_files}
    assert refused["activity_fit/1.bak"] is RefusalReason.DUPLICATE_ARCHIVE
    assert refused["activity_fit/1.zip"] is RefusalReason.DUPLICATE_ARCHIVE
    assert not read_index(tmp_path).entries[0].has_recording


def test_a_duplicate_archive_is_refused_before_the_index_is_checked(
    tmp_path: Path,
) -> None:
    """``9`` n'est pas dans l'index : ses deux fichiers sont des doublons d'abord."""
    make_export(tmp_path)
    fit_dir = tmp_path / "raw" / "activity_fit"
    for name in ("9.zip", "9.bak"):
        (fit_dir / name).write_bytes((fit_dir / "1.zip").read_bytes())
    ingest_export(tmp_path)
    refused = {f.name: f.reason for f in read_report(tmp_path).refused_files}
    assert refused["activity_fit/9.bak"] is RefusalReason.DUPLICATE_ARCHIVE
    assert refused["activity_fit/9.zip"] is RefusalReason.DUPLICATE_ARCHIVE


@pytest.mark.skipif(
    sys.platform == "win32", reason="« : » et « \\ » sont interdits dans un nom Windows"
)
@pytest.mark.parametrize("name", ["copie 12:00.zip", "a\\b.zip"])
def test_a_name_the_report_cannot_hold_stops_the_ingestion(
    tmp_path: Path, name: str
) -> None:
    make_export(tmp_path)
    (tmp_path / "raw" / "activity_fit" / name).write_bytes(b"x")
    with pytest.raises(IngestError) as error:
        ingest_export(tmp_path)
    assert str(error.value) == (
        f"raw/activity_fit/{name} : nom de fichier que le rapport ne peut pas porter "
        "(« : » ou « \\ »)."
    )
    assert not (tmp_path / "interim").exists()


def _stored_zip(member: str, data: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr(member, data)
    return buffer.getvalue()


@pytest.mark.parametrize("damage", ["crc", "compression"])
def test_an_unreadable_member_is_not_one_fit(tmp_path: Path, damage: str) -> None:
    """Un membre illisible (CRC faux, méthode de compression inconnue) : l'archive est
    refusée ``NOT_ONE_FIT``, et l'ingestion continue."""
    make_export(tmp_path)
    fit = activity_fit([Sample(t, heart_rate=100) for t in range(3)])
    archive = bytearray(_stored_zip("1_ACTIVITY.fit", fit))
    if damage == "crc":
        start = 30 + len("1_ACTIVITY.fit")
        archive[start] ^= 0xFF
    else:
        for header in (b"PK\x03\x04", b"PK\x01\x02"):
            at = archive.index(header)
            offset = 8 if header == b"PK\x03\x04" else 10
            archive[at + offset : at + offset + 2] = (99).to_bytes(2, "little")
    (tmp_path / "raw" / "activity_fit" / "1.zip").write_bytes(bytes(archive))
    summary = ingest_export(tmp_path)
    assert summary.recordings == 0
    refused = {f.name: f.reason for f in read_report(tmp_path).refused_files}
    assert refused["activity_fit/1.zip"] is RefusalReason.NOT_ONE_FIT
