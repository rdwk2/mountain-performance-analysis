"""Les fichiers de l'interface : ``list_files``, ``list_curves``, ``add_file`` (§ 6.4 et
§ 8.2 du brief M5-1).

Le dossier des données est celui de ``tests/conftest.py`` (``data_dir()``, neuf pour
chaque test). Le dossier temporaire du système est redirigé vers un sous-dossier
dédié de ``tmp_path``, créé vide, et vérifié vide après chaque appel d'``add_file``,
quelle qu'en soit l'issue (précision 4 de la relecture du plan) : un dossier de
vérification jamais retiré s'y verrait, avec ou sans préfixe.
"""

import tempfile
from pathlib import Path

import pytest

from mountain_perf.config import data_dir
from mountain_perf.data_files import (
    AddFileError,
    AddOutcome,
    FileKind,
    add_file,
    list_curves,
    list_files,
)

FIXTURES = Path(__file__).parent / "fixtures"
ROUTE = FIXTURES / "mini_11.gpx"
TRACE = FIXTURES / "appariement_trace_x01.gpx"
CURVE = FIXTURES / "courbe_synthetique.csv"
COMPANION = FIXTURES / "courbe_synthetique.meta.json"

SINGLE_POINT_GPX = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
    b'<trkpt lat="45" lon="6"><ele>1500</ele></trkpt>'
    b"</trkseg></trk></gpx>\n"
)


@pytest.fixture(autouse=True)
def system_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Le dossier temporaire du système, redirigé vers ``tmp_path / "systeme"``,
    créé vide."""
    systeme = tmp_path / "systeme"
    systeme.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(systeme))
    return systeme


def _tree(root: Path) -> list[str]:
    """Tout ce qui existe sous ``root``, dossiers compris."""
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))


def _add(
    system_temp: Path,
    kind: FileKind,
    name: str,
    content: bytes,
    *,
    root: Path | None = None,
) -> AddOutcome:
    """``add_file``, puis le dossier temporaire du système vérifié vide, quelle que soit
    l'issue."""
    try:
        return add_file(data_dir() if root is None else root, kind, name, content)
    finally:
        assert list(system_temp.iterdir()) == []


# ---------------------------------------------------------------------------
# list_files, list_curves
# ---------------------------------------------------------------------------


def test_list_files_without_folder_is_empty() -> None:
    assert list_files(data_dir(), FileKind.ROUTE) == ()
    assert list_files(data_dir(), FileKind.OUTING) == ()


def test_list_files_sorted_case_insensitive_suffix_files_only() -> None:
    routes = data_dir() / "routes"
    routes.mkdir()
    for name in ("b.gpx", "a.GPX", "c.gpx", "notes.txt"):
        (routes / name).write_bytes(b"")
    (routes / "x.gpx").mkdir()
    assert [path.name for path in list_files(data_dir(), FileKind.ROUTE)] == [
        "a.GPX",
        "b.gpx",
        "c.gpx",
    ]
    assert list_files(data_dir(), FileKind.ROUTE)[0] == routes / "a.GPX"


def test_each_kind_reads_its_folder() -> None:
    for folder, name in (("routes", "prepare.gpx"), ("sorties", "sortie.gpx")):
        (data_dir() / folder).mkdir()
        (data_dir() / folder / name).write_bytes(b"")
    assert [p.name for p in list_files(data_dir(), FileKind.ROUTE)] == ["prepare.gpx"]
    assert [p.name for p in list_files(data_dir(), FileKind.OUTING)] == ["sortie.gpx"]


def test_list_curves_without_folder_is_empty() -> None:
    assert list_curves(data_dir()) == ()


def test_list_curves_needs_the_companion_and_sorts() -> None:
    reference = data_dir() / "reference"
    reference.mkdir()
    for stem in ("z", "a"):
        (reference / f"{stem}.csv").write_bytes(CURVE.read_bytes())
        (reference / f"{stem}.meta.json").write_bytes(COMPANION.read_bytes())
    (reference / "seule.csv").write_bytes(CURVE.read_bytes())
    (reference / "M.CSV").write_bytes(CURVE.read_bytes())
    (reference / "M.meta.json").write_bytes(COMPANION.read_bytes())
    assert [path.name for path in list_curves(data_dir())] == [
        "M.CSV",
        "a.csv",
        "z.csv",
    ]


# ---------------------------------------------------------------------------
# add_file : le nom
# ---------------------------------------------------------------------------

NAME_REFUSALS = [
    ("", "Nom de fichier invalide : ''."),
    (".", "Nom de fichier invalide : '.'."),
    ("..", "Nom de fichier invalide : '..'."),
    (" x.gpx", "Nom de fichier invalide : ' x.gpx'."),
    ("x.gpx ", "Nom de fichier invalide : 'x.gpx '."),
    *[
        (
            f"a{character}b.gpx",
            f"Nom de fichier invalide (caractère interdit) : {f'a{character}b.gpx'!r}.",
        )
        for character in '<>:"/\\|?*'
    ],
    ("x.txt", "Le fichier doit être un .gpx : 'x.txt'."),
    (".gpx", "Le fichier doit être un .gpx : '.gpx'."),
    ("CON.gpx", "Nom réservé par Windows : 'CON.gpx'."),
    ("com1.GPX", "Nom réservé par Windows : 'com1.GPX'."),
]


