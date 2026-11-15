"""Les personnages des profils de démo (M5-3) : la courbe de base, la spécificité, la
vitesse vraie selon la pente, les temps vrais des courses.

La vitesse vraie est **horizontale**, connue du seul générateur ; elle s'écrit en km/h
dans les constantes et circule en m/s : :func:`true_speed_ms` est la seule conversion
du paquet (``0002``).
"""

from dataclasses import dataclass
from itertools import pairwise
from typing import Final

from mountain_perf.demo.constantes import (
    BASE_KNOTS,
    CHARACTER_NAMES,
    CHARACTER_TABLE,
    STEEP_FROM,
    STEEP_FULL,
)
from mountain_perf.demo.parcours import Route
from mountain_perf.validation import ContractError


@dataclass(frozen=True)
class Character:
    """Un personnage : son nom de dossier, son nom affiché, son rang, sa graine, ses
    deux facteurs (raide, roulant), son historique en jours, les restes (modulo le
    cycle) de ses jours de sortie, son cycle en jours, la suite des sorties d'un cycle
    (boucle, tours) et la boucle de sa sortie exportée en GPX."""

    name: str
    label: str
    rank: int
    seed: int
    steep_factor: float
    rolling_factor: float
    history_days: int
    outing_days: tuple[int, ...]
    cycle_days: int
    week: tuple[tuple[str, int], ...]
    witness_loop: str


CHARACTERS: Final[tuple[Character, ...]] = tuple(
    Character(name, label, rank, seed, steep, rolling, history, days, cycle, week, loop)
    for rank, (
        name,
        label,
        seed,
        steep,
        rolling,
        history,
        days,
        cycle,
        week,
        loop,
    ) in enumerate(CHARACTER_TABLE)
)
"""Les cinq personnages, dans l'ordre de leurs rangs (``CHARACTER_NAMES``)."""


def character(name: str) -> Character:
    """Le personnage nommé ``name`` ; ``ContractError`` pour un autre nom."""
    for found in CHARACTERS:
        if found.name == name:
            return found
    raise ContractError(
        f"personnage inconnu : {name} ; les personnages : {', '.join(CHARACTER_NAMES)}"
    )


def base_speed_kmh(grade: float) -> float:
    """La vitesse horizontale de base, en km/h, à la pente ``grade`` : l'interpolation
    linéaire entre les deux nœuds qui l'encadrent ; ``ContractError`` hors de
    ``[−0,40 ; 0,40]``."""
    for (g0, v0), (g1, v1) in pairwise(BASE_KNOTS):
        if g0 <= grade <= g1:
            if grade == g0:
                return v0
            if grade == g1:
                return v1
            return v0 + (v1 - v0) * (grade - g0) / (g1 - g0)
    raise ContractError(f"pente hors de la courbe de base : {grade}")


def steep_weight(grade: float) -> float:
    """Le poids du facteur du raide : 0 jusqu'à ``STEEP_FROM`` de pente (en montée comme
    en descente), 1 dès ``STEEP_FULL``, linéaire entre les deux."""
    magnitude = grade if grade >= 0 else -grade
    return min(1.0, max(0.0, (magnitude - STEEP_FROM) / (STEEP_FULL - STEEP_FROM)))


def true_speed_kmh(person: Character, grade: float) -> float:
    """La vitesse vraie du personnage, en km/h : la base, multipliée par le mélange de
    ses deux facteurs."""
    factor = person.rolling_factor + (
        person.steep_factor - person.rolling_factor
    ) * steep_weight(grade)
    return base_speed_kmh(grade) * factor


def true_speed_ms(person: Character, grade: float) -> float:
    """La vitesse vraie du personnage, en m/s : la seule conversion du paquet."""
    return true_speed_kmh(person, grade) / 3.6


PARTS: Final = (
    ("partie raide", 0.0, 10_000.0),
    ("partie roulante", 10_000.0, 30_000.0),
)
"""Les deux parties de ``deux_parties`` : nom, début, fin (mètres)."""


def true_time_s(person: Character, route: Route, start_m: float, end_m: float) -> float:
    """Le temps, à vitesse vraie sans bruit, de ``start_m`` à ``end_m`` : la somme, sur
    chaque tronçon de pente constante, de la longueur parcourue divisée par la vitesse
    vraie ; un tronçon à pente variable dans l'intervalle lève ``ContractError``."""
    total = 0.0
    start = 0.0
    for segment in route.segments:
        end = start + segment.length_m
        low = max(start, start_m)
        high = min(end, end_m)
        if high > low:
            if segment.grade_start != segment.grade_end:
                raise ContractError(
                    f"tronçon à pente variable dans {route.name} : true_time_s ne "
                    "somme que des tronçons de pente constante"
                )
            total += (high - low) / true_speed_ms(person, segment.grade_start)
        start = end
    return total
