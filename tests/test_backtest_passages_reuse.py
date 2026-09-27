"""Réemploi (§ 8.3, test 8, du brief M4a-3, et précision P4 de la relecture du plan).

``backtest/passages.py`` n'importe de ``mountain_perf.backtest`` que ce que le § 0
réemploie, et ne réécrit ni franchissement, ni regroupement, ni position
fractionnaire, ni médiane de lissage. Lecture de son arbre syntaxique : ses seules
sources de position sont ``crossing_candidates``, ``group_events``, ``time_at``,
``position_at`` et les séries lissées — ni positions brutes de la trace, ni
coordonnées GPX du lieu. Et aucun des modules qu'il importe ne l'importe.
"""

import ast
from pathlib import Path

import pytest

import mountain_perf.backtest as backtest

PACKAGE = Path(backtest.__file__).parent
PASSAGES = ast.parse((PACKAGE / "passages.py").read_text(encoding="utf-8"))

ALLOWED_IMPORTS = {
    "mountain_perf.backtest.clocks": {"stop_episodes"},
    "mountain_perf.backtest.geometry": {
        "LocalFrame",
        "ReferenceGeometry",
        "frame_at",
        "position_at",
        "to_local",
    },
    "mountain_perf.backtest.matching": {
        "MATCHING_PARAMETER_SPECS",
        "crossing_candidates",
        "group_events",
        "score_grid",
        "time_at",
    },
    "mountain_perf.backtest.series": {"TraceSeries"},
}
"""Ce que le § 0 réemploie : géométrie de référence, franchissements et regroupement,
séries lissées et épisodes d'arrêt ; leurs types, et la déclaration des paramètres
qu'exige une précondition du § 6.9."""

FORBIDDEN_CALLS = {"coordinates", "crosses", "crossing_fraction", "raw_position_at"}
"""Précision P4 : ni ``h`` ni écart latéral recalculés, ni franchissement, ni
position brute interpolée."""

FORBIDDEN_ATTRIBUTES = {"latitude_deg", "longitude_deg"}
"""Précision P4 : ni positions brutes de la trace, ni coordonnées GPX du lieu."""


def _imports(tree: ast.Module) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            found.setdefault(node.module, set()).update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                found.setdefault(alias.name, set())
    return found


def _functions(tree: ast.Module) -> set[str]:
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def test_imports_from_backtest_are_exactly_the_reused_ones() -> None:
    imported = {
        module: names
        for module, names in _imports(PASSAGES).items()
        if module.startswith("mountain_perf.backtest")
    }
    assert imported == ALLOWED_IMPORTS


@pytest.mark.parametrize("module", ["matching", "geometry", "series", "clocks"])
def test_no_function_is_rewritten(module: str) -> None:
    """Aucune fonction de ``passages.py`` n'est homonyme d'une fonction des modules
    réemployés."""
    tree = ast.parse((PACKAGE / f"{module}.py").read_text(encoding="utf-8"))
    assert not _functions(PASSAGES) & _functions(tree)


def test_no_raw_crossing_or_position_is_computed() -> None:
    """Précision P4 : aucun appel à ``.coordinates``, ``crosses``,
    ``crossing_fraction``, ``raw_position_at``."""
    called = set()
    for node in ast.walk(PASSAGES):
        if isinstance(node, ast.Call):
            function = node.func
            if isinstance(function, ast.Name):
                called.add(function.id)
            elif isinstance(function, ast.Attribute):
                called.add(function.attr)
    assert not called & FORBIDDEN_CALLS


def test_no_raw_or_gpx_coordinate_is_read() -> None:
    """Précision P4 : aucun attribut lu nommé exactement ``latitude_deg`` ou
    ``longitude_deg`` ; les séries lissées (``smoothed_*``) sont permises."""
    read = {node.attr for node in ast.walk(PASSAGES) if isinstance(node, ast.Attribute)}
    assert not read & FORBIDDEN_ATTRIBUTES
    assert {"smoothed_latitude_deg", "smoothed_longitude_deg"} <= read


@pytest.mark.parametrize(
    "module", ["matching", "geometry", "series", "clocks", "segments"]
)
def test_reused_modules_do_not_import_passages(module: str) -> None:
    """Ni le module ``passages``, ni l'un de ses noms par le paquet ``backtest``."""
    tree = ast.parse((PACKAGE / f"{module}.py").read_text(encoding="utf-8"))
    defined = _functions(PASSAGES) | {
        target.id
        for node in PASSAGES.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    for name, names in _imports(tree).items():
        assert name != "mountain_perf.backtest.passages"
        if name == "mountain_perf.backtest":
            assert not names & defined
