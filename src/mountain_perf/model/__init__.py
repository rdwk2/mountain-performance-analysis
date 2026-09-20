"""Moteur de projection v0 (M3) : lecture de courbe, modèle d'allure, projection."""

from mountain_perf.model.curve_io import (
    CURVE_PARAMETER_SPECS,
    CurveError,
    CurveReadResult,
    DiscardedBin,
    curve_reference,
    read_curve,
)

__all__ = [
    "CURVE_PARAMETER_SPECS",
    "CurveError",
    "CurveReadResult",
    "DiscardedBin",
    "curve_reference",
    "read_curve",
]
