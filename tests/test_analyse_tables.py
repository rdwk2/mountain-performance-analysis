"""Les tables ``activites`` et ``montees`` calculées depuis ``interim/``
(``mountain_perf.analyse.tables``, ``docs/decisions/0014``), sur un ``interim/``
synthétique (``tests/fixtures/processed.py``)."""

from __future__ import annotations

import dataclasses
import hashlib
import math
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from fixtures.day_table import definition, index_entry, index_of
from fixtures.days import (
    EXPORT_B,
    days_report,
    export_report,
    read_name,
)
from fixtures.days import day_record as complete_day
from fixtures.montees import FLAT, climb_at, recording
from fixtures.processed import COMMIT, write_days_interim, write_interim, write_one
from mountain_perf.analyse import days as days_module
from mountain_perf.analyse import tables as tables_module
from mountain_perf.analyse.athlete import DEFAULT_SETTINGS, AthleteSettings
from mountain_perf.analyse.climbs import (
    CLIMB_PARAMETER_SPECS,
    climbs,
    motion_track,
    track_route,
)
from mountain_perf.analyse.days import DEFAULT_DAY_DEFINITION
from mountain_perf.analyse.journal import JOURNAL_FILE, JournalError
from mountain_perf.analyse.quality import QUALITY_PARAMETER_SPECS
from mountain_perf.analyse.stability import stability, variant_climbs
from mountain_perf.analyse.tables import (
    DAYS_INTERIM,
    DEFAULT_DEFINITION,
    STALE_INTERIM,
    DaySummary,
    Tables,
    TablesError,
    _gaps,
    _timer_stops,
    build_tables,
    interim_days_sha256,
    interim_sha256,
)
from mountain_perf.gpx.geo import haversine_m
from mountain_perf.gpx.profile import (
    PROFILE_PARAMETER_SPECS,
    build_profile_with_diagnostics,
)
from mountain_perf.ingest.interim import ACTIVITIES_DIR, DAYS_DIR, write_activities
from mountain_perf.schemas import (
    CENTRAL_CONVENTION_INDEX,
    ActivityRecording,
    ContractError,
    DayFamily,
    HeartRateChannel,
    IntervalState,
    JournalEventType,
    ParameterSet,
    ReadFile,
    Sport,
    TemperatureChannel,
    TimerEvent,
    TimerEventType,
    TimerTrigger,
    ViewRefusal,
)
from mountain_perf.schemas.processed import (
    JOURNAL_ABSENT,
    AdmissionRefusal,
    ClimbFlag,
    ClimbRegime,
    DayRowState,
)
from test_ingest_interim import REPORT


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("donnees")
    write_interim(folder)
    return folder


@pytest.fixture(scope="module")
def tables(data_dir: Path) -> Tables:
    return build_tables(data_dir, DEFAULT_SETTINGS, commit=COMMIT)


def test_one_activity_row_per_index_entry_in_index_order(tables: Tables) -> None:
    assert [a.activity_ref for a in tables.activities] == ["a1", "a2", "a3", "a4"]


def test_activities_without_track_or_recording(tables: Tables) -> None:
    a3, a4 = tables.activities[2], tables.activities[3]
    assert a3.has_recording is True
    assert a3.has_track is False
    assert a3.session_count == 1
    assert a3.moving_s_by_convention is None
    assert a4.has_recording is False
    assert a4.session_count is None
    assert a4.sport is None
    assert a4.view_refusal is ViewRefusal.NO_SPORT


def test_climbs_in_time_order_with_ranks_from_one(tables: Tables) -> None:
    a1 = [c for c in tables.climbs if c.activity_ref == "a1"]
    assert [c.rank for c in a1] == [1, 2]
    assert a1[0].start_offset_s < a1[1].start_offset_s


def test_regimes_and_counts(tables: Tables) -> None:
    short, long = (c for c in tables.climbs if c.activity_ref == "a1")
    assert short.regime is ClimbRegime.SHORT_CLIMB
    assert long.regime is ClimbRegime.LONG_CLIMB
    (ski,) = (c for c in tables.climbs if c.activity_ref == "a2")
    assert ski.regime is ClimbRegime.SKI_TOURING
    a1, a2 = tables.activities[0], tables.activities[1]
    assert (a1.climb_count, a1.short_climb_count, a1.long_climb_count) == (2, 1, 1)
    assert (a2.climb_count, a2.ski_touring_count) == (1, 1)


def test_vertical_speed_of_the_long_climb(tables: Tables) -> None:
    long = [c for c in tables.climbs if c.activity_ref == "a1"][1]
    assert long.vertical_speed_ms is not None
    assert long.vertical_speed_ms * 3600 == pytest.approx(600.0, rel=0.01)
    assert long.sport is Sport.FOOT


def test_barometric_from_the_file_or_the_declaration(data_dir: Path) -> None:
    plain = build_tables(data_dir, DEFAULT_SETTINGS, commit=COMMIT)
    (ski,) = (c for c in plain.climbs if c.activity_ref == "a2")
    assert ski.barometric is False
    assert ClimbFlag.NON_BAROMETRIC in ski.flags
    activities = {a.activity_ref: a for a in plain.activities}
    assert (activities["a1"].barometric, activities["a2"].barometric) == (True, False)
    declared = dataclasses.replace(
        DEFAULT_SETTINGS, barometer_products=frozenset({("garmin", 1)})
    )
    again = build_tables(data_dir, declared, commit=COMMIT)
    (ski,) = (c for c in again.climbs if c.activity_ref == "a2")
    assert ski.barometric is True
    assert {a.activity_ref: a for a in again.activities}["a2"].barometric is True
    assert again.provenance.barometer_products == ("garmin:1",)


def test_the_declared_reference_speed_moves_the_regimes(data_dir: Path) -> None:
    slow = AthleteSettings(300.0 / 3600.0, True, frozenset())
    tables = build_tables(data_dir, slow, commit=COMMIT)
    short, _ = (c for c in tables.climbs if c.activity_ref == "a1")
    assert short.regime is ClimbRegime.INTERMEDIATE  # 60 m > 300 m/h × 5 min = 25 m
    assert tables.provenance.reference_vertical_speed_declared is True


def test_local_start_time_keeps_the_index_offset(tables: Tables) -> None:
    for climb in tables.climbs:
        assert climb.local_start_time.utcoffset() == timedelta(hours=2)


