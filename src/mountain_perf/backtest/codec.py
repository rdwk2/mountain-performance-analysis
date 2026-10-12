"""Écriture canonique des contrats en JSON, et sa relecture (M4b-4).

Protocole : ``docs/decisions/0010`` D14. Un contrat se convertit **d'après les
annotations de ses champs** (``typing.get_type_hints``, ``dataclasses.fields``), sans
table par type ; la relecture reconstruit le contrat par son constructeur, qui revalide
tous ses invariants. L'écriture refuse ce que la relecture refuserait (écrit, donc
relu) : un contrat stocké laisse passer des types voisins (une ``datetime`` pour une
``date``, un flottant pour un ``int``, la valeur texte d'un ``StrEnum``), qui écrits
feraient refuser leur ligne à la relecture.

Écriture canonique : ``json.dumps`` sans échappement ASCII, sans espace, sans NaN,
encodée en UTF-8 ; les membres d'un objet dans l'ordre des champs, les clés d'une table
triées ; un flottant non fini s'écrit en texte (``NON_FINITE_TEXTS``), un instant garde
son décalage d'origine.
"""

from __future__ import annotations

import dataclasses
import functools
import hashlib
import json
import math
import types
import typing
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum

from mountain_perf.schemas import (
    REGISTRY_FORMAT_VERSION,
    CalibratedScenarioScores,
    OutingObservation,
    RepeatabilityReference,
    ScenarioScores,
)

DOCUMENT_TYPES: tuple[type, ...] = (
    OutingObservation,
    ScenarioScores,
    RepeatabilityReference,
    CalibratedScenarioScores,
)
"""Les contrats que le registre range en documents, nommés par leur empreinte
(``0010`` D14) : l'observation d'une sortie, les scores d'un scénario (prévision
comprise), la référence D8 d'un parcours ; depuis le format 2, les scores calés d'un
modèle dans un scénario (prévision non calée et calages compris, M4c-2)."""

DOCUMENT_FIRST_FORMAT: Mapping[type, int] = types.MappingProxyType(
    {
        OutingObservation: 1,
        ScenarioScores: 1,
        RepeatabilityReference: 1,
        CalibratedScenarioScores: 2,
    }
)
"""Le premier format du registre qui connaît chaque type de document (précision de
D14, M4c-2) : un document ne s'écrit ni ne se relit à un format antérieur."""

NON_FINITE_TEXTS: tuple[str, ...] = ("inf", "-inf", "nan")
"""Les textes d'un flottant non fini : JSON n'a pas de nombre pour eux."""


class CodecError(ValueError):
    """Une valeur ne correspond pas à son annotation, ou un document est illisible.

    Le message commence par le **chemin** de la valeur (``segments[3].times_s[2]``, ou
    ``valeur`` à la racine). Sous-classe de ``ValueError``, comme ``ContractError`` :
    une ``ContractError`` levée par un constructeur à la relecture remonte telle
    quelle, sans conversion.
    """


def _where(path: str) -> str:
    return path or "valeur"


def _field_path(path: str, name: str) -> str:
    return f"{path}.{name}" if path else name


def _item_path(path: str, key: object) -> str:
    return f"{_where(path)}[{key!r}]"


def _error(path: str, detail: str) -> CodecError:
    return CodecError(f"{_where(path)} : {detail}")


def _kind(value: object) -> str:
    """Le nom du type Python d'une valeur, pour les messages."""
    return type(value).__name__


_JSON_KINDS: tuple[tuple[type, str], ...] = (
    (bool, "booléen"),
    (int, "entier"),
    (float, "flottant"),
    (str, "texte"),
    (list, "tableau"),
    (dict, "objet"),
)


def _json_kind(data: object) -> str:
    """La nature JSON d'une donnée relue, pour les messages."""
    if data is None:
        return "null"
    for cls, name in _JSON_KINDS:
        if isinstance(data, cls):
            return f"{name} {data!r}" if cls in (bool, int, float, str) else name
    return _kind(data)


