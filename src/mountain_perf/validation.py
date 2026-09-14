"""Vérifications partagées par tous les contrats de données.

Chaque ``__post_init__`` des schémas passe par ces fonctions, et par elles seules :
une vérification réécrite quinze fois est un bug en attente.

Politique (``docs/decisions/0007-forme-des-donnees.md``) : **le contrat est strict,
l'ingestion est tolérante et tracée.** Une violation d'invariant dur lève
:class:`ContractError` et l'objet n'existe pas ; une simple suspicion ne passe pas
par ici, elle devient un drapeau de qualité.

Ce module est **générique** : il ne connaît aucune plage de domaine (latitude,
altitude…). Celles-ci vivent dans ``mountain_perf.schemas.common``.
"""

import math
from collections.abc import Sequence
from datetime import datetime, timedelta


class ContractError(ValueError):
    """Violation d'un invariant dur d'un contrat de données.

    Sous-classe de ``ValueError`` : un appelant peut distinguer une violation de
    contrat d'une autre ``ValueError`` sans perdre la compatibilité.
    """


def require_aware(dt: datetime, name: str) -> timedelta:
    """Refuse un ``datetime`` naïf (sans fuseau, ou fuseau sans décalage défini).

    Renvoie le décalage à UTC, désormais garanti défini.
    """
    offset = dt.utcoffset() if dt.tzinfo is not None else None
    if offset is None:
        raise ContractError(f"{name} doit porter un fuseau horaire, reçu {dt!r}.")
    return offset


def require_same_length(**arrays: Sequence[object]) -> None:
    """Refuse des tableaux parallèles de longueurs différentes."""
    lengths = {name: len(array) for name, array in arrays.items()}
    if len(set(lengths.values())) > 1:
        detail = ", ".join(f"{name}={length}" for name, length in lengths.items())
        raise ContractError(f"Tableaux parallèles de longueurs différentes : {detail}.")


def require_min_length(seq: Sequence[object], n: int, name: str) -> None:
    """Refuse une séquence de moins de ``n`` éléments."""
    if len(seq) < n:
        raise ContractError(
            f"{name} doit contenir au moins {n} éléments, reçu {len(seq)}."
        )


def require_increasing(seq: Sequence[float], name: str, *, strict: bool) -> None:
    """Refuse une séquence non croissante (strictement si ``strict``)."""
    for i in range(1, len(seq)):
        previous, current = seq[i - 1], seq[i]
        ok = current > previous if strict else current >= previous
        if not ok:
            sense = "strictement croissante" if strict else "croissante"
            raise ContractError(
                f"{name} doit être {sense} : {name}[{i - 1}]={previous}, "
                f"{name}[{i}]={current}."
            )


def require_finite(value: float, name: str) -> None:
    """Refuse NaN et ±inf."""
    if not math.isfinite(value):
        raise ContractError(f"{name} doit être fini, reçu {value}.")


def require_all_finite(seq: Sequence[float], name: str) -> None:
    """Refuse un tableau contenant NaN ou ±inf."""
    for i, value in enumerate(seq):
        require_finite(value, f"{name}[{i}]")


def require_in_range(value: float, low: float, high: float, name: str) -> None:
    """Refuse une valeur hors de ``[low, high]`` (bornes incluses). NaN est refusé."""
    if not low <= value <= high:
        raise ContractError(f"{name} doit être dans [{low}, {high}], reçu {value}.")


def require_all_in_range(
    seq: Sequence[float], low: float, high: float, name: str
) -> None:
    """Refuse un tableau dont un élément est hors de ``[low, high]``."""
    for i, value in enumerate(seq):
        require_in_range(value, low, high, f"{name}[{i}]")


def require_non_empty(text: str, name: str) -> None:
    """Refuse une chaîne vide ou faite seulement d'espaces."""
    if not text.strip():
        raise ContractError(f"{name} ne doit pas être vide.")


def require_immutable_sequence(seq: Sequence[object], name: str) -> None:
    """Refuse une séquence mutable : aujourd'hui, seul ``tuple`` est accepté.

    Un objet gelé qui porte une ``list`` reste modifiable au travers de cette liste.
    Plutôt que de copier (coûteux sur 150 000 points) ou de s'en remettre à la
    discipline, on refuse. Point unique à élargir le jour où numpy arrivera
    (``ndarray`` non inscriptible).
    """
    if not isinstance(seq, tuple):
        raise ContractError(
            f"{name} doit être une séquence immuable : passer un tuple, "
            f"reçu {type(seq).__name__}."
        )
