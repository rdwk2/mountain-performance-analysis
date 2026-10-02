"""Réemploi (§ 6 et § 8.1, test 7, du brief M4b-1 ; précision 2 de la relecture du
plan).

``backtest/metrics.py`` n'importe aucun module de ``mountain_perf.backtest`` ; parmi
les modules du projet, seulement ``mountain_perf.schemas`` et
``mountain_perf.validation``, que le § 6 permet. Aucun module de ``src/`` ne l'importe,
hors l'export de ``backtest/__init__.py`` et ``backtest/scoring.py``, son consommateur
(§ 6 du brief M4b-2). Lecture de son arbre syntaxique, comme
``test_backtest_passages_reuse.py``.

Et les valeurs publiées par ``support_metrics`` sont, **au bit**, celles des fonctions
pures appliquées aux valeurs publiées (choix 1 du brief) : ``L`` et ``E_R`` par
``log_ratio``, ``E_R − L`` par une seule soustraction, ``A`` et ``D_R`` par
``time_weighted_deviation``, ``C_comp`` par ``compensation`` — jamais par
``W + B − A``.
"""

import ast
import math
from pathlib import Path

import pytest

import mountain_perf
import mountain_perf.backtest as backtest
from fixtures.metrics import SUPPORT_CASES
from mountain_perf.backtest import (
    compensation,
    log_ratio,
    support_metrics,
    time_weighted_deviation,
)

PACKAGE = Path(backtest.__file__).parent
SOURCE = Path(mountain_perf.__file__).parent
METRICS = ast.parse((PACKAGE / "metrics.py").read_text(encoding="utf-8"))

PROJECT_MODULES_ALLOWED = {"mountain_perf.schemas", "mountain_perf.validation"}
"""§ 6 : ``backtest/metrics.py`` importe ``math``, ``mountain_perf.schemas`` et
``mountain_perf.validation``."""


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
    """Le paquet d'un fichier de ``src/`` : ``mountain_perf.backtest`` pour
    ``backtest/metrics.py``."""
    return ".".join(("mountain_perf", *path.relative_to(SOURCE).parent.parts))


def test_relative_imports_are_resolved() -> None:
    """Correctif de la relecture : un import relatif compte comme l'import absolu
    qu'il désigne."""
    tree = ast.parse(
        "from .passages import observe_passages\n"
        "from . import metrics\n"
        "from ..schemas import MetricValue\n"
    )
    assert _imported_modules(tree, "mountain_perf.backtest") == {
        "mountain_perf.backtest.passages": {"observe_passages"},
        "mountain_perf.backtest": {"metrics"},
        "mountain_perf.schemas": {"MetricValue"},
    }


def _defined_names(tree: ast.Module) -> set[str]:
    names = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    }
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def test_metrics_imports_no_backtest_module() -> None:
    """Précision 2 : aucun module ``mountain_perf.backtest*``."""
    imported = _imported_modules(METRICS, "mountain_perf.backtest")
    assert not [name for name in imported if name.startswith("mountain_perf.backtest")]


def test_metrics_imports_only_schemas_and_validation_from_the_project() -> None:
    imported = _imported_modules(METRICS, "mountain_perf.backtest")
    project = {name for name in imported if name.startswith("mountain_perf")}
    assert project <= PROJECT_MODULES_ALLOWED


def test_no_module_imports_metrics_but_the_backtest_package() -> None:
    """§ 6 : l'export de ``backtest/__init__.py`` est la seule importation permise de
    ``backtest/metrics.py``, ni par son nom de module, ni par ses noms depuis le
    paquet ``backtest`` — avec, depuis M4b-2, ``backtest/scoring.py``, qui assemble les
    vecteurs et appelle ses fonctions (§ 6 du brief M4b-2) — et, depuis M4b-3,
    ``backtest/repeatability.py``, qui appelle ``support_metrics`` sur les prévisions
    d'un pli (§ 6 du brief M4b-3)."""
    defined = _defined_names(METRICS)
    importers = []
    allowed = (
        PACKAGE / "__init__.py",
        PACKAGE / "metrics.py",
        PACKAGE / "scoring.py",
        PACKAGE / "repeatability.py",
    )
    for path in sorted(SOURCE.rglob("*.py")):
        if path in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for module, names in _imported_modules(tree, _package(path)).items():
            by_module = module == "mountain_perf.backtest.metrics"
            by_package = module == "mountain_perf.backtest" and names & (
                defined | {"metrics"}
            )
            if by_module or by_package:
                importers.append(path.relative_to(SOURCE).as_posix())
    assert importers == []


def test_the_backtest_package_exports_metrics() -> None:
    init = ast.parse((PACKAGE / "__init__.py").read_text(encoding="utf-8"))
    assert "mountain_perf.backtest.metrics" in _imported_modules(
        init, "mountain_perf.backtest"
    )


def _hex(value: float | None) -> str:
    assert value is not None
    return value.hex()


@pytest.mark.parametrize("name", ["T12", "Dyadique", "Quatre classes", "Une classe"])
def test_published_values_are_the_pure_functions_at_the_bit(name: str) -> None:
    """Test 7 : ``L``, ``E_R``, ``E_R − L``, ``A``, ``D_R`` et ``C_comp`` publiés
    égalent au bit les fonctions pures appliquées aux valeurs publiées (``0010`` D7.2,
    choix 1)."""
    case = SUPPORT_CASES[name]
    p = [value for value in case.projected_s if value is not None]
    t, classes = case.observed_s, case.classes
    assert len(p) == len(t)
    metrics = support_metrics(p, t, classes)
    level = metrics.log_ratio.value
    assert level is not None
    assert level.hex() == log_ratio(math.fsum(p), math.fsum(t)).hex()
    r = [log_ratio(p_i, t_i) for p_i, t_i in zip(p, t, strict=True)]
    levels = {}
    for regime in metrics.classes:
        members = [i for i, c in enumerate(classes) if c is regime.regime_class]
        if not members:
            continue
        p_r = [p[i] for i in members]
        t_r = [t[i] for i in members]
        class_level = regime.log_ratio.value
        assert class_level is not None
        assert class_level.hex() == log_ratio(math.fsum(p_r), math.fsum(t_r)).hex()
        assert _hex(regime.shape.value) == (class_level - level).hex()
        dispersion = time_weighted_deviation(
            [r[i] for i in members], [class_level] * len(members), t_r
        )
        assert _hex(regime.dispersion.value) == dispersion.hex()
        levels[regime.regime_class] = class_level
    dispersion = time_weighted_deviation(r, [level] * len(t), t)
    assert _hex(metrics.dispersion.value) == dispersion.hex()
    compensation_value = compensation(r, [levels[c] for c in classes], level, t)
    assert _hex(metrics.compensation.value) == compensation_value.hex()


def test_zero_time_level_is_log_ratio_at_the_bit() -> None:
    """§ 6.4, étape 5 : sous temps nul, ``L`` par la même écriture
    ``log_ratio(fsum p, fsum t)``, au bit (« Temps nul » du § 7.1 : ``ln 2``)."""
    case = SUPPORT_CASES["Temps nul"]
    p = [value for value in case.projected_s if value is not None]
    metrics = support_metrics(p, case.observed_s, case.classes)
    expected = log_ratio(math.fsum(p), math.fsum(case.observed_s))
    assert _hex(metrics.log_ratio.value) == expected.hex()
