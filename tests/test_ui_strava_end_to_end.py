"""Condition 4 de la piste (AN1-3, § 6.4 (o) du brief) : un utilisateur qui n'a qu'une
archive Strava, de bout en bout — ``mperf ingest``, ``mperf tables``, ``mperf q1``, puis
la page récupération (``AppTest``). Nommé ``test_ui_*`` : seul ce motif peut importer
streamlit (``ruff``, TID251). Valeurs inventées (règle 1)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest

pytest.importorskip("fitdecode")
pytest.importorskip("pyarrow")
pytest.importorskip("plotly")
pytest.importorskip("streamlit")

import streamlit as st
from streamlit.testing.v1 import AppTest

from fixtures.fit_activity import LOCAL_BAROMETER, SOURCE_LOCAL, Sample, activity_fit
from fixtures.montees import FLAT, climb_at, recording
from fixtures.processed import COMMIT
from fixtures.strava_archive import write_strava_export
from mountain_perf import cli, gitstate
from mountain_perf.cli import main
from mountain_perf.config import data_dir
from mountain_perf.gitstate import GitState
from mountain_perf.ingest.interim import read_index
from test_ingest_strava_fusion import GARMIN, PRODUCT, fit_9006, gz

AT = "2026-11-20T09:45:00+00:00"
EMPTY_DAYS = (
    "La table jours n'a aucune ligne : aucun export ne porte de données journalières "
    "(une archive Strava n'en a pas), ou interim/ n'est pas à jour : lancer just "
    "process."
)


@pytest.fixture(autouse=True)
def _world(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Un clone propre au commit des fixtures, une date du jour fixe, le cache des
    tables vidé avant et après."""
    monkeypatch.setattr(
        gitstate, "git_state", lambda directory: GitState(COMMIT, False)
    )
    monkeypatch.setattr(cli, "_today", lambda: date(2026, 11, 21))
    st.cache_resource.clear()
    yield
    st.cache_resource.clear()


def _fit_9301() -> bytes:
    """Un FIT garmin à baromètre déclaré : un replat, une montée de 60 m à 15 %, un
    replat, à la seconde (``fixtures.montees``, sans bruit)."""
    track = recording([FLAT, climb_at(600, 0.15, 60), FLAT], noise=False)
    assert track.position is not None
    assert track.elevation is not None
    samples = [
        Sample(round(t), lat=lat, lon=lon, enhanced_altitude=z)
        for t, lat, lon, z in zip(
            track.position.time_s,
            track.position.latitude_deg,
            track.position.longitude_deg,
            track.elevation.elevation_m,
            strict=True,
        )
    ]
    duration = round(track.position.time_s[-1])
    return activity_fit(
        samples,
        record_fields=(
            "timestamp",
            "position_lat",
            "position_long",
            "enhanced_altitude",
        ),
        start=datetime(2026, 6, 10, 6, tzinfo=UTC),
        manufacturer=GARMIN,
        product=PRODUCT,
        sensors=((1, SOURCE_LOCAL, LOCAL_BAROMETER),),
        sessions=((0, "running", "trail", float(duration), float(duration), 1400.0),),
        timer_events=((0, "start"), (duration, "stop_all")),
        local_offset_s=7200,
    )


def _row(
    ident: str, kind: str, when: str, filename: str, **more: str
) -> dict[str, str]:
    return {
        "Activity ID": ident,
        "Activity Date": when,
        "Activity Type": kind,
        "Filename": filename,
        **more,
    }


def _recovery() -> None:
    from mountain_perf.ui.recuperation import recuperation_page

    recuperation_page()


def test_strava_alone_end_to_end() -> None:
    pytest.importorskip("fitdecode")
    from mountain_perf.analyse.parquet import read_tables

    root = data_dir()
    write_strava_export(
        root,
        "e1",
        retrieved_at=AT,
        rows=[
            _row(
                "9301",
                "Run",
                "Jun 10, 2026, 6:00:00 AM",
                "activities/9301.fit.gz",
                **{
                    "Elapsed Time": "1360",
                    "Moving Time": "1360",
                    "Distance": "1400",
                    "Elevation Gain": "60",
                    "Elevation Loss": "0",
                },
            ),
            _row("9006", "Run", "Jul 13, 2025, 5:02:03 AM", "activities/9006.fit.gz"),
            _row("9008", "Walk", "Jul 13, 2024, 12:05:09 PM", "activities/9008.gpx"),
        ],
        members={
            "activities/9301.fit.gz": gz(_fit_9301()),
            "activities/9006.fit.gz": gz(fit_9006()),
            "activities/9008.gpx": b"<gpx/>",
        },
    )
    assert main(["ingest"]) == 0
    index = read_index(root)
    assert [entry.activity_ref for entry in index.entries] == [
        "strava-9008",
        "strava-9006",
        "strava-9301",
    ]
    assert {entry.activity_ref for entry in index.entries if entry.has_recording} == {
        "strava-9006",
        "strava-9301",
    }
    entry = index.entries[-1]
    assert (entry.elevation_corrected, entry.training_load) == (None, None)

    assert main(["tables"]) == 0
    tables = read_tables(root)
    assert tables.days == ()
    assert tables.provenance.acquired_at == AT
    assert {row.activity_ref for row in tables.activities} >= {
        "strava-9008",
        "strava-9006",
        "strava-9301",
    }
    assert any(row.activity_ref == "strava-9301" for row in tables.climbs)

    assert main(["q1"]) == 0

    at = AppTest.from_function(_recovery, default_timeout=30).run()
    assert not at.exception
    assert [info.value for info in at.info] == [EMPTY_DAYS]
