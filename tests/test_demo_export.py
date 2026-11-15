"""Les sorties et l'export Garmin des profils de démo (M5-3, § 6.2 (b) à (e) du
brief) : la version réduite du débutant, écrite puis ingérée par la vraie commande
(``main(["ingest"])``, extra ``ingest``)."""

from __future__ import annotations

import contextlib
import io
import json
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from mountain_perf.cli import main
from mountain_perf.config import DATA_DIR_ENV_VAR
from mountain_perf.demo.constantes import CHARACTER_NAMES
from mountain_perf.demo.parcours import (
    ROUTES,
    grade_at,
    length_m,
    route,
    to_lat_lon,
    xy_at,
)
from mountain_perf.demo.personnages import character, true_speed_ms
from mountain_perf.demo.sorties import (
    ExportSummary,
    Outing,
    PlannedOuting,
    plan,
    simulate,
    write_export,
    write_routes,
)
from mountain_perf.gpx.trace_reader import read_trace
from mountain_perf.ingest.interim import read_index

T0 = date(2026, 11, 13)
EXPORT = Path("raw") / "garmin" / "demo"


@dataclass(frozen=True)
class Written:
    folder: Path
    summary: ExportSummary
    code: int
    out: str


@pytest.fixture(scope="module")
def written(tmp_path_factory: pytest.TempPathFactory) -> Written:
    """La version réduite du débutant, ses préparés, puis ``mperf ingest`` sur ce
    dossier."""
    pytest.importorskip("fitdecode")
    folder = tmp_path_factory.mktemp("demo_export")
    summary = write_export(character("debutant"), folder, T0, reduced=True)
    write_routes(folder)
    buffer = io.StringIO()
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(DATA_DIR_ENV_VAR, str(folder))
        with contextlib.redirect_stdout(buffer):
            code = main(["ingest"])
    return Written(folder, summary, code, buffer.getvalue())


def _index(folder: Path) -> list[dict[str, Any]]:
    text = (folder / EXPORT / "activities" / "activities.json").read_bytes()
    loaded: list[dict[str, Any]] = json.loads(text.decode("utf-8"))
    return loaded


def test_acquisition_bytes(written: Written) -> None:
    assert (written.folder / EXPORT / "acquisition.json").read_bytes() == (
        b'{"retrieved_at": "2026-11-13T06:00:00+01:00"}'
    )


def test_ingest_counts(written: Written) -> None:
    assert written.code == 0
    lines = written.out.splitlines()
    for line in (
        "Activités dans l'index : 12",
        "Enregistrements : 12",
        "Fichiers refusés : 0",
        "Entrées de l'index refusées : 0",
        "Entrées sans archive : 0",
        "Enregistrements en désaccord avec l'index : 0",
    ):
        assert line in lines, line


def test_moving_durations(written: Written) -> None:
    entries = _index(written.folder)
    for number, entry in enumerate(entries, start=1):
        stop = 120.0 if number % 3 == 0 else 0.0
        assert entry["movingDuration"] == entry["elapsedDuration"] - stop, number


def test_training_load(written: Written) -> None:
    entries = _index(written.folder)
    for number, entry in enumerate(entries, start=1):
        if number == 11:
            assert entry["activityTrainingLoad"] is None
        else:
            assert entry["activityTrainingLoad"] == round(
                entry["elapsedDuration"] / 60, 1
            )


def test_the_index_entries(written: Written) -> None:
    entries = _index(written.folder)
    first = entries[0]
    assert first["activityId"] == 1_000_001
    assert entries[-1]["activityId"] == 1_000_012
    assert first["activityName"] == "boucle_douce, 1 tour"
    assert first["activityType"] == {"typeKey": "trail_running"}
    assert first["startTimeLocal"] == "2026-10-09 09:00:00"
    assert first["startTimeGMT"] == "2026-10-09 07:00:00"
    assert first["distance"] == 7_200.0
    assert first["elevationGain"] == first["elevationLoss"] == 117.0
    assert entries[-1]["startTimeLocal"] == "2026-11-11 09:00:00"
    assert entries[-1]["startTimeGMT"] == "2026-11-11 08:00:00"


def test_every_field_of_the_summary(written: Written) -> None:
    summary = written.summary
    assert (summary.outings, summary.first_day, summary.last_day) == (
        12,
        date(2026, 10, 9),
        date(2026, 11, 12),
    )
    assert summary.witness == (
        written.folder / "sorties" / "sortie_2026-11-11_boucle_douce.gpx"
    )


