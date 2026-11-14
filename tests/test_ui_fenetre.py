"""La page « La fenêtre » (OG-UI, § 6.6 (a) du brief), par ``AppTest.from_function``.
Sautée sans l'extra ``tableau``."""

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest

from mountain_perf.ui.fenetre import WINDOW_TEXT

TIMEOUT_S = 30


def _page() -> None:
    from mountain_perf.ui.fenetre import window_page

    window_page()


def test_the_window_page_shows_its_title_and_its_text() -> None:
    at = AppTest.from_function(_page, default_timeout=TIMEOUT_S).run()
    assert not at.exception
    assert [str(title.value) for title in at.title] == [
        "La fenêtre de la courbe à l'origine"
    ]
    assert [str(text.value) for text in at.markdown] == [WINDOW_TEXT]


def test_the_window_text_names_the_bounded_origin_and_the_remedy() -> None:
    bounded = "(aujourd'hui, pour une course au-delà d'aujourd'hui + 7 jours)"
    assert bounded in WINDOW_TEXT
    assert "élargir la fenêtre d'un jour (57 jours au lieu de 56)" in WINDOW_TEXT
    assert WINDOW_TEXT.endswith("sur la page sortie, une plage de dates.")