def test_timer_stops_and_heart_rate_inside_the_long_climb(tables: Tables) -> None:
    short, long = (c for c in tables.climbs if c.activity_ref == "a1")
    assert (long.timer_stop_count, long.auto_pause_count) == (1, 1)
    assert (short.timer_stop_count, short.auto_pause_count) == (0, 0)
    assert long.moving_mean_heart_rate_bpm == pytest.approx(140.0)
    assert long.moving_heart_rate_coverage == pytest.approx(1.0)
    assert long.second_half_mean_heart_rate_bpm == pytest.approx(140.0)
    assert long.moving_mean_temperature_c == pytest.approx(12.0)
    (ski,) = (c for c in tables.climbs if c.activity_ref == "a2")
    assert ski.moving_mean_heart_rate_bpm is None
    assert ski.moving_heart_rate_coverage == 0.0


def test_preceding_ascent_and_moving_time(tables: Tables) -> None:
    short, long = (c for c in tables.climbs if c.activity_ref == "a1")
    assert short.preceding_ascent_m == pytest.approx(0.0, abs=2.0)
    # D+ et D− du profil lissé : la pointe de la côte de 60 m y est rabotée.
    assert 50.0 < long.preceding_ascent_m < 60.0
    assert 50.0 < long.preceding_descent_m < 60.0
    assert long.preceding_moving_s > short.preceding_moving_s


def test_the_provenance(data_dir: Path, tables: Tables) -> None:
    provenance = tables.provenance
    assert provenance.interim_sha256 == interim_sha256(data_dir)
    assert provenance.commit == COMMIT
    assert (
        provenance.activity_count,
        provenance.climb_count,
        provenance.variant_climb_count,
    ) == (4, 3, 36)
    names = [name for name, _ in provenance.parameters]
    assert names == sorted(names)
    assert ("climb.min_gain_m", 20.0) in provenance.parameters
    assert provenance.parameters == tuple(
        sorted((*DEFAULT_DEFINITION.items(), *DEFAULT_DAY_DEFINITION.items()))
    )
    assert len(names) == len(DEFAULT_DEFINITION.items()) + len(
        DEFAULT_DAY_DEFINITION.items()
    )
    assert {name.split(".")[0] for name in names} == {
        "climb",
        "days",
        "normal",
        "profile",
        "quality",
        "regimes",
        "stability",
    }
    for published in (
        ("profile.grid_step_m", 50.0),
        ("quality.max_sinuosity", 6.0),
        ("regimes.short_climb_max_duration_s", 300.0),
        ("stability.min_jaccard", 0.5),
    ):
        assert published in provenance.parameters


def test_the_defaults_are_those_of_the_decision() -> None:
    """Constat 4 de la relecture de la PR #31 : chaque défaut de la définition, tel
    que ``0014`` (et ``0008`` pour le profil) l'écrit ; la provenance les porte tous."""
    assert dict(DEFAULT_DEFINITION.items()) == {
        "climb.bound_tolerance_m": 1.0,
        "climb.flat_grade": 0.02,
        "climb.flat_length_m": 250.0,
        "climb.flat_time_ratio": 0.10,
        "climb.hysteresis_m": 10.0,
        "climb.max_sustained_vertical_speed_ms": 2000 / 3600,
        "climb.min_climb_steps": 30.0,
        "climb.min_gain_m": 20.0,
        "climb.min_grade": 0.05,
        "climb.min_profile_gain_fraction": 0.5,
        "climb.slow_max_horizontal_speed_ms": 0.30,
        "climb.slow_max_vertical_speed_ms": 0.03,
        "profile.grid_step_m": 50.0,
        "profile.point_match_max_offset_m": 150.0,
        "profile.point_match_min_separation_m": 500.0,
        "profile.smoothing_window_m": 150.0,
        "quality.loop_closure_distance_m": 50.0,
        "quality.max_foot_horizontal_speed_ms": 10.0,
        "quality.max_human_vertical_speed_ms": 3000 / 3600,
        "quality.max_loop_closure_rate_ms": 5 / 3600,
        "quality.max_outside_moving_gain_fraction": 0.20,
        "quality.max_record_vertical_rate_ms": 3.0,
        "quality.max_sinuosity": 6.0,
        "quality.max_slow_moving_fraction": 0.10,
        "regimes.long_climb_min_duration_s": 900.0,
        "regimes.low_altitude_max_m": 1500.0,
        "regimes.mid_altitude_max_m": 2500.0,
        "regimes.moderate_grade_max": 0.15,
        "regimes.short_climb_max_duration_s": 300.0,
        "regimes.steep_grade_max": 0.30,
        "stability.max_relative_deviation": 0.05,
        "stability.min_found_fraction": 0.80,
        "stability.min_jaccard": 0.5,
    }


def test_a_climb_with_two_flags_lists_them_sorted(tmp_path: Path) -> None:
    """Constat 2 de la relecture de la PR #31 : une montée à 11 m/s à l'horizontale,
    à pied, sans baromètre attesté, porte deux drapeaux, triés."""
    rec = recording(
        [FLAT, climb_at(2376, 0.06, 150), FLAT], noise=False, barometer=False
    )
    write_one(tmp_path, rec)
    (climb,) = build_tables(tmp_path, DEFAULT_SETTINGS, commit=COMMIT).climbs
    assert climb.flags == (ClimbFlag.NON_BAROMETRIC, ClimbFlag.NON_HUMAN)


@pytest.mark.parametrize(
    ("segments", "source_activity_type", "counts"),
    [
        ([FLAT, climb_at(600, 0.15, 60), FLAT], "trail_running", (1, 0, 0, 0, 0, 0)),
        (
            [FLAT, climb_at(2376, 0.06, 150), FLAT],
            "trail_running",
            (0, 1, 0, 0, 0, 0),
        ),
        (
            [FLAT, climb_at(2376, 0.06, 150), FLAT],
            "mountain_biking",
            (0, 0, 0, 0, 0, 1),
        ),
    ],
)
def test_each_regime_count_reads_its_own_regime(
    tmp_path: Path,
    segments: list[tuple[float, float, float]],
    source_activity_type: str,
    counts: tuple[int, ...],
) -> None:
    """Constat 3 de la relecture de la PR #31 : une activité d'une seule montée, une
    côte, une intermédiaire (150 m à pied) ou un autre sport (la même en VTT), la
    compte dans la colonne de son régime et dans aucune autre (côtes, intermédiaires,
    montées longues, ski de randonnée, ski de randonnée court, autres sports)."""
    write_one(tmp_path, recording(segments, noise=False), source_activity_type)
    tables = build_tables(tmp_path, DEFAULT_SETTINGS, commit=COMMIT)
    (activity,) = tables.activities
    assert activity.climb_count == 1
    assert (
        activity.short_climb_count,
        activity.intermediate_count,
        activity.long_climb_count,
        activity.ski_touring_count,
        activity.short_ski_touring_count,
        activity.other_sport_count,
    ) == counts


