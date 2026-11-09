"""Les normales d'une suite de jours (``mountain_perf.analyse.normals``, AN2-2) :
paramètres, mesures, normale du jour t, fenêtre, segments, contrôles des entrées. Des
suites inventées : l'entrée i est le jour i d'une table (le premier est le jour 0)."""

from __future__ import annotations

import inspect
import math
import re
from collections.abc import Sequence
from typing import Any, cast

import pytest

import mountain_perf.schemas.processed as processed_module
from fixtures.day_rows import admitted_measure, complete_row, measure_columns
from mountain_perf.analyse.normals import (
    INTEGER_PARAMETERS,
    MEASURE_SPECS,
    NORMAL_PARAMETER_SPECS,
    MeasureNormal,
    MeasureScale,
    MeasureSpec,
    NormalMeasure,
    integer_parameter,
    measure_normals,
    segments,
)
from mountain_perf.schemas import AlgorithmVersions, ContractError, ParameterSet
from mountain_perf.schemas.processed import AdmissionRefusal, DayRow, NormalAbsence

DEFAULT = ParameterSet(NORMAL_PARAMETER_SPECS)
SIX = list(NormalMeasure)
HRV, HR = NormalMeasure.HRV, NormalMeasure.RESTING_HR
SLEEP, STRESS = NormalMeasure.MEASURED_SLEEP, NormalMeasure.NIGHT_STRESS
RESP, SPO2 = NormalMeasure.NIGHT_RESPIRATION, NormalMeasure.NIGHT_SPO2


def params(**values: float) -> ParameterSet:
    return ParameterSet(NORMAL_PARAMETER_SPECS, values)


def run(
    measure: NormalMeasure,
    values: Sequence[float | None],
    admitted: Sequence[bool] | None = None,
    parameters: ParameterSet = DEFAULT,
    ranks: Sequence[tuple[int, ...]] | None = None,
    versions: Sequence[int | None] | None = None,
) -> tuple[MeasureNormal, ...]:
    """Les normales : chaque valeur présente admise par défaut, aucun rang, une version
    constante pour une mesure qu'une version rompt."""
    n = len(values)
    if admitted is None:
        admitted = [v is not None for v in values]
    if ranks is None:
        ranks = [()] * n
    if versions is None and MEASURE_SPECS[measure].version is not None:
        versions = [1] * n
    return measure_normals(measure, values, admitted, ranks, versions, parameters)


def after(
    measure: NormalMeasure, values: Sequence[float], parameters: ParameterSet = DEFAULT
) -> MeasureNormal:
    """La normale du jour placé juste après ``values``, lui-même sans valeur."""
    return run(measure, [*values, None], parameters=parameters)[-1]


def test_the_eleven_parameters() -> None:
    assert [
        (s.name, s.unit, s.default, s.minimum, s.maximum)
        for s in NORMAL_PARAMETER_SPECS
    ] == [
        ("window_days", "d", 28.0, 1.0, 365.0),
        ("min_admitted_days", "d", 14.0, 1.0, 365.0),
        ("mad_factor", None, 1.4826, 0.0, 10.0),
        ("range_k", None, 1.0, 0.0, 10.0),
        ("exclude_altitude_stay", None, 1.0, 0.0, 1.0),
        ("hrv_resolution_ms", "ms", 1.0, 0.001, 100.0),
        ("resting_hr_resolution_bpm", "bpm", 1.0, 0.001, 100.0),
        ("measured_sleep_resolution_s", "s", 60.0, 0.001, 3600.0),
        ("night_stress_resolution", None, 1.0, 0.001, 100.0),
        ("night_respiration_resolution_breaths_per_min", "/min", 1.0, 0.001, 100.0),
        ("night_spo2_resolution_percent", "%", 1.0, 0.001, 100.0),
    ]
    assert all(s.description.strip() for s in NORMAL_PARAMETER_SPECS)
    assert INTEGER_PARAMETERS == (
        "window_days",
        "min_admitted_days",
        "exclude_altitude_stay",
    )


