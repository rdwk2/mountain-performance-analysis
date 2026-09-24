"""Backtest (M4) : observer les sorties réelles avant tout modèle (``0010``)."""

from mountain_perf.backtest.calendar import (
    ORIGIN_LAG,
    PARIS,
    available_at_origin,
    civil_date,
    origin,
)
from mountain_perf.backtest.clocks import (
    CLOCK_HALF_WINDOW_S,
    Qualification,
    WindowMeasures,
    clock_duration_s,
    clock_partition,
    confirm,
    cumulative_s,
    qualify,
    stop_episodes,
    trace_totals,
    window_measures,
)
from mountain_perf.backtest.geometry import (
    ReferenceGeometry,
    reference_geometry,
    trace_route,
)
from mountain_perf.backtest.manifest import (
    ManifestError,
    ManifestReadResult,
    RefusedEntry,
    load_manifest,
)
from mountain_perf.backtest.outings import (
    DOMAIN_MIN_DPLUS_PER_KM,
    RETENTION_LIMIT_S,
    domain_profile_source,
    dplus_per_km,
    group_performances,
    in_domain,
    retain_outings,
)
from mountain_perf.backtest.series import (
    MAX_STEP_S,
    SMOOTHING_HALF_WIDTH,
    TraceSeries,
    build_series,
)

__all__ = [
    "CLOCK_HALF_WINDOW_S",
    "DOMAIN_MIN_DPLUS_PER_KM",
    "MAX_STEP_S",
    "ORIGIN_LAG",
    "PARIS",
    "RETENTION_LIMIT_S",
    "SMOOTHING_HALF_WIDTH",
    "ManifestError",
    "ManifestReadResult",
    "Qualification",
    "ReferenceGeometry",
    "RefusedEntry",
    "TraceSeries",
    "WindowMeasures",
    "available_at_origin",
    "build_series",
    "civil_date",
    "clock_duration_s",
    "clock_partition",
    "confirm",
    "cumulative_s",
    "domain_profile_source",
    "dplus_per_km",
    "group_performances",
    "in_domain",
    "load_manifest",
    "origin",
    "qualify",
    "reference_geometry",
    "retain_outings",
    "stop_episodes",
    "trace_route",
    "trace_totals",
    "window_measures",
]
