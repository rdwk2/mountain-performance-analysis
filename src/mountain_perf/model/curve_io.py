"""Lecture d'un fichier de courbe : CSV de tranches et compagnon de provenance.

La courbe est **un fichier, jamais une constante** (``docs/decisions/0009``). Le CSV
porte le format de l'ancien projet — ``grade_pct,kmh,hr,vam_mh,time_min``, tranches
centrées sur leur étiquette, pente en pourcentage, vitesse horizontale en km/h — et
un fichier ``<stem>.meta.json`` **obligatoire**, à côté, porte la provenance que le
CSV ne contient pas.

Les conversions se font ici, à la frontière, une seule fois : ``grade_pct / 100``
et ``kmh_to_ms``. Au-delà de ce module, tout est en fraction et en m/s.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any, Final

from mountain_perf.schemas import (
    GRADE_RANGE,
    CurveProvenance,
    PaceCurve,
    ParameterDisplay,
    ParameterSet,
    ParameterSpec,
    SourceRef,
    Sport,
)
from mountain_perf.units import kmh_to_ms

CURVE_PARAMETER_SPECS: tuple[ParameterSpec, ...] = (
    ParameterSpec(
        name="curve_min_support_min",
        unit="min",
        default=10.0,
        minimum=0.0,
        maximum=1440.0,
        description=(
            "Données minimales par tranche de pente pour la retenir ; "
            "0 = aucun filtre de support."
        ),
    ),
)
"""Paramètres de la lecture de courbe.

La borne haute de 1 440 minutes — vingt-quatre heures de données dans une seule
tranche — n'a pas de sens physique atteignable ; elle existe parce que
``ParameterSpec`` exige un maximum fini, et elle transforme une faute de frappe en
erreur de contrat plutôt qu'en courbe vide.
"""

CURVE_PARAMETER_DISPLAYS: tuple[ParameterDisplay, ...] = (
    ParameterDisplay(
        "curve_min_support_min", "Support minimal d'une tranche (min)", 0, 60, 1
    ),
)
"""Plages d'affichage des paramètres de la lecture de courbe dans l'interface (M5) ;
jamais stockées."""

CURVE_HEADER: Final = ("grade_pct", "kmh", "hr", "vam_mh", "time_min")
"""En-tête du CSV de l'ancien projet. ``hr`` et ``vam_mh`` sont lues et validées, puis
ignorées : elles ne rentrent dans aucun contrat."""

EXTENDED_COLUMNS: Final = ("kmh_elapsed", "activities", "shape_iqr")
"""Les colonnes que l'estimation (M6b) ajoute à :data:`CURVE_HEADER`, dans cet ordre :
la vitesse écoulée de la tranche (km/h), son nombre d'activités, sa forme (écart
interquartile d'un logarithme, sans unité ; vide sous le seuil d'activités). Dans un
fichier à l'en-tête étendu, ``hr`` peut être vide (aucune FC dans la tranche) et
``sample_count`` reçoit le nombre d'activités."""

EXTENDED_HEADER: Final = CURVE_HEADER + EXTENDED_COLUMNS
"""En-tête du CSV écrit par l'estimation (M6b)."""

_OPTIONAL_CELLS: Final = ("hr", "shape_iqr")
"""Les cellules qu'un fichier à l'en-tête étendu, seul, peut laisser vides."""

SPEED_RANGE_KMH: Final = (0.01, 100.0)
"""Garde-fou sur les vitesses lues, en km/h.

Il n'est pas cosmétique : ``PaceCurve`` accepte une vitesse de ``1e-309`` m/s, dont
l'inverse déborde le domaine des flottants, et l'allure du modèle vaudrait ``inf``
sans qu'aucun contrat ne s'en plaigne. Les deux bornes sont larges au point
qu'aucune courbe réelle ne les approche : elles attrapent une erreur d'unité ou de
colonne, pas un cas d'usage.
"""

