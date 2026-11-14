"""Les composants communs aux pages : le dossier des données, l'ajout d'un fichier, les
contrôles des paramètres, l'abscisse des figures ; la source de la courbe et le corpus
gardé (OG-UI). Mise en forme seule : tout vient de la bibliothèque."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Final

import streamlit as st

from mountain_perf import runs
from mountain_perf.config import ConfigError, data_dir
from mountain_perf.controls import ParameterControl
from mountain_perf.data_files import (
    FOLDERS,
    AddFileError,
    AddOutcome,
    FileKind,
    add_file,
)
from mountain_perf.estimation.origin import (
    ALL_PAST,
    DEFAULT_WINDOW_DAYS,
    CurveCorpus,
    IntervalsOf,
    OriginWindow,
    intervals_cache,
)
from mountain_perf.runs import (
    OriginCurve,
    RangeCurve,
    course_origin,
    curve_selection,
    index_digest,
    load_athlete_corpus,
    origin_curve,
    range_curve,
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


ORIGIN_SOURCE: Final = "à l'origine"
RANGE_SOURCE: Final = "sur une plage de dates"
FILE_SOURCE: Final = "un fichier de reference/"
SOURCES: tuple[str, ...] = (ORIGIN_SOURCE, RANGE_SOURCE, FILE_SOURCE)
"""Les trois sources de la courbe, dans l'ordre du choix ; la première par défaut
(OG-UI)."""

WINDOW_CHOICES: dict[str, OriginWindow | None] = {
    "28 jours": 28,
    "56 jours": DEFAULT_WINDOW_DAYS,
    "tout le passé": ALL_PAST,
    "autre": None,
}
"""Les fenêtres proposées ; « autre » demande un nombre de jours (OG-UI)."""

WINDOW_LINK: Final = (
    "Une activité qui finit tout près d'une borne de la fenêtre peut ne pas être "
    "comptée : [la fenêtre](fenetre)."
)
"""Le lien vers la page « La fenêtre », sous une courbe à l'origine (OG-UI)."""


@dataclass(frozen=True)
class OriginSource:
    """La courbe à l'origine (OG-UI) : le jour de la course (sur la page sortie,
    aujourd'hui, que la page ne lit pas : elle prend le jour de la trace) et la
    fenêtre."""

    day: date
    window: OriginWindow


@dataclass(frozen=True)
class RangeSource:
    """La courbe d'une plage de dates (OG-UI) : ses deux jours."""

    date_from: date
    date_to: date


@dataclass(frozen=True)
class FileSource:
    """Un fichier de ``reference/`` (OG-UI) : son chemin, ``None`` sans courbe dans le
    dossier."""

    path: Path | None


CurveSource = OriginSource | RangeSource | FileSource
"""La source de la courbe d'une page ; les pages aiguillent par ``isinstance``."""


def _name(path: Path) -> str:
    return path.name


def curve_source_inputs(
    prefix: str, curves: Sequence[Path], today: date, *, with_day: bool
) -> CurveSource:
    """Les contrôles de la source de la courbe, dans la barre latérale (l'appelant
    ouvre ``st.sidebar``) (OG-UI) : la source ; à l'origine, le jour de la course
    (``with_day``, sinon ``today``) et la fenêtre ; sur une plage, ses deux jours (par
    défaut, les 56 jours qui finissent la veille d'aujourd'hui) ; un fichier, la courbe
    de ``reference/`` s'il y en a. Les clés commencent par ``prefix``."""
    source = st.radio("Source de la courbe", SOURCES, key=f"{prefix}source")
    if source == ORIGIN_SOURCE:
        day = today
        if with_day:
            day = st.date_input("Jour de la course", value=today, key=f"{prefix}jour")
        choice = st.radio(
            "Fenêtre",
            tuple(WINDOW_CHOICES),
            index=1,
            key=f"{prefix}fenetre",
            horizontal=True,
        )
        window = WINDOW_CHOICES[choice]
        if window is None:
            window = int(
                st.number_input(
                    "Jours",
                    min_value=1,
                    value=DEFAULT_WINDOW_DAYS,
                    step=1,
                    key=f"{prefix}fenetre_jours",
                )
            )
        return OriginSource(day, window)
    if source == RANGE_SOURCE:
        date_from = st.date_input(
            "Du",
            value=today - timedelta(days=DEFAULT_WINDOW_DAYS),
            key=f"{prefix}plage_debut",
        )
        date_to = st.date_input(
            "Au", value=today - timedelta(days=1), key=f"{prefix}plage_fin"
        )
        return RangeSource(date_from, date_to)
    if not curves:
        return FileSource(None)
    path = st.selectbox("Courbe", curves, format_func=_name, key=f"{prefix}courbe")
    return FileSource(path)


