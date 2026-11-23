"""Les états du modèle de la montée (AN4-2a, ``docs/decisions/0024``) : leurs valeurs
sont les textes des pages (charte, § 8) ; une estimation impossible rend
:class:`Unavailable`, une entrée fautive lève :class:`AscentError`."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AscentState(StrEnum):
    """Les états d'une estimation ; la valeur est le texte affiché."""

    INSUFFICIENT = "données insuffisantes"
    NOT_APPLICABLE = "sans objet"
    NOT_SEPARABLE = "non séparable"
    DEVICE_RUPTURE = "à cheval sur une rupture d'appareil"
    BORROWED = "emprunté à l'histoire"
    DEFAULT = "par défaut"
    ESTIMATED = "estimé"


@dataclass(frozen=True)
class Unavailable:
    """Une estimation que les données ne permettent pas : son état, et une phrase en
    français qui nomme le compte manquant et le minimum."""

    state: AscentState
    reason: str


class AscentError(ValueError):
    """Une entrée fautive (une montée sans activité, un argument hors domaine)."""