def test_the_contracts_name_declared_parameters() -> None:
    named = set(
        re.findall(r"normal\.([a-z_0-9]+)", inspect.getsource(processed_module))
    )
    assert named == {"min_admitted_days", "exclude_altitude_stay"}
    assert named <= {s.name for s in NORMAL_PARAMETER_SPECS}


def _into_row(measure: NormalMeasure, normal: MeasureNormal) -> DayRow:
    """La ligne ``complete`` dont les colonnes de ``measure`` portent ``normal``."""
    columns = measure_columns(
        measure.value,
        admitted=True,
        refusal=None,
        normal=normal.normal,
        low=normal.range_low,
        high=normal.range_high,
        dispersion=normal.log_dispersion if measure is HRV else normal.dispersion,
        log_median=normal.log_median,
        admitted_days=normal.admitted_days,
        absence=normal.absence,
        segment=normal.segment,
        rupture=normal.rupture,
        straddles=normal.straddles,
    )
    value = admitted_measure(measure.value)
    return complete_row(**{**value, **columns})


TEN = [50.0, 52.0, 47.0, 50.0, 51.0, 49.0, 48.0, 53.0, 50.0, 46.0]


@pytest.mark.parametrize("measure", SIX)
@pytest.mark.parametrize("spec", NORMAL_PARAMETER_SPECS, ids=lambda s: s.name)
@pytest.mark.parametrize("bound", ["minimum", "maximum"])
def test_each_parameter_at_its_bounds(measure: Any, spec: Any, bound: str) -> None:
    value = getattr(spec, bound)
    parameters = params(**{spec.name: value})
    if spec.name in INTEGER_PARAMETERS:
        result = integer_parameter(parameters, spec.name)
        assert result == value
        assert type(result) is int
    days = 400 if spec.name in ("window_days", "min_admitted_days") else 60
    series = [TEN[i % 10] for i in range(days)]
    normals = run(measure, series, parameters=parameters)
    for normal in normals:
        _into_row(measure, normal)
    window = integer_parameter(parameters, "window_days")
    minimum = integer_parameter(parameters, "min_admitted_days")
    assert any(n.normal is not None for n in normals) is (window >= minimum)


@pytest.mark.parametrize("spec", NORMAL_PARAMETER_SPECS, ids=lambda s: s.name)
def test_just_beyond_each_bound_is_refused(spec: Any) -> None:
    for value in (
        math.nextafter(spec.minimum, -math.inf),
        math.nextafter(spec.maximum, math.inf),
    ):
        with pytest.raises(ContractError, match=spec.name):
            params(**{spec.name: value})


def test_the_message_at_the_minimum_of_the_window() -> None:
    with pytest.raises(
        ContractError,
        match=(
            r"^window_days doit être dans \[1\.0, 365\.0\], "
            r"reçu 0\.9999999999999999\.$"
        ),
    ):
        params(window_days=math.nextafter(1.0, -math.inf))


@pytest.mark.parametrize("measure", SIX)
def test_a_window_shorter_than_the_minimum_never_has_a_normal(
    measure: NormalMeasure,
) -> None:
    normals = run(
        measure, [50.0] * 20, parameters=params(window_days=4, min_admitted_days=5)
    )
    assert all(n.normal is None for n in normals)
    assert normals[0].absence is NormalAbsence.NO_ADMITTED_DAY
    assert all(n.absence is NormalAbsence.TOO_FEW_ADMITTED_DAYS for n in normals[1:])
    assert max(n.admitted_days for n in normals) == 4
    equal = run(
        measure, [50.0] * 20, parameters=params(window_days=5, min_admitted_days=5)
    )
    assert all(n.normal is None for n in equal[:5])
    assert all(n.normal is not None for n in equal[5:])


