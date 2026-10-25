"""Les lieux du profil de la page « projection », lisibles sur le thème sombre
(contrôle réel de M5-2) : leur règle et leur nom ont une couleur donnée, le gris ; sans
couleur, Vega les dessinait en noir, sur le fond presque noir du thème sombre.

Sautés sans l'extra ``tableau``.
"""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest

import mountain_perf
from mountain_perf.config import data_dir

APP = Path(mountain_perf.__file__).parent / "ui" / "app.py"
FIXTURES = Path(__file__).parent / "fixtures"
ROUTE = FIXTURES / "mini_11.gpx"
CURVE = FIXTURES / "courbe_synthetique.csv"
COMPANION = FIXTURES / "courbe_synthetique.meta.json"
TIMEOUT_S = 30


def _profile_layers() -> list[dict[str, Any]]:
    """Les couches de la première figure de la page, sur un préparé à lieux nommés."""
    routes, reference = data_dir() / "routes", data_dir() / "reference"
    routes.mkdir(exist_ok=True)
    reference.mkdir(exist_ok=True)
    shutil.copy(ROUTE, routes / ROUTE.name)
    shutil.copy(CURVE, reference / CURVE.name)
    shutil.copy(COMPANION, reference / COMPANION.name)
    at = AppTest.from_file(APP, default_timeout=TIMEOUT_S).run()
    assert not at.exception
    profile = json.loads(at.get("vega_lite_chart")[0].proto.spec)
    layers: list[dict[str, Any]] = profile["layer"]
    return layers


def test_the_places_of_the_profile_are_gray() -> None:
    line, rule, text = _profile_layers()
    assert line["mark"] == "line"
    assert rule["mark"] == {"type": "rule", "strokeDash": [4, 4], "color": "gray"}
    assert text["mark"]["type"] == "text"
    assert text["mark"]["color"] == "gray"
    assert [value["passage"] for value in text["data"]["values"]] == [
        "Départ",
        "Départ",
        "Col",
        "Arrivée",
    ]
