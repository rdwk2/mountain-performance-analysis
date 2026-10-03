"""Valeurs de l'oracle du § 7.3 du brief M4b-3 — les lignes du brief, recopiées par
script au caractère près (aucune copie à la main), et leur lecteur.

Calculées en conception avant écriture par un oracle à 50 chiffres et par un
prototype flottant, qui concordent (en-tête du brief). Tolérance
``1e−6·max(1, |x|)`` (§ 7.0), portée par :func:`fixtures.repeatability.close` ;
dates, statuts, motifs, effectifs, cellules nulles, contributions, booléens et
nombres d'itérations exacts.

Lecture d'une ligne de pli (§ 7.3) : `` `date` — S s, P p, `L` v `` puis, pour chaque
classe où le jour retiré a au moins une cellule, ``classe : statut, vus s/l``,
``apprentissage d j, n seg., c cell.`` (avec composante), ``μ₂ x``,
``nulles (date, k) …``, ``n it.``, puis, si ``s > 0``, `` `E_R` v, `D_R` v `` et
``(contribue)``. Une classe absente de la ligne a ``left == seen == 0``. Le
tableau : ``F_|L|``, puis ``F_|E_R| ; F_D_R`` par classe, l'effectif entre
parenthèses.

Le lecteur refuse une ligne qu'il ne lit pas en entier, et :func:`render_fold`,
:func:`render_row`, :func:`render_header` réécrivent chaque ligne lue : un test
vérifie l'aller-retour au caractère près.

Utilisées par ``tests/test_backtest_repeatability_values.py``.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from mountain_perf.schemas import RegimeClass, Unavailability

Value = float | Unavailability

CLASS_WORDS: Mapping[str, RegimeClass] = {
    "montée": RegimeClass.ASCENT,
    "plat": RegimeClass.FLAT,
    "descente": RegimeClass.DESCENT,
    "mixte": RegimeClass.MIXED,
}
MOTIF_WORDS: Mapping[str, Unavailability] = {
    "insuf.": Unavailability.INSUFFICIENT_SUPPORT,
    "nul": Unavailability.ZERO_TIME,
    "non identifiée": Unavailability.UNIDENTIFIED_REFERENCE,
    "non-conv.": Unavailability.NON_CONVERGENCE,
    "err.": Unavailability.MODEL_ERROR,
}
FITTED = "ajustée"
CLOCK_LABELS: Mapping[str, int] = {"`E`": 0, "`M θ1`": 1, "`M θ3`": 3, "`(M+U) θ3`": 8}
"""Les quatre horloges du § 7.3 et leur indice dans ``CLOCKS`` (§ 7.0)."""

_DATE = r"\d{4}-\d\d-\d\d"
_FOLD = re.compile(rf"- `({_DATE})` — S (\d+), P (\d+), `L` (.+)")
_FIT = re.compile(
    r"(montée|plat|descente|mixte) : (ajustée|insuf\.|nul|non identifiée|non-conv\.|"
    r"err\.), vus (\d+)/(\d+)"
    r"(?:, apprentissage (\d+) j, (\d+) seg\., (\d+) cell\.)?"
    r"(?:, μ₂ (\d+\.\d+))?"
    rf"(?:, nulles ((?:\({_DATE}, \d+\) ?)+))?"
    r"(?:, (\d+) it\.)?"
)
_SCORE = re.compile(r"`E_R` (.+), `D_R` (.+?)( \(contribue\))?")
_HEADER = re.compile(
    r"Jours éligibles : (.+) ; multi-sorties : (.+) ; un seul contraste : (oui|non)\."
)
_F = re.compile(r"(.+) \((\d+)\)")


@dataclass(frozen=True)
class Fit:
    """Une classe d'une ligne de pli : ``ClassFit`` et ``ClassScore`` attendus ;
    ``log_ratio`` et ``dispersion`` absents (``None``) quand ``seen == 0``."""

    regime: RegimeClass
    motif: Unavailability | None
    seen: int
    left: int
    training: tuple[int, int, int] | None
    contraction: float | None
    zero_cells: tuple[tuple[date, int], ...]
    iterations: int | None
    log_ratio: Value | None
    dispersion: Value | None
    contributes: bool


@dataclass(frozen=True)
class Fold:
    """Une ligne de pli : jour, ``S``, ``P``, ``L`` (valeur signée ou motif), et les
    classes écrites, dans l'ordre de ``RegimeClass``."""

    day: date
    support: int
    predicted: int
    level: Value
    classes: tuple[Fit, ...]


@dataclass(frozen=True)
class Fq:
    """Un ``F`` du tableau : valeur, ou motif ``insufficient_support`` ; effectif."""

    value: float | None
    motif: Unavailability | None
    count: int


@dataclass(frozen=True)
class Row:
    """Une ligne du tableau : ``F_|L|``, puis ``(F_|E_R|, F_D_R)`` des quatre
    classes."""

    level: Fq
    classes: tuple[tuple[Fq, Fq], ...]


@dataclass(frozen=True)
class Case:
    """Les valeurs d'un cas du § 7.3 : jours, multi-sorties, « un seul contraste » ;
    les plis sous ``CLOCKS[0]`` et ``CLOCKS[1]`` ; les ``F`` sous ``CLOCKS[0]``,
    ``[1]``, ``[3]``, ``[8]``."""

    days: tuple[date, ...]
    multi_outing_days: tuple[date, ...]
    single_contrast: bool
    folds: Mapping[int, tuple[Fold, ...]]
    table: Mapping[int, Row]


def _match(pattern: re.Pattern[str], text: str) -> re.Match[str]:
    match = pattern.fullmatch(text)
    if match is None:
        raise ValueError(f"ligne du § 7.3 illisible : {text!r}")
    return match


def _value(token: str) -> Value:
    if re.fullmatch(r"-?\d+\.\d+", token):
        return float(token)
    return MOTIF_WORDS[token]


def _dates(text: str) -> tuple[date, ...]:
    return () if text == "aucun" else tuple(map(date.fromisoformat, text.split(", ")))


def read_fold(line: str) -> Fold:
    """Une ligne de pli du § 7.3."""
    head, *parts = line.split(" ; ")
    match = _match(_FOLD, head)
    fits: list[Fit] = []
    while parts:
        fit = _match(_FIT, parts.pop(0))
        seen = int(fit[3])
        log_ratio: Value | None = None
        dispersion: Value | None = None
        contributes = False
        if seen > 0:
            score = _match(_SCORE, parts.pop(0))
            log_ratio, dispersion = _value(score[1]), _value(score[2])
            contributes = score[3] is not None
        training = None if fit[5] is None else (int(fit[5]), int(fit[6]), int(fit[7]))
        zero_cells = tuple(
            (date.fromisoformat(day), int(k))
            for day, k in re.findall(rf"\(({_DATE}), (\d+)\)", fit[9] or "")
        )
        fits.append(
            Fit(
                CLASS_WORDS[fit[1]],
                None if fit[2] == FITTED else MOTIF_WORDS[fit[2]],
                seen,
                int(fit[4]),
                training,
                None if fit[8] is None else float(fit[8]),
                zero_cells,
                None if fit[10] is None else int(fit[10]),
                log_ratio,
                dispersion,
                contributes,
            )
        )
    return Fold(
        date.fromisoformat(match[1]),
        int(match[2]),
        int(match[3]),
        _value(match[4]),
        tuple(fits),
    )


def _fq(cell: str) -> tuple[str, int]:
    match = _match(_F, cell)
    return match[1], int(match[2])


def _number_or_insufficient(text: str, count: int) -> Fq:
    if text == "insuf.":
        return Fq(None, Unavailability.INSUFFICIENT_SUPPORT, count)
    return Fq(float(text), None, count)


def read_row(line: str) -> tuple[int, Row]:
    """Une ligne du tableau des ``F`` : l'indice de l'horloge dans ``CLOCKS`` et la
    ligne."""
    label, level, *classes = (cell.strip() for cell in line.strip("|").split("|"))
    pairs: list[tuple[Fq, Fq]] = []
    for cell in classes:
        text, count = _fq(cell)
        first, _, second = text.partition(" ; ")
        pairs.append(
            (
                _number_or_insufficient(first, count),
                _number_or_insufficient(second or first, count),
            )
        )
    return CLOCK_LABELS[label], Row(_number_or_insufficient(*_fq(level)), tuple(pairs))


