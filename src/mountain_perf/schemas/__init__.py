"""Contrats de données : ce qui circule entre les modules.

Aucune entrée/sortie, aucun algorithme. Voir ``docs/DICTIONNAIRE_DONNEES.md``,
généré depuis les docstrings de ce paquet.
"""

from mountain_perf.schemas.activity import Activity, TrackPointStream
from mountain_perf.schemas.common import (
    ELEVATION_RANGE_M,
    GRADE_RANGE,
    HEART_RATE_RANGE_BPM,
    LATITUDE_RANGE_DEG,
    LONGITUDE_RANGE_DEG,
    QUALITY_FLAG_DESCRIPTIONS,
    SPORT_DESCRIPTIONS,
    UTC_OFFSET_RANGE_S,
    QualityFlag,
    SourceRef,
    Sport,
)
from mountain_perf.schemas.parameters import ParameterSet, ParameterSpec
from mountain_perf.schemas.route import (
    POINT_KIND_DESCRIPTIONS,
    NamedPoint,
    PointKind,
    ResolvedPoint,
    Route,
    RouteProfile,
)
from mountain_perf.validation import ContractError

__all__ = [
    "ELEVATION_RANGE_M",
    "GRADE_RANGE",
    "HEART_RATE_RANGE_BPM",
    "LATITUDE_RANGE_DEG",
    "LONGITUDE_RANGE_DEG",
    "POINT_KIND_DESCRIPTIONS",
    "QUALITY_FLAG_DESCRIPTIONS",
    "SPORT_DESCRIPTIONS",
    "UTC_OFFSET_RANGE_S",
    "Activity",
    "ContractError",
    "NamedPoint",
    "ParameterSet",
    "ParameterSpec",
    "PointKind",
    "QualityFlag",
    "ResolvedPoint",
    "Route",
    "RouteProfile",
    "SourceRef",
    "Sport",
    "TrackPointStream",
]
