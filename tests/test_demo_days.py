"""Les jours des profils de démo (M5-3, § 6.5 du brief) : les onze familles et le
journal, passés par la vraie chaîne (``ingest``, ``tables``, ``q1``) sur la version
réduite de chaque personnage (``tests/demo_world.py``), et une version complète de la
polyvalente, jours seuls ; ``day_values`` contre les littéraux du brief."""

from __future__ import annotations

import contextlib
import io
import json
import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from demo_world import COMMIT, T0, DemoBuild, built
from mountain_perf import gitstate
from mountain_perf.analyse.normals import NormalMeasure
from mountain_perf.cli import main
from mountain_perf.config import DATA_DIR_ENV_VAR
from mountain_perf.demo import jours
from mountain_perf.demo.constantes import CHARACTER_NAMES
from mountain_perf.demo.jours import DayValues, day_values, write_days, write_journal
from mountain_perf.demo.personnages import character
from mountain_perf.demo.sorties import export_dir, plan, write_acquisition
from mountain_perf.gitstate import GitState
from mountain_perf.ingest.interim import read_days_report
from mountain_perf.schemas import AdmissionRefusal, DayRow, JournalEventType

pytest.importorskip("fitdecode")
pytest.importorskip("pyarrow")

from mountain_perf.analyse.parquet import read_tables

VALUE_FIELDS = (
    "hrv_last_night_avg_ms",
    "resting_hr_bpm",
    "measured_sleep_s",
    "night_avg_stress",
    "respiration_avg_sleep_breaths_per_min",
    "spo2_avg_sleep_percent",
)
"""Les six colonnes de ``DayRow`` des mesures, dans l'ordre de ``NormalMeasure``."""

UNITS = ("_ms", "_bpm", "_s", "", "_breaths_per_min", "_percent")
"""Le suffixe d'unité des colonnes de plage de chaque mesure."""

ILLNESS = {T0 - timedelta(days=n) for n in (29, 28, 27)}
ALTITUDE = {T0 - timedelta(days=n) for n in (20, 19, 18, 17)}
RACE = T0 - timedelta(days=14)
UNCERTAIN = T0 - timedelta(days=11)
RUPTURE = T0 - timedelta(days=10)
NO_SPO2 = {T0 - timedelta(days=6), T0 - timedelta(days=5)}
LAST = T0 - timedelta(days=1)


def _days(build: DemoBuild) -> list[DayRow]:
    return list(read_tables(build.folder).days)


def _after_two_laps(name: str, reduced: bool) -> set[date]:
    return {
        o.day + timedelta(days=1)
        for o in plan(character(name), T0, reduced=reduced)
        if o.laps == 2
    }


@pytest.mark.parametrize("name", CHARACTER_NAMES)
def test_the_ingestion_of_the_days(
    name: str, tmp_path_factory: pytest.TempPathFactory
) -> None:
    lines = built(name, tmp_path_factory).outputs["ingest"].splitlines()
    assert "Fichiers journaliers refusés : 0" in lines
    count = 35 if name == "debutant" else 42
    assert f"  complete : {count} jour(s)" in lines


@pytest.mark.parametrize("name", CHARACTER_NAMES)
def test_the_table_carries_the_day_values(
    name: str, tmp_path_factory: pytest.TempPathFactory
) -> None:
    rows = _days(built(name, tmp_path_factory))
    values = day_values(character(name), T0, reduced=True)
    assert [row.day for row in rows] == sorted(values)
    for row in rows:
        expected = values[row.day]
        for field in VALUE_FIELDS:
            found, wanted = getattr(row, field), getattr(expected, field)
            if wanted is None:
                assert found is None, (row.day, field)
            else:
                assert found == pytest.approx(wanted), (row.day, field)


