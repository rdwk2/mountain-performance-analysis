"""La page « Q2 » (AN3-5, ``docs/decisions/0023``) : le dernier résultat écrit par
``just q2``, sans rien recalculer : la lecture principale et ses intervalles, les
mises en garde (lues dans la puissance que le résultat nomme, sauf la dépendance à la
covariance estimée, lue dans l'essai principal), la figure telle qu'écrite, le tableau
des autres essais, et, repliés, le flux et l'autocorrélation ;
elle dit si le résultat ne vient pas des tables actuelles. Exploratoire, sans verdict
(charte § 8) : les nombres sont mis en forme seulement.

``mountain_perf.analyse`` ne s'importe que dans la fonction
(``tests/test_ui_imports.py``, ``PISTE_PAGES``) ; ni plotly ni pyarrow : la figure est
le HTML écrit par ``just q2``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from mountain_perf.ui.components import data_folder
from mountain_perf.ui.piste import cached_tables

FIGURE_HEIGHT = 1100
"""La hauteur du cadre de la figure, en pixels."""

NO_RESULT = (
    "Aucun résultat de Q2 dans resultats/Q2/ : lancer just q2 puissance, puis just q2."
)
EXPLORATORY = (
    "Exploratoire : tout résultat de Q2 l'est (docs/decisions/0023) ; les estimations "
    "se lisent avec leurs intervalles, sans verdict."
)
MATCH_TEXTS: dict[str, str] = {
    "different": (
        "Ce résultat ne vient pas des tables actuelles : just process a été relancé "
        "depuis (autre commit, autres paramètres, journal.csv retouché…). Relancer "
        "just q2 puissance, puis just q2, pour le refaire."
    ),
    "unknown": (
        "Comparaison impossible : les tables actuelles ne se relisent pas. Le "
        "résultat est celui du dernier just q2."
    ),
}
"""L'avertissement de chaque comparaison qui n'est pas ``same``."""
NO_PRINCIPAL = "essais.csv n'a pas d'essai principal (P)."
NO_POWER_NAMED = (
    "Ce résultat ne nomme aucune puissance : ses mises en garde ne s'affichent pas."
)
FIGURE_CAPTION = (
    "Descriptive, sans verdict : les résidus partiels de la date et une courbe "
    "lissée ; le dernier tronçon, en pointillé, est provisoire."
)
TRIALS_CAPTION = (
    "Les secondaires se lisent sur leurs intervalles à 99 % (Holm), ou au niveau "
    "calibré que donne la colonne Niveau ; les sensibilités sont rapportées, jamais "
    "promues."
)
FLUX_TITLE = "Le flux (journées et montées écartées, par étape)"
AUTOCORRELATION_TITLE = "L'autocorrélation des résidus, par écart en jours"
LABEL: dict[str, str] = {
    "long_climb": "Montées longues",
    "short_climb": "Côtes",
    "ski_touring": "Ski de randonnée",
}
"""Le nom affiché de chaque régime."""
FAMILY_LABELS: dict[str, str] = {
    "secondaire": "secondaire",
    "sensibilite": "sensibilité",
}
STATUS_LABELS: dict[str, str] = {
    "estime": "estimé",
    "non_estimable": "non estimable",
    "non_faite": "non faite",
}
_PRINCIPAL = "P"
_LONG = "long_climb"
_ABSENT = "—"


# --- la mise en forme (§ 6.1 du brief) ----------------------------------------------


def _decimal(x: float) -> str:
    """``x`` à une décimale, virgule décimale."""
    return f"{x:.1f}".replace(".", ",")


def fraction_text(f: float | None) -> str:
    """Une fraction par an en %, une décimale, signe explicite (``−``, U+2212),
    virgule décimale ; ``0,0 %`` sans signe ; ``±∞ %`` ; ``—`` sans valeur."""
    if f is None:
        return _ABSENT
    if f == math.inf:
        return "+∞ %"
    if f == -math.inf:
        return "−∞ %"
    x = round(100 * f, 1)
    if x == 0:
        return "0,0 %"
    return f"{'+' if x > 0 else '−'}{_decimal(abs(x))} %"


def share_text(p: float | None) -> str:
    """Une part en %, sans signe, une décimale, virgule décimale ; ``—`` sans
    valeur."""
    if p is None:
        return _ABSENT
    return f"{_decimal(round(100 * p, 1))} %"


def level_text(level: float | None) -> str:
    """Un niveau en % : sans décimale s'il est entier, sinon une ; ``—`` sans
    valeur."""
    if level is None:
        return _ABSENT
    x = round(100 * level, 1)
    if x == int(x):
        return f"{int(x)} %"
    return f"{_decimal(x)} %"


def interval_text(low: float | None, high: float | None) -> str:
    """Un intervalle de fractions par an, « de … à … » ; ``—`` sans borne."""
    if low is None and high is None:
        return _ABSENT
    return f"de {fraction_text(low)} à {fraction_text(high)}"


def sentence(text: str) -> str:
    """La première lettre en capitale, un point final s'il n'y en a pas."""
    if not text:
        return text
    capital = text[0].upper() + text[1:]
    return capital if capital.endswith(".") else f"{capital}."


def _date(text: str) -> str:
    return f"{date.fromisoformat(text):%d/%m/%Y}"


def _float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


# --- les blocs ------------------------------------------------------------------------


def _unreadable(count: int) -> None:
    if count:
        st.caption(f"Dossiers de résultats illisibles, ignorés : {count}.")


def _long_warning(power: Sequence[Any] | None) -> Any:
    return next((w for w in power or () if w.regime == _LONG), None)


def _bounds(bounds: Mapping[str, object]) -> None:
    entry = bounds.get(_LONG)
    if not isinstance(entry, Mapping):
        return
    status = entry.get("statut")
    if status == "declenchees":
        count = entry.get("journees_imputees")
        days = "1 journée imputée" if count == 1 else f"{count} journées imputées"
        low = fraction_text(_float(entry.get("b_basse_fraction")))
        high = fraction_text(_float(entry.get("b_haute_fraction")))
        st.caption(
            f"Bornes d'exclusion déclenchées ({days}) : aux deux bornes, la "
            f"régression directe vaut {low} et {high} par an."
        )
    elif status == "non calculees":
        st.caption("Bornes d'exclusion déclenchées, mais non calculées.")


def _principal(principal: Mapping[str, object], reading: Any) -> None:
    if principal.get("statut") == "estime":
        phrase = _text(principal.get("phrase"))
        if phrase is not None:
            st.markdown(f"**{sentence(phrase)}**")
        warning = _long_warning(reading.power)
        if warning is not None and warning.message:
            st.markdown(sentence(warning.message))
        level = level_text(_float(principal.get("niveau")))
        direct = fraction_text(_float(principal.get("estimation_fraction")))
        direct_interval = interval_text(
            _float(principal.get("intervalle_fraction_bas")),
            _float(principal.get("intervalle_fraction_haut")),
        )
        st.markdown(
            f"Régression directe : {direct} par an ({direct_interval}, à {level})."
        )
        inverse = _float(principal.get("inverse_fraction"))
        if inverse is not None:
            inverse_interval = interval_text(
                _float(principal.get("intervalle_inverse_fraction_bas")),
                _float(principal.get("intervalle_inverse_fraction_haut")),
            )
            st.markdown(
                f"Régression inverse : {fraction_text(inverse)} par an "
                f"({inverse_interval}, à {level})."
            )
        mention = _text(principal.get("mention"))
        if mention is not None:
            st.caption(f"Mention : {mention}.")
    else:
        motif = _text(principal.get("motif"))
        st.markdown("Non estimé." if motif is None else f"Non estimé : {motif}.")
    _bounds(reading.bounds)


def _warnings(reading: Any, principal: Mapping[str, object] | None) -> None:
    if reading.power is None:
        if reading.power_folder is None:
            st.warning(NO_POWER_NAMED)
        else:
            st.warning(
                "La puissance que nomme ce résultat (resultats/Q2/puissance/"
                f"{reading.power_folder}/) manque ou a changé : ses mises en garde ne "
                "s'affichent pas."
            )
    bullets: list[str] = []
    for warning in reading.power or ():
        bullets.append(
            f"- {LABEL[warning.regime]} : à effet nul simulé, la lecture dit "
            f"« établi » dans {share_text(warning.established_at_zero)} des tirages, "
            f"pour un seuil nominal de {share_text(warning.nominal_level)}."
        )
    long_warning = _long_warning(reading.power)
    if long_warning is not None and long_warning.bias_at_delta is not None:
        bullets.append(
            "- Montées longues : sous l'erreur de mesure simulée de la FC de la montée "
            "(scénario 4), la régression directe s'écarte en moyenne de "
            f"{fraction_text(long_warning.bias_at_delta)} par an, à un effet simulé de "
            f"{fraction_text(reading.delta)} par an."
        )
    phi = None if principal is None else _float(principal.get("phi"))
    if principal is not None and phi is not None:
        edge = (
            ", à une borne de sa plage"
            if principal.get("phi_a_la_borne_basse") is True
            or principal.get("phi_a_la_borne_haute") is True
            else ""
        )
        bullets.append(
            "- Les intervalles dépendent de la covariance estimée entre journées "
            "(portée φ̂ = " + _decimal(phi) + " jours aux montées longues" + edge + ")."
        )
    if bullets:
        st.markdown("\n".join(bullets))


def _status(trial: Mapping[str, object]) -> str:
    status = str(trial.get("statut"))
    label = STATUS_LABELS.get(status, status)
    if status == "estime":
        return label
    motif = _text(trial.get("motif"))
    return label if motif is None else f"{label} : {motif}"


def _index(trial: Mapping[str, object]) -> int:
    index = trial.get("indice")
    return index if isinstance(index, int) else 0


def _trial_rows(trials: Sequence[Mapping[str, object]]) -> list[dict[str, str]]:
    """Le tableau des essais : une ligne par essai sauf ``P``, dans l'ordre
    d'``indice``, des chaînes mises en forme."""
    rows: list[dict[str, str]] = []
    others = [t for t in trials if t.get("essai") != _PRINCIPAL]
    for trial in sorted(others, key=_index):
        family = str(trial.get("famille"))
        regime = str(trial.get("regime"))
        rows.append(
            {
                "Essai": str(trial.get("essai")),
                "Famille": FAMILY_LABELS.get(family, family),
                "Régime": LABEL.get(regime, regime),
                "Mesure": str(trial.get("mesure")),
                "Estimation": fraction_text(_float(trial.get("estimation_fraction"))),
                "Intervalle": interval_text(
                    _float(trial.get("intervalle_fraction_bas")),
                    _float(trial.get("intervalle_fraction_haut")),
                ),
                "Inverse": fraction_text(_float(trial.get("inverse_fraction"))),
                "Intervalle inverse": interval_text(
                    _float(trial.get("intervalle_inverse_fraction_bas")),
                    _float(trial.get("intervalle_inverse_fraction_haut")),
                ),
                "Niveau": level_text(_float(trial.get("niveau"))),
                "Lecture": _text(trial.get("lecture")) or _ABSENT,
                "Statut": _status(trial),
                "Mention": _text(trial.get("mention")) or "",
            }
        )
    return rows


