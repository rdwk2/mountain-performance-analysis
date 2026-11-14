"""Les communs du paquet d'inférence (``mountain_perf.analyse.inference.base``, AN3-1,
``docs/decisions/0021``) : l'intervalle, le quantile par statistique d'ordre,
l'intervalle percentile, les générateurs dérivés d'une graine, et l'absence de toute
graine cachée dans le paquet. Sautés sans numpy ou scipy (extra ``analyse``)."""

from __future__ import annotations

import ast
import dataclasses
import math
import random
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")

import numpy

from mountain_perf.analyse import inference
from mountain_perf.analyse.inference.base import (
    InferenceError,
    Interval,
    child_rng,
    order_quantile,
    percentile_interval,
)
from mountain_perf.analyse.inference.linear import ols

PACKAGE = Path(inference.__file__).parent
ALLOWED_RANDOM_CALLS = {"default_rng", "SeedSequence"}
"""Les seuls appels de ``numpy.random`` permis, et seulement dans ``child_rng``."""


def test_t1_interval_refuses_reversed_or_non_finite_bounds() -> None:
    """T1 : ``Interval`` refuse ``low > high``, ``nan`` et ``inf`` ; un point est un
    intervalle."""
    assert Interval(1.0, 1.0) == Interval(1.0, 1.0)
    for low, high in [
        (2.0, 1.0),
        (math.nan, 1.0),
        (0.0, math.nan),
        (-math.inf, 0.0),
        (0.0, math.inf),
    ]:
        with pytest.raises(InferenceError):
            Interval(low, high)


def test_t2_order_quantile_h15() -> None:
    """T2 : H15 (percentiles des entiers 1 à 20 mélangés ; ``order_quantile`` sur
    2 000 valeurs), ``q = 1`` rend le maximum, ``q`` hors de ``]0 ; 1]`` refusé,
    ``B = 1``."""
    draws = list(range(1, 21))
    random.Random(15).shuffle(draws)
    assert percentile_interval(draws, 0.9) == Interval(1.0, 19.0)
    assert percentile_interval(draws, 0.8) == Interval(2.0, 18.0)
    assert percentile_interval(draws, 0.85) == Interval(2.0, 19.0)
    many = list(range(1, 2001))
    assert order_quantile(many, 0.025) == 50.0
    assert order_quantile(many, 0.975) == 1950.0
    assert order_quantile(many, 0.95) == 1900.0
    assert order_quantile(draws, 1.0) == 20.0
    for q in (0.0, -0.1, 1.0001):
        with pytest.raises(InferenceError):
            order_quantile(draws, q)
    assert order_quantile([7.5], 0.025) == 7.5
    assert order_quantile([7.5], 1.0) == 7.5
    with pytest.raises(InferenceError):
        order_quantile([], 0.5)
    with pytest.raises(InferenceError):
        percentile_interval(draws, 1.0)


def _draws(rng: numpy.random.Generator) -> list[int]:
    return [int(rng.integers(1 << 30)) for _ in range(8)]


def test_t3_child_rng_derives_its_stream_from_the_spawn_key() -> None:
    """T3 : même clé, même suite ; ``(0, 1)`` et ``(1, 0)`` différentes ;
    ``child_rng(20261112, 0, 1)`` tire la suite de
    ``SeedSequence(20261112).spawn(1)[0].spawn(2)[1]``, et pas celle de
    ``default_rng([20261112, 0, 1])``."""
    assert _draws(child_rng(20261112, 0, 1)) == _draws(child_rng(20261112, 0, 1))
    assert _draws(child_rng(20261112, 0, 1)) != _draws(child_rng(20261112, 1, 0))
    spawned = numpy.random.SeedSequence(20261112).spawn(1)[0].spawn(2)[1]
    expected = _draws(numpy.random.default_rng(spawned))
    assert _draws(child_rng(20261112, 0, 1)) == expected
    assert _draws(numpy.random.default_rng([20261112, 0, 1])) != expected
    for bad in (-1, 1.5, True):
        with pytest.raises(InferenceError):
            child_rng(cast(int, bad))
        with pytest.raises(InferenceError):
            child_rng(1, cast(int, bad))


def _aliases(tree: ast.Module) -> dict[str, str]:
    """Chaque nom lié par un import de numpy, et le chemin qu'il désigne."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] != "numpy":
                    continue
                if alias.asname is not None:
                    aliases[alias.asname] = alias.name
                else:
                    aliases["numpy"] = "numpy"
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            if node.module.split(".")[0] != "numpy" or node.level:
                continue
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return aliases


def _dotted(node: ast.expr, aliases: dict[str, str]) -> str | None:
    """Le chemin résolu d'un appelé ``a.b.c``, ou ``None``."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name) or node.id not in aliases:
        return None
    return ".".join([aliases[node.id], *reversed(parts)])


