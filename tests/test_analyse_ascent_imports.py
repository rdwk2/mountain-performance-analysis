"""La clôture d'import d'``analyse/ascent/`` (AN4-2a, ``docs/decisions/0024``) : I1 du
brief. Aucun module du paquet n'importe numpy, scipy, pyarrow, plotly, streamlit,
l'interface ni le backtest, même sous ``TYPE_CHECKING`` (l'AST entier est lu) ; les
calculs matriciels passent par ``analyse/inference/``."""

from __future__ import annotations

import ast
from pathlib import Path

import mountain_perf
from test_backtest_metrics_reuse import _imported_modules, _package

ASCENT = Path(mountain_perf.__file__).parent / "analyse" / "ascent"
FORBIDDEN = (
    "numpy",
    "scipy",
    "pyarrow",
    "plotly",
    "streamlit",
    "mountain_perf.ui",
    "mountain_perf.backtest",
)


def _imports(path: Path) -> set[str]:
    imports = _imported_modules(
        ast.parse(path.read_text(encoding="utf-8")), _package(path)
    )
    return {*imports, *(f"{m}.{n}" for m, names in imports.items() for n in names)}


def test_i1_ascent_imports_none_of_the_closed_packages() -> None:
    """I1 : aucun module d'``analyse/ascent/`` n'importe un paquet fermé."""
    modules = sorted(ASCENT.glob("*.py"))
    assert len(modules) >= 5
    for path in modules:
        found = _imports(path)
        assert not any(
            m == f or m.startswith(f"{f}.") for m in found for f in FORBIDDEN
        ), path.name