def _load(folder: Path, digest: str) -> tuple[CurveCorpus, IntervalsOf]:
    """Le corpus complet du dossier et son cache des intervalles ; ``digest``,
    l'empreinte de l'index, ne sert qu'à la clé."""
    corpus = load_athlete_corpus(folder, curve_selection().source_activity_types)
    return corpus, intervals_cache(corpus)


_kept_corpus: Callable[[Path, str], tuple[CurveCorpus, IntervalsOf]] = (
    st.cache_resource(max_entries=1, show_spinner="Lecture des activités…")(_load)
)
"""Le corpus gardé par le processus de l'appli sous la clé ``(dossier, empreinte de
l'index)`` ; ``st.cache_resource`` appliqué par un appel, sans décorateur (``mypy`` sans
l'extra ``tableau``)."""


def athlete_corpus(folder: Path) -> tuple[CurveCorpus, IntervalsOf]:
    """Le corpus complet du dossier et son cache des intervalles, gardés par le
    processus sous la clé ``(folder, index_digest(folder))`` (OG-UI) : un nouvel
    ``interim/`` (une autre empreinte d'index) recharge le corpus."""
    return _kept_corpus(folder, index_digest(folder))


def _origin_curve(
    folder: Path, digest: str, day: date, today: date, window: OriginWindow
) -> OriginCurve:
    corpus, cache = athlete_corpus(folder)
    return origin_curve(
        corpus,
        course_origin(day, today),
        window,
        generated_at=runs.now(),
        intervals_of=cache,
    )


_kept_origin_curve: Callable[[Path, str, date, date, OriginWindow], OriginCurve] = (
    st.cache_resource(max_entries=16, show_spinner="Courbe à l'origine…")(_origin_curve)
)


def cached_origin_curve(
    folder: Path, day: date, today: date, window: OriginWindow
) -> OriginCurve:
    """La courbe à l'origine de la course du jour ``day``, gardée par le processus
    sous la clé ``(folder, index_digest(folder), day, today, window)`` (OG-UI), sur le
    corpus et le cache des intervalles de :func:`athlete_corpus` ; un nouvel
    ``interim/`` change la clé."""
    return _kept_origin_curve(folder, index_digest(folder), day, today, window)


def _range_curve(
    folder: Path, digest: str, date_from: date, date_to: date
) -> RangeCurve:
    corpus, cache = athlete_corpus(folder)
    return range_curve(
        corpus, date_from, date_to, generated_at=runs.now(), intervals_of=cache
    )


_kept_range_curve: Callable[[Path, str, date, date], RangeCurve] = st.cache_resource(
    max_entries=16, show_spinner="Courbe de la plage…"
)(_range_curve)


def cached_range_curve(folder: Path, date_from: date, date_to: date) -> RangeCurve:
    """La courbe de la plage ``[date_from ; date_to]``, gardée par le processus sous la
    clé ``(folder, index_digest(folder), date_from, date_to)`` (OG-UI), sur le corpus
    et le cache des intervalles de :func:`athlete_corpus` ; un nouvel ``interim/``
    change la clé."""
    return _kept_range_curve(folder, index_digest(folder), date_from, date_to)
