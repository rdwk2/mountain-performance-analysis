"""Tests des contrats communs : Sport, QualityFlag, SourceRef."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone

import pytest
from hypothesis import given

from mountain_perf.schemas import (
    QUALITY_FLAG_DESCRIPTIONS,
    SPORT_DESCRIPTIONS,
    ContractError,
    QualityFlag,
    SourceRef,
    Sport,
)
from strategies import (
    aware_datetimes,
    blank_texts,
    naive_datetimes,
    path_like_identifiers,
    source_refs,
)

HASH = "0" * 64


SOURCE = SourceRef(
    kind="gpx",
    identifier="trace.gpx",
    content_hash=HASH,
    retrieved_at=datetime(2026, 9, 13, 8, 0, tzinfo=UTC),
)


# ---------------------------------------------------------------------------
# Énumérations
# ---------------------------------------------------------------------------


def test_every_sport_is_described() -> None:
    assert set(SPORT_DESCRIPTIONS) == set(Sport)
    assert all(text.strip() for text in SPORT_DESCRIPTIONS.values())


def test_every_quality_flag_is_described() -> None:
    assert set(QUALITY_FLAG_DESCRIPTIONS) == set(QualityFlag)
    assert all(text.strip() for text in QUALITY_FLAG_DESCRIPTIONS.values())


def test_descriptions_are_read_only() -> None:
    with pytest.raises(TypeError):
        SPORT_DESCRIPTIONS[Sport.FOOT] = "x"  # type: ignore[index]


def test_sport_values_are_declared_not_speculated() -> None:
    assert {s.value for s in Sport} == {"foot", "ski_touring", "mtb"}


def test_quality_flags_are_the_three_planned() -> None:
    assert {f.value for f in QualityFlag} == {
        "gps_gap",
        "elevation_spike",
        "implausible_speed",
    }


# ---------------------------------------------------------------------------
# SourceRef
# ---------------------------------------------------------------------------


@given(source_refs())
def test_valid_source_refs_build_and_are_in_utc(source: SourceRef) -> None:
    assert source.retrieved_at.utcoffset() == timedelta(0)


@given(aware_datetimes())
def test_retrieved_at_is_normalised_to_utc_without_changing_the_instant(
    dt: datetime,
) -> None:
    source = replace(SOURCE, retrieved_at=dt)
    assert source.retrieved_at == dt
    assert source.retrieved_at.tzinfo == UTC


def test_retrieved_at_example_in_local_time() -> None:
    local = datetime(2026, 9, 13, 10, 0, tzinfo=timezone(timedelta(hours=2)))
    assert replace(SOURCE, retrieved_at=local).retrieved_at == datetime(
        2026, 9, 13, 8, 0, tzinfo=UTC
    )


@given(naive_datetimes())
def test_naive_retrieved_at_is_refused(dt: datetime) -> None:
    with pytest.raises(ContractError, match="fuseau"):
        replace(SOURCE, retrieved_at=dt)


@pytest.mark.parametrize("identifier", ["trace.gpx", "a.b.c.json", "..gpx", "x"])
def test_file_names_are_accepted(identifier: str) -> None:
    assert replace(SOURCE, identifier=identifier).identifier == identifier


@pytest.mark.parametrize(
    "identifier", ["a/b.gpx", "a\\b.gpx", "C:x", ".", "..", r"C:\Users\x\trace.gpx"]
)
def test_paths_are_refused_as_identifier(identifier: str) -> None:
    with pytest.raises(ContractError, match="chemin"):
        replace(SOURCE, identifier=identifier)


@given(path_like_identifiers())
def test_generated_paths_are_refused_as_identifier(identifier: str) -> None:
    with pytest.raises(ContractError, match="chemin"):
        replace(SOURCE, identifier=identifier)


@given(blank_texts())
def test_blank_kind_is_refused(kind: str) -> None:
    with pytest.raises(ContractError, match="kind"):
        replace(SOURCE, kind=kind)


@given(blank_texts())
def test_blank_identifier_is_refused(identifier: str) -> None:
    with pytest.raises(ContractError, match="identifier"):
        replace(SOURCE, identifier=identifier)


@pytest.mark.parametrize(
    "content_hash", ["", "0" * 63, "0" * 65, "A" * 64, "g" * 64, " " + "0" * 63]
)
def test_malformed_hash_is_refused(content_hash: str) -> None:
    with pytest.raises(ContractError, match="sha256"):
        replace(SOURCE, content_hash=content_hash)


def test_source_ref_is_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        SOURCE.identifier = "autre.gpx"  # type: ignore[misc]
