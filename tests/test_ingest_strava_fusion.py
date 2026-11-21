"""La fusion des sources Garmin et Strava dans ``ingest_export`` (AN1-3, § 6.4 du
brief) : les mondes ``W_F``, ``W_F'``, ``W_A``, ``W_S``, ``W_L``, ``W_P``, les arrêts,
un FIT Garmin malformé, un FIT Strava lu par tolérance. Valeurs inventées, calculées à
la main dans le brief (règle 1)."""

from __future__ import annotations

import gzip
import json
import zipfile
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fitdecode")

from fixtures.fit_activity import Sample, activity_fit, fit_time
from fixtures.strava_archive import write_strava_export
from mountain_perf.cli import main
from mountain_perf.config import data_dir
from mountain_perf.ingest.export import IngestError, ingest_export
from mountain_perf.ingest.interim import (
    ACTIVITIES_DIR,
    read_days_report,
    read_index,
    read_report,
    read_sources,
)
from mountain_perf.schemas import (
    ExportReport,
    RefusalReason,
    RefusedEntry,
    RefusedFile,
    RetiredActivity,
    SourcesReport,
    ToleratedFile,
)
from test_ingest_index import item

GARMIN, SUUNTO, COROS = 1, 23, 294
PRODUCT = 4315
G1_AT = "2026-10-01T12:00:00+00:00"
S1_AT = "2026-11-20T09:45:00+00:00"
PARIS = "Europe/Paris"
_ZIP_DATE = (2001, 1, 1, 0, 0, 0)


def _utc(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0
) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


def _samples(altitude: bool = True) -> list[Sample]:
    return [
        Sample(
            t,
            lat=45.0,
            lon=6.0 + t / 1e4,
            enhanced_altitude=1000.0 + t if altitude else None,
            heart_rate=120,
        )
        for t in range(0, 60, 10)
    ]


def _fit(start: datetime, *, manufacturer: int = GARMIN, **options: Any) -> bytes:
    """Un FIT d'activité inventé, parti à ``start``, produit ``PRODUCT``."""
    return activity_fit(
        _samples(), start=start, manufacturer=manufacturer, product=PRODUCT, **options
    )


def gz(data: bytes) -> bytes:
    return gzip.compress(data, mtime=0)


