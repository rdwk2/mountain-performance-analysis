"""La table ``variantes`` (``mountain_perf.analyse.tables``, AN1-2c,
``docs/decisions/0015``) : les montées que la stabilité calcule sous chaque variante,
avec leurs drapeaux, leur régime et leurs strates sous les paramètres de la variante,
sur l'``interim/`` synthétique de ``tests/fixtures/processed.py``."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from fixtures.montees import FLAT, climb_at, recording
from fixtures.processed import COMMIT, write_interim, write_one
from mountain_perf.analyse import tables as tables_module
from mountain_perf.analyse.athlete import DEFAULT_SETTINGS, AthleteSettings
from mountain_perf.analyse.climbs import climbs, motion_track
from mountain_perf.analyse.q1 import View, q1_figure
from mountain_perf.analyse.quality import (
    altitude_stratum,
    climb_flags,
    grade_stratum,
    regime,
)
from mountain_perf.analyse.stability import (
    VARIANTS,
    variant_climbs,
    variant_parameters,
)
from mountain_perf.analyse.tables import DEFAULT_DEFINITION, Tables, build_tables
from mountain_perf.ingest.interim import read_index, read_recording
from mountain_perf.ingest.types import SOURCE_TYPE_SPORTS
from mountain_perf.schemas import CENTRAL_CONVENTION_INDEX, ParameterSet
from mountain_perf.schemas.processed import ClimbFlag, ClimbRegime, ClimbVariantRow


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("donnees")
    write_interim(folder)
    return folder


@pytest.fixture(scope="module")
def tables(data_dir: Path) -> Tables:
    return build_tables(data_dir, DEFAULT_SETTINGS, commit=COMMIT)


def _expected(data_dir: Path, settings: AthleteSettings) -> list[ClimbVariantRow]:
    """Les lignes attendues, recalculées montée par montée : pour chaque activité qui
    a une montée de référence, les montées de chaque variante, dans l'ordre de
    ``VARIANTS`` puis du temps, avec ``quality.py`` sous les paramètres de la variante
    (baromètre attesté, pas de boucle dans l'``interim/`` synthétique)."""
    rows = []
    definition = DEFAULT_DEFINITION
    for entry in read_index(data_dir).entries:
        if not entry.has_recording:
            continue
        recording_ = read_recording(data_dir, entry.activity_ref)
        track = motion_track(recording_)
        if track is None:
            continue
        sport = SOURCE_TYPE_SPORTS.get(entry.source_activity_type)
        barometric = settings.barometric(
            recording_.device.barometer,
            recording_.device.manufacturer,
            recording_.device.product,
        )
        all_variants = variant_climbs(track)
        if not climbs(track):
            continue
        for variant, (_, climb), measures in zip(
            VARIANTS, variant_parameters(), all_variants, strict=True
        ):
            for m in measures:
                rows.append(
                    ClimbVariantRow(
                        activity_ref=entry.activity_ref,
                        variant=variant.name,
                        start_offset_s=track.offset_s + m.span.start_s,
                        end_offset_s=track.offset_s + m.span.end_s,
                        gain_m=m.span.gain_m,
                        moving_gain_m=m.moving_gain_m[CENTRAL_CONVENTION_INDEX],
                        moving_s=m.moving_s[CENTRAL_CONVENTION_INDEX],
                        regime=regime(
                            m.span.gain_m,
                            sport,
                            settings.reference_vertical_speed_ms,
                            definition.regimes,
                        ),
                        grade_stratum=grade_stratum(
                            m, climb, definition.regimes, definition.quality
                        ),
                        altitude_stratum=altitude_stratum(m, definition.regimes),
                        flags=tuple(
                            sorted(
                                climb_flags(
                                    m,
                                    sport,
                                    barometric=barometric,
                                    altimetric_drift=False,
                                    climb=climb,
                                    quality=definition.quality,
                                )
                            )
                        ),
                    )
                )
    return rows


def test_each_row_is_a_climb_of_its_variant(data_dir: Path, tables: Tables) -> None:
    assert list(tables.variants) == _expected(data_dir, DEFAULT_SETTINGS)


def test_the_rows_follow_the_index_the_variants_and_the_time(tables: Tables) -> None:
    refs = [a.activity_ref for a in tables.activities]
    names = [v.name for v in VARIANTS]
    keys = [
        (refs.index(r.activity_ref), names.index(r.variant), r.start_offset_s)
        for r in tables.variants
    ]
    assert keys == sorted(keys)
    assert {r.activity_ref for r in tables.variants} == {"a1", "a2"}
    assert {r.variant for r in tables.variants} == set(names)


def test_every_variant_sees_both_climbs_of_the_walk(tables: Tables) -> None:
    """``a1`` a une côte et une montée longue, que chaque variante retrouve : vingt-
    quatre lignes, deux par variante, une côte puis une montée longue."""
    walk = [r for r in tables.variants if r.activity_ref == "a1"]
    assert [(r.variant, r.regime) for r in walk] == [
        (v.name, regime_)
        for v in VARIANTS
        for regime_ in (ClimbRegime.SHORT_CLIMB, ClimbRegime.LONG_CLIMB)
    ]


def test_the_ski_climb_keeps_its_flag_in_every_variant(tables: Tables) -> None:
    """``a2`` n'a pas de baromètre décrit : sa montée est marquée sous chaque
    variante, comme sa montée de référence."""
    ski = [r for r in tables.variants if r.activity_ref == "a2"]
    assert len(ski) == len(VARIANTS)
    assert all(ClimbFlag.NON_BAROMETRIC in r.flags for r in ski)
    assert all(r.regime is ClimbRegime.SKI_TOURING for r in ski)


def test_an_activity_without_climb_has_no_variant_rows(tmp_path: Path) -> None:
    write_one(tmp_path, recording([FLAT, FLAT], activity_ref="p1"))
    tables = build_tables(tmp_path, DEFAULT_SETTINGS, commit=COMMIT)
    assert tables.climbs == ()
    assert tables.variants == ()
    assert tables.provenance.variant_climb_count == 0


def test_a_variant_climb_without_a_reference_climb_is_not_kept(tmp_path: Path) -> None:
    """Une montée de 19,5 m (graine 1) : la référence n'y trouve aucune montée, une
    variante en trouve une. L'activité n'a aucune ligne de variante : la table ne
    garde que les activités qui ont au moins une montée de référence
    (``docs/decisions/0015``, « La table des variantes »)."""
    rec = recording([FLAT, climb_at(600, 0.15, 19.5), FLAT], seed=1, activity_ref="p2")
    track = motion_track(rec)
    assert track is not None
    assert not climbs(track)
    assert any(variant_climbs(track))
    write_one(tmp_path, rec)
    tables = build_tables(tmp_path, DEFAULT_SETTINGS, commit=COMMIT)
    assert tables.climbs == ()
    assert tables.variants == ()


def _cut_walk(data_dir: Path) -> Tables:
    """Deux montées de 150 m à 12 %, séparées d'un replat de 200 m : la référence en
    fait une montée longue de 300 m ; ``flat_length_half`` et ``grid_25_m`` la coupent
    en deux morceaux d'environ 150 m, intermédiaires sous la ``V_ref`` par défaut
    (900 m/h : le panneau des montées longues commence à 225 m)."""
    write_one(
        data_dir,
        recording(
            [
                FLAT,
                climb_at(600, 0.12, 150),
                (200.0, 0.0, 1.0),
                climb_at(600, 0.12, 150),
                FLAT,
            ],
            activity_ref="c1",
        ),
    )
    return build_tables(data_dir, DEFAULT_SETTINGS, commit=COMMIT)


CUTTING = ("flat_length_half", "grid_25_m")
"""Les deux variantes qui coupent la montée de ``_cut_walk``."""


def test_each_piece_of_a_cut_climb_reads_its_own_regime(tmp_path: Path) -> None:
    """Le régime d'une ligne se lit sur son gain, pas sur la montée de référence
    qu'elle recouvre : sous les deux variantes qui coupent, deux lignes
    intermédiaires ; sous les autres, une montée longue, comme la référence."""
    tables = _cut_walk(tmp_path)
    assert [c.regime for c in tables.climbs] == [ClimbRegime.LONG_CLIMB]
    assert [(r.variant, r.regime) for r in tables.variants] == [
        (v.name, regime_)
        for v in VARIANTS
        for regime_ in (
            (ClimbRegime.INTERMEDIATE,) * 2
            if v.name in CUTTING
            else (ClimbRegime.LONG_CLIMB,)
        )
    ]


def test_a_point_is_not_found_where_a_cut_takes_it_out_of_its_panel(
    tmp_path: Path,
) -> None:
    """La figure de la même activité : sous les deux variantes qui coupent, aucune
    montée longue ne couvre le point, qui n'y est pas retrouvé ; il l'est dans les dix
    autres (``docs/decisions/0015``, « La stabilité du point »)."""
    figure = q1_figure(_cut_walk(tmp_path))
    (point,) = [p for p in figure.points if p.view is View.MAIN]
    assert point.stability is not None
    assert point.stability.min_kept_fraction == 0.0
    assert point.stability.found_fraction == 10 / 12


def test_the_variants_read_the_declared_reference_speed(data_dir: Path) -> None:
    """Une ``V_ref`` déclarée de 300 m/h : la côte de 60 m d'``a1`` devient
    intermédiaire sous chaque variante, comme sa montée de référence."""
    settings = AthleteSettings(300 / 3600, True, frozenset())
    tables = build_tables(data_dir, settings, commit=COMMIT)
    walk = [r for r in tables.variants if r.activity_ref == "a1"]
    assert [r.regime for r in walk[:2]] == [
        ClimbRegime.INTERMEDIATE,
        ClimbRegime.LONG_CLIMB,
    ]
    assert list(tables.variants) == _expected(data_dir, settings)


def test_the_flags_and_strata_of_a_variant_read_its_own_parameters(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Les drapeaux et la strate de pente d'une montée de variante se lisent sous les
    paramètres de la variante, pas sous ceux de la référence : chaque jeu de
    paramètres de ``variant_parameters`` passe par ``climb_flags`` et
    ``grade_stratum``. (Aucune variante déclarée ne change la pente minimale, seul
    paramètre de la montée qu'ils lisent : sans ce contrôle, la confusion ne se
    verrait pas.)"""
    seen: dict[str, list[dict[str, float]]] = {"flags": [], "grade": []}

    def flags_spy(*args: Any, climb: ParameterSet, **kwargs: Any) -> Any:
        seen["flags"].append(dict(climb.values))
        return climb_flags(*args, climb=climb, **kwargs)

    def grade_spy(measure: Any, climb: ParameterSet, *rest: Any) -> Any:
        seen["grade"].append(dict(climb.values))
        return grade_stratum(measure, climb, *rest)

    monkeypatch.setattr(tables_module, "climb_flags", flags_spy)
    monkeypatch.setattr(tables_module, "grade_stratum", grade_spy)
    build_tables(data_dir, DEFAULT_SETTINGS, commit=COMMIT)
    expected = [dict(c.values) for _, c in variant_parameters()]
    for name in ("flags", "grade"):
        for values in expected:
            assert values in seen[name]


def test_a_non_default_definition_reaches_the_variants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Une hystérésis de 25 m : les montées des variantes sont celles de
    ``variant_climbs`` sous ces paramètres, et leurs drapeaux et leurs strates se
    lisent sous les paramètres de chaque variante tirés de cette définition."""
    seen: list[dict[str, float]] = []

    def flags_spy(*args: Any, climb: ParameterSet, **kwargs: Any) -> Any:
        seen.append(dict(climb.values))
        return climb_flags(*args, climb=climb, **kwargs)

    monkeypatch.setattr(tables_module, "climb_flags", flags_spy)
    rec = recording(
        [
            FLAT,
            climb_at(600, 0.15, 150),
            (200.0, -0.1, 1.0),
            climb_at(600, 0.15, 150),
            FLAT,
        ],
        activity_ref="n1",
    )
    climb = ParameterSet(
        DEFAULT_DEFINITION.climb.specs,
        {**DEFAULT_DEFINITION.climb.values, "hysteresis_m": 25.0},
    )
    definition = dataclasses.replace(DEFAULT_DEFINITION, climb=climb)
    write_one(tmp_path, rec)
    tables = build_tables(tmp_path, DEFAULT_SETTINGS, definition, commit=COMMIT)
    track = motion_track(rec)
    assert track is not None
    expected = [
        (v.name, track.offset_s + m.span.start_s)
        for v, measures in zip(
            VARIANTS,
            variant_climbs(track, DEFAULT_DEFINITION.profile, climb),
            strict=True,
        )
        for m in measures
    ]
    assert [(r.variant, r.start_offset_s) for r in tables.variants] == expected
    assert tables.variants
    for _, variant_climb in variant_parameters(DEFAULT_DEFINITION.profile, climb):
        assert dict(variant_climb.values) in seen
    assert expected != [
        (v.name, track.offset_s + m.span.start_s)
        for v, measures in zip(VARIANTS, variant_climbs(track), strict=True)
        for m in measures
    ]


def test_the_variants_carry_the_drift_of_their_activity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Une activité dont la dérive altimétrique est établie : chaque montée de chaque
    variante porte le drapeau, comme ses montées de référence."""
    write_interim(tmp_path)
    monkeypatch.setattr(tables_module, "altimetric_drift", lambda *args: True)
    tables = build_tables(tmp_path, DEFAULT_SETTINGS, commit=COMMIT)
    assert tables.variants
    assert all(ClimbFlag.ALTIMETRIC_DRIFT in c.flags for c in tables.climbs)
    assert all(ClimbFlag.ALTIMETRIC_DRIFT in r.flags for r in tables.variants)


def test_a_variant_row_reads_g_and_the_central_convention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Les mesures des variantes faussées à la main, pour que les conventions et les
    deux gains diffèrent : le temps en M et le gain pris en mouvement de la ligne sont
    ceux de θc, ni ceux de la première convention, ni ceux de la dernière ; le régime
    se lit sur ``G`` (inchangé), pas sur ``G_M,θc`` (environ divisé par dix)."""
    write_interim(tmp_path)
    real = variant_climbs
    seen: list[Any] = []

    def skewed(track: Any, profile: Any = None, climb: Any = None) -> Any:
        out = tuple(
            tuple(
                dataclasses.replace(
                    m,
                    moving_s=tuple(v + 7.0 * i for i, v in enumerate(m.moving_s)),
                    moving_gain_m=tuple(
                        v / 10 + 3.0 * i for i, v in enumerate(m.moving_gain_m)
                    ),
                )
                for m in measures
            )
            for measures in real(track, profile, climb)
        )
        seen.append(out)
        return out

    monkeypatch.setattr(tables_module, "variant_climbs", skewed)
    tables = build_tables(tmp_path, DEFAULT_SETTINGS, commit=COMMIT)
    walk = [r for r in tables.variants if r.activity_ref == "a1"]
    measures = [m for ms in seen[0] for m in ms]
    k = CENTRAL_CONVENTION_INDEX
    assert [r.moving_s for r in walk] == [m.moving_s[k] for m in measures]
    assert [r.moving_gain_m for r in walk] == [m.moving_gain_m[k] for m in measures]
    for m in measures:
        for values in (m.moving_s, m.moving_gain_m):
            assert values[0] != values[k] != values[-1]
    assert [r.regime for r in walk] == [
        ClimbRegime.SHORT_CLIMB,
        ClimbRegime.LONG_CLIMB,
    ] * len(VARIANTS)
