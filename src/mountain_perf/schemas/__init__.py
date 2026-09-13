"""Contrats de données : ce qui circule entre les modules.

Aucune entrée/sortie, aucun algorithme. Voir ``docs/DICTIONNAIRE_DONNEES.md``,
généré depuis les docstrings de ce paquet.
"""

from mountain_perf.schemas.common import (
    ELEVATION_RANGE_M,
    LATITUDE_RANGE_DEG,
    LONGITUDE_RANGE_DEG,
    QUALITY_FLAG_DESCRIPTIONS,
    SPORT_DESCRIPTIONS,
    QualityFlag,
    SourceRef,
    Sport,
)
from mountain_perf.schemas.parameters import ParameterSet, ParameterSpec
from mountain_perf.validation import ContractError

__all__ = [
    "ELEVATION_RANGE_M",
    "LATITUDE_RANGE_DEG",
    "LONGITUDE_RANGE_DEG",
    "QUALITY_FLAG_DESCRIPTIONS",
    "SPORT_DESCRIPTIONS",
    "ContractError",
    "ParameterSet",
    "ParameterSpec",
    "QualityFlag",
    "SourceRef",
    "Sport",
]
