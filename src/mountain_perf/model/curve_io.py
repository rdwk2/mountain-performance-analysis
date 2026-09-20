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
from dataclasses import dataclass
from datetime import UTC, date, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any, Final

from mountain_perf.schemas import (
    GRADE_RANGE,
    CurveProvenance,
    PaceCurve,
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

CURVE_HEADER: Final = ("grade_pct", "kmh", "hr", "vam_mh", "time_min")
"""En-tête exigé du CSV. ``hr`` et ``vam_mh`` sont lues et validées, puis ignorées :
elles ne rentrent dans aucun contrat."""

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


def _read_bins(text: str) -> list[CurveBin]:
    """Lignes du CSV, validées et triées par pente croissante."""
    rows = [row for row in csv.reader(text.splitlines()) if any(row)]
    expected = ",".join(CURVE_HEADER)
    if not rows:
        raise CurveError(f"Fichier de courbe vide : en-tête « {expected} » attendu.")
    header = tuple(field.strip() for field in rows[0])
    if header != CURVE_HEADER:
        raise CurveError(
            f"En-tête inattendu « {','.join(header)} » ; attendu « {expected} »."
        )
    bins: list[CurveBin] = []
    for line, row in enumerate(rows[1:], start=2):
        if len(row) != len(CURVE_HEADER):
            raise CurveError(
                f"ligne {line} : {len(row)} colonnes, {len(CURVE_HEADER)} attendues."
            )
        cells = dict(zip(CURVE_HEADER, row, strict=True))
        # hr et vam_mh sont validées puis jetées : une cellule illisible signale un
        # fichier abîmé même dans une colonne dont le modèle ne se sert pas.
        values = {column: _number(cells, column, line) for column in CURVE_HEADER}
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
    )
    return _sport(meta, name), provenance


def read_curve(path: Path, parameters: ParameterSet) -> CurveReadResult:
    """Lit un CSV de courbe et son compagnon, et n'en retient que le support.

    ``sample_count`` reçoit ``round(time_min × 60)``, c'est-à-dire **des secondes de
    données assimilées à des échantillons** : le CSV ne porte aucun comptage de
    points. La définition sera alignée en M6b, quand l'estimateur écrira lui-même le
    fichier (ligne de ``BACKLOG.md``). ``dispersion_ms`` reste ``None``, le fichier
    n'en porte pas.

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
