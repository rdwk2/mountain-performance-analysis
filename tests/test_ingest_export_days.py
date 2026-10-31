"""Les jours dans ``ingest_export`` et ``mperf ingest`` (AN2-1), de bout en bout : la
condition (2) du moteur (``interim/activities/`` à l'octet, avec et sans familles
journalières, et comme AN2-0), les octets d'``interim/days/``, les refus d'un export,
la sortie complète de ``mperf ingest``, l'échec de la mise en place des jours."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

pytest.importorskip("fitdecode")

from fixtures.day_exports import write_day, write_document
from fixtures.days import DAY
from fixtures.families import DOCUMENTS
from fixtures.garmin_activities import (
    EXPORT,
    write_activities_export,
)
from mountain_perf.cli import main
from mountain_perf.ingest import export as export_module
from mountain_perf.ingest.days import build_days, load_export_days
from mountain_perf.ingest.export import (
    DAYS_NOT_IN_PLACE,
    IngestError,
    ingest_export,
    read_acquisition,
)
from mountain_perf.ingest.interim import (
    read_days,
    read_days_report,
    read_training_status,
)
from mountain_perf.schemas import DayFamily

D1 = DAY + timedelta(days=1)
LATER = "garmin_b"
LATER_AT = "2001-03-13T12:00:00+01:00"

ACTIVITY_HASHES = {
    "index.json": "ab73396849df779434de1f36b3ad23fc8ca6a836b16334cf85073783cb755ad7",
    "recordings/11.json": (
        "4293007dfced86b1e4a1219885f5c60098a59885868f027c9ffc868dc75407a7"
    ),
    "recordings/12.json": (
        "da2a8ad2d04801c72648d3754eb9934d5a21ce7949f44f8c55524cc50a957b0d"
    ),
    "report.json": "ad01ec2409ad5f30df1294884188bd3ff610a2aa440e89a57ccb52c351d8bbec",
}
"""Les empreintes SHA-256 d'``interim/activities/`` pour le faux export des activités,
écrites par le code de ``main`` avant AN2-1 (``abab4d2``)."""

ACTIVITY_LINES = [
    "Activités dans l'index : 2",
    "Enregistrements : 2",
    "Fichiers refusés : 0",
    "Entrées de l'index refusées : 0",
    "Entrées sans archive : 0",
    "Enregistrements en désaccord avec l'index : 0",
    "Activités sans vue Activity : 0",
    "Activités retirées de la source : 0",
    "Champs de l'index qui diffèrent d'un export à l'autre : 0",
    "Activités aux FIT différents d'un export à l'autre : 0",
    "Enregistrements tirés d'un autre export que leur entrée : 0",
]


def _later_export(root: Path, name: str = LATER, at: str = LATER_AT) -> None:
    """Un second export des mêmes activités, acquis plus tard."""
    write_activities_export(root, name)
    (root / "raw" / "garmin" / name / "acquisition.json").write_text(
        json.dumps({"retrieved_at": at}), encoding="utf-8"
    )


def _files(folder: Path) -> dict[str, bytes]:
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def _hashes(folder: Path) -> dict[str, str]:
    return {
        name: hashlib.sha256(data).hexdigest() for name, data in _files(folder).items()
    }


def _two_days(root: Path) -> None:
    write_activities_export(root)
    write_day(root, DAY)
    write_day(root, D1)


def test_activities_are_those_of_an2_0_with_and_without_daily_families(
    tmp_path: Path,
) -> None:
    """Les octets d'``interim/activities/`` d'un faux export sont les mêmes avec et sans
    familles journalières, et égaux à ceux du code d'AN2-0 : le calcul des activités n'a
    pas bougé."""
    without = tmp_path / "sans"
    write_activities_export(without)
    ingest_export(without)
    with_days = tmp_path / "avec"
    _two_days(with_days)
    summary = ingest_export(with_days)
    assert summary.days.days == 2
    activities = _files(with_days / "interim" / "activities")
    assert activities == _files(without / "interim" / "activities")
    assert _hashes(with_days / "interim" / "activities") == ACTIVITY_HASHES
    assert (without / "interim" / "days").is_dir()
    assert read_days(without) == ()


def test_two_ingestions_write_the_same_bytes(tmp_path: Path) -> None:
    _two_days(tmp_path)
    ingest_export(tmp_path)
    first = _files(tmp_path / "interim")
    ingest_export(tmp_path)
    assert _files(tmp_path / "interim") == first
    assert any(name.startswith("days/") for name in first)


def _two_exports(root: Path) -> None:
    write_activities_export(root, "garmin_z")
    _later_export(root, "garmin_y")
    for export in ("garmin_z", "garmin_y"):
        write_day(root, DAY, export=export)
    write_day(
        root,
        D1,
        export="garmin_y",
        families=[item for item in DayFamily if item is not DayFamily.HRV],
    )
    write_document(root, DayFamily.HRV, DOCUMENTS[DayFamily.HRV](D1), D1, "garmin_z")


def test_the_same_exports_listed_in_another_order_write_the_same_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Les mêmes exports (des noms dans l'ordre inverse de leurs instants), listés à
    rebours (dossiers des exports et des familles, fichiers) : mêmes octets
    d'``interim/``."""
    forward = tmp_path / "endroit"
    backward = tmp_path / "envers"
    _two_exports(forward)
    _two_exports(backward)
    ingest_export(forward)
    real = Path.iterdir

    def reversed_listing(self: Path) -> Iterator[Path]:
        return iter(sorted(real(self), key=lambda path: path.name, reverse=True))

    monkeypatch.setattr(Path, "iterdir", reversed_listing)
    summary = ingest_export(backward)
    monkeypatch.undo()
    assert summary.days.borrowings == 1
    assert _files(backward / "interim") == _files(forward / "interim")