MIN_EDGE_GRADE: Final = 0.01
"""Écartement minimal du support de part et d'autre du plat, en fraction (1 %).

Une courbe qui ne dit rien au-delà de ±1 % ne peut de toute façon rien projeter en
montagne, et cette borne est ce qui rend la finitude de l'allure **démontrable** :
avec ``v >= 0,01 km/h`` et ``|g_b| >= 0,01``, la vitesse verticale de bord vaut au
moins ``(0,01 / 3,6) × 0,01 = 1/36 000`` m/s. Voir :mod:`mountain_perf.model.pace`.
"""

META_SUFFIX: Final = ".meta.json"
"""Suffixe du fichier compagnon, cherché à côté du CSV."""

REASON_LOW_SUPPORT: Final = "support insuffisant"
REASON_OUTSIDE_RANGE: Final = "hors plage contiguë"


class CurveError(ValueError):
    """Fichier de courbe inutilisable : format, valeurs, support ou provenance."""


@dataclass(frozen=True)
class CurveBin:
    """Une ligne du CSV, convertie aux unités internes.

    ``sample_count`` est calculé ici, à la ligne, pour que son débordement porte un
    numéro de ligne au lieu de remonter en ``OverflowError`` nu.
    """

    grade: float
    speed_ms: float
    time_min: float
    sample_count: int


@dataclass(frozen=True)
class DiscardedBin:
    """Tranche lue mais non retenue dans le support, avec son motif."""

    grade: float
    time_min: float
    reason: str


@dataclass(frozen=True)
class CurveReadResult:
    """Courbe construite et diagnostics de la lecture, sans toucher aux contrats."""

    curve: PaceCurve
    source: SourceRef
    bin_count_read: int
    discarded: tuple[DiscardedBin, ...]

    @property
    def bin_count_kept(self) -> int:
        """Nombre de tranches retenues dans le support."""
        return len(self.curve.grade)

    @property
    def kept_grade_range(self) -> tuple[float, float]:
        """Plage de pentes retenue, en fraction."""
        return (self.curve.grade[0], self.curve.grade[-1])

    @property
    def curve_ref(self) -> str:
        """Référence de la courbe, telle que ``Projection.curve_ref`` l'attend."""
        return curve_reference(self.source)


def curve_reference(source: SourceRef) -> str:
    """Référence courte d'une courbe : nom de fichier et début de son ``sha256``.

    Le nom seul ne suffit pas : deux courbes peuvent le partager.
    """
    return f"{source.identifier}#{source.content_hash[:12]}"


def _pct(grade: float) -> str:
    """Pente en pourcentage, pour les messages d'erreur et les diagnostics."""
    return f"{grade * 100:g} %"


def _number(row: dict[str, str], column: str, line: int) -> float:
    """Valeur numérique finie d'une cellule ; ``CurveError`` sinon."""
    raw = row[column]
    try:
        value = float(raw)
    except ValueError as error:
        raise CurveError(
            f"ligne {line}, colonne {column} : valeur numérique illisible {raw!r}."
        ) from error
    if not math.isfinite(value):
        raise CurveError(f"ligne {line}, colonne {column} : valeur non finie {raw!r}.")
    return value


def _extended_checks(values: dict[str, float], line: int) -> int:
    """Les cellules de :data:`EXTENDED_COLUMNS` d'une ligne lue ; rend son nombre
    d'activités, ``sample_count`` de la tranche."""
    elapsed_kmh = values["kmh_elapsed"]
    if not SPEED_RANGE_KMH[0] <= elapsed_kmh <= SPEED_RANGE_KMH[1]:
        raise CurveError(
            f"ligne {line} : vitesse écoulée {elapsed_kmh} km/h hors de "
            f"[{SPEED_RANGE_KMH[0]} ; {SPEED_RANGE_KMH[1]}] km/h."
        )
    activities = values["activities"]
    if not activities.is_integer() or activities < 0:
        raise CurveError(
            f"ligne {line} : activities doit être un entier >= 0, reçu {activities}."
        )
    shape = values.get("shape_iqr")
    if shape is not None and shape < 0:
        raise CurveError(f"ligne {line} : shape_iqr doit être >= 0, reçu {shape}.")
    return int(activities)


