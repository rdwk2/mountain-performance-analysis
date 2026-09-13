"""Paramètres déclaratifs : une spécification par paramètre, un jeu de valeurs validé.

Dans l'ancien projet, les constantes du modèle vivaient en dur dans le code, et on
ne savait plus laquelle servait à quelque chose. Ici, un paramètre est déclaré une
fois, avec ses bornes et sa description ; l'interface (M5) génère ses contrôles en
parcourant les specs, le backtest (M4) les énumère et les balaie, et une projection
enregistre exactement le jeu qui l'a produite.

Ce n'est pas un système de plugins : pas d'enregistrement dynamique, pas de points
d'entrée. Le « registre » du moteur (M3) sera un tuple au niveau du module.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from mountain_perf.validation import (
    ContractError,
    require_finite,
    require_immutable_sequence,
    require_in_range,
    require_non_empty,
)


@dataclass(frozen=True)
class ParameterSpec:
    """Déclaration d'un paramètre réel du modèle.

    Champs
    ------
    - ``name`` — sans unité — identifiant du paramètre, unique dans un jeu.
    - ``unit`` — sans unité — unité de la valeur (``"m"``, ``"s"``…) ; ``None``
      pour une grandeur sans dimension (coefficient, fraction).
    - ``default`` — en ``unit`` — valeur prise quand le jeu n'en fournit pas.
    - ``minimum`` — en ``unit`` — borne basse incluse.
    - ``maximum`` — en ``unit`` — borne haute incluse.
    - ``description`` — sans unité — texte destiné à l'infobulle de l'interface.

    Invariants
    ----------
    - ``name`` et ``description`` non vides ; ``unit`` non vide s'il est présent ;
    - ``default``, ``minimum``, ``maximum`` finis ;
    - ``minimum <= default <= maximum``.

    Producteur
    ----------
    Déclaration statique dans le code des briques qui ont des paramètres : le
    moteur (M3, M6a), la construction du profil (M2).

    Consommateurs
    -------------
    ``ParameterSet`` (validation), l'interface (M5, contrôles et bornes), le
    backtest (M4, balayage).

    Non promis
    ----------
    - aucun type autre que flottant : pas de booléen (le modèle est multiplicatif,
      désactiver un effet c'est mettre son coefficient à zéro), pas de choix
      d'objet (une courbe est une référence qui vit à côté du jeu) ;
    - aucun pas, aucune échelle (linéaire, logarithmique) pour l'interface ;
    - aucune spec réelle n'est déclarée en M1.
    """

    name: str
    unit: str | None
    default: float
    minimum: float
    maximum: float
    description: str

    def __post_init__(self) -> None:
        require_non_empty(self.name, "name")
        if self.unit is not None:
            require_non_empty(self.unit, f"{self.name}.unit")
        require_non_empty(self.description, f"{self.name}.description")
        require_finite(self.minimum, f"{self.name}.minimum")
        require_finite(self.maximum, f"{self.name}.maximum")
        require_finite(self.default, f"{self.name}.default")
        require_in_range(
            self.default, self.minimum, self.maximum, f"{self.name}.default"
        )


@dataclass(frozen=True)
class ParameterSet:
    """Jeu de valeurs validé contre ses spécifications.

    Champs
    ------
    - ``specs`` — sans unité — tuple des ``ParameterSpec`` du jeu, dans l'ordre de
      déclaration.
    - ``values`` — en unité de chaque spec — table ``nom → valeur``. À la
      construction on peut n'en fournir qu'une partie ; **après construction, la
      table est complétée par les défauts** et contient exactement une entrée par
      spec, dans l'ordre des specs. Elle est en lecture seule.

    Invariants
    ----------
    - ``specs`` est un tuple, sans doublon de nom ;
    - toute clé de ``values`` correspond à une spec connue ;
    - toute valeur est finie et dans ``[minimum, maximum]`` de sa spec.

    Producteur
    ----------
    L'appelant d'une brique paramétrée : l'interface (M5), le backtest (M4), la
    construction du profil (M2), qui l'enregistre dans ``RouteProfile``.

    Consommateurs
    -------------
    Le moteur (M3), la construction du profil (M2), et tout objet qui doit dire ce
    qui l'a produit (``RouteProfile.build_parameters``, ``Projection`` en M1b).

    Non promis
    ----------
    - la table fournie n'est pas conservée : elle est copiée, la modifier après
      construction n'a pas d'effet ;
    - l'objet n'est pas hachable (la table est un ``Mapping``) ;
    - aucune validation croisée entre paramètres.
    """

    specs: tuple[ParameterSpec, ...]
    values: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_immutable_sequence(self.specs, "specs")
        names = [spec.name for spec in self.specs]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ContractError(f"Specs en double : {', '.join(duplicates)}.")
        unknown = sorted(set(self.values) - set(names))
        if unknown:
            raise ContractError(f"Paramètres inconnus : {', '.join(unknown)}.")
        completed: dict[str, float] = {}
        for spec in self.specs:
            value = self.values.get(spec.name, spec.default)
            require_finite(value, spec.name)
            require_in_range(value, spec.minimum, spec.maximum, spec.name)
            completed[spec.name] = value
        object.__setattr__(self, "values", MappingProxyType(completed))

    def __getitem__(self, name: str) -> float:
        """Valeur du paramètre ``name`` ; ``KeyError`` s'il n'est pas déclaré."""
        return self.values[name]