def test_integer_parameters() -> None:
    assert integer_parameter(DEFAULT, "window_days") == 28
    assert type(integer_parameter(DEFAULT, "window_days")) is int
    assert (
        integer_parameter(params(exclude_altitude_stay=0.0), "exclude_altitude_stay")
        == 0
    )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("window_days", 27.5),
        ("min_admitted_days", 13.5),
        ("exclude_altitude_stay", 0.5),
    ],
)
def test_a_non_integer_count_is_refused(name: str, value: float) -> None:
    parameters = params(**{name: value})
    with pytest.raises(ValueError, match=name):
        integer_parameter(parameters, name)
    with pytest.raises(ValueError, match=name):
        measure_normals(HR, [50.0], [True], [()], None, parameters)


def test_the_message_of_a_non_integer_window() -> None:
    with pytest.raises(
        ValueError,
        match=r"^Le paramètre window_days doit être entier \(un compte ou un "
        r"interrupteur\), reçu 27\.5\.$",
    ):
        integer_parameter(params(window_days=27.5), "window_days")


def test_an_undeclared_name_is_never_read_as_zero() -> None:
    with pytest.raises(KeyError):
        integer_parameter(DEFAULT, "window_day")


@pytest.mark.parametrize(
    "parameters",
    [ParameterSet((NORMAL_PARAMETER_SPECS[0],)), {"window_days": 28.0}],
    ids=["autre jeu", "dictionnaire"],
)
def test_parameters_are_a_set_of_the_declared_specs(parameters: Any) -> None:
    with pytest.raises(
        ValueError,
        match=r"^parameters doit être un ParameterSet de NORMAL_PARAMETER_SPECS",
    ):
        measure_normals(HRV, [], [], [], None, parameters)


def test_the_measures_are_the_prefixes_of_the_columns() -> None:
    assert [m.value for m in NormalMeasure] == [
        "hrv",
        "resting_hr",
        "measured_sleep",
        "night_stress",
        "night_respiration",
        "night_spo2",
    ]
    names = [
        name[: -len("_admitted")]
        for name in DayRow.__dataclass_fields__
        if name.endswith("_admitted")
    ]
    assert names == [m.value for m in NormalMeasure]


def test_measure_specs() -> None:
    assert dict(MEASURE_SPECS) == {
        HRV: MeasureSpec(MeasureScale.LOG, "hrv_resolution_ms", None, True),
        HR: MeasureSpec(MeasureScale.LINEAR, "resting_hr_resolution_bpm", None, False),
        SLEEP: MeasureSpec(
            MeasureScale.LINEAR, "measured_sleep_resolution_s", "sleep_version", True
        ),
        STRESS: MeasureSpec(
            MeasureScale.LINEAR, "night_stress_resolution", "sleep_version", True
        ),
        RESP: MeasureSpec(
            MeasureScale.LINEAR,
            "night_respiration_resolution_breaths_per_min",
            "respiration_version",
            True,
        ),
        SPO2: MeasureSpec(
            MeasureScale.LINEAR, "night_spo2_resolution_percent", None, True
        ),
    }
    assert list(MEASURE_SPECS) == list(NormalMeasure)
    declared = {s.name for s in NORMAL_PARAMETER_SPECS}
    for spec in MEASURE_SPECS.values():
        assert spec.resolution in declared
        if spec.version is not None:
            assert spec.version in AlgorithmVersions.__dataclass_fields__
            assert spec.version in DayRow.__dataclass_fields__


def test_the_hrv_example_centred_on_54_6_ms() -> None:
    d = 0.1 / 1.4826
    logs = [4.0] * 4 + [4.0 - d] * 5 + [4.0 + d] * 5
    normal = after(HRV, [math.exp(x) for x in logs])
    assert normal.log_median == pytest.approx(4.0, abs=1e-12)
    assert normal.log_dispersion == pytest.approx(0.1, abs=1e-12)
    assert normal.normal == pytest.approx(54.6, abs=0.005)
    assert normal.range_low == pytest.approx(49.4, abs=0.005)
    assert normal.range_high == pytest.approx(60.34, abs=0.005)
    assert normal.dispersion is None
    assert normal.admitted_days == 14
    assert normal.absence is None


