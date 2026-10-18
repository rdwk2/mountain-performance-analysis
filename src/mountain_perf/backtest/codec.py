"""Documents du registre (M4b-4) : les types que le registre range en documents, le
premier format qui connaît chacun, leur écriture et leur relecture (``0010`` D14).

L'écriture canonique et l'enveloppe des documents vivent dans le module commun
``mountain_perf.codec`` depuis AN1-0 (``docs/decisions/0013``, point 4) : ce module les
applique aux types et au format du registre, et réexporte la partie générique, pour que
``mountain_perf.backtest`` garde ses exports.
"""

from __future__ import annotations

import types
from collections.abc import Mapping

from mountain_perf.codec import (
    NON_FINITE_TEXTS,
    CodecError,
    canonical_bytes,
    content_hash,
    decode_contract,
    decode_envelope,
    decode_value,
    encode_contract,
    encode_envelope,
    encode_value,
)
from mountain_perf.schemas import (
    REGISTRY_FORMAT_VERSION,
    Admission,
    CalibratedScenarioScores,
    OutingBands,
    OutingObservation,
    RepeatabilityReference,
    ScenarioScores,
    SensitivityOutcome,
)

__all__ = [
    "DOCUMENT_FIRST_FORMAT",
    "DOCUMENT_TYPES",
    "NON_FINITE_TEXTS",
    "CodecError",
    "canonical_bytes",
    "content_hash",
    "decode_contract",
    "decode_document",
    "decode_value",
    "encode_contract",
    "encode_document",
    "encode_value",
]

DOCUMENT_TYPES: tuple[type, ...] = (
    OutingObservation,
    ScenarioScores,
    RepeatabilityReference,
    CalibratedScenarioScores,
    Admission,
    OutingBands,
    SensitivityOutcome,
)
"""Les contrats que le registre range en documents, nommés par leur empreinte
(``0010`` D14) : l'observation d'une sortie, les scores d'un scénario (prévision
comprise), la référence D8 d'un parcours ; depuis le format 2, les scores calés d'un
modèle dans un scénario (prévision non calée et calages compris, M4c-2) ; depuis le
format 3, le document d'admission d'une expérience (M4c-3) ; depuis le format 4, les
fourchettes d'une sortie (M4d-2) ; depuis le format 5, le document de sensibilité
(M4d-3)."""

DOCUMENT_FIRST_FORMAT: Mapping[type, int] = types.MappingProxyType(
    {
        OutingObservation: 1,
        ScenarioScores: 1,
        RepeatabilityReference: 1,
        CalibratedScenarioScores: 2,
        Admission: 3,
        OutingBands: 4,
        SensitivityOutcome: 5,
    }
)
"""Le premier format du registre qui connaît chaque type de document (précision de
D14, M4c-2) : un document ne s'écrit ni ne se relit à un format antérieur."""


def encode_document(
    value: object, format_version: int = REGISTRY_FORMAT_VERSION
) -> bytes:
    """Le document d'un contrat de ``DOCUMENT_TYPES`` au format ``format_version`` :
    l'écriture canonique de ``{"type": <nom de la classe>, "format": format_version,
    "data": …}`` ; ``TypeError`` pour un autre type, ou pour un format antérieur au
    premier qui connaît le type (``DOCUMENT_FIRST_FORMAT`` ; précision de D14,
    M4c-2)."""
    return encode_envelope(
        value, format_version=format_version, first_formats=DOCUMENT_FIRST_FORMAT
    )


def decode_document[T](
    data: bytes, expected: type[T], format_version: int = REGISTRY_FORMAT_VERSION
) -> T:
    """Le contrat ``expected`` relu depuis les octets d'un document **du format
    ``format_version``** — celui de l'événement qui le cite (précision de D14, M4c-2).

    Dans cet ordre : JSON en UTF-8 ; un objet aux clés exactement ``type``,
    ``format``, ``data`` ; le type ; le format, égal à ``format_version`` ; un format
    qui connaît le type (``DOCUMENT_FIRST_FORMAT``) ; le contrat ; enfin, la
    réécriture du contrat relu, au même format, redonne les octets lus (sinon :
    écriture non canonique).
    """
    return decode_envelope(
        data,
        expected,
        format_version=format_version,
        first_formats=DOCUMENT_FIRST_FORMAT,
    )
