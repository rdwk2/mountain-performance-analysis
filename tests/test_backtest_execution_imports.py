"""Imports de l'exécution et du rapport (§ 6.0 et § 8.1, test 11, du brief M4b-5).

``backtest/execution.py`` et ``backtest/report.py`` n'importent, du projet et de la
bibliothèque standard, que les modules que le § 6.0 nomme ; le rapport ne prend de
l'exécution que ``BacktestRun``, et ne lit ni n'écrit rien (pas de ``pathlib``) ;
seuls ``backtest/__init__.py``, ``backtest/report.py`` et ``cli.py`` importent
l'exécution, seuls ``backtest/__init__.py`` et ``cli.py`` le rapport ; aucune
dépendance nouvelle. Même lecture de l'arbre syntaxique que
``test_backtest_metrics_reuse.py``, dont les aides sont réemployées.
"""

import ast
import sys
from pathlib import Path

import mountain_perf
import mountain_perf.backtest as backtest
from test_backtest_metrics_reuse import _defined_names, _imported_modules, _package

SOURCE = Path(mountain_perf.__file__).parent
EXECUTION = Path(backtest.__file__).parent / "execution.py"
REPORT = Path(backtest.__file__).parent / "report.py"


def _imports(path: Path) -> dict[str, set[str]]:
    return _imported_modules(
        ast.parse(path.read_text(encoding="utf-8")), _package(path)
    )


def _project(path: Path) -> set[str]:
    return {name for name in _imports(path) if name.startswith("mountain")}


def _outside(path: Path) -> set[str]:
    return {
        name
        for name in _imports(path)
        if not name.startswith("mountain") and name != "__future__"
    }


def test_execution_imports_the_named_modules_only() -> None:
    """§ 6.0 : l'exécution enchaîne les modules fusionnés, sans calcul neuf."""
    assert _project(EXECUTION) <= {
        "mountain_perf.backtest.calendar",
        "mountain_perf.backtest.calibration",
        "mountain_perf.backtest.clocks",
        "mountain_perf.backtest.geometry",
        "mountain_perf.backtest.manifest",
        "mountain_perf.backtest.matching",
        "mountain_perf.backtest.outings",
        "mountain_perf.backtest.passages",
        "mountain_perf.backtest.registry",
        "mountain_perf.backtest.repeatability",
        "mountain_perf.backtest.scoring",
        "mountain_perf.backtest.segments",
        "mountain_perf.backtest.series",
        "mountain_perf.gpx",
        "mountain_perf.model",
        "mountain_perf.schemas",
        "mountain_perf.validation",
    }
    assert _outside(EXECUTION) <= {
        "collections",
        "collections.abc",
        "dataclasses",
        "datetime",
        "math",
        "pathlib",
        "subprocess",
    }


def test_report_imports_the_named_modules_only() -> None:
    """§ 6.0 : le rapport, des fonctions pures — de l'exécution, ``BacktestRun``
    seul ; ni ``pathlib`` ni registre."""
    imported = _imports(REPORT)
    assert _project(REPORT) <= {
        "mountain_perf.backtest.calendar",
        "mountain_perf.backtest.execution",
        "mountain_perf.backtest.metrics",
        "mountain_perf.backtest.scoring",
        "mountain_perf.backtest.segments",
        "mountain_perf.schemas",
    }
    assert imported["mountain_perf.backtest.execution"] == {"BacktestRun"}
    assert _outside(REPORT) <= {
        "collections",
        "collections.abc",
        "dataclasses",
        "datetime",
        "enum",
        "math",
    }


def test_no_new_dependency() -> None:
    """§ 6.0 : hors du projet, la bibliothèque standard seule."""
    for path in (EXECUTION, REPORT):
        tops = {name.split(".")[0] for name in _outside(path)}
        assert tops <= set(sys.stdlib_module_names), path.name


def _importers(module: Path, name: str) -> list[str]:
    """Les fichiers de ``src/`` qui importent ``module``, par son nom de module ou
    par ses noms depuis le paquet ``backtest``."""
    defined = _defined_names(ast.parse(module.read_text(encoding="utf-8")))
    importers = []
    for path in sorted(SOURCE.rglob("*.py")):
        if path == module:
            continue
        for imported, names in _imports(path).items():
            by_module = imported == f"mountain_perf.backtest.{name}"
            by_package = imported == "mountain_perf.backtest" and names & (
                defined | {name}
            )
            if by_module or by_package:
                importers.append(path.relative_to(SOURCE).as_posix())
    return sorted(set(importers))


def test_only_the_package_the_report_and_the_command_import_the_execution() -> None:
    """§ 6.0 : ``backtest/__init__.py`` (export), le rapport et ``cli.py``."""
    assert _importers(EXECUTION, "execution") == [
        "backtest/__init__.py",
        "backtest/report.py",
        "cli.py",
    ]


def test_only_the_package_and_the_command_import_the_report() -> None:
    """§ 6.0 : ``backtest/__init__.py`` (export) et ``cli.py``."""
    assert _importers(REPORT, "report") == ["backtest/__init__.py", "cli.py"]
