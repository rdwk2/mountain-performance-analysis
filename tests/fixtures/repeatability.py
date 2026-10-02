"""Jours synthétiques de la référence de répétabilité (M4b-3) — les cas du § 7.2 du
brief M4b-3.

Les données sont **recopiées telles quelles** du § 7.2 (valeurs exactes) : seuls
changent les types, pour mypy strict (``DaySpec`` gelée au lieu d'un ``dict``) et le
nom ``moving`` au lieu de ``M`` dans ``tm`` (ruff N806). ``A``, ``F``, ``D``, ``X`` :
montée, plat, descente, mixte, par leur valeur de ``RegimeClass`` ; ``tm(e, m)`` : les
onze temps d'une cellule.

- :data:`CASES` : les quinze cas du § 7.2 par leur nom ; Lent limité est Lent avec
  ``LENT_LIMITE_MAX_ITERATIONS`` ;
- :data:`TOTAL_NUL_NON_VU`, :data:`ZEROS_CROISES`, :data:`JOUR_ISOLE` : les données
  des trois tests nommés du § 8.1, test 4 ;
- :func:`log_cells`, :func:`plan_cells` : les cellules d'une classe d'un cas, clés
  ``(u, k)`` avec ``u`` le rang du jour dans le cas (§ 7.1) ;
- :func:`close` : la tolérance ``1e−6·max(1, |x|)`` du § 7.0.

Utilisées par les ``tests/test_*repeatability*.py``.
"""

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

A, F, D, X = "ascent", "flat", "descent", "mixed"

Times = tuple[float, ...]
Cells = Mapping[int, tuple[str, Times]]


def tm(e: float, m: float | None = None) -> Times:
    """Temps sous les onze horloges : écoulé e ; M_θ = m, m−1, m−2, m−1, m (m = e − 10
    par défaut ; m = 0 : nul sous les cinq M_θ) ; (M+U)_θ = e, e, e−1, e, e."""
    if m is None:
        m = e - 10
    moving = (0.0,) * 5 if m == 0 else (m, m - 1, m - 2, m - 1, m)
    return (
        float(e),
        *(float(x) for x in moving),
        float(e),
        float(e),
        float(e - 1),
        float(e),
        float(e),
    )


@dataclass(frozen=True)
class DaySpec:
    """Un jour du § 7.2 : date ISO, multi-sorties, cellules ``{k: (classe, onze
    temps)}``, indices ancrés."""

    date: str
    multi: bool
    cells: Cells
    anchored: frozenset[int]


def day(
    date: str, cells: Cells, anchored: Iterable[int] = (), multi: bool = False
) -> DaySpec:
    """Un jour : date ISO, cellules {k: (classe, onze temps)}, indices ancrés,
    multi-sorties."""
    return DaySpec(date, multi, dict(cells), frozenset(anchored))


# 1. Complet : trois jours voient les neuf segments ; montée 3, descente 3, plat 2,
# mixte 1.
COMPLET = [
    day(
        "2026-05-01",
        {
            0: (A, tm(200)),
            1: (A, tm(210)),
            2: (A, tm(190)),
            3: (D, tm(120)),
            4: (D, tm(110)),
            5: (D, tm(130)),
            6: (F, tm(150)),
            7: (F, tm(160)),
            8: (X, tm(170)),
        },
    ),
    day(
        "2026-05-08",
        {
            0: (A, tm(220)),
            1: (A, tm(225)),
            2: (A, tm(200)),
            3: (D, tm(118)),
            4: (D, tm(121)),
            5: (D, tm(126)),
            6: (F, tm(140)),
            7: (F, tm(171)),
            8: (X, tm(160)),
        },
    ),
    day(
        "2026-05-15",
        {
            0: (A, tm(205)),
            1: (A, tm(230)),
            2: (A, tm(185)),
            3: (D, tm(131)),
            4: (D, tm(108)),
            5: (D, tm(119)),
            6: (F, tm(155)),
            7: (F, tm(149)),
            8: (X, tm(181)),
        },
    ),
]

