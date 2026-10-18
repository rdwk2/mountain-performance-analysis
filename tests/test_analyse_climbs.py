"""La chaîne de la montée (``mountain_perf.analyse.climbs``, ``docs/decisions/0014``),
sur des enregistrements synthétiques (``tests/fixtures/montees.py``).

Les valeurs attendues sont écrites en dur : un tronçon de pente ``p`` parcouru à la
vitesse horizontale ``v`` monte à la VAM vraie ``p × v`` ; sans bruit, la chaîne doit
la retrouver exactement, et avec le bruit du fixture à 1 % près."""

from __future__ import annotations

import dataclasses
import math
from typing import Any

import pytest

from fixtures.montees import FLAT, climb_at, recording
from mountain_perf.analyse.climbs import (
    CLIMB_PARAMETER_SPECS,
    ClimbMeasure,
    ClimbSpan,
    MotionTrack,
    _moving_s,
    _Piece,
    _profile_bounds,
    _settle,
    _time_bounds,
    _zigzag,
    climbs,
    detect_climbs,
    interpolate,
    measure_climb,
    motion_track,
    state_gain_m,
    state_time_s,
    track_route,
)
from mountain_perf.clocks import clock_partition, cumulative_s, window_measures
from mountain_perf.gpx.geo import deduplicated_polyline, haversine_m
from mountain_perf.gpx.profile import (
    PROFILE_PARAMETER_SPECS,
    build_profile_with_diagnostics,
)
from mountain_perf.schemas import (
    CENTRAL_CONVENTION_INDEX,
    CLOCK_CONVENTIONS,
    ActivityRecording,
    IntervalState,
    ParameterSet,
    RecordedTrace,
    Route,
)
from mountain_perf.series import build_series


def _climbs(
    segments: list[tuple[float, float, float]], **options: Any
) -> tuple[ClimbMeasure, ...]:
    track = motion_track(recording(segments, **options))
    assert track is not None
    return climbs(track)


def _vam_m_per_h(measure: ClimbMeasure) -> float:
    vam = measure.vertical_speed_ms
    assert vam is not None
    return vam * 3600.0


def test_a_regular_climb_without_noise_is_exact() -> None:
    (measure,) = _climbs([FLAT, climb_at(600, 0.15, 300), FLAT], noise=False)
    assert measure.span.gain_m == pytest.approx(300.0, abs=1e-6)
    assert _vam_m_per_h(measure) == pytest.approx(600.0, rel=1e-6)
    assert measure.grade == pytest.approx(0.15, rel=2e-3)


def test_a_regular_climb_with_noise_is_one_climb_within_one_percent() -> None:
    (measure,) = _climbs([FLAT, climb_at(600, 0.15, 300), FLAT])
    assert measure.span.gain_m == pytest.approx(300.0, abs=2.0)
    assert _vam_m_per_h(measure) == pytest.approx(600.0, rel=0.01)


@pytest.mark.parametrize("gain_m", [30.0, 50.0, 100.0])
def test_a_short_pointed_climb_keeps_its_vertical_speed(gain_m: float) -> None:
    """C2 : bornes et gain lus en temps sur ``z̃`` ; une côte courte entre deux
    replats n'est ni rabotée par le lissage du profil, ni diluée par les replats."""
    descent = (gain_m / 0.15, -0.15, 1.5)
    (measure,) = _climbs([FLAT, climb_at(600, 0.15, gain_m), descent, FLAT])
    assert _vam_m_per_h(measure) == pytest.approx(600.0, rel=0.02)


@pytest.mark.parametrize("grade", [0.007, 0.01, 0.015, 0.019, -0.019])
@pytest.mark.parametrize("gain_m", [30.0, 150.0])
def test_a_rising_flat_stays_out_of_the_climb(grade: float, gain_m: float) -> None:
    """Constat 1 de la C de la PR #31 : 300 m de replat à ``grade`` de part et d'autre
    d'une côte à 600 m/h, sans bruit. Un replat qui monte de moins de ``flat_grade``
    reste hors de la montée, comme un replat plat ou qui descend : la VAM ne se dilue
    pas. (À 0,5 %, la tolérance lue sur la fenêtre pose déjà la borne à moins d'un pas
    du pied, où le resserrement ne la voit pas : 584 m/h pour la côte de 30 m, la limite
    que dit ``0014``.)"""
    flat = (300.0, grade, 1.0)
    segments = [FLAT, flat, climb_at(600, 0.15, gain_m), flat, FLAT]
    (measure,) = _climbs(segments, noise=False)
    assert _vam_m_per_h(measure) == pytest.approx(600.0, rel=0.015)


@pytest.mark.parametrize("seed", range(8))
def test_a_rising_flat_stays_out_of_a_noisy_climb(seed: int) -> None:
    """La côte de 30 m entre deux replats à 1 %, avec le bruit du fixture : sa VAM est
    celle de la même côte entre deux replats plats, au même bruit, à 1 % près."""

    def vam(grade: float) -> float:
        flat = (300.0, grade, 1.0)
        segments = [FLAT, flat, climb_at(600, 0.15, 30), flat, FLAT]
        (measure,) = _climbs(segments, seed=seed)
        return _vam_m_per_h(measure)

    assert vam(0.01) == pytest.approx(vam(0.0), rel=0.01)


@pytest.mark.parametrize("grade", [0.0, 0.01, 0.015, 0.019])
def test_a_rising_flat_between_two_climbs_cuts(grade: float) -> None:
    """Constat 1, la coupe : deux montées de 150 m (900 s chacune) séparées de 260 m
    de replat parcouru à 1 m/s ; la règle lit le temps du replat entier, même montant
    (260 s, plus du dixième de 900 s), et coupe."""
    climb = climb_at(600, 0.15, 150)
    segments = [FLAT, climb, (260.0, grade, 1.0), climb, FLAT]
    first, second = _climbs(segments, noise=False)
    assert _vam_m_per_h(first) == pytest.approx(600.0, rel=0.015)
    assert _vam_m_per_h(second) == pytest.approx(600.0, rel=0.015)


@pytest.mark.parametrize("grade", [0.0, 0.015, 0.019])
def test_a_merged_climb_leaves_its_rising_flats_out(grade: float) -> None:
    """Une fusion se borne comme un morceau : deux montées de 300 m (1 800 s chacune)
    séparées de 300 m de replat parcouru en 100 s fusionnent (600 m en 3 700 s de
    mouvement), et les replats à ``grade`` qui les bordent restent dehors."""
    flat = (300.0, grade, 1.0)
    part = climb_at(600, 0.15, 300)
    segments = [FLAT, flat, part, (300.0, 0.0, 3.0), part, flat, FLAT]
    (measure,) = _climbs(segments, noise=False)
    assert _vam_m_per_h(measure) == pytest.approx(600 / 3700 * 3600, rel=0.005)


def test_a_rising_flat_reads_the_realized_distance_of_its_step() -> None:
    """Un instant toutes les 5 s : le pas qui suit une borne court jusqu'au premier
    instant à 50 m au moins (jusqu'à 55 m) ; sa pente se lit sur sa distance réalisée,
    pas sur 50 m, sans quoi un replat à 1,9 % monterait d'un pas de plus de 2 % de
    50 m et resterait dans la montée."""
    flat = (300.0, 0.019, 1.0)
    segments = [FLAT, flat, climb_at(600, 0.15, 150), flat, FLAT]
    (measure,) = _climbs(segments, noise=False, step_s=5.0)
    assert _vam_m_per_h(measure) == pytest.approx(600.0, rel=0.03)


