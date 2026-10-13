"""Le codec commun (brief AN1-0 ; ``docs/decisions/0013``, point 4).

La partie générique de l'écriture canonique et l'enveloppe des documents vivent dans
``mountain_perf.codec``, qui n'importe que la bibliothèque standard ; le registre les
applique à ses types et à son format (``backtest/codec.py``), et
``mountain_perf.backtest`` réexporte les mêmes objets. Le comportement du registre est
tenu par ses propres tests, inchangés ; ceux-ci tiennent les imports, l'identité des
objets réexportés, et l'enveloppe sous une configuration qui n'est pas celle du
registre.
"""

import ast
import json
import re
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

import pytest

import mountain_perf
import mountain_perf.backtest as backtest
import mountain_perf.backtest.codec as backtest_codec
import mountain_perf.codec as codec
from mountain_perf.codec import (
    CodecError,
    canonical_bytes,
    decode_envelope,
    encode_envelope,
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
    """Dans ``src/``, seul ``backtest/codec.py`` importe le codec commun ; l'ingestion
    s'y ajoutera (AN1, ``0013``)."""
    importers = []
    for path in sorted(SOURCE.rglob("*.py")):
        if path == COMMON_MODULE:
            continue
        for module, names in _imports(path).items():
            if module == "mountain_perf.codec" or (
                module == "mountain_perf" and "codec" in names
            ):
                importers.append(path.relative_to(SOURCE).as_posix())
    assert importers == ["backtest/codec.py"]


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
        match=re.escape("Stray n'est pas un type de document (Probe, LateProbe)."),
    ):
        _write(Stray(1), 5)


def test_envelope_refuses_to_write_before_the_first_format() -> None:
    with pytest.raises(
        TypeError,
        match=re.escape(
            "LateProbe n'existe qu'à partir du format 5, demandé au format 4."
        ),
    ):
        _write(LateProbe(7), 4)


def test_envelope_refuses_to_read_before_the_first_format() -> None:
    with pytest.raises(
        CodecError,
        match=re.escape(
            "document de type 'LateProbe' au format 4, qui ne le connaît pas"
        ),
    ):
        _read(_raw("LateProbe", 4, {"count": 7}), LateProbe, 4)


def test_envelope_reads_only_the_requested_format() -> None:
    with pytest.raises(CodecError, match=re.escape("document au format 5, 3 attendu")):
        _read(PROBE_DOCUMENT, Probe, 3)


def test_envelope_reads_only_the_expected_type() -> None:
    with pytest.raises(
        CodecError, match=re.escape("document de type 'Probe', 'LateProbe' attendu")
    ):
        _read(PROBE_DOCUMENT, LateProbe, 5)


def test_envelope_refuses_a_non_canonical_document() -> None:
    indented = json.dumps(json.loads(PROBE_DOCUMENT), ensure_ascii=False, indent=1)
    with pytest.raises(
        CodecError, match=re.escape("document d'écriture non canonique")
    ):
        _read(indented.encode(), Probe, 5)


def test_type_absent_from_the_table_counts_from_format_one() -> None:
    """Comportement repris tel quel du registre : un type non admis passe le contrôle
    du format à partir du format 1, puis la réécriture le refuse ; avant le format 1,
    la relecture le refuse."""
    with pytest.raises(
        TypeError,
        match=re.escape("Stray n'est pas un type de document (Probe, LateProbe)."),
    ):
        _read(_raw("Stray", 1, {"count": 2}), Stray, 1)
    with pytest.raises(
        CodecError,
        match=re.escape("document de type 'Stray' au format 0, qui ne le connaît pas"),
    ):
        _read(_raw("Stray", 0, {"count": 2}), Stray, 0)
