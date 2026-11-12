"""Clôture d'import de l'estimation de la courbe (M6b, ``docs/decisions/0017``) :
``estimation/`` est du Python pur, qui n'importe ni ``analyse/``, ni ``backtest/``, ni
l'interface, ni une bibliothèque d'un extra. Lu sur l'arbre syntaxique de chaque module,
imports dans les fonctions compris."""

from __future__ import annotations

import ast
import sys
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


def test_the_package_has_five_modules() -> None:
    assert sorted(p.name for p in ESTIMATION.glob("*.py")) == [
        "__init__.py",
        "curve.py",
        "decision.py",
        "intervals.py",
        "origin.py",
    ]


def test_estimation_imports_neither_analyse_nor_backtest_nor_an_extra() -> None:
    for path in sorted(ESTIMATION.glob("*.py")):
        for module in _modules(path):
            assert not module.startswith(FORBIDDEN_PACKAGES), (path.name, module)
            assert module.split(".")[0] not in FORBIDDEN_LIBRARIES, (path.name, module)


def test_the_rule_reads_no_clock_no_file_no_environment() -> None:
    """Le noyau de la règle à l'origine (OG-1) est déterministe : ``origin.py``, et
    ``decision.py`` où vit sa décision sur des instants (OG-2), n'importent ni le
    système, ni la configuration, ni git, ni le lecteur d'``interim/``, et n'appellent
    ni l'horloge, ni l'environnement, ni ``open``."""
    forbidden_modules = {
        "os",
        "pathlib",
        "time",
        "subprocess",
        "mountain_perf.config",
        "mountain_perf.gitstate",
        "mountain_perf.ingest.interim",
    }
    forbidden_names = {"now", "today", "utcnow", "getenv", "environ", "open"}
    for path in (ESTIMATION / "origin.py", ESTIMATION / "decision.py"):
        assert not _modules(path) & forbidden_modules, path.name
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            name = (
                node.attr
                if isinstance(node, ast.Attribute)
                else node.id
                if isinstance(node, ast.Name)
                else None
            )
            assert name not in forbidden_names, (path.name, name)


def test_the_decision_imports_the_standard_library_and_validation_only() -> None:
    """OG-2, § 6.1, choix C1 : ``estimation/decision.py`` « n'importe que la
    bibliothèque standard et ``mountain_perf.validation`` » ; le registre, qui
    l'importe, ne charge donc rien d'autre de l'estimation (constat C-8 de la relecture
    C du bloc 1)."""
    for module in _modules(ESTIMATION / "decision.py"):
        top = module.split(".")[0]
        assert top in sys.stdlib_module_names or (
            module == "mountain_perf.validation"
            or module.startswith("mountain_perf.validation.")
        ), module


def test_the_package_init_imports_nothing() -> None:
    """OG-2, choix C1 : ``estimation/__init__.py`` n'importe rien ; importer
    ``mountain_perf.estimation.decision`` ne charge pas ``origin``, ``curve`` ni
    ``intervals``."""
    assert _modules(ESTIMATION / "__init__.py") == set()