def q2_page() -> None:
    """La page « Q2 » (§ 6 du brief AN3-5)."""
    from mountain_perf.analyse.parquet import ProcessedError
    from mountain_perf.analyse.q2.results import (
        RESULTS_DIR,
        EstimationReading,
        Q2ResultsError,
        latest_estimation,
        read_estimation,
        stored_estimations,
    )
    from mountain_perf.analyse.results import TablesMatch

    st.title("Q2")
    data = data_folder()
    if data is None:
        return
    try:
        current = cached_tables(data).provenance
    except (ProcessedError, FileNotFoundError):
        current = None
    latest = latest_estimation(data, current)
    if latest is None:
        st.info(NO_RESULT)
        _unreadable(stored_estimations(data)[1])
        return
    estimation = latest.estimation
    folder = f"{RESULTS_DIR.as_posix()}/{estimation.folder.name}/"
    reading: EstimationReading | None = None
    error: Q2ResultsError | None = None
    try:
        reading = read_estimation(data, estimation)
    except Q2ResultsError as raised:
        error = raised
    period = ""
    if reading is not None and reading.period is not None:
        period = (
            f" ; montées du {_date(reading.period['debut'])} au "
            f"{_date(reading.period['fin'])}"
        )
    st.caption(
        f"Résultat du {estimation.generated_on:%d/%m/%Y} ({folder}), tel que just q2 "
        f"l'a écrit{period}."
    )
    st.caption(EXPLORATORY)
    if latest.match is not TablesMatch.SAME:
        st.warning(MATCH_TEXTS[latest.match.value])
    _unreadable(latest.unreadable)
    if reading is None:
        st.error(str(error))
        return
    principal = next((t for t in reading.trials if t.get("essai") == _PRINCIPAL), None)
    st.subheader("La lecture principale")
    if principal is None:
        st.error(NO_PRINCIPAL)
    else:
        _principal(principal, reading)
    st.subheader("Les mises en garde")
    _warnings(reading, principal)
    st.subheader("La figure")
    if reading.figure_html is None:
        st.error(f"figure.html manque dans {folder}.")
    else:
        components.html(reading.figure_html, height=FIGURE_HEIGHT, scrolling=True)
        st.caption(FIGURE_CAPTION)
    st.subheader("Les essais")
    st.caption(TRIALS_CAPTION)
    st.dataframe(_trial_rows(reading.trials), hide_index=True)
    with st.expander(FLUX_TITLE):
        st.dataframe([dict(line) for line in reading.flux], hide_index=True)
    with st.expander(AUTOCORRELATION_TITLE):
        st.dataframe([dict(line) for line in reading.autocorrelation], hide_index=True)
