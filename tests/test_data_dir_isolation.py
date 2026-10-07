"""Les fixtures ``autouse`` de ``MPA_DATA_DIR`` (§ 6.6 et § 8.1, test 11, du brief
M4c-1 ; décisions 3 et 16).

Ces tests ne demandent pas les fixtures de ``tests/conftest.py`` par leur nom : ils
lisent l'environnement, comme un test qui oublierait de le fixer. Ils vérifient que
``MPA_DATA_DIR`` désigne, pour chaque test, un dossier neuf et vide de la base
temporaire de pytest, distinct de ``tmp_path`` ; qu'un ``monkeypatch.delenv`` la retire
par-dessus ; et qu'une fixture de **module**, mise en place avant toute fixture de
portée fonction, voit déjà un dossier de la session (décision 16), jamais celui de
``.env``.
"""

import os
from pathlib import Path

import pytest

from mountain_perf.config import DATA_DIR_ENV_VAR, data_dir

MARK = "marque.txt"


def _current() -> Path:
    """Le dossier que désigne ``MPA_DATA_DIR`` ; la variable doit être posée."""
    raw = os.environ.get(DATA_DIR_ENV_VAR)
    assert raw is not None, "MPA_DATA_DIR n'est pas posée"
    return Path(raw).resolve()


@pytest.fixture(scope="module")
def module_data_dir() -> str | None:
    """``MPA_DATA_DIR`` lue à la mise en place d'une fixture de module, comme le fait
    ``world`` (``tests/test_cli_backtest.py``) avant d'exécuter la commande."""
    return os.environ.get(DATA_DIR_ENV_VAR)


def test_each_test_sees_a_fresh_empty_directory_under_the_base_temp(
    tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Décision 3 : ``MPA_DATA_DIR`` posée sur un dossier existant et vide, sous la base
    temporaire de pytest, distinct de ``tmp_path`` ; ``data_dir()`` le rend."""
    current = _current()
    assert current.is_dir()
    assert list(current.iterdir()) == []
    assert current.is_relative_to(tmp_path_factory.getbasetemp().resolve())
    assert current != tmp_path.resolve()
    assert data_dir() == current


@pytest.mark.parametrize("case", ["premier", "second"])
def test_one_directory_per_test(case: str) -> None:
    """Décision 3 : chaque test trouve son dossier vide, puis y écrit une marque ; le
    second cas ne voit pas celle du premier."""
    current = _current()
    assert list(current.iterdir()) == []
    (current / MARK).write_text(case, encoding="utf-8")


def test_a_test_can_remove_the_variable_over_the_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§ 6.6 : ``monkeypatch.delenv`` par-dessus la fixture retire la variable."""
    monkeypatch.delenv(DATA_DIR_ENV_VAR)
    assert DATA_DIR_ENV_VAR not in os.environ


def test_a_module_fixture_sees_a_session_directory(
    module_data_dir: str | None, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Décision 16 : une fixture de module voit un dossier posé, sous la base
    temporaire de pytest, distinct de celui du test."""
    assert module_data_dir is not None
    seen = Path(module_data_dir).resolve()
    assert seen.is_relative_to(tmp_path_factory.getbasetemp().resolve())
    assert seen != _current()