def _read_bins(text: str) -> list[CurveBin]:
    """Lignes du CSV, à l'ancien en-tête ou à l'en-tête étendu, validées et triées par
    pente croissante."""
    rows = [row for row in csv.reader(text.splitlines()) if any(row)]
    expected = ",".join(CURVE_HEADER)
    if not rows:
        raise CurveError(f"Fichier de courbe vide : en-tête « {expected} » attendu.")
    header = tuple(field.strip() for field in rows[0])
    if header not in (CURVE_HEADER, EXTENDED_HEADER):
        raise CurveError(
            f"En-tête inattendu « {','.join(header)} » ; attendu « {expected} » ou "
            f"« {','.join(EXTENDED_HEADER)} »."
        )
    extended = header == EXTENDED_HEADER
    bins: list[CurveBin] = []
    for line, row in enumerate(rows[1:], start=2):
        if len(row) != len(header):
            raise CurveError(
                f"ligne {line} : {len(row)} colonnes, {len(header)} attendues."
            )
        cells = dict(zip(header, row, strict=True))
        # hr et vam_mh sont validées puis jetées : une cellule illisible signale un
        # fichier abîmé même dans une colonne dont le modèle ne se sert pas. Seul
        # l'en-tête étendu permet une cellule hr ou shape_iqr vide.
        values = {
            column: _number(cells, column, line)
            for column in header
            if not (
                extended and column in _OPTIONAL_CELLS and not cells[column].strip()
            )
        }
        grade = values["grade_pct"] / 100
        speed_kmh = values["kmh"]
        time_min = values["time_min"]
        if not GRADE_RANGE[0] <= grade <= GRADE_RANGE[1]:
            raise CurveError(
                f"ligne {line} : pente {_pct(grade)} hors de "
                f"[{_pct(GRADE_RANGE[0])} ; {_pct(GRADE_RANGE[1])}]."
            )
        if not SPEED_RANGE_KMH[0] <= speed_kmh <= SPEED_RANGE_KMH[1]:
            raise CurveError(
                f"ligne {line} : vitesse {speed_kmh} km/h hors de "
                f"[{SPEED_RANGE_KMH[0]} ; {SPEED_RANGE_KMH[1]}] km/h — "
                "erreur d'unité ou de colonne, pas un cas d'usage."
            )
        if time_min < 0:
            raise CurveError(
                f"ligne {line} : time_min doit être >= 0, reçu {time_min}."
            )
        if extended:
            sample_count = _extended_checks(values, line)
        else:
            try:
                # round(inf) lève OverflowError : une entrée finie mais démesurée ne
                # doit pas sortir en trace, comme toute autre erreur d'entrée.
                sample_count = round(time_min * 60)
            except OverflowError as error:
                raise CurveError(
                    f"ligne {line}, colonne time_min : {time_min} minutes déborde le "
                    "comptage d'échantillons."
                ) from error
        bins.append(CurveBin(grade, kmh_to_ms(speed_kmh), time_min, sample_count))
    bins.sort(key=lambda curve_bin: curve_bin.grade)
    for previous, current in pairwise(bins):
        if previous.grade == current.grade:
            raise CurveError(f"Pente en double : {_pct(current.grade)}.")
    return bins


