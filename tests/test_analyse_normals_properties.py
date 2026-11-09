"""Les normales par des propriétés (AN2-2) : des suites tirées par Hypothesis."""

from __future__ import annotations

import itertools
import math
import statistics
from dataclasses import dataclass
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from mountain_perf.analyse.normals import (
    MEASURE_SPECS,
    NORMAL_PARAMETER_SPECS,
    MeasureNormal,
    MeasureScale,
    NormalMeasure,
    integer_parameter,
    measure_normals,
    rank_ruptures,
    straddles,
    uncertain_days,
    version_ruptures,
)
from mountain_perf.schemas import ParameterSet
from mountain_perf.schemas.processed import NormalAbsence

EXAMPLES = settings(max_examples=150, deadline=None)

values_st = st.one_of(
    st.none(),
    st.sampled_from([float(v) for v in range(10, 130, 10)]),
    st.floats(min_value=0.5, max_value=200.0, allow_nan=False, allow_infinity=False),
)
ranks_st = st.sampled_from([(), (1,), (2,), (1, 2), (3,), (2, 4)])
version_st = st.one_of(st.none(), st.integers(min_value=0, max_value=2))


@dataclass(frozen=True)
class Suite:
    measure: NormalMeasure
    values: list[float | None]
    admitted: list[bool]
    ranks: list[tuple[int, ...]]
    versions: list[int | None] | None
    parameters: ParameterSet


@st.composite
def parameter_sets(draw: Any) -> ParameterSet:
    values: dict[str, float] = {
        "window_days": draw(st.integers(1, 20)),
        "min_admitted_days": draw(st.integers(1, 22)),
        "mad_factor": draw(
            st.one_of(st.just(1.4826), st.floats(0, 3, allow_nan=False))
        ),
        "range_k": draw(st.one_of(st.just(1.0), st.floats(0, 3, allow_nan=False))),
    }
    for spec in NORMAL_PARAMETER_SPECS:
        if spec.name.endswith(
            ("_resolution_ms", "_resolution_bpm", "_resolution_s", "_resolution")
        ) or spec.name.endswith(("_breaths_per_min", "_percent")):
            values[spec.name] = draw(
                st.one_of(st.just(1.0), st.floats(0.001, 5, allow_nan=False))
            )
    return ParameterSet(NORMAL_PARAMETER_SPECS, values)


@st.composite
def suites(draw: Any) -> Suite:
    measure = draw(st.sampled_from(list(NormalMeasure)))
    n = draw(st.integers(0, 60))
    values = [draw(values_st) for _ in range(n)]
    admitted = [v is not None and draw(st.booleans()) for v in values]
    ranks = [draw(ranks_st) for _ in range(n)]
    versions = (
        None
        if MEASURE_SPECS[measure].version is None
        else [draw(version_st) for _ in range(n)]
    )
    return Suite(measure, values, admitted, ranks, versions, draw(parameter_sets()))


def run(suite: Suite) -> tuple[MeasureNormal, ...]:
    return measure_normals(
        suite.measure,
        suite.values,
        suite.admitted,
        suite.ranks,
        suite.versions,
        suite.parameters,
    )


def stats(normal: MeasureNormal) -> tuple[Any, ...]:
    return (
        normal.normal,
        normal.dispersion,
        normal.log_median,
        normal.log_dispersion,
        normal.range_low,
        normal.range_high,
        normal.admitted_days,
        normal.absence,
    )


@given(suites(), st.data())
@EXAMPLES
def test_the_normal_of_day_t_ignores_the_days_from_t_on(
    suite: Suite, data: Any
) -> None:
    n = len(suite.values)
    t = data.draw(st.integers(0, n))
    values = list(suite.values)
    admitted = list(suite.admitted)
    for i in range(t, n):
        values[i] = data.draw(values_st)
        admitted[i] = values[i] is not None and data.draw(st.booleans())
    other = run(
        Suite(
            suite.measure,
            values,
            admitted,
            suite.ranks,
            suite.versions,
            suite.parameters,
        )
    )
    # Les segments et les avertissements ne dépendent, jusqu'à t, que du passé.
    assert run(suite)[: t + 1 if t < n else n] == other[: t + 1 if t < n else n]


