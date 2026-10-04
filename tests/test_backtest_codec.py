"""Écriture canonique des contrats (§ 6.2, § 7.1 et § 8.1, test 2, du brief M4b-4 ;
``0010`` D14).

``SAMPLE`` parcourt toutes les formes de la table du § 6.2 : son écriture exacte est un
attendu au bit, et sa relecture rend chaque forme. Puis chaque refus, de relecture et
d'écriture (écrit, donc relu : l'écriture refuse ce que la relecture refuserait), en
``CodecError`` de type exact, le message commençant par le chemin de la valeur.
"""

import dataclasses
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest

from mountain_perf.backtest import (
    NON_FINITE_TEXTS,
    CodecError,
    canonical_bytes,
    content_hash,
    decode_contract,
    decode_value,
    encode_contract,
    encode_value,
)
from mountain_perf.schemas import Scenario, SourceRef
from mountain_perf.validation import ContractError


@dataclass(frozen=True)
class Inner:
    when: date
    label: str | None


@dataclass(frozen=True)
class Sample:
    real: float
    from_int: float
    plus: float
    minus: float
    nan: float
    count: int
    flag: bool
    text: str
    instant: datetime
    scenario: Scenario
    values: tuple[float | None, ...]
    pair: tuple[int, float]
    table: Mapping[str, float]
    inner: Inner
    absent: float | None


SAMPLE = Sample(
    real=0.1,
    from_int=2,
    plus=math.inf,
    minus=-math.inf,
    nan=math.nan,
    count=3,
    flag=True,
    text="été",
    instant=datetime(2026, 10, 3, 15, 0, tzinfo=timezone(timedelta(hours=2))),
    scenario=Scenario.USAGE,
    values=(1.0, None, 1e-320),
    pair=(4, -0.0),
    table={"b": 2.5, "a": 1.0},
    inner=Inner(date(2026, 5, 20), None),
    absent=None,
)
SAMPLE_BYTES = (
    '{"real":0.1,"from_int":2.0,"plus":"inf","minus":"-inf","nan":"nan","count":3,'
    '"flag":true,"text":"été","instant":"2026-10-03T15:00:00+02:00","scenario":"usage",'
    '"values":[1.0,null,1e-320],"pair":[4,-0.0],"table":{"a":1.0,"b":2.5},'
    '"inner":{"when":"2026-05-20","label":null},"absent":null}'
).encode()


def _data() -> dict[str, Any]:
    """La donnée JSON de ``SAMPLE``, à modifier par un test."""
    data = json.loads(SAMPLE_BYTES)
    assert isinstance(data, dict)
    return data


def _read_refused(fragment: str, **changes: Any) -> None:
    with pytest.raises(CodecError, match=re.escape(fragment)):
        decode_value(Sample, _data() | changes)


def _write_refused(fragment: str, **changes: Any) -> None:
    value = dataclasses.replace(SAMPLE, **changes)
    with pytest.raises(CodecError, match=re.escape(fragment)):
        encode_value(value, Sample)


# ---------------------------------------------------------------------------
# SAMPLE : écriture et relecture
# ---------------------------------------------------------------------------


def test_sample_is_written_exactly() -> None:
    """§ 7.1 : l'écriture canonique de ``SAMPLE``, au bit (``0010`` D14)."""
    assert canonical_bytes(encode_contract(SAMPLE)) == SAMPLE_BYTES


def test_sample_is_read_back() -> None:
    """§ 7.1 : NaN, ``±inf``, ``2.0`` flottant, ``-0.0`` signé, sous-normal au bit,
    décalage ``+02:00`` conservé, table triée ; la réécriture redonne les octets."""
    back = decode_contract(Sample, json.loads(SAMPLE_BYTES))
    assert math.isnan(back.nan)
    assert (back.plus, back.minus) == (math.inf, -math.inf)
    assert back.from_int == 2.0
    assert type(back.from_int) is float
    assert back.pair == (4, -0.0)
    assert type(back.pair[0]) is int
    assert math.copysign(1.0, back.pair[1]) == -1.0
    assert back.values == (1.0, None, 1e-320)
    assert back.instant.utcoffset() == timedelta(hours=2)
    assert back.table == {"a": 1.0, "b": 2.5}
    assert back.scenario is Scenario.USAGE
    assert dataclasses.replace(back, nan=SAMPLE.nan) == SAMPLE
    assert canonical_bytes(encode_contract(back)) == SAMPLE_BYTES


def test_non_finite_texts() -> None:
    """§ 6.2 : les trois textes d'un flottant non fini."""
    assert NON_FINITE_TEXTS == ("inf", "-inf", "nan")


