"""Invariants des contrats de ``processed/`` (``mountain_perf.schemas.processed``,
``docs/decisions/0014``) : chaque invariant écrit refuse la ligne qui le viole, avec
son propre message.

Les lignes valides viennent de l'``interim/`` synthétique de
``tests/fixtures/processed.py`` ; chaque cas en change un champ, ou plusieurs quand il
faut que seul l'invariant visé soit violé."""

from __future__ import annotations

import dataclasses
import re
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import Any

import pytest

from fixtures.processed import COMMIT, write_interim
from mountain_perf.analyse.athlete import DEFAULT_SETTINGS
from mountain_perf.analyse.tables import Tables, build_tables
from mountain_perf.schemas import ContractError
from mountain_perf.schemas.processed import (
    ActivityRow,
    ClimbFlag,
    ClimbRow,
    ClimbVariantRow,
    ProcessedProvenance,
)

NO_TRACK = "Sans vue, aucun champ de la vue."
NO_RECORDING = "Sans enregistrement, aucun champ de l'enregistrement."


@pytest.fixture(scope="module")
def tables(tmp_path_factory: pytest.TempPathFactory) -> Tables:
    folder = tmp_path_factory.mktemp("interim")
    write_interim(folder)
    return build_tables(folder, DEFAULT_SETTINGS, commit=COMMIT)


@pytest.fixture(scope="module")
def climb(tables: Tables) -> ClimbRow:
    return tables.climbs[-1]


@pytest.fixture(scope="module")
def walk(tables: Tables) -> ActivityRow:
    """``a1`` : enregistrement, vue, deux montées."""
    return tables.activities[0]


@pytest.fixture(scope="module")
def no_track(tables: Tables) -> ActivityRow:
    """``a3`` : un enregistrement sans altitude, donc sans vue."""
    return tables.activities[2]


@pytest.fixture(scope="module")
def no_recording(tables: Tables) -> ActivityRow:
    """``a4`` : sans enregistrement, sans sport."""
    return tables.activities[3]


def _refused(
    row: ClimbRow | ClimbVariantRow | ActivityRow | ProcessedProvenance,
    message: str,
    **changes: Any,
) -> None:
    """``changes`` est refusé, et le message commence par ``message``."""
    with pytest.raises(ContractError, match=f"^{re.escape(message)}"):
        dataclasses.replace(row, **changes)