def test_what_the_documents_say(tmp_path: Path) -> None:
    _two_exports(tmp_path)
    summary = ingest_export(tmp_path)
    raw = tmp_path / "raw" / "garmin"
    expected = build_days(
        [
            load_export_days(raw / name, name, read_acquisition(raw / name))
            for name in ("garmin_z", "garmin_y")
        ]
    )
    assert read_days(tmp_path) == expected.records
    assert read_training_status(tmp_path) == expected.history
    assert read_days_report(tmp_path) == expected.report
    assert summary.days == expected.summary
    assert [item.day for item in expected.records] == [DAY, D1]
    assert [item.reference_export for item in expected.records] == [
        "garmin_y",
        "garmin_y",
    ]


@pytest.mark.parametrize("refusal", ["date", "fin"])
def test_a_refused_export_stops_the_ingestion_and_writes_nothing(
    tmp_path: Path, refusal: str
) -> None:
    write_activities_export(tmp_path)
    last = DAY + timedelta(days=2)
    if refusal == "date":
        write_document(tmp_path, DayFamily.HRV, b"{}", last + timedelta(days=1), EXPORT)
        message = (
            f"raw/garmin/{EXPORT}/ : un fichier journalier est daté après le jour de "
            "l'acquisition de l'export ; acquisition.json est faux."
        )
    else:
        write_day(tmp_path, last, export=EXPORT, families=(DayFamily.DAILY_SUMMARY,))
        message = (
            f"raw/garmin/{EXPORT}/ : la fin des données de son dernier jour dépasse "
            "l'instant d'acquisition de plus d'une heure ; acquisition.json est faux."
        )
    with pytest.raises(IngestError) as error:
        ingest_export(tmp_path)
    assert str(error.value) == message
    assert error.value.__cause__ is None
    assert not (tmp_path / "interim").exists()


def test_c6_iv_two_exports_at_the_same_instant_stop_the_ingestion(
    tmp_path: Path,
) -> None:
    write_activities_export(tmp_path)
    write_activities_export(tmp_path, LATER)
    write_day(tmp_path, DAY, export=EXPORT)
    write_day(tmp_path, DAY, export=LATER)
    with pytest.raises(IngestError) as error:
        ingest_export(tmp_path)
    assert str(error.value) == (
        f"raw/garmin/{EXPORT}/ et raw/garmin/{LATER}/ : même instant d'acquisition ; "
        "l'ordre des exports serait indéterminé."
    )
    assert not (tmp_path / "interim").exists()