@pytest.mark.parametrize("kind", [FileKind.ROUTE, FileKind.OUTING])
@pytest.mark.parametrize("folder_exists", [False, True])
@pytest.mark.parametrize(("name", "message"), NAME_REFUSALS)
def test_name_refusals_write_nothing(
    system_temp: Path, kind: FileKind, folder_exists: bool, name: str, message: str
) -> None:
    if folder_exists:
        (data_dir() / ("routes" if kind is FileKind.ROUTE else "sorties")).mkdir()
    before = _tree(data_dir())
    with pytest.raises(AddFileError) as error:
        _add(system_temp, kind, name, ROUTE.read_bytes())
    assert str(error.value) == message
    assert _tree(data_dir()) == before


# ---------------------------------------------------------------------------
# add_file : un fichier du même nom, le contenu
# ---------------------------------------------------------------------------


def test_a_valid_route_is_added(system_temp: Path) -> None:
    outcome = _add(system_temp, FileKind.ROUTE, "mini_11.gpx", ROUTE.read_bytes())
    assert outcome is AddOutcome.ADDED
    assert (data_dir() / "routes" / "mini_11.gpx").read_bytes() == ROUTE.read_bytes()
    assert _tree(data_dir()) == ["routes", "routes/mini_11.gpx"]


def test_the_same_content_twice_is_already_present(system_temp: Path) -> None:
    _add(system_temp, FileKind.ROUTE, "mini_11.gpx", ROUTE.read_bytes())
    target = data_dir() / "routes" / "mini_11.gpx"
    stamp = target.stat().st_mtime_ns
    outcome = _add(system_temp, FileKind.ROUTE, "mini_11.gpx", ROUTE.read_bytes())
    assert outcome is AddOutcome.ALREADY_PRESENT
    assert target.read_bytes() == ROUTE.read_bytes()
    assert target.stat().st_mtime_ns == stamp


def test_the_same_name_with_another_content_is_refused(system_temp: Path) -> None:
    _add(system_temp, FileKind.ROUTE, "mini_11.gpx", ROUTE.read_bytes())
    target = data_dir() / "routes" / "mini_11.gpx"
    stamp = target.stat().st_mtime_ns
    with pytest.raises(AddFileError) as error:
        _add(system_temp, FileKind.ROUTE, "mini_11.gpx", TRACE.read_bytes())
    assert str(error.value) == (
        "mini_11.gpx existe déjà dans routes/, avec un autre contenu : "
        "renomme le fichier."
    )
    assert target.read_bytes() == ROUTE.read_bytes()
    assert target.stat().st_mtime_ns == stamp


@pytest.mark.parametrize(
    "content", [b"<gpx>pas du XML", SINGLE_POINT_GPX], ids=["xml", "un-point"]
)
def test_an_unreadable_route_is_refused(system_temp: Path, content: bytes) -> None:
    with pytest.raises(AddFileError) as error:
        _add(system_temp, FileKind.ROUTE, "faux.gpx", content)
    assert str(error.value).startswith(
        "faux.gpx ne se lit pas comme un tracé préparé : "
    )
    assert error.value.__cause__ is None
    assert _tree(data_dir()) == []


def test_a_route_without_time_is_refused_as_an_outing(system_temp: Path) -> None:
    with pytest.raises(AddFileError) as error:
        _add(system_temp, FileKind.OUTING, "mini_11.gpx", ROUTE.read_bytes())
    assert str(error.value) == (
        "mini_11.gpx ne se lit pas comme une trace horodatée : "
        "mini_11.gpx, trkpt[0].time : instant manquant."
    )
    assert error.value.__cause__ is None
    assert not (data_dir() / "sorties").exists()
    assert _tree(data_dir()) == []
    outcome = _add(system_temp, FileKind.ROUTE, "mini_11.gpx", ROUTE.read_bytes())
    assert outcome is AddOutcome.ADDED


def test_a_timed_trace_is_added_as_an_outing(system_temp: Path) -> None:
    outcome = _add(system_temp, FileKind.OUTING, "trace.gpx", TRACE.read_bytes())
    assert outcome is AddOutcome.ADDED
    assert (data_dir() / "sorties" / "trace.gpx").read_bytes() == TRACE.read_bytes()
    assert _tree(data_dir()) == ["sorties", "sorties/trace.gpx"]


def test_the_kind_folder_is_created_never_its_parent(
    system_temp: Path, tmp_path: Path
) -> None:
    missing = tmp_path / "absent"
    with pytest.raises(FileNotFoundError):
        _add(
            system_temp, FileKind.ROUTE, "mini_11.gpx", ROUTE.read_bytes(), root=missing
        )
    assert not missing.exists()


def test_creation_is_exclusive(
    system_temp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un fichier de même nom apparu pendant la vérification : refusé, le fichier
    apparu inchangé."""
    appeared = b"apparu pendant la verification"

    def reader_that_races(path: Path) -> None:
        (data_dir() / "routes").mkdir()
        (data_dir() / "routes" / path.name).write_bytes(appeared)

    monkeypatch.setattr("mountain_perf.data_files.read_gpx", reader_that_races)
    with pytest.raises(AddFileError) as error:
        _add(system_temp, FileKind.ROUTE, "mini_11.gpx", ROUTE.read_bytes())
    assert str(error.value) == (
        "mini_11.gpx est apparu dans routes/ pendant l'ajout : rien n'est écrasé."
    )
    assert error.value.__cause__ is None
    assert (data_dir() / "routes" / "mini_11.gpx").read_bytes() == appeared
