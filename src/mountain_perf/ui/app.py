"""Le point d'entrée de l'interface (M5, ``docs/decisions/0016``), lancé par
``just ui``.

Une page par usage : un module de ``ui/`` (jamais dans un dossier ``ui/pages/``, que
Streamlit prendrait pour ses pages), qui expose une fonction ``<nom>_page() -> None``,
déclarée par une ligne de ``PAGES``.
"""

import streamlit as st

from mountain_perf.ui.projection import projection_page

PAGES = [
    st.Page(projection_page, title="Projection", url_path="projection"),
]

st.set_page_config(page_title="mountain-performance-analysis", layout="wide")
st.navigation(PAGES).run()