def test_the_same_interim_gives_the_same_tables(data_dir: Path, tables: Tables) -> None:
    assert build_tables(data_dir, DEFAULT_SETTINGS, commit=COMMIT) == tables


def test_the_interim_fingerprint_follows_the_documents(tmp_path: Path) -> None:
    write_interim(tmp_path)
    before = interim_sha256(tmp_path)
    path = tmp_path / ACTIVITIES_DIR / "report.json"
    path.write_bytes(path.read_bytes() + b" ")
    assert interim_sha256(tmp_path) != before


def test_the_interim_fingerprint_is_the_one_its_docstring_writes(
    tmp_path: Path,
) -> None:
    """SHA-256 des lignes « chemin relatif, tabulation, SHA-256 du document, saut de
    ligne », triées par chemin, mises bout à bout."""
    write_interim(tmp_path)
    root = tmp_path / ACTIVITIES_DIR
    lines = sorted(
        f"{path.relative_to(root).as_posix()}\t"
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}\n"
        for path in root.rglob("*.json")
    )
    assert len(lines) > 2
    expected = hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()
    assert interim_sha256(tmp_path) == expected


def test_the_gaps_of_a_window() -> None:
    """Les trous de la vue qui recoupent une fenêtre, et leur durée dans elle : quatre
    trous de 19, 30, 40 et 20 s, dont le premier et le dernier intervalle ; une
    fenêtre qui dépasse la vue ; une fenêtre qui part juste après un trou, une autre
    au milieu d'un trou."""
    track = motion_track(
        recording(
            [FLAT],
            noise=False,
            gaps=((1.0, 20.0), (200.0, 230.0), (300.0, 340.0), (480.0, 500.0)),
        )
    )
    assert track is not None
    end = track.time_s[-1]
    assert _gaps(track, 0.0, end) == (4, 109.0)
    assert _gaps(track, 0.0, end + 100.0) == (4, 109.0)
    assert _gaps(track, 229.0, 290.0) == (0, 0.0)
    assert _gaps(track, 209.0, 219.0) == (1, 10.0)


def test_the_timer_stops_of_a_closed_window() -> None:
    """Les arrêts du chronomètre de ``[début ; fin]``, bornes comprises, dont ceux de
    la pause automatique ; les reprises n'en sont pas."""
    start, stop, stop_all, stop_disable = (
        TimerEventType.START,
        TimerEventType.STOP,
        TimerEventType.STOP_ALL,
        TimerEventType.STOP_DISABLE,
    )
    manual, auto = TimerTrigger.MANUAL, TimerTrigger.AUTO
    rec = dataclasses.replace(
        recording([FLAT], noise=False),
        timer_events=(
            TimerEvent(0.0, start, manual),
            TimerEvent(100.0, stop, manual),
            TimerEvent(150.0, start, manual),
            TimerEvent(200.0, stop_all, auto),
            TimerEvent(250.0, start, auto),
            TimerEvent(300.0, stop_disable, auto),
        ),
    )
    assert _timer_stops(rec, 100.0, 300.0) == (3, 2)
    assert _timer_stops(rec, 100.5, 299.5) == (1, 1)


def _one(tmp_path: Path, rec: ActivityRecording) -> Tables:
    write_one(tmp_path, rec)
    return build_tables(tmp_path, DEFAULT_SETTINGS, commit=COMMIT)


def test_a_winter_activity(tmp_path: Path) -> None:
    """Une température négative entre dans les deux tables."""
    rec = recording([FLAT, climb_at(600, 0.15, 300), FLAT], activity_ref="w1")
    times = rec.position.time_s if rec.position is not None else ()
    rec = dataclasses.replace(
        rec, temperature=TemperatureChannel(times, tuple(-5.0 for _ in times))
    )
    tables = _one(tmp_path, rec)
    (activity,) = tables.activities
    (climb,) = tables.climbs
    assert activity.mean_temperature_c == pytest.approx(-5.0)
    assert climb.moving_mean_temperature_c == pytest.approx(-5.0)


def test_an_activity_that_never_moves(tmp_path: Path) -> None:
    """Toutes les positions confondues : une vue, sans profil ni montée, au lieu
    d'arrêter le calcul."""
    rec = recording([FLAT], activity_ref="i1")
    assert rec.position is not None
    n = len(rec.position.time_s)
    rec = dataclasses.replace(
        rec,
        position=dataclasses.replace(
            rec.position, latitude_deg=(45.0,) * n, longitude_deg=(6.0,) * n
        ),
    )
    tables = _one(tmp_path, rec)
    (activity,) = tables.activities
    assert activity.has_track is True
    assert (
        activity.profile_distance_m,
        activity.profile_ascent_m,
        activity.profile_descent_m,
        activity.climb_count,
    ) == (0.0, 0.0, 0.0, 0)
    assert tables.climbs == ()


def _loop(closing_descent_m: float) -> ActivityRecording:
    """Un aller-retour : 500 m de plat, une montée de 150 m, une descente de
    ``closing_descent_m`` sur le même chemin, 500 m de plat ; l'arrivée revient au
    départ."""
    segments = [
        FLAT,
        climb_at(600, 0.15, 150),
        (1000.0, -closing_descent_m / 1000.0, 1.5),
        FLAT,
    ]
    rec = recording(segments, noise=False, activity_ref="l1")
    assert rec.position is not None
    scale = 111_320.0 * math.cos(math.radians(45.0))
    turn = 500.0 + 1000.0
    lon = []
    for longitude in rec.position.longitude_deg:
        x = (longitude - 6.0) * scale
        lon.append(6.0 + (x if x <= turn else 2 * turn - x) / scale)
    return dataclasses.replace(
        rec, position=dataclasses.replace(rec.position, longitude_deg=tuple(lon))
    )


