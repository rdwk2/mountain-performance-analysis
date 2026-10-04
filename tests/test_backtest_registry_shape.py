"""Forme des contrats stockés au registre (§ 7.6 et § 8.1, test 5, du brief M4b-4 ;
``0010`` D14).

L'empreinte de forme de ``RegistryEvent``, de ``DOCUMENT_TYPES`` et de toutes les
dataclasses atteintes par leurs annotations : elle change dès qu'un champ, une
annotation ou une valeur d'énumération d'un contrat stocké change. Une PR qui la change
change ce que le registre relit, et doit dire comment il relit ses documents existants
(ligne de ``BACKLOG.md``). Le rendu est celui du brief, recopié.
"""

import dataclasses
import types
import typing
from collections.abc import Mapping
from datetime import date, datetime
from enum import Enum

from mountain_perf.backtest import DOCUMENT_TYPES, content_hash
from mountain_perf.schemas import RegistryEvent


def _render(annotation: object) -> str:
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin in (types.UnionType, typing.Union):
        (inner,) = [a for a in args if a is not type(None)]
        return f"{_render(inner)}|None"
    if annotation in (int, float, bool, str, datetime, date):
        return annotation.__name__
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return f"{annotation.__name__}{{{','.join(str(m.value) for m in annotation)}}}"
    if origin is tuple:
        if len(args) == 2 and args[1] is Ellipsis:
            return f"tuple[{_render(args[0])},...]"
        return "tuple[" + ",".join(_render(a) for a in args) + "]"
    if origin is Mapping:
        return f"Mapping[str,{_render(args[1])}]"
    if dataclasses.is_dataclass(annotation):
        return annotation.__name__  # type: ignore[union-attr]
    raise TypeError(annotation)


def _shape() -> tuple[int, str]:
    seen: dict[str, str] = {}
    todo: list[type] = [RegistryEvent, *DOCUMENT_TYPES]
    while todo:
        cls = todo.pop()
        if cls.__name__ in seen:
            continue
        hints = typing.get_type_hints(cls)
        parts = []
        for field in dataclasses.fields(cls):
            annotation = hints[field.name]
            parts.append(f"{field.name}:{_render(annotation)}")
            stack = [annotation]
            while stack:
                a = stack.pop()
                if dataclasses.is_dataclass(a) and isinstance(a, type):
                    todo.append(a)
                stack.extend(typing.get_args(a))
        seen[cls.__name__] = f"{cls.__name__}(" + ",".join(parts) + ")"
    text = "\n".join(sorted(seen.values()))
    return len(seen), content_hash(text.encode())


def test_shape_of_the_stored_contracts() -> None:
    """D14 : 44 contrats stockés, et leur empreinte de forme d'aujourd'hui."""
    assert _shape() == (
        44,
        "4e2f2b5569ef8b6cdf9a1ea6d7c952bd1c14e5bb409f2f9653c43847dcb6d2ed",
    )
