"""Le journal de l'athlète : la lecture de ``MPA_DATA_DIR/journal.csv`` (charte, § 3 ;
AN2-2).

Le journal porte les événements que Garmin ne contient pas (une maladie, une blessure,
une course, un séjour en altitude…). Il est tenu à la main par l'athlète : la
bibliothèque le lit, ne l'écrit jamais. Sans fichier, ou avec un fichier vide (aucun
octet, un BOM seul, ou seulement des lignes vides), il n'y a aucun événement.

Le format, pour qui tient le fichier
------------------------------------

Un fichier CSV : une ligne d'en-tête, puis une ligne par événement. Exemple inventé,
tel qu'Excel en français l'enregistre :

```csv
debut;fin;type;note
2000-01-12;2000-01-14;maladie;
2000-02-05;2000-02-05;course;"une note ; avec le séparateur"
```

- **L'en-tête** est la première ligne non vide. Il nomme les colonnes ``debut``,
  ``fin`` et ``type``, obligatoires, et ``note``, facultative, dans n'importe quel
  ordre ; la casse et les blancs autour d'un nom ne comptent pas (``Debut`` vaut
  ``debut``), les accents si (``début`` n'est pas un nom admis). Une colonne d'un autre
  nom, ou nommée deux fois, arrête la lecture. Des colonnes sans nom **à la fin** de
  l'en-tête (``debut;fin;type;note;;``, une marge qu'Excel laisse quand une cellule à
  droite du tableau a servi) sont ignorées, si tous leurs champs sont vides ou blancs ;
  un champ non vide dans l'une d'elles arrête, comme une colonne sans nom avant une
  colonne nommée (``debut;;fin;type``).
- **Le séparateur** est ``;`` si la ligne d'en-tête contient un ``;``, sinon ``,``
  (Excel en français enregistre avec ``;``). Un champ qui contient le séparateur, un
  guillemet ou un retour à la ligne s'écrit entre guillemets ``"``, et un guillemet
  s'y double (``""``) : Excel le fait seul. Un guillemet ouvert en tête de champ doit
  se refermer, suivi du séparateur ou de la fin de la ligne.
- **L'encodage** est UTF-8, avec ou sans BOM : dans Excel, « Enregistrer sous », type
  « CSV UTF-8 ». Un autre encodage arrête la lecture, avec un message qui le dit.
- **Les blancs autour d'un champ** ne comptent jamais : ``2000-01-12, 2000-01-14,
  maladie`` se lit comme ``2000-01-12,2000-01-14,maladie``.
- **Les dates** s'écrivent ``AAAA-MM-JJ``, en chiffres ASCII, et rien d'autre
  (``2000-01-12``) ; ce sont
  des dates locales. Une date d'un autre format (``12/01/2000``) ou qui n'existe pas
  (``2000-02-30``) arrête la lecture. Excel réécrit une date tapée au format de la
  région : mettre les colonnes ``debut`` et ``fin`` au format personnalisé
  ``aaaa-mm-jj``, ou en texte, avant d'enregistrer.
- **``debut`` et ``fin``** sont le premier et le dernier jour de l'événement, tous deux
  compris : un événement d'un jour a ``fin`` égale à ``debut``. ``fin`` est
  obligatoire, et jamais avant ``debut`` : un événement en cours s'écrit avec sa fin
  prévue, qui se corrige ensuite.
- **``type``** est l'un des huit types de la charte (§ 3), sans accent ; la casse et
  les blancs autour ne comptent pas : ``maladie``, ``blessure``, ``course``,
  ``deplacement`` (une absence temporaire), ``demenagement`` (un changement durable de
  lieu de vie, donc de terrain), ``sejour_altitude``, ``etalon`` (un passage d'un
  parcours étalon que l'appariement ne reconnaît pas), ``autre``. Ce que la table
  ``jours`` en fait : ``JOURNAL_EVENT_TYPE_DESCRIPTIONS`` (``maladie`` et ``blessure``
  sortent les jours couverts des normales, ``sejour_altitude`` aussi par défaut).
- **``note``** est un texte libre, pour l'athlète seul : la bibliothèque ne regarde
  que s'il est vide, ne le garde pas, et ne le recopie dans aucun message.
- **Une ligne vide**, dont tous les champs sont vides ou blancs (une ligne sans rien,
  ``;;;``), est ignorée, avant l'en-tête comme après ; avant l'en-tête, ses champs
  se lisent avec le séparateur qu'elle choisirait (``;`` si elle en contient un,
  sinon ``,``), sans le mode strict, et une ligne que le module ``csv`` refuse
  n'est pas vide. Toute autre ligne a autant de
  champs que l'en-tête, colonnes sans nom comprises : sous ``debut;fin;type;note``, une
  ligne sans note garde son dernier ``;`` (``2000-01-12;2000-01-14;maladie;``).

**Les jours couverts** vont de ``debut`` à ``fin``, bornes comprises
(:func:`journal_types_by_day`, sur les jours de la table ``jours``), et la nuit suit son
jour de réveil : une ``maladie`` du 12 au 14 couvre les jours 12, 13 et 14, donc les
nuits du 11 au 12, du 12 au 13 et du 13 au 14 ; la nuit du 14 au 15, rattachée au jour
15, ne l'est pas.

Les erreurs
-----------

Un fichier malformé arrête la lecture (:class:`JournalError`), et avec elle
``mperf tables``, qui n'écrit rien. Le message est ``journal.csv, ligne <n> : <cause>``,
la ligne comptée depuis 1 dans le fichier, en-tête et lignes vides compris (un
enregistrement sur plusieurs lignes, par une note entre guillemets, porte le numéro de
sa première) ; sans ligne à désigner (encodage, fichier illisible),
``journal.csv : <cause>``. Les causes sont les constantes ``*_CAUSE`` du module, dont
certaines nomment une colonne attendue ou une position, jamais une valeur du fichier :
**aucun message ne recopie une note, un type, une date ou un nom d'en-tête mal écrits**.
Une ligne se contrôle dans cet ordre : le nombre de champs, les colonnes sans nom,
``debut``, ``fin`` (vide, puis illisible), ``fin`` avant ``debut``, ``type`` ; la
première cause qui s'applique est dite.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from itertools import pairwise
from pathlib import Path
from types import MappingProxyType

from mountain_perf.schemas.processed import JournalEventType
from mountain_perf.validation import ContractError, require_immutable_sequence

JOURNAL_FILE = "journal.csv"
"""Le nom du fichier, à la racine de ``MPA_DATA_DIR``."""

START_COLUMN = "debut"
END_COLUMN = "fin"
TYPE_COLUMN = "type"
NOTE_COLUMN = "note"

REQUIRED_COLUMNS = (START_COLUMN, END_COLUMN, TYPE_COLUMN)
"""Les colonnes obligatoires de l'en-tête, dans l'ordre où leur absence se dit."""

JOURNAL_COLUMNS = (*REQUIRED_COLUMNS, NOTE_COLUMN)
"""Les seules colonnes admises ; ``note`` est facultative."""

DATE_FORMAT = "AAAA-MM-JJ"
"""Le format des dates, tel que les messages le disent."""

ENCODING_CAUSE = "pas en UTF-8 (l'enregistrer en « CSV UTF-8 »)"
"""Les octets ne se décodent pas en UTF-8 (avec ou sans BOM) ; sans numéro de ligne."""

READ_CAUSE = "lecture impossible ({reason})"
"""Le fichier existe mais ne se lit pas (un dossier, un droit qui manque, un fichier
verrouillé) ; ``reason`` est le texte que le système donne à l'erreur (son
``strerror``, sans numéro ni chemin), ou, s'il manque, le nom de sa classe ; jamais un
contenu.
"""

MISSING_COLUMN_CAUSE = "colonne {column} manquante dans l'en-tête"
"""Une colonne de :data:`REQUIRED_COLUMNS` manque ; ``column`` est son nom."""

UNKNOWN_COLUMN_CAUSE = (
    "colonne {position} de l'en-tête inconnue (colonnes admises : debut, "
    "fin, type, note)"
)
"""Un nom d'en-tête hors de :data:`JOURNAL_COLUMNS` ; ``position`` compte les colonnes
depuis 1, le nom lu n'est pas recopié.
"""

REPEATED_COLUMN_CAUSE = "colonne {column} nommée deux fois dans l'en-tête"
"""Un nom admis, répété ; ``column`` est le nom admis, non le texte lu."""

UNNAMED_COLUMN_CAUSE = (
    "colonne {position} de l'en-tête sans nom, avant une colonne nommée"
)
"""Un nom vide ou blanc avant un nom non vide : ce n'est pas une marge d'Excel ;
``position`` compte les colonnes depuis 1.
"""

UNNAMED_FIELD_CAUSE = (
    "champ non vide dans la colonne {position}, sans nom dans l'en-tête"
)
"""Un champ non vide (ni blanc) dans une colonne de la marge sans nom ; ``position``
compte les colonnes depuis 1, la valeur n'est pas recopiée.
"""

FIELD_COUNT_CAUSE = "{found} champs, l'en-tête en a {expected}"
"""Une ligne non vide n'a pas autant de champs que l'en-tête (colonnes sans nom
comprises).
"""

UNREADABLE_DATE_CAUSE = (
    "date illisible dans la colonne {column} (format attendu AAAA-MM-JJ)"
)
"""``debut`` ou ``fin`` hors de :data:`DATE_FORMAT`, ou une date qui n'existe pas."""

