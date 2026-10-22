"""Clôtures d'import de l'interface (``0011``, ``0016`` ; § 6.1 et § 8.2 du brief M5-1).

Dans ``src/mountain_perf/ui/`` et ``tests/test_ui_*.py``, l'exemption de
``per-file-ignores`` lève toute la règle TID251 : ni pandas, ni numpy, ni altair, ni
pyarrow n'y sont plus bannis par ``ruff``. Leur clôture est donc ici. Ce fichier tourne
sans l'extra ``tableau`` : il n'importe pas Streamlit.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import tomllib
from pathlib import Path

import mountain_perf
from test_backtest_metrics_reuse import _imported_modules, _package

SOURCE = Path(mountain_perf.__file__).parent
UI = SOURCE / "ui"
TESTS = Path(__file__).parent
ROOT = TESTS.parent
STDLIB = set(sys.stdlib_module_names) | {"__future__"}
RUNS_BACKTEST_MODULES = (
    "mountain_perf.backtest.calendar",
    "mountain_perf.backtest.geometry",
    "mountain_perf.backtest.matching",
    "mountain_perf.backtest.passages",
    "mountain_perf.backtest.scoring",
    "mountain_perf.backtest.segments",
)
"""Les modules purs de ``backtest/`` que ``runs.py`` peut importer (M5-2)."""


def _imports(path: Path, package: str) -> set[str]:
    """Les modules importés par le fichier ``path``, imports relatifs résolus depuis
    ``package``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return set(_imported_modules(tree, package))


def _source_imports(path: Path) -> set[str]:
    return _imports(path, _package(path))


def _top(modules: set[str]) -> set[str]:
    return {module.split(".")[0] for module in modules}


def _test_modules() -> set[str]:
    """Les modules de premier niveau de ``tests/`` : un fichier ``tests/<nom>.py`` ou un
    dossier ``tests/<nom>/``, relevés dans le dossier (précision 2 de la relecture du
    plan)."""
    return {
        path.stem if path.is_file() else path.name
        for path in TESTS.iterdir()
        if (path.is_file() and path.suffix == ".py")
        or (path.is_dir() and path.name.isidentifier() and path.name != "__pycache__")
    }


def test_only_the_interface_imports_streamlit() -> None:
    importers = sorted(
        path.relative_to(SOURCE).as_posix()
        for path in SOURCE.rglob("*.py")
        if "streamlit" in _top(_source_imports(path))
    )
    assert importers
    assert all(importer.startswith("ui/") for importer in importers), importers


def test_the_interface_imports_only_stdlib_the_library_and_streamlit() -> None:
    modules = sorted(UI.rglob("*.py"))
    assert modules
    for path in modules:
        outside = _top(_source_imports(path)) - STDLIB
        assert outside <= {"mountain_perf", "streamlit"}, (path.name, outside)


def test_interface_tests_import_only_what_they_are_allowed() -> None:
    allowed = {"pytest", "hypothesis", "mountain_perf", "streamlit"} | _test_modules()
    files = sorted(TESTS.glob("test_ui_*.py"))
    assert Path(__file__) in files
    for path in files:
        outside = _top(_imports(path, "tests")) - STDLIB
        assert outside <= allowed, (path.name, outside - allowed)


def test_the_library_loads_without_streamlit_pandas_or_numpy() -> None:
    """Dans un processus neuf : la bibliothèque, la CLI comprise, ne charge ni
    Streamlit ni ce qu'il installe."""
    modules = [
        "mountain_perf",
        "mountain_perf.schemas",
        "mountain_perf.controls",
        "mountain_perf.data_files",
        "mountain_perf.runs",
        "mountain_perf.reports",
        "mountain_perf.model",
        "mountain_perf.model.export",
        "mountain_perf.model.views",
        "mountain_perf.gpx.profile",
        "mountain_perf.backtest",
        "mountain_perf.cli",
    ]
    code = (
        "import importlib, sys\n"
        f"for name in {modules!r}: importlib.import_module(name)\n"
        "print(sorted({m.split('.')[0] for m in sys.modules} "
        "& {'streamlit', 'pandas', 'numpy'}))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "[]"


def test_the_interface_imports_neither_backtest_nor_analyse() -> None:
    for path in sorted(UI.rglob("*.py")):
        for module in _source_imports(path):
            assert not module.startswith(
                ("mountain_perf.backtest", "mountain_perf.analyse")
            ), (path.name, module)


def test_new_library_modules_import_neither_ui_backtest_nor_analyse() -> None:
    for name in (
        "controls.py",
        "data_files.py",
        "runs.py",
        "reports.py",
        "model/export.py",
        "model/views.py",
        "outing_views.py",
    ):
        for module in _source_imports(SOURCE / name):
            if name == "runs.py" and module in RUNS_BACKTEST_MODULES:
                continue
            assert not module.startswith(
                (
                    "mountain_perf.ui",
                    "mountain_perf.backtest",
                    "mountain_perf.analyse",
                )
            ), (name, module)


def test_streamlit_configuration_is_local_and_without_telemetry() -> None:
    with (ROOT / ".streamlit" / "config.toml").open("rb") as stream:
        configuration = tomllib.load(stream)
    assert configuration == {
        "server": {"address": "localhost", "headless": True},
        "browser": {"gatherUsageStats": False},
    }
