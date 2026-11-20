"""La table ``[periodes]`` d'``athlete.toml``, lue pour Q2 (AN3-3b, Q-33). Bibliothèque
standard seule : ce fichier n'a pas le saut de numpy. Dates inventées."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from mountain_perf.analyse.athlete import (
    ATHLETE_FILE,
    AthleteError,
    Periods,
    read_athlete,
    read_periods,
)


def _write(folder: Path, text: str) -> Path:
    (folder / ATHLETE_FILE).write_text(text, encoding="utf-8")
    return folder


def test_the_discovery_period_is_read(tmp_path: Path) -> None:
    _write(
        tmp_path,
        '[periodes]\ndecouverte = { debut = "2031-03-01", fin = "2031-05-31" }\n',
    )
    assert read_periods(tmp_path) == Periods(date(2031, 3, 1), date(2031, 5, 31))


def test_a_one_day_period_is_admitted(tmp_path: Path) -> None:
    _write(
        tmp_path,
        '[periodes]\ndecouverte = { debut = "2031-03-01", fin = "2031-03-01" }\n',
    )
    assert read_periods(tmp_path) == Periods(date(2031, 3, 1), date(2031, 3, 1))


def test_no_file_or_no_table_means_no_period(tmp_path: Path) -> None:
    assert read_periods(tmp_path) is None
    _write(tmp_path, "[analyse]\nreference_vertical_speed_m_per_h = 900\n")
    assert read_periods(tmp_path) is None


def test_the_periods_do_not_disturb_the_analyse_table(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "[analyse]\nreference_vertical_speed_m_per_h = 900\n"
        '[periodes]\ndecouverte = { debut = "2031-03-01", fin = "2031-05-31" }\n',
    )
    assert read_athlete(tmp_path).reference_vertical_speed_ms == 900 / 3600


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('periodes = "x"\n', r"\[periodes\] n'est pas une table"),
        (
            '[periodes]\nautre = { debut = "2031-03-01", fin = "2031-05-31" }\n',
            r"clés inconnues \['autre'\]",
        ),
        ("[periodes]\n", "decouverte manque"),
        ('[periodes]\ndecouverte = { debut = "2031-03-01" }\n', r"\{ debut, fin \}"),
        (
            '[periodes]\ndecouverte = { debut = "2031-03-01", fin = "2031-05-31",'
            " x = 1 }\n",
            r"\{ debut, fin \}",
        ),
        ('[periodes]\ndecouverte = "2031-03-01"\n', r"\{ debut, fin \}"),
        (
            "[periodes]\ndecouverte = { debut = 2031-03-01, fin = 2031-05-31 }\n",
            "decouverte.debut : une date",
        ),
        (
            '[periodes]\ndecouverte = { debut = "2031-3-1", fin = "2031-05-31" }\n',
            "decouverte.debut : une date",
        ),
        (
            '[periodes]\ndecouverte = { debut = "2031-03-01", fin = "2031-02-30" }\n',
            "decouverte.fin : date invalide",
        ),
        (
            '[periodes]\ndecouverte = { debut = "2031-05-31", fin = "2031-03-01" }\n',
            "fin précède debut",
        ),
        ("[periodes\n", "illisible"),
    ],
)
def test_invalid_periods_are_refused(tmp_path: Path, text: str, message: str) -> None:
    _write(tmp_path, text)
    with pytest.raises(AthleteError, match=message):
        read_periods(tmp_path)