HR_14 = [47.0] * 4 + [50.0] * 6 + [52.0] * 4


def test_a_linear_normal() -> None:
    normal = after(HR, HR_14)
    assert normal.normal == 50.0
    assert type(normal.normal) is float
    assert normal.dispersion == pytest.approx(2.9652, abs=1e-12)
    assert normal.range_low == pytest.approx(47.0348, abs=1e-12)
    assert normal.range_high == pytest.approx(52.9652, abs=1e-12)
    assert normal.log_median is None
    assert normal.log_dispersion is None
    other = after(HR, [52.0, 47.0, 50.0, 52.0, 50.0, 47.0, 50.0] * 2)
    assert other.normal == 50.0
    assert other.dispersion == pytest.approx(2.9652, abs=1e-12)


def test_an_even_median_and_the_floor() -> None:
    normal = after(HR, [50.0] * 7 + [51.0] * 7)
    assert normal.normal == 50.5
    assert normal.dispersion == 1.0
    assert (normal.range_low, normal.range_high) == (49.5, 51.5)


@pytest.mark.parametrize(
    ("measure", "name", "resolution"),
    [
        (HR, "resting_hr_resolution_bpm", 2.0),
        (SLEEP, "measured_sleep_resolution_s", 3.0),
        (STRESS, "night_stress_resolution", 4.0),
        (RESP, "night_respiration_resolution_breaths_per_min", 5.0),
        (SPO2, "night_spo2_resolution_percent", 6.0),
    ],
)
def test_a_null_mad_gives_the_resolution_under_its_own_name(
    measure: NormalMeasure, name: str, resolution: float
) -> None:
    others = {
        "resting_hr_resolution_bpm": 2.0,
        "measured_sleep_resolution_s": 3.0,
        "night_stress_resolution": 4.0,
        "night_respiration_resolution_breaths_per_min": 5.0,
        "night_spo2_resolution_percent": 6.0,
        "hrv_resolution_ms": 7.0,
    }
    assert others[name] == resolution
    normal = after(measure, [100.0] * 14, params(**others))
    assert normal.normal == 100.0
    assert normal.dispersion == resolution
    assert (normal.range_low, normal.range_high) == (100 - resolution, 100 + resolution)


def test_the_floor_of_the_hrv() -> None:
    normal = after(HRV, [50.0] * 14)
    assert normal.log_median == pytest.approx(math.log(50), abs=1e-15)
    assert normal.log_dispersion == pytest.approx(0.019802627296, abs=1e-12)
    assert normal.normal == pytest.approx(50, rel=1e-15)
    assert normal.range_low == pytest.approx(49.019607843, abs=1e-8)
    assert normal.range_high == pytest.approx(51.0, abs=1e-12)
    wide = after(HRV, [50.0] * 14, params(hrv_resolution_ms=5))
    assert wide.log_dispersion == pytest.approx(math.log(1.1), abs=1e-12)
    assert wide.range_low == pytest.approx(50 / 1.1, abs=1e-9)
    assert wide.range_high == pytest.approx(55.0, abs=1e-9)


def test_the_centre_of_the_hrv_is_the_exponential_of_the_median_log() -> None:
    normal = after(HRV, [40.0] * 7 + [90.0] * 7)
    assert normal.normal == pytest.approx(60, rel=1e-12)
    assert normal.log_median == pytest.approx(math.log(60), rel=1e-15)
    assert normal.log_median is not None
    assert normal.normal == math.exp(normal.log_median)
    assert normal.log_dispersion == pytest.approx(0.6011425693, abs=1e-9)
    assert normal.range_low == pytest.approx(32.891096332, abs=1e-6)
    assert normal.range_high == pytest.approx(109.452113230, abs=1e-6)