def test_a_short_flat_stays_inside_the_climb() -> None:
    flat = (100.0, 0.0, 1.0)
    segments = [FLAT, climb_at(600, 0.15, 150), flat, climb_at(600, 0.15, 150), FLAT]
    (measure,) = _climbs(segments, noise=False)
    assert measure.span.gain_m == pytest.approx(300.0, abs=1e-6)
    # 2 × 900 s de montée et 100 s de replat : 300 m en 1 900 s de mouvement.
    assert _vam_m_per_h(measure) == pytest.approx(300 / 1900 * 3600, rel=0.005)


def test_a_long_flat_cuts_the_climb() -> None:
    flat = (400.0, 0.0, 1.0)
    segments = [FLAT, climb_at(600, 0.15, 150), flat, climb_at(600, 0.15, 150), FLAT]
    first, second = _climbs(segments, noise=False)
    assert first.span.gain_m == pytest.approx(150.0, abs=1e-6)
    assert second.span.gain_m == pytest.approx(150.0, abs=1e-6)
    assert first.span.end_s < second.span.start_s
    assert _vam_m_per_h(first) == pytest.approx(600.0, rel=1e-6)


def test_a_counter_slope_under_the_hysteresis_stays_inside() -> None:
    back = (5.0 / 0.1, -0.1, 1.0)
    segments = [FLAT, climb_at(600, 0.15, 150), back, climb_at(600, 0.15, 150), FLAT]
    (measure,) = _climbs(segments, noise=False)
    assert measure.span.gain_m == pytest.approx(295.0, abs=1e-6)


def test_a_counter_slope_of_the_hysteresis_splits() -> None:
    back = (20.0 / 0.1, -0.1, 1.0)
    segments = [FLAT, climb_at(600, 0.15, 150), back, climb_at(600, 0.15, 150), FLAT]
    assert len(_climbs(segments, noise=False)) == 2


def test_shifting_the_elevation_changes_nothing() -> None:
    segments = [FLAT, climb_at(600, 0.15, 300), FLAT]
    base = _climbs(segments)
    shifted = _climbs(segments, elevation_offset_m=500.0)
    assert [m.span.gain_m for m in shifted] == pytest.approx(
        [m.span.gain_m for m in base]
    )
    assert [m.vertical_speed_ms for m in shifted] == pytest.approx(
        [m.vertical_speed_ms for m in base]
    )


def test_a_gap_leaves_the_principal_vertical_speed_with_its_gain() -> None:
    """C1 : le gain et le temps d'un trou sortent ensemble de la VAM principale."""
    segments = [FLAT, climb_at(600, 0.12, 200), FLAT]
    (measure,) = _climbs(segments, gaps=((1100.0, 1131.0),))
    assert _vam_m_per_h(measure) == pytest.approx(600.0, rel=0.005)
    assert measure.gap_gain_m == pytest.approx(31 * 600 / 3600, abs=1.0)
    k = CENTRAL_CONVENTION_INDEX
    assert measure.undetermined_gain_m[k] >= measure.gap_gain_m - 1e-9


def test_the_minimum_gain_follows_the_recording_step() -> None:
    """``D_min_eff = max(D_min ; 30 × pas × V_haute)`` : au pas de 5 s, 83 m."""
    small = [FLAT, climb_at(600, 0.15, 50), (50 / 0.15, -0.15, 1.5), FLAT]
    large = [FLAT, climb_at(600, 0.15, 120), (120 / 0.15, -0.15, 1.5), FLAT]
    assert _climbs(small, step_s=5.0) == ()
    assert len(_climbs(small, step_s=1.0)) == 1
    (measure,) = _climbs(large, step_s=5.0)
    assert measure.step_s == 5.0


@pytest.mark.parametrize(("grade", "kept"), [(0.048, False), (0.052, True)])
def test_the_minimum_grade_reads_one_support(grade: float, kept: bool) -> None:
    """Sans bruit, une montée régulière a la même pente sur tout support : ``G``,
    pris aux extrêmes, divisé par la longueur entre les bornes, placées à la
    tolérance des extrêmes, la surestimerait et retiendrait la première."""
    segments = [FLAT, climb_at(600, grade, 30), FLAT]
    assert len(_climbs(segments, noise=False)) == (1 if kept else 0)


def test_a_climb_whose_gain_is_in_a_gap_stays_in_the_table() -> None:
    """Le gain d'un trou sort de la VAM principale, pas de la table. Ici, la montée
    raide tombe tout entière dans un trou, entre deux tronçons à 3 % : en M, la pente
    est sous le seuil, mais sur toute la montée, trous compris, elle le passe. La
    montée reste, avec son gain pris hors de M."""
    traverse = (300.0, 0.03, 1.0)
    segments = [FLAT, traverse, climb_at(600, 0.15, 200), traverse, FLAT]
    (measure,) = _climbs(segments, gaps=((800.0, 2000.0),))
    assert measure.grade < 0.05
    assert measure.gap_gain_m == pytest.approx(200.0, abs=3.0)
    outside = measure.outside_moving_gain_fraction
    assert outside is not None
    assert outside > 0.8


def test_the_cumulative_clocks_are_those_of_the_common_module() -> None:
    rec = recording([FLAT, climb_at(600, 0.15, 150), FLAT], stops=((900.0, 990.0),))
    track = motion_track(rec)
    assert track is not None
    trace = RecordedTrace(
        rec.start_time,
        track.time_s,
        track.latitude_deg,
        track.longitude_deg,
        track.elevation_m,
        (rec.source,),
        0,
    )
    partition = clock_partition(trace, build_series(trace))
    for at_s in (0.0, 12.5, 600.0, 901.25, 950.0, track.time_s[-1]):
        for k in range(len(CLOCK_CONVENTIONS)):
            for state in IntervalState:
                expected = cumulative_s(partition, k, {state}, at_s)
                assert state_time_s(track, k, state, 0.0, at_s) == pytest.approx(
                    expected, abs=1e-6
                )


def test_the_gain_clock_sums_to_the_smoothed_rise() -> None:
    rec = recording([FLAT, climb_at(600, 0.15, 150), FLAT], stops=((900.0, 990.0),))
    track = motion_track(rec)
    assert track is not None
    zs = track.smoothed_elevation_m
    a, b = 3, len(track.time_s) - 4
    start, end = track.time_s[a], track.time_s[b]
    for k in range(len(CLOCK_CONVENTIONS)):
        total = math.fsum(
            state_gain_m(track, k, state, start, end) for state in IntervalState
        )
        assert total == pytest.approx(zs[b] - zs[a], abs=1e-9)


def test_no_track_without_elevation() -> None:
    rec = recording([FLAT])
    assert motion_track(rec.__class__(**{**rec.__dict__, "elevation": None})) is None


