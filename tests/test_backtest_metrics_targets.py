"""``K`` par défaut et cible d'usage (§ 6.8, § 6.9, § 7.6, § 7.7 et § 8.1, test 6, du
brief M4b-1 ; précisions 3 et 5 de la relecture du plan).

``0010`` D7.4 et sa précision de M4b-1, D4.12 (arrivée unique). Chaque ligne des
§§ 7.6 et 7.7, chaque champ : poids publiés (déclarés : tels quels, ``==`` ; par
défaut : à ``1e−15`` des fractions, précision 3), ``q_usage`` et
``q_usage | préfixe`` (valeur à ``1e−9``, motif, effectif), comparables, drapeau,
écart d'ancrage.
"""

import math
from fractions import Fraction

import pytest

from fixtures.metrics import raises_value_error
from mountain_perf.backtest import default_targets, usage_target
from mountain_perf.schemas import MetricValue, PassageRole, Unavailability

INSUF = Unavailability.INSUFFICIENT_SUPPORT
ERR = Unavailability.MODEL_ERROR
ABSENT = Unavailability.ABSENT
AMBIGUOUS = Unavailability.AMBIGUOUS
In, Dp, Ar = PassageRole.INTERMEDIATE, PassageRole.DEPARTURE, PassageRole.ARRIVAL
NAN = math.nan

# ---------------------------------------------------------------------------
# K par défaut (§ 7.6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        ((), ((None, True),)),
        ((In, In), ((0, False), (1, False), (None, True))),
        ((Dp, In, Ar), ((1, False), (2, True))),
        ((In, Ar, Ar), ((0, False), (1, True))),
        ((Dp,), ((None, True),)),
        ((Dp, Dp, In), ((2, False), (None, True))),
        ((Ar,), ((0, True),)),
        ((In, Dp), ((0, False), (None, True))),
        ((Ar, In), ((1, False), (0, True))),
    ],
    ids=["none", "I,I", "Dp,I,Ar", "I,Ar,Ar", "Dp", "Dp,Dp,I", "Ar", "I,Dp", "Ar,I"],
)
def test_default_targets(
    roles: tuple[PassageRole, ...], expected: tuple[tuple[int | None, bool], ...]
) -> None:
    """§ 7.6 : ``0010`` D7.4 (départ exclu, plus l'arrivée ; sans waypoint,
    ``K = {arrivée}``) et D4.12 (arrivée unique : deux lieux à moins de 1 m de ``L``
    donnent un seul élément) ; choix 8 du brief — l'arrivée toujours en dernier,
    première occurrence de rôle arrivée."""
    members = default_targets(roles)
    assert tuple((m.occurrence_index, m.arrival) for m in members) == expected


# ---------------------------------------------------------------------------
# Cible d'usage (§ 7.7)
# ---------------------------------------------------------------------------

Usage = float | tuple[Unavailability, int]
"""``q_usage`` ou ``q_usage | préfixe`` attendu : sa valeur (effectif donné à part),
ou ``(motif, effectif)``."""

