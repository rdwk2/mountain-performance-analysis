"""Le codec commun (brief AN1-0 ; ``docs/decisions/0013``, point 4).

La partie générique de l'écriture canonique et l'enveloppe des documents vivent dans
``mountain_perf.codec``, qui n'importe que la bibliothèque standard ; le registre les
applique à ses types et à son format (``backtest/codec.py``), et
``mountain_perf.backtest`` réexporte les mêmes objets. Les tests du registre tiennent
ses documents et les refus de la partie générique (``tests/test_backtest_codec.py``) ;
ceux-ci tiennent les imports, l'identité des objets réexportés, l'enveloppe sous une
configuration qui n'est pas celle du registre (ordre de ses contrôles et texte exact de
ses refus compris), et des messages de la partie générique : le chemin de la valeur en
tête, dans un tuple de longueur fixe et dans une table, et les annotations non prises
en charge.
"""

import ast
import json
import re
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import cast

import pytest

import mountain_perf
import mountain_perf.backtest as backtest
import mountain_perf.backtest.codec as backtest_codec
import mountain_perf.codec as codec
from mountain_perf.codec import (
    CodecError,
    canonical_bytes,
    decode_contract,
    decode_envelope,
    decode_value,
    encode_contract,
    encode_envelope,
    encode_value,
)
from test_backtest_metrics_reuse import _imported_modules, _package

SOURCE = Path(mountain_perf.__file__).parent
COMMON_MODULE = SOURCE / "codec.py"

GENERIC_NAMES = (
    "NON_FINITE_TEXTS",
    "CodecError",
    "canonical_bytes",
    "content_hash",
    "decode_contract",
    "decode_value",
    "encode_contract",
    "encode_value",
)
"""La partie générique, réexportée par ``backtest/codec.py`` et par
``mountain_perf.backtest``."""


def _imports(path: Path) -> dict[str, set[str]]:
    return _imported_modules(
        ast.parse(path.read_text(encoding="utf-8")), _package(path)
    )


# ---------------------------------------------------------------------------
# Imports et identité
# ---------------------------------------------------------------------------


def test_common_codec_imports_the_standard_library_only() -> None:
    """Aucun module du projet ; les seuls modules de la bibliothèque standard que
    le codec importait déjà."""
    assert set(_imports(COMMON_MODULE)) <= {
        "__future__",
        "collections.abc",
        "dataclasses",
        "datetime",
        "enum",
        "functools",
        "hashlib",
        "json",
        "math",
        "types",
        "typing",
    }