def test_the_synthetic_rows_are_valid(tables: Tables) -> None:
    assert len(tables.climbs) == 3
    assert len(tables.activities) == 4


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"activity_ref": ""}, "activity_ref doit être fait de lettres"),
        ({"source_activity_type": ""}, "source_activity_type ne doit pas être vide."),
        ({"rank": 0}, "rank doit être >= 1, reçu 0."),
        ({"elapsed_s": 1.0}, "elapsed_s doit valoir end_offset_s − start_offset_s."),
        (
            {"local_start_time": datetime(2024, 3, 9, 9)},
            "local_start_time doit porter un fuseau horaire",
        ),
        (
            {
                "local_start_time": datetime(
                    2024, 3, 9, 9, tzinfo=timezone(timedelta(hours=15))
                )
            },
            "décalage de local_start_time doit être dans",
        ),
        ({"gain_m": float("nan")}, "gain_m doit être fini, reçu nan."),
        ({"gain_m": -1.0}, "gain_m doit être >= 0, reçu -1.0."),
        ({"profile_start_m": -1.0}, "profile_start_m doit être >= 0"),
        ({"profile_end_m": -1.0}, "profile_end_m doit être >= 0"),
        ({"profile_ascent_m": -1.0}, "profile_ascent_m doit être >= 0"),
        (
            {"moving_s_by_convention": (1.0,) * 4},
            "moving_s_by_convention doit avoir 5 valeurs.",
        ),
        (
            {"moving_s_by_convention": (1.0, 1.0, float("inf"), 1.0, 1.0)},
            "moving_s_by_convention doit être fini, reçu inf.",
        ),
        (
            {"stopped_s_by_convention": (0.0, -1.0, 0.0, 0.0, 0.0)},
            "stopped_s_by_convention doit être >= 0, reçu -1.0.",
        ),
        ({"slow_moving_s": -1.0}, "slow_moving_s doit être >= 0"),
        ({"moving_distance_m": -1.0}, "moving_distance_m doit être >= 0"),
        ({"step_s": -1.0}, "step_s doit être >= 0"),
        ({"gap_count": -1}, "gap_count doit être >= 0"),
        ({"timer_stop_count": -1}, "timer_stop_count doit être >= 0"),
        ({"preceding_ascent_m": -1.0}, "preceding_ascent_m doit être >= 0"),
        (
            {"moving_s_by_convention": (0.0, -1.0, 0.0, 0.0, 0.0)},
            "moving_s_by_convention doit être >= 0, reçu -1.0.",
        ),
        (
            {"undetermined_s_by_convention": (0.0, 0.0, 0.0, 0.0, -1.0)},
            "undetermined_s_by_convention doit être >= 0, reçu -1.0.",
        ),
        ({"net_displacement_m": -1.0}, "net_displacement_m doit être >= 0"),
        ({"longest_step_s": -1.0}, "longest_step_s doit être >= 0"),
        ({"gap_s": -1.0}, "gap_s doit être >= 0"),
        ({"auto_pause_count": -1}, "auto_pause_count doit être >= 0"),
        ({"max_vertical_rate_ms": -1.0}, "max_vertical_rate_ms doit être >= 0"),
        ({"preceding_moving_s": -1.0}, "preceding_moving_s doit être >= 0"),
        ({"preceding_descent_m": -1.0}, "preceding_descent_m doit être >= 0"),
        ({"found_fraction": 1.01}, "found_fraction doit être dans [0.0, 1.0]"),
        (
            {"slow_moving_fraction": -0.01},
            "slow_moving_fraction doit être dans [0.0, 1.0]",
        ),
        (
            {"outside_moving_gain_fraction": float("nan")},
            "outside_moving_gain_fraction doit être fini",
        ),
        (
            {"moving_heart_rate_coverage": 2.0},
            "moving_heart_rate_coverage doit être dans [0.0, 1.0]",
        ),
        (
            {"moving_mean_temperature_c": -60.1},
            "moving_mean_temperature_c doit être dans [-60.0, 80.0]",
        ),
        (
            {"flags": (ClimbFlag.SPIKE, ClimbFlag.SPIKE)},
            "flags doit être trié, sans doublon.",
        ),
    ],
)
def test_climb_row_refusals(
    climb: ClimbRow, changes: dict[str, Any], message: str
) -> None:
    _refused(climb, message, **changes)


def test_climb_row_offsets_are_ordered_from_zero(climb: ClimbRow) -> None:
    """``0 <= start_offset_s < end_offset_s`` : ``elapsed_s`` suit, pour que seul cet
    invariant soit violé."""
    message = "Il faut 0 <= start_offset_s < end_offset_s."
    _refused(climb, message, start_offset_s=-1.0, elapsed_s=climb.end_offset_s + 1.0)
    _refused(climb, message, end_offset_s=climb.start_offset_s, elapsed_s=0.0)


def test_climb_row_may_start_at_zero(climb: ClimbRow) -> None:
    row = dataclasses.replace(climb, start_offset_s=0.0, elapsed_s=climb.end_offset_s)
    assert row.start_offset_s == 0.0


def test_climb_row_elapsed_tolerance(climb: ClimbRow) -> None:
    """``elapsed_s`` égale la différence des bornes à 1e-6 s près, en absolu : un écart
    plus petit passe, même sur une montée d'une seconde ; un centième ne passe pas."""
    row = dataclasses.replace(
        climb, start_offset_s=0.0, end_offset_s=1.0, elapsed_s=1.0 + 5e-7
    )
    assert row.elapsed_s == 1.0 + 5e-7
    message = "elapsed_s doit valoir end_offset_s − start_offset_s."
    _refused(climb, message, elapsed_s=climb.elapsed_s + 0.01)


def test_climb_row_elapsed_is_non_negative(climb: ClimbRow) -> None:
    """Sous la tolérance de l'égalité, une durée négative reste refusée."""
    _refused(
        climb,
        "elapsed_s doit être >= 0, reçu -1e-07.",
        start_offset_s=0.0,
        end_offset_s=1e-7,
        elapsed_s=-1e-7,
    )


def test_climb_row_outside_moving_gain_is_signed(climb: ClimbRow) -> None:
    """L'altitude peut baisser pendant S ou U : le rapport est signé, et peut dépasser
    un quand le gain pris en M est négatif."""
    for value in (-0.2, 1.5, None):
        row = dataclasses.replace(climb, outside_moving_gain_fraction=value)
        assert row.outside_moving_gain_fraction == value


def test_climb_row_temperature_may_be_negative(climb: ClimbRow) -> None:
    for value in (-60.0, -5.0, None):
        row = dataclasses.replace(climb, moving_mean_temperature_c=value)
        assert row.moving_mean_temperature_c == value