def _garmin_export(
    root: Path,
    name: str,
    retrieved_at: str,
    activities: Sequence[tuple[int, str, datetime, bytes | None]],
) -> None:
    """``raw/garmin/<name>/`` : ``acquisition.json``, l'index (identifiant, type de la
    source, départ UTC, l'heure locale à +02:00) et une archive par FIT donné."""
    folder = root / "raw" / "garmin" / name
    (folder / "activities").mkdir(parents=True)
    (folder / "activity_fit").mkdir()
    (folder / "acquisition.json").write_text(
        json.dumps({"retrieved_at": retrieved_at}), encoding="utf-8"
    )
    items = [
        item(
            activityId=ident,
            activityType={"typeKey": kind},
            startTimeLocal=(start + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
            startTimeGMT=start.strftime("%Y-%m-%d %H:%M:%S"),
            elapsedDuration=60.0,
        )
        for ident, kind, start, _ in activities
    ]
    (folder / "activities" / "activities.json").write_text(
        json.dumps(items), encoding="utf-8"
    )
    for ident, _, _, fit in activities:
        if fit is None:
            continue
        info = zipfile.ZipInfo(f"{ident}_ACTIVITY.fit", date_time=_ZIP_DATE)
        info.compress_type = zipfile.ZIP_STORED
        with zipfile.ZipFile(folder / "activity_fit" / f"{ident}.zip", "w") as archive:
            archive.writestr(info, fit)


def _row(ident: str, kind: str, date: str, filename: str = "") -> dict[str, str]:
    return {
        "Activity ID": ident,
        "Activity Date": date,
        "Activity Type": kind,
        "Filename": filename,
        "Elapsed Time": "60",
    }


def _ingest_output(capsys: pytest.CaptureFixture[str]) -> list[str]:
    assert main(["ingest"]) == 0
    return capsys.readouterr().out.splitlines()


def _in_order(lines: list[str], expected: list[str]) -> None:
    """Chaque ligne attendue figure, exacte, après la précédente."""
    position = 0
    for line in expected:
        assert line in lines[position:], line
        position = lines.index(line, position) + 1


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Les noms que ``ZipFile.open`` ouvre dans une archive Strava
    (``export_1.zip``)."""
    names: list[str] = []
    real = zipfile.ZipFile.open

    def recorded(self: zipfile.ZipFile, name: Any, *args: Any, **kwargs: Any) -> Any:
        if str(self.filename).endswith("export_1.zip"):
            names.append(name if isinstance(name, str) else name.filename)
        return real(self, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "open", recorded)
    return names


# --- W_F (§ 6.4 (l)) ------------------------------------------------------------------

G_STARTS = {ident: _utc(2026, 6, ident - 100, 6) for ident in (101, 102, 103, 104, 105)}
FIT_G = {ident: _fit(G_STARTS[ident]) for ident in (101, 102, 103, 104)}
FIT_9013 = _fit(_utc(2024, 8, 4, 8))

WF_ROWS: list[dict[str, str]] = [
    _row("9001", "Run", "Jun 1, 2026, 6:00:00 AM", "activities/9001.fit.gz"),
    _row("9002", "Run", "Jun 2, 2026, 6:00:00 AM", "activities/9002.fit.gz"),
    _row("9003", "Run", "Jun 3, 2026, 6:00:00 AM", "activities/9003.fit.gz"),
    _row("9004", "Hike", "Jul 10, 2026, 7:00:00 AM", "activities/9004.fit.gz"),
    _row("9005", "Run", "Nov 18, 2026, 6:30:00 AM", "activities/9005.fit.gz"),
    _row("9006", "Run", "Jul 13, 2025, 5:02:03 AM", "activities/9006.fit.gz"),
    _row("9008", "Walk", "Jul 13, 2024, 12:05:09 PM", "activities/9008.gpx"),
    _row("9009", "Workout", "Aug 1, 2024, 8:00:00 AM"),
    _row("9010", "Ride", "Aug 2, 2024, 8:00:00 AM", "activities/9010.fit.gz"),
    _row("9011", "Run", "Aug 3, 2024, 8:00:00 AM"),
    _row("9011", "Run", "Aug 3, 2024, 8:00:00 AM"),
    _row("9012", "Run", "Jun 4, 2026, 6:00:00 AM", "activities/9012.fit.gz"),
    _row("9013", "Run", "Aug 4, 2024, 8:00:00 AM", "activities/9013.fit.gz"),
]


def fit_9006() -> bytes:
    return activity_fit(
        _samples(altitude=False),
        record_fields=("timestamp", "position_lat", "position_long", "heart_rate"),
        start=_utc(2025, 7, 13, 5, 2, 3),
        manufacturer=COROS,
        product=PRODUCT,
        local_offset_s=7200,
    )


WF_MEMBERS: dict[str, bytes] = {
    "activities/9001.fit.gz": gz(FIT_G[101]),
    "activities/9002.fit.gz": gz(_fit(G_STARTS[102], local_offset_s=7200)),
    "activities/9003.fit.gz": gz(
        _fit(G_STARTS[103], created_raw=fit_time(G_STARTS[103]) + 1)
    ),
    "activities/9004.fit.gz": gz(_fit(_utc(2026, 7, 10, 7))),
    "activities/9005.fit.gz": gz(_fit(_utc(2026, 11, 18, 6, 30), local_offset_s=3600)),
    "activities/9006.fit.gz": gz(fit_9006()),
    "activities/9008.gpx": b"<gpx/>",
    "activities/9012.fit.gz": gz(
        _fit(G_STARTS[104], manufacturer=SUUNTO, local_offset_s=0)
    ),
    "activities/9013.fit.gz": FIT_9013,
}


def _world_f(root: Path, timezone: str | None = PARIS) -> Path:
    _garmin_export(
        root,
        "g1",
        G1_AT,
        [
            (101, "trail_running", G_STARTS[101], FIT_G[101]),
            (102, "trail_running", G_STARTS[102], FIT_G[102]),
            (103, "trail_running", G_STARTS[103], FIT_G[103]),
            (104, "breathwork", G_STARTS[104], FIT_G[104]),
            (105, "trail_running", G_STARTS[105], None),
        ],
    )
    write_strava_export(
        root,
        "s1",
        retrieved_at=S1_AT,
        timezone=timezone,
        rows=WF_ROWS,
        members=WF_MEMBERS,
    )
    return root


WF_ORDER = [
    "strava-9008",
    "strava-9009",
    "strava-9010",
    "strava-9013",
    "strava-9006",
    "101",
    "102",
    "103",
    "104",
    "strava-9012",
    "105",
    "strava-9005",
]
WF_STARTS = {
    "strava-9008": "2024-07-13T14:05:09+02:00",
    "strava-9009": "2024-08-01T10:00:00+02:00",
    "strava-9010": "2024-08-02T10:00:00+02:00",
    "strava-9013": "2024-08-04T10:00:00+02:00",
    "strava-9006": "2025-07-13T07:02:03+02:00",
    "strava-9012": "2026-06-04T06:00:00+00:00",
    "strava-9005": "2026-11-18T07:30:00+01:00",
}


def test_wf_index_recordings_and_offsets() -> None:
    root = _world_f(data_dir())
    summary = ingest_export(root)
    index = read_index(root)
    assert [entry.activity_ref for entry in index.entries] == WF_ORDER
    recorded = {entry.activity_ref for entry in index.entries if entry.has_recording}
    assert recorded == {
        "101",
        "102",
        "103",
        "104",
        "strava-9005",
        "strava-9006",
        "strava-9012",
    }
    assert summary.recordings == 7
    entries = {entry.activity_ref: entry for entry in index.entries}
    for ref, start in WF_STARTS.items():
        expected = datetime.fromisoformat(start)
        assert entries[ref].start_time == expected, ref
        assert entries[ref].start_time.utcoffset() == expected.utcoffset(), ref
    assert entries["strava-9005"].start_time.utcoffset() == timedelta(hours=1)
    assert entries["strava-9012"].start_time.utcoffset() == timedelta(0)
    recordings = {
        path.stem for path in (root / ACTIVITIES_DIR / "recordings").iterdir()
    }
    assert recordings == recorded


def test_wf_retired_export_report_and_files() -> None:
    root = _world_f(data_dir())
    ingest_export(root)
    report = read_report(root)
    assert report.retired == (RetiredActivity("strava-9004", "g1"),)
    exports = {item.name: item for item in report.exports}
    assert [item.name for item in report.exports] == ["g1", "s1"]
    s1 = exports["s1"]
    assert isinstance(s1, ExportReport)
    assert (s1.entries, s1.archives) == (11, 10)
    assert s1.refused_entries == (
        RefusedEntry(9, RefusalReason.DUPLICATE_ENTRY),
        RefusedEntry(10, RefusalReason.DUPLICATE_ENTRY),
    )
    member = "strava/s1/export_1.zip/activities/{}.fit.gz"
    assert [
        item for item in report.refused_files if item.name.startswith("strava/")
    ] == [RefusedFile(member.format(9013), RefusalReason.NOT_A_GZIP_FIT)]
    assert [item.name for item in report.read if item.name.startswith("strava/")] == [
        "strava/s1/acquisition.json",
        "strava/s1/export_1.zip",
        "strava/s1/export_1.zip/activities.csv",
        *(member.format(ident) for ident in (9001, 9002, 9003, 9004, 9005, 9006)),
        member.format(9012),
        member.format(9013),
    ]


def test_wf_sources() -> None:
    root = _world_f(data_dir())
    summary = ingest_export(root)
    expected = SourcesReport(
        strava_exports=1,
        strava_entries=7,
        matched_by_hash=1,
        matched_by_identity=1,
        matched_by_fit_start=1,
        ambiguous=0,
        retired_garmin_device=1,
        default_timezone_entries=0,
        strava_recordings_without_elevation=1,
        tolerated=(),
    )
    assert read_sources(root) == expected
    assert summary.sources == expected
    assert summary.strava_exports == ("s1",)


WF_LINES = [
    "Exports : 2",
    "  g1 : acquis le 2026-10-01T12:00:00+00:00, 5 entrées gardées, 0 refusées, "
    "4 archives",
    "  s1 (Strava) : acquis le 2026-11-20T09:45:00+00:00, 11 entrées gardées, "
    "2 refusées, 10 fichiers nommés",
    "Activités dans l'index : 12",
    "Enregistrements : 7",
    "Fichiers refusés : 1",
    "Entrées de l'index refusées : 2",
    "Entrées sans archive : 4",
    "Activités retirées de la source : 1",
    "Strava : 1 export(s)",
    "  Entrées venues de Strava : 7",
    "  Appariées à Garmin : 3 (empreinte 1, identité 1, départ du FIT 1)",
    "  Ambiguës : 0",
    "  FIT d'un appareil Garmin absents de Garmin, retirés : 1",
    "  Datées par le fuseau par défaut : 0",
    "  Enregistrements sans altitude : 1",
]


def test_wf_ingest_output(capsys: pytest.CaptureFixture[str]) -> None:
    _world_f(data_dir())
    lines = _ingest_output(capsys)
    _in_order(lines, WF_LINES)
    assert not any(line.startswith("FIT Strava lus par tolérance") for line in lines)
    assert lines.index("  Enregistrements sans altitude : 1") < lines.index(
        next(line for line in lines if line.startswith("Jours : "))
    )


def test_wf_opens_only_named_members(opened: list[str]) -> None:
    root = _world_f(data_dir())
    ingest_export(root)
    named = {row["Filename"] for row in WF_ROWS if row["Filename"]}
    assert opened
    assert set(opened) <= {"activities.csv"} | named
    assert "activities.csv" in opened


def test_wf_prime_default_timezone() -> None:
    """``W_F'`` : sans ``timezone``, mêmes entrées et mêmes départs (le défaut est
    Europe/Paris) ; quatre entrées datées par le défaut."""
    root = _world_f(data_dir(), timezone=None)
    ingest_export(root)
    index = read_index(root)
    assert [entry.activity_ref for entry in index.entries] == WF_ORDER
    entries = {entry.activity_ref: entry for entry in index.entries}
    for ref, start in WF_STARTS.items():
        assert entries[ref].start_time.isoformat() == start, ref
    assert read_sources(root).default_timezone_entries == 4


# --- W_A, W_S, W_L, W_P (§ 6.4 (m)) --------------------------------------------------


def test_wa_ambiguity() -> None:
    root = data_dir()
    start = _utc(2026, 6, 10, 6)
    fit_203 = _fit(_utc(2026, 6, 11, 6))
    _garmin_export(
        root,
        "g1",
        G1_AT,
        [
            (201, "trail_running", start, _fit(start, created_raw=fit_time(start) + 1)),
            (202, "trail_running", start, _fit(start, created_raw=fit_time(start) + 2)),
            (203, "trail_running", _utc(2026, 6, 11, 6), fit_203),
        ],
    )
    write_strava_export(
        root,
        "s1",
        retrieved_at=S1_AT,
        timezone=PARIS,
        rows=[
            _row("9101", "Run", "Jun 10, 2026, 6:00:00 AM", "activities/9101.fit.gz"),
            _row("9102", "Run", "Jun 11, 2026, 6:00:00 AM", "activities/9102.fit.gz"),
            _row("9103", "Run", "Jun 11, 2026, 6:00:00 AM", "activities/9103.fit.gz"),
            _row("9104", "Run", "Jun 11, 2026, 6:00:00 AM", "activities/9103.fit.gz"),
        ],
        members={
            "activities/9101.fit.gz": gz(_fit(start, created_raw=fit_time(start) + 3)),
            "activities/9102.fit.gz": gz(fit_203),
            "activities/9103.fit.gz": gz(fit_203),
        },
    )
    ingest_export(root)
    sources = read_sources(root)
    assert (sources.ambiguous, sources.retired_garmin_device) == (4, 4)
    assert sources.strava_entries == 0
    assert [entry.activity_ref for entry in read_index(root).entries] == [
        "201",
        "202",
        "203",
    ]
    member = "strava/s1/export_1.zip/activities/{}.fit.gz"
    report = read_report(root)
    assert [item.name for item in report.read if item.name.startswith("strava/")] == [
        "strava/s1/acquisition.json",
        "strava/s1/export_1.zip",
        "strava/s1/export_1.zip/activities.csv",
        member.format(9101),
        member.format(9102),
        member.format(9103),
    ]
    assert {item.activity_ref for item in report.retired} == {
        f"strava-{ident}" for ident in (9101, 9102, 9103, 9104)
    }


def test_ws_two_strava_exports() -> None:
    root = data_dir()
    write_strava_export(
        root,
        "s1",
        retrieved_at="2026-06-30T00:00:00+00:00",
        rows=[
            _row("9201", "Run", "Jun 1, 2026, 6:00:00 AM"),
            _row("9202", "Run", "Jun 2, 2026, 6:00:00 AM"),
            _row("9204", "Run", "Jun 15, 2026, 6:00:00 AM"),
        ],
        members={},
    )
    write_strava_export(
        root,
        "s2",
        retrieved_at=S1_AT,
        rows=[
            _row("9202", "Run", "Jun 2, 2026, 6:00:00 AM"),
            _row("9203", "Run", "Jul 1, 2026, 6:00:00 AM"),
        ],
        members={},
    )
    ingest_export(root)
    index = read_index(root)
    assert [entry.activity_ref for entry in index.entries] == [
        "strava-9201",
        "strava-9202",
        "strava-9203",
    ]
    sources = {entry.activity_ref: entry.source.retrieved_at for entry in index.entries}
    assert sources["strava-9201"] == datetime.fromisoformat("2026-06-30T00:00:00+00:00")
    assert sources["strava-9202"] == datetime.fromisoformat(S1_AT)
    report = read_report(root)
    assert report.retired == (RetiredActivity("strava-9204", "s2"),)
    assert [item.name for item in report.exports] == ["s1", "s2"]
    days = read_days_report(root)
    assert [export.name for export in days.exports] == ["s1", "s2"]
    assert all(export.files == 0 for export in days.exports)
    assert days.read == ()
    assert not list((root / "interim" / "days").glob("2*.json"))


@pytest.mark.parametrize(
    "case",
    [
        "meme-nom",
        "garmin-strava-meme-instant",
        "strava-strava-meme-instant",
        "aucun-export",
    ],
)
def test_stops(case: str) -> None:
    root = data_dir()
    if case == "meme-nom":
        _garmin_export(root, "x", G1_AT, [])
        write_strava_export(root, "x", retrieved_at=S1_AT, rows=[], members={})
        message = (
            "raw/garmin/x/ et raw/strava/x/ : même nom d'export ; le rapport nomme les "
            "exports par leur nom seul : renommer l'un des deux dossiers."
        )
    elif case == "garmin-strava-meme-instant":
        _garmin_export(root, "g1", G1_AT, [])
        write_strava_export(root, "s1", retrieved_at=G1_AT, rows=[], members={})
        message = (
            "raw/garmin/g1/ et raw/strava/s1/ : même instant d'acquisition ; l'ordre "
            "des exports serait indéterminé."
        )
    elif case == "strava-strava-meme-instant":
        write_strava_export(root, "s1", retrieved_at=S1_AT, rows=[], members={})
        write_strava_export(
            root, "s2", retrieved_at="2026-11-20T10:45:00+01:00", rows=[], members={}
        )
        message = (
            "raw/strava/s1/ et raw/strava/s2/ : même instant d'acquisition ; l'ordre "
            "des exports serait indéterminé."
        )
    else:
        message = (
            "raw/ ne contient aucun export : un export Garmin se range dans "
            "raw/garmin/<export>/, une archive Strava dans raw/strava/<export>/, "
            "chacun avec son acquisition.json."
        )
    with pytest.raises(IngestError) as error:
        ingest_export(root)
    assert str(error.value) == message
    assert not (root / ACTIVITIES_DIR).exists()


def test_an_empty_strava_folder_beside_a_garmin_export() -> None:
    root = data_dir()
    _garmin_export(
        root, "g1", G1_AT, [(101, "trail_running", G_STARTS[101], FIT_G[101])]
    )
    (root / "raw" / "strava").mkdir()
    summary = ingest_export(root)
    assert summary.activities == 1
    assert summary.sources is None
    assert not (root / ACTIVITIES_DIR / "sources.json").exists()


def test_malformed_garmin_fit_stays_refused(capsys: pytest.CaptureFixture[str]) -> None:
    root = data_dir()
    start = _utc(2026, 6, 1, 6)
    _garmin_export(
        root,
        "g1",
        G1_AT,
        [(301, "trail_running", start, _fit(start, malformed_event_data=True))],
    )
    lines = _ingest_output(capsys)
    report = read_report(root)
    assert report.refused_files == (
        RefusedFile("garmin/g1/activity_fit/301.zip", RefusalReason.UNREADABLE_FIT),
    )
    (entry,) = read_index(root).entries
    assert entry.has_recording is False
    assert not (root / ACTIVITIES_DIR / "sources.json").exists()
    assert not any(line.startswith("Strava") for line in lines)
    assert not any("tolérance" in line for line in lines)


def test_tolerated_strava_fit(capsys: pytest.CaptureFixture[str]) -> None:
    root = data_dir()
    write_strava_export(
        root,
        "s1",
        retrieved_at=S1_AT,
        timezone=PARIS,
        rows=[_row("9014", "Run", "Aug 5, 2024, 8:00:00 AM", "activities/9014.fit.gz")],
        members={
            "activities/9014.fit.gz": gz(
                _fit(_utc(2024, 8, 5, 8), manufacturer=COROS, malformed_event_data=True)
            )
        },
    )
    lines = _ingest_output(capsys)
    name = "strava/s1/export_1.zip/activities/9014.fit.gz"
    (entry,) = read_index(root).entries
    assert (entry.activity_ref, entry.has_recording) == ("strava-9014", True)
    assert read_sources(root).tolerated == (ToleratedFile(name, "coros", "event", 3),)
    _in_order(lines, ["FIT Strava lus par tolérance : 1", f"  {name} : event, champ 3"])


def test_wl_limits(capsys: pytest.CaptureFixture[str]) -> None:
    """``W_L`` : un FIT Garmin refusé dont la copie Strava se lit par tolérance
    s'apparie, l'activité reste sans enregistrement ; une ligne Strava sans FIT lisible
    fait une seconde entrée au même instant qu'une activité Garmin."""
    root = data_dir()
    fit_401 = _fit(_utc(2026, 6, 1, 6), malformed_event_data=True)
    fit_402 = _fit(_utc(2026, 6, 2, 6))
    _garmin_export(
        root,
        "g1",
        G1_AT,
        [
            (401, "trail_running", _utc(2026, 6, 1, 6), fit_401),
            (402, "trail_running", _utc(2026, 6, 2, 6), fit_402),
        ],
    )
    write_strava_export(
        root,
        "s1",
        retrieved_at=S1_AT,
        timezone=PARIS,
        rows=[
            _row("9401", "Run", "Jun 1, 2026, 6:00:00 AM", "activities/9401.fit.gz"),
            _row("9402", "Run", "Jun 2, 2026, 6:00:00 AM", "activities/9402.fit.gz"),
        ],
        members={
            "activities/9401.fit.gz": gz(fit_401),
            "activities/9402.fit.gz": fit_402,
        },
    )
    lines = _ingest_output(capsys)
    index = read_index(root)
    assert [entry.activity_ref for entry in index.entries] == [
        "401",
        "402",
        "strava-9402",
    ]
    entries = {entry.activity_ref: entry for entry in index.entries}
    assert [ref for ref, entry in entries.items() if entry.has_recording] == ["402"]
    assert entries["strava-9402"].start_time.isoformat() == "2026-06-02T08:00:00+02:00"
    assert entries["strava-9402"].start_time == entries["402"].start_time
    assert read_report(root).refused_files == (
        RefusedFile("garmin/g1/activity_fit/401.zip", RefusalReason.UNREADABLE_FIT),
        RefusedFile(
            "strava/s1/export_1.zip/activities/9402.fit.gz",
            RefusalReason.NOT_A_GZIP_FIT,
        ),
    )
    assert read_sources(root) == SourcesReport(
        strava_exports=1,
        strava_entries=1,
        matched_by_hash=1,
        matched_by_identity=0,
        matched_by_fit_start=0,
        ambiguous=0,
        retired_garmin_device=0,
        default_timezone_entries=0,
        strava_recordings_without_elevation=0,
        tolerated=(
            ToleratedFile(
                "strava/s1/export_1.zip/activities/9401.fit.gz", "garmin", "event", 3
            ),
        ),
    )
    assert "Entrées sans archive : 0" in lines