def test_importing_the_common_codec_does_not_load_the_backtest_package() -> None:
    """Le motif du déplacement (``0013``, point 4) : importer le codec commun ne charge
    pas le paquet ``backtest``. Vérifié sur les modules chargés, dans un processus neuf,
    pas seulement sur les imports écrits."""
    code = (
        "import sys\n"
        "import mountain_perf.codec\n"
        "print(sorted(name for name in sys.modules "
        "if name.split('.')[0] == 'mountain_perf'))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    loaded = ast.literal_eval(result.stdout.strip())
    assert "mountain_perf.codec" in loaded
    assert not [name for name in loaded if name.startswith("mountain_perf.backtest")]


def test_backtest_reexports_the_same_objects() -> None:
    """``mountain_perf.backtest`` garde ses exports, et ce sont les objets du codec
    commun : une ``CodecError`` levée par l'un est attrapée sous le nom de l'autre."""
    for name in GENERIC_NAMES:
        common = getattr(codec, name)
        assert getattr(backtest_codec, name) is common, name
        assert getattr(backtest, name) is common, name
    assert set(GENERIC_NAMES) <= set(backtest_codec.__all__)


def test_only_the_registry_documents_import_the_common_codec() -> None:
    """Dans ``src/``, seuls ``backtest/codec.py`` et les documents d'``interim/``
    (``ingest/interim.py``, AN1-1, ``0013``) importent le codec commun."""
    importers = []
    for path in sorted(SOURCE.rglob("*.py")):
        if path == COMMON_MODULE:
            continue
        for module, names in _imports(path).items():
            if module == "mountain_perf.codec" or (
                module == "mountain_perf" and "codec" in names
            ):
                importers.append(path.relative_to(SOURCE).as_posix())
    assert importers == ["backtest/codec.py", "ingest/interim.py"]


# ---------------------------------------------------------------------------
# L'enveloppe sous une autre configuration que celle du registre
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Probe:
    level_m: float
    label: str


@dataclass(frozen=True)
class LateProbe:
    count: int


@dataclass(frozen=True)
class Stray:
    count: int


FIRST_FORMATS: Mapping[type, int] = MappingProxyType({Probe: 3, LateProbe: 5})
"""Deux types admis, aux premiers formats distincts ; ``Stray`` n'est pas admis."""

PROBE = Probe(1234.25, "été")
PROBE_DOCUMENT = (
    '{"type":"Probe","format":5,"data":{"level_m":1234.25,"label":"été"}}'.encode()
)


def _write(value: object, format_version: int) -> bytes:
    return encode_envelope(
        value, format_version=format_version, first_formats=FIRST_FORMATS
    )


def _read[T](data: bytes, expected: type[T], format_version: int) -> T:
    return decode_envelope(
        data, expected, format_version=format_version, first_formats=FIRST_FORMATS
    )


def _whole(message: str) -> str:
    """Le motif d'un message exact, du premier au dernier caractère."""
    return f"^{re.escape(message)}$"


def _raw(type_name: str, format_version: int, data: object) -> bytes:
    """Un document écrit à la main, canonique, sans passer par l'enveloppe."""
    return canonical_bytes({"type": type_name, "format": format_version, "data": data})


def test_envelope_writes_type_format_then_data() -> None:
    assert _write(PROBE, 5) == PROBE_DOCUMENT


def test_envelope_reads_back_at_and_after_the_first_format() -> None:
    assert _read(PROBE_DOCUMENT, Probe, 5) == PROBE
    at_first = _write(PROBE, 3)
    assert at_first.startswith(b'{"type":"Probe","format":3,')
    assert _read(at_first, Probe, 3) == PROBE
    late = LateProbe(7)
    assert _read(_write(late, 5), LateProbe, 5) == late


def test_envelope_names_the_admitted_types_in_their_order() -> None:
    with pytest.raises(
        TypeError,
        match=_whole("Stray n'est pas un type de document (Probe, LateProbe)."),
    ):
        _write(Stray(1), 5)


def test_envelope_refuses_to_write_before_the_first_format() -> None:
    with pytest.raises(
        TypeError,
        match=_whole(
            "LateProbe n'existe qu'à partir du format 5, demandé au format 4."
        ),
    ):
        _write(LateProbe(7), 4)


def test_envelope_refuses_to_read_before_the_first_format() -> None:
    with pytest.raises(
        CodecError,
        match=_whole("document de type 'LateProbe' au format 4, qui ne le connaît pas"),
    ):
        _read(_raw("LateProbe", 4, {"count": 7}), LateProbe, 4)


def test_envelope_reads_only_the_requested_format() -> None:
    with pytest.raises(CodecError, match=_whole("document au format 5, 3 attendu")):
        _read(PROBE_DOCUMENT, Probe, 3)


def test_envelope_reads_only_the_expected_type() -> None:
    with pytest.raises(
        CodecError, match=_whole("document de type 'Probe', 'LateProbe' attendu")
    ):
        _read(PROBE_DOCUMENT, LateProbe, 5)


def test_envelope_refuses_a_non_canonical_document() -> None:
    indented = json.dumps(json.loads(PROBE_DOCUMENT), ensure_ascii=False, indent=1)
    with pytest.raises(CodecError, match=_whole("document d'écriture non canonique")):
        _read(indented.encode(), Probe, 5)


def test_type_absent_from_the_table_counts_from_format_one() -> None:
    """Comportement repris tel quel du registre : un type non admis passe le contrôle
    du format à partir du format 1, puis la réécriture le refuse ; avant le format 1,
    la relecture le refuse."""
    with pytest.raises(
        TypeError,
        match=_whole("Stray n'est pas un type de document (Probe, LateProbe)."),
    ):
        _read(_raw("Stray", 1, {"count": 2}), Stray, 1)
    with pytest.raises(
        CodecError,
        match=_whole("document de type 'Stray' au format 0, qui ne le connaît pas"),
    ):
        _read(_raw("Stray", 0, {"count": 2}), Stray, 0)


def test_envelope_checks_in_the_documented_order() -> None:
    """Sur un document qui viole deux contrôles voisins, le message est celui du
    premier : les clés avant le type, le type avant le format, le format avant le
    premier format qui connaît le type, celui-ci avant le contrat (relecture de la
    PR #24)."""
    extra_key = {"type": "LateProbe", "format": 5, "data": {"count": 7}, "extra": 1}
    with pytest.raises(
        CodecError, match=_whole("document : objet {type, format, data} attendu")
    ):
        _read(canonical_bytes(extra_key), Probe, 5)
    with pytest.raises(
        CodecError, match=_whole("document de type 'Probe', 'LateProbe' attendu")
    ):
        _read(PROBE_DOCUMENT, LateProbe, 4)
    with pytest.raises(CodecError, match=_whole("document au format 5, 4 attendu")):
        _read(_raw("LateProbe", 5, {"count": 7}), LateProbe, 4)
    with pytest.raises(
        CodecError,
        match=_whole("document de type 'LateProbe' au format 4, qui ne le connaît pas"),
    ):
        _read(_raw("LateProbe", 4, {}), LateProbe, 4)


def test_unreadable_envelope_has_the_exact_message() -> None:
    with pytest.raises(
        CodecError, match=_whole("document illisible : JSON en UTF-8 attendu")
    ):
        _read(PROBE_DOCUMENT[:-1], Probe, 5)


# ---------------------------------------------------------------------------
# Messages de la partie générique : le chemin de la valeur en tête (``CodecError``)
# ---------------------------------------------------------------------------


class Shade(StrEnum):
    DARK = "dark"


@dataclass(frozen=True)
class Nested:
    pair: tuple[float, str]
    table: Mapping[str, float]
    day: date
    shade: Shade


@dataclass(frozen=True)
class Outer:
    inner: Nested


GOOD = {"pair": [1.5, "a"], "table": {"k": 2.25}, "day": "2026-01-02", "shade": "dark"}


def _inner(**changes: object) -> dict[str, object]:
    return {"inner": {**GOOD, **changes}}


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (_inner(pair=[1.5, 2]), "inner.pair[1] : texte attendu, reçu entier 2"),
        (
            _inner(pair=[None, "a"]),
            "inner.pair[0] : nombre flottant (ou inf, -inf, nan) attendu, reçu null",
        ),
        (_inner(pair=[1.5, [1]]), "inner.pair[1] : texte attendu, reçu tableau"),
        (
            _inner(table={"k": "x"}),
            "inner.table['k'] : nombre flottant (ou inf, -inf, nan) attendu, reçu "
            "texte 'x'",
        ),
        (_inner(day=5), "inner.day : date attendue (texte), reçu entier 5"),
        (_inner(shade=5), "inner.shade : texte attendu, reçu entier 5"),
        (
            {"inner": {}},
            "inner : champs manquants de Nested : pair, table, day, shade",
        ),
        (
            _inner(x=1, y=2),
            "inner : champs inconnus de Nested : 'x', 'y'",
        ),
    ],
)
def test_decoding_errors_start_with_the_path_of_the_value(
    data: object, message: str
) -> None:
    """La docstring de ``CodecError`` : le message commence par le chemin de la
    valeur, dans un tuple de longueur fixe et dans une table comme dans un champ
    (balayage de mutation de la PR #24)."""
    with pytest.raises(CodecError, match=_whole(message)):
        decode_contract(Outer, data)