@given(suites(), st.data())
@EXAMPLES
def test_it_reads_only_the_admitted_values(suite: Suite, data: Any) -> None:
    values = [
        v if flag else data.draw(values_st)
        for v, flag in zip(suite.values, suite.admitted, strict=True)
    ]
    other = Suite(
        suite.measure,
        values,
        suite.admitted,
        suite.ranks,
        suite.versions,
        suite.parameters,
    )
    assert run(other) == run(suite)


@given(suites(), st.data())
@EXAMPLES
def test_it_is_invariant_by_permutation_of_its_window(suite: Suite, data: Any) -> None:
    n = len(suite.values)
    if n == 0:
        return
    t = data.draw(st.integers(0, n - 1))
    window = integer_parameter(suite.parameters, "window_days")
    days = list(range(max(t - window, 0), t))
    shuffled = data.draw(st.permutations(days)) if days else []
    values = list(suite.values)
    admitted = list(suite.admitted)
    for target, source in zip(days, shuffled, strict=True):
        values[target] = suite.values[source]
        admitted[target] = suite.admitted[source]
    other = Suite(
        suite.measure, values, admitted, suite.ranks, suite.versions, suite.parameters
    )
    assert stats(run(other)[t]) == stats(run(suite)[t])


@given(
    suites(),
    st.floats(0, 10, allow_nan=False),
    st.floats(0, 10, allow_nan=False),
)
@EXAMPLES
def test_the_range_grows_with_k(suite: Suite, one: float, two: float) -> None:
    k1, k2 = min(one, two), max(one, two)

    def with_k(k: float) -> tuple[MeasureNormal, ...]:
        values = {**suite.parameters.values, "range_k": k}
        parameters = ParameterSet(NORMAL_PARAMETER_SPECS, values)
        return run(
            Suite(
                suite.measure,
                suite.values,
                suite.admitted,
                suite.ranks,
                suite.versions,
                parameters,
            )
        )

    for a, b in zip(with_k(k1), with_k(k2), strict=True):
        assert (a.normal, a.dispersion, a.log_median, a.log_dispersion) == (
            b.normal,
            b.dispersion,
            b.log_median,
            b.log_dispersion,
        )
        assert (a.admitted_days, a.absence) == (b.admitted_days, b.absence)
        if a.normal is not None:
            assert a.range_low is not None
            assert a.range_high is not None
            assert b.range_low is not None
            assert b.range_high is not None
            assert (
                b.range_low <= a.range_low <= a.normal <= a.range_high <= b.range_high
            )