def test_climb_row_flags_are_sorted(climb: ClimbRow) -> None:
    ordered = tuple(sorted({ClimbFlag.SPIKE, ClimbFlag.NON_HUMAN}))
    assert dataclasses.replace(climb, flags=ordered).flags == ordered
    _refused(climb, "flags doit être trié, sans doublon.", flags=ordered[::-1])


def test_climb_row_local_time_keeps_its_offset(climb: ClimbRow) -> None:
    plus1 = timezone(timedelta(hours=1))
    row = dataclasses.replace(
        climb, local_start_time=datetime(2024, 3, 9, 8, tzinfo=UTC)
    )
    assert row.local_start_time.utcoffset() == timedelta(0)
    row = dataclasses.replace(
        climb, local_start_time=datetime(2024, 3, 9, 9, tzinfo=plus1)
    )
    assert row.local_start_time.utcoffset() == timedelta(hours=1)


class _ConstantOffset(tzinfo):
    """Fuseau de test à décalage constant, qui n'est pas un ``datetime.timezone``.

    Tient lieu d'un ``ZoneInfo`` sans dépendre d'une base de fuseaux (absente sous
    Windows sans ``tzdata``).
    """

    def utcoffset(self, dt: datetime | None) -> timedelta:
        return timedelta(hours=2)

    def dst(self, dt: datetime | None) -> timedelta:
        return timedelta(0)

    def tzname(self, dt: datetime | None) -> str:
        return "TEST+02"


def test_local_times_are_brought_to_a_fixed_offset(
    climb: ClimbRow, walk: ActivityRow
) -> None:
    """Un fuseau qui n'est pas un décalage fixe est ramené à son décalage."""
    instant = datetime(2024, 3, 9, 9, tzinfo=_ConstantOffset())
    fixed = timezone(timedelta(hours=2))
    row = dataclasses.replace(climb, local_start_time=instant)
    assert row.local_start_time.tzinfo == fixed
    assert row.local_start_time == instant
    activity = dataclasses.replace(walk, start_time=instant)
    assert activity.start_time.tzinfo == fixed
    assert activity.start_time == instant


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"activity_ref": ""}, "activity_ref doit être fait de lettres"),
        ({"source_activity_type": ""}, "source_activity_type ne doit pas être vide."),
        (
            {"start_time": datetime(2024, 3, 9, 9)},
            "start_time doit porter un fuseau horaire",
        ),
        ({"index_distance_m": -1.0}, "index_distance_m doit être >= 0"),
        ({"index_ascent_m": float("nan")}, "index_ascent_m doit être fini"),
        ({"profile_ascent_m": -1.0}, "profile_ascent_m doit être >= 0"),
        ({"heart_rate_coverage": 1.5}, "heart_rate_coverage doit être dans [0.0, 1.0]"),
        (
            {"mean_temperature_c": 80.1},
            "mean_temperature_c doit être dans [-60.0, 80.0]",
        ),
        ({"climb_count": 3}, "Les comptes par régime somment climb_count."),
        ({"short_climb_count": 2}, "Les comptes par régime somment climb_count."),
        (
            {"flagged_climb_count": 3},
            "Montées marquées ou instables : au plus climb_count.",
        ),
        (
            {"unstable_climb_count": 3},
            "Montées marquées ou instables : au plus climb_count.",
        ),
        ({"has_recording": False}, NO_RECORDING),
        (
            {"moving_s_by_convention": (1.0,) * 4},
            "moving_s_by_convention doit avoir 5 valeurs.",
        ),
    ],
)
def test_activity_row_refusals(
    walk: ActivityRow, changes: dict[str, Any], message: str
) -> None:
    _refused(walk, message, **changes)


def test_every_regime_counts(walk: ActivityRow) -> None:
    """Les six comptes par régime somment ``climb_count``, ski compris."""
    row = dataclasses.replace(
        walk,
        ski_touring_count=1,
        short_ski_touring_count=1,
        climb_count=walk.climb_count + 2,
    )
    assert row.climb_count == walk.climb_count + 2


def test_a_track_needs_a_recording(walk: ActivityRow) -> None:
    """Une vue sans enregistrement : les champs de l'enregistrement retirés, pour que
    seul cet invariant soit violé."""
    _refused(
        walk,
        "Une vue demande un enregistrement.",
        has_recording=False,
        session_count=None,
        device_manufacturer=None,
        device_product=None,
        software_version=None,
        barometer=None,
        external_heart_rate_sensor=None,
        mean_temperature_c=None,
    )