@pytest.mark.parametrize(
    ("closing_descent_m", "drift"), [(150.0, False), (140.0, True)]
)
def test_a_loop_and_its_altimetric_drift(
    tmp_path: Path, closing_descent_m: float, drift: bool
) -> None:
    """Une boucle dont l'altitude revient au départ n'a pas de dérive ; s'il manque
    10 m en un peu plus de 40 min, la fermeture dépasse 5 m/h : la dérive marque
    l'activité et ses montées."""
    tables = _one(tmp_path, _loop(closing_descent_m))
    (activity,) = tables.activities
    (climb,) = tables.climbs
    assert activity.loop is True
    assert activity.altimetric_drift is drift
    assert (ClimbFlag.ALTIMETRIC_DRIFT in climb.flags) is drift
    assert activity.closure_elevation_m == pytest.approx(
        150.0 - closing_descent_m, abs=0.5
    )


def test_the_ascent_of_a_climb_lost_in_a_gap_stays_in_the_activity(
    tmp_path: Path,
) -> None:
    """Tout le gain dans un trou de la vue : pas de montée, mais le D+ du canal
    d'altitude pendant le trou reste dans la ligne de l'activité."""
    rec = recording(
        [FLAT, climb_at(600, 0.15, 200), FLAT],
        noise=False,
        activity_ref="t1",
        gaps=((500.0, 1700.0),),
    )
    tables = _one(tmp_path, rec)
    (activity,) = tables.activities
    assert tables.climbs == ()
    assert activity.gap_count == 1
    assert activity.position_gap_ascent_m == pytest.approx(200.0, abs=0.5)


def test_an_activity_that_breaks_a_contract_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Une erreur de contrat arrête le calcul et nomme l'activité en cause."""

    def broken(*args: object, **kwargs: object) -> None:
        raise ContractError("contrat violé")

    monkeypatch.setattr(tables_module, "_track_summary", broken)
    write_interim(tmp_path)
    with pytest.raises(TablesError, match=r"^activité a1 : contrat violé$"):
        build_tables(tmp_path, DEFAULT_SETTINGS, commit=COMMIT)


def test_the_interim_fingerprint_ignores_files_that_are_not_documents(
    tmp_path: Path,
) -> None:
    write_interim(tmp_path)
    before = interim_sha256(tmp_path)
    (tmp_path / ACTIVITIES_DIR / ".DS_Store").write_bytes(b"x")
    (tmp_path / ACTIVITIES_DIR / "recordings" / "Thumbs.db").write_bytes(b"x")
    assert interim_sha256(tmp_path) == before


def test_the_second_half_starts_at_the_half_of_the_moving_time() -> None:
    """La seconde moitié du temps M d'une fenêtre commence à sa moitié exacte :
    l'intervalle qui part à cet instant en fait partie. Dix intervalles M de 1 s, une
    valeur par intervalle (0 à 9) : la moyenne vaut 4,5, celle de la seconde moitié 7
    (5 à 9). Une fenêtre vide n'a ni moyenne ni couverture ; une seconde suffit."""
    track = motion_track(recording([FLAT], noise=False))
    assert track is not None
    window = range(200, 210)
    marks = track.states[CENTRAL_CONVENTION_INDEX]
    assert all(marks[i] is IntervalState.MOVING for i in window)
    assert all(track.time_s[i + 1] - track.time_s[i] == 1.0 for i in window)
    channel = {track.recording_time_s[i]: float(k) for k, i in enumerate(window)}
    start, end = track.time_s[200], track.time_s[210]
    assert tables_module._moving_mean(track, channel, start, end) == (4.5, 1.0)
    second, _ = tables_module._moving_mean(track, channel, start, end, second_half=True)
    assert second == 7.0
    assert tables_module._moving_mean(track, channel, start, start) == (None, 0.0)
    one = tables_module._moving_mean(
        track, channel, track.time_s[205], track.time_s[206]
    )
    assert one == (5.0, 1.0)


@pytest.mark.parametrize(
    ("source_activity_type", "flagged"),
    [("trail_running", True), ("mountain_biking", False)],
)
def test_the_sport_of_the_activity_goes_to_the_flags(
    tmp_path: Path, source_activity_type: str, flagged: bool
) -> None:
    """Une montée à 11 m/s à l'horizontale, sous la VAM maximale (6 % à 2 376 m/h) :
    « non humaine » à pied seulement."""
    rec = recording([FLAT, climb_at(2376, 0.06, 150), FLAT], noise=False)
    write_one(tmp_path, rec, source_activity_type)
    (climb,) = build_tables(tmp_path, DEFAULT_SETTINGS, commit=COMMIT).climbs
    assert (ClimbFlag.NON_HUMAN in climb.flags) is flagged


def test_timer_stops_are_read_on_the_recording_clock(tmp_path: Path) -> None:
    """Les arrêts du chronomètre d'une montée se lisent aux instants de
    l'enregistrement, quand la vue commence tard (301 s après le départ) : un arrêt
    100 s avant la montée n'en est pas, un arrêt 100 s avant sa fin en est."""
    rec = recording(
        [FLAT, climb_at(600, 0.15, 300), FLAT], gaps=[(0.0, 301.0)], noise=False
    )
    assert rec.position is not None
    assert rec.position.time_s[0] == 301.0
    (climb,) = _one(tmp_path / "sans", rec).climbs
    a, b = climb.start_offset_s, climb.end_offset_s
    events = (
        TimerEvent(0.0, TimerEventType.START, TimerTrigger.MANUAL),
        TimerEvent(a - 100.0, TimerEventType.STOP, TimerTrigger.MANUAL),
        TimerEvent(a - 99.0, TimerEventType.START, TimerTrigger.MANUAL),
        TimerEvent(b - 100.0, TimerEventType.STOP, TimerTrigger.AUTO),
        TimerEvent(b - 99.0, TimerEventType.START, TimerTrigger.AUTO),
    )
    stopped = dataclasses.replace(rec, timer_events=events)
    (climb,) = _one(tmp_path / "avec", stopped).climbs
    assert (climb.start_offset_s, climb.end_offset_s) == (a, b)
    assert (climb.timer_stop_count, climb.auto_pause_count) == (1, 1)


