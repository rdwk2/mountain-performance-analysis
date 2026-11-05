"""Les documents d'``interim/activities/`` : écriture, relecture, mise en place
(``docs/decisions/0013``, point 3).

Chaque fichier est un document JSON canonique (``{"type", "format", "data"}``), écrit et
relu par l'enveloppe du codec commun au format ``INTERIM_FORMAT_VERSION`` : la relecture
revalide le contrat et vérifie que la réécriture redonne les octets lus. Ce module ne
demande aucun extra : ``interim/`` se relit sans fitdecode (``0011``).
"""

import shutil
from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path
from types import MappingProxyType

from mountain_perf.codec import decode_envelope, encode_envelope
from mountain_perf.schemas import (
    INTERIM_FORMAT_VERSION,
    ActivityIndex,
    ActivityRecording,
    DayRecord,
    DaysReport,
    IngestionReport,
    TrainingStatusHistory,
    require_activity_ref,
)

INTERIM_DOCUMENT_FIRST_FORMAT: Mapping[type, int] = MappingProxyType(
    {
        ActivityIndex: 1,
        ActivityRecording: 1,
        IngestionReport: 1,
        DayRecord: 2,
        TrainingStatusHistory: 2,
        DaysReport: 2,
    }
)
"""Les types admis en documents d'``interim/``, et le premier format qui connaît
chacun : les types des jours (AN2-1) entrent au format 2, sans changer
``INTERIM_FORMAT_VERSION``."""

ACTIVITIES_DIR = Path("interim") / "activities"
"""Le dossier des documents des activités, relatif à ``MPA_DATA_DIR``."""

INDEX_FILE = "index.json"
"""Le document de l'index (``ActivityIndex``)."""

REPORT_FILE = "report.json"
"""Le document du rapport des activités de la dernière ingestion
(``IngestionReport``)."""

RECORDINGS_DIR = "recordings"
"""Le dossier des enregistrements, un document par activité (``ActivityRecording``)."""

DOCUMENT_SUFFIX = ".json"
"""Le suffixe d'un document : ``recordings/<activity_ref>.json``,
``days/<AAAA-MM-JJ>.json``."""

DAYS_DIR = Path("interim") / "days"
"""Le dossier des documents des jours, relatif à ``MPA_DATA_DIR`` (AN2-1) : un document
par jour (``DayRecord``, ``<AAAA-MM-JJ>.json``), Training Status et le rapport des
jours."""

TRAINING_STATUS_FILE = "training_status.json"
"""Le document de Training Status (``TrainingStatusHistory``), dans ``DAYS_DIR``."""

DAYS_REPORT_FILE = "report.json"
"""Le document du rapport des jours de la dernière ingestion (``DaysReport``), dans
``DAYS_DIR``."""

_NEW_SUFFIX = ".nouveau"
_OLD_SUFFIX = ".ancien"

_EXTRA_RECORDING = (
    "Un enregistrement doit correspondre à une entrée de l'index qui en porte un, une "
    "seule fois."
)
_MISSING_RECORDING = (
    "Chaque entrée de l'index qui porte un enregistrement doit en recevoir un."
)
_UNSORTED_DAYS = "Les jours doivent venir triés par date, chacun une seule fois."
_RUN_INGEST = "lancer `mperf ingest`."


class InterimError(Exception):
    """``interim/`` est absent ou incohérent : le message dit de lancer
    ``mperf ingest``."""


def encode_interim(value: object) -> bytes:
    """Le document d'``interim/`` du contrat ``value``, au format
    ``INTERIM_FORMAT_VERSION`` : ``encode_envelope`` avec les types de
    ``INTERIM_DOCUMENT_FIRST_FORMAT``."""
    return encode_envelope(
        value,
        format_version=INTERIM_FORMAT_VERSION,
        first_formats=INTERIM_DOCUMENT_FIRST_FORMAT,
    )


def decode_interim[T](data: bytes, expected: type[T]) -> T:
    """Le contrat ``expected`` relu depuis un document d'``interim/`` :
    ``decode_envelope`` au format ``INTERIM_FORMAT_VERSION`` (``CodecError`` pour un
    document illisible, d'un autre type ou d'un autre format, ou non canonique)."""
    return decode_envelope(
        data,
        expected,
        format_version=INTERIM_FORMAT_VERSION,
        first_formats=INTERIM_DOCUMENT_FIRST_FORMAT,
    )


