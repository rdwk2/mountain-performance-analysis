"""Les fichiers de l'interface (M5), sous ``MPA_DATA_DIR``.

Trois dossiers :

- ``routes/`` — les tracés préparés, GPX, ajoutés à la main ou par l'interface ;
- ``sorties/`` — les traces des sorties, GPX horodatés, ajoutées par l'interface ;
- ``reference/`` — les courbes, CSV et leur compagnon ``.meta.json``, lues seulement.

L'interface n'écrit que par :func:`add_file`, et seulement dans ``routes/`` et
``sorties/``. Un fichier est vérifié avant d'être écrit et n'en écrase jamais un autre ;
rien n'est jamais supprimé.
"""

import tempfile
from enum import StrEnum
from pathlib import Path
from typing import Final

from mountain_perf.gpx.reader import GpxError, read_gpx
from mountain_perf.gpx.trace_reader import TraceError, read_trace
from mountain_perf.validation import ContractError


class FileKind(StrEnum):
    """La sorte d'un fichier ajouté : un tracé préparé, ou la trace d'une sortie."""

    ROUTE = "route"
    OUTING = "outing"


FOLDERS: Final = {FileKind.ROUTE: "routes", FileKind.OUTING: "sorties"}
"""Le dossier de chaque sorte, sous ``MPA_DATA_DIR``."""

CURVES_FOLDER: Final = "reference"
"""Le dossier des courbes, sous ``MPA_DATA_DIR`` : lu, jamais écrit par l'interface."""

FORBIDDEN_CHARACTERS: Final = frozenset('<>:"/\\|?*')
"""Les caractères refusés dans un nom de fichier (ceux que Windows refuse, et les deux
séparateurs de dossier)."""

RESERVED_STEMS: Final = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)
"""Les noms que Windows réserve à ses périphériques, quelle que soit l'extension."""

GPX_SUFFIX: Final = ".gpx"
CURVE_SUFFIX: Final = ".csv"
COMPANION_SUFFIX: Final = ".meta.json"


class AddFileError(ValueError):
    """Un ajout refusé ; rien n'est écrit."""


class AddOutcome(StrEnum):
    """L'issue d'un ajout accepté : écrit, ou déjà présent à l'identique."""

    ADDED = "added"
    ALREADY_PRESENT = "already_present"


def _files(folder: Path, suffix: str) -> list[Path]:
    """Les fichiers (pas les dossiers) de ``folder`` d'extension ``suffix``, sans casse,
    triés par nom ; aucun si le dossier n'existe pas."""
    if not folder.is_dir():
        return []
    return sorted(
        (
            path
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() == suffix
        ),
        key=lambda path: path.name,
    )


def list_files(data_dir: Path, kind: FileKind) -> tuple[Path, ...]:
    """Les GPX du dossier de ``kind``, triés par nom ; ``()`` sans dossier."""
    return tuple(_files(data_dir / FOLDERS[kind], GPX_SUFFIX))


def list_curves(data_dir: Path) -> tuple[Path, ...]:
    """Les courbes de ``reference/`` : les CSV qui ont leur compagnon
    ``<stem>.meta.json``, triés par nom ; ``()`` sans dossier."""
    return tuple(
        path
        for path in _files(data_dir / CURVES_FOLDER, CURVE_SUFFIX)
        if path.with_suffix(COMPANION_SUFFIX).is_file()
    )


def _check_name(name: str) -> None:
    if name in ("", ".", "..") or name != name.strip():
        raise AddFileError(f"Nom de fichier invalide : {name!r}.")
    if any(character in FORBIDDEN_CHARACTERS for character in name):
        raise AddFileError(f"Nom de fichier invalide (caractère interdit) : {name!r}.")
    if not name.lower().endswith(GPX_SUFFIX) or len(name) == len(GPX_SUFFIX):
        raise AddFileError(f"Le fichier doit être un .gpx : {name!r}.")
    if name[: -len(GPX_SUFFIX)].lower() in RESERVED_STEMS:
        raise AddFileError(f"Nom réservé par Windows : {name!r}.")


def _check_content(kind: FileKind, name: str, content: bytes) -> None:
    """Lit le contenu comme le lira la page : écrit sous son nom dans un dossier
    temporaire du système, hors de ``MPA_DATA_DIR`` (le lecteur de traces nomme le
    fichier qu'il lit), retiré à la sortie du bloc."""
    with tempfile.TemporaryDirectory(prefix="mpa-ajout-") as scratch:
        copy = Path(scratch) / name
        copy.write_bytes(content)
        try:
            if kind is FileKind.ROUTE:
                read_gpx(copy)
            else:
                read_trace([copy])
        except (GpxError, TraceError, ContractError) as error:
            what = (
                "un tracé préparé" if kind is FileKind.ROUTE else "une trace horodatée"
            )
            raise AddFileError(f"{name} ne se lit pas comme {what} : {error}") from None


def add_file(data_dir: Path, kind: FileKind, name: str, content: bytes) -> AddOutcome:
    """Ajoute le fichier ``name`` de contenu ``content`` au dossier de ``kind``.

    Dans cet ordre : le nom (``AddFileError`` s'il est vide, ``.`` ou ``..``, entouré
    d'espaces, porte un caractère interdit, n'est pas un ``.gpx`` ou est réservé par
    Windows) ; un fichier du même nom déjà présent (même contenu : ``ALREADY_PRESENT``,
    rien n'est écrit ; autre contenu : refusé) ; le contenu, lu par ``read_gpx`` (un
    préparé) ou ``read_trace`` (une sortie) ; enfin le dossier de la sorte créé s'il
    manque (jamais son parent) et la création exclusive du fichier (apparu
    entre-temps : refusé). Rend ``ADDED``.

    Après un refus, rien n'est écrit sous ``data_dir``, pas même le dossier de la sorte.
    Jamais d'écrasement, jamais de suppression.
    """
    _check_name(name)
    folder_name = FOLDERS[kind]
    folder = data_dir / folder_name
    target = folder / name
    if target.exists():
        if target.read_bytes() == content:
            return AddOutcome.ALREADY_PRESENT
        raise AddFileError(
            f"{name} existe déjà dans {folder_name}/, avec un autre contenu : "
            "renomme le fichier."
        )
    _check_content(kind, name, content)
    folder.mkdir(exist_ok=True)
    try:
        with target.open("xb") as stream:
            stream.write(content)
    except FileExistsError:
        raise AddFileError(
            f"{name} est apparu dans {folder_name}/ pendant l'ajout : rien n'est "
            "écrasé."
        ) from None
    return AddOutcome.ADDED