@pytest.mark.parametrize("name", CHARACTER_NAMES)
def test_refusals(name: str, tmp_path_factory: pytest.TempPathFactory) -> None:
    """``illness`` aux six mesures les jours de maladie, ``altitude_stay`` les jours du
    séjour, ``no_value`` à la SpO2 les deux nuits sans valeur, et aucun autre."""
    for row in _days(built(name, tmp_path_factory)):
        for measure in NormalMeasure:
            refusal = getattr(row, f"{measure.value}_refusal")
            expected: AdmissionRefusal | None = None
            if row.day in ILLNESS:
                expected = AdmissionRefusal.ILLNESS
            elif row.day in ALTITUDE:
                expected = AdmissionRefusal.ALTITUDE_STAY
            elif measure is NormalMeasure.NIGHT_SPO2 and row.day in NO_SPO2:
                expected = AdmissionRefusal.NO_VALUE
            assert refusal is expected, (row.day, measure)


@pytest.mark.parametrize("name", CHARACTER_NAMES)
def test_the_journal_types(name: str, tmp_path_factory: pytest.TempPathFactory) -> None:
    for row in _days(built(name, tmp_path_factory)):
        expected: tuple[JournalEventType, ...] = ()
        if row.day in ILLNESS:
            expected = (JournalEventType.ILLNESS,)
        elif row.day in ALTITUDE:
            expected = (JournalEventType.ALTITUDE_STAY,)
        elif row.day == RACE:
            expected = (JournalEventType.RACE,)
        assert row.journal_types == expected, row.day


@pytest.mark.parametrize("name", CHARACTER_NAMES)
def test_rupture_and_uncertain_day(
    name: str, tmp_path_factory: pytest.TempPathFactory
) -> None:
    for row in _days(built(name, tmp_path_factory)):
        assert row.uncertain_device is (row.day == UNCERTAIN), row.day
        for measure in NormalMeasure:
            assert getattr(row, f"{measure.value}_rupture") is (row.day == RUPTURE), (
                row.day,
                measure,
            )


@pytest.mark.parametrize("name", CHARACTER_NAMES)
def test_a_normal_on_the_last_day(
    name: str, tmp_path_factory: pytest.TempPathFactory
) -> None:
    (last,) = [r for r in _days(built(name, tmp_path_factory)) if r.day == LAST]
    for measure in NormalMeasure:
        assert getattr(last, f"{measure.value}_normal_absence") is None, measure


@pytest.mark.parametrize("name", CHARACTER_NAMES)
def test_one_activity_without_load(
    name: str, tmp_path_factory: pytest.TempPathFactory
) -> None:
    outings = plan(character(name), T0, reduced=True)
    penultimate = outings[-2].day
    for row in _days(built(name, tmp_path_factory)):
        assert row.activities_without_load == (1 if row.day == penultimate else 0)


@pytest.mark.parametrize("name", CHARACTER_NAMES)
def test_the_days_report(name: str, tmp_path_factory: pytest.TempPathFactory) -> None:
    """Chaque copie suit sa valeur ; l'égalité de la nuit tient chaque jour, nuit du
    2026-10-25 comprise."""
    folder = built(name, tmp_path_factory).folder
    report = read_days_report(folder)
    assert report.copy_disagreements == ()
    path = folder / "interim" / "days" / "report.json"
    data: dict[str, Any] = json.loads(path.read_bytes().decode("utf-8"))["data"]
    assert data["copy_disagreements"] == []
    assert data["night_equality_violations"] == 0


