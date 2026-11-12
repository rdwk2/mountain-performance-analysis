"""Les rapports de la commande glissante (OG-2, § 6.7 et § 6.9 (a)), correctifs de la
PR #44 : chaque rapport D15 est écrit après son RÉSULTAT, avant la fenêtre suivante,
et un ÉCHEC au ``W`` k garde ceux des ``W`` précédents (B-1 de la relecture C du
bloc 2) ; le rapport D15 glissant porte les lignes du registre et du rapport, comme le
mode « courbe déclarée » (B-2, point 1)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from mountain_perf import cli
from mountain_perf.backtest import rolling as rolling_module
from mountain_perf.backtest.registry import line_hash
from mountain_perf.config import data_dir
from test_og2_rolling import activities, build_world, events, fix_world, rolling


@pytest.fixture(autouse=True)
def _world(monkeypatch: pytest.MonkeyPatch) -> None:
    fix_world(monkeypatch)


def _reports() -> list[str]:
    folder = data_dir() / "rapports"
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def _failing_second_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """``evaluate_rolling`` en panne à son deuxième appel : le calcul du second
    ``W``."""
    original = rolling_module.evaluate_rolling
    calls: list[int] = []

    def failing(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("panne simulée pendant le calcul du second W")
        return original(*args, **kwargs)

    monkeypatch.setattr(rolling_module, "evaluate_rolling", failing)


def test_a_failure_at_the_second_window_keeps_the_first_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§ 6.7 (a) : « le rapport écrit après son RÉSULTAT » ; (c) : une erreur → l'ÉCHEC
    de ce ``W``. Le RÉSULTAT 2 est annoncé, avec son sceau, et son rapport écrit avant
    la DÉCLARATION 3 ; l'ÉCHEC 4 arrête la commande."""
    manifest = build_world(tmp_path)
    _failing_second_window(monkeypatch)
    outcome = rolling(manifest, "28,56")
    recorded = events()
    assert [e.kind.value for e in recorded] == [
        "declaration",
        "result",
        "declaration",
        "failure",
    ]
    assert outcome.code == 1
    assert "panne simulée pendant le calcul du second W" in outcome.err
    lines = outcome.out.splitlines()
    assert [line.split()[0] for line in lines] == [
        "déclaration",
        "résultat",
        "rapport",
        "déclaration",
    ]
    assert lines[1] == (
        f"{'résultat':<13}2 enregistré ; dernière ligne sha256 {line_hash(recorded[1])}"
    )
    assert lines[2] == f"{'rapport':<13}rapports/backtest-0002.txt"
    assert _reports() == ["backtest-0002.txt"]


def test_after_a_failure_the_next_windows_are_not_declared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§ 6.7 (c) : « une erreur → l'ÉCHEC de ce ``W``, ``BacktestError``, et la
    commande s'arrête (les ``W`` suivants ne sont pas déclarés) ». Trois ``W``, le
    second en panne."""
    manifest = build_world(tmp_path)
    _failing_second_window(monkeypatch)
    outcome = rolling(manifest, "28,56,all")
    assert outcome.code == 1
    assert [e.kind.value for e in events()] == [
        "declaration",
        "result",
        "declaration",
        "failure",
    ]
    assert _reports() == ["backtest-0002.txt"]


def test_an_unwritten_report_stops_the_command_before_the_next_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un rapport non écrit (ici, celui du premier ``W``) : le message d'aujourd'hui
    (``REPORT_NOT_WRITTEN_ERROR``, avec le sceau du RÉSULTAT), le code 1, et le second
    ``W`` n'est pas déclaré ; aucun ÉCHEC n'est écrit (le RÉSULTAT est au registre)."""
    manifest = build_world(tmp_path)

    def refused(data: Path, name: str, text: str) -> None:
        del data, text
        raise OSError(f"disque plein ({name})")

    monkeypatch.setattr(cli, "_write_report", refused)
    outcome = rolling(manifest, "28,56")
    recorded = events()
    assert [e.kind.value for e in recorded] == ["declaration", "result"]
    assert outcome.code == 1
    assert outcome.err.strip() == cli.REPORT_NOT_WRITTEN_ERROR.format(
        number=2,
        seal=line_hash(recorded[1]),
        name="rapports/backtest-0002.txt",
        reason="OSError (errno None)",
    )
    lines = outcome.out.splitlines()
    assert [line.split()[0] for line in lines] == ["déclaration", "résultat"]


def test_the_rolling_report_carries_the_registry_and_report_lines(
    tmp_path: Path,
) -> None:
    """§ 6.9 (a) : « ce qui change en mode glissant, et rien d'autre ». Comme le mode
    « courbe déclarée » (``_summary``), la synthèse du rapport porte, après sa première
    ligne, « registre déclaration …, résultat … ; dernière ligne sha256 … » et la ligne
    « à recopier au JOURNAL », et finit par « rapport <nom> » ; la sortie standard ne
    change pas (une ligne par événement, une ligne par rapport)."""
    manifest = build_world(tmp_path, activities(first=date(2026, 6, 3)))
    outcome = rolling(manifest, "4,28", "--rule-support-threshold", "5")
    assert outcome.code == 0, outcome.err
    recorded = events()
    for number in (2, 4):
        name = f"rapports/backtest-{number:04d}.txt"
        lines = (data_dir() / name).read_text(encoding="utf-8").splitlines()
        assert lines[0].startswith(f"{'backtest':<13}")
        assert lines[1] == (
            f"{'registre':<13}déclaration {number - 1}, résultat {number} ; "
            f"dernière ligne sha256 {line_hash(recorded[number - 1])}"
        )
        assert lines[2].endswith(
            "à recopier au JOURNAL : l'empreinte de la dernière ligne scelle le "
            "registre"
        )
        assert lines[3].startswith(f"{'manifeste':<13}")
        assert sum(line.startswith("rapport ") for line in lines) == 1
        assert f"{'rapport':<13}{name}" in lines
    assert [line.split()[0] for line in outcome.out.splitlines()] == [
        "déclaration",
        "résultat",
        "rapport",
        "déclaration",
        "résultat",
        "rapport",
        "comparaison",
    ]
