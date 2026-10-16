"""Effets candidats synthétiques de l'expérience (M4c-3) : des ``CandidateEffect``
minuscules, sans estimation, pour le monde de ``fixtures.backtest_world``.

- :class:`Identity` : reproduit v0 — gain nul attendu (D10.5) ;
- :class:`Scale` : l'allure multipliée partout — un effet de niveau, que le recalage de
  l'effort absorbe ;
- :class:`Descent` : l'allure multipliée sur les intervalles de pente sous un seuil ;
- :class:`Broken` : aucune chronologie — une erreur du modèle sur chaque sortie ;
- :class:`Raising` : la transformation lève l'exception reçue — ``ValueError`` ou
  ``ArithmeticError``, une erreur du modèle ; toute autre, une erreur de l'expérience.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mountain_perf.model import ProjectedTimeline
from mountain_perf.schemas import ParameterSet, RouteProfile

EMPTY = ParameterSet(())
"""Des paramètres vides : aucun effet synthétique n'en estime."""


@dataclass(frozen=True)
class Identity:
    """La chronologie de v0, inchangée."""

    name: str = "identite"
    description: str = "reproduit v0 (gain nul attendu, D10.5)"
    parameters: ParameterSet = EMPTY

    def timeline(
        self, profile: RouteProfile, base: ProjectedTimeline
    ) -> ProjectedTimeline | None:
        return base


@dataclass(frozen=True)
class Scale:
    """L'allure de v0 multipliée par ``factor`` partout."""

    factor: float = 0.95
    name: str = "niveau"
    description: str = "allure multipliée partout (effet de niveau)"
    parameters: ParameterSet = EMPTY

    def timeline(
        self, profile: RouteProfile, base: ProjectedTimeline
    ) -> ProjectedTimeline | None:
        return ProjectedTimeline(
            base.grid_m, tuple(pace * self.factor for pace in base.pace_s_per_m)
        )


@dataclass(frozen=True)
class Descent:
    """L'allure de v0 multipliée par ``factor`` sur les intervalles de pente sous
    ``threshold``."""

    factor: float = 0.9
    threshold: float = -0.05
    name: str = "descente"
    description: str = "allure multipliée sur les intervalles de pente < -5 %"
    parameters: ParameterSet = EMPTY

    def timeline(
        self, profile: RouteProfile, base: ProjectedTimeline
    ) -> ProjectedTimeline | None:
        return ProjectedTimeline(
            base.grid_m,
            tuple(
                pace * self.factor if grade < self.threshold else pace
                for pace, grade in zip(base.pace_s_per_m, profile.grade, strict=True)
            ),
        )


@dataclass(frozen=True)
class Broken:
    """Aucune chronologie."""

    name: str = "casse"
    description: str = "aucune chronologie (erreur du modèle)"
    parameters: ParameterSet = EMPTY

    def timeline(
        self, profile: RouteProfile, base: ProjectedTimeline
    ) -> ProjectedTimeline | None:
        return None


@dataclass(frozen=True)
class Raising:
    """La transformation lève ``error``."""

    error: BaseException = field(default_factory=lambda: ValueError("synthétique"))
    name: str = "leve"
    description: str = "la transformation lève une exception"
    parameters: ParameterSet = EMPTY

    def timeline(
        self, profile: RouteProfile, base: ProjectedTimeline
    ) -> ProjectedTimeline | None:
        raise self.error