def _remove(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def write_activities(
    data_dir: Path,
    index: ActivityIndex,
    recordings: Iterable[ActivityRecording],
    report: IngestionReport,
) -> None:
    """Écrit ``interim/activities/`` sous ``data_dir`` : l'index, un document par
    enregistrement, le rapport ; une écriture interrompue laisse l'ancien dossier
    intact.

    Dans cet ordre : supprime ``interim/activities.nouveau/`` et
    ``interim/activities.ancien/`` s'ils restent d'une écriture interrompue ; écrit tout
    dans ``activities.nouveau/`` ; renomme l'ancien ``activities/`` (s'il existe) en
    ``activities.ancien/`` ; met ``activities.nouveau/`` à sa place ; supprime
    ``activities.ancien/``. Si ``activities.nouveau/`` ne prend pas sa place (un fichier
    tenu ailleurs, sous Windows), ``activities.ancien/`` reprend la sienne, et l'erreur
    se propage (AN2-0, ``BACKLOG``).

    Les enregistrements doivent correspondre exactement aux entrées de l'index dont
    ``has_recording`` est vrai, chacun une fois. Ils se contrôlent dans l'ordre reçu,
    chacun contre l'index : un enregistrement en trop, en double ou sans
    ``has_recording`` lève ``ValueError`` (« Un enregistrement doit correspondre à une
    entrée de l'index qui en porte un, une seule fois. ») ; le manque se contrôle
    ensuite (« Chaque entrée de l'index qui porte un enregistrement doit en recevoir
    un. »). Sur ces fautes, ``activities.nouveau/`` est supprimé et rien n'est mis en
    place : l'ancien ``activities/`` reste intact.
    """
    target = data_dir / ACTIVITIES_DIR
    new = target.with_name(target.name + _NEW_SUFFIX)
    old = target.with_name(target.name + _OLD_SUFFIX)
    _remove(new)
    _remove(old)
    expected = {entry.activity_ref for entry in index.entries if entry.has_recording}
    try:
        (new / RECORDINGS_DIR).mkdir(parents=True)
        (new / INDEX_FILE).write_bytes(encode_interim(index))
        for recording in recordings:
            if recording.activity_ref not in expected:
                raise ValueError(_EXTRA_RECORDING)
            expected.remove(recording.activity_ref)
            name = recording.activity_ref + DOCUMENT_SUFFIX
            (new / RECORDINGS_DIR / name).write_bytes(encode_interim(recording))
        if expected:
            raise ValueError(_MISSING_RECORDING)
        (new / REPORT_FILE).write_bytes(encode_interim(report))
    except BaseException:
        _remove(new)
        raise
    if target.exists():
        target.rename(old)
    try:
        new.rename(target)
    except BaseException:
        if old.exists() and not target.exists():
            old.rename(target)
        raise
    _remove(old)


def _read_document(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        raise InterimError(
            f"{path.name} manque dans interim/ : lancer `mperf ingest`."
        ) from None


def read_index(data_dir: Path) -> ActivityIndex:
    """L'index d'``interim/activities/`` sous ``data_dir`` ; fichier absent :
    ``InterimError`` (« index.json manque dans interim/ : lancer `mperf ingest`. »)."""
    data = _read_document(data_dir / ACTIVITIES_DIR / INDEX_FILE)
    return decode_interim(data, ActivityIndex)


def read_report(data_dir: Path) -> IngestionReport:
    """Le rapport des activités de la dernière ingestion ; fichier absent :
    ``InterimError`` (« report.json manque dans interim/ : lancer `mperf ingest`. »)."""
    data = _read_document(data_dir / ACTIVITIES_DIR / REPORT_FILE)
    return decode_interim(data, IngestionReport)


def read_recording(data_dir: Path, activity_ref: str) -> ActivityRecording:
    """L'enregistrement de l'activité ``activity_ref``.

    Dans cet ordre : ``require_activity_ref`` (un identifiant qui ne nomme pas un
    fichier du dossier lève ``ContractError``, avant toute lecture) ; fichier absent :
    ``InterimError`` (« <identifiant>.json manque dans interim/ : lancer
    `mperf ingest`. ») ; document relu ; un document dont l'``activity_ref`` n'est pas
    celui demandé lève ``InterimError`` (« interim/ incohérent : … »).
    """
    require_activity_ref(activity_ref)
    path = data_dir / ACTIVITIES_DIR / RECORDINGS_DIR / (activity_ref + DOCUMENT_SUFFIX)
    recording = decode_interim(_read_document(path), ActivityRecording)
    if recording.activity_ref != activity_ref:
        raise InterimError(
            "interim/ incohérent : un enregistrement porte un autre identifiant que "
            "son nom de fichier. Lancer `mperf ingest`."
        )
    return recording


def write_days(
    data_dir: Path,
    records: Iterable[DayRecord],
    history: TrainingStatusHistory,
    report: DaysReport,
) -> None:
    """Écrit ``interim/days/`` sous ``data_dir`` : un document par jour, Training
    Status, le rapport des jours ; une écriture interrompue laisse l'ancien dossier
    intact.

    Sur le modèle exact de ``write_activities``, qui ne change pas : supprime
    ``interim/days.nouveau/`` et ``interim/days.ancien/`` s'ils restent d'une écriture
    interrompue ; écrit tout dans ``days.nouveau/`` ; renomme l'ancien ``days/`` (s'il
    existe) en ``days.ancien/`` ; met ``days.nouveau/`` à sa place ; supprime
    ``days.ancien/``. Si ``days.nouveau/`` ne prend pas sa place, ``days.ancien/``
    reprend la sienne, et l'erreur se propage. ``interim/activities/`` n'est pas
    touché : deux échanges, pas un.

    Les jours s'écrivent un à un, dans l'ordre reçu (``records`` peut être un
    générateur) : un jour qui ne suit pas strictement le précédent (en double, ou non
    trié) lève ``ValueError`` (« Les jours doivent venir triés par date, chacun une
    seule fois. ») ; ``days.nouveau/`` est alors supprimé et rien n'est mis en place.
    """
    target = data_dir / DAYS_DIR
    new = target.with_name(target.name + _NEW_SUFFIX)
    old = target.with_name(target.name + _OLD_SUFFIX)
    _remove(new)
    _remove(old)
    try:
        new.mkdir(parents=True)
        previous: date | None = None
        for record in records:
            if previous is not None and not record.day > previous:
                raise ValueError(_UNSORTED_DAYS)
            previous = record.day
            name = record.day.isoformat() + DOCUMENT_SUFFIX
            (new / name).write_bytes(encode_interim(record))
        (new / TRAINING_STATUS_FILE).write_bytes(encode_interim(history))
        (new / DAYS_REPORT_FILE).write_bytes(encode_interim(report))
    except BaseException:
        _remove(new)
        raise
    if target.exists():
        target.rename(old)
    try:
        new.rename(target)
    except BaseException:
        if old.exists() and not target.exists():
            old.rename(target)
        raise
    _remove(old)


def _days_folder(data_dir: Path) -> Path:
    folder = data_dir / DAYS_DIR
    if not folder.is_dir():
        raise InterimError(f"{DAYS_DIR.name}/ manque dans interim/ : {_RUN_INGEST}")
    return folder


def _read_days_document(data_dir: Path, name: str) -> bytes:
    path = _days_folder(data_dir) / name
    try:
        return path.read_bytes()
    except FileNotFoundError:
        raise InterimError(
            f"{DAYS_DIR.name}/{name} manque dans interim/ : {_RUN_INGEST}"
        ) from None


def read_days(data_dir: Path) -> tuple[DayRecord, ...]:
    """Les documents des jours d'``interim/days/`` sous ``data_dir``, triés par jour.

    Dossier absent : ``InterimError`` (« days/ manque dans interim/ : lancer
    `mperf ingest`. »). Tout ce que le dossier porte, hors de ``training_status.json``
    et ``report.json``, est un document ``DayRecord`` nommé par sa date : un élément qui
    n'est pas un fichier, ou un document dont le jour n'est pas celui de son nom, lève
    ``InterimError`` (« interim/ incohérent : … ») ; un fichier qui n'est pas un
    document ``DayRecord`` lève ``CodecError``.
    """
    folder = _days_folder(data_dir)
    paths = sorted(
        (
            path
            for path in folder.iterdir()
            if path.name not in (TRAINING_STATUS_FILE, DAYS_REPORT_FILE)
        ),
        key=lambda path: path.name,
    )
    if any(not path.is_file() for path in paths):
        raise InterimError(
            "interim/ incohérent : interim/days/ porte autre chose que des documents. "
            "Lancer `mperf ingest`."
        )
    records: list[DayRecord] = []
    for path in paths:
        record = decode_interim(path.read_bytes(), DayRecord)
        if path.name != record.day.isoformat() + DOCUMENT_SUFFIX:
            raise InterimError(
                "interim/ incohérent : un jour porte une autre date que son nom de "
                "fichier. Lancer `mperf ingest`."
            )
        records.append(record)
    return tuple(sorted(records, key=lambda record: record.day))


def read_training_status(data_dir: Path) -> TrainingStatusHistory:
    """Le document de Training Status ; dossier ou fichier absent : ``InterimError``
    (« days/ manque… », « days/training_status.json manque dans interim/ : lancer
    `mperf ingest`. »)."""
    data = _read_days_document(data_dir, TRAINING_STATUS_FILE)
    return decode_interim(data, TrainingStatusHistory)


def read_days_report(data_dir: Path) -> DaysReport:
    """Le rapport des jours de la dernière ingestion ; dossier ou fichier absent :
    ``InterimError`` (« days/ manque… », « days/report.json manque dans interim/ :
    lancer `mperf ingest`. »)."""
    data = _read_days_document(data_dir, DAYS_REPORT_FILE)
    return decode_interim(data, DaysReport)
