"""Fixtures communes à toute la suite : ``MPA_DATA_DIR`` sur un dossier temporaire
(§ 6.6 du brief M4c-1, décisions 3 et 16).

``just check`` charge ``.env``, où ``MPA_DATA_DIR`` désigne le vrai dossier de données :
un test qui oublierait de la fixer écrirait au registre réel avant d'échouer. Les deux
fixtures ``autouse`` ci-dessous l'empêchent :

- pour la session, la variable désigne un dossier de la base temporaire de pytest,
  posé avant toute fixture de module ou de session (pytest met en place les fixtures
  de plus grande portée d'abord) : les fixtures de module qui exécutent la commande
  (``world``, ``synthesis``) voient ce dossier de la session, jamais celui de ``.env`` ;
- pour chaque test, un dossier neuf, distinct de ``tmp_path`` (des tests vérifient que
  rien ne s'écrit dans leur ``tmp_path``).

Un test peut poser (``setenv``) ou retirer (``delenv``) la variable par-dessus, par
``monkeypatch`` : il le fait après ces fixtures.
"""

import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from mountain_perf.config import DATA_DIR_ENV_VAR


@pytest.fixture(autouse=True, scope="session")
def _session_data_dir(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """``MPA_DATA_DIR`` sur un dossier de la base temporaire de pytest pour toute la
    session, avant toute fixture de module ; rend le dossier qui reçoit ceux des
    tests."""
    root = tmp_path_factory.mktemp("mpa_data_dir", numbered=False)
    session = root / "session"
    session.mkdir()
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(DATA_DIR_ENV_VAR, str(session))
        yield root


@pytest.fixture(autouse=True)
def _isolated_data_dir(
    _session_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``MPA_DATA_DIR`` sur un dossier neuf pour chaque test, distinct de
    ``tmp_path``."""
    monkeypatch.setenv(
        DATA_DIR_ENV_VAR, tempfile.mkdtemp(prefix="test-", dir=_session_data_dir)
    )