# 2. Variantes : quatre jours, couvertures partielles, une composante par classe ; le
#    segment 9 n'est vu que par le dernier jour (hors S_j de son pli) ; segment 0 ancré
#    le 2e jour ; montée 0..4, descente 5..8, plat 9.
VARIANTES = [
    day(
        "2026-06-01",
        {
            0: (A, tm(200)),
            1: (A, tm(205)),
            2: (A, tm(198)),
            5: (D, tm(120)),
            6: (D, tm(115)),
            7: (D, tm(122)),
        },
    ),
    day(
        "2026-06-03",
        {
            1: (A, tm(212)),
            2: (A, tm(207)),
            3: (A, tm(240)),
            4: (A, tm(233)),
            6: (D, tm(119)),
            7: (D, tm(126)),
            8: (D, tm(131)),
        },
        anchored={0},
    ),
    day(
        "2026-06-05",
        {
            0: (A, tm(196)),
            3: (A, tm(229)),
            4: (A, tm(226)),
            5: (D, tm(117)),
            8: (D, tm(127)),
        },
    ),
    day(
        "2026-06-09",
        {
            0: (A, tm(209)),
            1: (A, tm(214)),
            2: (A, tm(204)),
            3: (A, tm(245)),
            4: (A, tm(238)),
            5: (D, tm(124)),
            6: (D, tm(121)),
            7: (D, tm(129)),
            8: (D, tm(136)),
            9: (F, tm(150)),
        },
    ),
]

# 3. Deux composantes : montée. Jour retiré W (2026-07-04) voit 0..3 ; P voit 0, 1 ; Q
#    voit 2, 3 : sans W, deux composantes -> W : référence non identifiée. Descente : W
#    et P voient 10..12, R ne voit que 13, à temps nul sous M (autre composante, ignorée
#    dans les plis de W et P).
DEUX_COMPOSANTES = [
    day(
        "2026-07-01",
        {
            0: (A, tm(200)),
            1: (A, tm(210)),
            10: (D, tm(120)),
            11: (D, tm(125)),
            12: (D, tm(118)),
        },
    ),
    day("2026-07-02", {2: (A, tm(190)), 3: (A, tm(215))}),
    day("2026-07-03", {13: (D, tm(100, 0))}),
    day(
        "2026-07-04",
        {
            0: (A, tm(206)),
            1: (A, tm(214)),
            2: (A, tm(197)),
            3: (A, tm(222)),
            10: (D, tm(123)),
            11: (D, tm(129)),
            12: (D, tm(121)),
        },
    ),
]

# 4. Zéros : montée 0..2 à 100 s environ, descente 3 ; sous M, le jour 1 a la descente
#    nulle (zéro du jour retiré sur S_j), le jour 2 aussi (zéro d'apprentissage) ; le
#    jour 4 a un segment 9 nul jamais vu à l'apprentissage (hors S_j).
ZEROS = [
    day(
        "2026-08-01",
        {0: (A, tm(100)), 1: (A, tm(104)), 2: (A, tm(98)), 3: (D, tm(60, 0))},
    ),
    day(
        "2026-08-02",
        {0: (A, tm(103)), 1: (A, tm(101)), 2: (A, tm(99)), 3: (D, tm(62, 0))},
    ),
    day(
        "2026-08-03", {0: (A, tm(97)), 1: (A, tm(106)), 2: (A, tm(102)), 3: (D, tm(58))}
    ),
    day(
        "2026-08-04",
        {
            0: (A, tm(105)),
            1: (A, tm(100)),
            2: (A, tm(96)),
            3: (D, tm(61)),
            9: (F, tm(80, 0)),
        },
    ),
]

# 5. Total nul : sous M, tout le support vu du jour retiré W est nul, et sa montée est
#    vue dans deux composantes (P voit 0, Q voit 1) : |L| de W = temps nul, pas
#    référence non identifiée.
TOTAL_NUL = [
    day("2026-09-01", {0: (A, tm(150))}),
    day("2026-09-02", {1: (A, tm(160))}),
    day("2026-09-03", {0: (A, tm(70, 0)), 1: (A, tm(75, 0))}),
]

# 6. Deux jours : un seul contraste.
DEUX_JOURS = [
    day(
        "2026-05-20",
        {
            0: (A, tm(300)),
            1: (A, tm(310)),
            2: (A, tm(295)),
            3: (D, tm(180)),
            4: (D, tm(175)),
            5: (D, tm(190)),
        },
    ),
    day(
        "2026-05-27",
        {
            0: (A, tm(320)),
            1: (A, tm(305)),
            2: (A, tm(316)),
            3: (D, tm(171)),
            4: (D, tm(186)),
            6: (D, tm(200)),
        },
    ),
]

