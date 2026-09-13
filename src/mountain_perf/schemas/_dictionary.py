"""Rendu du dictionnaire de données depuis les docstrings des schémas.

Source unique : les docstrings et les annotations du paquet. Ce module ne lit ni
n'écrit aucun fichier — :func:`render` renvoie une chaîne ; c'est
``scripts/data_dictionary.py`` (``just dictionary``) qui l'écrit dans
``docs/DICTIONNAIRE_DONNEES.md``, et un test vérifie que le fichier commité est à jour.

Sortie déterministe : ordre des types fixé ici, fins de ligne ``\\n``, aucun
horodatage ni numéro de version. Les annotations sont rendues depuis leurs chaînes
sources (``from __future__ import annotations``), jamais depuis les objets de
``typing``, dont le ``repr`` varie d'une version de Python à l'autre.
"""

import dataclasses
import functools
import inspect
from collections.abc import Mapping
from enum import Enum
from itertools import pairwise
from types import MappingProxyType
from typing import Any

from mountain_perf.schemas.common import (
    QUALITY_FLAG_DESCRIPTIONS,
    SPORT_DESCRIPTIONS,
    QualityFlag,
    SourceRef,
    Sport,
)
from mountain_perf.schemas.parameters import ParameterSet, ParameterSpec
from mountain_perf.schemas.route import (
    POINT_KIND_DESCRIPTIONS,
    NamedPoint,
    PointKind,
    ResolvedPoint,
    Route,
    RouteProfile,
)

RUBRICS: tuple[str, ...] = (
    "Champs",
    "Invariants",
    "Producteur",
    "Consommateurs",
    "Non promis",
)
"""Les cinq rubriques que toute docstring de type documente, dans cet ordre."""

DOCUMENTED_TYPES: tuple[type, ...] = (
    Sport,
    QualityFlag,
    SourceRef,
    ParameterSpec,
    ParameterSet,
    PointKind,
    NamedPoint,
    Route,
    ResolvedPoint,
    RouteProfile,
)
"""Types publiés dans le dictionnaire, dans l'ordre de lecture."""

# Any : la clé du Mapping est invariante, et chaque table a son propre type de membre.
ENUM_DESCRIPTIONS: Mapping[type[Enum], Mapping[Any, str]] = MappingProxyType(
    {
        Sport: SPORT_DESCRIPTIONS,
        QualityFlag: QUALITY_FLAG_DESCRIPTIONS,
        PointKind: POINT_KIND_DESCRIPTIONS,
    }
)
"""Description des membres de chaque énumération publiée."""

_HEADER = """\
# Dictionnaire de données

> **Fichier généré** depuis les docstrings de `mountain_perf.schemas` par
> `just dictionary`. Ne pas l'éditer à la main : un test échoue dès qu'il diverge
> du code. Pour le modifier, modifier la docstring, puis relancer la recette.
"""


def rubric_headings(cls: type) -> tuple[str, ...]:
    """Titres de rubrique (soulignés de tirets) trouvés dans la docstring de ``cls``."""
    lines = inspect.cleandoc(cls.__doc__ or "").splitlines()
    return tuple(
        line
        for line, underline in pairwise(lines)
        if line.strip() and underline == "-" * len(line)
    )


def _docstring_markdown(cls: type) -> str:
    """Docstring de classe, titres de rubrique convertis en titres Markdown."""
    lines = inspect.cleandoc(cls.__doc__ or "").splitlines()
    out: list[str] = []
    skip_next = False
    for i, line in enumerate(lines):
        if skip_next:
            skip_next = False
            continue
        next_line = lines[i + 1] if i + 1 < len(lines) else ""
        if line.strip() and next_line == "-" * len(line):
            out += [f"#### {line}", ""]
            skip_next = True
        else:
            out.append(line)
    return "\n".join(out).replace("``", "`")


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _default(field: dataclasses.Field[object]) -> str:
    if field.default is not dataclasses.MISSING:
        value = field.default
        if isinstance(value, Enum):
            return f"`{type(value).__name__}.{value.name}`"
        return f"`{value!r}`"
    if field.default_factory is not dataclasses.MISSING:
        return f"`{field.default_factory()!r}`"
    return "—"


def _render_enum(cls: type[Enum]) -> list[str]:
    descriptions = ENUM_DESCRIPTIONS[cls]
    lines = ["| Membre | Valeur | Description |", "|---|---|---|"]
    for member in cls:
        lines.append(
            f"| `{member.name}` | `{member.value}` | {_cell(descriptions[member])} |"
        )
    return lines


def _render_dataclass(cls: type) -> list[str]:
    lines = ["| Champ | Type | Défaut |", "|---|---|---|"]
    for field in dataclasses.fields(cls):
        lines.append(
            f"| `{field.name}` | `{_cell(str(field.type))}` | {_default(field)} |"
        )
    properties = [
        (name, member)
        for name, member in vars(cls).items()
        if isinstance(member, (property, functools.cached_property))
    ]
    if properties:
        lines += ["", "| Propriété calculée | Type | Sens |", "|---|---|---|"]
        for name, prop in properties:
            getter = prop.fget if isinstance(prop, property) else prop.func
            annotations = getter.__annotations__ if getter else {}
            annotation = str(annotations.get("return", ""))
            summary = inspect.cleandoc(prop.__doc__ or "").split("\n\n")[0]
            summary = " ".join(summary.split()).replace("``", "`")
            lines.append(f"| `{name}` | `{_cell(annotation)}` | {_cell(summary)} |")
    return lines


def render() -> str:
    """Le dictionnaire de données complet, en Markdown."""
    parts = [_HEADER, "## Sommaire", ""]
    parts += [f"- `{cls.__name__}`" for cls in DOCUMENTED_TYPES]
    for cls in DOCUMENTED_TYPES:
        is_enum = issubclass(cls, Enum)
        nature = "énumération" if is_enum else "dataclass gelée"
        parts += ["", "---", "", f"## `{cls.__name__}`", ""]
        parts += [f"*`{cls.__module__}` · {nature}*", ""]
        parts += _render_enum(cls) if is_enum else _render_dataclass(cls)
        parts += ["", _docstring_markdown(cls)]
    return "\n".join(parts) + "\n"