INPUTS: dict[
    str,
    tuple[
        tuple[float | None, ...],
        tuple[float | None, ...],
        tuple[float | None, ...],
        tuple[Unavailability | None, ...],
        tuple[float, ...] | None,
        float | None,
    ],
] = {
    "Défaut": ((140.0, 250.0), (100.0, 300.0), (120.0, 280.0), (None,) * 2, None, None),
    "T21": (
        (100.0, 100.0),
        (100.0, 100.0),
        (100.0, None),
        (None, ABSENT),
        (0.5, 0.5),
        None,
    ),
    "X01": ((490.0,), (490.0,), (490.0,), (None,), None, 10.0),
    "X13": ((100.0, 250.0), (100.0, 250.0), (100.0, None), (None, INSUF), None, None),
    "Premier motif": (
        (100.0, 200.0, 300.0),
        (100.0, 200.0, 300.0),
        (100.0, None, None),
        (None, AMBIGUOUS, ABSENT),
        None,
        None,
    ),
    "T nul": ((40.0, 210.0), (50.0, 200.0), (0.0, 200.0), (None,) * 2, None, None),
    "Base invalide": (
        (100.0, 200.0),
        (100.0, 0.0),
        (100.0, 200.0),
        (None,) * 2,
        None,
        None,
    ),
    "Base invalide, poids déclarés": (
        (100.0, 200.0),
        (100.0, -1.0),
        (100.0, 200.0),
        (None,) * 2,
        (0.5, 0.5),
        None,
    ),
    "Modèle invalide": (
        (NAN, 200.0),
        (100.0, 200.0),
        (100.0, 200.0),
        (None,) * 2,
        None,
        None,
    ),
    "Préfixe renormalisé": (
        (120.0, 330.0, 700.0),
        (100.0, 300.0, 600.0),
        (100.0, 300.0, None),
        (None, None, INSUF),
        None,
        None,
    ),
    "Poids nuls disponibles": (
        (100.0, 100.0),
        (100.0, 100.0),
        (90.0, None),
        (None, ABSENT),
        (0.0, 1.0),
        None,
    ),
    "Aucun disponible": (
        (100.0, 200.0),
        (100.0, 200.0),
        (None, None),
        (ABSENT, INSUF),
        None,
        None,
    ),
    "Motif et erreur": (
        (NAN, 100.0),
        (100.0, 100.0),
        (100.0, None),
        (None, ABSENT),
        None,
        None,
    ),
    "Poids décimaux": (
        (110.0, 200.0, 300.0),
        (100.0, 200.0, 300.0),
        (100.0, 200.0, 300.0),
        (None,) * 3,
        (0.1, 0.2, 0.7),
        None,
    ),
    "Aucun disponible, erreur": (
        (NAN, 200.0),
        (100.0, 200.0),
        (None, None),
        (ABSENT, INSUF),
        None,
        None,
    ),
    "Erreur sur un indisponible": (
        (100.0, NAN),
        (100.0, 100.0),
        (100.0, None),
        (None, ABSENT),
        None,
        None,
    ),
    "Poids nuls, erreur": (
        (NAN, 100.0),
        (100.0, 100.0),
        (90.0, None),
        (None, ABSENT),
        (0.0, 1.0),
        None,
    ),
}
"""Les entrées du § 7.7 : ``P``, ``P^(0)``, ``T``, motifs, poids déclarés, écart."""

F = Fraction
EXPECTED: dict[
    str,
    tuple[
        tuple[Fraction | float, ...] | None, Usage, Usage, int, tuple[bool, ...], bool
    ],
] = {
    "Défaut": ((F(1, 4), F(3, 4)), 0.125, 0.125, 2, (True, True), False),
    "T21": ((0.5, 0.5), (ABSENT, 1), 0.0, 1, (True, False), False),
    "X01": ((F(1),), 0.0, 0.0, 1, (True,), False),
    "X13": ((F(2, 7), F(5, 7)), (INSUF, 1), 0.0, 1, (True, False), False),
    "Premier motif": (
        (F(1, 6), F(1, 3), F(1, 2)),
        (AMBIGUOUS, 1),
        0.0,
        1,
        (True, False, False),
        False,
    ),
    "T nul": ((F(1, 5), F(4, 5)), 0.2, 0.2, 2, (False, True), False),
    "Base invalide": (None, (ERR, 2), (ERR, 2), 2, (True, True), True),
    "Base invalide, poids déclarés": (
        (0.5, 0.5),
        (ERR, 2),
        (ERR, 2),
        2,
        (True, True),
        True,
    ),
    "Modèle invalide": ((F(1, 3), F(2, 3)), (ERR, 2), (ERR, 2), 2, (True, True), True),
    "Préfixe renormalisé": (
        (F(1, 10), F(3, 10), F(6, 10)),
        (INSUF, 2),
        0.125,
        2,
        (True, True, False),
        False,
    ),
    "Poids nuls disponibles": (
        (0.0, 1.0),
        (ABSENT, 1),
        (INSUF, 1),
        1,
        (True, False),
        False,
    ),
    "Aucun disponible": (
        (F(1, 3), F(2, 3)),
        (ABSENT, 0),
        (INSUF, 0),
        0,
        (False, False),
        False,
    ),
    "Motif et erreur": (
        (F(1, 2), F(1, 2)),
        (ABSENT, 1),
        (ERR, 1),
        1,
        (True, False),
        True,
    ),
    "Poids décimaux": ((0.1, 0.2, 0.7), 0.01, 0.01, 3, (True, True, True), False),
    "Aucun disponible, erreur": (
        (F(1, 3), F(2, 3)),
        (ABSENT, 0),
        (INSUF, 0),
        0,
        (False, False),
        True,
    ),
    "Erreur sur un indisponible": (
        (F(1, 2), F(1, 2)),
        (ABSENT, 1),
        (ERR, 1),
        1,
        (True, False),
        True,
    ),
    "Poids nuls, erreur": ((0.0, 1.0), (ABSENT, 1), (INSUF, 1), 1, (True, False), True),
}
"""Le tableau des résultats du § 7.7 : poids publiés (``Fraction`` : poids par défaut,
à ``1e−15`` ; flottant : poids déclarés, exacts), ``q_usage``, ``q_usage_prefix``,
effectif des valeurs de ``q_usage_prefix`` (et de ``q_usage`` disponible),
comparables, drapeau."""


