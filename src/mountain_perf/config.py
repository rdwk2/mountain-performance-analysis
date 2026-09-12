"""Configuration : localisation du dossier de données, hors du dépôt.

Les données personnelles vivent dans le dossier pointé par la variable
d'environnement ``MPA_DATA_DIR`` (voir ``docs/decisions/0001-separation-data-code.md``).
Ce module ne lit que l'environnement : il ne parse aucun fichier ``.env``.
C'est ``just`` (``set dotenv-load``) ou ``uv run --env-file`` qui charge ``.env``.
"""

import os
from pathlib import Path

DATA_DIR_ENV_VAR = "MPA_DATA_DIR"

_HOW_TO_FIX = (
    "Copie `.env.example` en `.env` à la racine du dépôt et renseigne "
    f"{DATA_DIR_ENV_VAR} avec le chemin du dossier de données (hors du dépôt)."
)


class ConfigError(RuntimeError):
    """Configuration absente ou invalide. Le message dit quoi faire."""


def data_dir() -> Path:
    """Retourne le dossier racine des données, résolu en chemin absolu.

    Lève :class:`ConfigError` si ``MPA_DATA_DIR`` est absente ou vide, ou si le
    dossier qu'elle désigne n'existe pas.
    """
    raw = os.environ.get(DATA_DIR_ENV_VAR, "").strip()
    if not raw:
        raise ConfigError(
            f"La variable d'environnement {DATA_DIR_ENV_VAR} n'est pas définie. "
            + _HOW_TO_FIX
        )

    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        raise ConfigError(
            f"{DATA_DIR_ENV_VAR} pointe vers un dossier inexistant : {path}. "
            + _HOW_TO_FIX
        )
    return path
