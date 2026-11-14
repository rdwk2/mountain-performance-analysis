"""La page « La fenêtre » (OG-UI) : ce que la courbe à l'origine compte, et les
activités en bordure de fenêtre ; texte seul."""

from typing import Final

import streamlit as st

WINDOW_TEXT: Final = (
    "La courbe à l'origine ne lit que les activités **finies avant l'origine**, 00:00 "
    "à Paris, 7 jours avant la course (aujourd'hui, pour une course au-delà "
    "d'aujourd'hui + 7 jours), et **finies dans la fenêtre** : à sa borne basse ou "
    "après.\n\n"
    "La fin d'une activité est la plus tardive de deux fins : celle de l'index (son "
    "départ et sa durée écoulée, dans le résumé de l'activité) et celle de "
    "l'enregistrement de la montre (son dernier instant). Elles peuvent différer de "
    "quelques secondes, ou davantage.\n\n"
    "Une activité qui finit tout près d'une borne peut donc ne pas être comptée :\n\n"
    "- **à l'origine**, dès que l'une des deux fins l'atteint ;\n"
    "- **à la borne basse**, quand la fin de l'index la précède, même si la montre "
    "finit après : l'index décide seul, sans lire l'enregistrement.\n\n"
    "Le remède : à la borne basse, élargir la fenêtre d'un jour (57 jours au lieu de "
    "56) ; à l'origine, choisir la course un jour plus tard, si ce jour reste à 7 "
    "jours ou moins d'aujourd'hui (au-delà, l'origine ne bouge plus) ; sinon, et sur "
    "la page sortie, une plage de dates."
)
"""Le texte de la page (OG-UI)."""


def window_page() -> None:
    """La page « La fenêtre »."""
    st.title("La fenêtre de la courbe à l'origine")
    st.markdown(WINDOW_TEXT)