def test_wp_retiring_export() -> None:
    root = data_dir()
    _garmin_export(
        root,
        "g1",
        G1_AT,
        [(501, "trail_running", _utc(2026, 6, 1, 6), _fit(_utc(2026, 6, 1, 6)))],
    )
    _garmin_export(
        root,
        "g2",
        "2026-11-01T12:00:00+00:00",
        [(502, "trail_running", _utc(2026, 7, 1, 6), _fit(_utc(2026, 7, 1, 6)))],
    )
    write_strava_export(
        root,
        "s1",
        retrieved_at=S1_AT,
        timezone=PARIS,
        rows=[
            _row("9501", "Hike", "Jul 10, 2026, 7:00:00 AM", "activities/9501.fit.gz"),
            _row("9502", "Hike", "Jun 10, 2026, 6:00:00 AM", "activities/9502.fit.gz"),
        ],
        members={
            "activities/9501.fit.gz": gz(_fit(_utc(2026, 7, 10, 7))),
            "activities/9502.fit.gz": gz(_fit(_utc(2026, 6, 10, 6))),
        },
    )
    ingest_export(root)
    assert [entry.activity_ref for entry in read_index(root).entries] == ["501", "502"]
    assert set(read_report(root).retired) == {
        RetiredActivity("strava-9501", "g2"),
        RetiredActivity("strava-9502", "g1"),
    }
    sources = read_sources(root)
    assert (sources.retired_garmin_device, sources.strava_entries) == (2, 0)
    assert sources.matched_by_hash + sources.matched_by_identity == 0
    assert sources.matched_by_fit_start == 0
