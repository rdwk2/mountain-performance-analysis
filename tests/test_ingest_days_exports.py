"""Les fichiers journaliers d'un export et ses refus (``load_export_days``, AN2-1) :
la liste, ce qu'elle ignore, les deux refus et leur borne, un export sans familles.
Sans extra : ni fitdecode, ni ``ingest_export``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType

import pytest

from fixtures.day_exports import export_dir, load, write_day, write_document
from fixtures.days import DAY, EXPORT_A, PLUS1, PLUS2, midnight
from fixtures.families import DOCUMENTS, START
from mountain_perf.ingest.days import (
    ACQUISITION_TOLERANCE_S,
    COMPARISON_IGNORED_FIELDS,
    FAMILY_PIECES,
    NIGHT_TOLERANCE_S,
    ExportDaysError,
    load_export_days,
)
from mountain_perf.schemas import DayFamily

D1 = DAY + timedelta(days=1)
_FULLWIDTH_YEAR = "".join(chr(0xFF10 + int(digit)) for digit in "2001")
"""« 2001 » en chiffres pleine chasse : pas des chiffres ASCII."""
DATE_MESSAGE = (
    f"raw/garmin/{EXPORT_A}/ : un fichier journalier est daté après le jour de "
    "l'acquisition de l'export ; acquisition.json est faux."
)
END_MESSAGE = (
    f"raw/garmin/{EXPORT_A}/ : la fin des données de son dernier jour dépasse "
    "l'instant d'acquisition de plus d'une heure ; acquisition.json est faux."
)


def test_the_constants_of_the_specification() -> None:
    assert ACQUISITION_TOLERANCE_S == 3600.0
    assert NIGHT_TOLERANCE_S == 210.0
    assert isinstance(COMPARISON_IGNORED_FIELDS, MappingProxyType)
    assert list(COMPARISON_IGNORED_FIELDS.items()) == [
        (DayFamily.DAILY_SUMMARY, ("lastSyncTimestampGMT",)),
        (DayFamily.HRV, ("hrvSummary.createTimeStamp",)),
    ]
    assert isinstance(FAMILY_PIECES, MappingProxyType)
    assert list(FAMILY_PIECES.items()) == [
        (DayFamily.SLEEP, ("night", "naps")),
        (DayFamily.HRV, ("hrv",)),
        (DayFamily.RESTING_HR, ("resting_hr",)),
        (DayFamily.HEART_RATE, ("series.heart_rate",)),
        (DayFamily.BODY_BATTERY, ()),
        (DayFamily.STRESS, ("series.stress", "series.body_battery")),
        (DayFamily.RESPIRATION, ("respiration", "series.respiration")),
        (DayFamily.SPO2, ("spo2", "series.spo2")),
        (
            DayFamily.DAILY_SUMMARY,
            ("wellness_data", "stress", "body_battery", "activity_totals"),
        ),
        (DayFamily.TRAINING_READINESS, ("readiness",)),
        (DayFamily.TRAINING_STATUS, ()),
    ]


def test_the_files_are_listed_by_day_then_family(tmp_path: Path) -> None:
    for day, family in (
        (D1, DayFamily.TRAINING_STATUS),
        (DAY, DayFamily.STRESS),
        (D1, DayFamily.SLEEP),
        (DAY, DayFamily.DAILY_SUMMARY),
        (DAY, DayFamily.SLEEP),
    ):
        write_document(tmp_path, family, b"{}", day)
    export = load(tmp_path)
    assert export.name == EXPORT_A
    assert [(file.day, file.family) for file in export.files] == [
        (DAY, DayFamily.SLEEP),
        (DAY, DayFamily.STRESS),
        (DAY, DayFamily.DAILY_SUMMARY),
        (D1, DayFamily.SLEEP),
        (D1, DayFamily.TRAINING_STATUS),
    ]
    assert export.files[0].path == export_dir(tmp_path) / "sleep" / "2001-03-10.json"
    assert "path" not in repr(export.files[0])
    assert "files" not in repr(export)


def test_what_is_not_a_daily_file_is_ignored(tmp_path: Path) -> None:
    """Un dossier qui n'est pas une famille, un nom qui n'est pas une date valide suivie
    de ``.json``, un sous-dossier : ignorés."""
    root = export_dir(tmp_path)
    write_document(tmp_path, DayFamily.HRV, b"{}")
    for folder in ("activities", "activity_fit", "range"):
        (root / folder).mkdir(parents=True)
        (root / folder / "2001-03-10.json").write_bytes(b"{}")
    (root / "profile.json").write_bytes(b"{}")
    hrv = root / "hrv"
    for name in (
        "notes.txt",
        "2001-02-30.json",
        "2001-3-10.json",
        _FULLWIDTH_YEAR + "-03-11.json",
        "2001-03-11.json.bak",
    ):
        (hrv / name).write_bytes(b"{}")
    (root / "sleep").mkdir()
    (root / "sleep" / "2001-03-10.JSON").write_bytes(b"{}")
    (hrv / "2001-03-09.json").mkdir()
    export = load(tmp_path)
    assert [(file.day, file.family) for file in export.files] == [(DAY, DayFamily.HRV)]


def test_an_export_without_daily_families_is_admitted(tmp_path: Path) -> None:
    (export_dir(tmp_path) / "activities").mkdir(parents=True)
    export = load(tmp_path)
    assert export.files == ()


@pytest.mark.parametrize(
    ("retrieved_at", "refused"),
    [
        (datetime(2001, 3, 11, 0, 30, tzinfo=PLUS2), False),
        (datetime(2001, 3, 10, 23, 59, tzinfo=PLUS2), True),
        (datetime(2001, 3, 10, 22, 30, tzinfo=UTC), True),
    ],
)
def test_a_file_dated_after_the_local_day_of_acquisition(
    tmp_path: Path, retrieved_at: datetime, refused: bool
) -> None:
    write_document(tmp_path, DayFamily.HRV, DOCUMENTS[DayFamily.HRV](D1), D1)
    if refused:
        with pytest.raises(ExportDaysError) as error:
            load(tmp_path, retrieved_at=retrieved_at)
        assert str(error.value) == DATE_MESSAGE
    else:
        assert len(load(tmp_path, retrieved_at=retrieved_at).files) == 1


@pytest.mark.parametrize(
    ("ahead_s", "refused"),
    [(ACQUISITION_TOLERANCE_S, False), (ACQUISITION_TOLERANCE_S + 1, True)],
)
def test_the_end_of_the_data_of_the_last_day_at_its_bound(
    tmp_path: Path, ahead_s: float, refused: bool
) -> None:
    """Fin des données à exactement ``ACQUISITION_TOLERANCE_S`` après l'instant :
    admise ; une seconde de plus : refusée."""
    write_day(tmp_path, families=(DayFamily.DAILY_SUMMARY,))
    retrieved_at = START + timedelta(days=1) - timedelta(seconds=ahead_s)
    assert retrieved_at.date() == DAY
    if refused:
        with pytest.raises(ExportDaysError) as error:
            load(tmp_path, retrieved_at=retrieved_at)
        assert str(error.value) == END_MESSAGE
    else:
        assert len(load(tmp_path, retrieved_at=retrieved_at).files) == 1


def test_the_end_of_the_data_is_read_on_the_day_window(tmp_path: Path) -> None:
    """La fin des données est celle de la fenêtre du jour (``daily_summary`` d'abord) :
    une autre famille qui finit plus tard ne refuse pas l'export."""
    heart_rate = DOCUMENTS[DayFamily.HEART_RATE](DAY)
    later = START + timedelta(hours=26)
    heart_rate["endTimestampGMT"] = later.astimezone(UTC).strftime(
        "%Y-%m-%dT%H:%M:%S.0"
    )
    write_day(
        tmp_path,
        families=(DayFamily.DAILY_SUMMARY, DayFamily.HEART_RATE),
        heart_rate=heart_rate,
    )
    retrieved_at = (
        START + timedelta(days=1) - timedelta(seconds=ACQUISITION_TOLERANCE_S)
    )
    assert len(load(tmp_path, retrieved_at=retrieved_at).files) == 2


def test_the_last_day_that_carries_a_window_is_checked(tmp_path: Path) -> None:
    """Un dernier jour sans fenêtre (``training_status``, et ``heart_rate`` vide) : la
    fin des données est celle du jour d'avant qui en porte une."""
    summary = DOCUMENTS[DayFamily.DAILY_SUMMARY](
        DAY, START, midnight(D1) + timedelta(hours=2)
    )
    write_day(tmp_path, families=(DayFamily.DAILY_SUMMARY,), daily_summary=summary)
    write_day(tmp_path, D1, families=(DayFamily.TRAINING_STATUS,))
    write_document(tmp_path, DayFamily.HEART_RATE, b"{}", D1)
    retrieved_at = datetime(2001, 3, 11, 0, 30, tzinfo=PLUS1)
    with pytest.raises(ExportDaysError) as error:
        load(tmp_path, retrieved_at=retrieved_at)
    assert str(error.value) == END_MESSAGE
    admitted = datetime(2001, 3, 11, 1, 0, tzinfo=PLUS1)
    assert len(load(tmp_path, retrieved_at=admitted).files) == 3


def test_the_date_is_checked_before_the_end_of_the_data(tmp_path: Path) -> None:
    """Les deux refus à la fois : la date parle."""
    write_day(tmp_path, families=(DayFamily.DAILY_SUMMARY,))
    write_document(tmp_path, DayFamily.HRV, b"{}", D1)
    with pytest.raises(ExportDaysError) as error:
        load(tmp_path, retrieved_at=datetime(2001, 3, 10, 12, tzinfo=PLUS1))
    assert str(error.value) == DATE_MESSAGE


def test_the_name_given_is_the_one_of_the_message(tmp_path: Path) -> None:
    write_document(tmp_path, DayFamily.HRV, b"{}", D1)
    with pytest.raises(ExportDaysError) as error:
        load_export_days(
            export_dir(tmp_path), "autre.nom", datetime(2001, 3, 10, 12, tzinfo=PLUS1)
        )
    assert str(error.value).startswith("raw/garmin/autre.nom/ : ")
