"""Tests du module de configuration.

Ces tests ne dépendent jamais du ``.env`` de la machine : la variable est posée
ou retirée explicitement par ``monkeypatch`` à chaque test.
"""

from pathlib import Path

import pytest

from mountain_perf.config import DATA_DIR_ENV_VAR, ConfigError, data_dir


def test_missing_variable_raises_with_instructions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DATA_DIR_ENV_VAR, raising=False)
    with pytest.raises(ConfigError, match=r"n'est pas définie.*\.env\.example"):
        data_dir()


def test_empty_variable_is_treated_as_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATA_DIR_ENV_VAR, "   ")
    with pytest.raises(ConfigError, match="n'est pas définie"):
        data_dir()


def test_nonexistent_directory_raises_with_resolved_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = tmp_path / "nope"
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(missing))
    with pytest.raises(ConfigError, match="inexistant") as excinfo:
        data_dir()
    assert str(missing.resolve()) in str(excinfo.value)
    assert ".env.example" in str(excinfo.value)


def test_existing_directory_is_returned_resolved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path))
    result = data_dir()
    assert result == tmp_path.resolve()
    assert result.is_absolute()
    assert result.is_dir()


def test_file_instead_of_directory_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    a_file = tmp_path / "file.txt"
    a_file.write_text("x")
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(a_file))
    with pytest.raises(ConfigError, match="inexistant"):
        data_dir()