@pytest.mark.parametrize(
    ("document", "old", "new", "message"),
    [
        (
            "recordings/a2.json",
            b'"format":2',
            b'"format":9',
            r"^activité a2 : document au format 9, 2 attendu$",
        ),
        (
            "recordings/a2.json",
            b'"time_s":[1.0,2.0,',
            b'"time_s":[1.0,1.0,',
            r"^activité a2 : time_s doit être strictement croissante",
        ),
        (
            "index.json",
            b'"format":2',
            b'"format":9',
            r"^index d'interim/ : document au format 9, 2 attendu$",
        ),
        (
            "index.json",
            b'"activity_ref":"a2"',
            b'"activity_ref":"a1"',
            r"^index d'interim/ : entries : identifiant d'activité répété\.$",
        ),
    ],
)
def test_a_document_that_does_not_read_back_is_named(
    tmp_path: Path, document: str, old: bytes, new: bytes, message: str
) -> None:
    """Un document d'``interim/`` qui ne se relit pas, d'un autre format
    (``CodecError``) ou refusé par un contrat à la relecture (un instant répété, un
    identifiant répété : ``ContractError``) : le calcul s'arrête et nomme l'activité,
    ou l'index. Seule la première occurrence du passage change (un enregistrement en a
    une par canal)."""
    write_interim(tmp_path)
    path = tmp_path / ACTIVITIES_DIR / document
    data = path.read_bytes()
    assert old in data
    path.write_bytes(data.replace(old, new, 1))
    with pytest.raises(TablesError, match=message):
        build_tables(tmp_path, DEFAULT_SETTINGS, commit=COMMIT)


@pytest.mark.parametrize(("margin_m", "loop"), [(0.0, False), (1e-6, True)])
def test_a_loop_closes_strictly_under_its_distance(
    tmp_path: Path, margin_m: float, loop: bool
) -> None:
    """L'arrivée doit être à moins de ``loop_closure_distance_m`` du départ : un
    aller-retour vers le nord-est, qui revient à une trentaine de mètres de son
    départ, n'est pas une boucle quand le seuil vaut exactement cette distance, entre
    le premier et le dernier instant de la vue, et l'est juste au-delà. La fermeture
    altimétrique est celle de l'altitude lissée, entre les mêmes instants (départ et
    arrivée en pente douce : l'altitude y change d'un instant à l'autre)."""
    rec = recording(
        [
            (500.0, 0.02, 1.0),
            climb_at(600, 0.15, 150),
            (1000.0, -0.15, 1.5),
            (470.0, -0.02, 1.0),
        ],
        noise=False,
        activity_ref="b1",
    )
    assert rec.position is not None
    scale = 111_320.0 * math.cos(math.radians(45.0))
    turn = 500.0 + 1000.0
    lat, lon = [], []
    for longitude in rec.position.longitude_deg:
        x = (longitude - 6.0) * scale
        x = x if x <= turn else 2 * turn - x
        lat.append(45.0 + 0.5 * x / 111_320.0)
        lon.append(6.0 + math.sqrt(3.0) / 2.0 * x / scale)
    rec = dataclasses.replace(
        rec,
        position=dataclasses.replace(
            rec.position, latitude_deg=tuple(lat), longitude_deg=tuple(lon)
        ),
    )
    track = motion_track(rec)
    assert track is not None
    closure_m = haversine_m(
        track.latitude_deg[0],
        track.longitude_deg[0],
        track.latitude_deg[-1],
        track.longitude_deg[-1],
    )
    assert 25.0 < closure_m < 35.0
    quality = ParameterSet(
        QUALITY_PARAMETER_SPECS,
        {
            **DEFAULT_DEFINITION.quality.values,
            "loop_closure_distance_m": closure_m + margin_m,
        },
    )
    definition = dataclasses.replace(DEFAULT_DEFINITION, quality=quality)
    write_one(tmp_path, rec)
    (activity,) = build_tables(
        tmp_path, DEFAULT_SETTINGS, definition, commit=COMMIT
    ).activities
    assert activity.loop is loop
    zs = track.smoothed_elevation_m
    assert zs[0] != zs[1]
    assert zs[-1] != zs[-2]
    assert activity.closure_elevation_m == zs[-1] - zs[0]
    assert activity.closure_rate_ms == abs(zs[-1] - zs[0]) / track.time_s[-1]


def test_the_envelope_of_the_vertical_speed(tmp_path: Path) -> None:
    """Un passage de 40 m à 0,12 m/s au milieu d'une montée : en mouvement sous les
    conventions dont le seuil horizontal est plus bas, pas sous celle à 0,15 m/s. Les
    VAM des cinq conventions diffèrent, et la table en garde la plus petite et la plus
    grande."""
    part = climb_at(600, 0.15, 100)
    rec = recording([FLAT, part, (40.0, 0.0, 0.12), part, FLAT], noise=False)
    track = motion_track(rec)
    assert track is not None
    (measure,) = climbs(track)
    envelope = measure.vertical_speed_envelope_ms
    assert envelope is not None
    assert envelope[0] < envelope[1]
    (row,) = _one(tmp_path, rec).climbs
    assert (row.vertical_speed_low_ms, row.vertical_speed_high_ms) == envelope


def test_the_ascent_of_two_position_gaps(tmp_path: Path) -> None:
    """Deux trous de positions de 60 et 90 s pendant une montée à 600 m/h, l'altitude
    continue : le D+ du canal pendant les trous les somme (25 m)."""
    rec = recording([FLAT, climb_at(600, 0.15, 300), FLAT], noise=False)
    assert rec.position is not None
    pos = rec.position
    gaps = ((1000.0, 1060.0), (1500.0, 1590.0))
    keep = [i for i, t in enumerate(pos.time_s) if not any(a < t < b for a, b in gaps)]
    rec = dataclasses.replace(
        rec,
        position=dataclasses.replace(
            pos,
            time_s=tuple(pos.time_s[i] for i in keep),
            latitude_deg=tuple(pos.latitude_deg[i] for i in keep),
            longitude_deg=tuple(pos.longitude_deg[i] for i in keep),
        ),
    )
    (activity,) = _one(tmp_path, rec).activities
    assert activity.gap_count == 2
    assert activity.position_gap_ascent_m == pytest.approx(150 * 600 / 3600, abs=1e-6)


def test_a_track_of_two_points_has_a_profile(tmp_path: Path) -> None:
    """Une vue de deux instants, à 100 m l'un de l'autre : son profil existe, et la
    ligne en porte la longueur."""
    rec = recording([(200.0, 0.1, 100.0 / 600.0)], noise=False, step_s=600.0)
    track = motion_track(rec)
    assert track is not None
    assert len(track.time_s) == 2
    (activity,) = _one(tmp_path, rec).activities
    assert activity.profile_distance_m == pytest.approx(track.distance_m[-1])
    assert activity.profile_distance_m == pytest.approx(100.0, abs=0.5)
    profile = build_profile_with_diagnostics(
        track_route(track), DEFAULT_DEFINITION.profile
    ).profile
    ascent, descent = profile.cumulative_ascent_m, profile.cumulative_descent_m
    assert (activity.profile_ascent_m, activity.profile_descent_m) == (
        ascent[-1],
        descent[-1],
    )
    assert ascent[-1] > ascent[-2]