EMPTY_END_CAUSE = (
    "fin vide (un événement en cours s'écrit avec sa fin prévue, qui se "
    "corrige ensuite)"
)
"""``fin`` vide ou blanche."""

END_BEFORE_START_CAUSE = "fin avant debut"
"""``fin`` antérieure à ``debut``."""

UNKNOWN_TYPE_CAUSE = (
    "type inconnu (types admis : maladie, blessure, course, deplacement, "
    "demenagement, sejour_altitude, etalon, autre)"
)
"""``type`` hors des valeurs de ``JournalEventType``, listées dans l'ordre de la
charte.
"""

UNREADABLE_CSV_CAUSE = (
    "illisible en CSV (un guillemet ouvert qui ne se referme pas, ou qui "
    "n'est pas suivi du séparateur, ou un champ trop long)"
)
"""Le module ``csv`` refuse l'enregistrement qui commence à cette ligne."""

_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_TYPES = {member.value: member for member in JournalEventType}


class JournalError(ValueError):
    """``journal.csv`` illisible ou malformé ; le message dit la ligne et la cause,
    sans recopier aucune valeur du fichier.
    """


@dataclass(frozen=True)
class JournalEvent:
    """Un événement du journal. La note n'est pas gardée.

    - ``start``, ``end`` : le premier et le dernier jour couverts, dates locales,
      compris ;
    - ``event_type`` : son type ;
    - ``line`` : le numéro, compté depuis 1 dans le fichier, de la première ligne de
      l'événement.

    Invariants (``ContractError``) : ``end`` ≥ ``start`` ; ``line`` ≥ 2 (l'en-tête
    occupe au moins la ligne 1).
    """

    start: date
    end: date
    event_type: JournalEventType
    line: int

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ContractError("JournalEvent : end doit être >= start.")
        if self.line < 2:
            raise ContractError(
                f"JournalEvent : line doit être >= 2, reçu {self.line}."
            )


