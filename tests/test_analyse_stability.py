"""La stabilité d'une montée (``mountain_perf.analyse.stability``,
``docs/decisions/0014``)."""

from __future__ import annotations

import dataclasses

import pytest

from fixtures.montees import FLAT, climb_at, recording
from mountain_perf.analyse.climbs import (
    CLIMB_PARAMETER_SPECS,
    ClimbMeasure,
    ClimbSpan,
    climbs,
    motion_track,
    track_route,
)
from mountain_perf.analyse.stability import (
    STABILITY_PARAMETER_SPECS,
    VARIANTS,
    jaccard,
    stability,
    variant_climbs,
)
from mountain_perf.gpx.profile import (
    PROFILE_PARAMETER_SPECS,
    build_profile_with_diagnostics,
)
from mountain_perf.schemas import ParameterSet
from test_analyse_quality import measure

PARAMETERS = ParameterSet(STABILITY_PARAMETER_SPECS)


def at(
    start_s: float, end_s: float, vam_ms: float | None = 100.0 / 600.0
) -> ClimbMeasure:
    """Une montée sur ``[start_s ; end_s]`` de VAM ``vam_ms`` (sans VAM : aucun temps
    en mouvement)."""
    span = ClimbSpan(start_s, end_s, 100.0, 0.0, 1000.0, 100.0, 100.0, 100.0)
    moving = (0.0,) * 5 if vam_ms is None else (100.0 / vam_ms,) * 5
    return dataclasses.replace(measure(), span=span, moving_s=moving)


def test_the_twelve_declared_variants() -> None:
    assert [v.name for v in VARIANTS] == [
        "hysteresis_half",
        "hysteresis_double",
        "flat_length_half",
        "flat_length_double",
        "flat_time_ratio_half",
        "flat_time_ratio_double",
        "flat_grade_minus",
        "flat_grade_plus",
        "smoothing_five_points",
        "grid_25_m",
        "bound_tolerance_half",
        "bound_tolerance_double",
    ]


def test_what_each_variant_changes() -> None:
    """Chaque variante change un seul paramètre, de la valeur que dit son nom."""
    profile = dict(ParameterSet(PROFILE_PARAMETER_SPECS).values)
    climb = dict(ParameterSet(CLIMB_PARAMETER_SPECS).values)
    expected: dict[str, tuple[dict[str, float], dict[str, float]]] = {
        "hysteresis_half": ({}, {"hysteresis_m": 5.0}),
        "hysteresis_double": ({}, {"hysteresis_m": 20.0}),
        "flat_length_half": ({}, {"flat_length_m": 125.0}),
        "flat_length_double": ({}, {"flat_length_m": 500.0}),
        "flat_time_ratio_half": ({}, {"flat_time_ratio": 0.05}),
        "flat_time_ratio_double": ({}, {"flat_time_ratio": 0.2}),
        "flat_grade_minus": ({}, {"flat_grade": 0.01}),
        "flat_grade_plus": ({}, {"flat_grade": 0.03}),
        "smoothing_five_points": ({"smoothing_window_m": 250.0}, {}),
        "grid_25_m": ({"grid_step_m": 25.0}, {}),
        "bound_tolerance_half": ({}, {"bound_tolerance_m": 0.5}),
        "bound_tolerance_double": ({}, {"bound_tolerance_m": 2.0}),
    }
    assert sorted(expected) == sorted(v.name for v in VARIANTS)
    for variant in VARIANTS:
        profile_changes, climb_changes = expected[variant.name]
        assert variant.profile(dict(profile)) == pytest.approx(
            {**profile, **profile_changes}
        )
        assert variant.climb(dict(climb)) == pytest.approx({**climb, **climb_changes})


def test_every_variant_changes_what_the_chain_reads() -> None:
    """Une variante qui ne change rien de ce que la chaîne lit serait stable par
    construction. Le lissage du profil se quantifie par le pas de la grille : on
    compare le pas et le nombre de points de la fenêtre que le profil emploie vraiment,
    et les paramètres de la montée."""
    track = motion_track(recording([FLAT, climb_at(600, 0.15, 300), FLAT]))
    assert track is not None
    route = track_route(track)
    profile = dict(ParameterSet(PROFILE_PARAMETER_SPECS).values)
    climb = dict(ParameterSet(CLIMB_PARAMETER_SPECS).values)

    def read(p: dict[str, float], c: dict[str, float]) -> tuple[object, ...]:
        built = build_profile_with_diagnostics(
            route, ParameterSet(PROFILE_PARAMETER_SPECS, p)
        )
        return built.profile.step_m, built.smoothing_point_count, sorted(c.items())

    reference = read(profile, climb)
    for variant in VARIANTS:
        changed = read(variant.profile(dict(profile)), variant.climb(dict(climb)))
        assert changed != reference, variant.name


