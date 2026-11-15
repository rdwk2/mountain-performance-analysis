"""Les personnages des profils de démo et leur courbe vraie (M5-3, § 6.1 (b) à (d) et
(f) du brief) : chaque valeur littérale vient du calcul à la main du brief."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from mountain_perf.demo import constantes
from mountain_perf.demo.constantes import CHARACTER_NAMES
from mountain_perf.demo.parcours import route
from mountain_perf.demo.personnages import (
    CHARACTERS,
    PARTS,
    base_speed_kmh,
    character,
    steep_weight,
    true_speed_kmh,
    true_speed_ms,
    true_time_s,
)
from mountain_perf.validation import ContractError

RULE_1 = (
    "Les constantes des profils de démo (M5-3) : inventées et rondes, ou d'ordre de "
    "grandeur courant ; jamais tirées des données de l'athlète (ni valeur, ni loi, ni "
    "ordre de grandeur) ni d'un jeu externe (règle 1 de `CLAUDE.md`, "
    "`docs/decisions/0022`)."
)


@pytest.mark.parametrize(
    ("grade", "speed"),
    [
        (0.35, 2.7),
        (-0.06, 9.6),
        (0.04, 7.8),
        (-0.25, 5.5),
        (0.25, 3.5),
        (-0.10, 10.0),
        (0.40, 2.4),
        (-0.02, 9.2),
    ],
)
def test_base_speed_cases(grade: float, speed: float) -> None:
    assert base_speed_kmh(grade) == pytest.approx(speed, rel=1e-12)


@pytest.mark.parametrize("grade", [0.41, -0.41])
def test_base_speed_out_of_the_curve_raises(grade: float) -> None:
    with pytest.raises(ContractError) as raised:
        base_speed_kmh(grade)
    assert str(raised.value) == f"pente hors de la courbe de base : {grade}"


@pytest.mark.parametrize(
    ("grade", "vertical_m_per_h"),
    [
        (0.10, 600.0),
        (0.20, 800.0),
        (0.30, 900.0),
        (0.40, 960.0),
        (-0.10, -1000.0),
        (-0.20, -1300.0),
        (-0.30, -1350.0),
        (-0.40, -1200.0),
    ],
)
def test_the_vertical_speeds_of_the_knots(
    grade: float, vertical_m_per_h: float
) -> None:
    assert base_speed_kmh(grade) * 1000 * grade == pytest.approx(
        vertical_m_per_h, rel=1e-12
    )


@pytest.mark.parametrize(
    ("grade", "weight"),
    [
        (0.0, 0.0),
        (0.10, 0.0),
        (-0.10, 0.0),
        (0.15, 0.5),
        (-0.15, 0.5),
        (0.20, 1.0),
        (-0.20, 1.0),
        (0.36, 1.0),
    ],
)
def test_steep_weight_cases(grade: float, weight: float) -> None:
    assert steep_weight(grade) == pytest.approx(weight, abs=1e-12)


@pytest.mark.parametrize(
    ("name", "grade", "speed"),
    [
        ("grimpeur", 0.15, 5.0),
        ("rouleur", -0.20, 5.85),
        ("polyvalente", 0.04, 8.58),
        ("moyen", 0.30, 3.0),
        ("debutant", 0.0, 6.75),
    ],
)
def test_true_speed_cases(name: str, grade: float, speed: float) -> None:
    assert true_speed_kmh(character(name), grade) == pytest.approx(speed, rel=1e-12)


def test_true_speed_ms() -> None:
    """La seule conversion : 9,9 km/h = 2,75 m/s."""
    assert true_speed_ms(character("rouleur"), 0.0) == pytest.approx(2.75, rel=1e-12)


TABLE = {
    "debutant": (
        "débutant",
        0,
        11,
        0.75,
        0.75,
        35,
        (0,),
        3,
        (("boucle_douce", 1),),
        "boucle_douce",
    ),
    "polyvalente": (
        "polyvalente",
        1,
        12,
        1.1,
        1.1,
        119,
        (0, 2, 4, 5),
        7,
        (
            ("boucle_raide", 1),
            ("boucle_roulante", 2),
            ("boucle_raide", 1),
            ("boucle_moyenne", 2),
        ),
        "boucle_raide",
    ),
    "grimpeur": (
        "grimpeur",
        2,
        13,
        1.1,
        0.9,
        119,
        (0, 2, 4, 5),
        7,
        (
            ("boucle_raide", 1),
            ("boucle_raide", 1),
            ("boucle_moyenne", 1),
            ("boucle_raide", 2),
        ),
        "boucle_raide",
    ),
    "rouleur": (
        "rouleur",
        3,
        14,
        0.9,
        1.1,
        119,
        (0, 2, 4, 5),
        7,
        (
            ("boucle_roulante", 2),
            ("boucle_roulante", 1),
            ("boucle_roulante", 2),
            ("boucle_douce", 1),
        ),
        "boucle_roulante",
    ),
    "moyen": (
        "moyen",
        4,
        15,
        1.0,
        1.0,
        119,
        (0, 2, 4, 5),
        7,
        (
            ("boucle_moyenne", 2),
            ("boucle_moyenne", 2),
            ("boucle_moyenne", 1),
            ("boucle_roulante", 1),
        ),
        "boucle_moyenne",
    ),
}
"""Le tableau du § 6.1 (d), recopié."""


@pytest.mark.parametrize("name", CHARACTER_NAMES)
def test_every_field_of_each_character(name: str) -> None:
    found = character(name)
    assert (
        found.label,
        found.rank,
        found.seed,
        found.steep_factor,
        found.rolling_factor,
        found.history_days,
        found.outing_days,
        found.cycle_days,
        found.week,
        found.witness_loop,
    ) == TABLE[name]
    assert found.name == name


def test_the_characters_are_in_rank_order() -> None:
    assert tuple(TABLE) == CHARACTER_NAMES
    assert tuple(c.name for c in CHARACTERS) == CHARACTER_NAMES
    assert [c.rank for c in CHARACTERS] == [0, 1, 2, 3, 4]


def test_an_unknown_character_raises() -> None:
    with pytest.raises(ContractError) as raised:
        character("x")
    assert str(raised.value) == (
        "personnage inconnu : x ; les personnages : debutant, polyvalente, grimpeur, "
        "rouleur, moyen"
    )


BASE_STEEP_S = 9_886.746587
BASE_ROLLING_S = 8_257.525084

PART_TIMES = {
    "debutant": (13_182.328782, 11_010.033445),
    "polyvalente": (8_987.951442, 7_506.840985),
    "grimpeur": (8_987.951442, 9_175.027871),
    "rouleur": (10_985.273985, 7_506.840985),
    "moyen": (BASE_STEEP_S, BASE_ROLLING_S),
}
"""Le tableau des temps vrais du § 6.1 (f), en secondes."""


@pytest.mark.parametrize("name", CHARACTER_NAMES)
def test_true_times_of_the_parts(name: str) -> None:
    course = route("deux_parties")
    person = character(name)
    (_, s0, e0), (_, s1, e1) = PARTS
    steep, rolling = PART_TIMES[name]
    assert true_time_s(person, course, s0, e0) == pytest.approx(steep, rel=1e-9)
    assert true_time_s(person, course, s1, e1) == pytest.approx(rolling, rel=1e-9)
    assert true_time_s(person, course, 0.0, 30_000.0) == pytest.approx(
        steep + rolling, rel=1e-9
    )


def test_the_parts() -> None:
    assert PARTS == (
        ("partie raide", 0.0, 10_000.0),
        ("partie roulante", 10_000.0, 30_000.0),
    )


def test_the_order_of_the_parts() -> None:
    """Le scénario : sur la partie raide, grimpeur = polyvalente < moyen < rouleur <
    débutant ; sur la roulante, polyvalente = rouleur < moyen < grimpeur < débutant."""
    course = route("deux_parties")

    def time(name: str, part: int) -> float:
        _, start, end = PARTS[part]
        return true_time_s(character(name), course, start, end)

    steep = [time(n, 0) for n in ("grimpeur", "polyvalente", "moyen", "rouleur")]
    assert steep[0] == pytest.approx(steep[1])
    assert steep[1] < steep[2] < steep[3] < time("debutant", 0)
    rolling = [time(n, 1) for n in ("polyvalente", "rouleur", "moyen", "grimpeur")]
    assert rolling[0] == pytest.approx(rolling[1])
    assert rolling[1] < rolling[2] < rolling[3] < time("debutant", 1)


def test_true_time_refuses_a_variable_grade() -> None:
    with pytest.raises(ContractError, match="pente variable"):
        true_time_s(character("moyen"), route("boucle_raide"), 0.0, 8_000.0)


def test_the_constants_carry_rule_1() -> None:
    path = Path(constantes.__file__)
    docstring = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
    assert docstring is not None
    assert " ".join(docstring.split()).startswith(RULE_1)