def test_range_k_widens_the_range() -> None:
    two = after(HR, HR_14, params(range_k=2))
    assert two.range_low == pytest.approx(44.0696, abs=1e-12)
    assert two.range_high == pytest.approx(55.9304, abs=1e-12)
    assert two.dispersion == pytest.approx(2.9652, abs=1e-12)
    zero = after(HR, HR_14, params(range_k=0))
    assert (zero.range_low, zero.normal, zero.range_high) == (50.0, 50.0, 50.0)
    assert zero.dispersion == pytest.approx(2.9652, abs=1e-12)
    d = 0.1 / 1.4826
    logs = [4.0] * 4 + [4.0 - d] * 5 + [4.0 + d] * 5
    hrv = after(HRV, [math.exp(x) for x in logs], params(range_k=2))
    assert hrv.range_low == pytest.approx(math.exp(3.8), abs=1e-9)
    assert hrv.range_high == pytest.approx(math.exp(4.2), abs=1e-9)
    assert (round(hrv.range_low or 0, 3), round(hrv.range_high or 0, 3)) == (
        44.701,
        66.686,
    )


def test_the_factor_of_the_mad() -> None:
    assert after(HR, HR_14, params(mad_factor=1)).dispersion == 2.0
    assert after(HR, HR_14, params(mad_factor=0)).dispersion == 1.0
    three = after(HR, HR_14, params(mad_factor=3))
    assert three.dispersion == 6.0
    assert (three.range_low, three.range_high) == (44.0, 56.0)


def _forty(admitted: set[int], overrides: dict[int, float] | None = None) -> list[Any]:
    """Quarante jours : 60 aux jours admis, 200 ailleurs ; ``overrides`` les change."""
    values = [60.0 if d in admitted else 200.0 for d in range(40)]
    for day, value in (overrides or {}).items():
        values[day] = value
    return values


THIRTEEN = set(range(21, 34))
T = 35


def _at_t(
    admitted: set[int],
    overrides: dict[int, float] | None = None,
    parameters: ParameterSet = DEFAULT,
) -> MeasureNormal:
    flags = [d in admitted for d in range(40)]
    return run(HR, _forty(admitted, overrides), flags, parameters)[T]


def test_the_first_day_of_the_window_is_included() -> None:
    day7 = _at_t(THIRTEEN | {7})
    assert (day7.admitted_days, day7.absence, day7.normal) == (14, None, 60.0)
    changed = dict.fromkeys([7, *range(21, 27)], 100.0)
    mixed = _at_t(THIRTEEN | {7}, changed, params(min_admitted_days=13))
    assert (mixed.admitted_days, mixed.normal) == (14, 80.0)


def test_the_day_before_the_window_is_out() -> None:
    day6 = _at_t(THIRTEEN | {6})
    assert day6.admitted_days == 13
    assert day6.absence is NormalAbsence.TOO_FEW_ADMITTED_DAYS
    assert day6.normal is None
    valued = _at_t(THIRTEEN | {6}, {6: 500.0}, params(min_admitted_days=13))
    assert (valued.admitted_days, valued.normal) == (13, 60.0)


def test_the_day_itself_is_never_in_its_window() -> None:
    assert _at_t(THIRTEEN | {T}).admitted_days == 13
    other = _at_t(THIRTEEN | {T, 7}, {T: 500.0})
    assert (other.admitted_days, other.normal) == (14, 60.0)


