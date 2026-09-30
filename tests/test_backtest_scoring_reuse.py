"""Imports des modules de M4b-2 (§ 6 et § 8.1, test 13, du brief M4b-2 ; précision 1
de la relecture du plan).

Lecture de l'arbre syntaxique, comme ``test_backtest_metrics_reuse.py`` :

- ``schemas/scoring.py`` n'importe ni ``mountain_perf.backtest`` ni
  ``mountain_perf.model`` ;
- ``backtest/scoring.py`` n'importe, parmi les modules du projet, que ceux que le § 6
  liste ;
- aucun module de ``src/`` n'importe ``backtest/scoring.py``, hors l'export de
  ``backtest/__init__.py`` et ``cli.py`` ;
- ``model/engine.py`` n'importe ni ``mountain_perf.backtest`` ni
  ``mountain_perf.schemas.scoring`` (précision 1 : ``mountain_perf.validation`` et
  ``dataclasses.field`` sont ses seuls imports nouveaux, permis).
"""

import ast
from pathlib import Path

import mountain_perf

SOURCE = Path(mountain_perf.__file__).parent


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


def _imports(relative: str) -> dict[str, set[str]]:
    path = SOURCE / relative
    return _imported_modules(
        ast.parse(path.read_text(encoding="utf-8")), _package(path)
    )


def _defined_names(tree: ast.Module) -> set[str]:
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.ClassDef)
    }


def test_relative_imports_are_resolved() -> None:
    tree = ast.parse("from .scoring import v0_scores\nfrom ..schemas import Clock\n")
    assert _imported_modules(tree, "mountain_perf.backtest") == {
        "mountain_perf.backtest.scoring": {"v0_scores"},
        "mountain_perf.schemas": {"Clock"},
    }


def test_scoring_contracts_import_neither_backtest_nor_model() -> None:
    """§ 6 : ``schemas/scoring.py`` n'importe que des contrats et
    ``mountain_perf.validation``."""
    imported = _imports("schemas/scoring.py")
    project = {name for name in imported if name.startswith("mountain_perf")}
    assert project == {
        "mountain_perf.schemas.clock",
        "mountain_perf.schemas.common",
        "mountain_perf.schemas.matching",
        "mountain_perf.schemas.metrics",
        "mountain_perf.schemas.outing",
        "mountain_perf.schemas.parameters",
        "mountain_perf.validation",
    }


def test_backtest_scoring_imports_only_what_section_6_lists() -> None:
    """§ 6 : ``backtest/scoring.py`` importe ``mountain_perf.schemas``,
    ``backtest/clocks.py``, ``backtest/geometry.py``, ``backtest/metrics.py``,
    ``mountain_perf.gpx`` et ``mountain_perf.model`` (``mountain_perf.validation``
    permis)."""
    imported = _imports("backtest/scoring.py")
    project = {name for name in imported if name.startswith("mountain_perf")}
    assert project <= {
        "mountain_perf.schemas",
        "mountain_perf.validation",
        "mountain_perf.backtest.clocks",
        "mountain_perf.backtest.geometry",
        "mountain_perf.backtest.metrics",
        "mountain_perf.gpx",
        "mountain_perf.model",
    }
    assert imported["mountain_perf.model"] <= {
        "ProjectedTimeline",
        "projected_timeline",
        "PROJECTION_PARAMETER_SPECS",
        "ENGINE_VERSION",
    }
    assert imported["mountain_perf.gpx"] == {"build_profile", "PROFILE_PARAMETER_SPECS"}


def test_no_module_imports_backtest_scoring_but_the_package_and_the_command() -> None:
    """§ 8.1, test 13 : ``backtest/scoring.py`` n'est importé, par son nom de module
    ou par ses noms depuis le paquet ``backtest``, que par ``backtest/__init__.py``
    et ``cli.py``."""
    scoring = SOURCE / "backtest" / "scoring.py"
    defined = _defined_names(ast.parse(scoring.read_text(encoding="utf-8")))
    importers = []
    for path in sorted(SOURCE.rglob("*.py")):
        if path == scoring:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for module, names in _imported_modules(tree, _package(path)).items():
            by_module = module == "mountain_perf.backtest.scoring"
            by_package = module == "mountain_perf.backtest" and names & (
                defined | {"scoring"}
            )
            if by_module or by_package:
                importers.append(path.relative_to(SOURCE).as_posix())
    assert set(importers) <= {"backtest/__init__.py", "cli.py"}
    assert "backtest/__init__.py" in importers


def test_engine_imports_neither_backtest_nor_the_scoring_contracts() -> None:
    """Précision 1 (§ 6 et § 6.1) : ``model/engine.py`` n'importe ni
    ``mountain_perf.backtest`` ni ``mountain_perf.schemas.scoring``, ni les noms des
    contrats de scores depuis ``mountain_perf.schemas``."""
    imported = _imports("model/engine.py")
    assert not [name for name in imported if name.startswith("mountain_perf.backtest")]
    assert "mountain_perf.schemas.scoring" not in imported
    scoring = ast.parse((SOURCE / "schemas" / "scoring.py").read_text(encoding="utf-8"))
    assert not imported.get("mountain_perf.schemas", set()) & _defined_names(scoring)