def _require_utf8(text: str, path: str) -> None:
    """Refuse un texte qui porte un caractère de substitution isolé."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise _error(path, "un texte doit s'encoder en UTF-8") from None


@functools.cache
def _fields(cls: typing.Any) -> tuple[tuple[str, object], ...]:
    """Les champs d'une dataclass et leurs annotations résolues, dans l'ordre."""
    hints = typing.get_type_hints(cls)
    return tuple((field.name, hints[field.name]) for field in dataclasses.fields(cls))


def _optional(annotation: object) -> object:
    """``X`` de ``X | None`` ; toute autre union lève ``TypeError``."""
    args = typing.get_args(annotation)
    others = [arg for arg in args if arg is not type(None)]
    if len(args) != 2 or len(others) != 1:
        raise TypeError(f"union non prise en charge par l'écriture : {annotation!r}")
    return others[0]


def _unsupported(annotation: object) -> TypeError:
    return TypeError(f"annotation non prise en charge par l'écriture : {annotation!r}")


def encode_value(value: object, annotation: object, path: str = "") -> object:
    """``value`` en donnée JSON d'après ``annotation`` (``0010`` D14).

    ``CodecError`` si la valeur ne correspond pas à l'annotation, y compris un type
    voisin que la relecture refuserait ; ``TypeError`` pour une annotation non prise en
    charge (erreur de programmation).
    """
    if annotation is bool:
        if not isinstance(value, bool):
            raise _error(path, f"booléen attendu, reçu {_kind(value)}")
        return value
    if annotation is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise _error(path, f"entier attendu, reçu {_kind(value)}")
        return value
    if annotation is str:
        if not isinstance(value, str):
            raise _error(path, f"texte attendu, reçu {_kind(value)}")
        _require_utf8(value, path)
        return value
    if annotation is float:
        return _encode_float(value, path)
    if annotation is datetime:
        if not isinstance(value, datetime):
            raise _error(path, f"instant attendu, reçu {_kind(value)}")
        offset = value.utcoffset()
        if offset is None:
            raise _error(path, "instant sans fuseau")
        # Un décalage à fraction de seconde se relit sans elle sous certaines versions
        # de Python, à l'identique sous d'autres : refusé quelle que soit la version.
        if offset % timedelta(seconds=1):
            raise _error(
                path,
                "instant dont le décalage horaire n'est pas un nombre entier de "
                "secondes",
            )
        return value.isoformat()
    if annotation is date:
        if type(value) is not date:
            raise _error(path, f"date attendue, reçu {_kind(value)}")
        return value.isoformat()
    if isinstance(annotation, type) and issubclass(annotation, StrEnum):
        if not isinstance(value, annotation):
            name = annotation.__name__
            raise _error(path, f"membre de {name} attendu, reçu {value!r}")
        return value.value
    if isinstance(annotation, type) and dataclasses.is_dataclass(annotation):
        if type(value) is not annotation:
            raise _error(path, f"{annotation.__name__} attendu, reçu {_kind(value)}")
        return {
            name: encode_value(getattr(value, name), hint, _field_path(path, name))
            for name, hint in _fields(annotation)
        }
    origin = typing.get_origin(annotation)
    if origin is tuple:
        return _encode_tuple(value, annotation, path)
    if origin is Mapping:
        return _encode_mapping(value, annotation, path)
    if origin in (types.UnionType, typing.Union):
        inner = _optional(annotation)
        return None if value is None else encode_value(value, inner, path)
    raise _unsupported(annotation)


def _encode_float(value: object, path: str) -> object:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _error(path, f"nombre attendu, reçu {_kind(value)}")
    try:
        number = float(value)
    except OverflowError:
        raise _error(path, "entier hors du domaine des flottants") from None
    if math.isfinite(number):
        return number
    if math.isnan(number):
        return "nan"
    return "inf" if number > 0 else "-inf"


def _encode_tuple(value: object, annotation: object, path: str) -> list[object]:
    if not isinstance(value, tuple):
        raise _error(path, f"tuple attendu, reçu {_kind(value)}")
    args = typing.get_args(annotation)
    if len(args) == 2 and args[1] is Ellipsis:
        return [
            encode_value(item, args[0], _item_path(path, i))
            for i, item in enumerate(value)
        ]
    if len(value) != len(args):
        raise _error(path, f"tuple de {len(args)} éléments attendu, reçu {len(value)}")
    return [
        encode_value(item, hint, _item_path(path, i))
        for i, (item, hint) in enumerate(zip(value, args, strict=True))
    ]


def _encode_mapping(value: object, annotation: object, path: str) -> dict[str, object]:
    key_type, value_type = typing.get_args(annotation)
    if key_type is not str:
        raise _unsupported(annotation)
    if not isinstance(value, Mapping):
        raise _error(path, f"table attendue, reçu {_kind(value)}")
    keys: list[str] = []
    for key in value:
        if not isinstance(key, str):
            raise _error(path, f"clé non texte {key!r}")
        _require_utf8(key, path)
        keys.append(key)
    return {
        key: encode_value(value[key], value_type, _item_path(path, key))
        for key in sorted(keys)
    }


def decode_value(annotation: object, data: object, path: str = "") -> object:
    """La valeur d'annotation ``annotation`` relue depuis la donnée JSON ``data``.

    Une dataclass est reconstruite par son constructeur (ses invariants revalidés :
    une ``ContractError`` remonte telle quelle) ; ``CodecError`` si la donnée ne
    correspond pas à l'annotation ; ``TypeError`` pour une annotation non prise en
    charge.
    """
    if annotation is bool:
        if not isinstance(data, bool):
            raise _error(path, f"booléen attendu, reçu {_json_kind(data)}")
        return data
    if annotation is int:
        if isinstance(data, bool) or not isinstance(data, int):
            raise _error(path, f"entier attendu, reçu {_json_kind(data)}")
        return data
    if annotation is str:
        if not isinstance(data, str):
            raise _error(path, f"texte attendu, reçu {_json_kind(data)}")
        _require_utf8(data, path)
        return data
    if annotation is float:
        return _decode_float(data, path)
    if annotation is datetime:
        return _decode_instant(data, path)
    if annotation is date:
        if not isinstance(data, str):
            raise _error(path, f"date attendue (texte), reçu {_json_kind(data)}")
        try:
            return date.fromisoformat(data)
        except ValueError:
            raise _error(path, f"date illisible {data!r}") from None
    if isinstance(annotation, type) and issubclass(annotation, StrEnum):
        if not isinstance(data, str):
            raise _error(path, f"texte attendu, reçu {_json_kind(data)}")
        try:
            return annotation(data)
        except ValueError:
            raise _error(
                path, f"valeur inconnue de {annotation.__name__} : {data!r}"
            ) from None
    if isinstance(annotation, type) and dataclasses.is_dataclass(annotation):
        return _decode_dataclass(annotation, data, path)
    origin = typing.get_origin(annotation)
    if origin is tuple:
        return _decode_tuple(annotation, data, path)
    if origin is Mapping:
        return _decode_mapping(annotation, data, path)
    if origin in (types.UnionType, typing.Union):
        inner = _optional(annotation)
        return None if data is None else decode_value(inner, data, path)
    raise _unsupported(annotation)


def _decode_float(data: object, path: str) -> float:
    if isinstance(data, float):
        return data
    if isinstance(data, str) and data in NON_FINITE_TEXTS:
        return float(data)
    raise _error(
        path,
        f"nombre flottant (ou {', '.join(NON_FINITE_TEXTS)}) attendu, reçu "
        f"{_json_kind(data)}",
    )


def _decode_instant(data: object, path: str) -> datetime:
    if not isinstance(data, str):
        raise _error(path, f"instant attendu (texte), reçu {_json_kind(data)}")
    try:
        instant = datetime.fromisoformat(data)
    except ValueError:
        raise _error(path, f"instant illisible {data!r}") from None
    if instant.utcoffset() is None:
        raise _error(path, f"instant sans fuseau {data!r}")
    try:
        instant.astimezone(UTC)
    except OverflowError:
        raise _error(path, f"instant hors du domaine des dates {data!r}") from None
    return instant


def _decode_dataclass(cls: typing.Any, data: object, path: str) -> object:
    if not isinstance(data, dict):
        kind = _json_kind(data)
        raise _error(path, f"objet attendu pour {cls.__name__}, reçu {kind}")
    fields = _fields(cls)
    names = [name for name, _ in fields]
    missing = [name for name in names if name not in data]
    if missing:
        raise _error(path, f"champs manquants de {cls.__name__} : {', '.join(missing)}")
    unknown = [repr(key) for key in data if key not in names]
    if unknown:
        raise _error(path, f"champs inconnus de {cls.__name__} : {', '.join(unknown)}")
    values = {
        name: decode_value(hint, data[name], _field_path(path, name))
        for name, hint in fields
    }
    return cls(**values)


def _decode_tuple(annotation: object, data: object, path: str) -> tuple[object, ...]:
    if not isinstance(data, list):
        raise _error(path, f"tableau attendu, reçu {_json_kind(data)}")
    args = typing.get_args(annotation)
    if len(args) == 2 and args[1] is Ellipsis:
        return tuple(
            decode_value(args[0], item, _item_path(path, i))
            for i, item in enumerate(data)
        )
    if len(data) != len(args):
        raise _error(path, f"tableau de {len(args)} éléments attendu, reçu {len(data)}")
    return tuple(
        decode_value(hint, item, _item_path(path, i))
        for i, (item, hint) in enumerate(zip(data, args, strict=True))
    )


def _decode_mapping(annotation: object, data: object, path: str) -> dict[str, object]:
    key_type, value_type = typing.get_args(annotation)
    if key_type is not str:
        raise _unsupported(annotation)
    if not isinstance(data, dict):
        raise _error(path, f"objet attendu, reçu {_json_kind(data)}")
    for key in data:
        _require_utf8(key, path)
    return {
        key: decode_value(value_type, item, _item_path(path, key))
        for key, item in data.items()
    }


def encode_contract(value: object) -> object:
    """L'écriture d'un contrat : ``encode_value(value, type(value))``."""
    return encode_value(value, type(value))


def decode_contract[T](cls: type[T], data: object) -> T:
    """Le contrat ``cls`` relu depuis ``data`` : ``decode_value(cls, data)``."""
    return typing.cast(T, decode_value(cls, data))


def canonical_bytes(data: object) -> bytes:
    """L'écriture canonique d'une donnée JSON : sans échappement ASCII, sans espace,
    sans NaN, en UTF-8."""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return text.encode("utf-8")


def content_hash(data: bytes) -> str:
    """L'empreinte ``sha256`` d'octets, en hexadécimal minuscule."""
    return hashlib.sha256(data).hexdigest()


def encode_document(
    value: object, format_version: int = REGISTRY_FORMAT_VERSION
) -> bytes:
    """Le document d'un contrat de ``DOCUMENT_TYPES`` au format ``format_version`` :
    l'écriture canonique de ``{"type": <nom de la classe>, "format": format_version,
    "data": …}`` ; ``TypeError`` pour un autre type, ou pour un format antérieur au
    premier qui connaît le type (``DOCUMENT_FIRST_FORMAT`` ; précision de D14,
    M4c-2)."""
    cls = type(value)
    if cls not in DOCUMENT_TYPES:
        names = ", ".join(document.__name__ for document in DOCUMENT_TYPES)
        raise TypeError(f"{cls.__name__} n'est pas un type de document ({names}).")
    first = DOCUMENT_FIRST_FORMAT[cls]
    if format_version < first:
        raise TypeError(
            f"{cls.__name__} n'existe qu'à partir du format {first}, demandé au "
            f"format {format_version}."
        )
    return canonical_bytes(
        {
            "type": cls.__name__,
            "format": format_version,
            "data": encode_contract(value),
        }
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
    try:
        envelope = json.loads(data.decode("utf-8"))
    except ValueError:
        # UnicodeDecodeError, JSONDecodeError, et l'entier de plus de 4 300 chiffres.
        raise CodecError("document illisible : JSON en UTF-8 attendu") from None
    if not isinstance(envelope, dict) or set(envelope) != {"type", "format", "data"}:
        raise CodecError("document : objet {type, format, data} attendu")
    if envelope["type"] != expected.__name__:
        raise CodecError(
            f"document de type {envelope['type']!r}, {expected.__name__!r} attendu"
        )
    if envelope["format"] != format_version:
        raise CodecError(
            f"document au format {envelope['format']!r}, {format_version} attendu"
        )
    if format_version < DOCUMENT_FIRST_FORMAT.get(expected, 1):
        raise CodecError(
            f"document de type {expected.__name__!r} au format {format_version}, qui "
            "ne le connaît pas"
        )
    value = decode_contract(expected, envelope["data"])
    if encode_document(value, format_version) != data:
        raise CodecError("document d'écriture non canonique")
    return value
