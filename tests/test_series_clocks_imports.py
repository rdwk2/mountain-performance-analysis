"""Les horloges communes (brief AN1-2a ; ``0010`` D4.4 et D5).

Les séries dérivées d'une trace (``mountain_perf.series`` : trous, blocs, lissage par
bloc, ``d_r``) et ses horloges (``mountain_perf.clocks`` : fenêtres, qualification,
confirmation, partition M/S/U, horloges cumulées, totaux, épisodes d'arrêt) vivent dans
deux modules communs au moteur et à la piste analyse : une seule définition du
mouvement dans le projet. ``backtest/series.py`` et ``backtest/clocks.py`` réexportent
leurs noms, et ``mountain_perf.backtest`` aussi. Le comportement reste tenu par
``tests/test_backtest_series.py`` et ``tests/test_backtest_clocks.py``, qui passent par
le réexport. Ceux-ci tiennent ce que les modules communs importent, écrit et chargé ;
la liste exacte des noms réexportés ; leur identité avec les objets des modules
communs ; et des modules de réexport qui ne définissent rien.
"""

import ast
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

import mountain_perf
import mountain_perf.backtest as backtest
import mountain_perf.backtest.clocks as backtest_clocks
import mountain_perf.backtest.series as backtest_series
import mountain_perf.clocks as clocks
import mountain_perf.series as series
from test_backtest_metrics_reuse import _imported_modules, _package

SOURCE = Path(mountain_perf.__file__).parent
STDLIB = set(sys.stdlib_module_names)

COMMON: dict[str, ModuleType] = {"series": series, "clocks": clocks}
REEXPORTS: dict[str, ModuleType] = {
    "series": backtest_series,
    "clocks": backtest_clocks,
}

PROJECT_IMPORTS = {
    "series": {"mountain_perf.gpx.geo", "mountain_perf.schemas"},
    "clocks": {
        "mountain_perf.gpx.geo",
        "mountain_perf.schemas",
        "mountain_perf.series",
    },
}
"""Les modules du projet que chaque module commun importe (réponse du moteur au relais
15, point 4) : ni ``mountain_perf.backtest``, ni ``mountain_perf.ingest``."""

REEXPORTED = {
    "series": {"MAX_STEP_S", "SMOOTHING_HALF_WIDTH", "TraceSeries", "build_series"},
    "clocks": {
        "CLOCK_HALF_WINDOW_S",
        "CLOCK_THRESHOLD_RELATIVE_TOLERANCE",
        "Qualification",
        "WindowMeasures",
        "_diameter_m",
        "_smoothed_at",
        "clock_duration_s",
        "clock_partition",
        "confirm",
        "cumulative_s",
        "qualify",
        "stop_episodes",
        "trace_totals",
        "window_measures",
    },
}
"""Les noms que ``backtest/series.py`` et ``backtest/clocks.py`` réexportent : chaque
nom public du module commun, et les deux aides privées que
``tests/test_backtest_clocks.py`` importe (réponse du moteur au relais 15, point 1)."""

