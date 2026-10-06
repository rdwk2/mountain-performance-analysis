"""Imports de la référence de répétabilité (§ 6 et § 8.1, test 8, du brief M4b-3).

``schemas/repeatability.py`` n'importe ni ``backtest`` ni ``model`` ; du projet,
seulement les contrats que le § 6 nomme et ``mountain_perf.validation``.
``backtest/repeatability.py`` n'importe, du projet, que ``mountain_perf.schemas`` et
``support_metrics`` de ``mountain_perf.backtest.metrics`` ; de la bibliothèque
standard, ``math``, ``collections.abc`` et ``datetime`` (aucune dépendance nouvelle :
pas de numpy). Aucun module de ``src/`` n'importe ``backtest/repeatability.py``, hors
l'export de ``backtest/__init__.py``. Même lecture de l'arbre syntaxique que
``test_backtest_metrics_reuse.py``, dont les aides sont réemployées.
"""

import ast
from pathlib import Path

import mountain_perf
import mountain_perf.backtest as backtest
import mountain_perf.schemas as schemas
from test_backtest_metrics_reuse import _defined_names, _imported_modules, _package

SOURCE = Path(mountain_perf.__file__).parent
BACKTEST_MODULE = Path(backtest.__file__).parent / "repeatability.py"
SCHEMAS_MODULE = Path(schemas.__file__).parent / "repeatability.py"


def _imports(path: Path) -> dict[str, set[str]]:
    return _imported_modules(
        ast.parse(path.read_text(encoding="utf-8")), _package(path)
    )


def test_schemas_module_imports_neither_backtest_nor_model() -> None:
    imported = _imports(SCHEMAS_MODULE)
    assert not [
        name
        for name in imported
        if name.startswith(("mountain_perf.backtest", "mountain_perf.model"))
    ]


def test_schemas_module_imports_only_the_named_contracts() -> None:
    """§ 6 : ``schemas/clock.py``, ``matching.py``, ``metrics.py``, ``outing.py``,
    ``common.py``, ``scoring.py`` et ``mountain_perf.validation``."""
    project = {name for name in _imports(SCHEMAS_MODULE) if name.startswith("mountain")}
    assert project <= {
        "mountain_perf.schemas.clock",
        "mountain_perf.schemas.matching",
        "mountain_perf.schemas.metrics",
        "mountain_perf.schemas.outing",
        "mountain_perf.schemas.common",
        "mountain_perf.schemas.scoring",
        "mountain_perf.validation",
    }


def test_backtest_module_imports_schemas_and_support_metrics_only() -> None:
    imported = _imports(BACKTEST_MODULE)
    project = {name for name in imported if name.startswith("mountain")}
    assert project == {"mountain_perf.schemas", "mountain_perf.backtest.metrics"}
    assert imported["mountain_perf.backtest.metrics"] == {"support_metrics"}


def test_backtest_module_adds_no_dependency() -> None:
    """Décision 1 de rdw : Python pur, aucune dépendance nouvelle (pas de numpy)."""
    imported = _imports(BACKTEST_MODULE)
    outside = {name for name in imported if not name.startswith("mountain")}
    assert outside <= {"math", "collections.abc", "datetime"}


def test_no_module_imports_repeatability_but_the_backtest_package() -> None:
    """Depuis M4b-5, ``backtest/execution.py`` l'importe : il calcule la référence D8
    de chaque parcours d'une exécution (§ 6.0 du brief M4b-5)."""
    defined = _defined_names(ast.parse(BACKTEST_MODULE.read_text(encoding="utf-8")))
    allowed = (SOURCE / "backtest" / "__init__.py", BACKTEST_MODULE)
    importers = []
    for path in sorted(SOURCE.rglob("*.py")):
        if path in allowed:
            continue
        for module, names in _imports(path).items():
            by_module = module == "mountain_perf.backtest.repeatability"
            by_package = module == "mountain_perf.backtest" and names & (
                defined | {"repeatability"}
            )
            if by_module or by_package:
                importers.append(path.relative_to(SOURCE).as_posix())
    assert importers == ["backtest/execution.py"]


def test_the_backtest_package_exports_repeatability() -> None:
    init = SOURCE / "backtest" / "__init__.py"
    assert "mountain_perf.backtest.repeatability" in _imports(init)