def test_the_definition_reaches_the_climbs_and_their_variants(tmp_path: Path) -> None:
    """Une définition qui n'est pas celle par défaut (profil au pas de 30 m lissé sur
    90 m ; hystérésis de 25 m, tolérance des bornes de 3 m) : les bornes des montées
    et leur stabilité sont celles de la chaîne et des variantes sous ces paramètres,
    et non sous les défauts."""
    back = (20.0 / 0.1, -0.1, 1.0)
    rec = recording(
        [FLAT, climb_at(600, 0.15, 150), back, climb_at(600, 0.15, 150), FLAT]
    )
    profile = ParameterSet(
        PROFILE_PARAMETER_SPECS,
        {
            **DEFAULT_DEFINITION.profile.values,
            "grid_step_m": 30.0,
            "smoothing_window_m": 90.0,
        },
    )
    climb = ParameterSet(
        CLIMB_PARAMETER_SPECS,
        {
            **DEFAULT_DEFINITION.climb.values,
            "hysteresis_m": 25.0,
            "bound_tolerance_m": 3.0,
        },
    )
    definition = dataclasses.replace(DEFAULT_DEFINITION, profile=profile, climb=climb)
    track = motion_track(rec)
    assert track is not None
    measures = climbs(track, profile, climb)
    variants = variant_climbs(track, profile, climb)
    expected = [
        (
            m.span.start_s,
            m.span.profile_start_m,
            stability(m, variants, DEFAULT_DEFINITION.stability).found_fraction,
            stability(m, variants, DEFAULT_DEFINITION.stability).max_relative_deviation,
        )
        for m in measures
    ]
    default_variants = variant_climbs(track)
    assert expected != [
        (
            m.span.start_s,
            m.span.profile_start_m,
            stability(m, default_variants, DEFAULT_DEFINITION.stability).found_fraction,
            stability(
                m, default_variants, DEFAULT_DEFINITION.stability
            ).max_relative_deviation,
        )
        for m in climbs(track)
    ]
    write_one(tmp_path, rec)
    rows = build_tables(tmp_path, DEFAULT_SETTINGS, definition, commit=COMMIT).climbs
    assert [
        (
            r.start_offset_s - track.offset_s,
            r.profile_start_m,
            r.found_fraction,
            r.max_relative_deviation,
        )
        for r in rows
    ] == expected


def test_the_gaps_and_steps_of_an_activity(tmp_path: Path) -> None:
    """Un trou de 19 s au premier intervalle de la vue, un de 20 s au dernier : la
    ligne les compte tous deux, en entier, et le plus long pas est le dernier."""
    rec = recording([FLAT], noise=False, gaps=((1.0, 20.0), (480.0, 500.0)))
    (activity,) = _one(tmp_path, rec).activities
    assert (activity.gap_count, activity.gap_s) == (2, 39.0)
    assert (activity.step_s, activity.longest_step_s) == (1.0, 20.0)


def test_a_view_shorter_than_a_second_has_its_closure_rate(tmp_path: Path) -> None:
    """Cinq instants, tous les deux dixièmes de seconde, sur une pente : la fermeture
    altimétrique se rapporte à ces 0,8 s."""
    rec = recording([(2.0, 0.5, 2.0)], noise=False, step_s=0.2)
    track = motion_track(rec)
    assert track is not None
    assert len(track.time_s) == 5
    elapsed = track.time_s[-1]
    assert 0.0 < elapsed < 1.0
    (activity,) = _one(tmp_path, rec).activities
    zs = track.smoothed_elevation_m
    assert zs[-1] != zs[0]
    assert activity.closure_rate_ms == abs(zs[-1] - zs[0]) / elapsed


def test_an_unstable_climb_is_counted_once(tmp_path: Path) -> None:
    """Une montée qu'une variante raccourcit (``test_analyse_stability``) : instable,
    elle compte pour une dans l'activité."""
    segments = [FLAT, (300.0, 0.025, 1.0), climb_at(600, 0.15, 100), FLAT]
    tables = _one(tmp_path, recording(segments, noise=False))
    (climb,) = tables.climbs
    assert climb.stable is False
    assert tables.activities[0].unstable_climb_count == 1


def test_the_definition_reaches_the_slow_moving_time(tmp_path: Path) -> None:
    """Les seuils du temps M lent viennent de la définition : un passage de 300 s à
    0,2 m/s au milieu d'une montée est lent par défaut, et ne l'est plus sous un seuil
    horizontal de 0,1 m/s."""
    part = climb_at(600, 0.15, 100)
    rec = recording([FLAT, part, (60.0, 0.0, 0.2), part, FLAT], noise=False)
    climb = ParameterSet(
        CLIMB_PARAMETER_SPECS,
        {**DEFAULT_DEFINITION.climb.values, "slow_max_horizontal_speed_ms": 0.1},
    )
    strict = dataclasses.replace(DEFAULT_DEFINITION, climb=climb)
    write_one(tmp_path, rec)
    (default,) = build_tables(tmp_path, DEFAULT_SETTINGS, commit=COMMIT).climbs
    (row,) = build_tables(tmp_path, DEFAULT_SETTINGS, strict, commit=COMMIT).climbs
    assert default.slow_moving_s > 240.0
    assert row.slow_moving_s < 30.0


# --- la table jours et la provenance étendue (AN2-2) ---------------------------------

EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
ACQUIRED = "2001-12-01T11:00:00+00:00"


def build(folder: Path, **kwargs: Any) -> Tables:
    return build_tables(folder, DEFAULT_SETTINGS, commit=COMMIT, **kwargs)


def test_the_days_table_of_the_synthetic_interim(
    tables: Tables, data_dir: Path
) -> None:
    assert [row.day for row in tables.days] == [date(2000, 1, d) for d in (1, 2, 3, 4)]
    assert tables.days[2].state is DayRowState.ABSENT
    assert tables.day_summary == DaySummary(0, 4, 1, 3, 0, 1)
    assert tables.days[1].ts_status_code == 4
    provenance = tables.provenance
    assert provenance.day_count == 4
    assert provenance.interim_days_sha256 == interim_days_sha256(data_dir)
    assert provenance.interim_days_sha256 != EMPTY_SHA256
    assert provenance.journal_sha256 == JOURNAL_ABSENT
    assert provenance.acquired_at == ACQUIRED