@pytest.mark.parametrize(
    ("pair", "table", "message"),
    [
        ((1.5, 2), {"k": 2.25}, "inner.pair[1] : texte attendu, reçu int"),
        ((1.5, "a"), {"k": "x"}, "inner.table['k'] : nombre attendu, reçu str"),
        (
            (1.5, "a"),
            {"k": 10**400},
            "inner.table['k'] : entier hors du domaine des flottants",
        ),
    ],
)
def test_encoding_errors_start_with_the_path_of_the_value(
    pair: object, table: object, message: str
) -> None:
    contract = Outer(
        Nested(
            cast(tuple[float, str], pair),
            cast(Mapping[str, float], table),
            date(2026, 1, 2),
            Shade.DARK,
        )
    )
    with pytest.raises(CodecError, match=_whole(message)):
        encode_contract(contract)


@pytest.mark.parametrize("annotation", [set[int], Mapping[int, float]])
def test_unsupported_annotations_are_named(annotation: object) -> None:
    """Une annotation que le codec ne sait pas écrire est une erreur de
    programmation (``TypeError``), qui la nomme, à l'écriture comme à la relecture."""
    message = f"annotation non prise en charge par l'écriture : {annotation!r}"
    with pytest.raises(TypeError, match=_whole(message)):
        encode_value({}, annotation)
    with pytest.raises(TypeError, match=_whole(message)):
        decode_value(annotation, {})
