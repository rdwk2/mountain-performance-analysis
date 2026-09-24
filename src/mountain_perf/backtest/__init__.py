"""Backtest (M4) : observer les sorties réelles avant tout modèle (``0010``)."""

from mountain_perf.backtest.calendar import (
    ORIGIN_LAG,
    PARIS,
    available_at_origin,
    civil_date,
    origin,
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
    "DOMAIN_MIN_DPLUS_PER_KM",
    "MAX_STEP_S",
    "ORIGIN_LAG",
    "PARIS",
    "RETENTION_LIMIT_S",
    "SMOOTHING_HALF_WIDTH",
    "ManifestError",
    "ManifestReadResult",
    "RefusedEntry",
    "TraceSeries",
    "available_at_origin",
    "build_series",
    "civil_date",
    "domain_profile_source",
    "dplus_per_km",
    "group_performances",
    "in_domain",
    "load_manifest",
    "origin",
    "retain_outings",
]