def test_closure_elevation_and_temperature_may_be_negative(walk: ActivityRow) -> None:
    row = dataclasses.replace(walk, closure_elevation_m=-3.0, mean_temperature_c=-5.0)
    assert (row.closure_elevation_m, row.mean_temperature_c) == (-3.0, -5.0)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("track_offset_s", 0.0),
        ("track_elapsed_s", 1.0),
        ("profile_distance_m", 1.0),
        ("profile_ascent_m", 1.0),
        ("profile_descent_m", 1.0),
        ("moving_s_by_convention", (1.0,) * 5),
        ("stopped_s_by_convention", (1.0,) * 5),
        ("undetermined_s_by_convention", (1.0,) * 5),
        ("step_s", 1.0),
        ("longest_step_s", 1.0),
        ("gap_count", 0),
        ("gap_s", 0.0),
        ("timer_stop_count", 0),
        ("auto_pause_count", 0),
        ("position_gap_ascent_m", 0.0),
        ("loop", False),
        ("closure_elevation_m", 0.0),
        ("closure_rate_ms", 0.0),
        ("altimetric_drift", False),
        ("barometric", True),
        ("mean_heart_rate_bpm", 140.0),
        ("heart_rate_coverage", 1.0),
    ],
)
def test_no_track_field_without_a_track(
    no_track: ActivityRow, name: str, value: object
) -> None:
    _refused(no_track, NO_TRACK, **{name: value})


def test_no_climb_without_a_track(no_track: ActivityRow) -> None:
    _refused(no_track, "Sans vue, aucune montée.", climb_count=1, short_climb_count=1)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("session_count", 1),
        ("device_manufacturer", "garmin"),
        ("device_product", 1),
        ("software_version", 1.0),
        ("barometer", True),
        ("external_heart_rate_sensor", False),
        ("mean_temperature_c", 12.0),
    ],
)
def test_no_recording_field_without_a_recording(
    no_recording: ActivityRow, name: str, value: object
) -> None:
    _refused(no_recording, NO_RECORDING, **{name: value})


def test_without_sport_a_view_refusal(no_recording: ActivityRow) -> None:
    assert no_recording.sport is None
    _refused(no_recording, "Sans sport, view_refusal est présent.", view_refusal=None)


def test_a_known_sport_may_still_have_no_view(walk: ActivityRow) -> None:
    assert walk.sport is not None
    assert dataclasses.replace(walk, view_refusal=None).view_refusal is None


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"interim_sha256": "0" * 63},
            "interim_sha256 : 64 chiffres hexadécimaux minuscules.",
        ),
        (
            {"interim_sha256": "A" * 64},
            "interim_sha256 : 64 chiffres hexadécimaux minuscules.",
        ),
        (
            {"interim_sha256": "X" * 64},
            "interim_sha256 : 64 chiffres hexadécimaux minuscules.",
        ),
        ({"package_version": ""}, "package_version ne doit pas être vide."),
        ({"commit": "0" * 12}, "commit : 40 ou 64 chiffres hexadécimaux minuscules."),
        ({"commit": "0" * 39}, "commit : 40 ou 64 chiffres hexadécimaux minuscules."),
        ({"commit": "0" * 41}, "commit : 40 ou 64 chiffres hexadécimaux minuscules."),
        ({"commit": "0" * 63}, "commit : 40 ou 64 chiffres hexadécimaux minuscules."),
        ({"commit": "A" * 40}, "commit : 40 ou 64 chiffres hexadécimaux minuscules."),
        ({"commit": "g" * 40}, "commit : 40 ou 64 chiffres hexadécimaux minuscules."),
        ({"commit": ""}, "commit : 40 ou 64 chiffres hexadécimaux minuscules."),
        (
            {"reference_vertical_speed_ms": 0.0},
            "reference_vertical_speed_ms doit être > 0.",
        ),
        (
            {"reference_vertical_speed_ms": float("inf")},
            "reference_vertical_speed_ms doit être fini",
        ),
        (
            {"barometer_products": ("b:1", "a:1")},
            "barometer_products doit être trié, sans doublon.",
        ),
        (
            {"barometer_products": ("a:1", "a:1")},
            "barometer_products doit être trié, sans doublon.",
        ),
        (
            {"parameters": (("b", 1.0), ("a", 1.0))},
            "parameters doit être trié par nom, sans doublon.",
        ),
        (
            {"parameters": (("a", 1.0), ("a", 2.0))},
            "parameters doit être trié par nom, sans doublon.",
        ),
        ({"parameters": (("a", float("nan")),)}, "a doit être fini, reçu nan."),
        ({"activity_count": -1}, "Les comptes sont positifs ou nuls."),
        ({"climb_count": -1}, "Les comptes sont positifs ou nuls."),
        ({"variant_climb_count": -1}, "Les comptes sont positifs ou nuls."),
    ],
)
def test_provenance_refusals(
    tables: Tables, changes: dict[str, Any], message: str
) -> None:
    _refused(tables.provenance, message, **changes)


