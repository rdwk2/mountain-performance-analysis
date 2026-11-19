"""Clôtures d'import de la piste analyse (``docs/decisions/0011``, ``0014``,
``0015``) : ``analyse/`` lit les horloges communes, jamais ``mountain_perf.backtest`` ;
l'état git commun, que ``cli.py`` lit pour elle, n'importe que la bibliothèque
standard ; pyarrow n'entre que par ``analyse/parquet.py``, plotly que par
``analyse/plot.py``, numpy et scipy que par ``analyse/inference/`` (``0021``) ; les
tables, la figure et les résultats se calculent sans eux ; le moteur n'importe pas
``analyse/``."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

import mountain_perf
from test_backtest_metrics_reuse import _imported_modules, _package

SOURCE = Path(mountain_perf.__file__).parent
ANALYSE = SOURCE / "analyse"


def _modules(imports: dict[str, set[str]]) -> set[str]:
    """Les modules d'``imports``, et chaque nom pris à un module comme sous-module
    possible : ``from mountain_perf import backtest`` compte comme
    ``import mountain_perf.backtest``."""
    return {*imports, *(f"{m}.{n}" for m, names in imports.items() for n in names)}


def _imports(path: Path) -> set[str]:
    return _modules(
        _imported_modules(ast.parse(path.read_text(encoding="utf-8")), _package(path))
    )


def test_a_name_taken_from_a_package_counts_as_its_module() -> None:
    """Constat 5 de la relecture de la PR #31 : ``from mountain_perf import
    backtest`` (ou ``analyse``) se lit comme l'import du module, que les clôtures
    ci-dessous voient."""
    tree = ast.parse("from mountain_perf import analyse, backtest\nimport pyarrow\n")
    assert _modules(_imported_modules(tree, "mountain_perf.analyse")) == {
        "mountain_perf",
        "mountain_perf.analyse",
        "mountain_perf.backtest",
        "pyarrow",
    }


def test_analyse_never_imports_the_backtest() -> None:
    for path in sorted(ANALYSE.rglob("*.py")):
        assert not any(
            m == "mountain_perf.backtest" or m.startswith("mountain_perf.backtest.")
            for m in _imports(path)
        ), path


def test_analyse_reads_the_common_clocks() -> None:
    imports = _imports(ANALYSE / "climbs.py")
    assert "mountain_perf.clocks" in imports
    assert "mountain_perf.series" in imports


def test_the_climb_heart_rate_reads_the_engine_window() -> None:
    """La FC d'une montée se mesure par l'outil de FC du moteur (AN3-1a, ``0017``,
    P5.1)."""
    assert "mountain_perf.estimation.intervals" in _imports(ANALYSE / "heart_rate.py")


def test_only_the_parquet_module_imports_pyarrow() -> None:
    importers = sorted(
        path.relative_to(SOURCE).as_posix()
        for path in SOURCE.rglob("*.py")
        if any(m == "pyarrow" or m.startswith("pyarrow.") for m in _imports(path))
    )
    assert importers == ["analyse/parquet.py"]


def test_only_the_plot_module_imports_plotly() -> None:
    importers = sorted(
        path.relative_to(SOURCE).as_posix()
        for path in SOURCE.rglob("*.py")
        if any(m == "plotly" or m.startswith("plotly.") for m in _imports(path))
    )
    assert importers == ["analyse/plot.py"]


INFERENCE = ANALYSE / "inference"


def _importers(library: str) -> list[str]:
    return sorted(
        path.relative_to(SOURCE).as_posix()
        for path in SOURCE.rglob("*.py")
        if any(m == library or m.startswith(f"{library}.") for m in _imports(path))
    )


def test_only_the_inference_package_imports_numpy_and_scipy() -> None:
    """T40 (AN3-1, ``0021``) : les importeurs de numpy, et ceux de scipy, dans ``src/``
    existent et sont tous sous ``analyse/inference/`` ; aucun module
    d'``analyse/inference/`` n'importe ``mountain_perf`` hors du paquet."""
    for library in ("numpy", "scipy"):
        importers = _importers(library)
        assert importers, library
        assert all(i.startswith("analyse/inference/") for i in importers), importers
    modules = sorted(INFERENCE.glob("*.py"))
    assert modules
    for path in modules:
        assert all(
            m == "mountain_perf.analyse.inference"
            or m.startswith("mountain_perf.analyse.inference.")
            for m in _package_imports(path)
        ), path.name


def test_the_common_git_state_uses_the_standard_library() -> None:
    """``gitstate.py`` n'importe que la bibliothèque standard : ni le moteur, ni la
    piste."""
    imports = _imports(SOURCE / "gitstate.py")
    assert not any(m.startswith("mountain_perf") for m in imports)
    assert {m.split(".")[0] for m in imports} <= set(sys.stdlib_module_names) | {
        "__future__"
    }


def test_the_engine_does_not_import_analyse() -> None:
    for folder in ("schemas", "gpx", "model", "backtest", "ingest"):
        for path in sorted((SOURCE / folder).rglob("*.py")):
            assert not any(
                m.startswith("mountain_perf.analyse") for m in _imports(path)
            ), path
    for name in ("codec.py", "validation.py", "config.py", "units.py", "gitstate.py"):
        assert not any(
            m.startswith("mountain_perf.analyse") for m in _imports(SOURCE / name)
        ), name
    for name in ("series.py", "clocks.py"):
        assert not any(
            m.startswith("mountain_perf.analyse") for m in _imports(SOURCE / name)
        ), name


def _allowed(name: str, modules: tuple[str, ...]) -> bool:
    return any(name == m or name.startswith(f"{m}.") for m in modules)


def _package_imports(path: Path) -> set[str]:
    return {m for m in _imports(path) if m.split(".")[0] == "mountain_perf"}


def _standard_only(imports: set[str]) -> bool:
    return all(
        m.split(".")[0] in {*sys.stdlib_module_names, "__future__"}
        for m in imports
        if m.split(".")[0] != "mountain_perf"
    )


PURE = ("mountain_perf.schemas", "mountain_perf.validation")


def test_the_journal_imports_only_the_standard_library_and_the_contracts() -> None:
    path = ANALYSE / "journal.py"
    package = _package_imports(path)
    assert package
    assert all(_allowed(m, PURE) for m in package)
    assert _standard_only(_imports(path))


def test_the_normals_import_only_the_standard_library_and_the_contracts() -> None:
    path = ANALYSE / "normals.py"
    assert all(_allowed(m, PURE) for m in _package_imports(path))
    assert _standard_only(_imports(path))


def test_the_days_read_the_views_the_journal_and_the_normals() -> None:
    path = ANALYSE / "days.py"
    allowed = (
        *PURE,
        "mountain_perf.ingest.day_views",
        "mountain_perf.ingest.interim",
        "mountain_perf.ingest.types",
        "mountain_perf.ingest.families",
        "mountain_perf.analyse.journal",
        "mountain_perf.analyse.normals",
    )
    package = _package_imports(path)
    assert all(_allowed(m, allowed) for m in package)
    assert "mountain_perf.ingest.day_views" in package
    assert "mountain_perf.analyse.normals" in package
    assert _standard_only(_imports(path))


EXTRAS = (
    "pyarrow",
    "plotly",
    "numpy",
    "scipy",
    "fitdecode",
    "mountain_perf.ingest.fit",
)
"""Les extras, et le seul module qui importe fitdecode."""


@pytest.mark.parametrize(
    ("module", "forbidden"),
    [
        ("mountain_perf.analyse.tables", (*EXTRAS, "mountain_perf.backtest")),
        ("mountain_perf.analyse.heart_rate", (*EXTRAS, "mountain_perf.backtest")),
        ("mountain_perf.analyse.journal", (*EXTRAS, "mountain_perf.backtest")),
        ("mountain_perf.analyse.normals", (*EXTRAS, "mountain_perf.backtest")),
        ("mountain_perf.analyse.days", (*EXTRAS, "mountain_perf.backtest")),
        ("mountain_perf.analyse.q1", (*EXTRAS, "mountain_perf.backtest")),
        ("mountain_perf.analyse.results", (*EXTRAS, "mountain_perf.backtest")),
        ("mountain_perf.gitstate", (*EXTRAS, "mountain_perf.backtest")),
        ("mountain_perf.cli", EXTRAS),
    ],
)
def test_tables_compute_without_the_extras(
    module: str, forbidden: tuple[str, ...]
) -> None:
    """Dans un processus neuf, importer le calcul des tables, de la figure ou des
    résultats, ou l'état git commun, ne charge ni un extra, ni le moteur ; importer
    ``mperf`` ne charge aucun extra (``mperf tables`` et ``mperf q1`` importent la
    lecture et l'écriture Parquet, et le rendu, dans la commande)."""
    code = (
        "import sys\n"
        f"import {module}\n"
        f"forbidden = {forbidden!r}\n"
        "loaded = sorted(m for m in sys.modules if any(m == f or"
        " m.startswith(f + '.') for f in forbidden))\n"
        "print(loaded)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"


Q2 = ANALYSE / "q2"
Q2_FORBIDDEN = ("numpy", "scipy", "pyarrow", "plotly", "mountain_perf.backtest")


def test_q2_never_imports_numpy_scipy_pyarrow_plotly_or_the_backtest() -> None:
    """AN3-3b (Q-32, T40) : aucun module d'``analyse/q2/`` n'importe numpy, scipy,
    pyarrow, plotly ni le backtest, même sous ``TYPE_CHECKING`` (l'AST entier est
    lu) ; les calculs matriciels passent par ``analyse/inference/``."""
    modules = sorted(Q2.glob("*.py"))
    assert modules
    for path in modules:
        assert not any(
            m == f or m.startswith(f"{f}.")
            for m in _imports(path)
            for f in Q2_FORBIDDEN
        ), path.name


def test_a_q2_import_under_type_checking_is_seen() -> None:
    tree = ast.parse(
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import numpy\n"
    )
    assert "numpy" in _modules(_imported_modules(tree, "mountain_perf.analyse.q2"))


def _under_type_checking(tree: ast.Module) -> set[int]:
    """Les nœuds placés sous un ``if TYPE_CHECKING:`` (ou ``typing.TYPE_CHECKING``)."""
    inside: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        name = (
            test.id
            if isinstance(test, ast.Name)
            else test.attr
            if isinstance(test, ast.Attribute)
            else None
        )
        if name == "TYPE_CHECKING":
            inside |= {id(child) for stmt in node.body for child in ast.walk(stmt)}
    return inside


def test_plot_imports_q2_only_under_type_checking() -> None:
    """Correctifs de la PR #52 : ``analyse/plot.py`` n'importe ``analyse.q2`` que sous
    ``TYPE_CHECKING`` (la figure de Q2 n'y sert qu'à une annotation). Contre un import
    remonté au niveau du module, qui ferait charger ``q2/model.py`` et ``inference/``
    à quiconque importe ``plot``."""
    tree = ast.parse((ANALYSE / "plot.py").read_text(encoding="utf-8"))
    guarded = _under_type_checking(tree)
    q2_imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        and any(
            m.startswith("mountain_perf.analyse.q2")
            for m in _modules(
                _imported_modules(
                    ast.Module(body=[node], type_ignores=[]), "mountain_perf.analyse"
                )
            )
        )
    ]
    assert q2_imports
    assert all(id(node) in guarded for node in q2_imports)


def test_importing_plot_does_not_load_the_q2_model() -> None:
    """Correctifs de la PR #52 : dans un processus neuf, importer
    ``mountain_perf.analyse.plot`` ne charge pas ``mountain_perf.analyse.q2.model``.
    Contre la garde ``TYPE_CHECKING`` ôtée."""
    pytest.importorskip("plotly")
    code = (
        "import sys\n"
        "import mountain_perf.analyse.plot\n"
        "print('mountain_perf.analyse.q2.model' in sys.modules)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"


def test_the_cli_imports_q2_only_inside_a_function() -> None:
    """``mperf`` s'importe sans l'extra ``analyse`` : ``cli.py`` n'importe
    ``analyse.q2`` que dans le corps d'une fonction."""
    tree = ast.parse((SOURCE / "cli.py").read_text(encoding="utf-8"))
    inside = {
        id(node)
        for function in ast.walk(tree)
        if isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef)
        for node in ast.walk(function)
    }
    top = ast.Module(
        body=[
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Import | ast.ImportFrom) and id(n) not in inside
        ],
        type_ignores=[],
    )
    assert not any(
        m.startswith("mountain_perf.analyse.q2")
        for m in _modules(_imported_modules(top, "mountain_perf"))
    )