@given(suites())
@EXAMPLES
def test_the_segment_grows_by_one_after_each_absent_normal(suite: Suite) -> None:
    normals = run(suite)
    if normals:
        assert normals[0].segment == 0
    for today, tomorrow in itertools.pairwise(normals):
        assert tomorrow.segment - today.segment == (1 if today.normal is None else 0)


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n % 2:
        return ordered[n // 2]
    return (ordered[n // 2 - 1] + ordered[n // 2]) / 2


@given(suites())
@EXAMPLES
def test_the_sliding_window_gives_the_recomputed_normal(suite: Suite) -> None:
    p = suite.parameters
    window = integer_parameter(p, "window_days")
    minimum = integer_parameter(p, "min_admitted_days")
    spec = MEASURE_SPECS[suite.measure]
    log = spec.scale is MeasureScale.LOG
    k, factor, r = p["range_k"], p["mad_factor"], p[spec.resolution]
    for t, normal in enumerate(run(suite)):
        chosen = [
            v
            for v, flag in zip(
                suite.values[max(t - window, 0) : t],
                suite.admitted[max(t - window, 0) : t],
                strict=True,
            )
            if flag and v is not None
        ]
        data = [math.log(v) for v in chosen] if log else [float(v) for v in chosen]
        count = len(data)
        assert normal.admitted_days == count
        if count == 0 or count < minimum:
            expected = (
                NormalAbsence.NO_ADMITTED_DAY
                if count == 0
                else NormalAbsence.TOO_FEW_ADMITTED_DAYS
            )
            assert normal.absence is expected
            assert stats(normal)[:6] == (None,) * 6
            continue
        median = _median(data)
        assert median == statistics.median(data)
        mad = _median([abs(x - median) for x in data])
        if log:
            m = math.exp(median)
            spread = max(factor * mad, math.log1p(r / m))
            assert stats(normal)[:6] == (
                m,
                None,
                median,
                spread,
                math.exp(median - k * spread),
                math.exp(median + k * spread),
            )
        else:
            spread = max(factor * mad, r)
            assert stats(normal)[:6] == (
                median,
                spread,
                None,
                None,
                median - k * spread,
                median + k * spread,
            )
        assert normal.range_low is not None
        assert normal.range_high is not None
        assert normal.normal is not None
        assert normal.range_low <= normal.normal <= normal.range_high


@given(suites())
@EXAMPLES
def test_each_normal_holds_the_invariants_of_a_row(suite: Suite) -> None:
    log = MEASURE_SPECS[suite.measure].scale is MeasureScale.LOG
    for normal in run(suite):
        numbers = stats(normal)[:6]
        assert all(x is None or math.isfinite(x) for x in numbers)
        assert (normal.normal is None) == (normal.absence is not None)
        assert (normal.absence is NormalAbsence.NO_ADMITTED_DAY) == (
            normal.admitted_days == 0
        )
        if normal.normal is None:
            assert numbers == (None,) * 6
            continue
        if log:
            assert normal.log_median is not None
            assert normal.normal == math.exp(normal.log_median)
            assert normal.dispersion is None
            assert normal.log_dispersion is not None
        else:
            assert normal.log_median is None
            assert normal.log_dispersion is None
            assert normal.dispersion is not None


def _expected_rank_ruptures(ranks: list[tuple[int, ...]]) -> list[bool]:
    out = []
    for r in range(len(ranks)):
        before = [ranks[d] for d in range(r) if ranks[d]]
        out.append(
            bool(ranks[r])
            and bool(before)
            and any(x not in before[-1] for x in ranks[r])
        )
    return out


def _expected_version_ruptures(versions: list[int | None]) -> list[bool]:
    out = []
    for r, version in enumerate(versions):
        before = [v for v in versions[:r] if v is not None]
        out.append(version is not None and bool(before) and before[-1] != version)
    return out


def _expected_uncertain(ranks: list[tuple[int, ...]], breaks: list[bool]) -> list[bool]:
    out = []
    for d, day_ranks in enumerate(ranks):
        following = next(
            (later for later in range(d + 1, len(ranks)) if ranks[later]), None
        )
        out.append(
            len(day_ranks) >= 2
            or (
                not day_ranks
                and any(ranks[:d])
                and following is not None
                and breaks[following]
            )
        )
    return out


@given(suites())
@EXAMPLES
def test_ruptures_uncertain_days_and_straddling_follow_their_definition(
    suite: Suite,
) -> None:
    rank_breaks = _expected_rank_ruptures(suite.ranks)
    assert rank_ruptures(suite.ranks) == tuple(rank_breaks)
    version_breaks = [False] * len(suite.ranks)
    if suite.versions is not None:
        version_breaks = _expected_version_ruptures(suite.versions)
        assert version_ruptures(suite.versions) == tuple(version_breaks)
    uncertain = _expected_uncertain(suite.ranks, rank_breaks)
    assert uncertain_days(suite.ranks) == tuple(uncertain)
    breaks = [a or b for a, b in zip(rank_breaks, version_breaks, strict=True)]
    w = integer_parameter(suite.parameters, "window_days")
    expected = [
        any(breaks[max(t - w + 1, 0) : t]) or any(uncertain[max(t - w, 0) : t])
        for t in range(len(breaks))
    ]
    assert straddles(breaks, uncertain, suite.parameters) == tuple(expected)
    normals = run(suite)
    assert [n.rupture for n in normals] == breaks
    assert [n.straddles for n in normals] == expected
