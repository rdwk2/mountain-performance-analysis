"""Moteur de projection v0 (M3) : lecture de courbe, modèle d'allure, projection."""

from mountain_perf.model.baselines import (
    BASELINE_VERSION,
    BASELINES,
    CONSTANT_SPEED_MS,
    NAISMITH_CLIMB_S_PER_M,
    NAISMITH_SPEED_MS,
    TOBLER_DECAY,
    TOBLER_OFFSET,
    TOBLER_PEAK_MS,
    baseline_paces,
    baseline_timeline,
)
from mountain_perf.model.curve_io import (
    CURVE_PARAMETER_SPECS,
    CurveError,
    CurveReadResult,
    DiscardedBin,
    curve_reference,
    read_curve,
)
from mountain_perf.model.engine import (
    ENGINE_VERSION,
    MODEL_PARAMETER_SPECS,
    PROJECTION_PARAMETER_SPECS,
    ProjectedTimeline,
    ProjectionDiagnostics,
    project,
    project_with_diagnostics,
    projected_timeline,
    route_endpoints,
)
from mountain_perf.model.pace import MAX_SAFE_GRADE, PaceModel

__all__ = [
    "BASELINES",
    "BASELINE_VERSION",
    "CONSTANT_SPEED_MS",
    "CURVE_PARAMETER_SPECS",
    "ENGINE_VERSION",
    "MAX_SAFE_GRADE",
    "MODEL_PARAMETER_SPECS",
    "NAISMITH_CLIMB_S_PER_M",
    "NAISMITH_SPEED_MS",
    "PROJECTION_PARAMETER_SPECS",
    "TOBLER_DECAY",
    "TOBLER_OFFSET",
    "TOBLER_PEAK_MS",
    "CurveError",
    "CurveReadResult",
    "DiscardedBin",
    "PaceModel",
    "ProjectedTimeline",
    "ProjectionDiagnostics",
    "baseline_paces",
    "baseline_timeline",
    "curve_reference",
    "project",
    "project_with_diagnostics",
    "projected_timeline",
    "read_curve",
    "route_endpoints",
]
