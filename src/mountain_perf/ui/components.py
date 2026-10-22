"""Les composants communs aux pages : le dossier des données, l'ajout d'un fichier, les
contrôles des paramètres, l'abscisse des figures. Mise en forme seule : tout vient de la
bibliothèque."""

from collections.abc import Sequence
from pathlib import Path

import streamlit as st

from mountain_perf.config import ConfigError, data_dir
from mountain_perf.controls import ParameterControl
from mountain_perf.data_files import (
    FOLDERS,
    AddFileError,
    AddOutcome,
    FileKind,
    add_file,
)

KINDS: tuple[FileKind, ...] = (FileKind.ROUTE, FileKind.OUTING)
"""Les sortes proposées à l'ajout, dans l'ordre du choix. Un tuple typé : avec
``tuple(FileKind)``, ``mypy`` choisit une surcharge de ``st.radio`` qui rend
``None``."""

KIND_LABELS: dict[FileKind, str] = {
    FileKind.ROUTE: f"un préparé ({FOLDERS[FileKind.ROUTE]}/)",
    FileKind.OUTING: f"une sortie ({FOLDERS[FileKind.OUTING]}/)",
}
"""Le libellé de chaque sorte, avec son dossier."""

DISTANCE_AXIS = {
    "field": "distance (m)",
    "type": "quantitative",
    "axis": {"format": "d"},
}
"""L'abscisse commune des deux figures : des mètres entiers, sans séparateur de milliers
à l'anglaise (``1,550`` se lirait 1,55)."""


def data_folder() -> Path | None:
    """Le dossier des données ; ``None``, l'erreur affichée, s'il n'est pas configuré
    (la page s'arrête alors d'elle-même)."""
    try:
        return data_dir()
    except ConfigError as error:
        st.error(str(error))
        return None


def file_adder(data: Path) -> None:
    """L'ajout d'un fichier GPX, dans la barre latérale : le fichier, sa sorte, et
    l'ajout au clic seulement (un fichier téléversé reste en mémoire d'une relance à
    l'autre)."""
    with st.sidebar.expander("Ajouter un fichier"):
        upload = st.file_uploader("Fichier GPX", type=["gpx"], key="ajout_fichier")
        kind = st.radio(
            "C'est",
            KINDS,
            format_func=lambda option: KIND_LABELS[option],
            key="ajout_sorte",
        )
        clicked = st.button("Ajouter", key="ajout_bouton", disabled=upload is None)
        if not clicked or upload is None:
            return
        folder = FOLDERS[kind]
        try:
            outcome = add_file(data, kind, upload.name, upload.getvalue())
        except AddFileError as error:
            st.error(str(error))
            return
        if outcome is AddOutcome.ADDED:
            st.success(f"{upload.name} ajouté à {folder}/.")
        else:
            st.info(f"{upload.name} est déjà dans {folder}/.")


def parameter_inputs(
    controls: Sequence[ParameterControl], key: str
) -> dict[str, float]:
    """Un contrôle par paramètre, dans l'ordre : un curseur quand une plage est
    déclarée, sinon un champ numérique borné aux garde-fous ; rend les valeurs
    réglées."""
    values: dict[str, float] = {}
    for control in controls:
        spec = control.spec
        widget_key = f"{key}.{spec.name}"
        if control.step is not None:
            value = st.slider(
                control.label,
                min_value=control.low,
                max_value=control.high,
                value=control.default,
                step=control.step,
                format="%.0f" if control.step >= 1 else "%.2f",
                help=spec.description,
                key=widget_key,
            )
        else:
            value = st.number_input(
                control.label,
                min_value=control.low,
                max_value=control.high,
                value=control.default,
                help=spec.description,
                key=widget_key,
            )
        values[spec.name] = float(value)
    return values