# 7. Multi-sorties : le deuxième jour est un jour multi-sorties (exclu) ; restent deux
# jours.
MULTI = [
    DEUX_JOURS[0],
    day("2026-05-24", {0: (A, tm(280)), 1: (A, tm(300)), 2: (A, tm(290))}, multi=True),
    DEUX_JOURS[1],
]


# 8. Lent : deux groupes de quatre segments (0..3 et 4..7), reliés par deux segments
#    communs (8 : jours 1, 2, 4 ; 9 : jours 2, 3) ; chaque pli reste connexe ; μ₂ de
#    0,73 à 0,86, 45 à 91 itérations des moyennes alternées sous l'écoulé.
def _lent(p: int = 4) -> list[DaySpec]:
    s1, s2 = 2 * p, 2 * p + 1
    d0 = {k: (A, tm(200 + 3 * k)) for k in range(p)}
    d0[s1] = (A, tm(260))
    d1 = {k: (A, tm(215 + 2 * k)) for k in range(p, 2 * p)}
    d1[s1] = (A, tm(272))
    d1[s2] = (A, tm(281))
    d2 = {k: (A, tm(208 + 3 * k)) for k in range(p)}
    d2[s2] = (A, tm(266))
    d3 = {k: (A, tm(221 + 2 * k)) for k in range(p, 2 * p)}
    d3[s1] = (A, tm(268))
    return [
        day("2026-10-01", d0),
        day("2026-10-02", d1),
        day("2026-10-03", d2),
        day("2026-10-04", d3),
    ]


LENT = _lent()

# 10. Zéro retiré : sous M, seul le premier jour a la descente (segment 3) nulle. Son
#     pli : ajustement de descente réussi, P_j = S_j, L calculable, métriques de régime
#     `temps nul` (D5.5) ; les deux autres plis : cellule nulle d'apprentissage.
ZERO_RETIRE = [
    day(
        "2026-08-11",
        {0: (A, tm(100)), 1: (A, tm(104)), 2: (A, tm(98)), 3: (D, tm(60, 0))},
    ),
    day(
        "2026-08-12", {0: (A, tm(103)), 1: (A, tm(101)), 2: (A, tm(99)), 3: (D, tm(62))}
    ),
    day(
        "2026-08-13", {0: (A, tm(97)), 1: (A, tm(106)), 2: (A, tm(102)), 3: (D, tm(58))}
    ),
]

# 9. Dégénérés : aucun jour ; un seul jour ; deux jours sans cellule commune.
UN_JOUR = [COMPLET[0]]
DISJOINTS = [day("2026-11-01", {0: (A, tm(100))}), day("2026-11-02", {1: (A, tm(110))})]

# 11. Zéro hors pli : descente 3, 4 ; sous M, la cellule (jour 2, segment 4) est nulle ;
#     le jour 3 ne voit que le segment 3 : la cellule nulle est dans la composante de
#     son pli sans qu'il voie le segment 4 -> descente `temps nul` pour ce pli.
ZERO_HORS_PLI = [
    day(
        "2026-08-21",
        {
            0: (A, tm(100)),
            1: (A, tm(104)),
            2: (A, tm(98)),
            3: (D, tm(60)),
            4: (D, tm(65)),
        },
    ),
    day(
        "2026-08-22",
        {
            0: (A, tm(103)),
            1: (A, tm(101)),
            2: (A, tm(99)),
            3: (D, tm(62)),
            4: (D, tm(66, 0)),
        },
    ),
    day(
        "2026-08-23", {0: (A, tm(97)), 1: (A, tm(106)), 2: (A, tm(102)), 3: (D, tm(58))}
    ),
]

# 12. Deux échecs : dans le pli du jour W (2026-09-14), la montée est vue dans deux
#     composantes (P voit 0, Q voit 1) et, sous M, la descente a une cellule nulle
#     d'apprentissage (Q, segment 5) : le motif de |L| est celui de la montée.
DEUX_ECHECS = [
    day("2026-09-11", {0: (A, tm(150)), 5: (D, tm(90))}),
    day("2026-09-12", {1: (A, tm(160)), 5: (D, tm(95, 0)), 6: (D, tm(97))}),
    day(
        "2026-09-14", {0: (A, tm(155)), 1: (A, tm(158)), 5: (D, tm(92)), 6: (D, tm(99))}
    ),
]