def test_cli_ingest_prints_the_days_after_the_activities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    write_activities_export(tmp_path)
    _later_export(tmp_path)
    write_day(tmp_path, DAY, export=EXPORT)
    write_day(tmp_path, D1, export=EXPORT)
    write_day(
        tmp_path,
        D1,
        export=LATER,
        families=[item for item in DayFamily if item is not DayFamily.HRV],
    )
    monkeypatch.setenv("MPA_DATA_DIR", str(tmp_path))
    assert main(["ingest"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "Exports : 2",
        f"  {EXPORT} : acquis le 2001-03-12T11:00:00+00:00, 2 entrées gardées, "
        "0 refusées, 2 archives",
        f"  {LATER} : acquis le 2001-03-13T11:00:00+00:00, 2 entrées gardées, "
        "0 refusées, 2 archives",
        *ACTIVITY_LINES,
        "Jours : 2",
        f"  {EXPORT} : export de référence de 1 jour(s)",
        f"  {LATER} : export de référence de 1 jour(s)",
        "  empty : 0 jour(s)",
        "  no_measurement : 0 jour(s)",
        "  truncated : 0 jour(s)",
        "  complete : 2 jour(s)",
        "Morceaux empruntés : 1",
        "Emprunts refusés : 0",
        "Révisions (champs × jours) : 0",
        "Dégradations (champs × jours) : 0",
        "Écarts à part (champs × jours) : 0",
        "Fichiers journaliers refusés : 0",
        "Points écartés : 2",
        "Codes inconnus : 0",
        "Blocs de Training Status : 10",
        "Blocs sans instant propre : 0",
    ]


def test_cli_ingest_names_the_refused_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    write_activities_export(tmp_path)
    write_document(tmp_path, DayFamily.HRV, b"{}", DAY + timedelta(days=3), EXPORT)
    monkeypatch.setenv("MPA_DATA_DIR", str(tmp_path))
    assert main(["ingest"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        f"Erreur : raw/garmin/{EXPORT}/ : un fichier journalier est daté après le jour "
        "de l'acquisition de l'export ; acquisition.json est faux.\n"
    )
    assert not (tmp_path / "interim").exists()


def _refuse_days_in_place(monkeypatch: pytest.MonkeyPatch) -> None:
    """``days.nouveau/`` ne prend pas sa place (un fichier ouvert, sous Windows)."""
    real = Path.rename

    def refused(self: Path, target: Path) -> Path:
        if self.name == "days.nouveau":
            raise PermissionError("fichier ouvert")
        return real(self, target)

    monkeypatch.setattr(Path, "rename", refused)


def _first_ingestion(root: Path) -> None:
    """Une première ingestion d'un jour, sans l'archive de la seconde activité ; puis
    l'archive revient et un second jour s'ajoute."""
    write_activities_export(root)
    archive = root / "raw" / "garmin" / EXPORT / "activity_fit" / "12.zip"
    kept = archive.read_bytes()
    archive.unlink()
    write_day(root, DAY)
    ingest_export(root)
    archive.write_bytes(kept)
    write_day(root, D1)


def test_days_that_fail_to_take_their_place_after_the_activities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Les activités sont neuves, les jours restent les anciens ; le message dit que la
    mise en place des jours a échoué, l'``OSError`` en est la cause."""
    _first_ingestion(tmp_path)
    recording = tmp_path / "interim" / "activities" / "recordings" / "12.json"
    assert not recording.exists()
    old_days = read_days(tmp_path)
    assert [item.day for item in old_days] == [DAY]
    _refuse_days_in_place(monkeypatch)
    with pytest.raises(IngestError) as error:
        ingest_export(tmp_path)
    monkeypatch.undo()
    assert str(error.value) == DAYS_NOT_IN_PLACE
    assert str(error.value) == (
        "interim/activities/ est à jour, mais la mise en place d'interim/days/ a "
        "échoué : relancer `mperf " + "ingest`."
    )
    assert isinstance(error.value.__cause__, PermissionError)
    assert recording.exists()
    assert read_days(tmp_path) == old_days


def test_days_in_place_whose_old_folder_is_not_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Les jours neufs ont pris leur place, seule la suppression de ``days.ancien/``
    échoue : le message ne dit pas les jours anciens (il ne dit pas lequel), et
    ``interim/days/`` est le neuf ; la prochaine ingestion retire ``days.ancien/``."""
    _first_ingestion(tmp_path)
    real = shutil.rmtree

    def refused(path: Path, *args: object, **kwargs: object) -> None:
        if Path(path).name == "days.ancien":
            raise PermissionError("fichier ouvert")
        real(path)

    monkeypatch.setattr(shutil, "rmtree", refused)
    with pytest.raises(IngestError) as error:
        ingest_export(tmp_path)
    monkeypatch.undo()
    assert str(error.value) == DAYS_NOT_IN_PLACE
    assert isinstance(error.value.__cause__, PermissionError)
    assert [item.day for item in read_days(tmp_path)] == [DAY, D1]
    assert (tmp_path / "interim" / "days.ancien").is_dir()
    ingest_export(tmp_path)
    assert not (tmp_path / "interim" / "days.ancien").exists()
    assert [item.day for item in read_days(tmp_path)] == [DAY, D1]


def test_cli_ingest_says_the_days_were_not_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _two_days(tmp_path)
    monkeypatch.setenv("MPA_DATA_DIR", str(tmp_path))
    _refuse_days_in_place(monkeypatch)
    assert main(["ingest"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"Erreur : {DAYS_NOT_IN_PLACE}\n"


def test_the_days_are_computed_before_any_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tout se calcule avant la première écriture : un échec du calcul des jours n'écrit
    rien, pas même ``interim/activities/``."""
    _two_days(tmp_path)

    def failing(*args: object) -> None:
        raise RuntimeError("calcul des jours")

    monkeypatch.setattr(export_module, "build_days", failing)
    with pytest.raises(RuntimeError, match=r"^calcul des jours$"):
        ingest_export(tmp_path)
    assert not (tmp_path / "interim").exists()