def test_canonical_bytes_and_content_hash() -> None:
    """§ 6.2 : ``json.dumps`` sans échappement ASCII, sans espace, sans NaN, en UTF-8 ;
    l'ordre des membres est celui de la donnée ; ``sha256`` en hexadécimal."""
    data = {"b": [1, "é", None], "a": 0.5}
    assert canonical_bytes(data) == '{"b":[1,"é",null],"a":0.5}'.encode()
    assert content_hash(b"") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    with pytest.raises(ValueError, match="JSON compliant"):
        canonical_bytes(math.nan)


# ---------------------------------------------------------------------------
# Refus de relecture
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        (
            {"real": 1},
            "real : nombre flottant (ou inf, -inf, nan) attendu, reçu entier 1",
        ),
        ({"real": "Infinity"}, "real : nombre flottant (ou inf, -inf, nan) attendu"),
        ({"values": [1.0, 2]}, "values[1] : nombre flottant"),
        ({"count": True}, "count : entier attendu, reçu booléen True"),
        ({"count": 1.0}, "count : entier attendu, reçu flottant 1.0"),
        ({"flag": 1}, "flag : booléen attendu, reçu entier 1"),
        ({"text": 1}, "text : texte attendu, reçu entier 1"),
        (
            {"instant": "2026-10-03T15:00:00"},
            "instant : instant sans fuseau '2026-10-03T15:00:00'",
        ),
        ({"instant": 1759496400}, "instant : instant attendu (texte), reçu entier"),
        ({"instant": "hier"}, "instant : instant illisible 'hier'"),
        (
            {"inner": {"when": "2026-13-01", "label": None}},
            "inner.when : date illisible '2026-13-01'",
        ),
        ({"scenario": "USAGE"}, "scenario : valeur inconnue de Scenario : 'USAGE'"),
        ({"pair": [4]}, "pair : tableau de 2 éléments attendu, reçu 1"),
        ({"pair": [4, 0.0, 1.0]}, "pair : tableau de 2 éléments attendu, reçu 3"),
        ({"values": (1.0, None, 1e-320)}, "values : tableau attendu, reçu tuple"),
        ({"inner": []}, "inner : objet attendu pour Inner, reçu tableau"),
        ({"table": []}, "table : objet attendu, reçu tableau"),
    ],
    ids=[
        "int-for-float",
        "Infinity",
        "int-in-float-tuple",
        "bool-for-int",
        "float-for-int",
        "int-for-bool",
        "int-for-text",
        "naive-instant",
        "instant-not-text",
        "unreadable-instant",
        "unreadable-date",
        "member-name",
        "pair-of-1",
        "pair-of-3",
        "python-tuple",
        "array-for-object",
        "array-for-table",
    ],
)
def test_read_refusals(changes: dict[str, Any], fragment: str) -> None:
    """§ 6.2, relecture : chaque refus, le chemin de la valeur en tête du message."""
    _read_refused(fragment, **changes)


def test_missing_field_is_named() -> None:
    """§ 6.2 : un champ manquant est refusé et nommé."""
    data = _data()
    del data["count"]
    with pytest.raises(
        CodecError, match=re.escape("valeur : champs manquants de Sample : count")
    ):
        decode_value(Sample, data)
    _read_refused(
        "inner : champs manquants de Inner : label", inner={"when": "2026-05-20"}
    )


def test_unknown_field_is_named() -> None:
    """§ 6.2 : un champ inconnu est refusé et nommé."""
    _read_refused("valeur : champs inconnus de Sample : 'extra'", extra=1)


def test_contract_error_is_raised_as_is() -> None:
    """§ 6.2 : la relecture reconstruit par le constructeur ; sa ``ContractError``
    remonte telle quelle, sans conversion."""
    data = {
        "kind": "gpx",
        "identifier": "a.gpx",
        "content_hash": "x",
        "retrieved_at": "2026-10-03T12:00:00+00:00",
    }
    with pytest.raises(
        ContractError, match="content_hash doit être un sha256"
    ) as raised:
        decode_contract(SourceRef, data)
    assert raised.type is ContractError


