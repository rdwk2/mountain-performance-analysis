"""La clôture d'import des profils de démo (M5-3, § 6.0 du brief) : les modules de
``mountain_perf/demo/`` n'importent, au premier niveau comme dans leurs fonctions, que
la bibliothèque standard, ``mountain_perf.demo``, ``mountain_perf.validation`` et
``mountain_perf.gitstate`` — plus, par égalité, le paquet ``mountain_perf`` seul (sa
racine, ``construction.py``) et ``mountain_perf.schemas.days`` (``WAKING_CONTEXT``,
``jours.py``) ; ni ``ui``, ni ``backtest``, ni ``analyse``, ni ``runs``, ni un extra."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import mountain_perf
from test_backtest_metrics_reuse import _imported_modules, _package

SOURCE = Path(mountain_perf.__file__).parent
DEMO = SOURCE / "demo"
STDLIB = set(sys.stdlib_module_names) | {"__future__"}
ALLOWED_PACKAGES = (
    "mountain_perf.demo",
    "mountain_perf.validation",
    "mountain_perf.gitstate",
)
ALLOWED_EXACT = ("mountain_perf", "mountain_perf.schemas.days")
MODULES = (
    "__init__.py",
    "constantes.py",
    "construction.py",
    "fit.py",
    "gpx.py",
    "jours.py",
    "parcours.py",
    "personnages.py",
    "sorties.py",
)
"""Les modules du paquet."""


def _imports(tree: ast.Module, path: Path) -> set[str]:
    """Les modules importés, plus ``paquet.nom`` pour chaque ``from paquet import
    nom`` : ``from mountain_perf import runs`` compte comme ``mountain_perf.runs``."""
    found = _imported_modules(tree, _package(path))
    return set(found) | {f"{m}.{name}" for m, names in found.items() for name in names}


def _allowed(module: str) -> bool:
    if module.split(".")[0] in STDLIB:
        return True
    if module in ALLOWED_EXACT:
        return True
    return any(module == p or module.startswith(f"{p}.") for p in ALLOWED_PACKAGES)


def _is_name_of(module: str) -> bool:
    """Un nom pris à un module autorisé par égalité (``from mountain_perf.schemas.days
    import WAKING_CONTEXT``) : ``mountain_perf.schemas.days.WAKING_CONTEXT``."""
    return any(
        module.startswith(f"{exact}.") and exact != "mountain_perf"
        for exact in ALLOWED_EXACT
    )


def test_the_package_has_its_modules() -> None:
    assert sorted(p.name for p in DEMO.glob("*.py")) == sorted(MODULES)


def test_demo_imports_only_stdlib_validation_and_gitstate() -> None:
    for name in MODULES:
        path = DEMO / name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for module in _imports(tree, path):
            assert _allowed(module) or _is_name_of(module), (name, module)


def test_the_closure_sees_every_form() -> None:
    """``import a.b``, ``from a import b``, ``from mountain_perf import b``, dans une
    fonction comme au premier niveau."""
    path = DEMO / "construction.py"
    for code in (
        "import mountain_perf.runs\n",
        "from mountain_perf.runs import now\n",
        "from mountain_perf import runs\n",
        "def f():\n    from mountain_perf import analyse\n",
        "import mountain_perf.backtest.calendar\n",
        "import fitdecode\n",
        "from mountain_perf.schemas import Sport\n",
    ):
        imports = _imports(ast.parse(code), path)
        assert not all(_allowed(m) or _is_name_of(m) for m in imports), code
    for code in (
        "import mountain_perf\n",
        "from mountain_perf import gitstate\n",
        "from mountain_perf.validation import ContractError\n",
        "from mountain_perf.demo.parcours import route\n",
        "from mountain_perf.schemas.days import WAKING_CONTEXT\n",
        "import json\n",
    ):
        imports = _imports(ast.parse(code), path)
        assert all(_allowed(m) or _is_name_of(m) for m in imports), code


def test_cli_imports_only_the_names_at_the_top_level() -> None:
    """``cli.py`` n'importe de la démo, au premier niveau, que ``CHARACTER_NAMES`` de
    ``mountain_perf.demo.constantes``."""
    tree = ast.parse((SOURCE / "cli.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("mountain_perf.demo"), alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = [alias.name for alias in node.names]
            if module == "mountain_perf":
                assert "demo" not in names
            if module.startswith("mountain_perf.demo"):
                assert (module, names) == (
                    "mountain_perf.demo.constantes",
                    ["CHARACTER_NAMES"],
                )


def test_loading_cli_loads_only_the_demo_constants() -> None:
    code = (
        "import sys, mountain_perf.cli\n"
        "print(sorted(m for m in sys.modules if m.startswith('mountain_perf.demo')))\n"
    )
    found = subprocess.run(
        [sys.executable, "-c", code], check=True, capture_output=True, text=True
    )
    assert found.stdout.strip() == (
        "['mountain_perf.demo', 'mountain_perf.demo.constantes']"
    )