def test_jaccard_in_time() -> None:
    assert jaccard(at(0, 100), at(50, 150)) == pytest.approx(50 / 150)
    assert jaccard(at(0, 100), at(100, 200)) == 0.0
    assert jaccard(at(0, 100), at(0, 100)) == 1.0


def test_found_from_a_jaccard_of_one_half() -> None:
    reference = at(0, 100)
    half = [[at(0, 50)]] * 10  # Jaccard 0,5 exactement : retrouvée
    below = [[at(0, 49.9)]] * 10
    assert stability(reference, half, PARAMETERS).found_fraction == 1.0
    assert stability(reference, below, PARAMETERS).found_fraction == 0.0


def test_the_best_match_is_kept() -> None:
    reference = at(0, 100)
    variants = [[at(0, 60, 1.0), at(0, 100, 100.0 / 600.0 * 1.01)]]
    result = stability(reference, variants, PARAMETERS)
    assert result.max_relative_deviation == pytest.approx(0.01)


def test_stable_needs_eighty_percent_and_a_deviation_under_five_percent() -> None:
    reference = at(0, 100)
    same = [at(0, 100)]
    missing: list[ClimbMeasure] = []
    eight_of_ten = [same] * 8 + [missing] * 2
    seven_of_ten = [same] * 7 + [missing] * 3
    assert stability(reference, eight_of_ten, PARAMETERS).stable is True
    assert stability(reference, seven_of_ten, PARAMETERS).stable is False
    off = [[at(0, 100, 100.0 / 600.0 * 1.05)]] * 10
    under = [[at(0, 100, 100.0 / 600.0 * 1.0499)]] * 10
    assert stability(reference, off, PARAMETERS).stable is False
    assert stability(reference, under, PARAMETERS).stable is True


def test_no_vertical_speed_no_verdict() -> None:
    result = stability(at(0, 100, None), [[at(0, 100)]] * 10, PARAMETERS)
    assert result.stable is None
    assert result.found_fraction == 1.0
    assert result.max_relative_deviation is None


@pytest.mark.parametrize("moving_gain_m", [0.0, -1.0])
def test_no_positive_vertical_speed_no_verdict(moving_gain_m: float) -> None:
    """Un gain en M nul ou négatif (le gain pris hors de M) : aucun écart relatif ne
    se lit, la montée n'est ni stable ni instable, même retrouvée partout."""
    reference = dataclasses.replace(at(0, 100), moving_gain_m=(moving_gain_m,) * 5)
    result = stability(reference, [[reference]] * 12, PARAMETERS)
    assert result.found_fraction == 1.0
    assert result.max_relative_deviation is None
    assert result.stable is None


def test_a_long_regular_climb_is_stable_under_every_variant() -> None:
    track = motion_track(recording([FLAT, climb_at(600, 0.15, 300), FLAT]))
    assert track is not None
    (reference,) = climbs(track)
    variants = variant_climbs(track)
    assert len(variants) == len(VARIANTS)
    result = stability(reference, variants, PARAMETERS)
    assert result.found_fraction == 1.0
    assert result.stable is True


def test_a_flat_that_only_one_variant_cuts() -> None:
    """Un replat de 210 m entre deux côtes de 60 m : la référence garde une seule
    montée ; sous ``flat_length_half``, le replat coupe. La montée n'est pas retrouvée
    dans toutes les variantes, mais dans assez pour rester stable. (À 220 m, le replat
    atteint son seuil à l'arrondi près sous ``grid_25_m``, qui coupe aussi.)"""
    flat = (210.0, 0.0, 1.0)
    segments = [FLAT, climb_at(600, 0.15, 60), flat, climb_at(600, 0.15, 60), FLAT]
    track = motion_track(recording(segments, noise=False))
    assert track is not None
    (reference,) = climbs(track)
    result = stability(reference, variant_climbs(track), PARAMETERS)
    assert result.found_fraction == pytest.approx(11 / 12)
    assert result.stable is True