def _random_calls(source: str) -> list[tuple[str, str | None, int]]:
    """Les appels d'un attribut de ``numpy.random`` : ``(attribut, fonction
    englobante, nombre d'arguments)``."""
    tree = ast.parse(source)
    aliases = _aliases(tree)
    found: list[tuple[str, str | None, int]] = []

    def visit(node: ast.AST, function: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            inner = function
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                inner = child.name
            if isinstance(child, ast.Call):
                path = _dotted(child.func, aliases)
                if path is not None and path.startswith("numpy.random."):
                    attribute = path.removeprefix("numpy.random.")
                    count = len(child.args) + len(child.keywords)
                    found.append((attribute, function, count))
            visit(child, inner)

    visit(tree, None)
    return found


def _violations(source: str) -> list[str]:
    return [
        f"{attribute} dans {function}"
        for attribute, function, count in _random_calls(source)
        if attribute not in ALLOWED_RANDOM_CALLS
        or function != "child_rng"
        or count == 0
    ]


def test_t3_the_reader_resolves_import_aliases() -> None:
    """T3, le lecteur lui-même : il résout les alias d'import et refuse ce qui n'est
    ni ``default_rng`` ni ``SeedSequence`` dans ``child_rng`` (``Generator(PCG64())``
    est un générateur sans graine)."""
    refused = [
        "import numpy\ndef f():\n    numpy.random.default_rng()\n",
        "import numpy as np\ndef child_rng():\n    np.random.default_rng()\n",
        "import numpy.random as npr\nnpr.normal()\n",
        "from numpy import random\ndef child_rng():\n    random.seed(1)\n",
        "from numpy import random as r\ndef child_rng():\n    r.Generator(r.PCG64())\n",
        "from numpy.random import default_rng as d\ndef g():\n    d(1)\n",
        "import numpy.random\ndef child_rng():\n    numpy.random.standard_normal()\n",
    ]
    for source in refused:
        assert _violations(source), source
    accepted = (
        "import numpy\n"
        "def child_rng(s: int) -> numpy.random.Generator:\n"
        "    return numpy.random.default_rng(numpy.random.SeedSequence(s))\n"
        "def f(rng: numpy.random.Generator) -> None:\n"
        "    rng.integers(2)\n"
    )
    assert _violations(accepted) == []


def test_t3_no_hidden_seed_in_the_package() -> None:
    """T3 : dans le paquet, les seuls appels de ``numpy.random`` sont
    ``default_rng`` (avec un argument) et ``SeedSequence``, dans ``child_rng``."""
    paths = sorted(PACKAGE.glob("*.py"))
    assert paths
    for path in paths:
        assert _violations(path.read_text(encoding="utf-8")) == [], path.name
    base = (PACKAGE / "base.py").read_text(encoding="utf-8")
    assert {a for a, _, _ in _random_calls(base)} == ALLOWED_RANDOM_CALLS


def test_t2_order_quantile_guards() -> None:
    """T2, garde-fous (A1) : sur les entiers 1 à 2 000, ``percentile_interval`` au
    niveau 0,95 rend exactement ``[50 ; 1 950]`` (``q = (1 − 0,95)/2`` vaut un peu
    plus que 0,025 : le ``− 1e−9`` le ramène à ``k = 50``) ; à ``q = 1e−12``, ``k``
    vaut 1."""
    assert (1 - 0.95) / 2 > 0.025
    assert percentile_interval(list(range(1, 2001)), 0.95) == Interval(50.0, 1950.0)
    assert order_quantile(list(range(1, 21)), 1e-12) == 1.0


def assert_frozen(output: object) -> None:
    """Une sortie du paquet est immuable (A4) : chaque champ tableau a
    ``flags.writeable`` faux, et affecter un champ lève ``FrozenInstanceError``."""
    assert dataclasses.is_dataclass(output)
    for field in dataclasses.fields(output):
        value = getattr(output, field.name)
        if isinstance(value, numpy.ndarray):
            assert not value.flags.writeable, field.name
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(output, field.name, value)


def test_t1_an_interval_is_frozen() -> None:
    """T1, immuabilité (A4) : un ``Interval``."""
    assert_frozen(Interval(0.0, 1.0))


@pytest.mark.parametrize(
    ("call", "match"),
    [
        (lambda: percentile_interval([1.0, 2.0], 0.0), "^level :"),
        (lambda: child_rng(cast(int, True)), "^root_seed :"),
        (lambda: child_rng(-1), "^root_seed :"),
        (lambda: child_rng(cast(int, 1.5)), "^root_seed :"),
        (lambda: child_rng(1, -1), "^key :"),
        (lambda: ols(numpy.empty((0, 2)), []), "^X :"),
    ],
)
def test_t1_refusals_at_the_bounds(call: Callable[[], object], match: str) -> None:
    """T1, refus aux bornes (L4, L5) : niveau 0, graine booléenne, négative ou non
    entière, matrice vide ; le message nomme l'argument."""
    with pytest.raises(InferenceError, match=match):
        call()


def test_t1_acceptances_next_to_the_bounds() -> None:
    """T1, acceptations juste à côté : niveau ``1e−9``, graine 0, clé 0, une ligne."""
    percentile_interval([1.0, 2.0], 1e-9)
    child_rng(0)
    child_rng(0, 0)
    ols(numpy.array([[1.0], [1.0]]), [1.0, 2.0])
