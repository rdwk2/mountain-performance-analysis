"""Clôtures d'import de l'interface sous toutes leurs formes (relecture de la PR #33) :
``from mountain_perf import backtest`` et ``from .. import backtest`` importent le
paquet ``backtest`` par son nom ; ``tests/test_ui_imports.py`` ne regarde que le
module d'un ``from … import …``, ici ``mountain_perf``. On compte donc aussi
``paquet.nom`` pour chaque ``from paquet import nom``.
"""

import ast
from pathlib import Path

import mountain_perf
from test_backtest_metrics_reuse import _imported_modules, _package

SOURCE = Path(mountain_perf.__file__).parent
UI = SOURCE / "ui"
NEW_MODULES = (
    "controls.py",
    "data_files.py",
    "runs.py",
    "reports.py",
    "model/export.py",
    "model/views.py",
)


def _targets(path: Path) -> set[str]:
    """Les modules importés, plus ``paquet.nom`` pour chaque ``from paquet import nom``
    (un sous-module importé par son nom)."""
    found = _imported_modules(
        ast.parse(path.read_text(encoding="utf-8")), _package(path)
    )
    targets = set(found)
    for module, names in found.items():
        targets |= {f"{module}.{name}" for name in names}
    return targets


def test_the_interface_imports_neither_backtest_nor_analyse_in_any_form() -> None:
    modules = sorted(UI.rglob("*.py"))
    assert modules
    for path in modules:
        for target in _targets(path):
            assert not target.startswith(
                ("mountain_perf.backtest", "mountain_perf.analyse")
            ), (path.name, target)


def test_new_modules_import_neither_ui_backtest_nor_analyse_in_any_form() -> None:
    for name in NEW_MODULES:
        for target in _targets(SOURCE / name):
            assert not target.startswith(
                ("mountain_perf.ui", "mountain_perf.backtest", "mountain_perf.analyse")
            ), (name, target)
