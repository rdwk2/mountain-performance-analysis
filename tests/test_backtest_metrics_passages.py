"""Erreurs aux passages (§ 6.7, § 7.5 et § 8.1, test 6, du brief M4b-1).

``0010`` D7.3 et sa précision de M4b-1 : ``C_k = P_k − T_k`` en secondes ; un ``C_k``
indisponible est publié avec son motif ; agrégats sur les points observés — aucun,
``support insuffisant`` ; une sortie de modèle invalide en l'un des points donnés,
observé ou non, ``erreur du modèle`` ; sinon les ``C_k`` des points observés. Chaque
ligne du § 7.5, chaque champ.
"""

import math

import pytest

from fixtures.metrics import raises_value_error
from mountain_perf.backtest import passage_errors
from mountain_perf.schemas import MetricValue, Unavailability

INSUF = Unavailability.INSUFFICIENT_SUPPORT
ERR = Unavailability.MODEL_ERROR
ABSENT = Unavailability.ABSENT
AMBIGUOUS = Unavailability.AMBIGUOUS
NAN = math.nan

Point = float | Unavailability
"""Un ``C_k`` attendu (effectif 1) : sa valeur, ou son motif."""

ROWS: dict[
    str,
    tuple[
        tuple[float | None, ...],
        tuple[float | None, ...],
        tuple[Unavailability | None, ...],
        tuple[Point, ...],
        bool,
        tuple[float, float, float] | Unavailability,
        int,
    ],
] = {
    "T27": (
        (100.0, 200.0, 300.0, 400.0),
        (120.0, 240.0, 360.0, 480.0),
        (None,) * 4,
        (-20.0, -40.0, -60.0, -80.0),
        False,
        (80.0, -20.0, -80.0),
        4,
    ),
    "Signes": (
        (90.0, 250.0, 290.0, 400.0),
        (120.0, 240.0, None, 380.0),
        (None, None, AMBIGUOUS, None),
        (-30.0, 10.0, AMBIGUOUS, 20.0),
        False,
        (30.0, 20.0, -30.0),
        3,
    ),
    "Aucun observé": (
        (100.0, 200.0),
        (None, None),
        (INSUF, ABSENT),
        (INSUF, ABSENT),
        False,
        INSUF,
        0,
    ),
    "Erreur observée": (
        (100.0, NAN),
        (100.0, 200.0),
        (None, None),
        (0.0, ERR),
        True,
        ERR,
        2,
    ),
    "Erreur non observée": (
        (100.0, None),
        (120.0, None),
        (None, ABSENT),
        (-20.0, ABSENT),
        True,
        ERR,
        1,
    ),
    "Vide": ((), (), (), (), False, INSUF, 0),
    "Nuls": (
        (100.0, 200.0),
        (100.0, 200.0),
        (None, None),
        (0.0, 0.0),
        False,
        (0.0, 0.0, 0.0),
        2,
    ),
    "Aucun observé, erreur": (
        (NAN, 200.0),
        (None, None),
        (ABSENT, ABSENT),
        (ABSENT, ABSENT),
        True,
        INSUF,
        0,
    ),
    "Tous observés en erreur": ((NAN,), (100.0,), (None,), (ERR,), True, ERR, 1),
}
"""Le tableau du § 7.5 : ``P``, ``T``, motifs, ``C_k``, drapeau, agrégats
(``max |C|``, ``max C``, ``min C``) ou leur motif, et leur effectif."""


def check_point(actual: MetricValue, expected: Point) -> None:
    assert actual.count == 1
    if isinstance(expected, Unavailability):
        assert actual.value is None
        assert actual.unavailability is expected
    else:
        assert actual.unavailability is None
        assert actual.value == pytest.approx(expected, abs=1e-9)


@pytest.mark.parametrize("name", ROWS)
def test_passage_errors_reproduce_the_brief(name: str) -> None:
    """§ 7.5 : ``0010`` D7.3, choix 4 de rdw, lectures de D7.3 (choix 8) et choix 7
    du brief — chaque ``C_k``, le drapeau, les trois agrégats et leur effectif."""
    projected, observed, motifs, points, model_error, aggregates, count = ROWS[name]
    errors = passage_errors(projected, observed, motifs)
    assert len(errors.errors_s) == len(points)
    for actual, expected in zip(errors.errors_s, points, strict=True):
        check_point(actual, expected)
    assert errors.model_error is model_error
    published = (errors.max_abs_error_s, errors.max_error_s, errors.min_error_s)
    for i, aggregate in enumerate(published):
        assert aggregate.count == count
        if isinstance(aggregates, Unavailability):
            assert aggregate.value is None
            assert aggregate.unavailability is aggregates
        else:
            assert aggregate.unavailability is None
            assert aggregate.value == pytest.approx(aggregates[i], abs=1e-9)


def test_healthy_error_is_published_under_the_flag() -> None:
    """Choix 7 du brief : un ``C_k`` sain reste publié quand le drapeau est levé ;
    seuls les agrégats en dépendent."""
    errors = passage_errors((100.0, None), (120.0, None), (None, ABSENT))
    assert errors.model_error
    assert errors.errors_s[0].value == -20.0
    assert errors.max_error_s.unavailability is ERR


@pytest.mark.parametrize(
    ("arguments", "match"),
    [
        (((1.0,), (None,), (None,)), "présent si et seulement si"),
        (((1.0,), (1.0,), (ABSENT,)), "présent si et seulement si"),
        (((1.0,), (-1.0,), (None,)), r"observed_s\[0\] doit être fini et >= 0"),
        (((1.0,), (math.inf,), (None,)), r"observed_s\[0\] doit être fini et >= 0"),
        (((1.0,), (None,), (ERR,)), "un motif de modèle et non d'observation"),
        (((1.0, 2.0), (1.0,), (None,)), "longueurs différentes"),
        (((1.0,), (1.0,), (None, None)), "longueurs différentes"),
    ],
    ids=[
        "absent-without-motif",
        "present-with-motif",
        "negative",
        "infinite",
        "model-error-motif",
        "projected-length",
        "motif-length",
    ],
)
def test_passage_errors_preconditions(
    arguments: tuple[
        tuple[float | None, ...],
        tuple[float | None, ...],
        tuple[Unavailability | None, ...],
    ],
    match: str,
) -> None:
    """Choix 10 du brief : une entrée d'observation fausse est une erreur d'appel ;
    ``model_error`` n'est jamais un motif d'observation."""
    with raises_value_error(f"passage_errors : .*{match}"):
        passage_errors(*arguments)
