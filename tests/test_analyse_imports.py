"""Clôtures d'import de la piste analyse (``docs/decisions/0011``, ``0014``) :
``analyse/`` lit les horloges communes, jamais ``mountain_perf.backtest`` ; pyarrow
n'entre que par ``analyse/parquet.py`` ; les tables se calculent sans lui ; le moteur
n'importe pas ``analyse/``."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

import mountain_perf
from test_backtest_metrics_reuse import _imported_modules, _package

SOURCE = Path(mountain_perf.__file__).parent
ANALYSE = SOURCE / "analyse"


def _imports(path: Path) -> dict[str, set[str]]:
    return _imported_modules(
        ast.parse(path.read_text(encoding="utf-8")), _package(path)
    )


def test_analyse_never_imports_the_backtest() -> None:
    for path in sorted(ANALYSE.rglob("*.py")):
        assert not any(
            m == "mountain_perf.backtest" or m.startswith("mountain_perf.backtest.")
            for m in _imports(path)
        ), path


def test_analyse_reads_the_common_clocks() -> None:
    imports = _imports(ANALYSE / "climbs.py")
    assert "mountain_perf.clocks" in imports
    assert "mountain_perf.series" in imports


def test_only_the_parquet_module_imports_pyarrow() -> None:
    importers = sorted(
        path.relative_to(SOURCE).as_posix()
        for path in SOURCE.rglob("*.py")
        if any(m == "pyarrow" or m.startswith("pyarrow.") for m in _imports(path))
    )
    assert importers == ["analyse/parquet.py"]


def test_the_engine_does_not_import_analyse() -> None:
    for folder in ("schemas", "gpx", "model", "backtest", "ingest"):
        for path in sorted((SOURCE / folder).rglob("*.py")):
            assert not any(
                m.startswith("mountain_perf.analyse") for m in _imports(path)
            ), path
    for name in ("codec.py", "validation.py", "config.py", "units.py"):
        assert not any(
            m.startswith("mountain_perf.analyse") for m in _imports(SOURCE / name)
        ), name
    for name in ("series.py", "clocks.py"):
        assert not any(
            m.startswith("mountain_perf.analyse") for m in _imports(SOURCE / name)
        ), name


EXTRAS = ("pyarrow", "fitdecode", "mountain_perf.ingest.fit")
"""Les deux extras, et le seul module qui importe le second."""


@pytest.mark.parametrize(
    ("module", "forbidden"),
    [
        ("mountain_perf.analyse.tables", (*EXTRAS, "mountain_perf.backtest")),
        ("mountain_perf.cli", EXTRAS),
    ],
)
def test_tables_compute_without_the_extras(
    module: str, forbidden: tuple[str, ...]
) -> None:
    """Dans un processus neuf, importer le calcul des tables ne charge ni un extra,
    ni le moteur ; importer ``mperf`` ne charge aucun extra (``mperf tables`` importe
    l'écriture Parquet dans la commande)."""
    code = (
        "import sys\n"
        f"import {module}\n"
        f"forbidden = {forbidden!r}\n"
        "loaded = sorted(m for m in sys.modules if any(m == f or"
        " m.startswith(f + '.') for f in forbidden))\n"
        "print(loaded)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"