def read_header(line: str) -> tuple[tuple[date, ...], tuple[date, ...], bool]:
    """L'en-tête d'un cas : jours éligibles, jours multi-sorties, un seul
    contraste."""
    match = _match(_HEADER, line)
    return _dates(match[1]), _dates(match[2]), match[3] == "oui"


def read_case(lines: Mapping[str, tuple[str, ...]]) -> Case:
    days, multi, single = read_header(lines["header"][0])
    return Case(
        days,
        multi,
        single,
        {0: tuple(map(read_fold, lines["E"])), 1: tuple(map(read_fold, lines["M1"]))},
        dict(map(read_row, lines["table"])),
    )


# ---------------------------------------------------------------------------
# Réécriture, pour l'aller-retour
# ---------------------------------------------------------------------------

_WORDS = {motif: word for word, motif in MOTIF_WORDS.items()}
_CLASSES = {regime: word for word, regime in CLASS_WORDS.items()}
_CLOCKS = {index: label for label, index in CLOCK_LABELS.items()}


def _text(value: Value | None) -> str:
    if isinstance(value, Unavailability):
        return _WORDS[value]
    assert value is not None
    return "0.0" if value == 0.0 else f"{value:.10f}"


def render_fold(fold: Fold) -> str:
    parts = [
        f"`{fold.day}` — S {fold.support}, P {fold.predicted}, `L` {_text(fold.level)}"
    ]
    for fit in fold.classes:
        motif = FITTED if fit.motif is None else _WORDS[fit.motif]
        fields = [motif, f"vus {fit.seen}/{fit.left}"]
        if fit.training is not None:
            days, segments, cells = fit.training
            fields += [f"apprentissage {days} j", f"{segments} seg.", f"{cells} cell."]
        if fit.contraction is not None:
            fields.append(f"μ₂ {_text(fit.contraction)}")
        if fit.zero_cells:
            cells_text = " ".join(f"({day}, {k})" for day, k in fit.zero_cells)
            fields.append(f"nulles {cells_text}")
        if fit.iterations is not None:
            fields.append(f"{fit.iterations} it.")
        parts.append(f"{_CLASSES[fit.regime]} : " + ", ".join(fields))
        if fit.seen > 0:
            score = f"`E_R` {_text(fit.log_ratio)}, `D_R` {_text(fit.dispersion)}"
            parts.append(score + (" (contribue)" if fit.contributes else ""))
    return "- " + " ; ".join(parts)


def _render_fq(first: Fq, second: Fq | None = None) -> str:
    if first.value is None:
        return f"insuf. ({first.count})"
    if second is None:
        return f"{_text(first.value)} ({first.count})"
    return f"{_text(first.value)} ; {_text(second.value)} ({first.count})"


def render_row(clock: int, row: Row) -> str:
    cells = [_CLOCKS[clock], _render_fq(row.level)]
    cells += [_render_fq(first, second) for first, second in row.classes]
    return "| " + " | ".join(cells) + " |"


def render_header(case: Case) -> str:
    def dates(values: tuple[date, ...]) -> str:
        return ", ".join(map(str, values)) or "aucun"

    contrast = "oui" if case.single_contrast else "non"
    return (
        f"Jours éligibles : {dates(case.days)} ; multi-sorties : "
        f"{dates(case.multi_outing_days)} ; un seul contraste : {contrast}."
    )