def _select_support(
    bins: list[CurveBin], threshold_min: float
) -> tuple[list[CurveBin], tuple[DiscardedBin, ...]]:
    """Plage contiguë autour du plat dont chaque tranche atteint le seuil.

    Les quatre règles de ``docs/decisions/0009``, dans l'ordre : le **noyau** —
    dernière pente strictement négative, première strictement positive, et la ligne
    de pente exactement nulle si elle existe — doit encadrer strictement le plat
    (1) et chacune de ses lignes atteindre le seuil (2) ; l'extension se fait
    ensuite ligne par ligne de chaque côté, les deux côtés s'arrêtant
    indépendamment à la première ligne sous le seuil (3) ; le support retenu doit
    enfin s'écarter d'au moins :data:`MIN_EDGE_GRADE` du plat des deux côtés (4).

    **La contiguïté se lit sur les lignes présentes, pas sur la grille théorique des
    pentes.** Une tranche absente du fichier n'est pas un trou : seule une ligne
    présente sous le seuil arrête la plage. C'est ce qui rend la sélection
    déterministe — il n'y a ni ex æquo à départager, ni tranche « la plus proche de
    zéro » à choisir.
    """
    if not bins:
        raise CurveError(
            "Le support doit encadrer le plat : le fichier ne contient aucune ligne "
            "exploitable."
        )
    negatives = [i for i, curve_bin in enumerate(bins) if curve_bin.grade < 0]
    positives = [i for i, curve_bin in enumerate(bins) if curve_bin.grade > 0]
    if not negatives or not positives:
        missing = "négative" if not negatives else "positive"
        raise CurveError(
            f"Le support doit encadrer le plat : aucune tranche de pente {missing}. "
            "Sans cela le prolongement hors support est indéfini ou absurde."
        )
    low, high = negatives[-1], positives[0]
    # Les lignes sont triées : le noyau est l'intervalle d'indices entre la dernière
    # pente négative et la première positive, la ligne de pente nulle comprise.
    for i in range(low, high + 1):
        if bins[i].time_min < threshold_min:
            raise CurveError(
                f"La tranche centrale de pente {_pct(bins[i].grade)} n'a que "
                f"{bins[i].time_min} min de données, en dessous du seuil de "
                f"{threshold_min} min. On ne saute pas une tranche centrale pour "
                "aller chercher plus loin : une courbe qui ne dit rien de fiable "
                "autour du plat n'est pas utilisable."
            )
    first, last = low, high
    while first > 0 and bins[first - 1].time_min >= threshold_min:
        first -= 1
    while last + 1 < len(bins) and bins[last + 1].time_min >= threshold_min:
        last += 1
    if min(abs(bins[first].grade), abs(bins[last].grade)) < MIN_EDGE_GRADE:
        raise CurveError(
            f"Support trop resserré autour du plat : bords retenus "
            f"{_pct(bins[first].grade)} et {_pct(bins[last].grade)}, il en faut au "
            f"moins {_pct(MIN_EDGE_GRADE)} de chaque côté."
        )
    discarded = tuple(
        DiscardedBin(
            grade=curve_bin.grade,
            time_min=curve_bin.time_min,
            # La ligne adjacente au support est celle qui a arrêté l'extension ;
            # au-delà, une ligne est écartée même si elle dépasse le seuil.
            reason=(
                REASON_LOW_SUPPORT
                if i in (first - 1, last + 1)
                else REASON_OUTSIDE_RANGE
            ),
        )
        for i, curve_bin in enumerate(bins)
        if not first <= i <= last
    )
    return bins[first : last + 1], discarded


def select_support(
    bins: list[CurveBin], threshold_min: float
) -> tuple[list[CurveBin], tuple[DiscardedBin, ...]]:
    """La sélection du support de :func:`read_curve` (``0009`` D2), pour un appelant qui
    a ses tranches en mémoire (l'estimation, M6b) : la même règle, appelée, jamais
    copiée. ``bins`` triées par pente croissante, sans pente en double."""
    return _select_support(bins, threshold_min)


def _field(meta: dict[str, Any], name: str, file_name: str) -> Any:
    if name not in meta:
        raise CurveError(f"{file_name} : champ « {name} » manquant.")
    return meta[name]


def _text(meta: dict[str, Any], name: str, file_name: str) -> str:
    value = _field(meta, name, file_name)
    if not isinstance(value, str) or not value.strip():
        raise CurveError(
            f"{file_name} : champ « {name} » attendu comme texte non vide, "
            f"reçu {value!r}."
        )
    return value


def _integer(meta: dict[str, Any], name: str, file_name: str) -> int:
    value = _field(meta, name, file_name)
    # bool est un int en Python : true passerait pour 1 sans ce garde.
    if isinstance(value, bool) or not isinstance(value, int):
        raise CurveError(
            f"{file_name} : champ « {name} » attendu comme entier, reçu {value!r}."
        )
    return value


