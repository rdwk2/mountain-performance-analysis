"""La table ``[analyse]`` d'``athlete.toml`` (``mountain_perf.analyse.athlete``,
``docs/decisions/0014``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from mountain_perf.analyse.athlete import (
    DEFAULT_SETTINGS,
    AthleteError,
    AthleteSettings,
    read_athlete,
)


def write(folder: Path, text: str) -> Path:
    (folder / "athlete.toml").write_text(text, encoding="utf-8")
    return folder


def test_absent_file_gives_the_defaults(tmp_path: Path) -> None:
    settings = read_athlete(tmp_path)
    assert settings == DEFAULT_SETTINGS
    assert settings.reference_vertical_speed_ms == 0.25
    assert settings.reference_vertical_speed_declared is False


def test_a_file_without_the_table_gives_the_defaults(tmp_path: Path) -> None:
    assert read_athlete(write(tmp_path, "[autre]\nx = 1\n")) == DEFAULT_SETTINGS


def test_the_declared_speed_is_read_in_metres_per_hour(tmp_path: Path) -> None:
    text = "[analyse]\nreference_vertical_speed_m_per_h = 720\n"
    settings = read_athlete(write(tmp_path, text))
    assert settings.reference_vertical_speed_ms == 0.2
    assert settings.reference_vertical_speed_declared is True


def test_barometer_products(tmp_path: Path) -> None:
    text = (
        "[analyse]\n"
        'barometer_products = [{ manufacturer = "garmin", product = 3 },'
        ' { manufacturer = "x", product = 0 }]\n'
    )
    settings = read_athlete(write(tmp_path, text))
    assert settings.barometer_products == frozenset({("garmin", 3), ("x", 0)})
    assert settings.reference_vertical_speed_ms == 0.25
    assert settings.reference_vertical_speed_declared is False
    assert settings.barometric(None, "garmin", 3) is True
    assert settings.barometric(None, "garmin", 4) is False
    assert settings.barometric(False, "garmin", 3) is False
    assert settings.barometric(True, None, None) is True


SPEED = "reference_vertical_speed_m_per_h : un nombre de 100 à 5000 m/h"
PRODUCTS = "barometer_products : des tables { manufacturer, product }"
PRODUCT = (
    "barometer_products : un fabricant non vide et un numéro de produit entier"
    " positif ou nul"
)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[analyse]\nvref = 700\n", "[analyse] : clés inconnues ['vref']"),
        ("[analyse]\nreference_vertical_speed_m_per_h = 99.9\n", SPEED),
        ("[analyse]\nreference_vertical_speed_m_per_h = 5000.1\n", SPEED),
        ("[analyse]\nreference_vertical_speed_m_per_h = true\n", SPEED),
        ("[analyse]\nreference_vertical_speed_m_per_h = 'x'\n", SPEED),
        ("[analyse]\nreference_vertical_speed_m_per_h = nan\n", SPEED),
        ("analyse = 3\n", "[analyse] n'est pas une table"),
        ('[analyse]\nbarometer_products = [{ manufacturer = "g" }]\n', PRODUCTS),
        ('[analyse]\nbarometer_products = ["g"]\n', PRODUCTS),
        (
            '[analyse]\nbarometer_products = [{ manufacturer = "", product = 1 }]\n',
            PRODUCT,
        ),
        (
            '[analyse]\nbarometer_products = [{ manufacturer = "g", product = -1 }]\n',
            PRODUCT,
        ),
        (
            "[analyse]\nbarometer_products = "
            '[{ manufacturer = "g", product = true }]\n',
            PRODUCT,
        ),
        (
            "[analyse]\nbarometer_products = [{ manufacturer = 3, product = 1 }]\n",
            PRODUCT,
        ),
        (
            "[analyse]\nbarometer_products = 3\n",
            "barometer_products : une liste de tables",
        ),
        (
            '[analyse]\nbarometer_products = { manufacturer = "g", product = 1 }\n',
            "barometer_products : une liste de tables",
        ),
    ],
)
def test_refusals(tmp_path: Path, text: str, message: str) -> None:
    """Chaque refus, avec son message entier."""
    with pytest.raises(AthleteError) as refused:
        read_athlete(write(tmp_path, text))
    assert str(refused.value) == message


def test_an_unreadable_file(tmp_path: Path) -> None:
    write(tmp_path, "[analyse\n")
    with pytest.raises(AthleteError, match=r"^athlete\.toml illisible : "):
        read_athlete(tmp_path)
    (tmp_path / "athlete.toml").write_bytes(b"[analyse]\n# \xe9t\xe9\n")
    with pytest.raises(AthleteError, match=r"^athlete\.toml illisible : "):
        read_athlete(tmp_path)


def test_a_file_in_utf8_is_read_as_utf8(tmp_path: Path) -> None:
    text = (
        '[analyse]\n# été\nbarometer_products = [{ manufacturer = "é", product = 1 }]\n'
    )
    (tmp_path / "athlete.toml").write_bytes(text.encode("utf-8"))
    assert read_athlete(tmp_path).barometer_products == frozenset({("é", 1)})


def test_the_bounds_are_inclusive(tmp_path: Path) -> None:
    for value in ("100", "5000"):
        text = f"[analyse]\nreference_vertical_speed_m_per_h = {value}\n"
        settings = read_athlete(write(tmp_path, text))
        assert settings.reference_vertical_speed_ms == float(value) / 3600


def test_settings_are_a_value(tmp_path: Path) -> None:
    assert AthleteSettings(0.25, False, frozenset()) == DEFAULT_SETTINGS
