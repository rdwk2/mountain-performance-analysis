"""Les documents d'``interim/activities/`` : écriture, relecture, mise en place."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mountain_perf.codec import CodecError
from mountain_perf.ingest.interim import (
    ACTIVITIES_DIR,
    INTERIM_DOCUMENT_FIRST_FORMAT,
    InterimError,
    decode_interim,
    encode_interim,
    read_index,
    read_recording,
    read_report,
    write_activities,
)
from mountain_perf.schemas import (
    INTERIM_FORMAT_VERSION,
    ActivityIndex,
    ActivityRecording,
    IngestionReport,
    ReadFile,
    RecordingMismatch,
    ViewRefusal,
    ViewRefusalCount,
)
from mountain_perf.validation import ContractError
from test_schemas_interim import SOURCE, entry, recording

INDEX = ActivityIndex(
    (
        entry(),
        entry(
            activity_ref="12",
            has_recording=False,
            start_time=datetime(2024, 3, 10, tzinfo=UTC),
        ),
    ),
    dataclasses.replace(SOURCE, kind="garmin_activities", identifier="activities.json"),
)
REPORT = IngestionReport(
    datetime(2024, 4, 1, tzinfo=UTC),
    (ReadFile("activity_fit/11.zip", "d" * 64),),
    (),
    (),
    (ViewRefusalCount(ViewRefusal.NO_SPORT, "golf", 2),),
    (RecordingMismatch("11", 7200.0, 61.0, 3723.5),),
)


def test_format_and_types() -> None:
    assert INTERIM_FORMAT_VERSION == 1
    assert dict(INTERIM_DOCUMENT_FIRST_FORMAT) == {
        ActivityIndex: 1,
        ActivityRecording: 1,
        IngestionReport: 1,
    }


def test_document_envelope_starts_with_type_and_format() -> None:
    assert encode_interim(recording()).startswith(
        b'{"type":"ActivityRecording","format":1,"data":{'
    )


@pytest.mark.parametrize("value", [INDEX, recording(), REPORT])
def test_round_trip_is_exact(value: object) -> None:
    data = encode_interim(value)
    assert decode_interim(data, type(value)) == value
    assert encode_interim(decode_interim(data, type(value))) == data


def test_other_format_is_refused() -> None:
    data = encode_interim(REPORT).replace(b'"format":1', b'"format":2', 1)
    with pytest.raises(CodecError, match="format 2, 1 attendu"):
        decode_interim(data, IngestionReport)


def test_write_then_read(tmp_path: Path) -> None:
    write_activities(tmp_path, INDEX, [recording()], REPORT)
    root = tmp_path / ACTIVITIES_DIR
    assert sorted(p.name for p in root.iterdir()) == [
        "index.json",
        "recordings",
        "report.json",
    ]
    assert [p.name for p in (root / "recordings").iterdir()] == ["11.json"]
    assert read_index(tmp_path) == INDEX
    assert read_report(tmp_path) == REPORT
    assert read_recording(tmp_path, "11") == recording()
    assert (root / "index.json").read_bytes() == encode_interim(INDEX)


def test_rewriting_replaces_everything(tmp_path: Path) -> None:
    write_activities(tmp_path, INDEX, [recording()], REPORT)
    stale = tmp_path / ACTIVITIES_DIR / "recordings" / "99.json"
    stale.write_bytes(b"x")
    write_activities(tmp_path, INDEX, [recording()], REPORT)
    assert not stale.exists()
    assert sorted(p.name for p in (tmp_path / "interim").iterdir()) == ["activities"]


EXTRA = (
    "Un enregistrement doit correspondre à une entrée de l'index qui en porte un, une "
    "seule fois."
)
MISSING = "Chaque entrée de l'index qui porte un enregistrement doit en recevoir un."


@pytest.mark.parametrize(
    ("recordings", "message"),
    [
        ([], MISSING),
        ([recording(), recording()], EXTRA),
        ([recording(activity_ref="12")], EXTRA),
        ([recording(activity_ref="13")], EXTRA),
    ],
)
def test_recordings_must_match_the_index(
    tmp_path: Path, recordings: list[ActivityRecording], message: str
) -> None:
    write_activities(tmp_path, INDEX, [recording()], REPORT)
    before = (tmp_path / ACTIVITIES_DIR / "index.json").read_bytes()
    with pytest.raises(ValueError, match="enregistrement") as error:
        write_activities(tmp_path, INDEX, recordings, REPORT)
    assert type(error.value) is ValueError
    assert str(error.value) == message
    assert (tmp_path / ACTIVITIES_DIR / "index.json").read_bytes() == before
    assert sorted(p.name for p in (tmp_path / "interim").iterdir()) == ["activities"]


def test_missing_interim_says_what_to_do(tmp_path: Path) -> None:
    with pytest.raises(InterimError) as error:
        read_index(tmp_path)
    assert (
        str(error.value) == "index.json manque dans interim/ : lancer `mperf ingest`."
    )
    with pytest.raises(InterimError) as error:
        read_recording(tmp_path, "7")
    assert str(error.value) == "7.json manque dans interim/ : lancer `mperf ingest`."


def test_recording_under_another_name_is_refused(tmp_path: Path) -> None:
    write_activities(tmp_path, INDEX, [recording()], REPORT)
    root = tmp_path / ACTIVITIES_DIR / "recordings"
    (root / "11.json").rename(root / "12.json")
    with pytest.raises(InterimError) as error:
        read_recording(tmp_path, "12")
    assert str(error.value) == (
        "interim/ incohérent : un enregistrement porte un autre identifiant que son "
        "nom de fichier. Lancer `mperf ingest`."
    )


def test_leftovers_of_an_interrupted_write_are_removed(tmp_path: Path) -> None:
    for name in ("activities.nouveau", "activities.ancien"):
        leftover = tmp_path / "interim" / name / "recordings"
        leftover.mkdir(parents=True)
        (leftover / "5.json").write_bytes(b"x")
    write_activities(tmp_path, INDEX, [recording()], REPORT)
    assert sorted(p.name for p in (tmp_path / "interim").iterdir()) == ["activities"]


@pytest.mark.parametrize("ref", ["..", "../11", "a/b", ""])
def test_recording_ref_must_name_a_file_of_the_folder(tmp_path: Path, ref: str) -> None:
    write_activities(tmp_path, INDEX, [recording()], REPORT)
    with pytest.raises(ContractError):
        read_recording(tmp_path, ref)