def _optional_number(meta: dict[str, Any], name: str, file_name: str) -> float | None:
    value = _field(meta, name, file_name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise CurveError(
            f"{file_name} : champ « {name} » attendu comme nombre ou null, "
            f"reçu {value!r}."
        )
    try:
        # Un entier JSON n'a pas de borne : float(10**400) lève OverflowError.
        return float(value)
    except OverflowError as error:
        raise CurveError(
            f"{file_name} : champ « {name} » déborde le domaine des flottants."
        ) from error


def _optional_text(meta: dict[str, Any], name: str, file_name: str) -> str | None:
    """Un champ de M6b : absent ou ``null`` donne ``None``, sinon un texte non vide."""
    if meta.get(name) is None:
        return None
    return _text(meta, name, file_name)


def _absent_or_number(meta: dict[str, Any], name: str, file_name: str) -> float | None:
    """Un champ de M6b : absent donne ``None``, sinon un nombre ou ``null``."""
    if name not in meta:
        return None
    return _optional_number(meta, name, file_name)


def _texts(meta: dict[str, Any], name: str, file_name: str) -> frozenset[str]:
    value = _field(meta, name, file_name)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise CurveError(
            f"{file_name} : champ « {name} » attendu comme liste de textes, "
            f"reçu {value!r}."
        )
    return frozenset(value)


def _date(meta: dict[str, Any], name: str, file_name: str) -> date:
    value = _text(meta, name, file_name)
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise CurveError(
            f"{file_name} : champ « {name} » attendu au format AAAA-MM-JJ, "
            f"reçu {value!r}."
        ) from error


def _instant(meta: dict[str, Any], name: str, file_name: str) -> datetime:
    value = _text(meta, name, file_name)
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as error:
        raise CurveError(
            f"{file_name} : champ « {name} » attendu au format ISO 8601, "
            f"reçu {value!r}."
        ) from error
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise CurveError(
            f"{file_name} : champ « {name} » doit porter un fuseau horaire, "
            f"reçu {value!r}. Ne jamais supposer un fuseau."
        )
    return moment


def _sport(meta: dict[str, Any], file_name: str) -> Sport:
    value = _text(meta, "sport", file_name)
    try:
        return Sport(value)
    except ValueError as error:
        admitted = ", ".join(sport.value for sport in Sport)
        raise CurveError(
            f"{file_name} : sport inconnu {value!r} ; valeurs admises : {admitted}."
        ) from error


def _read_provenance(path: Path) -> tuple[Sport, CurveProvenance]:
    """Sport et provenance lus dans le compagnon ``<stem>.meta.json``, obligatoire.

    Le CSV ne porte que des nombres : ni dates, ni filtres, ni estimateur, ni
    famille de modèle. Inventer ces valeurs produirait une projection qui affirme
    une provenance fausse sans le signaler — exactement ce que la décision ``0001``
    cherche à empêcher. Un champ supplémentaire inconnu est ignoré en silence, pour
    ne pas bloquer une version future du fichier.
    """
    meta_path = path.with_name(f"{path.stem}{META_SUFFIX}")
    name = meta_path.name
    try:
        raw = meta_path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise CurveError(
            f"Fichier de provenance absent : « {name} » est attendu à côté de "
            f"« {path.name} ». Une courbe sans provenance est une projection dont "
            "on ne peut plus dire sur quoi elle repose."
        ) from error
    except UnicodeDecodeError as error:
        raise CurveError(f"{name} : fichier illisible en UTF-8.") from error
    try:
        meta = json.loads(raw)
    except json.JSONDecodeError as error:
        raise CurveError(f"{name} : JSON illisible ({error}).") from error
    if not isinstance(meta, dict):
        raise CurveError(f"{name} : un objet JSON est attendu.")
    provenance = CurveProvenance(
        activity_count=_integer(meta, "activity_count", name),
        hr_center_bpm=_optional_number(meta, "hr_center_bpm", name),
        hr_width_bpm=_optional_number(meta, "hr_width_bpm", name),
        date_from=_date(meta, "date_from", name),
        date_to=_date(meta, "date_to", name),
        source_activity_types=_texts(meta, "source_activity_types", name),
        min_duration_s=_optional_number(meta, "min_duration_s", name),
        estimator=_text(meta, "estimator", name),
        generated_at=_instant(meta, "generated_at", name),
        athlete_ref=_optional_text(meta, "athlete_ref", name),
        max_duration_s=_absent_or_number(meta, "max_duration_s", name),
        max_elapsed_s=_absent_or_number(meta, "max_elapsed_s", name),
        hr_lag_s=_absent_or_number(meta, "hr_lag_s", name),
    )
    return _sport(meta, name), provenance


def read_curve(path: Path, parameters: ParameterSet) -> CurveReadResult:
    """Lit un CSV de courbe et son compagnon, et n'en retient que le support.

    ``sample_count`` reçoit, d'un fichier à l'en-tête étendu, le **nombre
    d'activités** de la tranche ; d'un fichier à l'ancien en-tête,
    ``round(time_min × 60)`` (des secondes de données assimilées à des échantillons,
    ce fichier ne portant aucun comptage). ``dispersion_ms`` reste ``None`` : la forme
    est l'écart interquartile d'un logarithme, sans unité, jamais une dispersion en
    m/s (``0017``) ; la vitesse écoulée et la forme sont validées, puis ignorées.

    Les violations d'invariant du contrat — fenêtre de FC à moitié renseignée,
    fréquence hors plage physiologique — restent des ``ContractError`` : elles sont
    déjà lisibles, et les recopier ici ferait deux messages à maintenir.
    """
    content = path.read_bytes()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CurveError(f"{path.name} : fichier illisible en UTF-8.") from error
    bins = _read_bins(text)
    kept, discarded = _select_support(bins, parameters["curve_min_support_min"])
    sport, provenance = _read_provenance(path)
    source = SourceRef(
        kind="csv",
        identifier=path.name,
        content_hash=hashlib.sha256(content).hexdigest(),
        retrieved_at=datetime.now(UTC),
    )
    return CurveReadResult(
        curve=PaceCurve(
            sport=sport,
            grade=tuple(curve_bin.grade for curve_bin in kept),
            speed_ms=tuple(curve_bin.speed_ms for curve_bin in kept),
            sample_count=tuple(curve_bin.sample_count for curve_bin in kept),
            dispersion_ms=None,
            estimation=provenance,
            source=source,
        ),
        source=source,
        bin_count_read=len(bins),
        discarded=discarded,
    )


@dataclass(frozen=True)
class CurveFileRow:
    """Une ligne du CSV de courbe à écrire (M6b), aux unités internes.

    - ``grade_pct`` — pourcentage — le texte exact de la pente, écrit tel quel ;
    - ``speed_ms`` — m/s — la valeur de la tranche ;
    - ``mean_hr_bpm`` — battements par minute — FC moyenne, ``None`` sans FC ;
    - ``time_min`` — minutes — le temps M qui porte la valeur ;
    - ``elapsed_speed_ms`` — m/s — la vitesse écoulée ;
    - ``activities`` — sans unité — le nombre d'activités (``sample_count``) ;
    - ``shape_iqr`` — sans unité — la forme, ``None`` sous le seuil.
    """

    grade_pct: str
    speed_ms: float
    mean_hr_bpm: float | None
    time_min: float
    elapsed_speed_ms: float
    activities: int
    shape_iqr: float | None


def _csv_text(rows: Sequence[CurveFileRow]) -> str:
    """Le texte du CSV : :data:`EXTENDED_HEADER`, puis une ligne par élément de
    ``rows``, dans leur ordre ; ``"\\n"`` entre les lignes et à la fin. La forme n'est
    jamais convertie ; un ``grade_pct`` illisible lève ``ValueError``."""
    lines = [",".join(EXTENDED_HEADER)]
    for row in rows:
        grade = float(row.grade_pct) / 100
        cells = (
            row.grade_pct,
            repr(row.speed_ms * 3.6),
            "" if row.mean_hr_bpm is None else repr(row.mean_hr_bpm),
            repr(row.speed_ms * grade * 3600),
            repr(row.time_min),
            repr(row.elapsed_speed_ms * 3.6),
            str(row.activities),
            "" if row.shape_iqr is None else repr(row.shape_iqr),
        )
        lines.append(",".join(cells))
    return "\n".join(lines) + "\n"


def _first_unreadable(rows: Sequence[CurveFileRow]) -> CurveFileRow | None:
    """La première ligne de ``rows`` qui, seule sous l'en-tête étendu, ne se lit
    pas."""
    for row in rows:
        try:
            _read_bins(_csv_text([row]))
        except CurveError:
            return row
    return None


def check_curve_rows(rows: Sequence[CurveFileRow], threshold_min: float) -> str | None:
    """Ce que :func:`read_curve` ferait de ces lignes (``0017``, P3.7).

    Une ligne qu'il refuse rendrait le fichier illisible : ``CurveError`` « La tranche
    <grade_pct> % serait illisible par read_curve, la courbe n'est pas écrite :
    <message de la lecture> », qui dit la tranche en cause — la première ligne qui,
    seule, ne se lit pas —, levée depuis l'erreur de lecture ; une erreur qu'aucune
    ligne seule ne cause (une pente en double) remonte telle quelle. Elle n'est jamais
    rendue comme un message de support. Si le support est impossible au seuil
    ``threshold_min`` (minutes), rend son message : la courbe s'écrit, non
    projetable. Sinon ``None``.
    """
    try:
        bins = _read_bins(_csv_text(rows))
    except CurveError as error:
        culprit = _first_unreadable(rows)
        if culprit is None:
            raise
        raise CurveError(
            f"La tranche {culprit.grade_pct} % serait illisible par read_curve, la "
            f"courbe n'est pas écrite : {error}"
        ) from error
    try:
        _select_support(bins, threshold_min)
    except CurveError as error:
        return str(error)
    return None


def _meta_text(
    sport: Sport, provenance: CurveProvenance, estimation: Mapping[str, object]
) -> str:
    """Le texte JSON du compagnon, clés dans l'ordre ; une valeur non finie est
    refusée (``ValueError``)."""
    document = {
        "sport": sport.value,
        "activity_count": provenance.activity_count,
        "hr_center_bpm": provenance.hr_center_bpm,
        "hr_width_bpm": provenance.hr_width_bpm,
        "hr_lag_s": provenance.hr_lag_s,
        "date_from": provenance.date_from.isoformat(),
        "date_to": provenance.date_to.isoformat(),
        "source_activity_types": sorted(provenance.source_activity_types),
        "min_duration_s": provenance.min_duration_s,
        "max_duration_s": provenance.max_duration_s,
        "max_elapsed_s": provenance.max_elapsed_s,
        "athlete_ref": provenance.athlete_ref,
        "estimator": provenance.estimator,
        "generated_at": provenance.generated_at.isoformat(),
        "estimation": dict(estimation),
    }
    return json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def write_curve(
    path: Path,
    rows: Sequence[CurveFileRow],
    sport: Sport,
    provenance: CurveProvenance,
    estimation: Mapping[str, object],
) -> None:
    """Écrit une courbe estimée (M6b) : le CSV ``path`` à l'en-tête étendu et son
    compagnon ``<stem>.meta.json``.

    Le compagnon porte le sport et la provenance, que :func:`read_curve` relit, et sous
    la clé ``estimation`` ce que :func:`read_curve` ignore (paramètres, niveau,
    comptes). Les deux fichiers sont des octets UTF-8, à fins de ligne ``"\\n"`` sous
    toute plateforme.

    Une courbe n'est jamais réécrite : si le CSV ou le compagnon existe, ``CurveError``
    avant tout écrit. Les deux textes sont calculés avant tout écrit (un ``grade_pct``
    illisible, une valeur non finie du compagnon sortent sans rien écrire). Le
    compagnon s'écrit d'abord, puis le CSV ; si l'écriture du CSV échoue, le compagnon
    est retiré et l'exception remonte : un compagnon orphelin ferait refuser la
    tentative suivante.
    """
    meta_path = path.with_name(f"{path.stem}{META_SUFFIX}")
    for target in (path, meta_path):
        if target.exists():
            raise CurveError(
                f"{target.name} existe déjà : une courbe n'est jamais réécrite."
            )
    meta_bytes = _meta_text(sport, provenance, estimation).encode("utf-8")
    csv_bytes = _csv_text(rows).encode("utf-8")
    with meta_path.open("xb") as stream:
        stream.write(meta_bytes)
    try:
        with path.open("xb") as stream:
            stream.write(csv_bytes)
    except BaseException:
        meta_path.unlink(missing_ok=True)
        raise