# 13. Nulle non identifiée (révision 1) : dans le pli de W (2026-09-24), la montée est
#     vue dans deux composantes (P voit 0, Q voit 1) et, sous M, celle de P porte une
#     cellule nulle : W reste `référence non identifiée` (l'identification précède la
#     cellule nulle).
NULLE_NON_IDENTIFIEE = [
    day("2026-09-21", {0: (A, tm(150, 0))}),
    day("2026-09-22", {1: (A, tm(160))}),
    day("2026-09-24", {0: (A, tm(155)), 1: (A, tm(158))}),
]

CASES = {
    "Complet": COMPLET,
    "Variantes": VARIANTES,
    "Deux composantes": DEUX_COMPOSANTES,
    "Zéros": ZEROS,
    "Zéro retiré": ZERO_RETIRE,
    "Zéro hors pli": ZERO_HORS_PLI,
    "Deux échecs": DEUX_ECHECS,
    "Total nul": TOTAL_NUL,
    "Nulle non identifiée": NULLE_NON_IDENTIFIEE,
    "Deux jours": DEUX_JOURS,
    "Multi-sorties": MULTI,
    "Lent": LENT,
    "Vide": [],
    "Un jour": UN_JOUR,
    "Disjoints": DISJOINTS,
}

# Données des tests nommés du § 8.1, test 4 (révision 1) : Total nul, non vu : Total
# nul, et W voit en plus le segment 5, en plat, que personne d'autre ne voit ; sous M,
# le total de W est nul sur S_j, pas sur toutes ses cellules.
TOTAL_NUL_NON_VU = [
    *TOTAL_NUL[:2],
    day("2026-09-03", {0: (A, tm(70, 0)), 1: (A, tm(75, 0)), 5: (F, tm(90))}),
]
# Zéros croisés : sous M, les cellules nulles (2026-08-21, 5) et (2026-08-22, 3), de
# dates et d'indices croisés, sont dans la composante du pli du 2026-08-23.
ZEROS_CROISES = [
    day("2026-08-21", {3: (D, tm(60)), 5: (D, tm(65, 0))}),
    day("2026-08-22", {3: (D, tm(62, 0)), 5: (D, tm(66))}),
    day("2026-08-23", {3: (D, tm(58)), 5: (D, tm(64))}),
]
# Jour isolé : Deux jours, et un troisième jour qui ne voit que le segment 7, vu par
# personne d'autre : un seul contraste.
JOUR_ISOLE = [*DEUX_JOURS, day("2026-05-30", {7: (A, tm(250))})]

LENT_LIMITE_MAX_ITERATIONS = 70  # Lent limité : Lent avec max_iterations=70


TOLERANCE = 1e-6
"""Tolérance relative du § 7.0 : ``1e−6·max(1, |x|)``, ``x`` la valeur attendue."""


def close(actual: float | None, expected: float) -> bool:
    """``actual`` égale ``expected`` à la tolérance du § 7.0."""
    return actual is not None and abs(actual - expected) <= TOLERANCE * max(
        1.0, abs(expected)
    )


def plan_cells(
    specs: Sequence[DaySpec], regime: str, *, without: int | None = None
) -> set[tuple[int, int]]:
    """Les cellules ``(u, k)`` de la classe ``regime``, ``u`` le rang du jour dans le
    cas ; le jour de rang ``without`` n'a pas de cellule, les autres gardent leur rang
    (§ 7.1)."""
    return {
        (u, k)
        for u, spec in enumerate(specs)
        if u != without
        for k, (cls, _) in spec.cells.items()
        if cls == regime
    }


def log_cells(
    specs: Sequence[DaySpec], clock: int, regime: str, *, without: int | None = None
) -> dict[tuple[int, int], float]:
    """``(u, k) ↦ math.log(temps sous CLOCKS[clock])`` sur :func:`plan_cells`."""
    return {
        (u, k): math.log(specs[u].cells[k][1][clock])
        for u, k in plan_cells(specs, regime, without=without)
    }
