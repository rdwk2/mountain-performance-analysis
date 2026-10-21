"""Garanties de la page « projection » sans test à la tête de la PR #33 (relecture de
la PR : la C et la conception) : les erreurs d'un préparé posé à la main dans
``routes/`` affichées sans trace Python ; le champ numérique d'un paramètre sans plage
d'affichage — la promesse de la ROADMAP, « chaque effet ajouté plus tard apparaît tout
seul » ; les cellules du tableau ; les messages, le bouton et l'ordre de l'ajout d'un
fichier ; l'export, fait sur la projection affichée.

Sautés sans l'extra ``tableau``.
"""

import io
import re
import shutil
from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest

import mountain_perf
from mountain_perf.config import data_dir
from mountain_perf.data_files import FileKind
from mountain_perf.model import CURVE_PARAMETER_DISPLAYS
from mountain_perf.model.export import write_passages_csv
from mountain_perf.model.views import passage_rows
from mountain_perf.runs import project_route
from mountain_perf.schemas import Projection
from mountain_perf.units import format_count, format_duration, format_pace, format_vam

APP = Path(mountain_perf.__file__).parent / "ui" / "app.py"
FIXTURES = Path(__file__).parent / "fixtures"
ROUTE = FIXTURES / "mini_11.gpx"
TRACE = FIXTURES / "appariement_trace_x01.gpx"
CURVE = FIXTURES / "courbe_synthetique.csv"
COMPANION = FIXTURES / "courbe_synthetique.meta.json"
TIMEOUT_S = 30


def _page() -> AppTest:
    return AppTest.from_file(APP, default_timeout=TIMEOUT_S).run()


def _with_route(name: str = ROUTE.name, content: bytes | None = None) -> Path:
    """Un préparé posé à la main dans ``routes/``, sans passer par l'ajout (qui
    l'aurait vérifié)."""
    routes = data_dir() / "routes"
    routes.mkdir(exist_ok=True)
    (routes / name).write_bytes(ROUTE.read_bytes() if content is None else content)
    return routes / name


def _with_curve() -> Path:
    reference = data_dir() / "reference"
    reference.mkdir(exist_ok=True)
    shutil.copy(CURVE, reference / CURVE.name)
    shutil.copy(COMPANION, reference / COMPANION.name)
    return reference / CURVE.name


def _upload(at: AppTest, path: Path) -> None:
    at.file_uploader(key="ajout_fichier").set_value(
        (path.name, path.read_bytes(), "application/gpx+xml")
    ).run()


# Les erreurs de l'étape 5, chacune par un préparé posé à la main ---------------------


@pytest.mark.parametrize(
    ("content", "error"),
    [
        # GpxError : un XML mal formé.
        (ROUTE.read_bytes()[:300], "XML mal formé"),
        # GpxError aussi : tous les points au même endroit. read_gpx refuse un tracé
        # de longueur nulle avant le profil ; la ProfileError que la page attrape
        # n'est plus atteignable par un fichier lu.
        (
            re.sub(rb'<trkpt lat="[0-9.]+"', b'<trkpt lat="45"', ROUTE.read_bytes()),
            "longueur nulle",
        ),
        # ContractError : une latitude hors de [-90, 90].
        (
            ROUTE.read_bytes().replace(b'<trkpt lat="45.', b'<trkpt lat="945.', 1),
            "latitude_deg",
        ),
    ],
    ids=["xml", "longueur_nulle", "contrat"],
)
def test_an_unusable_route_put_by_hand_is_an_error_without_traceback(
    content: bytes, error: str
) -> None:
    _with_route("pose_a_la_main.gpx", content)
    _with_curve()
    at = _page()
    assert not at.exception
    (shown,) = at.error
    assert error in str(shown.value)
    assert not at.code
    assert not at.dataframe


# Un paramètre sans plage d'affichage devient un champ numérique ----------------------


def _a_spec_without_display() -> None:
    """Une page d'essai : les contrôles d'une spec qui n'a pas de plage d'affichage."""
    import streamlit as st

    from mountain_perf.controls import parameter_controls
    from mountain_perf.schemas import ParameterSpec
    from mountain_perf.ui.components import parameter_inputs

    spec = ParameterSpec(
        name="nouvel_effet",
        unit="m",
        default=2.0,
        minimum=0.0,
        maximum=10.0,
        description="Un effet ajouté sans plage d'affichage.",
    )
    values = parameter_inputs(parameter_controls((spec,), ()), "essai")
    st.text(repr(values))


def test_a_parameter_without_display_gets_a_bounded_number_input() -> None:
    at = AppTest.from_function(_a_spec_without_display, default_timeout=TIMEOUT_S).run()
    assert not at.exception
    assert not at.slider
    (field,) = at.number_input
    assert field.key == "essai.nouvel_effet"
    assert field.label == "nouvel_effet (m)"
    assert field.min == 0.0
    assert field.max == 10.0
    assert field.value == 2.0
    assert field.help == "Un effet ajouté sans plage d'affichage."
    assert at.text[0].value == "{'nouvel_effet': 2.0}"
    field.set_value(7.5).run()
    assert at.text[0].value == "{'nouvel_effet': 7.5}"