def check_usage(actual: MetricValue, expected: Usage, count: int) -> None:
    if isinstance(expected, tuple):
        motif, motif_count = expected
        assert actual.value is None
        assert actual.unavailability is motif
        assert actual.count == motif_count
    else:
        assert actual.unavailability is None
        assert actual.value == pytest.approx(expected, abs=1e-9)
        assert actual.count == count


@pytest.mark.parametrize("name", INPUTS)
def test_usage_target_reproduces_the_brief(name: str) -> None:
    """§ 7.7 : ``0010`` D7.4 et sa précision (motif du premier indisponible, effectif
    des disponibles, préfixe renormalisé) ; choix 5, 6 de rdw et 9 du brief."""
    projected, base, observed, motifs, weights, gap_m = INPUTS[name]
    published, usage, prefix, count, comparable, model_error = EXPECTED[name]
    target = usage_target(
        projected, base, observed, motifs, weights=weights, arrival_anchor_gap_m=gap_m
    )
    if published is None:
        assert target.weights is None
    else:
        assert target.weights is not None
        assert len(target.weights) == len(published)
        for actual, wanted in zip(target.weights, published, strict=True):
            if isinstance(wanted, Fraction):
                assert abs(actual - float(wanted)) <= 1e-15
            else:
                assert actual == wanted
    check_usage(target.q_usage, usage, len(observed))
    check_usage(target.q_usage_prefix, prefix, count)
    assert target.q_usage.count == target.q_usage_prefix.count == count
    assert target.comparable == comparable
    assert target.model_error is model_error
    assert target.arrival_anchor_gap_m == gap_m
    assert target.target_count == len(observed)
    assert target.available_count == count


def test_anchored_arrival_gap_is_published_as_given() -> None:
    """X01 : « arrivée ancrée, 10 m » — ``q_usage = 0`` et l'écart ``L − s'_K`` publié
    tel quel (D4.8, D7.4)."""
    target = usage_target(
        (490.0,), (490.0,), (490.0,), (None,), arrival_anchor_gap_m=10.0
    )
    assert target.arrival_anchor_gap_m == 10.0
    assert target.q_usage.value == 0.0
    assert (
        usage_target((490.0,), (490.0,), (490.0,), (None,)).arrival_anchor_gap_m is None
    )


def test_declared_weights_are_published_as_a_tuple() -> None:
    """Précision 5 : des poids déclarés passés en liste sont une entrée valide ;
    publiés en ``tuple(weights)``, mêmes valeurs."""
    target = usage_target(
        (110.0, 200.0, 300.0),
        (100.0, 200.0, 300.0),
        (100.0, 200.0, 300.0),
        (None,) * 3,
        weights=[0.1, 0.2, 0.7],
    )
    assert target.weights == (0.1, 0.2, 0.7)
    assert isinstance(target.weights, tuple)


def test_near_one_weights_are_accepted() -> None:
    """Choix 11 du brief : ``(0.5, 0.5 + 5e−10)`` somme à 1 à ``1e−9`` près."""
    target = usage_target(
        (100.0, 100.0),
        (100.0, 100.0),
        (100.0, 100.0),
        (None,) * 2,
        weights=(0.5, 0.5 + 5e-10),
    )
    assert target.weights == (0.5, 0.5 + 5e-10)


def test_decimal_weights_use_the_declared_weights() -> None:
    """§ 7.7, Poids décimaux : ``0.1 × 0.1 = 0.01`` aux poids déclarés ; ``1/60`` aux
    poids par défaut ou par la formule courte ``Σ |P − T| / Σ P^(0)``."""
    projected, base, observed, motifs, weights, _ = INPUTS["Poids décimaux"]
    declared = usage_target(projected, base, observed, motifs, weights=weights)
    default = usage_target(projected, base, observed, motifs)
    assert declared.q_usage.value == pytest.approx(0.01, abs=1e-9)
    assert default.q_usage.value == pytest.approx(1 / 60, abs=1e-9)


