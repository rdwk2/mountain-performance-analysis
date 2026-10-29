"""Clôture d'import de l'estimation de la courbe (M6b, ``docs/decisions/0017``) :
``estimation/`` est du Python pur, qui n'importe ni ``analyse/``, ni ``backtest/``, ni
l'interface, ni une bibliothèque d'un extra. Lu sur l'arbre syntaxique de chaque module,
imports dans les fonctions compris."""

from __future__ import annotations

import ast
from pathlib import Path

import mountain_perf
from test_backtest_metrics_reuse import _imported_modules, _package

SOURCE = Path(mountain_perf.__file__).parent
ESTIMATION = SOURCE / "estimation"
FORBIDDEN_PACKAGES = (
    "mountain_perf.analyse",
    "mountain_perf.backtest",
    "mountain_perf.ui",
)
FORBIDDEN_LIBRARIES = {"numpy", "pandas", "fitdecode", "pyarrow", "plotly", "streamlit"}


def _modules(path: Path) -> set[str]:
    """Les modules qu'importe ``path`` : ``from a import b`` compte pour ``a`` et
    ``a.b``."""
    found = _imported_modules(
        ast.parse(path.read_text(encoding="utf-8")), _package(path)
    )
    return set(found) | {
        f"{module}.{name}" for module, names in found.items() for name in names
    }


def test_the_package_has_three_modules() -> None:
    assert sorted(p.name for p in ESTIMATION.glob("*.py")) == [
        "__init__.py",
        "curve.py",
        "intervals.py",
    ]


def test_estimation_imports_neither_analyse_nor_backtest_nor_an_extra() -> None:
    for path in sorted(ESTIMATION.glob("*.py")):
        for module in _modules(path):
            assert not module.startswith(FORBIDDEN_PACKAGES), (path.name, module)
            assert module.split(".")[0] not in FORBIDDEN_LIBRARIES, (path.name, module)