def test_the_minimum_of_admitted_days() -> None:
    assert _at_t(THIRTEEN).absence is NormalAbsence.TOO_FEW_ADMITTED_DAYS
    assert _at_t(set(range(20, 34))).absence is None
    flags = [d in THIRTEEN for d in range(40)]
    thirteen = run(HR, [60.0] * 40, flags, params(min_admitted_days=13))[T]
    assert (thirteen.admitted_days, thirteen.absence, thirteen.normal) == (
        13,
        None,
        60.0,
    )
    none = _at_t(set())
    assert (none.admitted_days, none.absence) == (0, NormalAbsence.NO_ADMITTED_DAY)
    one = _at_t({20})
    assert (one.admitted_days, one.absence) == (1, NormalAbsence.TOO_FEW_ADMITTED_DAYS)


def test_at_the_start_of_the_table_the_window_is_shorter() -> None:
    normals = run(HR, [60.0] * 40)
    assert [n.admitted_days for n in normals] == [min(t, 28) for t in range(40)]
    assert normals[0].absence is NormalAbsence.NO_ADMITTED_DAY
    assert all(n.absence is NormalAbsence.TOO_FEW_ADMITTED_DAYS for n in normals[1:14])
    assert all(n.absence is None and n.normal == 60.0 for n in normals[14:])
    short = run(
        STRESS,
        [10.0, 20.0, 30.0, 40.0, 50.0],
        parameters=params(window_days=3, min_admitted_days=2),
    )
    assert [n.normal for n in short] == [None, None, 15.0, 20.0, 30.0]
    assert [n.admitted_days for n in short] == [0, 1, 2, 3, 3]


def test_only_admitted_values_make_the_normal() -> None:
    values: list[float | None] = []
    flags: list[bool] = []
    for _ in range(14):
        values += [60.0, 300.0]
        flags += [True, False]
    values.append(None)
    flags.append(False)
    first = run(HR, values, flags)
    assert (first[-1].normal, first[-1].admitted_days) == (60.0, 14)
    empty: list[float | None] = [
        v if f else None for v, f in zip(values, flags, strict=True)
    ]
    assert run(HR, empty, flags) == first


def test_the_segment_counts_absent_normals_before_the_row() -> None:
    no, few = NormalAbsence.NO_ADMITTED_DAY, NormalAbsence.TOO_FEW_ADMITTED_DAYS
    assert segments([no, few, None, None, few, None]) == (0, 1, 2, 2, 2, 3)
    assert segments([]) == ()
    with pytest.raises(ValueError, match=r"absences\[1\]"):
        segments(cast(Any, [None, "no_admitted_day"]))
    normals = run(
        SPO2,
        [5.0] * 8,
        [d in (0, 1, 2, 5, 6) for d in range(8)],
        params(window_days=2, min_admitted_days=2),
    )
    assert [n.admitted_days for n in normals] == [0, 1, 2, 2, 1, 0, 1, 2]
    assert [d for d, n in enumerate(normals) if n.normal is None] == [0, 1, 4, 5, 6]
    assert [n.segment for n in normals] == [0, 1, 2, 2, 2, 3, 4, 5]


@pytest.mark.parametrize("measure", SIX)
def test_each_normal_enters_a_row(measure: NormalMeasure) -> None:
    days = 80
    values = [40.0 + (7 * d) % 23 for d in range(days)]
    flags = [(d % 9) not in (3, 4) and not 30 <= d <= 49 for d in range(days)]
    ranks = [(1,) if d <= 39 else (1, 2) if d == 40 else (2,) for d in range(days)]
    versions = (
        None
        if MEASURE_SPECS[measure].version is None
        else [1 if d < 60 else 2 for d in range(days)]
    )
    normals = measure_normals(measure, values, flags, ranks, versions, DEFAULT)
    assert {n.absence for n in normals} == {
        None,
        NormalAbsence.NO_ADMITTED_DAY,
        NormalAbsence.TOO_FEW_ADMITTED_DAYS,
    }
    assert any(n.rupture for n in normals)
    assert any(n.straddles for n in normals)
    for normal in normals:
        _into_row(measure, normal)
        if normal.normal is not None:
            if measure is HRV:
                assert normal.dispersion is None
            else:
                assert normal.log_median is None
                assert normal.log_dispersion is None