PRECONDITIONS = [
    ("T21", {"weights": (2.0, -1.0)}, r"weights\[1\] doit être fini et >= 0"),
    ("T21", {"weights": (0.5, 0.49)}, "les poids somment à"),
    ("T21", {"weights": (0.5, 0.5 + 2e-9)}, "les poids somment à"),
    ("T21", {"weights": (0.5, NAN)}, r"weights\[1\] doit être fini et >= 0"),
    ("T21", {"weights": (1.0,)}, "1 poids pour 2 éléments de K"),
    ("X01", {"arrival_anchor_gap_m": -1.0}, "arrival_anchor_gap_m doit être fini"),
    ("X01", {"arrival_anchor_gap_m": NAN}, "arrival_anchor_gap_m doit être fini"),
]


@pytest.mark.parametrize(
    ("name", "keywords", "match"),
    PRECONDITIONS,
    ids=["2,-1", "0.99", "1+2e-9", "nan", "length", "gap<0", "gap=nan"],
)
def test_usage_target_keyword_preconditions(
    name: str, keywords: dict[str, object], match: str
) -> None:
    """Choix 9 et 10 du brief : poids déclarés finis, ``>= 0``, de somme 1 à
    ``WEIGHT_SUM_TOLERANCE`` près (``T21`` : ``(2, −1)`` refusés) ; écart d'ancrage fini
    et ``>= 0``."""
    projected, base, observed, motifs, _, _ = INPUTS[name]
    weights = keywords.get("weights")
    gap_m = keywords.get("arrival_anchor_gap_m")
    assert weights is None or isinstance(weights, tuple)
    assert gap_m is None or isinstance(gap_m, float)
    with raises_value_error(f"usage_target : {match}"):
        usage_target(
            projected,
            base,
            observed,
            motifs,
            weights=weights,
            arrival_anchor_gap_m=gap_m,
        )


@pytest.mark.parametrize(
    ("arguments", "match"),
    [
        (((), (), (), ()), "K vide"),
        (((1.0,), (1.0,), (None,), (None,)), "présent si et seulement si"),
        (((1.0,), (1.0,), (100.0,), (ABSENT,)), "présent si et seulement si"),
        (((1.0,), (1.0,), (None,), (ERR,)), "un motif de modèle et non d'observation"),
        (((1.0,), (1.0,), (-1.0,), (None,)), r"observed_s\[0\] doit être fini et >= 0"),
        (((1.0, 2.0), (1.0,), (1.0,), (None,)), "longueurs différentes"),
    ],
    ids=[
        "empty",
        "absent-without-motif",
        "present-with-motif",
        "model-error-motif",
        "negative",
        "length",
    ],
)
def test_usage_target_observation_preconditions(
    arguments: tuple[
        tuple[float | None, ...],
        tuple[float | None, ...],
        tuple[float | None, ...],
        tuple[Unavailability | None, ...],
    ],
    match: str,
) -> None:
    """Choix 10 du brief : ``K`` vide, instants et motifs faux sont des erreurs
    d'appel."""
    with raises_value_error(f"usage_target : .*{match}"):
        usage_target(*arguments)


# ---------------------------------------------------------------------------
# Correctifs de la relecture de la PR #14
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("motifs", "expected"),
    [
        ((ABSENT, AMBIGUOUS), ABSENT),
        ((AMBIGUOUS, ABSENT), AMBIGUOUS),
        ((INSUF, ABSENT), INSUF),
    ],
    ids=["absent,ambigu", "ambigu,absent", "insuffisant,absent"],
)
def test_usage_motif_is_the_first_in_k_order(
    motifs: tuple[Unavailability, Unavailability], expected: Unavailability
) -> None:
    """Choix 6 de rdw, ``0010`` D7.4 (précision de M4b-1) : le motif du premier
    élément indisponible dans l'ordre de ``K``, quel que soit celui des suivants."""
    target = usage_target((100.0, 200.0), (100.0, 200.0), (None, None), motifs)
    assert target.q_usage == MetricValue(None, expected, 0)


def test_zero_anchor_gap_is_published() -> None:
    """Choix 9 : l'écart d'ancrage est fini et ``>= 0``, zéro compris ; publié tel
    quel."""
    target = usage_target(
        (490.0,), (490.0,), (490.0,), (None,), arrival_anchor_gap_m=0.0
    )
    assert target.arrival_anchor_gap_m == 0.0