def test_the_fingerprint_of_the_days_follows_the_days(tmp_path: Path) -> None:
    write_interim(tmp_path)
    before = build(tmp_path).provenance
    write_days_interim(tmp_path, [complete_day(date(2000, 1, 1))])
    after = build(tmp_path).provenance
    assert after.interim_days_sha256 != before.interim_days_sha256
    assert after.interim_days_sha256 == interim_days_sha256(tmp_path)
    assert after.interim_sha256 == before.interim_sha256
    assert after.interim_sha256 == interim_sha256(tmp_path)


def test_the_fingerprint_of_an_absent_or_empty_folder(tmp_path: Path) -> None:
    assert interim_days_sha256(tmp_path) == EMPTY_SHA256
    (tmp_path / DAYS_DIR).mkdir(parents=True)
    assert interim_days_sha256(tmp_path) == EMPTY_SHA256


def test_the_fingerprint_of_the_days_is_the_one_its_docstring_writes(
    tmp_path: Path,
) -> None:
    root = tmp_path / DAYS_DIR
    (root / "plus").mkdir(parents=True)
    documents = {
        "2000-01-05.json": b'{"a":1}',
        "2000-01-06.json": b'{"a":2}',
        "training_status.json": b"{}",
        "report.json": b"[]",
        "plus/2000-01-07.json": b"{}",
    }
    for name, data in documents.items():
        (root / name).write_bytes(data)
    (root / ".DS_Store").write_bytes(b"x")
    (root / "notes.txt").write_bytes(b"x")
    lines = sorted(
        f"{name}\t{hashlib.sha256(data).hexdigest()}\n"
        for name, data in documents.items()
    )
    expected = hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()
    assert interim_days_sha256(tmp_path) == expected


def test_the_two_fingerprints_are_separate(tmp_path: Path) -> None:
    write_interim(tmp_path)
    days, activities = interim_days_sha256(tmp_path), interim_sha256(tmp_path)
    (tmp_path / DAYS_DIR / "note.json").write_bytes(b"{}")
    changed = interim_days_sha256(tmp_path)
    assert changed != days
    (tmp_path / DAYS_DIR / "note.json").write_bytes(b"{ }")
    assert interim_days_sha256(tmp_path) != changed
    assert interim_sha256(tmp_path) == activities
    settled = interim_days_sha256(tmp_path)
    report = tmp_path / ACTIVITIES_DIR / "report.json"
    report.write_bytes(report.read_bytes() + b" ")
    assert interim_sha256(tmp_path) != activities
    assert interim_days_sha256(tmp_path) == settled


def _break_index(folder: Path) -> None:
    (folder / ACTIVITIES_DIR / "index.json").write_bytes(b"pas du json")


def test_without_interim_days_nothing_is_read(tmp_path: Path) -> None:
    write_interim(tmp_path)
    shutil.rmtree(tmp_path / DAYS_DIR)
    _break_index(tmp_path)
    with pytest.raises(TablesError) as caught:
        build(tmp_path)
    assert str(caught.value) == STALE_INTERIM
    assert "relancer just process" in STALE_INTERIM
    assert STALE_INTERIM == (
        "interim/days/ manque : interim/ date d'avant AN2-1, ou n'a jamais été écrit : "
        "relancer just process"
    )


def test_an_empty_data_folder(tmp_path: Path) -> None:
    with pytest.raises(TablesError, match=r"^interim/days/ manque"):
        build(tmp_path)


def test_an_interim_days_without_a_document(tmp_path: Path) -> None:
    write_interim(tmp_path)
    write_days_interim(tmp_path, [])
    result = build(tmp_path)
    assert result.days == ()
    assert result.day_summary == DaySummary(4, 0, 2, 0, 0, 0)
    assert result.provenance.day_count == 0
    assert result.provenance.acquired_at == ACQUIRED


def _reformat(path: Path) -> None:
    path.write_bytes(path.read_bytes().replace(b'"format":2', b'"format":9', 1))


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("2000-01-02.json", "document au format 9"),
        ("training_status.json", "document au format"),
        ("report.json", "document au format"),
    ],
)
def test_a_document_of_the_days_that_does_not_read_back(
    tmp_path: Path, name: str, text: str
) -> None:
    write_interim(tmp_path)
    _reformat(tmp_path / DAYS_DIR / name)
    with pytest.raises(TablesError) as caught:
        build(tmp_path)
    assert str(caught.value).startswith(f"{DAYS_INTERIM} : ")
    assert text in str(caught.value)


def test_a_document_of_the_days_refused_by_its_contract(tmp_path: Path) -> None:
    write_interim(tmp_path)
    path = tmp_path / DAYS_DIR / "2000-01-02.json"
    data = path.read_bytes()
    assert b'"sleep_score":80' in data
    path.write_bytes(data.replace(b'"sleep_score":80', b'"sleep_score":800', 1))
    with pytest.raises(TablesError) as caught:
        build(tmp_path)
    assert str(caught.value).startswith("jours d'interim/ : ")
    assert "sleep_score" in str(caught.value)


def test_a_row_that_violates_its_contract_is_named_with_its_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = days_module.activity_columns

    def broken(entries: Any) -> dict[str, Any]:
        return {**real(()), "activity_count": -1}

    monkeypatch.setattr(days_module, "activity_columns", broken)
    write_interim(tmp_path)
    with pytest.raises(TablesError) as caught:
        build(tmp_path)
    assert str(caught.value).startswith("jours d'interim/ : jour 2000-01-01 : ")


def _journal(folder: Path, data: bytes) -> None:
    (folder / JOURNAL_FILE).write_bytes(data)


def test_a_malformed_journal_stops_the_tables(tmp_path: Path) -> None:
    write_interim(tmp_path)
    _journal(tmp_path, b"debut;fin;type\n2000-01-02;2000-01-01;maladie\n")
    with pytest.raises(JournalError) as caught:
        build(tmp_path)
    assert str(caught.value) == "journal.csv, ligne 2 : fin avant debut"


def _no_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(*args: object, **kwargs: object) -> None:
        raise AssertionError("les montées ne doivent pas être calculées")

    monkeypatch.setattr(tables_module, "_track_summary", failing)


def test_the_journal_is_read_before_the_index_and_the_climbs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_interim(tmp_path)
    _journal(tmp_path, b"debut;fin\n")
    _break_index(tmp_path)
    _no_summary(monkeypatch)
    with pytest.raises(JournalError, match="colonne type manquante"):
        build(tmp_path)