@dataclass(frozen=True)
class Journal:
    """Le journal lu.

    - ``events`` : les événements, dans l'ordre du fichier ;
    - ``sha256`` : le SHA-256 des octets du fichier (64 chiffres hexadécimaux
      minuscules), ou ``None`` s'il n'existe pas.

    Invariants (``ContractError``) : ``events`` est un tuple, de lignes strictement
    croissantes ; ``sha256`` absent, ou de 64 chiffres hexadécimaux minuscules ; sans
    fichier, aucun événement.
    """

    events: tuple[JournalEvent, ...]
    sha256: str | None

    def __post_init__(self) -> None:
        require_immutable_sequence(self.events, "Journal.events")
        lines = [event.line for event in self.events]
        if any(later <= earlier for earlier, later in pairwise(lines)):
            raise ContractError("Journal.events : lignes strictement croissantes.")
        if self.sha256 is None:
            if self.events:
                raise ContractError("Journal : sans fichier (sha256 absent), rien lu.")
        elif len(self.sha256) != 64 or any(
            c not in "0123456789abcdef" for c in self.sha256
        ):
            raise ContractError("Journal.sha256 : 64 chiffres hexadécimaux minuscules.")


def _refusal(cause: str) -> JournalError:
    return JournalError(f"{JOURNAL_FILE} : {cause}")


