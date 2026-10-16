"""Clôtures d'import de l'ingestion (``0011``, ``0013``) : fitdecode n'entre que par
``ingest/fit.py`` ; ``interim/`` se lit et les vues se calculent sans lui ; l'ingestion
importe le codec commun, jamais ``mountain_perf.backtest`` ; le moteur n'importe pas
l'ingestion."""

from __future__ import annotations

import ast
import subprocess
import sys
import types
from pathlib import Path

import pytest

import mountain_perf
import mountain_perf.ingest
from mountain_perf.cli import main
from test_backtest_metrics_reuse import _imported_modules, _package

SOURCE = Path(mountain_perf.__file__).parent
INGEST = SOURCE / "ingest"
STDLIB = set(sys.stdlib_module_names)


def _imports(path: Path) -> dict[str, set[str]]:
    return _imported_modules(
        ast.parse(path.read_text(encoding="utf-8")), _package(path)
    )


def test_only_the_fit_reader_imports_fitdecode() -> None:
    importers = sorted(
        path.relative_to(SOURCE).as_posix()
        for path in SOURCE.rglob("*.py")
        if any(m.split(".")[0] == "fitdecode" for m in _imports(path))
    )
    assert importers == ["ingest/fit.py"]


def test_no_extra_library_is_loaded_without_ingesting() -> None:
    """Modules chargés, dans un processus neuf : tout le paquet sauf le lecteur FIT et
    l'ingestion d'un export, CLI comprise."""
    modules = [
        "mountain_perf",
        "mountain_perf.schemas",
        "mountain_perf.codec",
        "mountain_perf.gpx.profile",
        "mountain_perf.model",
        "mountain_perf.backtest",
        "mountain_perf.ingest",
        "mountain_perf.ingest.interim",
        "mountain_perf.ingest.views",
        "mountain_perf.ingest.index",
        "mountain_perf.ingest.types",
        "mountain_perf.cli",
    ]
    code = (
        "import importlib, sys\n"
        f"for name in {modules!r}: importlib.import_module(name)\n"
        "print(sorted(m for m in sys.modules if m.split('.')[0] == 'fitdecode'))\n"
        "print('mountain_perf.ingest.fit' in sys.modules)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.split("\n")[:2] == ["[]", "False"]


def test_ingest_imports_the_common_codec_never_backtest() -> None:
    allowed_project = {
        "mountain_perf.codec",
        "mountain_perf.schemas",
        "mountain_perf.validation",
        "mountain_perf.ingest.export",
        "mountain_perf.ingest.fit",
        "mountain_perf.ingest.index",
        "mountain_perf.ingest.interim",
        "mountain_perf.ingest.types",
    }
    for path in sorted(INGEST.glob("*.py")):
        project = {m for m in _imports(path) if m.startswith("mountain")}
        allowed = allowed_project | (
            {"mountain_perf.ingest.views"} if path.name == "export.py" else set()
        )
        assert project <= allowed, path.name
        outside = {
            m.split(".")[0] for m in _imports(path) if not m.startswith("mountain")
        }
        assert outside <= STDLIB | {"fitdecode", "__future__"}, path.name


def test_ingest_package_does_not_import_the_fit_reader() -> None:
    assert _imports(INGEST / "__init__.py") == {}
    for name in ("interim.py", "views.py", "index.py", "types.py"):
        assert "mountain_perf.ingest.fit" not in _imports(INGEST / name), name
        assert "mountain_perf.ingest.export" not in _imports(INGEST / name), name


def test_engine_does_not_import_the_ingestion() -> None:
    for folder in ("schemas", "gpx", "model", "backtest"):
        for path in sorted((SOURCE / folder).rglob("*.py")):
            assert not any(
                m.startswith("mountain_perf.ingest") for m in _imports(path)
            ), path
    for name in ("codec.py", "validation.py", "config.py", "units.py"):
        assert not any(
            m.startswith("mountain_perf.ingest") for m in _imports(SOURCE / name)
        )


def test_cli_ingest_without_the_extra_says_how_to_install(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """fitdecode absent (``None`` dans ``sys.modules`` : son import échoue) : un
    message, code 1, sans rien lire.

    Le paquet garde l'attribut ``export`` d'un sous-module chargé plus tôt (par un
    autre test, ou par un autre appel) : il est posé ici, pour que seule la forme
    exacte de l'import du § 5.8 du brief AN1-1 voie l'extra manquer, quels que soient
    les tests lancés avec celui-ci."""
    for name in ("mountain_perf.ingest.export", "mountain_perf.ingest.fit"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setattr(
        mountain_perf.ingest,
        "export",
        types.ModuleType("mountain_perf.ingest.export"),
        raising=False,
    )
    monkeypatch.setitem(sys.modules, "fitdecode", None)
    assert main(["ingest"]) == 1
    assert capsys.readouterr().err == (
        "Erreur : la lecture des FIT demande l'extra ingest. Installer : "
        "uv sync --extra ingest\n"
    )


def test_cli_ingest_help_is_the_one_of_the_brief(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """L'aide de ``mperf ingest``, recopiée telle quelle (§ 5.8 du brief AN1-1)."""
    monkeypatch.setenv("COLUMNS", "200")
    with pytest.raises(SystemExit) as stop:
        main(["--help"])
    assert stop.value.code == 0
    assert (
        "Ingérer l'export de MPA_DATA_DIR/raw dans MPA_DATA_DIR/interim (AN1-1)"
        in capsys.readouterr().out
    )


def test_cli_ingest_does_not_hide_another_missing_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "mountain_perf.ingest.export", None)
    with pytest.raises(ModuleNotFoundError):
        main(["ingest"])