def test_the_slow_moving_time_follows_its_declared_thresholds() -> None:
    """Le temps M lent : les intervalles M dont la fenêtre va au plus à 0,03 m/s
    verticalement et à 0,30 m/s horizontalement. Un passage de 300 s à 0,2 m/s, sans
    gain, au milieu d'une montée, compte ; à 0,5 m/s, non ; avec un seuil horizontal
    abaissé à 0,1 m/s, non plus."""
    part = climb_at(600, 0.15, 100)
    slow = [FLAT, part, (60.0, 0.0, 0.2), part, FLAT]
    fast = [FLAT, part, (150.0, 0.0, 0.5), part, FLAT]
    (measure,) = _climbs(slow, noise=False)
    assert 240.0 < measure.slow_moving_s <= 300.0
    (measure,) = _climbs(fast, noise=False)
    assert measure.slow_moving_s < 30.0
    strict = ParameterSet(
        CLIMB_PARAMETER_SPECS,
        {
            **ParameterSet(CLIMB_PARAMETER_SPECS).values,
            "slow_max_horizontal_speed_ms": 0.1,
        },
    )
    track = motion_track(recording(slow, noise=False), strict)
    assert track is not None
    (measure,) = climbs(track)
    assert measure.slow_moving_s < 30.0


def test_the_minimum_climb_steps_is_a_parameter() -> None:
    """``D_min_eff`` lit ``min_climb_steps`` : à 10 pas, au pas de 5 s, une côte de
    50 m passe (``10 × 5 × 2 000 m/h`` ≈ 28 m)."""
    small = [FLAT, climb_at(600, 0.15, 50), (50 / 0.15, -0.15, 1.5), FLAT]
    track = motion_track(recording(small, step_s=5.0))
    assert track is not None
    assert climbs(track) == ()
    fewer = ParameterSet(
        CLIMB_PARAMETER_SPECS,
        {**ParameterSet(CLIMB_PARAMETER_SPECS).values, "min_climb_steps": 10.0},
    )
    assert len(climbs(track, None, fewer)) == 1


def test_the_vertical_rate_reads_the_step() -> None:
    """Le plus grand saut d'altitude brute, par seconde : au pas de 2 s, un point de
    la montée relevé de 8 m donne ``(8 + 2 × VAM) / 2``."""
    rec = recording([FLAT, climb_at(600, 0.15, 200), FLAT], noise=False, step_s=2.0)
    assert rec.elevation is not None
    values = list(rec.elevation.elevation_m)
    j = len(values) // 2
    values[j] += 8.0
    rec = dataclasses.replace(
        rec, elevation=dataclasses.replace(rec.elevation, elevation_m=tuple(values))
    )
    track = motion_track(rec)
    assert track is not None
    (measure,) = climbs(track)
    assert measure.max_vertical_rate_ms == pytest.approx((8.0 + 2 * 600 / 3600) / 2)


def test_the_elevations_of_a_regular_climb() -> None:
    """Sans bruit, une montée de 1 000 à 1 300 m : ses altitudes basse et haute, à la
    tolérance des bornes près, et son altitude moyenne en M, au milieu."""
    (measure,) = _climbs([FLAT, climb_at(600, 0.15, 300), FLAT], noise=False)
    assert 1000.0 <= measure.low_elevation_m <= 1001.0 + 1e-9
    assert 1299.0 - 1e-9 <= measure.high_elevation_m <= 1300.0
    assert measure.moving_mean_elevation_m == pytest.approx(1150.0, abs=1.0)


def test_the_sinuosity_of_a_bent_climb() -> None:
    """Une montée qui part vers l'est puis tourne vers le nord, à mi-chemin : la
    longueur parcourue rapportée au déplacement net vaut ``√2``."""
    rec = recording([FLAT, climb_at(600, 0.15, 300), FLAT], noise=False)
    assert rec.position is not None
    scale = 111_320.0 * math.cos(math.radians(45.0))
    x_mid = 500.0 + 1000.0
    lat, lon = [], []
    for longitude in rec.position.longitude_deg:
        x = (longitude - 6.0) * scale
        east, north = min(x, x_mid), max(0.0, x - x_mid)
        lat.append(45.0 + north / 111_320.0)
        lon.append(6.0 + east / scale)
    rec = dataclasses.replace(
        rec,
        position=dataclasses.replace(
            rec.position, latitude_deg=tuple(lat), longitude_deg=tuple(lon)
        ),
    )
    track = motion_track(rec)
    assert track is not None
    (measure,) = climbs(track)
    assert measure.sinuosity == pytest.approx(math.sqrt(2), rel=3e-3)


def test_a_climb_entirely_in_a_gap_is_removed() -> None:
    """Sans aucune longueur parcourue en M (tout le gain dans un trou, entre deux
    replats), il n'y a ni pente en M ni VAM : la montée est écartée."""
    segments = [FLAT, climb_at(600, 0.15, 200), FLAT]
    assert _climbs(segments, noise=False, gaps=((500.0, 1700.0),)) == ()


def test_a_short_steep_counter_slope_is_smoothed_into_the_climb() -> None:
    """L'hystérésis lit le profil lissé : une contre-pente de 15 m à 30 %, sur 50 m,
    y est atténuée sous 10 m, et la montée n'est pas coupée."""
    back = (50.0, -0.30, 1.0)
    segments = [FLAT, climb_at(600, 0.15, 150), back, climb_at(600, 0.15, 150), FLAT]
    assert len(_climbs(segments, noise=False)) == 1


def _with_parameters(**values: float) -> ParameterSet:
    """Les paramètres de la montée par défaut, dont ``values`` remplace certains."""
    return ParameterSet(
        CLIMB_PARAMETER_SPECS,
        {**ParameterSet(CLIMB_PARAMETER_SPECS).values, **values},
    )


@pytest.mark.parametrize(("speed_ms", "count"), [(3.0, 1), (1.0, 2)])
def test_a_long_flat_cuts_only_if_its_moving_time_counts(
    speed_ms: float, count: int
) -> None:
    """Un replat de 300 m, au-delà de la longueur qui en fait un candidat, entre deux
    montées de 300 m (1 800 s chacune) : parcouru en 100 s, son temps en mouvement
    reste sous un dixième de celui du plus court morceau, et la montée n'est pas
    coupée (600 m en 3 700 s de mouvement) ; parcouru en 300 s, il coupe."""
    flat = (300.0, 0.0, speed_ms)
    part = climb_at(600, 0.15, 300)
    found = _climbs([FLAT, part, flat, part, FLAT], noise=False)
    assert len(found) == count
    if count == 1:
        (measure,) = found
        assert measure.span.gain_m == pytest.approx(600.0, abs=1e-6)
        assert _vam_m_per_h(measure) == pytest.approx(600 / 3700 * 3600, rel=1e-3)
    else:
        assert [m.span.gain_m for m in found] == pytest.approx([300.0, 300.0])


def test_the_slow_moving_time_reads_the_vertical_threshold() -> None:
    """Une montée raide et lente : 0,2 m/s à l'horizontale, 0,05 m/s verticalement
    (180 m/h à 25 %). Au seuil vertical de 0,03 m/s, aucun temps M n'est lent ; relevé
    à 0,06 m/s, tout le temps M l'est."""
    segments = [FLAT, climb_at(180, 0.25, 60), FLAT]
    (measure,) = _climbs(segments, noise=False)
    assert measure.slow_moving_s == 0.0
    track = motion_track(
        recording(segments, noise=False),
        _with_parameters(slow_max_vertical_speed_ms=0.06),
    )
    assert track is not None
    (measure,) = climbs(track)
    assert measure.slow_moving_fraction == pytest.approx(1.0)