def _line_refusal(line: int, cause: str) -> JournalError:
    return JournalError(f"{JOURNAL_FILE}, ligne {line} : {cause}")


def _decoded(data: bytes) -> str | None:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def _separator(line: str) -> str:
    return ";" if ";" in line else ","


def _all_blank(fields: Sequence[str]) -> bool:
    return all(not field.strip() for field in fields)


def _empty_before_header(line: str) -> bool:
    """Une ligne d'avant l'en-tête est vide si ses champs, lus avec le séparateur
    qu'elle choisirait et sans le mode strict, sont tous vides ou blancs ; une ligne
    que le module ``csv`` refuse n'est pas vide."""
    try:
        fields = next(csv.reader([line], delimiter=_separator(line)), [])
    except csv.Error:
        return False
    return _all_blank(fields)


def _records(lines: Sequence[str], first: int) -> Iterator[tuple[int, list[str]]]:
    """Les enregistrements de ``lines`` depuis la ligne d'indice ``first`` (l'en-tête),
    en mode strict, chacun avec le numéro de sa première ligne physique."""
    reader = csv.reader(
        iter(lines[first:]), delimiter=_separator(lines[first]), strict=True
    )
    while True:
        line = first + reader.line_num + 1
        fields: list[str] = []
        unreadable = False
        try:
            fields = next(reader)
        except StopIteration:
            return
        except csv.Error:
            unreadable = True
        if unreadable:
            raise _line_refusal(line, UNREADABLE_CSV_CAUSE)
        yield line, fields


def _header(fields: Sequence[str], line: int) -> dict[str, int]:
    """Les indices des colonnes nommées de l'en-tête ; refuse un en-tête invalide,
    dans l'ordre de ses colonnes, puis les colonnes obligatoires qui manquent."""
    names = [field.strip().lower() for field in fields]
    last_named = max((i for i, name in enumerate(names) if name), default=-1)
    columns: dict[str, int] = {}
    for i, name in enumerate(names):
        position = i + 1
        if not name:
            if i < last_named:
                raise _line_refusal(
                    line, UNNAMED_COLUMN_CAUSE.format(position=position)
                )
        elif name not in JOURNAL_COLUMNS:
            raise _line_refusal(line, UNKNOWN_COLUMN_CAUSE.format(position=position))
        elif name in columns:
            raise _line_refusal(line, REPEATED_COLUMN_CAUSE.format(column=name))
        else:
            columns[name] = i
    for column in REQUIRED_COLUMNS:
        if column not in columns:
            raise _line_refusal(line, MISSING_COLUMN_CAUSE.format(column=column))
    return columns


def _date(text: str) -> date | None:
    """La date de ``text``, déjà sans blancs autour ; ``None`` si elle est illisible."""
    if _DATE_PATTERN.fullmatch(text) is None:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _event(
    fields: Sequence[str], line: int, width: int, columns: Mapping[str, int]
) -> JournalEvent | None:
    """L'événement d'un enregistrement, ``None`` pour une ligne vide ; les contrôles
    se font dans l'ordre du module."""
    if _all_blank(fields):
        return None
    if len(fields) != width:
        raise _line_refusal(
            line, FIELD_COUNT_CAUSE.format(found=len(fields), expected=width)
        )
    named = set(columns.values())
    for i, field in enumerate(fields):
        if i not in named and field.strip():
            raise _line_refusal(line, UNNAMED_FIELD_CAUSE.format(position=i + 1))
    start = _date(fields[columns[START_COLUMN]].strip())
    if start is None:
        raise _line_refusal(line, UNREADABLE_DATE_CAUSE.format(column=START_COLUMN))
    end_text = fields[columns[END_COLUMN]].strip()
    if not end_text:
        raise _line_refusal(line, EMPTY_END_CAUSE)
    end = _date(end_text)
    if end is None:
        raise _line_refusal(line, UNREADABLE_DATE_CAUSE.format(column=END_COLUMN))
    if end < start:
        raise _line_refusal(line, END_BEFORE_START_CAUSE)
    event_type = _TYPES.get(fields[columns[TYPE_COLUMN]].strip().lower())
    if event_type is None:
        raise _line_refusal(line, UNKNOWN_TYPE_CAUSE)
    return JournalEvent(start, end, event_type, line)