def test_provenance_is_a_value(tables: Tables) -> None:
    provenance = tables.provenance
    assert dataclasses.replace(provenance) == provenance
    assert isinstance(provenance, ProcessedProvenance)


def test_provenance_of_empty_tables(tables: Tables) -> None:
    """Un ``interim/`` sans activité donne des tables vides : les comptes nuls
    passent."""
    empty = dataclasses.replace(tables.provenance, activity_count=0, climb_count=0)
    assert (empty.activity_count, empty.climb_count) == (0, 0)


@pytest.mark.parametrize("commit", ["0123456789abcdef" * 2 + "01234567", "f" * 64])
def test_provenance_takes_both_lengths_of_commit(tables: Tables, commit: str) -> None:
    """Un commit SHA-1 (40 chiffres) ou SHA-256 (64 chiffres) de git."""
    assert dataclasses.replace(tables.provenance, commit=commit).commit == commit


# --- la table des variantes (AN1-2c) --------------------------------------------


@pytest.fixture(scope="module")
def variant_row(tables: Tables) -> ClimbVariantRow:
    """La montée longue d'``a1`` sous la première variante."""
    row = tables.variants[1]
    assert row.activity_ref == "a1"
    return row


def test_the_synthetic_variant_rows_are_valid(tables: Tables) -> None:
    assert len(tables.variants) == 36
    assert all(isinstance(r, ClimbVariantRow) for r in tables.variants)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"activity_ref": ".."},
            "activity_ref doit être fait de lettres et de chiffres ASCII",
        ),
        ({"activity_ref": "a/1"}, "activity_ref doit être fait de lettres"),
        ({"variant": ""}, "variant ne doit pas être vide."),
        ({"variant": "  "}, "variant ne doit pas être vide."),
        ({"start_offset_s": float("nan")}, "start_offset_s doit être fini"),
        ({"end_offset_s": float("inf")}, "end_offset_s doit être fini"),
        ({"gain_m": float("nan")}, "gain_m doit être fini"),
        ({"moving_gain_m": float("-inf")}, "moving_gain_m doit être fini"),
        ({"moving_s": float("nan")}, "moving_s doit être fini"),
        (
            {"start_offset_s": -1.0},
            "Il faut 0 <= start_offset_s < end_offset_s.",
        ),
        (
            {"start_offset_s": 100.0, "end_offset_s": 100.0},
            "Il faut 0 <= start_offset_s < end_offset_s.",
        ),
        (
            {"start_offset_s": 101.0, "end_offset_s": 100.0},
            "Il faut 0 <= start_offset_s < end_offset_s.",
        ),
        ({"gain_m": -0.5}, "gain_m doit être >= 0, reçu -0.5."),
        ({"moving_s": -1.0}, "moving_s doit être >= 0, reçu -1.0."),
        (
            {"flags": (ClimbFlag.SPIKE, ClimbFlag.NON_BAROMETRIC)},
            "flags doit être trié, sans doublon.",
        ),
        (
            {"flags": (ClimbFlag.SPIKE, ClimbFlag.SPIKE)},
            "flags doit être trié, sans doublon.",
        ),
    ],
)
def test_variant_row_refusals(
    variant_row: ClimbVariantRow, changes: dict[str, Any], message: str
) -> None:
    _refused(variant_row, message, **changes)


def test_variant_row_limits(variant_row: ClimbVariantRow) -> None:
    """Un départ à zéro, un gain et un temps nuls, un gain en M négatif (signé, comme
    celui de la montée), une montée sans strate d'altitude : acceptés."""
    row = dataclasses.replace(
        variant_row,
        start_offset_s=0.0,
        gain_m=0.0,
        moving_s=0.0,
        moving_gain_m=-1.0,
        altitude_stratum=None,
    )
    assert (row.start_offset_s, row.gain_m, row.moving_s) == (0.0, 0.0, 0.0)
    assert row.moving_gain_m == -1.0
    assert row.altitude_stratum is None