@pytest.mark.parametrize("noise", [False, True])
def test_a_climb_that_a_variant_shortens_is_unstable(noise: bool) -> None:
    """Une rampe à 2,5 % avant une côte : la référence la compte dans la montée ;
    ``flat_grade_plus`` (3 %) en fait un replat et ne garde que la côte. La VAM change
    de plus de 5 % : la montée est instable."""
    segments = [FLAT, (300.0, 0.025, 1.0), climb_at(600, 0.15, 100), FLAT]
    track = motion_track(recording(segments, noise=noise))
    assert track is not None
    (reference,) = climbs(track)
    result = stability(reference, variant_climbs(track), PARAMETERS)
    assert result.max_relative_deviation is not None
    assert result.max_relative_deviation > 0.05
    assert result.stable is False


def test_jaccard_of_a_short_overlap() -> None:
    """Un recouvrement d'une demi-seconde compte : 0,5 s sur 200 s."""
    assert jaccard(at(0, 100), at(99.5, 200)) == pytest.approx(0.5 / 200)


def test_a_tie_keeps_the_first_candidate() -> None:
    """Deux montées de la variante recouvrent la référence avec le même indice (0,5) :
    la première dans l'ordre du temps est gardée, et c'est sa VAM qui se compare."""
    reference = at(0, 100)
    first, second = at(0, 50, 100.0 / 600.0 * 1.10), at(50, 100, 100.0 / 600.0 * 1.20)
    result = stability(reference, [[first, second]], PARAMETERS)
    assert result.max_relative_deviation == pytest.approx(0.10)


def test_no_variant_no_found_fraction() -> None:
    result = stability(at(0, 100), [], PARAMETERS)
    assert result.found_fraction == 0.0
    assert result.max_relative_deviation is None
    assert result.stable is False


def test_a_deviation_at_the_threshold_is_unstable() -> None:
    """L'écart relatif doit rester strictement sous le seuil : à 0,25 exactement (une
    VAM de 1 m/s contre 1,25 m/s, valeurs exactes en binaire), la montée est
    instable ; juste dessous, stable."""
    parameters = ParameterSet(
        STABILITY_PARAMETER_SPECS,
        {**PARAMETERS.values, "max_relative_deviation": 0.25},
    )
    reference = measure(moving_gain_m=(100.0,) * 5, moving_s=(100.0,) * 5)
    at_threshold = measure(moving_gain_m=(100.0,) * 5, moving_s=(80.0,) * 5)
    below = measure(moving_gain_m=(100.0,) * 5, moving_s=(81.0,) * 5)
    assert stability(reference, [[at_threshold]] * 10, parameters).stable is False
    assert stability(reference, [[below]] * 10, parameters).stable is True


def test_each_variant_runs_the_chain_under_its_own_parameters() -> None:
    """``variant_climbs`` passe à la chaîne les paramètres que chaque variante change,
    du profil comme de la montée : chaque liste rendue est celle de ``climbs`` sous
    ces paramètres, écrits ici en clair."""
    track = motion_track(
        recording(
            [
                FLAT,
                climb_at(600, 0.15, 60),
                (220.0, 0.0, 1.0),
                climb_at(600, 0.15, 60),
                FLAT,
            ]
        )
    )
    assert track is not None
    profile = dict(ParameterSet(PROFILE_PARAMETER_SPECS).values)
    climb = dict(ParameterSet(CLIMB_PARAMETER_SPECS).values)
    changed = {
        "smoothing_five_points": ({"smoothing_window_m": 250.0}, {}),
        "grid_25_m": ({"grid_step_m": 25.0}, {}),
        "flat_length_half": ({}, {"flat_length_m": 125.0}),
        "hysteresis_double": ({}, {"hysteresis_m": 20.0}),
    }
    found = dict(zip((v.name for v in VARIANTS), variant_climbs(track), strict=True))
    for name, (profile_changes, climb_changes) in changed.items():
        expected = climbs(
            track,
            ParameterSet(PROFILE_PARAMETER_SPECS, {**profile, **profile_changes}),
            ParameterSet(CLIMB_PARAMETER_SPECS, {**climb, **climb_changes}),
        )
        assert found[name] == expected, name
    reference = climbs(track)
    assert found["grid_25_m"] != reference
    assert found["flat_length_half"] != reference