def read_journal(data_dir: Path) -> Journal:
    """Le journal de ``data_dir/journal.csv``.

    Rend un :class:`Journal` : ses événements dans l'ordre du fichier, et le SHA-256
    des octets lus, lus une seule fois (l'empreinte est celle des octets interprétés,
    BOM compris) ; sans fichier (``FileNotFoundError``), un ``Journal`` sans événement
    ni empreinte (``events`` vide, ``sha256`` à ``None``) ; un
    fichier vide (aucun octet, un BOM seul, des lignes vides seulement) rend un journal
    sans événement, avec son empreinte.

    Lève :class:`JournalError` (message ``journal.csv, ligne <n> : <cause>``, ou
    ``journal.csv : <cause>``) : un fichier qui existe mais ne se lit pas
    (:data:`READ_CAUSE`) ; des octets qui ne sont pas de l'UTF-8
    (:data:`ENCODING_CAUSE`) ; un en-tête au nom inconnu ou répété, à une colonne sans
    nom avant une colonne nommée, ou sans colonne obligatoire ; un enregistrement que le
    module ``csv`` refuse ; une ligne au mauvais nombre de champs, à un champ non vide
    dans une colonne sans nom, à la date illisible, à ``fin`` vide ou avant ``debut``,
    au type inconnu. Aucun message ne recopie une valeur du fichier, et l'erreur n'en
    enchaîne aucune.
    """
    data: bytes | None = None
    reason = ""
    try:
        data = (data_dir / JOURNAL_FILE).read_bytes()
    except FileNotFoundError:
        return Journal((), None)
    except OSError as error:
        reason = error.strerror or type(error).__name__
    if data is None:
        raise _refusal(READ_CAUSE.format(reason=reason))
    sha256 = hashlib.sha256(data).hexdigest()
    text = _decoded(data)
    if text is None:
        raise _refusal(ENCODING_CAUSE)
    lines = io.StringIO(text, newline="").readlines()
    first = next(
        (i for i, line in enumerate(lines) if not _empty_before_header(line)), None
    )
    if first is None:
        return Journal((), sha256)
    records = _records(lines, first)
    header_line, header = next(records)
    columns = _header(header, header_line)
    events = [
        event
        for line, fields in records
        if (event := _event(fields, line, len(header), columns)) is not None
    ]
    return Journal(tuple(events), sha256)


def _bound(value: object, name: str) -> None:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise ValueError(
            f"journal_types_by_day : {name} doit être une date, reçu "
            f"{type(value).__name__}."
        )


def journal_types_by_day(
    journal: Journal, first: date, last: date
) -> Mapping[date, tuple[JournalEventType, ...]]:
    """Les types du journal, jour par jour, sur les jours ``[first, last]`` (ceux de
    la table ``jours``, bornes comprises).

    Rend une table en lecture seule, triée par jour : chaque jour de ``[first, last]``
    couvert par au moins un événement, de son ``start`` à son ``end``, bornes comprises,
    avec les types qui le couvrent, sans doublon et triés par valeur
    (l'ordre de ``DayRow.journal_types``). Un événement qui
    déborde de ``[first, last]`` y est coupé ; un jour qu'aucun événement ne couvre n'y
    est pas. Le coût ne dépend que de ``[first, last]`` et du nombre d'événements, pas
    de leur durée : une fin absurde (``9999-12-31``) ne coûte rien de plus.

    Lève ``ValueError``, qui nomme l'argument, si ``first`` ou ``last`` n'est pas une
    date (un ``datetime`` non plus), ou si ``first`` est après ``last``.
    """
    _bound(first, "first")
    _bound(last, "last")
    if first > last:
        raise ValueError(
            f"journal_types_by_day : first ({first.isoformat()}) doit être <= last "
            f"({last.isoformat()})."
        )
    found: dict[date, set[JournalEventType]] = {}
    for event in journal.events:
        start, end = max(event.start, first), min(event.end, last)
        for ordinal in range(start.toordinal(), end.toordinal() + 1):
            found.setdefault(date.fromordinal(ordinal), set()).add(event.event_type)
    return MappingProxyType({day: tuple(sorted(found[day])) for day in sorted(found)})