def test_the_documents_of_the_days_are_read_before_the_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_interim(tmp_path)
    _reformat(tmp_path / DAYS_DIR / "report.json")
    _break_index(tmp_path)
    _journal(tmp_path, b"debut;fin\n")
    _no_summary(monkeypatch)
    with pytest.raises(TablesError) as caught:
        build(tmp_path)
    assert str(caught.value).startswith("jours d'interim/ : document au format 9")


def test_the_index_is_read_after_the_days_and_the_journal(tmp_path: Path) -> None:
    write_interim(tmp_path)
    _journal(tmp_path, b"debut;fin;type\n")
    _break_index(tmp_path)
    with pytest.raises(TablesError) as caught:
        build(tmp_path)
    assert str(caught.value).startswith("index d'interim/ : ")


def test_the_journal_goes_to_its_days_and_to_the_provenance(tmp_path: Path) -> None:
    write_interim(tmp_path)
    data = b"debut;fin;type;note\n2000-01-02;2000-01-02;maladie;\n"
    _journal(tmp_path, data)
    result = build(tmp_path)
    assert result.provenance.journal_sha256 == hashlib.sha256(data).hexdigest()
    assert result.days[1].journal_types == (JournalEventType.ILLNESS,)
    assert result.days[1].hrv_refusal is AdmissionRefusal.ILLNESS
    assert result.days[0].journal_types == ()


def test_acquired_at_is_the_latest_acquisition_in_utc(tmp_path: Path) -> None:
    write_interim(tmp_path)
    report = days_report(
        exports=(export_report(), export_report(EXPORT_B)),
        read=(
            ReadFile(read_name_sleep(), "a" * 64),
            ReadFile(read_name_sleep(EXPORT_B), "b" * 64),
        ),
    )
    write_days_interim(tmp_path, report=report)
    assert build(tmp_path).provenance.acquired_at == "2001-12-02T11:00:00+00:00"


def read_name_sleep(export: str = "garmin_a") -> str:
    return read_name(DayFamily.SLEEP, export=export)


def test_the_day_definition_goes_to_the_rows_and_the_provenance(tmp_path: Path) -> None:
    write_interim(tmp_path)
    chosen = definition({"min_coverage_fraction": 0.0}, {"exclude_altitude_stay": 0.0})
    result = build(tmp_path, day_definition=chosen)
    assert result.day_summary is not None
    assert result.day_summary.nights_below_body_battery_coverage == 0
    assert result.days[0].night_body_battery_coverage is not None
    found = dict(result.provenance.parameters)
    assert found["days.min_coverage_fraction"] == 0.0
    assert found["normal.exclude_altitude_stay"] == 0.0
    assert found["days.short_sleep_s"] == 14400.0


def test_the_three_tables_read_neither_the_days_nor_the_journal(tmp_path: Path) -> None:
    write_interim(tmp_path)
    first = build(tmp_path)
    write_days_interim(tmp_path, [complete_day(date(2024, 3, 9))])
    _journal(tmp_path, b"debut,fin,type\n2024-03-09,2024-03-12,maladie\n")
    second = build(tmp_path)
    assert second.activities == first.activities
    assert second.climbs == first.climbs
    assert second.variants == first.variants
    assert second.days != first.days


def test_the_activities_of_the_index_go_to_the_row_of_their_day(tmp_path: Path) -> None:
    plus1 = timezone(timedelta(hours=1))
    entries = [
        index_entry("b0", datetime(1999, 12, 31, 23, 30, tzinfo=plus1)),
        index_entry(
            "b1", datetime(2000, 1, 1, 23, 30, tzinfo=plus1), elapsed_duration_s=7200.0
        ),
        index_entry(
            "b2",
            datetime(2000, 1, 4, 9, tzinfo=plus1),
            source_activity_type="road_biking",
            training_load=None,
        ),
        index_entry("b3", datetime(2000, 1, 5, 0, 30, tzinfo=plus1)),
    ]
    write_activities(tmp_path, index_of(entries), [], REPORT)
    write_days_interim(tmp_path)
    result = build(tmp_path)
    assert result.day_summary is not None
    assert result.day_summary.activities_before_first_day == 1
    assert result.day_summary.activities_after_last_day == 1
    first, last = result.days[0], result.days[3]
    assert first.activity_count == 1
    assert first.foot_elapsed_s == 7200.0
    assert first.garmin_training_load == 87.5
    assert last.activity_count == 1
    assert last.other_activity_count == 1
    assert last.garmin_training_load is None
    assert last.other_elapsed_s == 3723.5
    assert [a.activity_ref for a in result.activities] == ["b0", "b1", "b2", "b3"]


def test_a_climb_starts_from_the_origin_of_the_view(tmp_path: Path) -> None:
    """Un enregistrement décalé de 300,5 s, au pas de 2 s, une FC qui varie : le départ
    d'une montée se compte depuis l'origine de la vue, sa FC se lit aux instants de
    l'enregistrement."""
    shift = 300.5
    base = recording([FLAT, climb_at(600, 0.15, 300), FLAT], noise=False, step_s=2.0)
    assert base.position is not None
    assert base.elevation is not None
    times = tuple(t + shift for t in base.position.time_s)
    rec = dataclasses.replace(
        base,
        position=dataclasses.replace(base.position, time_s=times),
        elevation=dataclasses.replace(base.elevation, time_s=times),
        heart_rate=HeartRateChannel(times, tuple(100.0 + t / 50.0 for t in times)),
    )
    write_one(tmp_path, rec)
    (climb,) = build(tmp_path).climbs
    track = motion_track(rec)
    assert track is not None
    assert track.offset_s == 302.5
    (measure,) = climbs(track, DEFAULT_DEFINITION.profile, DEFAULT_DEFINITION.climb)
    assert climb.start_offset_s == track.offset_s + measure.span.start_s
    assert climb.end_offset_s == track.offset_s + measure.span.end_s
    assert 500.0 <= climb.start_offset_s - shift <= 560.0
    assert climb.local_start_time == rec.start_time + timedelta(
        seconds=climb.start_offset_s
    )
    assert climb.local_start_time.utcoffset() == timedelta(hours=2)
    middle = (climb.start_offset_s + climb.end_offset_s) / 2
    assert climb.moving_mean_heart_rate_bpm == pytest.approx(
        100.0 + (middle - 1.0) / 50.0, abs=0.05
    )
    assert climb.moving_heart_rate_coverage == pytest.approx(1.0, rel=1e-6)