def test_the_readiness_copies_follow_their_value(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """La HRV hebdomadaire de Training Readiness (``hrvWeeklyAverage``) suit celle du
    résumé HRV : aucune copie antérieure ne diffère."""
    report = read_days_report(built("debutant", tmp_path_factory).folder)
    assert report.readiness_prior_copies
    for count in report.readiness_prior_copies:
        assert count.differing == 0, count


def test_the_weekly_hrv_is_the_normal(tmp_path_factory: pytest.TempPathFactory) -> None:
    rows = _days(built("debutant", tmp_path_factory))
    assert rows
    for row in rows:
        assert row.hrv_weekly_avg_ms == 55, row.day


def test_the_waking_readiness_is_kept(tmp_path_factory: pytest.TempPathFactory) -> None:
    """La Training Readiness du réveil est retenue chaque jour."""
    rows = _days(built("debutant", tmp_path_factory))
    assert rows
    for row in rows:
        assert row.readiness_absence is None, (row.day, row.readiness_absence)
        assert row.readiness_score is not None, row.day


@pytest.mark.parametrize("name", CHARACTER_NAMES)
def test_the_climbs_have_their_heart_rate(
    name: str, tmp_path_factory: pytest.TempPathFactory
) -> None:
    climbs = read_tables(built(name, tmp_path_factory).folder).climbs
    assert climbs
    for climb in climbs:
        assert climb.lagged_moving_heart_rate_coverage >= 0.99


def _shown(output: str, panel: str) -> int:
    lines = output.splitlines()
    start = lines.index("Vue principale :")
    for line in lines[start + 1 :]:
        if line.startswith(f"  {panel} : "):
            return int(line.split(" : ")[1].split(" ")[0])
    raise AssertionError(panel)


@pytest.mark.parametrize("name", CHARACTER_NAMES)
def test_the_q1_points(name: str, tmp_path_factory: pytest.TempPathFactory) -> None:
    output = built(name, tmp_path_factory).outputs["q1"]
    if name in ("polyvalente", "grimpeur", "moyen"):
        assert _shown(output, "long_climb") >= 1
    if name in ("polyvalente", "moyen", "rouleur", "debutant"):
        assert _shown(output, "short_climb") >= 1


# --- La version complète de la polyvalente, jours seuls -------------------------------


@dataclass(frozen=True)
class Full:
    rows: list[DayRow]


@pytest.fixture(scope="module")
def full(tmp_path_factory: pytest.TempPathFactory) -> Full:
    """La polyvalente complète, jours seuls : l'instant d'acquisition, les onze
    familles, le journal, un index vide ; puis ``ingest`` et ``tables``."""
    folder = tmp_path_factory.mktemp("demo_full")
    person = character("polyvalente")
    write_acquisition(folder, T0)
    write_days(person, folder, T0)
    write_journal(person, folder, T0)
    index = export_dir(folder) / "activities" / "activities.json"
    index.parent.mkdir(parents=True)
    index.write_bytes(b"[]")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(DATA_DIR_ENV_VAR, str(folder))
        patch.setattr(gitstate, "git_state", lambda directory: GitState(COMMIT, False))
        with contextlib.redirect_stdout(io.StringIO()):
            assert main(["ingest"]) == 0
            assert main(["tables"]) == 0
    return Full(list(read_tables(folder).days))


def test_the_full_version_has_its_normals(full: Full) -> None:
    window = {T0 - timedelta(days=n) for n in range(5, 30)}
    for row in full.rows:
        if row.day in window:
            for measure in NormalMeasure:
                absence = getattr(row, f"{measure.value}_normal_absence")
                assert absence is None, (row.day, measure)


def test_ordinary_days_leave_their_range(full: Full) -> None:
    after = _after_two_laps("polyvalente", reduced=False)
    for measure, field, unit in zip(NormalMeasure, VALUE_FIELDS, UNITS, strict=True):
        outside = 0
        for row in full.rows:
            value = getattr(row, field)
            ordinary = (
                getattr(row, f"{measure.value}_admitted")
                and getattr(row, f"{measure.value}_normal_absence") is None
                and row.day not in after
            )
            if not ordinary or value is None:
                continue
            low = getattr(row, f"{measure.value}_range_low{unit}")
            high = getattr(row, f"{measure.value}_range_high{unit}")
            if value < low or value > high:
                outside += 1
        assert outside >= 1, measure


# --- day_values contre les littéraux ------------------------------------------------

AMPLITUDES = (4.0, 3.0, 1_200.0, 3.0, 2.0, 2.0)
NORMALS = (55.0, 48.0, 24_000.0, 15.0, 14.0, 95.0)


def _versions() -> list[tuple[dict[date, DayValues], set[date]]]:
    person = character("polyvalente")
    return [
        (day_values(person, T0, reduced=True), set()),
        (day_values(person, T0), _after_two_laps("polyvalente", reduced=False)),
    ]


def test_day_values_ordinary() -> None:
    for values, after in _versions():
        for found in values.values():
            assert found.measured_sleep_s <= 27_000
            assert found.measured_sleep_s % 60 == 0
        ordinary = [
            v
            for d, v in values.items()
            if d not in ILLNESS | ALTITUDE | after | NO_SPO2
        ]
        assert ordinary
        for field, normal, amplitude in zip(
            VALUE_FIELDS, NORMALS, AMPLITUDES, strict=True
        ):
            seen = [getattr(v, field) for v in ordinary]
            assert all(abs(x - normal) <= amplitude + 1e-9 for x in seen), field
            assert abs(statistics.fmean(seen) - normal) <= amplitude / 2, field


def test_day_values_illness() -> None:
    for values, _ in _versions():
        for day in ILLNESS:
            v = values[day]
            assert v.hrv_last_night_avg_ms <= 39
            assert v.resting_hr_bpm >= 53
            assert v.measured_sleep_s >= 24_600
            assert v.night_avg_stress >= 27
            assert v.respiration_avg_sleep_breaths_per_min >= 15.0
            assert v.spo2_avg_sleep_percent is not None
            assert v.spo2_avg_sleep_percent <= 93


def test_day_values_altitude() -> None:
    for values, _ in _versions():
        for day in ALTITUDE:
            v = values[day]
            assert v.resting_hr_bpm >= 51
            assert v.spo2_avg_sleep_percent is not None
            assert v.spo2_avg_sleep_percent <= 92


def test_day_values_after_two_laps() -> None:
    values, after = _versions()[1]
    assert after
    for day in after & set(values):
        v = values[day]
        assert v.hrv_last_night_avg_ms <= 51, day
        assert v.resting_hr_bpm >= 50, day
        assert v.night_avg_stress >= 17, day


def test_day_values_spo2_missing() -> None:
    for values, _ in _versions():
        for day, v in values.items():
            assert (v.spo2_avg_sleep_percent is None) is (day in NO_SPO2), day


@pytest.mark.parametrize("name", CHARACTER_NAMES)
def test_the_spo2_is_drawn_even_without_value(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un tirage par mesure et par jour, même les nuits où la SpO2 écrite est
    ``null`` : sans ces nuits, aucune autre valeur d'aucun jour ne change."""
    person = character(name)
    written = jours.day_values(person, T0)
    monkeypatch.setattr(jours, "SPO2_MISSING_FROM_T0", ())
    every = jours.day_values(person, T0)
    assert sorted(written) == sorted(every)
    for day, value in written.items():
        for field in VALUE_FIELDS[:-1]:
            assert getattr(value, field) == getattr(every[day], field), (day, field)
        if value.spo2_avg_sleep_percent is not None:
            assert value.spo2_avg_sleep_percent == every[day].spo2_avg_sleep_percent


def test_every_field_of_day_values() -> None:
    v = DayValues(55.0, 48.0, 24_000.0, 15.0, 14.0, None)
    assert (
        v.hrv_last_night_avg_ms,
        v.resting_hr_bpm,
        v.measured_sleep_s,
        v.night_avg_stress,
        v.respiration_avg_sleep_breaths_per_min,
        v.spo2_avg_sleep_percent,
    ) == (55.0, 48.0, 24_000.0, 15.0, 14.0, None)
    values = day_values(character("debutant"), T0)
    assert min(values) == date(2026, 10, 9)
    assert max(values) == LAST


def test_the_journal(tmp_path: Path) -> None:
    write_journal(character("moyen"), tmp_path, T0)
    assert (tmp_path / "journal.csv").read_bytes() == (
        "debut;fin;type;note\n"
        "2026-10-15;2026-10-17;maladie;inventé (démo)\n"
        "2026-10-24;2026-10-27;sejour_altitude;inventé (démo)\n"
        "2026-10-30;2026-10-30;course;inventé (démo)\n"
    ).encode()