# ---------------------------------------------------------------------------
# Refus d'écriture : écrit, donc relu
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"count": True}, "count : entier attendu, reçu bool"),
        ({"count": 2.0}, "count : entier attendu, reçu float"),
        ({"count": 2.5}, "count : entier attendu, reçu float"),
        ({"real": "1"}, "real : nombre attendu, reçu str"),
        ({"real": True}, "real : nombre attendu, reçu bool"),
        ({"values": (1.0, "x")}, "values[1] : nombre attendu, reçu str"),
        ({"flag": 1}, "flag : booléen attendu, reçu int"),
        ({"text": b"t"}, "text : texte attendu, reçu bytes"),
        ({"instant": datetime(2026, 10, 3, 15, 0)}, "instant : instant sans fuseau"),
        ({"instant": date(2026, 10, 3)}, "instant : instant attendu, reçu date"),
        (
            {"inner": Inner(datetime(2026, 5, 20, tzinfo=UTC), None)},
            "inner.when : date attendue, reçu datetime",
        ),
        ({"values": [1.0, None]}, "values : tuple attendu, reçu list"),
        ({"pair": (4, -0.0, 1.0)}, "pair : tuple de 2 éléments attendu, reçu 3"),
        ({"pair": (4.0, -0.0)}, "pair[0] : entier attendu, reçu float"),
        ({"scenario": "usage"}, "scenario : membre de Scenario attendu, reçu 'usage'"),
        ({"table": {"a": 1.0, 2: 3.0}}, "table : clé non texte 2"),
        ({"table": [("a", 1.0)]}, "table : table attendue, reçu list"),
        ({"inner": (date(2026, 5, 20), None)}, "inner : Inner attendu, reçu tuple"),
    ],
    ids=[
        "bool-for-int",
        "float-2.0-for-int",
        "float-2.5-for-int",
        "text-for-float",
        "bool-for-float",
        "text-in-float-tuple",
        "int-for-bool",
        "bytes-for-text",
        "naive-instant",
        "date-for-instant",
        "datetime-for-date",
        "list-for-tuple",
        "tuple-of-3",
        "float-in-int-pair",
        "text-for-member",
        "non-text-key",
        "list-for-table",
        "tuple-for-dataclass",
    ],
)
def test_write_refusals(changes: dict[str, Any], fragment: str) -> None:
    """§ 6.2, écriture : chaque type voisin que la relecture refuserait est refusé."""
    _write_refused(fragment, **changes)


def test_another_dataclass_is_refused() -> None:
    """§ 6.2 : une dataclass s'écrit sous son type exact."""
    with pytest.raises(
        CodecError, match=re.escape("valeur : Sample attendu, reçu Inner")
    ):
        encode_value(SAMPLE.inner, Sample)


def test_lone_surrogate_text_is_refused_both_ways() -> None:
    """§ 6.2 : un texte à caractère de substitution isolé ne s'encode pas en UTF-8,
    refusé à l'écriture comme à la relecture (écrit en échappement JSON)."""
    _write_refused("text : un texte doit s'encoder en UTF-8", text="a\udcff")
    _read_refused(
        "text : un texte doit s'encoder en UTF-8", text=json.loads('"a\\udcff"')
    )


def test_lone_surrogate_key_is_refused_both_ways() -> None:
    _write_refused("table : un texte doit s'encoder en UTF-8", table={"\udcff": 1.0})
    escaped = json.loads('{"\\udcff": 1.0}')
    _read_refused("table : un texte doit s'encoder en UTF-8", table=escaped)


# ---------------------------------------------------------------------------
# Annotations non prises en charge
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "annotation"),
    [
        (frozenset({"a"}), frozenset[str]),
        ((1.0,), Sequence[float]),
        (1.0, float | int),
        ({1: 1.0}, Mapping[int, float]),
        ((1.0,), tuple),
    ],
    ids=["frozenset", "Sequence", "union-of-two", "int-keys", "bare-tuple"],
)
def test_unsupported_annotation_is_a_type_error(value: object, annotation: Any) -> None:
    """§ 6.2 : toute autre annotation est une erreur de programmation."""
    with pytest.raises(TypeError, match=r"annotation|union"):
        encode_value(value, annotation)
    with pytest.raises(TypeError, match=r"annotation|union"):
        decode_value(annotation, [])


def test_utc_offset_of_the_sample_is_kept() -> None:
    """§ 6.2 : un instant s'écrit avec son décalage d'origine, jamais converti."""
    assert SAMPLE.instant.tzinfo == timezone(timedelta(hours=2))
    assert b'"instant":"2026-10-03T15:00:00+02:00"' in canonical_bytes(
        encode_contract(SAMPLE)
    )


# ---------------------------------------------------------------------------
# Correctifs de la relecture de la PR #19
# ---------------------------------------------------------------------------


def test_non_text_date_and_member_are_refused_at_reading() -> None:
    """§ 6.2, relecture : une date, ou un membre d'énumération, relus d'une donnée
    non texte sont refusés en ``CodecError``, le chemin en tête du message."""
    with pytest.raises(CodecError, match=re.escape("valeur : date attendue (texte)")):
        decode_value(date, 1)
    with pytest.raises(CodecError, match=re.escape("valeur : texte attendu")):
        decode_value(Scenario, 1)


def test_integer_out_of_the_float_range_is_refused() -> None:
    """§ 6.2 : un entier s'écrit dans un champ flottant par ``float(value)`` ; hors du
    domaine des flottants, l'écriture le refuse en ``CodecError``."""
    with pytest.raises(
        CodecError, match=re.escape("valeur : entier hors du domaine des flottants")
    ):
        encode_value(10**400, float)