def test_the_witness_trace_matches_its_activity(written: Written) -> None:
    trace = read_trace([written.summary.witness])
    index = read_index(written.folder)
    (entry,) = [
        e
        for e in index.entries
        if e.start_time.astimezone(UTC).date() == date(2026, 11, 11)
    ]
    assert entry.elapsed_duration_s is not None
    assert abs((trace.start_time - entry.start_time).total_seconds()) <= 1
    assert abs(trace.time_s[-1] - entry.elapsed_duration_s) <= 1


def test_the_prepared_routes(written: Written) -> None:
    assert sorted(p.name for p in (written.folder / "routes").iterdir()) == sorted(
        f"{r.name}.gpx" for r in ROUTES
    )


class _Half(random.Random):
    """Un flux qui rend toujours 0,5 : facteur 1,0, aucun bruit d'altitude."""

    def random(self) -> float:
        return 0.5


START = datetime(2026, 11, 10, 8, tzinfo=UTC)


def _second_way_s(name: str, loop: str) -> float:
    """La durée par une seconde voie : la somme, par pas de 1 m, de 1 / vitesse."""
    found = route(loop)
    person = character(name)
    return sum(
        1 / true_speed_ms(person, grade_at(found, float(s)))
        for s in range(round(length_m(found)))
    )


def test_simulate_without_noise() -> None:
    loop = route("boucle_roulante")
    outing = simulate(
        character("rouleur"), loop, 1, start=START, stop=False, rng=_Half()
    )
    assert isinstance(outing, Outing)
    assert outing.factor == 1.0
    assert outing.start == START
    assert outing.stop_s == 0
    first, second, last = outing.records[0], outing.records[1], outing.records[-1]
    assert (first.lat, first.lon) == to_lat_lon(*xy_at(loop, 0.0))
    assert (first.elapsed_s, first.altitude_m, first.heart_rate) == (0, 1_100.0, 95.0)
    assert first.speed_ms == pytest.approx(2.75, rel=1e-12)
    assert first.distance_m == 0.0
    assert second.distance_m == pytest.approx(2.75, rel=1e-12)
    assert last.distance_m == 8_100.0
    assert last.altitude_m == pytest.approx(1_100.0, abs=1e-9)
    assert last.elapsed_s == pytest.approx(
        _second_way_s("rouleur", "boucle_roulante"), rel=0.01
    )
    stopped = simulate(
        character("rouleur"), loop, 1, start=START, stop=True, rng=_Half()
    )
    assert stopped.stop_s == 120
    assert stopped.records[-1].elapsed_s == last.elapsed_s + 120


@pytest.mark.parametrize("name", CHARACTER_NAMES)
@pytest.mark.parametrize("reduced", [False, True])
def test_plan(name: str, reduced: bool) -> None:
    person = character(name)
    outings = plan(person, T0, reduced=reduced)
    beginner = name == "debutant"
    count = 12 if beginner else (24 if reduced else 68)
    assert len(outings) == count
    assert [o.number for o in outings] == list(range(1, count + 1))
    assert [o.stop for o in outings] == [o.number % 3 == 0 for o in outings]
    assert outings[-1].day == date(2026, 11, 11)
    days = 35 if beginner else (42 if reduced else 119)
    assert outings[0].day == T0 - timedelta(days=days)
    for index, outing in enumerate(outings):
        loop, laps = person.week[index % len(person.week)]
        assert outing.loop == loop
        assert outing.laps == (1 if reduced else laps)


def test_every_field_of_a_planned_outing() -> None:
    outing = plan(character("polyvalente"), T0)[1]
    assert isinstance(outing, PlannedOuting)
    assert (outing.number, outing.day, outing.loop, outing.laps, outing.stop) == (
        2,
        date(2026, 7, 19),
        "boucle_roulante",
        2,
        False,
    )


def test_the_witness_of_the_full_polyvalente() -> None:
    """La dernière sortie d'un tour sur la boucle raide : le 2026-11-10 (k = 116)."""
    person = character("polyvalente")
    last = [
        o for o in plan(person, T0) if o.loop == person.witness_loop and o.laps == 1
    ][-1]
    assert f"sortie_{last.day.isoformat()}_{last.loop}.gpx" == (
        "sortie_2026-11-10_boucle_raide.gpx"
    )