def test_the_minimum_gain_reads_the_median_step() -> None:
    """Une côte de 40 m dont les instants vont par 1, 1, 1 puis 9 s (sans trou) : le
    pas médian vaut 1 s et le gain minimal 20 m, la côte reste ; le pas moyen, 3 s,
    porterait le gain minimal à 50 m et l'écarterait."""
    segments = [FLAT, climb_at(600, 0.15, 40), (40 / 0.15, -0.15, 1.5), FLAT]
    end_s = 500 + 40 / 0.15 / (600 / 3600 / 0.15) + 40 / 0.15 / 1.5 + 500
    gaps = [(12.0 * k + 3, 12.0 * k + 12) for k in range(int(end_s // 12) + 2)]
    (measure,) = _climbs(segments, noise=False, gaps=gaps)
    assert measure.step_s == 1.0
    assert measure.longest_step_s == 9.0
    assert measure.span.gain_m == pytest.approx(40.0, abs=1.5)


def test_an_elevation_drift_during_a_stop_leaves_the_vertical_speed() -> None:
    """Pendant un arrêt de 600 s au milieu d'une montée, l'altitude dérive de
    0,01 m/s (sous le seuil vertical de θc : l'arrêt reste S). L'horloge du gain voit
    ces quelque 6 m en S ; la VAM principale ne change pas à 0,2 % près, alors que
    compter le gain de S au numérateur l'élèverait de 3 %."""
    segments = [FLAT, climb_at(600, 0.15, 300), FLAT]
    k = CENTRAL_CONVENTION_INDEX
    vams, stopped = [], []
    for drift_ms in (0.0, 0.01):
        rec = recording(segments, noise=False, stops=((1100.0, 1700.0),))
        assert rec.elevation is not None
        z = tuple(
            v + drift_ms * min(max(t - 1100.0, 0.0), 600.0)
            for t, v in zip(
                rec.elevation.time_s, rec.elevation.elevation_m, strict=True
            )
        )
        rec = dataclasses.replace(
            rec, elevation=dataclasses.replace(rec.elevation, elevation_m=z)
        )
        track = motion_track(rec)
        assert track is not None
        (measure,) = climbs(track)
        vams.append(_vam_m_per_h(measure))
        stopped.append(measure.stopped_gain_m[k])
    assert stopped[0] == pytest.approx(0.0, abs=1e-9)
    assert stopped[1] == pytest.approx(6.0, abs=0.5)
    assert vams[1] == pytest.approx(vams[0], rel=2e-3)


@pytest.mark.parametrize(("fraction", "count"), [(0.5, 0), (0.25, 1)])
def test_the_relaxed_detection_reads_its_declared_fraction(
    fraction: float, count: int
) -> None:
    """Une côte de 22 m à 30 % : le profil lissé la rabote sous 10 m, le gain lu en
    temps dépasse 20 m. À une hystérésis de 5 m (la variante ``hysteresis_half``), la
    détection relâchée l'écarte si son gain du profil doit atteindre la moitié du gain
    minimal, et la garde au quart."""
    segments = [FLAT, climb_at(600, 0.30, 22), (22 / 0.30, -0.30, 1.5), FLAT]
    track = motion_track(recording(segments, noise=False))
    assert track is not None
    climb = _with_parameters(hysteresis_m=5.0, min_profile_gain_fraction=fraction)
    found = climbs(track, None, climb)
    assert len(found) == count
    if count:
        assert found[0].span.gain_m >= 20.0


def test_the_moving_mean_elevation_is_weighted_by_time() -> None:
    """Sans bruit, une montée de 1 000 à 1 300 m dont les instants vont par 1 s puis
    par 5 s à partir de son milieu : l'altitude moyenne en M, pondérée par le temps,
    est l'altitude vraie au milieu en temps de la montée, ``1 000 + (t − 500) / 6`` ;
    une moyenne des enregistrements la tirerait vers le bas."""
    gaps = [(float(t), float(t + 5)) for t in range(1400, 2400, 5)]
    rec = recording([FLAT, climb_at(600, 0.15, 300), FLAT], noise=False, gaps=gaps)
    track = motion_track(rec)
    assert track is not None
    (measure,) = climbs(track)
    middle_s = track.offset_s + (measure.span.start_s + measure.span.end_s) / 2
    assert measure.moving_mean_elevation_m == pytest.approx(
        1000.0 + (middle_s - 500.0) / 6.0, abs=0.05
    )


def test_a_track_needs_two_instants() -> None:
    """Une vue d'un seul instant n'a pas de :class:`MotionTrack` ; deux suffisent."""
    assert motion_track(recording([(1.0, 0.0, 1.0)], noise=False)) is None
    track = motion_track(recording([(2.0, 0.0, 1.0)], noise=False))
    assert track is not None
    assert track.time_s == (0.0, 1.0)


def test_the_track_keeps_its_source_and_gives_its_route() -> None:
    rec = recording([FLAT], noise=False)
    track = motion_track(rec)
    assert track is not None
    assert track.source == rec.source
    assert track_route(track) == Route(
        "vue",
        track.latitude_deg,
        track.longitude_deg,
        track.elevation_m,
        (),
        rec.source,
    )


def _north_east(rec: ActivityRecording) -> ActivityRecording:
    """``rec``, dont le parcours vers l'est est tourné vers le nord-est (60° du
    nord) : latitude et longitude changent toutes deux d'un instant à l'autre."""
    assert rec.position is not None
    scale = 111_320.0 * math.cos(math.radians(45.0))
    lat, lon = [], []
    for longitude in rec.position.longitude_deg:
        x = (longitude - 6.0) * scale
        lat.append(45.0 + 0.5 * x / 111_320.0)
        lon.append(6.0 + math.sqrt(3.0) / 2.0 * x / scale)
    return dataclasses.replace(
        rec,
        position=dataclasses.replace(
            rec.position, latitude_deg=tuple(lat), longitude_deg=tuple(lon)
        ),
    )


def test_the_moving_cumulations_advance_on_moving_intervals_only() -> None:
    """Intervalle par intervalle, sur une montée au nord-est à vitesses alternées (1
    puis 3 m/s d'un instant à l'autre), coupée d'un arrêt : la longueur en M avance
    de la distance entre les deux instants de l'intervalle, l'intégrale de ``z̃`` de
    son trapèze, le temps M lent d'un pas ou de rien ; hors de M (θc), aucune
    n'avance."""
    steps = [(1.0, 0.1, 1.0), (3.0, 0.1, 3.0)] * 150
    rec = _north_east(recording([FLAT, *steps, FLAT], stops=((700.0, 760.0),)))
    track = motion_track(rec)
    assert track is not None
    lat, lon, zs = track.latitude_deg, track.longitude_deg, track.smoothed_elevation_m
    moving_count = other_count = 0
    for i, state in enumerate(track.states[CENTRAL_CONVENTION_INDEX]):
        step = track.time_s[i + 1] - track.time_s[i]
        distance = track.moving_distance_m[i + 1] - track.moving_distance_m[i]
        integral = (
            track.moving_elevation_integral[i + 1] - track.moving_elevation_integral[i]
        )
        slow = track.slow_moving_s[i + 1] - track.slow_moving_s[i]
        if state is IntervalState.MOVING:
            moving_count += 1
            expected = haversine_m(lat[i], lon[i], lat[i + 1], lon[i + 1])
            assert distance == pytest.approx(expected, abs=1e-6)
            assert integral == pytest.approx((zs[i] + zs[i + 1]) / 2 * step, abs=1e-6)
            assert slow == pytest.approx(0.0, abs=1e-6) or slow == pytest.approx(step)
        else:
            other_count += 1
            assert (distance, integral, slow) == pytest.approx((0.0, 0.0, 0.0))
    assert moving_count > 500
    assert other_count > 30


def test_the_slow_thresholds_are_inclusive() -> None:
    """Un intervalle M dont la fenêtre va exactement aux deux seuils du temps M lent
    est lent : chaque vitesse est « au plus » son seuil."""
    rec = recording([FLAT, climb_at(180, 0.25, 60), FLAT], noise=False)
    track = motion_track(rec)
    assert track is not None
    trace = RecordedTrace(
        rec.start_time,
        track.time_s,
        track.latitude_deg,
        track.longitude_deg,
        track.elevation_m,
        (rec.source,),
        0,
    )
    i = track.time_s.index(800.0)
    assert track.states[CENTRAL_CONVENTION_INDEX][i] is IntervalState.MOVING
    window = window_measures(trace, build_series(trace), i)
    assert window is not None
    assert window.v_z > 0.0
    assert window.v_h > 0.0
    exact = motion_track(
        rec,
        _with_parameters(
            slow_max_vertical_speed_ms=window.v_z,
            slow_max_horizontal_speed_ms=window.v_h,
        ),
    )
    assert exact is not None
    assert exact.slow_moving_s[i + 1] - exact.slow_moving_s[i] == pytest.approx(1.0)


def test_a_zero_bound_tolerance_puts_the_bounds_on_the_extremes() -> None:
    """À une tolérance des bornes nulle, les bornes sont le dernier minimum et le
    premier maximum, sur le profil comme en temps : sans bruit, de 1 000 à 1 300 m
    exactement, et plus larges qu'à la tolérance par défaut."""
    track = motion_track(recording([FLAT, climb_at(600, 0.15, 300), FLAT], noise=False))
    assert track is not None
    (exact,) = climbs(track, None, _with_parameters(bound_tolerance_m=0.0))
    (default,) = climbs(track)
    assert exact.span.gain_m == pytest.approx(300.0, abs=1e-6)
    assert exact.low_elevation_m == pytest.approx(1000.0, abs=1e-9)
    assert exact.high_elevation_m == pytest.approx(1300.0, abs=1e-9)
    assert exact.span.start_s < default.span.start_s
    assert exact.span.end_s > default.span.end_s


def test_a_second_climb_below_the_first_keeps_its_own_top() -> None:
    """Une montée de 300 m, une descente de 200 m, puis une montée de 150 m : le haut
    de la seconde se cherche dans sa propre fenêtre, pas au sommet de la première,
    plus haut."""
    descent = (200 / 0.15, -0.15, 1.5)
    segments = [FLAT, climb_at(600, 0.15, 300), descent, climb_at(600, 0.15, 150), FLAT]
    first, second = _climbs(segments, noise=False)
    assert first.span.gain_m == pytest.approx(300.0, abs=0.5)
    assert second.span.gain_m == pytest.approx(150.0, abs=0.5)
    assert first.span.end_s < second.span.start_s
    assert _vam_m_per_h(second) == pytest.approx(600.0, rel=1e-6)


def test_interpolate() -> None:
    """Linéaire par intervalle, prolongée par le premier et le dernier intervalle ;
    en une abscisse répétée, la valeur la plus à droite ; un intervalle de longueur
    nulle au bout rend sa valeur de gauche."""
    xs, ys = (0.0, 1.0, 3.0, 4.0), (0.0, 10.0, 0.0, 5.0)
    cases = {0.5: 5.0, 1.0: 10.0, 2.0: 5.0, 3.5: 2.5, -1.0: -10.0, 5.0: 10.0}
    for x, expected in cases.items():
        assert interpolate(xs, ys, x) == pytest.approx(expected), x
    assert interpolate((0.0, 0.0, 1.0), (0.0, 5.0, 10.0), 0.5) == 7.5
    assert interpolate((0.0, 1.0, 1.0), (0.0, 1.0, 7.0), 1.0) == 1.0
    assert interpolate((0.0, 1.0, 1.0), (0.0, 1.0, 7.0), 2.0) == 1.0
    assert interpolate((0.0, 1.0, 1.0, 2.0), (0.0, 1.0, 7.0, 9.0), 1.0) == 7.0
    assert interpolate((0.0, 0.0, 1.0), (5.0, 3.0, 9.0), 0.0) == 3.0
    assert interpolate((0.0, 0.0, 1.0), (5.0, 3.0, 9.0), -1.0) == 5.0


@pytest.mark.parametrize(
    ("z", "pairs"),
    [
        ([0.0, 5.0, 10.0], [(0, 2)]),
        ([0.0, 5.0], [(0, 1)]),
        ([10.0, 5.0, 0.0, 5.0, 10.0], [(2, 4)]),
        ([0.0, 10.0, 10.0, 0.0], [(0, 1)]),
        ([0.0, 0.0, 10.0], [(0, 2)]),
        ([0.0, 10.0, 5.0, 20.0], [(0, 1), (2, 3)]),
        ([1000.0, 1001.0, 990.0], []),
        ([0.0, 4.9, 0.0], []),
    ],
)
def test_zigzag(z: list[float], pairs: list[tuple[int, int]]) -> None:
    """L'hystérésis de l'étape 3, à 5 m : une montée part du point le plus bas quand
    l'altitude le dépasse d'au moins 5 m, finit à son point le plus haut quand elle
    redescend d'au moins 5 m ; à égalité, le premier point bas et le premier point
    haut ; une montée en cours à la fin compte."""
    assert _zigzag(z, 5.0) == pairs


def test_profile_bounds() -> None:
    """Étape 5, sur le profil : le dernier point à la tolérance du minimum, le premier
    à la tolérance du maximum, le minimum lu avant le haut seulement."""
    z = [0.0, 0.5, 5.0, 9.5, 10.0, 9.6]
    assert _profile_bounds(z, 0, 5, 1.0) == (1, 3)
    assert _profile_bounds(z, 0, 5, 0.0) == (0, 4)
    assert _profile_bounds([0.0, 10.0, -5.0], 0, 2, 0.0) == (0, 1)
    assert _profile_bounds([0.6, 1.4, 5.0, 10.0, 0.0], 0, 4, 1.0) == (1, 3)


def test_time_bounds() -> None:
    """Étape 5, en temps, sur un replat sans bruit parcouru à 1 m/s (un instant par
    mètre), au pas de 50 m : une fenêtre vide, d'un côté ou de l'autre, ne donne pas de
    bornes ; des bornes confondues non plus. Un replat tout entier n'en a pas : la
    borne de départ y avance jusqu'à la borne d'arrivée, le dernier pas s'arrêtant à
    elle, même au dernier instant de la vue ; à ``flat_grade`` nul, un pas qui ne monte
    pas l'arrête (la comparaison est large)."""
    track = motion_track(recording([FLAT], noise=False))
    assert track is not None
    d = track.distance_m
    assert _time_bounds(track, d[400], d[-1], 0.25, 1.0, 50.0, 0.02) is None
    assert _time_bounds(track, 100.0, 200.0, 0.25, 1.0, 50.0, 0.0) == (
        100.0,
        200.0,
        0.0,
    )
    assert _time_bounds(track, 100.0, 200.0, 0.25, 1.0, 50.0, 0.02) is None
    assert _time_bounds(track, 100.5, 200.0, 0.25, 1.0, 50.0, 0.0) is None
    assert _time_bounds(track, 100.0, 200.5, 0.25, 1.0, 50.0, 0.0) is None
    assert _time_bounds(track, 100.0, 100.0, 0.25, 1.0, 50.0, 0.0) is None


def test_time_bounds_leave_a_rising_flat_out() -> None:
    """Étape 5 : 200 m à 1 % de part et d'autre d'une côte de 9 m, sans bruit (pied à
    399 s, haut à 459 s, un instant par mètre). Lue sur toute la fenêtre, la tolérance
    place les bornes 100 m dans les replats (à ``flat_grade`` nul, rien ne se
    resserre) ; resserrées, elles entrent dans la côte, plus près du pied et du haut
    qu'entre deux replats plats (405 s et 453 s), et le gain ne garde des replats que
    le début de leur dernier pas : 0,46 m au pied et 0,48 m au haut (le pas se lit en
    distance réalisée, un peu plus courte que l'abscisse de la fixture), soit
    9,94 m."""
    rising = (200.0, 0.01, 1.0)
    level = (200.0, 0.0, 1.0)
    track = motion_track(
        recording([level, rising, (60.0, 0.15, 1.0), rising, level], noise=False)
    )
    assert track is not None
    assert _time_bounds(track, 300.0, 560.0, 150.0, 1.0, 50.0, 0.0) == (
        299.0,
        559.0,
        13.0,
    )
    bounds = _time_bounds(track, 300.0, 560.0, 150.0, 1.0, 50.0, 0.02)
    assert bounds is not None
    start, end, gain = bounds
    assert (start, end) == (402.0, 456.0)
    assert gain == pytest.approx(9.94, abs=1e-9)


def test_time_bounds_settle_in_the_step_where_the_rise_starts() -> None:
    """Étape 5 : resserrées, les bornes se placent dans le pas où la montée commence
    (finit), à la tolérance du minimum (du maximum) de ce seul pas. Après le pied du
    premier ressaut (399 s), un creux qui redescend à la tolérance n'y compte pas ;
    avant le haut (509 s), un premier sommet à la tolérance (499 s) non plus."""
    level, rising = (200.0, 0.0, 1.0), (200.0, 0.01, 1.0)
    segments = [
        level,
        rising,
        (20.0, 0.15, 1.0),
        (20.0, -0.15, 1.0),
        (60.0, 0.15, 1.0),
        (4.0, -0.15, 1.0),
        (6.0, 0.15, 1.0),
        rising,
        level,
    ]
    track = motion_track(recording(segments, noise=False))
    assert track is not None
    bounds = _time_bounds(track, 300.0, 610.0, 150.0, 1.0, 50.0, 0.02)
    assert bounds is not None
    start, end, _ = bounds
    assert 399.0 <= start < 410.0
    assert 500.0 < end <= 509.0


def test_the_arrival_step_stops_at_the_start_bound() -> None:
    """Étape 5 : le pas qui précède la borne d'arrivée s'arrête à la borne de départ.
    Sur une vue écrite à la main, une marche de 2 m au premier instant, puis un palier,
    et un saut de 2 m de la distance réalisée (un trou) : en reculant, l'arrivée n'a
    bientôt plus un pas entier devant le départ, et ce pas partiel se lit jusqu'au
    premier instant de la vue, jamais au-delà."""
    track = motion_track(recording([FLAT], noise=False))
    assert track is not None
    d = tuple(float(i) for i in range(50)) + tuple(i + 2.0 for i in range(50, 500))
    track = dataclasses.replace(
        track, distance_m=d, smoothed_elevation_m=(0.0,) + (2.0,) * 499
    )
    assert _time_bounds(track, 0.0, d[70], 0.25, 1.0, 50.0, 0.02) == (0.0, 1.0, 2.0)


def test_settle() -> None:
    """Étape 5 d'un morceau, sur un profil écrit à la main le long de la vue d'une
    montée régulière : bornes au dernier point bas et au premier point haut, gains
    lissé et brut entre elles, D+ des seuls pas montants (la contre-pente de 10 m n'y
    compte pas, ni la montée avant le bas) ; pas de montée sans haut après le bas, ni
    sans bornes en temps (un haut au-delà de la vue)."""
    track = motion_track(recording([FLAT, climb_at(600, 0.15, 300), FLAT], noise=False))
    assert track is not None
    grid = [0.0, 500.0, 1000.0, 1500.0, 2000.0, 2500.0, 2600.0, 5000.0]
    z = [990.0, 1000.0, 1080.0, 1070.0, 1200.0, 1300.0, 1300.0, 1400.0]
    raw = [990.0, 999.0, 1085.0, 1065.0, 1210.0, 1302.0, 1300.0, 1400.0]
    climb = _with_parameters()
    bounds = _time_bounds(track, 500.0, 2500.0, 150.0, 1.0, 50.0, 0.02)
    assert bounds is not None
    piece = _settle(track, grid, z, raw, _Piece(1, 6), climb, 150.0, 50.0)
    assert piece.span == ClimbSpan(*bounds, 500.0, 2500.0, 300.0, 303.0, 310.0)
    assert _settle(track, grid, z, raw, _Piece(5, 6), climb, 150.0, 50.0).span is None
    assert _settle(track, grid, z, raw, _Piece(1, 7), climb, 150.0, 50.0).span is None


def test_moving_time_between_two_bounds() -> None:
    track = motion_track(recording([FLAT, climb_at(600, 0.15, 300), FLAT], noise=False))
    assert track is not None
    k, moving = CENTRAL_CONVENTION_INDEX, IntervalState.MOVING
    assert _moving_s(track, 500.0, 600.0) == state_time_s(track, k, moving, 500, 600)
    assert _moving_s(track, 600.0, 500.0) == 0.0
    assert _moving_s(track, 500.0, 500.0) == 0.0


@pytest.mark.parametrize(
    ("distance_m", "step_m", "count"),
    [(200.0, None, 1), (120.0, None, 1), (90.0, None, 0), (200.0, "half", 1)],
)
def test_a_track_of_two_points(
    distance_m: float, step_m: str | None, count: int
) -> None:
    """Deux instants, à 600 s l'un de l'autre, sur une pente de 30 % : une montée est
    détectée dès que la vue fait au moins deux pas de grille (deux fois 50 m, ou
    exactement deux pas d'une grille de la moitié de sa longueur), aucune en deçà."""
    rec = recording(
        [(2 * distance_m, 0.3, distance_m / 600.0)], noise=False, step_s=600
    )
    track = motion_track(rec)
    assert track is not None
    assert len(track.time_s) == 2
    profile = ParameterSet(PROFILE_PARAMETER_SPECS)
    if step_m == "half":
        length = deduplicated_polyline(track.latitude_deg, track.longitude_deg)
        profile = ParameterSet(
            PROFILE_PARAMETER_SPECS,
            {**profile.values, "grid_step_m": length.distance_m[-1] / 2},
        )
    assert len(detect_climbs(track, profile, _with_parameters())) == count


def test_the_profile_gain_threshold_is_inclusive() -> None:
    """Étape 3 : une montée dont le gain du profil vaut exactement
    ``min_profile_gain_fraction × min_gain_m`` est gardée."""
    track = motion_track(recording([FLAT, climb_at(600, 0.15, 300), FLAT], noise=False))
    assert track is not None
    profile = ParameterSet(PROFILE_PARAMETER_SPECS)
    z = build_profile_with_diagnostics(track_route(track), profile).profile.elevation_m
    ((low, high),) = _zigzag(z, 10.0)
    gain = z[high] - z[low]
    exact = _with_parameters(min_gain_m=gain, min_profile_gain_fraction=1.0)
    assert len(detect_climbs(track, profile, exact)) == 1


def test_a_small_bump_before_a_climb_is_skipped_not_final() -> None:
    """À une hystérésis de 5 m, une bosse de 12 m, lissée à moins de 10 m sur le
    profil, est une montée de l'hystérésis écartée par la détection relâchée ; la
    montée qui la suit est encore cherchée."""
    bump = [climb_at(600, 0.15, 12.0), (12.0 / 0.15, -0.15, 1.5)]
    track = motion_track(
        recording([FLAT, *bump, FLAT, climb_at(600, 0.15, 300), FLAT], noise=False)
    )
    assert track is not None
    spans = detect_climbs(
        track, ParameterSet(PROFILE_PARAMETER_SPECS), _with_parameters(hysteresis_m=5.0)
    )
    assert [s.gain_m for s in spans] == pytest.approx([300.0], abs=0.5)


def _stepped_profile() -> tuple[MotionTrack, ParameterSet]:
    """Sans lissage du profil : un replat, une montée de 21 pas de grille, un pas de
    grille à plat, un pas à 4 %, une montée, un replat. Les bornes des tronçons
    tombent sur la grille, à l'écart près de la conversion des longitudes."""
    segments = [
        (501.0, 0.0, 1.0),
        climb_at(600, 0.15, 157.5),
        (50.0, 0.0, 1.0),
        (50.0, 0.04, 1.0),
        climb_at(600, 0.15, 150),
        FLAT,
    ]
    track = motion_track(recording(segments, noise=False))
    assert track is not None
    profile = ParameterSet(
        PROFILE_PARAMETER_SPECS,
        {**ParameterSet(PROFILE_PARAMETER_SPECS).values, "smoothing_window_m": 0.0},
    )
    return track, profile


def test_each_flat_step_is_read_and_the_flat_grade_is_strict() -> None:
    """Étape 4, à longueur de replat et rapport nuls (tout replat coupe) : le pas à
    plat, à un nombre impair de pas du début de la montée, coupe ; le pas à 4 %, dont
    la pente vaut exactement ``flat_grade``, n'est pas plat, et la seconde montée part
    de son pied."""
    track, profile = _stepped_profile()
    built = build_profile_with_diagnostics(track_route(track), profile).profile
    grid, z = built.distance_m, built.elevation_m
    grades = [(z[h + 1] - z[h]) / (grid[h + 1] - grid[h]) for h in range(len(z) - 1)]
    assert grades[31] < 0.02 < grades[32] < 0.05
    climb = _with_parameters(
        flat_length_m=0.0, flat_time_ratio=0.0, flat_grade=grades[32]
    )
    first, second = detect_climbs(track, profile, climb)
    assert (first.profile_end_m, second.profile_start_m) == (grid[31], grid[32])


def test_the_flat_length_threshold_is_inclusive() -> None:
    """Étape 4 : le pas à plat, dont la distance parcourue en mouvement (entre les
    instants de ses deux points de grille) vaut exactement ``flat_length_m``, est
    candidat ; sans lissage, ``w_eff − h`` est nul."""
    track, profile = _stepped_profile()
    built = build_profile_with_diagnostics(track_route(track), profile)
    assert built.effective_smoothing_window_m == profile["grid_step_m"]
    grid = built.profile.distance_m
    polyline = deduplicated_polyline(track.latitude_deg, track.longitude_deg)
    times = [track.time_s[i] for i in polyline.indices]
    at = [interpolate(polyline.distance_m, times, grid[h]) for h in (31, 32)]
    length = interpolate(track.time_s, track.moving_distance_m, at[1]) - interpolate(
        track.time_s, track.moving_distance_m, at[0]
    )
    climb = _with_parameters(flat_length_m=length, flat_time_ratio=0.0)
    assert len(detect_climbs(track, profile, climb)) == 2


@pytest.mark.parametrize(("excess", "count"), [(1e-12, 2), (1e-7, 2), (1e-5, 1)])
def test_the_flat_length_threshold_is_reached_to_the_rounding(
    excess: float, count: int
) -> None:
    """Étape 4 : le seuil d'un replat est atteint à l'arrondi près (``0010`` D5.2) :
    un seuil plus long que la distance parcourue en mouvement de ``1e-12`` ou ``1e-7``
    en relatif est atteint, et le replat coupe ; de ``1e-5``, il ne l'est pas. Aux
    défauts, le seuil tombe sur un nombre entier de pas de grille, que les arrondis
    d'une plateforme placeraient sinon d'un côté ou de l'autre."""
    track, profile = _stepped_profile()
    built = build_profile_with_diagnostics(track_route(track), profile)
    grid = built.profile.distance_m
    polyline = deduplicated_polyline(track.latitude_deg, track.longitude_deg)
    times = [track.time_s[i] for i in polyline.indices]
    at = [interpolate(polyline.distance_m, times, grid[h]) for h in (31, 32)]
    length = interpolate(track.time_s, track.moving_distance_m, at[1]) - interpolate(
        track.time_s, track.moving_distance_m, at[0]
    )
    climb = _with_parameters(flat_length_m=length * (1 + excess), flat_time_ratio=0.0)
    assert len(detect_climbs(track, profile, climb)) == count


def _three_climbs(flats: list[tuple[float, float, float]]) -> list[float]:
    part = climb_at(600, 0.15, 300)
    track = motion_track(
        recording([FLAT, part, flats[0], part, flats[1], part, FLAT], noise=False)
    )
    assert track is not None
    return [m.span.gain_m for m in climbs(track)]


def test_the_lightest_flat_merges_first_among_three_pieces() -> None:
    """Trois morceaux : un replat de 400 s coupe (plus d'un dixième des 1 800 s du
    plus court voisin), un replat de 100 s ne coupe pas, à gauche comme à droite ;
    deux replats lourds coupent tous les deux."""
    heavy, light = (400.0, 0.0, 1.0), (300.0, 0.0, 3.0)
    assert _three_climbs([heavy, light]) == pytest.approx([300.0, 600.0], abs=0.5)
    assert _three_climbs([light, heavy]) == pytest.approx([600.0, 300.0], abs=0.5)
    assert _three_climbs([heavy, heavy]) == pytest.approx([300.0] * 3, abs=0.5)


def test_a_piece_without_moving_time_is_not_merged() -> None:
    """Une montée tout entière dans un trou, après un replat : son temps en mouvement
    est nul, le rapport du replat n'est pas défini, et le morceau n'est pas fusionné
    (puis la mesure l'écarte, faute de longueur en M)."""
    segments = [
        FLAT,
        climb_at(600, 0.15, 150),
        (400.0, 0.0, 1.0),
        climb_at(600, 0.15, 150),
        FLAT,
    ]
    track = motion_track(recording(segments, noise=False, gaps=((1800.0, 2700.0),)))
    assert track is not None
    spans = detect_climbs(
        track, ParameterSet(PROFILE_PARAMETER_SPECS), _with_parameters()
    )
    assert len(spans) == 2
    k, moving = CENTRAL_CONVENTION_INDEX, IntervalState.MOVING
    assert state_time_s(track, k, moving, spans[1].start_s, spans[1].end_s) == 0.0
    assert len(climbs(track)) == 1


def test_the_flat_time_ratio_is_inclusive() -> None:
    """Un replat dont le rapport vaut exactement ``flat_time_ratio`` ne coupe pas :
    il coupe s'il le « dépasse »."""
    segments = [
        FLAT,
        climb_at(600, 0.15, 150),
        (400.0, 0.0, 1.0),
        climb_at(600, 0.15, 150),
        FLAT,
    ]
    track = motion_track(recording(segments, noise=False))
    assert track is not None
    profile = ParameterSet(PROFILE_PARAMETER_SPECS)
    left, right = detect_climbs(track, profile, _with_parameters())
    k, moving = CENTRAL_CONVENTION_INDEX, IntervalState.MOVING

    def moving_s(start: float, end: float) -> float:
        return state_time_s(track, k, moving, start, end)

    ratio = moving_s(left.end_s, right.start_s) / min(
        moving_s(left.start_s, left.end_s), moving_s(right.start_s, right.end_s)
    )
    assert 0.1 < ratio < 1.0
    assert (
        len(detect_climbs(track, profile, _with_parameters(flat_time_ratio=ratio))) == 1
    )


def _span(start_s: float, end_s: float, gain_m: float = 100.0) -> ClimbSpan:
    """Une montée écrite à la main, bornée à deux instants de la vue ; ses champs du
    profil ne servent pas aux mesures."""
    return ClimbSpan(start_s, end_s, gain_m, 0.0, 1.0, 1.0, 1.0, 1.0)


def _shifted(rec: ActivityRecording, changes: dict[float, float]) -> ActivityRecording:
    """``rec``, l'altitude brute de certains instants déplacée."""
    assert rec.elevation is not None
    z = tuple(
        v + changes.get(t, 0.0)
        for t, v in zip(rec.elevation.time_s, rec.elevation.elevation_m, strict=True)
    )
    return dataclasses.replace(
        rec, elevation=dataclasses.replace(rec.elevation, elevation_m=z)
    )


def test_the_measures_read_only_the_inside_of_the_climb() -> None:
    """Juste avant la montée, un pas de 5 s et une altitude brute abaissée de 10 m :
    ni le pas, ni le saut, ni l'altitude lissée qu'il abaisse ne comptent ; dedans,
    pas de 1 s et 600 m/h."""
    rec = recording(
        [FLAT, climb_at(600, 0.15, 300), FLAT], noise=False, gaps=((995.0, 1000.0),)
    )
    track = motion_track(_shifted(rec, {995.0: -10.0}))
    assert track is not None
    t = track.time_s
    first, last = t.index(1000.0 - track.offset_s), t.index(1600.0 - track.offset_s)
    measure = measure_climb(track, _span(t[first], t[last]), _with_parameters())
    assert measure is not None
    assert (measure.step_s, measure.longest_step_s) == (1.0, 1.0)
    assert measure.max_vertical_rate_ms == pytest.approx(600.0 / 3600.0)
    inside = track.smoothed_elevation_m[first : last + 1]
    assert (measure.low_elevation_m, measure.high_elevation_m) == (
        min(inside),
        max(inside),
    )


@pytest.mark.parametrize("end", [False, True])
def test_the_measures_read_the_first_and_the_last_steps(end: bool) -> None:
    """Une montée bornée au premier et au dernier instant de la vue : le pas et le
    saut d'altitude du premier intervalle comptent (5 s, 15 m), ceux du dernier aussi
    (6 s, 15 m)."""
    gaps, changes, step = ((1.0, 6.0),), {1.0: -15.0}, 5.0
    if end:
        gaps, changes, step = ((594.0, 600.0),), {600.0: 15.0}, 6.0
    rec = recording([climb_at(600, 0.15, 100)], noise=False, gaps=gaps)
    track = motion_track(_shifted(rec, changes))
    assert track is not None
    measure = measure_climb(
        track, _span(track.time_s[0], track.time_s[-1]), _with_parameters()
    )
    assert measure is not None
    assert measure.longest_step_s == step
    assert measure.max_vertical_rate_ms == pytest.approx((15.0 + step / 6.0) / step)


def test_the_filters_of_a_climb() -> None:
    """Étape 6, sur une montée lente et raide (0,5 m/s à 30 %) coupée d'un trou de
    20 s : à travers le trou, aucune longueur en M, pas de mesure, quel que soit le
    gain ; sur une seule seconde (50 cm), des mesures, dont l'altitude moyenne en M ;
    au gain minimal exact, des mesures, juste dessous aucune ; à la pente minimale
    exacte, aucune."""
    rec = recording(
        [FLAT, climb_at(540, 0.30, 60), FLAT], noise=False, gaps=((700.0, 720.0),)
    )
    track = motion_track(rec)
    assert track is not None
    t, climb = track.time_s, _with_parameters()
    at = {
        s: t[t.index(s - track.offset_s)]
        for s in (600.0, 650.0, 651.0, 690.0, 700.0, 720.0)
    }
    assert measure_climb(track, _span(at[700.0], at[720.0], 1000.0), climb) is None
    short = measure_climb(track, _span(at[650.0], at[651.0]), climb)
    assert short is not None
    assert 0.0 < short.moving_distance_m < 1.0
    assert short.moving_s[CENTRAL_CONVENTION_INDEX] == 1.0
    assert short.moving_mean_elevation_m is not None
    assert measure_climb(track, _span(at[600.0], at[690.0], 20.0), climb) is not None
    assert measure_climb(track, _span(at[600.0], at[690.0], 19.999), climb) is None
    zs, d = track.smoothed_elevation_m, track.distance_m
    a, b = at[600.0], at[690.0]
    grade = (interpolate(t, zs, b) - interpolate(t, zs, a)) / (
        interpolate(t, d, b) - interpolate(t, d, a)
    )
    assert measure_climb(track, _span(a, b), _with_parameters(min_grade=grade)) is None


def test_the_measures_are_the_clocks_between_the_bounds() -> None:
    """Le temps et le gain de chaque état, sous chaque convention, sont ceux des
    horloges entre les bornes, sur une montée coupée d'un arrêt et d'un trou."""
    rec = recording(
        [FLAT, climb_at(600, 0.15, 300), FLAT],
        stops=((900.0, 990.0),),
        gaps=((1500.0, 1540.0),),
    )
    track = motion_track(rec)
    assert track is not None
    (measure,) = climbs(track)
    a, b = measure.span.start_s, measure.span.end_s
    fields = {
        IntervalState.MOVING: (measure.moving_s, measure.moving_gain_m),
        IntervalState.STOPPED: (measure.stopped_s, measure.stopped_gain_m),
        IntervalState.UNDETERMINED: (
            measure.undetermined_s,
            measure.undetermined_gain_m,
        ),
    }
    conventions = range(len(CLOCK_CONVENTIONS))
    for state, (times, gains) in fields.items():
        assert times == tuple(state_time_s(track, k, state, a, b) for k in conventions)
        assert gains == tuple(state_gain_m(track, k, state, a, b) for k in conventions)
    k = CENTRAL_CONVENTION_INDEX
    assert measure.stopped_s[k] > 60.0
    assert measure.undetermined_s[k] > 30.0


def test_the_low_elevation_reads_the_first_inside_instant() -> None:
    """Une montée écrite à la main, bornée un instant avant le fond d'un vallon : le
    point bas est le premier instant intérieur."""
    descent = (60.0 / 0.15, -0.15, 1.5)
    track = motion_track(
        recording([FLAT, descent, climb_at(600, 0.15, 300), FLAT], noise=False)
    )
    assert track is not None
    zs = track.smoothed_elevation_m
    bottom = zs.index(min(zs))
    t = track.time_s
    measure = measure_climb(track, _span(t[bottom - 1], t[-1]), _with_parameters())
    assert measure is not None
    assert zs[bottom] < zs[bottom - 1]
    assert measure.low_elevation_m == zs[bottom]