PACKAGE_EXPORTED = {
    "series": {"MAX_STEP_S", "SMOOTHING_HALF_WIDTH", "TraceSeries", "build_series"},
    "clocks": {
        "CLOCK_HALF_WINDOW_S",
        "Qualification",
        "WindowMeasures",
        "clock_duration_s",
        "clock_partition",
        "confirm",
        "cumulative_s",
        "qualify",
        "stop_episodes",
        "trace_totals",
        "window_measures",
    },
}
"""Les noms des modules communs que ``mountain_perf.backtest`` exporte, comme avant
AN1-2a."""


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _public_definitions(tree: ast.Module) -> set[str]:
    """Les noms publics que définit le premier niveau d'un module : fonctions, classes,
    affectations (cibles multiples comprises) et alias de type, y compris dans le corps
    d'un ``if``, d'un ``try``, d'un ``with`` ou d'une boucle de premier niveau."""
    names: set[str] = set()

    def bind(target: ast.expr) -> None:
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, ast.Tuple | ast.List):
            for element in target.elts:
                bind(element)
        elif isinstance(target, ast.Starred):
            bind(target.value)

    def visit(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                names.add(node.name)
            elif isinstance(node, ast.TypeAlias):
                bind(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    bind(target)
            elif isinstance(node, ast.AnnAssign | ast.AugAssign):
                bind(node.target)
            elif isinstance(node, ast.If | ast.For | ast.While):
                visit(node.body)
                visit(node.orelse)
            elif isinstance(node, ast.With):
                visit(node.body)
            elif isinstance(node, ast.Try | ast.TryStar):
                visit(node.body)
                for handler in node.handlers:
                    visit(handler.body)
                visit(node.orelse)
                visit(node.finalbody)

    visit(tree.body)
    return {name for name in names if not name.startswith("_")}


@pytest.mark.parametrize("name", ["series", "clocks"])
def test_common_module_imports_geo_schemas_and_the_standard_library(name: str) -> None:
    """Imports écrits : du projet, exactement les modules de ``PROJECT_IMPORTS`` ; hors
    du projet, la bibliothèque standard seule."""
    path = SOURCE / f"{name}.py"
    imported = _imported_modules(_tree(path), _package(path))
    project = {m for m in imported if m.split(".")[0] == "mountain_perf"}
    assert project == PROJECT_IMPORTS[name]
    outside = {m.split(".")[0] for m in imported if m not in project}
    assert outside <= STDLIB


def test_importing_the_common_modules_loads_neither_backtest_nor_ingest() -> None:
    """Modules chargés, dans un processus neuf, pas seulement les imports écrits :
    importer les deux modules communs ne charge ni ``mountain_perf.backtest`` ni
    ``mountain_perf.ingest``."""
    code = (
        "import sys\n"
        "import mountain_perf.series\n"
        "import mountain_perf.clocks\n"
        "print(sorted(name for name in sys.modules "
        "if name.split('.')[0] == 'mountain_perf'))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    loaded = ast.literal_eval(result.stdout.strip())
    assert {"mountain_perf.series", "mountain_perf.clocks"} <= set(loaded)
    assert not [
        name
        for name in loaded
        if name.startswith(("mountain_perf.backtest", "mountain_perf.ingest"))
    ]


@pytest.mark.parametrize("name", ["series", "clocks"])
def test_reexport_lists_every_public_name_and_the_two_private_helpers(
    name: str,
) -> None:
    """``__all__`` du réexport vaut ``REEXPORTED`` ; ses noms publics sont exactement
    ceux que le module commun définit : aucun oublié, aucun en trop."""
    assert set(REEXPORTS[name].__all__) == REEXPORTED[name]
    public = _public_definitions(_tree(SOURCE / f"{name}.py"))
    assert public == {n for n in REEXPORTED[name] if not n.startswith("_")}


@pytest.mark.parametrize("name", ["series", "clocks"])
def test_reexported_names_are_the_objects_of_the_common_module(name: str) -> None:
    """Chaque nom réexporté, par ``backtest/<module>.py`` et par
    ``mountain_perf.backtest``, est l'objet même du module commun : ni copie, ni
    enveloppe."""
    for exported in REEXPORTED[name]:
        common = getattr(COMMON[name], exported)
        assert getattr(REEXPORTS[name], exported) is common, exported
    assert set(backtest.__all__) & REEXPORTED[name] == PACKAGE_EXPORTED[name]
    for exported in PACKAGE_EXPORTED[name]:
        assert getattr(backtest, exported) is getattr(COMMON[name], exported), exported


@pytest.mark.parametrize("name", ["series", "clocks"])
def test_reexport_module_defines_nothing(name: str) -> None:
    """Le réexport ne contient que sa docstring, un seul import, depuis le module
    commun, sans alias, et ``__all__`` : aucune définition, pas même une constante
    recopiée, que l'identité ne verrait pas pour un petit entier."""
    tree = _tree(SOURCE / "backtest" / f"{name}.py")
    docstring, imported, listed = tree.body
    assert isinstance(docstring, ast.Expr)
    assert isinstance(docstring.value, ast.Constant)
    assert isinstance(imported, ast.ImportFrom)
    assert imported.module == f"mountain_perf.{name}"
    assert imported.level == 0
    assert {(a.name, a.asname) for a in imported.names} == {
        (n, None) for n in REEXPORTED[name]
    }
    assert isinstance(listed, ast.Assign)
    assert [ast.unparse(t) for t in listed.targets] == ["__all__"]
