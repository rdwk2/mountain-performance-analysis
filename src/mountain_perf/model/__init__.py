"""Moteur de projection v0 (M3) : lecture de courbe, modèle d'allure, projection."""

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
    ProjectionDiagnostics,
    project,
    project_with_diagnostics,
    route_endpoints,
)
from mountain_perf.model.pace import MAX_SAFE_GRADE, PaceModel

__all__ = [
    "CURVE_PARAMETER_SPECS",
    "ENGINE_VERSION",
    "MAX_SAFE_GRADE",
    "MODEL_PARAMETER_SPECS",
    "PROJECTION_PARAMETER_SPECS",
    "CurveError",
    "CurveReadResult",
    "DiscardedBin",
    "PaceModel",
    "ProjectionDiagnostics",
    "curve_reference",
    "project",
    "project_with_diagnostics",
    "read_curve",
    "route_endpoints",
]
