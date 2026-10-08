"""Imports des trois modules neufs de M4c-1 (§ 6.0 et § 8.1, test 10, du brief M4c-1).

Lecture de l'arbre syntaxique, comme ``test_backtest_scoring_reuse.py`` :

- ``schemas/calibration.py`` n'importe, du projet, que ``schemas.clock``,
  ``schemas.metrics``, ``schemas.outing``, ``schemas.scoring`` et
  ``mountain_perf.validation`` — jamais ``schemas/registry.py``, qui l'importe pour
  ``ModelKind`` (décision 5) ;
- ``model/baselines.py`` n'importe que ``model.engine`` (``ProjectedTimeline``) et
  ``mountain_perf.schemas`` (``ModelKind``, ``RouteProfile``) ;
- ``backtest/calibration.py`` n'importe que ``backtest.calendar``, ``backtest.metrics``,
  ``backtest.scoring``, ``model.baselines`` et ``mountain_perf.schemas`` ;
- hors du projet, la bibliothèque standard seule (aucune dépendance nouvelle) ;
- aucun module de ``src/`` n'importe ``backtest/calibration.py``, hors l'export de
  ``backtest/__init__.py`` (M4c-2 l'importera depuis l'exécution).
"""

import ast
import sys
from pathlib import Path

import mountain_perf

SOURCE = Path(mountain_perf.__file__).parent
CONTRACTS = SOURCE / "schemas" / "calibration.py"
BASELINES = SOURCE / "model" / "baselines.py"
CALIBRATION = SOURCE / "backtest" / "calibration.py"


def _imported_modules(tree: ast.Module, package: str) -> dict[str, set[str]]:
    """Les modules importés par ``tree``, avec les noms pris à chacun ; un import
    relatif est résolu depuis ``package``, le paquet du fichier lu."""
    found: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            parts = package.split(".")
            base = parts[: len(parts) - node.level + 1] if node.level else []
            module = ".".join([*base, *([node.module] if node.module else [])])
            found.setdefault(module, set()).update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                found.setdefault(alias.name, set())
    return found


def _package(path: Path) -> str:
    return ".".join(("mountain_perf", *path.relative_to(SOURCE).parent.parts))


def _imports(path: Path) -> dict[str, set[str]]:
    return _imported_modules(
        ast.parse(path.read_text(encoding="utf-8")), _package(path)
    )


def _project(path: Path) -> dict[str, set[str]]:
    return {
        module: names
        for module, names in _imports(path).items()
        if module.startswith("mountain_perf")
    }


def _defined_names(tree: ast.Module) -> set[str]:
    names = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.ClassDef)
    }
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def test_calibration_contracts_import_only_section_6_0() -> None:
    """§ 6.0, décisions 5 et 15 : des contrats et ``mountain_perf.validation``, jamais
    le registre."""
    assert _project(CONTRACTS) == {
        "mountain_perf.schemas.clock": {"CLOCKS", "Clock"},
        "mountain_perf.schemas.metrics": {"METRIC_RELATIVE_TOLERANCE"},
        "mountain_perf.schemas.outing": {"Unavailability"},
        "mountain_perf.schemas.scoring": {
            "ClockScores",
            "ModelForecast",
            "OutingObservation",
            "Scenario",
        },
        "mountain_perf.validation": {
            "ContractError",
            "require_aware",
            "require_finite",
            "require_immutable_sequence",
        },
    }


def test_baselines_import_only_section_6_0() -> None:
    """§ 6.0 : la chronologie générique du moteur et deux contrats."""
    assert _project(BASELINES) == {
        "mountain_perf.model.engine": {"ProjectedTimeline"},
        "mountain_perf.schemas": {"ModelKind", "RouteProfile"},
    }


def test_backtest_calibration_imports_only_section_6_0() -> None:
    """§ 6.0 : le calendrier, le jugement des sorties de modèle, les scores de M4b-2,
    les baselines et les contrats."""
    imported = _project(CALIBRATION)
    assert set(imported) == {
        "mountain_perf.backtest.calendar",
        "mountain_perf.backtest.metrics",
        "mountain_perf.backtest.scoring",
        "mountain_perf.model.baselines",
        "mountain_perf.schemas",
    }
    assert imported["mountain_perf.backtest.calendar"] == {
        "available_at_origin",
        "origin",
    }
    assert imported["mountain_perf.backtest.metrics"] == {"is_invalid_model_output"}
    assert imported["mountain_perf.backtest.scoring"] == {
        "clock_scores",
        "control_forecast",
        "score_outing",
        "score_scenario",
        "usage_forecast",
    }
    assert imported["mountain_perf.model.baselines"] == {
        "BASELINE_VERSION",
        "BASELINES",
        "baseline_timeline",
    }


def test_no_new_dependency() -> None:
    """§ 6.0 : hors du projet, la bibliothèque standard seule (règle 5)."""
    for path in (CONTRACTS, BASELINES, CALIBRATION):
        outside = {m for m in _imports(path) if not m.startswith("mountain_perf")}
        tops = {name.split(".")[0] for name in outside}
        assert tops <= set(sys.stdlib_module_names), path.name


def test_only_the_backtest_package_imports_the_calibration() -> None:
    """§ 6.0 : aucun module de ``src/`` n'importe ``backtest/calibration.py``, ni par
    son nom de module, ni par ses noms depuis le paquet ``backtest``, hors l'export de
    ``backtest/__init__.py``."""
    defined = _defined_names(ast.parse(CALIBRATION.read_text(encoding="utf-8")))
    importers = []
    for path in sorted(SOURCE.rglob("*.py")):
        if path == CALIBRATION:
            continue
        for module, names in _imports(path).items():
            by_module = module == "mountain_perf.backtest.calibration"
            by_package = module == "mountain_perf.backtest" and names & (
                defined | {"calibration"}
            )
            if by_module or by_package:
                importers.append(path.relative_to(SOURCE).as_posix())
    assert importers == ["backtest/__init__.py"]
