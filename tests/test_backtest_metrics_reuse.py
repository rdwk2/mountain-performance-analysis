"""Réemploi (§ 6 et § 8.1, test 7, du brief M4b-1 ; précision 2 de la relecture du
plan).

``backtest/metrics.py`` n'importe aucun module de ``mountain_perf.backtest`` ; parmi
les modules du projet, seulement ``mountain_perf.schemas`` et
``mountain_perf.validation``, que le § 6 permet. Aucun module de ``src/`` ne l'importe,
hors l'export de ``backtest/__init__.py``. Lecture de son arbre syntaxique, comme
``test_backtest_passages_reuse.py``.
"""

import ast
from pathlib import Path

import mountain_perf
import mountain_perf.backtest as backtest

PACKAGE = Path(backtest.__file__).parent
SOURCE = Path(mountain_perf.__file__).parent
METRICS = ast.parse((PACKAGE / "metrics.py").read_text(encoding="utf-8"))

PROJECT_MODULES_ALLOWED = {"mountain_perf.schemas", "mountain_perf.validation"}
"""§ 6 : ``backtest/metrics.py`` importe ``math``, ``mountain_perf.schemas`` et
``mountain_perf.validation``."""


def _imported_modules(tree: ast.Module) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            found.setdefault(node.module, set()).update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                found.setdefault(alias.name, set())
    return found


def _defined_names(tree: ast.Module) -> set[str]:
    names = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    }
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def test_metrics_imports_no_backtest_module() -> None:
    """Précision 2 : aucun module ``mountain_perf.backtest*``."""
    imported = _imported_modules(METRICS)
    assert not [name for name in imported if name.startswith("mountain_perf.backtest")]


def test_metrics_imports_only_schemas_and_validation_from_the_project() -> None:
    imported = _imported_modules(METRICS)
    project = {name for name in imported if name.startswith("mountain_perf")}
    assert project <= PROJECT_MODULES_ALLOWED


def test_no_module_imports_metrics_but_the_backtest_package() -> None:
    """§ 6 : l'export de ``backtest/__init__.py`` est la seule importation permise de
    ``backtest/metrics.py``, ni par son nom de module, ni par ses noms depuis le
    paquet ``backtest``."""
    defined = _defined_names(METRICS)
    importers = []
    for path in sorted(SOURCE.rglob("*.py")):
        if path in (PACKAGE / "__init__.py", PACKAGE / "metrics.py"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for module, names in _imported_modules(tree).items():
            by_module = module == "mountain_perf.backtest.metrics"
            by_package = module == "mountain_perf.backtest" and names & defined
            if by_module or by_package:
                importers.append(path.relative_to(SOURCE).as_posix())
    assert importers == []


def test_the_backtest_package_exports_metrics() -> None:
    init = ast.parse((PACKAGE / "__init__.py").read_text(encoding="utf-8"))
    assert "mountain_perf.backtest.metrics" in _imported_modules(init)