ORACLE_LINES: dict[str, dict[str, tuple[str, ...]]] = {
    "Complet": {
        "header": (
            (
                "Jours éligibles : 2026-05-01, 2026-05-08, 2026-05-15 ; multi-sorties "
                ": aucun ; un seul contraste : non."
            ),
        ),
        "E": (
            (
                "- `2026-05-01` — S 9, P 9, `L` 0.0208983389 ; montée : ajustée, vus "
                "3/3, apprentissage 2 j, 3 seg., 6 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0522883396, `D_R` 0.0249229221 (contribue) ; plat : ajustée, vus "
                "2/2, apprentissage 2 j, 2 seg., 4 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "-0.0099505502, `D_R` 0.0078571378 ; descente : ajustée, vus 3/3, "
                "apprentissage 2 j, 3 seg., 6 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0030385694, `D_R` 0.0443362100 (contribue) ; mixte : ajustée, vus "
                "1/1, apprentissage 2 j, 1 seg., 2 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0010369862, `D_R` 0.0"
            ),
            (
                "- `2026-05-08` — S 9, P 9, `L` -0.0206098668 ; montée : ajustée, vus "
                "3/3, apprentissage 2 j, 3 seg., 6 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "-0.0562168441, `D_R` 0.0231413645 (contribue) ; plat : ajustée, vus "
                "2/2, apprentissage 2 j, 2 seg., 4 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "-0.0133309740, `D_R` 0.0932499267 ; descente : ajustée, vus 3/3, "
                "apprentissage 2 j, 3 seg., 6 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "-0.0172624113, `D_R` 0.0555937825 (contribue) ; mixte : ajustée, vus "
                "1/1, apprentissage 2 j, 1 seg., 2 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0919739189, `D_R` 0.0"
            ),
            (
                "- `2026-05-15` — S 9, P 9, `L` -0.0022828287 ; montée : ajustée, vus "
                "3/3, apprentissage 2 j, 3 seg., 6 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0033304282, `D_R` 0.0432935864 (contribue) ; plat : ajustée, vus "
                "2/2, apprentissage 2 j, 2 seg., 4 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0205839025, `D_R` 0.0859186122 ; descente : ajustée, vus 3/3, "
                "apprentissage 2 j, 3 seg., 6 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0120752512, `D_R` 0.0760360543 (contribue) ; mixte : ajustée, vus "
                "1/1, apprentissage 2 j, 1 seg., 2 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "-0.0930109051, `D_R` 0.0"
            ),
        ),
        "M1": (
            (
                "- `2026-05-01` — S 9, P 9, `L` 0.0221953079 ; montée : ajustée, vus "
                "3/3, apprentissage 2 j, 3 seg., 6 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0549408348, `D_R` 0.0260884871 (contribue) ; plat : ajustée, vus "
                "2/2, apprentissage 2 j, 2 seg., 4 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "-0.0107770885, `D_R` 0.0083948786 ; descente : ajustée, vus 3/3, "
                "apprentissage 2 j, 3 seg., 6 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0032025834, `D_R` 0.0483491360 (contribue) ; mixte : ajustée, vus "
                "1/1, apprentissage 2 j, 1 seg., 2 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0009756101, `D_R` 0.0"
            ),
            (
                "- `2026-05-08` — S 9, P 9, `L` -0.0219930506 ; montée : ajustée, vus "
                "3/3, apprentissage 2 j, 3 seg., 6 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "-0.0590633628, `D_R` 0.0244053424 (contribue) ; plat : ajustée, vus "
                "2/2, apprentissage 2 j, 2 seg., 4 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "-0.0142824057, `D_R` 0.0996461428 ; descente : ajustée, vus 3/3, "
                "apprentissage 2 j, 3 seg., 6 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "-0.0188884622, `D_R` 0.0606695551 (contribue) ; mixte : ajustée, vus "
                "1/1, apprentissage 2 j, 1 seg., 2 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0977833918, `D_R` 0.0"
            ),
            (
                "- `2026-05-15` — S 9, P 9, `L` -0.0024713037 ; montée : ajustée, vus "
                "3/3, apprentissage 2 j, 3 seg., 6 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0034629415, `D_R` 0.0455037767 (contribue) ; plat : ajustée, vus "
                "2/2, apprentissage 2 j, 2 seg., 4 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0219753492, `D_R` 0.0918936657 ; descente : ajustée, vus 3/3, "
                "apprentissage 2 j, 3 seg., 6 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0131298877, `D_R` 0.0830458433 (contribue) ; mixte : ajustée, vus "
                "1/1, apprentissage 2 j, 1 seg., 2 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "-0.0987590018, `D_R` 0.0"
            ),
        ),
        "table": (
            (
                "| `E` | 0.0145970115 (3) | 0.0372785373 ; 0.0304526243 (3) | insuf. "
                "(0) | 0.0107920773 ; 0.0586553489 (3) | insuf. (0) |"
            ),
            (
                "| `M θ1` | 0.0155532207 (3) | 0.0391557130 ; 0.0319992020 (3) | "
                "insuf. (0) | 0.0117403111 ; 0.0640215115 (3) | insuf. (0) |"
            ),
            (
                "| `M θ3` | 0.0157596730 (3) | 0.0395540709 ; 0.0323275475 (3) | "
                "insuf. (0) | 0.0119502551 ; 0.0652148014 (3) | insuf. (0) |"
            ),
            (
                "| `(M+U) θ3` | 0.0146873156 (3) | 0.0374581145 ; 0.0306005266 (3) | "
                "insuf. (0) | 0.0108799675 ; 0.0591511320 (3) | insuf. (0) |"
            ),
        ),
    },
    "Variantes": {
        "header": (
            (
                "Jours éligibles : 2026-06-01, 2026-06-03, 2026-06-05, 2026-06-09 ; "
                "multi-sorties : aucun ; un seul contraste : non."
            ),
        ),
        "E": (
            (
                "- `2026-06-01` — S 6, P 6, `L` 0.0197695127 ; montée : ajustée, vus "
                "3/3, apprentissage 3 j, 5 seg., 12 cell., μ₂ 0.2127794312, 12 it. ; "
                "`E_R` 0.0196315733, `D_R` 0.0010550553 (contribue) ; descente : "
                "ajustée, vus 3/3, apprentissage 3 j, 4 seg., 9 cell., μ₂ "
                "0.2959820616, 14 it. ; `E_R` 0.0200024595, `D_R` 0.0097985899 "
                "(contribue)"
            ),
            (
                "- `2026-06-03` — S 7, P 7, `L` -0.0198470761 ; montée : ajustée, vus "
                "4/4, apprentissage 3 j, 5 seg., 11 cell., μ₂ 0.3333333333, 14 it. ; "
                "`E_R` -0.0223176030, `D_R` 0.0112570342 (contribue) ; descente : "
                "ajustée, vus 3/3, apprentissage 3 j, 4 seg., 9 cell., μ₂ "
                "0.2959820616, 13 it. ; `E_R` -0.0140104455, `D_R` 0.0089128681 "
                "(contribue)"
            ),
            (
                "- `2026-06-05` — S 5, P 5, `L` 0.0395124027 ; montée : ajustée, vus "
                "3/3, apprentissage 3 j, 5 seg., 12 cell., μ₂ 0.2127794312, 11 it. ; "
                "`E_R` 0.0394701094, `D_R` 0.0076542707 (contribue) ; descente : "
                "ajustée, vus 2/2, apprentissage 3 j, 4 seg., 10 cell., μ₂ "
                "0.1666666667, 10 it. ; `E_R` 0.0396252340, `D_R` 0.0023947751"
            ),
            (
                "- `2026-06-09` — S 9, P 9, `L` -0.0395535860 ; montée : ajustée, vus "
                "5/5, apprentissage 3 j, 5 seg., 10 cell., μ₂ 0.3333333333, 13 it. ; "
                "`E_R` -0.0368075108, `D_R` 0.0081281006 (contribue) ; plat : insuf., "
                "vus 0/1 ; descente : ajustée, vus 4/4, apprentissage 3 j, 4 seg., 8 "
                "cell., μ₂ 0.3333333333, 15 it. ; `E_R` -0.0455565334, `D_R` "
                "0.0068777572 (contribue)"
            ),
        ),
        "M1": (
            (
                "- `2026-06-01` — S 6, P 6, `L` 0.0210894946 ; montée : ajustée, vus "
                "3/3, apprentissage 3 j, 5 seg., 12 cell., μ₂ 0.2127794312, 12 it. ; "
                "`E_R` 0.0206708362, `D_R` 0.0011570142 (contribue) ; descente : "
                "ajustée, vus 3/3, apprentissage 3 j, 4 seg., 9 cell., μ₂ "
                "0.2959820616, 14 it. ; `E_R` 0.0218226847, `D_R` 0.0107236996 "
                "(contribue)"
            ),
            (
                "- `2026-06-03` — S 7, P 7, `L` -0.0210252395 ; montée : ajustée, vus "
                "4/4, apprentissage 3 j, 5 seg., 11 cell., μ₂ 0.3333333333, 14 it. ; "
                "`E_R` -0.0233801083, `D_R` 0.0118047730 (contribue) ; descente : "
                "ajustée, vus 3/3, apprentissage 3 j, 4 seg., 9 cell., μ₂ "
                "0.2959820616, 13 it. ; `E_R` -0.0152500759, `D_R` 0.0096788884 "
                "(contribue)"
            ),
            (
                "- `2026-06-05` — S 5, P 5, `L` 0.0417391939 ; montée : ajustée, vus "
                "3/3, apprentissage 3 j, 5 seg., 12 cell., μ₂ 0.2127794312, 11 it. ; "
                "`E_R` 0.0412714454, `D_R` 0.0080799261 (contribue) ; descente : "
                "ajustée, vus 2/2, apprentissage 3 j, 4 seg., 10 cell., μ₂ "
                "0.1666666667, 10 it. ; `E_R` 0.0430347999, `D_R` 0.0028278938"
            ),
            (
                "- `2026-06-09` — S 9, P 9, `L` -0.0419430698 ; montée : ajustée, vus "
                "5/5, apprentissage 3 j, 5 seg., 10 cell., μ₂ 0.3333333333, 13 it. ; "
                "`E_R` -0.0385924940, `D_R` 0.0084777562 (contribue) ; plat : insuf., "
                "vus 0/1 ; descente : ajustée, vus 4/4, apprentissage 3 j, 4 seg., 8 "
                "cell., μ₂ 0.3333333333, 15 it. ; `E_R` -0.0495411538, `D_R` "
                "0.0073310284 (contribue)"
            ),
        ),
        "table": (
            (
                "| `E` | 0.0296706444 (4) | 0.0295566991 ; 0.0070236152 (4) | insuf. "
                "(0) | 0.0265231461 ; 0.0085297384 (3) | insuf. (0) |"
            ),
            (
                "| `M θ1` | 0.0314492495 (4) | 0.0309787210 ; 0.0073798674 (4) | "
                "insuf. (0) | 0.0288713048 ; 0.0092445388 (3) | insuf. (0) |"
            ),
            (
                "| `M θ3` | 0.0318309442 (4) | 0.0312797251 ; 0.0074554806 (4) | "
                "insuf. (0) | 0.0293917556 ; 0.0094021387 (3) | insuf. (0) |"
            ),
            (
                "| `(M+U) θ3` | 0.0298393772 (4) | 0.0296929929 ; 0.0070576910 (4) | "
                "insuf. (0) | 0.0267406253 ; 0.0085962002 (3) | insuf. (0) |"
            ),
        ),
    },
    "Deux composantes": {
        "header": (
            (
                "Jours éligibles : 2026-07-01, 2026-07-02, 2026-07-03, 2026-07-04 ; "
                "multi-sorties : aucun ; un seul contraste : non."
            ),
        ),
        "E": (
            (
                "- `2026-07-01` — S 5, P 5, `L` 0.0165476332 ; montée : ajustée, vus "
                "2/2, apprentissage 2 j, 4 seg., 6 cell., μ₂ 0.2500000000, 12 it. ; "
                "`E_R` 0.0070427990, `D_R` 0.0053423275 ; descente : ajustée, vus 3/3,"
                " apprentissage 1 j, 3 seg., 3 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0271755854, `D_R` 0.0029822654 (contribue)"
            ),
            (
                "- `2026-07-02` — S 2, P 2, `L` 0.0218770312 ; montée : ajustée, vus "
                "2/2, apprentissage 2 j, 4 seg., 6 cell., μ₂ 0.2500000000, 12 it. ; "
                "`E_R` 0.0218770312, `D_R` 0.0020623951"
            ),
            "- `2026-07-03` — S 0, P 0, `L` insuf. ; descente : insuf., vus 0/1",
            (
                "- `2026-07-04` — S 7, P 3, `L` non identifiée ; montée : non "
                "identifiée, vus 4/4 ; `E_R` non identifiée, `D_R` non identifiée ; "
                "descente : ajustée, vus 3/3, apprentissage 1 j, 3 seg., 3 cell., μ₂ "
                "0.0, 2 it. ; `E_R` -0.0271755854, `D_R` 0.0029852884 (contribue)"
            ),
        ),
        "M1": (
            (
                "- `2026-07-01` — S 5, P 5, `L` 0.0176729544 ; montée : ajustée, vus "
                "2/2, apprentissage 2 j, 4 seg., 6 cell., μ₂ 0.2500000000, 12 it. ; "
                "`E_R` 0.0073857926, `D_R` 0.0056406773 ; descente : ajustée, vus 3/3,"
                " apprentissage 1 j, 3 seg., 3 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0295879572, `D_R` 0.0031851577 (contribue)"
            ),
            (
                "- `2026-07-02` — S 2, P 2, `L` 0.0229947790 ; montée : ajustée, vus "
                "2/2, apprentissage 2 j, 4 seg., 6 cell., μ₂ 0.2500000000, 12 it. ; "
                "`E_R` 0.0229947790, `D_R` 0.0022782581"
            ),
            "- `2026-07-03` — S 0, P 0, `L` insuf. ; descente : insuf., vus 0/1",
            (
                "- `2026-07-04` — S 7, P 3, `L` non identifiée ; montée : non "
                "identifiée, vus 4/4 ; `E_R` non identifiée, `D_R` non identifiée ; "
                "descente : ajustée, vus 3/3, apprentissage 1 j, 3 seg., 3 cell., μ₂ "
                "0.0, 2 it. ; `E_R` -0.0295879572, `D_R` 0.0031885702 (contribue)"
            ),
        ),
        "table": (
            (
                "| `E` | 0.0192123322 (2) | insuf. (0) | insuf. (0) | 0.0271755854 ; "
                "0.0029837769 (2) | insuf. (0) |"
            ),
            (
                "| `M θ1` | 0.0203338667 (2) | insuf. (0) | insuf. (0) | 0.0295879572 "
                "; 0.0031868640 (2) | insuf. (0) |"
            ),
            (
                "| `M θ3` | 0.0205744139 (2) | insuf. (0) | insuf. (0) | 0.0301227595 "
                "; 0.0032305231 (2) | insuf. (0) |"
            ),
            (
                "| `(M+U) θ3` | 0.0193187817 (2) | insuf. (0) | insuf. (0) | "
                "0.0273989742 ; 0.0030030060 (2) | insuf. (0) |"
            ),
        ),
    },
    "Zéros": {
        "header": (
            (
                "Jours éligibles : 2026-08-01, 2026-08-02, 2026-08-03, 2026-08-04 ; "
                "multi-sorties : aucun ; un seul contraste : non."
            ),
        ),
        "E": (
            (
                "- `2026-08-01` — S 4, P 4, `L` 0.0032763782 ; montée : ajustée, vus "
                "3/3, apprentissage 3 j, 3 seg., 9 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0029058694, `D_R` 0.0132520391 (contribue) ; descente : ajustée, "
                "vus 1/1, apprentissage 3 j, 1 seg., 3 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0051391910, `D_R` 0.0"
            ),
            (
                "- `2026-08-02` — S 4, P 4, `L` -0.0076874963 ; montée : ajustée, vus "
                "3/3, apprentissage 3 j, 3 seg., 9 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "-0.0014820795, `D_R` 0.0161980730 (contribue) ; descente : ajustée, "
                "vus 1/1, apprentissage 3 j, 1 seg., 3 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "-0.0385805727, `D_R` 0.0"
            ),
            (
                "- `2026-08-03` — S 4, P 4, `L` -0.0001328287 ; montée : ajustée, vus "
                "3/3, apprentissage 3 j, 3 seg., 9 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "-0.0100263211, `D_R` 0.0434441029 (contribue) ; descente : ajustée, "
                "vus 1/1, apprentissage 3 j, 1 seg., 3 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0503412599, `D_R` 0.0"
            ),
            (
                "- `2026-08-04` — S 4, P 4, `L` 0.0034367761 ; montée : ajustée, vus "
                "3/3, apprentissage 3 j, 3 seg., 9 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0075082333, `D_R` 0.0386613359 (contribue) ; plat : insuf., vus 0/1"
                " ; descente : ajustée, vus 1/1, apprentissage 3 j, 1 seg., 3 cell., "
                "μ₂ 0.0, 2 it. ; `E_R` -0.0168998782, `D_R` 0.0"
            ),
        ),
        "M1": (
            (
                "- `2026-08-01` — S 4, P 3, `L` nul ; montée : ajustée, vus 3/3, "
                "apprentissage 3 j, 3 seg., 9 cell., μ₂ 0.0, 2 it. ; `E_R` nul, `D_R` "
                "nul ; descente : nul, vus 1/1, apprentissage 3 j, 1 seg., 3 cell., μ₂"
                " 0.0, nulles (2026-08-02, 3) ; `E_R` nul, `D_R` nul"
            ),
            (
                "- `2026-08-02` — S 4, P 3, `L` nul ; montée : ajustée, vus 3/3, "
                "apprentissage 3 j, 3 seg., 9 cell., μ₂ 0.0, 2 it. ; `E_R` nul, `D_R` "
                "nul ; descente : nul, vus 1/1, apprentissage 3 j, 1 seg., 3 cell., μ₂"
                " 0.0, nulles (2026-08-01, 3) ; `E_R` nul, `D_R` nul"
            ),
            (
                "- `2026-08-03` — S 4, P 3, `L` nul ; montée : ajustée, vus 3/3, "
                "apprentissage 3 j, 3 seg., 9 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "-0.0111434229, `D_R` 0.0481506822 (contribue) ; descente : nul, vus "
                "1/1, apprentissage 3 j, 1 seg., 3 cell., μ₂ 0.0, nulles (2026-08-01, "
                "3) (2026-08-02, 3) ; `E_R` nul, `D_R` nul"
            ),
            (
                "- `2026-08-04` — S 4, P 3, `L` nul ; montée : ajustée, vus 3/3, "
                "apprentissage 3 j, 3 seg., 9 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0083098805, `D_R` 0.0429741607 (contribue) ; plat : insuf., vus 0/1"
                " ; descente : nul, vus 1/1, apprentissage 3 j, 1 seg., 3 cell., μ₂ "
                "0.0, nulles (2026-08-01, 3) (2026-08-02, 3) ; `E_R` nul, `D_R` nul"
            ),
        ),
        "table": (
            (
                "| `E` | 0.0036333698 (4) | 0.0054806258 ; 0.0278888877 (4) | insuf. "
                "(0) | insuf. (0) | insuf. (0) |"
            ),
            (
                "| `M θ1` | insuf. (0) | 0.0097266517 ; 0.0455624214 (2) | insuf. (0) "
                "| insuf. (0) | insuf. (0) |"
            ),
            (
                "| `M θ3` | insuf. (0) | 0.0099442863 ; 0.0465859455 (2) | insuf. (0) "
                "| insuf. (0) | insuf. (0) |"
            ),
            (
                "| `(M+U) θ3` | 0.0036733150 (4) | 0.0055352311 ; 0.0281679981 (4) | "
                "insuf. (0) | insuf. (0) | insuf. (0) |"
            ),
        ),
    },
    "Zéro retiré": {
        "header": (
            (
                "Jours éligibles : 2026-08-11, 2026-08-12, 2026-08-13 ; multi-sorties "
                ": aucun ; un seul contraste : non."
            ),
        ),
        "E": (
            (
                "- `2026-08-11` — S 4, P 4, `L` 0.0051806318 ; montée : ajustée, vus "
                "3/3, apprentissage 2 j, 3 seg., 6 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0063164251, `D_R` 0.0122643797 (contribue) ; descente : ajustée, "
                "vus 1/1, apprentissage 2 j, 1 seg., 2 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "-0.0005558644, `D_R` 0.0"
            ),
            (
                "- `2026-08-12` — S 4, P 4, `L` -0.0069960901 ; montée : ajustée, vus "
                "3/3, apprentissage 2 j, 3 seg., 6 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0015295689, `D_R` 0.0308853445 (contribue) ; descente : ajustée, "
                "vus 1/1, apprentissage 2 j, 1 seg., 2 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "-0.0497405987, `D_R` 0.0"
            ),
            (
                "- `2026-08-13` — S 4, P 4, `L` 0.0012897276 ; montée : ajustée, vus "
                "3/3, apprentissage 2 j, 3 seg., 6 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "-0.0083076247, `D_R` 0.0347515108 (contribue) ; descente : ajustée, "
                "vus 1/1, apprentissage 2 j, 1 seg., 2 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0502964631, `D_R` 0.0"
            ),
        ),
        "M1": (
            (
                "- `2026-08-11` — S 4, P 4, `L` 0.1745219475 ; montée : ajustée, vus "
                "3/3, apprentissage 2 j, 3 seg., 6 cell., μ₂ 0.0, 2 it. ; `E_R` nul, "
                "`D_R` nul ; descente : ajustée, vus 1/1, apprentissage 2 j, 1 seg., 2"
                " cell., μ₂ 0.0, 2 it. ; `E_R` nul, `D_R` nul"
            ),
            (
                "- `2026-08-12` — S 4, P 3, `L` nul ; montée : ajustée, vus 3/3, "
                "apprentissage 2 j, 3 seg., 6 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0016828285, `D_R` 0.0342910360 (contribue) ; descente : nul, vus "
                "1/1, apprentissage 2 j, 1 seg., 2 cell., μ₂ 0.0, nulles (2026-08-11, "
                "3) ; `E_R` nul, `D_R` nul"
            ),
            (
                "- `2026-08-13` — S 4, P 3, `L` nul ; montée : ajustée, vus 3/3, "
                "apprentissage 2 j, 3 seg., 6 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "-0.0092274287, `D_R` 0.0385150005 (contribue) ; descente : nul, vus "
                "1/1, apprentissage 2 j, 1 seg., 2 cell., μ₂ 0.0, nulles (2026-08-11, "
                "3) ; `E_R` nul, `D_R` nul"
            ),
        ),
        "table": (
            (
                "| `E` | 0.0044888165 (3) | 0.0053845396 ; 0.0259670783 (3) | insuf. "
                "(0) | insuf. (0) | insuf. (0) |"
            ),
            (
                "| `M θ1` | insuf. (1) | 0.0054551286 ; 0.0364030182 (2) | insuf. (0) "
                "| insuf. (0) | insuf. (0) |"
            ),
            (
                "| `M θ3` | insuf. (1) | 0.0055767912 ; 0.0372160179 (2) | insuf. (0) "
                "| insuf. (0) | insuf. (0) |"
            ),
            (
                "| `(M+U) θ3` | 0.0045375908 (3) | 0.0054372143 ; 0.0262260738 (3) | "
                "insuf. (0) | insuf. (0) | insuf. (0) |"
            ),
        ),
    },
    "Zéro hors pli": {
        "header": (
            (
                "Jours éligibles : 2026-08-21, 2026-08-22, 2026-08-23 ; multi-sorties "
                ": aucun ; un seul contraste : non."
            ),
        ),
        "E": (
            (
                "- `2026-08-21` — S 5, P 5, `L` 0.0016747771 ; montée : ajustée, vus "
                "3/3, apprentissage 2 j, 3 seg., 6 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0063164251, `D_R` 0.0122643797 (contribue) ; descente : ajustée, "
                "vus 2/2, apprentissage 2 j, 2 seg., 3 cell., μ₂ 0.2500000000, 13 it. "
                "; `E_R` -0.0096291606, `D_R` 0.0087486905"
            ),
            (
                "- `2026-08-22` — S 5, P 5, `L` -0.0108174067 ; montée : ajustée, vus "
                "3/3, apprentissage 2 j, 3 seg., 6 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0015295689, `D_R` 0.0308853445 (contribue) ; descente : ajustée, "
                "vus 2/2, apprentissage 2 j, 2 seg., 3 cell., μ₂ 0.2500000000, 12 it. "
                "; `E_R` -0.0406673025, `D_R` 0.0087514216"
            ),
            (
                "- `2026-08-23` — S 4, P 4, `L` 0.0012897276 ; montée : ajustée, vus "
                "3/3, apprentissage 2 j, 3 seg., 6 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "-0.0083076247, `D_R` 0.0347515108 (contribue) ; descente : ajustée, "
                "vus 1/1, apprentissage 2 j, 2 seg., 4 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0502964631, `D_R` 0.0"
            ),
        ),
        "M1": (
            (
                "- `2026-08-21` — S 5, P 3, `L` nul ; montée : ajustée, vus 3/3, "
                "apprentissage 2 j, 3 seg., 6 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0069760733, `D_R` 0.0136313844 (contribue) ; descente : nul, vus "
                "2/2, apprentissage 2 j, 2 seg., 3 cell., μ₂ 0.2500000000, nulles "
                "(2026-08-22, 4) ; `E_R` nul, `D_R` nul"
            ),
            (
                "- `2026-08-22` — S 5, P 5, `L` 0.1466634717 ; montée : ajustée, vus "
                "3/3, apprentissage 2 j, 3 seg., 6 cell., μ₂ 0.0, 2 it. ; `E_R` nul, "
                "`D_R` nul ; descente : ajustée, vus 2/2, apprentissage 2 j, 2 seg., 3"
                " cell., μ₂ 0.2500000000, 12 it. ; `E_R` nul, `D_R` nul"
            ),
            (
                "- `2026-08-23` — S 4, P 3, `L` nul ; montée : ajustée, vus 3/3, "
                "apprentissage 2 j, 3 seg., 6 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "-0.0092274287, `D_R` 0.0385150005 (contribue) ; descente : nul, vus "
                "1/1, apprentissage 2 j, 2 seg., 4 cell., μ₂ 0.0, nulles (2026-08-22, "
                "4) ; `E_R` nul, `D_R` nul"
            ),
        ),
        "table": (
            (
                "| `E` | 0.0045939704 (3) | 0.0053845396 ; 0.0259670783 (3) | insuf. "
                "(0) | insuf. (0) | insuf. (0) |"
            ),
            (
                "| `M θ1` | insuf. (1) | 0.0081017510 ; 0.0260731924 (2) | insuf. (0) "
                "| insuf. (0) | insuf. (0) |"
            ),
            (
                "| `M θ3` | insuf. (1) | 0.0082806137 ; 0.0266549078 (2) | insuf. (0) "
                "| insuf. (0) | insuf. (0) |"
            ),
            (
                "| `(M+U) θ3` | 0.0046459389 (3) | 0.0054372143 ; 0.0262260738 (3) | "
                "insuf. (0) | insuf. (0) | insuf. (0) |"
            ),
        ),
    },
    "Deux échecs": {
        "header": (
            (
                "Jours éligibles : 2026-09-11, 2026-09-12, 2026-09-14 ; multi-sorties "
                ": aucun ; un seul contraste : non."
            ),
        ),
        "E": (
            (
                "- `2026-09-11` — S 2, P 2, `L` 0.0386832884 ; montée : ajustée, vus "
                "1/1, apprentissage 2 j, 2 seg., 3 cell., μ₂ 0.2500000000, 11 it. ; "
                "`E_R` 0.0390792139, `D_R` 0.0 ; descente : ajustée, vus 1/1, "
                "apprentissage 2 j, 2 seg., 4 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0380230640, `D_R` 0.0"
            ),
            (
                "- `2026-09-12` — S 3, P 3, `L` -0.0219922578 ; montée : ajustée, vus "
                "1/1, apprentissage 2 j, 2 seg., 3 cell., μ₂ 0.2500000000, 12 it. ; "
                "`E_R` -0.0289736936, `D_R` 0.0 ; descente : ajustée, vus 2/2, "
                "apprentissage 2 j, 2 seg., 3 cell., μ₂ 0.2500000000, 12 it. ; `E_R` "
                "-0.0162113973, `D_R` 0.0262421579"
            ),
            (
                "- `2026-09-14` — S 4, P 2, `L` non identifiée ; montée : non "
                "identifiée, vus 2/2 ; `E_R` non identifiée, `D_R` non identifiée ; "
                "descente : ajustée, vus 2/2, apprentissage 2 j, 2 seg., 3 cell., μ₂ "
                "0.2500000000, 12 it. ; `E_R` -0.0218116667, `D_R` 0.0262259520"
            ),
        ),
        "M1": (
            (
                "- `2026-09-11` — S 2, P 1, `L` nul ; montée : ajustée, vus 1/1, "
                "apprentissage 2 j, 2 seg., 3 cell., μ₂ 0.2500000000, 11 it. ; `E_R` "
                "0.0418028300, `D_R` 0.0 ; descente : nul, vus 1/1, apprentissage 2 j,"
                " 2 seg., 4 cell., μ₂ 0.0, nulles (2026-09-12, 5) ; `E_R` nul, `D_R` "
                "nul"
            ),
            (
                "- `2026-09-12` — S 3, P 3, `L` 0.2823757772 ; montée : ajustée, vus "
                "1/1, apprentissage 2 j, 2 seg., 3 cell., μ₂ 0.2500000000, 12 it. ; "
                "`E_R` nul, `D_R` nul ; descente : ajustée, vus 2/2, apprentissage 2 "
                "j, 2 seg., 3 cell., μ₂ 0.2500000000, 12 it. ; `E_R` nul, `D_R` nul"
            ),
            (
                "- `2026-09-14` — S 4, P 0, `L` non identifiée ; montée : non "
                "identifiée, vus 2/2 ; `E_R` non identifiée, `D_R` non identifiée ; "
                "descente : nul, vus 2/2, apprentissage 2 j, 2 seg., 3 cell., μ₂ "
                "0.2500000000, nulles (2026-09-12, 5) ; `E_R` nul, `D_R` nul"
            ),
        ),
        "table": (
            (
                "| `E` | 0.0303377731 (2) | insuf. (0) | insuf. (0) | insuf. (0) | "
                "insuf. (0) |"
            ),
            (
                "| `M θ1` | insuf. (1) | insuf. (0) | insuf. (0) | insuf. (0) | insuf."
                " (0) |"
            ),
            (
                "| `M θ3` | insuf. (1) | insuf. (0) | insuf. (0) | insuf. (0) | insuf."
                " (0) |"
            ),
            (
                "| `(M+U) θ3` | 0.0305942951 (2) | insuf. (0) | insuf. (0) | insuf. "
                "(0) | insuf. (0) |"
            ),
        ),
    },
    "Total nul": {
        "header": (
            (
                "Jours éligibles : 2026-09-01, 2026-09-02, 2026-09-03 ; multi-sorties "
                ": aucun ; un seul contraste : non."
            ),
        ),
        "E": (
            (
                "- `2026-09-01` — S 1, P 1, `L` -0.3832972012 ; montée : ajustée, vus "
                "1/1, apprentissage 2 j, 2 seg., 3 cell., μ₂ 0.2500000000, 14 it. ; "
                "`E_R` -0.3832972012, `D_R` 0.0"
            ),
            (
                "- `2026-09-02` — S 1, P 1, `L` -0.3766156757 ; montée : ajustée, vus "
                "1/1, apprentissage 2 j, 2 seg., 3 cell., μ₂ 0.2500000000, 14 it. ; "
                "`E_R` -0.3766156757, `D_R` 0.0"
            ),
            (
                "- `2026-09-03` — S 2, P 0, `L` non identifiée ; montée : non "
                "identifiée, vus 2/2 ; `E_R` non identifiée, `D_R` non identifiée"
            ),
        ),
        "M1": (
            (
                "- `2026-09-01` — S 1, P 0, `L` nul ; montée : nul, vus 1/1, "
                "apprentissage 2 j, 2 seg., 3 cell., μ₂ 0.2500000000, nulles "
                "(2026-09-03, 0) (2026-09-03, 1) ; `E_R` nul, `D_R` nul"
            ),
            (
                "- `2026-09-02` — S 1, P 0, `L` nul ; montée : nul, vus 1/1, "
                "apprentissage 2 j, 2 seg., 3 cell., μ₂ 0.2500000000, nulles "
                "(2026-09-03, 0) (2026-09-03, 1) ; `E_R` nul, `D_R` nul"
            ),
            (
                "- `2026-09-03` — S 2, P 0, `L` nul ; montée : non identifiée, vus 2/2"
                " ; `E_R` nul, `D_R` nul"
            ),
        ),
        "table": (
            (
                "| `E` | 0.3799564384 (2) | insuf. (0) | insuf. (0) | insuf. (0) | "
                "insuf. (0) |"
            ),
            (
                "| `M θ1` | insuf. (0) | insuf. (0) | insuf. (0) | insuf. (0) | insuf."
                " (0) |"
            ),
            (
                "| `M θ3` | insuf. (0) | insuf. (0) | insuf. (0) | insuf. (0) | insuf."
                " (0) |"
            ),
            (
                "| `(M+U) θ3` | 0.3836697276 (2) | insuf. (0) | insuf. (0) | insuf. "
                "(0) | insuf. (0) |"
            ),
        ),
    },
    "Nulle non identifiée": {
        "header": (
            (
                "Jours éligibles : 2026-09-21, 2026-09-22, 2026-09-24 ; multi-sorties "
                ": aucun ; un seul contraste : non."
            ),
        ),
        "E": (
            (
                "- `2026-09-21` — S 1, P 1, `L` 0.0390792139 ; montée : ajustée, vus "
                "1/1, apprentissage 2 j, 2 seg., 3 cell., μ₂ 0.2500000000, 11 it. ; "
                "`E_R` 0.0390792139, `D_R` 0.0"
            ),
            (
                "- `2026-09-22` — S 1, P 1, `L` -0.0289736936 ; montée : ajustée, vus "
                "1/1, apprentissage 2 j, 2 seg., 3 cell., μ₂ 0.2500000000, 12 it. ; "
                "`E_R` -0.0289736936, `D_R` 0.0"
            ),
            (
                "- `2026-09-24` — S 2, P 0, `L` non identifiée ; montée : non "
                "identifiée, vus 2/2 ; `E_R` non identifiée, `D_R` non identifiée"
            ),
        ),
        "M1": (
            (
                "- `2026-09-21` — S 1, P 1, `L` nul ; montée : ajustée, vus 1/1, "
                "apprentissage 2 j, 2 seg., 3 cell., μ₂ 0.2500000000, 11 it. ; `E_R` "
                "nul, `D_R` nul"
            ),
            (
                "- `2026-09-22` — S 1, P 0, `L` nul ; montée : nul, vus 1/1, "
                "apprentissage 2 j, 2 seg., 3 cell., μ₂ 0.2500000000, nulles "
                "(2026-09-21, 0) ; `E_R` nul, `D_R` nul"
            ),
            (
                "- `2026-09-24` — S 2, P 0, `L` non identifiée ; montée : non "
                "identifiée, vus 2/2 ; `E_R` non identifiée, `D_R` non identifiée"
            ),
        ),
        "table": (
            (
                "| `E` | 0.0340264538 (2) | insuf. (0) | insuf. (0) | insuf. (0) | "
                "insuf. (0) |"
            ),
            (
                "| `M θ1` | insuf. (0) | insuf. (0) | insuf. (0) | insuf. (0) | insuf."
                " (0) |"
            ),
            (
                "| `M θ3` | insuf. (0) | insuf. (0) | insuf. (0) | insuf. (0) | insuf."
                " (0) |"
            ),
            (
                "| `(M+U) θ3` | 0.0342485200 (2) | insuf. (0) | insuf. (0) | insuf. "
                "(0) | insuf. (0) |"
            ),
        ),
    },
    "Deux jours": {
        "header": (
            (
                "Jours éligibles : 2026-05-20, 2026-05-27 ; multi-sorties : aucun ; un"
                " seul contraste : oui."
            ),
        ),
        "E": (
            (
                "- `2026-05-20` — S 5, P 5, `L` 0.0297128973 ; montée : ajustée, vus "
                "3/3, apprentissage 1 j, 3 seg., 3 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0390081959, `D_R` 0.0370952540 (contribue) ; descente : ajustée, "
                "vus 2/3, apprentissage 1 j, 3 seg., 3 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0056179923, `D_R` 0.0561380434"
            ),
            (
                "- `2026-05-27` — S 5, P 5, `L` -0.0297128973 ; montée : ajustée, vus "
                "3/3, apprentissage 1 j, 3 seg., 3 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "-0.0390081959, `D_R` 0.0365891601 (contribue) ; descente : ajustée, "
                "vus 2/3, apprentissage 1 j, 3 seg., 3 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "-0.0056179923, `D_R` 0.0560940437"
            ),
        ),
        "M1": (
            (
                "- `2026-05-20` — S 5, P 5, `L` 0.0309219103 ; montée : ajustée, vus "
                "3/3, apprentissage 1 j, 3 seg., 3 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0403190109, `D_R` 0.0383511357 (contribue) ; descente : ajustée, "
                "vus 2/3, apprentissage 1 j, 3 seg., 3 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0059523985, `D_R` 0.0594794335"
            ),
            (
                "- `2026-05-27` — S 5, P 5, `L` -0.0309219103 ; montée : ajustée, vus "
                "3/3, apprentissage 1 j, 3 seg., 3 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "-0.0403190109, `D_R` 0.0378105110 (contribue) ; descente : ajustée, "
                "vus 2/3, apprentissage 1 j, 3 seg., 3 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "-0.0059523985, `D_R` 0.0594271197"
            ),
        ),
        "table": (
            (
                "| `E` | 0.0297128973 (2) | 0.0390081959 ; 0.0368422071 (2) | insuf. "
                "(0) | insuf. (0) | insuf. (0) |"
            ),
            (
                "| `M θ1` | 0.0309219103 (2) | 0.0403190109 ; 0.0380808234 (2) | "
                "insuf. (0) | insuf. (0) | insuf. (0) |"
            ),
            (
                "| `M θ3` | 0.0311756175 (2) | 0.0405918184 ; 0.0383386142 (2) | "
                "insuf. (0) | insuf. (0) | insuf. (0) |"
            ),
            (
                "| `(M+U) θ3` | 0.0298295272 (2) | 0.0391354289 ; 0.0369624290 (2) | "
                "insuf. (0) | insuf. (0) | insuf. (0) |"
            ),
        ),
    },
    "Multi-sorties": {
        "header": (
            (
                "Jours éligibles : 2026-05-20, 2026-05-27 ; multi-sorties : 2026-05-24"
                " ; un seul contraste : oui."
            ),
        ),
        "E": (
            (
                "- `2026-05-20` — S 5, P 5, `L` 0.0297128973 ; montée : ajustée, vus "
                "3/3, apprentissage 1 j, 3 seg., 3 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0390081959, `D_R` 0.0370952540 (contribue) ; descente : ajustée, "
                "vus 2/3, apprentissage 1 j, 3 seg., 3 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0056179923, `D_R` 0.0561380434"
            ),
            (
                "- `2026-05-27` — S 5, P 5, `L` -0.0297128973 ; montée : ajustée, vus "
                "3/3, apprentissage 1 j, 3 seg., 3 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "-0.0390081959, `D_R` 0.0365891601 (contribue) ; descente : ajustée, "
                "vus 2/3, apprentissage 1 j, 3 seg., 3 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "-0.0056179923, `D_R` 0.0560940437"
            ),
        ),
        "M1": (
            (
                "- `2026-05-20` — S 5, P 5, `L` 0.0309219103 ; montée : ajustée, vus "
                "3/3, apprentissage 1 j, 3 seg., 3 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0403190109, `D_R` 0.0383511357 (contribue) ; descente : ajustée, "
                "vus 2/3, apprentissage 1 j, 3 seg., 3 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "0.0059523985, `D_R` 0.0594794335"
            ),
            (
                "- `2026-05-27` — S 5, P 5, `L` -0.0309219103 ; montée : ajustée, vus "
                "3/3, apprentissage 1 j, 3 seg., 3 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "-0.0403190109, `D_R` 0.0378105110 (contribue) ; descente : ajustée, "
                "vus 2/3, apprentissage 1 j, 3 seg., 3 cell., μ₂ 0.0, 2 it. ; `E_R` "
                "-0.0059523985, `D_R` 0.0594271197"
            ),
        ),
        "table": (
            (
                "| `E` | 0.0297128973 (2) | 0.0390081959 ; 0.0368422071 (2) | insuf. "
                "(0) | insuf. (0) | insuf. (0) |"
            ),
            (
                "| `M θ1` | 0.0309219103 (2) | 0.0403190109 ; 0.0380808234 (2) | "
                "insuf. (0) | insuf. (0) | insuf. (0) |"
            ),
            (
                "| `M θ3` | 0.0311756175 (2) | 0.0405918184 ; 0.0383386142 (2) | "
                "insuf. (0) | insuf. (0) | insuf. (0) |"
            ),
            (
                "| `(M+U) θ3` | 0.0298295272 (2) | 0.0391354289 ; 0.0369624290 (2) | "
                "insuf. (0) | insuf. (0) | insuf. (0) |"
            ),
        ),
    },
    "Lent": {
        "header": (
            (
                "Jours éligibles : 2026-10-01, 2026-10-02, 2026-10-03, 2026-10-04 ; "
                "multi-sorties : aucun ; un seul contraste : non."
            ),
        ),
        "E": (
            (
                "- `2026-10-01` — S 5, P 5, `L` 0.0657618345 ; montée : ajustée, vus "
                "5/5, apprentissage 3 j, 10 seg., 16 cell., μ₂ 0.8612987560, 91 it. ; "
                "`E_R` 0.0657618345, `D_R` 0.0234212365 (contribue)"
            ),
            (
                "- `2026-10-02` — S 6, P 6, `L` -0.0054480742 ; montée : ajustée, vus "
                "6/6, apprentissage 3 j, 10 seg., 15 cell., μ₂ 0.8605551275, 75 it. ; "
                "`E_R` -0.0054480742, `D_R` 0.0306888472 (contribue)"
            ),
            (
                "- `2026-10-03` — S 5, P 5, `L` 0.0025284184 ; montée : ajustée, vus "
                "5/5, apprentissage 3 j, 10 seg., 16 cell., μ₂ 0.8061960132, 62 it. ; "
                "`E_R` 0.0025284184, `D_R` 0.0236259811 (contribue)"
            ),
            (
                "- `2026-10-04` — S 5, P 5, `L` -0.0477065012 ; montée : ajustée, vus "
                "5/5, apprentissage 3 j, 10 seg., 16 cell., μ₂ 0.7333333333, 45 it. ; "
                "`E_R` -0.0477065012, `D_R` 0.0181114084 (contribue)"
            ),
        ),
        "M1": (
            (
                "- `2026-10-01` — S 5, P 5, `L` 0.0685537614 ; montée : ajustée, vus "
                "5/5, apprentissage 3 j, 10 seg., 16 cell., μ₂ 0.8612987560, 91 it. ; "
                "`E_R` 0.0685537614, `D_R` 0.0246264185 (contribue)"
            ),
            (
                "- `2026-10-02` — S 6, P 6, `L` -0.0055914641 ; montée : ajustée, vus "
                "6/6, apprentissage 3 j, 10 seg., 15 cell., μ₂ 0.8605551275, 75 it. ; "
                "`E_R` -0.0055914641, `D_R` 0.0321214343 (contribue)"
            ),
            (
                "- `2026-10-03` — S 5, P 5, `L` 0.0024453785 ; montée : ajustée, vus "
                "5/5, apprentissage 3 j, 10 seg., 16 cell., μ₂ 0.8061960132, 62 it. ; "
                "`E_R` 0.0024453785, `D_R` 0.0248459212 (contribue)"
            ),
            (
                "- `2026-10-04` — S 5, P 5, `L` -0.0495983475 ; montée : ajustée, vus "
                "5/5, apprentissage 3 j, 10 seg., 16 cell., μ₂ 0.7333333333, 46 it. ; "
                "`E_R` -0.0495983475, `D_R` 0.0189739960 (contribue)"
            ),
        ),
        "table": (
            (
                "| `E` | 0.0303612071 (4) | 0.0303612071 ; 0.0239618683 (4) | insuf. "
                "(0) | insuf. (0) | insuf. (0) |"
            ),
            (
                "| `M θ1` | 0.0315472379 (4) | 0.0315472379 ; 0.0251419425 (4) | "
                "insuf. (0) | insuf. (0) | insuf. (0) |"
            ),
            (
                "| `M θ3` | 0.0317956639 (4) | 0.0317956639 ; 0.0253920691 (4) | "
                "insuf. (0) | insuf. (0) | insuf. (0) |"
            ),
            (
                "| `(M+U) θ3` | 0.0304757777 (4) | 0.0304757777 ; 0.0240748591 (4) | "
                "insuf. (0) | insuf. (0) | insuf. (0) |"
            ),
        ),
    },
    "Vide": {
        "header": (
            (
                "Jours éligibles : aucun ; multi-sorties : aucun ; un seul contraste :"
                " non."
            ),
        ),
        "E": (),
        "M1": (),
        "table": (
            (
                "| `E` | insuf. (0) | insuf. (0) | insuf. (0) | insuf. (0) | insuf. "
                "(0) |"
            ),
            (
                "| `M θ1` | insuf. (0) | insuf. (0) | insuf. (0) | insuf. (0) | insuf."
                " (0) |"
            ),
            (
                "| `M θ3` | insuf. (0) | insuf. (0) | insuf. (0) | insuf. (0) | insuf."
                " (0) |"
            ),
            (
                "| `(M+U) θ3` | insuf. (0) | insuf. (0) | insuf. (0) | insuf. (0) | "
                "insuf. (0) |"
            ),
        ),
    },
    "Un jour": {
        "header": (
            (
                "Jours éligibles : 2026-05-01 ; multi-sorties : aucun ; un seul "
                "contraste : non."
            ),
        ),
        "E": (
            (
                "- `2026-05-01` — S 0, P 0, `L` insuf. ; montée : insuf., vus 0/3 ; "
                "plat : insuf., vus 0/2 ; descente : insuf., vus 0/3 ; mixte : insuf.,"
                " vus 0/1"
            ),
        ),
        "M1": (
            (
                "- `2026-05-01` — S 0, P 0, `L` insuf. ; montée : insuf., vus 0/3 ; "
                "plat : insuf., vus 0/2 ; descente : insuf., vus 0/3 ; mixte : insuf.,"
                " vus 0/1"
            ),
        ),
        "table": (
            (
                "| `E` | insuf. (0) | insuf. (0) | insuf. (0) | insuf. (0) | insuf. "
                "(0) |"
            ),
            (
                "| `M θ1` | insuf. (0) | insuf. (0) | insuf. (0) | insuf. (0) | insuf."
                " (0) |"
            ),
            (
                "| `M θ3` | insuf. (0) | insuf. (0) | insuf. (0) | insuf. (0) | insuf."
                " (0) |"
            ),
            (
                "| `(M+U) θ3` | insuf. (0) | insuf. (0) | insuf. (0) | insuf. (0) | "
                "insuf. (0) |"
            ),
        ),
    },
    "Disjoints": {
        "header": (
            (
                "Jours éligibles : 2026-11-01, 2026-11-02 ; multi-sorties : aucun ; un"
                " seul contraste : non."
            ),
        ),
        "E": (
            "- `2026-11-01` — S 0, P 0, `L` insuf. ; montée : insuf., vus 0/1",
            "- `2026-11-02` — S 0, P 0, `L` insuf. ; montée : insuf., vus 0/1",
        ),
        "M1": (
            "- `2026-11-01` — S 0, P 0, `L` insuf. ; montée : insuf., vus 0/1",
            "- `2026-11-02` — S 0, P 0, `L` insuf. ; montée : insuf., vus 0/1",
        ),
        "table": (
            (
                "| `E` | insuf. (0) | insuf. (0) | insuf. (0) | insuf. (0) | insuf. "
                "(0) |"
            ),
            (
                "| `M θ1` | insuf. (0) | insuf. (0) | insuf. (0) | insuf. (0) | insuf."
                " (0) |"
            ),
            (
                "| `M θ3` | insuf. (0) | insuf. (0) | insuf. (0) | insuf. (0) | insuf."
                " (0) |"
            ),
            (
                "| `(M+U) θ3` | insuf. (0) | insuf. (0) | insuf. (0) | insuf. (0) | "
                "insuf. (0) |"
            ),
        ),
    },
    "Lent limité": {
        "header": (
            (
                "Jours éligibles : 2026-10-01, 2026-10-02, 2026-10-03, 2026-10-04 ; "
                "multi-sorties : aucun ; un seul contraste : non."
            ),
        ),
        "E": (
            (
                "- `2026-10-01` — S 5, P 0, `L` non-conv. ; montée : non-conv., vus "
                "5/5, apprentissage 3 j, 10 seg., 16 cell., μ₂ 0.8612987560, 70 it. ; "
                "`E_R` non-conv., `D_R` non-conv."
            ),
            (
                "- `2026-10-02` — S 6, P 0, `L` non-conv. ; montée : non-conv., vus "
                "6/6, apprentissage 3 j, 10 seg., 15 cell., μ₂ 0.8605551275, 70 it. ; "
                "`E_R` non-conv., `D_R` non-conv."
            ),
            (
                "- `2026-10-03` — S 5, P 5, `L` 0.0025284184 ; montée : ajustée, vus "
                "5/5, apprentissage 3 j, 10 seg., 16 cell., μ₂ 0.8061960132, 62 it. ; "
                "`E_R` 0.0025284184, `D_R` 0.0236259811 (contribue)"
            ),
            (
                "- `2026-10-04` — S 5, P 5, `L` -0.0477065012 ; montée : ajustée, vus "
                "5/5, apprentissage 3 j, 10 seg., 16 cell., μ₂ 0.7333333333, 45 it. ; "
                "`E_R` -0.0477065012, `D_R` 0.0181114084 (contribue)"
            ),
        ),
        "M1": (
            (
                "- `2026-10-01` — S 5, P 0, `L` non-conv. ; montée : non-conv., vus "
                "5/5, apprentissage 3 j, 10 seg., 16 cell., μ₂ 0.8612987560, 70 it. ; "
                "`E_R` non-conv., `D_R` non-conv."
            ),
            (
                "- `2026-10-02` — S 6, P 0, `L` non-conv. ; montée : non-conv., vus "
                "6/6, apprentissage 3 j, 10 seg., 15 cell., μ₂ 0.8605551275, 70 it. ; "
                "`E_R` non-conv., `D_R` non-conv."
            ),
            (
                "- `2026-10-03` — S 5, P 5, `L` 0.0024453785 ; montée : ajustée, vus "
                "5/5, apprentissage 3 j, 10 seg., 16 cell., μ₂ 0.8061960132, 62 it. ; "
                "`E_R` 0.0024453785, `D_R` 0.0248459212 (contribue)"
            ),
            (
                "- `2026-10-04` — S 5, P 5, `L` -0.0495983475 ; montée : ajustée, vus "
                "5/5, apprentissage 3 j, 10 seg., 16 cell., μ₂ 0.7333333333, 46 it. ; "
                "`E_R` -0.0495983475, `D_R` 0.0189739960 (contribue)"
            ),
        ),
        "table": (
            (
                "| `E` | 0.0251174598 (2) | 0.0251174598 ; 0.0208686948 (2) | insuf. "
                "(0) | insuf. (0) | insuf. (0) |"
            ),
            (
                "| `M θ1` | 0.0260218630 (2) | 0.0260218630 ; 0.0219099586 (2) | "
                "insuf. (0) | insuf. (0) | insuf. (0) |"
            ),
            (
                "| `M θ3` | 0.0262103810 (2) | 0.0262103810 ; 0.0221307983 (2) | "
                "insuf. (0) | insuf. (0) | insuf. (0) |"
            ),
            (
                "| `(M+U) θ3` | 0.0252051383 (2) | 0.0252051383 ; 0.0209683486 (2) | "
                "insuf. (0) | insuf. (0) | insuf. (0) |"
            ),
        ),
    },
}
"""Les lignes du § 7.3, par cas : l'en-tête, les plis sous ``E`` et sous
``M θ1``, le tableau des ``F`` — recopiées par script, au caractère près."""

VALUES: dict[str, Case] = {
    name: read_case(lines) for name, lines in ORACLE_LINES.items()
}
"""Les seize cas du § 7.3, lus."""