def test_on_the_page_a_spec_without_display_becomes_a_number_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La page elle-même, la plage de l'effort retirée : un champ numérique aux
    garde-fous de la spec, dont la valeur va au moteur."""
    monkeypatch.setattr(
        "mountain_perf.ui.projection.PROJECTION_PARAMETER_DISPLAYS",
        CURVE_PARAMETER_DISPLAYS,
    )
    _with_route()
    _with_curve()
    at = _page()
    assert not at.exception
    field = at.number_input(key="projection.effort")
    assert (field.label, field.value, field.min, field.max) == ("effort", 1.0, 0.5, 1.5)
    field.set_value(0.9).run()
    assert not at.exception
    (block,) = at.code
    assert "effort       0.90" in str(block.value).split("\n")


# Le tableau : chaque cellule porte la valeur de la bibliothèque, mise en forme --------


def test_the_table_cells_are_the_library_values() -> None:
    route, curve = _with_route(), _with_curve()
    at = _page()
    (table,) = at.dataframe
    rows = passage_rows(project_route(route, curve, {}, {}).projection)
    for i, row in enumerate(rows):
        segment = row.segment
        expected = {
            "passage": row.name,
            "distance (m)": format_count(row.distance_m),
            "altitude (m)": format_count(row.elevation_m),
            "temps": format_duration(row.arrival_s),
            "heure": "—",
            "tronçon (m)": "—" if segment is None else format_count(segment.distance_m),
            "D+ (m)": "—" if segment is None else format_count(segment.ascent_m),
            "D− (m)": "—" if segment is None else format_count(segment.descent_m),
            "durée": "—" if segment is None else format_duration(segment.duration_s),
            "allure": "—" if row.speed_ms is None else format_pace(row.speed_ms),
            "montée horaire": "—"
            if row.ascent_rate_ms is None
            else format_vam(row.ascent_rate_ms),
        }
        shown = {column: table.value[column].iloc[i] for column in expected}
        assert shown == expected, i
    # Les tirets sont écrits en dur : le départ n'a pas de tronçon, et le tronçon de
    # durée nulle de mini_11.gpx n'a pas de moyennes.
    assert table.value["tronçon (m)"].iloc[0] == "—"
    assert table.value["allure"].iloc[1] == "—"
    assert table.value["montée horaire"].iloc[1] == "—"


# L'ajout d'un fichier : bouton, ordre, messages --------------------------------------


def test_the_add_button_is_disabled_without_a_file() -> None:
    at = _page()
    assert at.button(key="ajout_bouton").disabled
    _upload(at, ROUTE)
    assert not at.button(key="ajout_bouton").disabled


def test_a_first_route_added_is_listed_in_the_same_run() -> None:
    _with_curve()
    at = _page()
    _upload(at, ROUTE)
    at.button(key="ajout_bouton").click().run()
    assert not at.exception
    assert [str(info.value) for info in at.info] == []
    assert len(at.code) == 1


def test_an_already_present_file_is_said_so() -> None:
    _with_route()
    _with_curve()
    at = _page()
    _upload(at, ROUTE)
    at.button(key="ajout_bouton").click().run()
    assert [str(info.value) for info in at.info] == [
        "mini_11.gpx est déjà dans routes/."
    ]
    assert not at.success


def test_an_added_outing_names_its_folder() -> None:
    at = _page()
    at.radio(key="ajout_sorte").set_value(FileKind.OUTING).run()
    _upload(at, TRACE)
    at.button(key="ajout_bouton").click().run()
    assert [str(s.value) for s in at.success] == [
        "appariement_trace_x01.gpx ajouté à sorties/."
    ]


def test_the_kinds_name_their_folders() -> None:
    at = _page()
    assert at.radio(key="ajout_sorte").options == [
        "un préparé (routes/)",
        "une sortie (sorties/)",
    ]


# L'export : le CSV de la projection affichée ------------------------------------------


def test_the_export_is_the_csv_of_the_projection_shown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``AppTest`` ne relit pas le contenu d'un bouton de téléchargement : un espion
    vérifie que la page exporte, par ``write_passages_csv``, la projection qu'elle
    vient de calculer — l'effort changé compris."""
    exported: list[Projection] = []

    def spy(projection: Projection, stream: io.StringIO) -> None:
        exported.append(projection)
        write_passages_csv(projection, stream)

    monkeypatch.setattr("mountain_perf.ui.projection.write_passages_csv", spy)
    _with_route()
    _with_curve()
    at = _page()
    assert not at.exception
    at.slider(key="projection.effort").set_value(0.9).run()
    assert not at.exception
    assert len(exported) == 2
    assert [p.parameters["effort"] for p in exported] == [1.0, 0.9]
    shown = str(at.code[0].value).split("\n")
    assert "effort       0.90" in shown
    assert exported[-1].passages[-1].arrival_s == pytest.approx(
        exported[0].passages[-1].arrival_s / 0.9, rel=1e-12
    )
