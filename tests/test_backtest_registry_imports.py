"""Imports du registre (§ 6 et § 8.1, test 13, du brief M4b-4).

Les contrats n'importent ni ``backtest`` ni ``model`` ; l'écriture canonique n'importe
du projet que ``mountain_perf.schemas`` ; le registre, ses seuls modules nommés ; aucune
dépendance nouvelle ; aucun module existant n'importe le codec ni le registre, hors
l'export de ``backtest/__init__.py`` (et le registre, qui importe le codec).
"""

import ast
import sys
from pathlib import Path

import mountain_perf
import mountain_perf.backtest as backtest
import mountain_perf.schemas as schemas
from test_backtest_metrics_reuse import _defined_names, _imported_modules, _package

SOURCE = Path(mountain_perf.__file__).parent
SCHEMAS_MODULE = Path(schemas.__file__).parent / "registry.py"
CODEC_MODULE = Path(backtest.__file__).parent / "codec.py"
REGISTRY_MODULE = Path(backtest.__file__).parent / "registry.py"


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


def test_contracts_import_only_the_named_contracts() -> None:
    """§ 6 : les contrats du registre, ni ``backtest`` ni ``model`` ;
    ``ModelKind`` vient des contrats du calage depuis M4c-1 (§ 2 du brief M4c-1),
    ``CALIBRATED_MODELS`` et ``CalibratedOutingScores`` depuis M4c-2
    (``OutingOutcome``)."""
    imported = _imports(SCHEMAS_MODULE)
    assert _project(SCHEMAS_MODULE) <= {
        "mountain_perf.validation",
        "mountain_perf.schemas.calibration",
        "mountain_perf.schemas.clock",
        "mountain_perf.schemas.common",
        "mountain_perf.schemas.matching",
        "mountain_perf.schemas.metrics",
        "mountain_perf.schemas.outing",
        "mountain_perf.schemas.parameters",
        "mountain_perf.schemas.scoring",
    }
    assert imported["mountain_perf.schemas.calibration"] == {
        "CALIBRATED_MODELS",
        "CalibratedOutingScores",
        "ModelKind",
    }
    assert imported["mountain_perf.schemas.clock"] <= {"CLOCKS", "Clock"}
    assert imported["mountain_perf.schemas.common"] <= {"SourceRef"}
    assert imported["mountain_perf.schemas.matching"] <= {"Coverage"}
    assert imported["mountain_perf.schemas.metrics"] <= {
        "WEIGHT_SUM_TOLERANCE",
        "MetricValue",
        "TargetMember",
    }
    assert imported["mountain_perf.schemas.outing"] <= {
        "ArtifactRef",
        "ArtifactRole",
        "Performance",
    }
    assert imported["mountain_perf.schemas.parameters"] <= {"ParameterSet"}
    assert imported["mountain_perf.schemas.scoring"] <= {"OutingScores", "Scenario"}


def test_codec_imports_schemas_only() -> None:
    assert _project(CODEC_MODULE) == {"mountain_perf.schemas"}
    assert _outside(CODEC_MODULE) <= {
        "collections.abc",
        "dataclasses",
        "datetime",
        "enum",
        "functools",
        "hashlib",
        "json",
        "math",
        "types",
        "typing",
    }


def test_registry_imports_the_named_modules_only() -> None:
    imported = _imports(REGISTRY_MODULE)
    assert _project(REGISTRY_MODULE) <= {
        "mountain_perf.schemas",
        "mountain_perf.validation",
        "mountain_perf.backtest.codec",
        "mountain_perf.backtest.calendar",
        "mountain_perf.model.curve_io",
    }
    assert imported["mountain_perf.backtest.calendar"] == {"origin"}
    assert imported["mountain_perf.model.curve_io"] <= {
        "META_SUFFIX",
        "CurveReadResult",
    }
    assert _outside(REGISTRY_MODULE) <= {
        "collections",
        "collections.abc",
        "contextlib",
        "datetime",
        "json",
        "os",
        "pathlib",
        "typing",
    }


def test_no_new_dependency() -> None:
    """§ 6 : hors du projet, la bibliothèque standard seule."""
    for path in (SCHEMAS_MODULE, CODEC_MODULE, REGISTRY_MODULE):
        tops = {name.split(".")[0] for name in _outside(path)}
        assert tops <= set(sys.stdlib_module_names), path.name


def test_no_module_imports_codec_or_registry_but_the_backtest_package() -> None:
    """§ 6 : seuls ``backtest/__init__.py`` (export) et le registre (qui importe le
    codec) les importent — et, depuis M4b-5, l'exécution, qui écrit au registre, et
    ``cli.py``, qui lit le nombre d'événements avant tout écrit (§ 6.0 du brief
    M4b-5)."""
    defined = _defined_names(
        ast.parse(CODEC_MODULE.read_text(encoding="utf-8"))
    ) | _defined_names(ast.parse(REGISTRY_MODULE.read_text(encoding="utf-8")))
    init = SOURCE / "backtest" / "__init__.py"
    importers = []
    for path in sorted(SOURCE.rglob("*.py")):
        if path in (init, CODEC_MODULE):
            continue
        for module, names in _imports(path).items():
            by_module = module in (
                "mountain_perf.backtest.codec",
                "mountain_perf.backtest.registry",
            )
            by_package = module == "mountain_perf.backtest" and names & (
                defined | {"codec", "registry"}
            )
            if by_module or by_package:
                importers.append((path.relative_to(SOURCE).as_posix(), module))
    assert importers == [
        ("backtest/execution.py", "mountain_perf.backtest.registry"),
        ("backtest/registry.py", "mountain_perf.backtest.codec"),
        ("cli.py", "mountain_perf.backtest.registry"),
    ]


def test_the_backtest_package_exports_codec_and_registry() -> None:
    imported = _imports(SOURCE / "backtest" / "__init__.py")
    assert "mountain_perf.backtest.codec" in imported
    assert "mountain_perf.backtest.registry" in imported