VALID = {
    "values": [25200.0, None, 24000.0],
    "admitted": [True, False, True],
    "ranks": [(1,), (), (1, 2)],
    "versions": [1, None, 1],
}


def call(**changes: Any) -> tuple[MeasureNormal, ...]:
    entries = {**VALID, **changes}
    return measure_normals(
        changes.pop("measure", SLEEP),
        entries["values"],
        entries["admitted"],
        entries["ranks"],
        entries["versions"],
        DEFAULT,
    )


def test_valid_entries_pass() -> None:
    assert len(call()) == 3
    assert measure_normals(SLEEP, [], [], [], [], DEFAULT) == ()


@pytest.mark.parametrize(
    ("changes", "pattern"),
    [
        ({"values": [1.0, 2.0]}, "values=2"),
        ({"admitted": [True, False]}, "admitted=2"),
        ({"ranks": [(), ()]}, "ranks=2"),
        ({"versions": [1, 1]}, "versions=2"),
        ({"values": [25200.0, None, math.nan]}, r"values\[2\]"),
        ({"values": [25200.0, None, math.inf]}, r"values\[2\]"),
        ({"values": [25200.0, True, 24000.0]}, r"values\[1\]"),
        ({"values": [25200.0, "1", 24000.0]}, r"values\[1\]"),
        ({"admitted": [True, 0, True]}, r"admitted\[1\]"),
        ({"admitted": [True, True, True]}, r"admitted\[1\]"),
        ({"ranks": [(1,), (), (2, 1)]}, r"ranks\[2\]"),
        ({"ranks": [(1,), (), (1, 1)]}, r"ranks\[2\]"),
        ({"ranks": [(0,), (), (1,)]}, r"ranks\[0\]"),
        ({"ranks": [(1,), [], (1,)]}, r"ranks\[1\]"),
        ({"ranks": [(1,), (True,), (1,)]}, r"ranks\[1\]"),
        ({"versions": [1, None, -1]}, r"versions\[2\]"),
        ({"versions": [1, True, 1]}, r"versions\[1\]"),
        ({"versions": [1, 1.0, 1]}, r"versions\[1\]"),
        ({"versions": None}, "versions manque"),
    ],
)
def test_each_faulty_entry_is_named(changes: dict[str, Any], pattern: str) -> None:
    with pytest.raises(ValueError, match=pattern):
        call(**changes)


def test_the_full_message_of_the_lengths() -> None:
    with pytest.raises(
        ValueError,
        match=r"^Les suites doivent avoir la même longueur \(un jour par entrée\) : "
        r"values=2, admitted=3, ranks=3, versions=3\.$",
    ):
        call(values=[1.0, 2.0])


def test_the_measure_is_a_measure() -> None:
    with pytest.raises(ValueError, match="measure"):
        measure_normals(cast(Any, "measured_sleep"), [], [], [], [], DEFAULT)


def test_versions_for_a_measure_without_family() -> None:
    with pytest.raises(ValueError, match="versions doit être None"):
        measure_normals(HRV, [50.0], [True], [()], [1], DEFAULT)


def test_an_admitted_hrv_is_strictly_positive() -> None:
    with pytest.raises(ValueError, match=r"values\[0\]"):
        run(HRV, [0.0], [True])
    normals = run(HRV, [0.0, 50.0], [False, True])
    assert [n.admitted_days for n in normals] == [0, 0]


def test_an_integer_value_is_a_value() -> None:
    normal = after(HR, [50] * 14)
    assert normal.normal == 50.0
    assert type(normal.normal) is float


def test_refusal_columns_are_those_of_a_row() -> None:
    assert complete_row(**admitted_measure("hrv")).hrv_refusal is None
    assert AdmissionRefusal.NO_VALUE.value == "no_value"
