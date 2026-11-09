"""Le journal de l'athlète, ``journal.csv`` (``mountain_perf.analyse.journal``, AN2-2) :
des fichiers inventés, écrits octet par octet ; dates de l'an 2000."""

from __future__ import annotations

import dataclasses
import hashlib
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from mountain_perf.analyse.journal import (
    EMPTY_END_CAUSE,
    ENCODING_CAUSE,
    END_BEFORE_START_CAUSE,
    FIELD_COUNT_CAUSE,
    JOURNAL_COLUMNS,
    JOURNAL_FILE,
    MISSING_COLUMN_CAUSE,
    READ_CAUSE,
    REPEATED_COLUMN_CAUSE,
    REQUIRED_COLUMNS,
    UNKNOWN_COLUMN_CAUSE,
    UNKNOWN_TYPE_CAUSE,
    UNNAMED_COLUMN_CAUSE,
    UNNAMED_FIELD_CAUSE,
    UNREADABLE_CSV_CAUSE,
    UNREADABLE_DATE_CAUSE,
    Journal,
    JournalError,
    JournalEvent,
    journal_types_by_day,
    read_journal,
)
from mountain_perf.schemas import JournalEventType
from mountain_perf.validation import ContractError

BOM = b"\xef\xbb\xbf"
ILLNESS, RACE = JournalEventType.ILLNESS, JournalEventType.RACE
REFERENCE = [
    (date(2000, 1, 12), date(2000, 1, 14), ILLNESS, 2),
    (date(2000, 2, 5), date(2000, 2, 5), RACE, 3),
]
HEADER = "debut;fin;type;note"
MALADIE = "2000-01-12;2000-01-14;maladie;"


def write(folder: Path, data: bytes) -> Journal:
    (folder / JOURNAL_FILE).write_bytes(data)
    return read_journal(folder)


def text(*lines: str, end: str = "\n") -> bytes:
    return end.join(lines).encode("utf-8") + end.encode("utf-8")


def seen(journal: Journal) -> list[tuple[date, date, JournalEventType, int]]:
    return [(e.start, e.end, e.event_type, e.line) for e in journal.events]


def refused(folder: Path, data: bytes, message: str) -> None:
    (folder / JOURNAL_FILE).write_bytes(data)
    with pytest.raises(JournalError) as caught:
        read_journal(folder)
    assert str(caught.value) == message
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def at(line: int, cause: str) -> str:
    return f"journal.csv, ligne {line} : {cause}"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- le fichier absent, l'empreinte --------------------------------------------------


def test_the_name_of_the_file() -> None:
    assert JOURNAL_FILE == "journal.csv"


def test_without_a_file_no_event_and_no_fingerprint(tmp_path: Path) -> None:
    assert read_journal(tmp_path) == Journal((), None)
    assert read_journal(tmp_path / "absent") == Journal((), None)


def test_a_header_alone(tmp_path: Path) -> None:
    data = b"debut;fin;type;note\r\n"
    assert write(tmp_path, data) == Journal((), sha(data))


def test_the_fingerprint_is_that_of_the_bytes_read(tmp_path: Path) -> None:
    data = BOM + text(HEADER, "2000-01-12;2000-01-14;maladie;une note")
    assert write(tmp_path, data).sha256 == sha(data)
    one = write(tmp_path, text(HEADER, "2000-01-12;2000-01-14;maladie;a"))
    other = write(tmp_path, text(HEADER, "2000-01-12;2000-01-14;maladie;b"))
    assert one.events == other.events
    assert one.sha256 != other.sha256
    plain = text(HEADER, MALADIE)
    without, with_bom = write(tmp_path, plain), write(tmp_path, BOM + plain)
    assert without.events == with_bom.events
    assert without.sha256 != with_bom.sha256
    assert with_bom.sha256 == sha(BOM + plain)


def test_the_bytes_are_read_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / JOURNAL_FILE).write_bytes(text(HEADER, "2000-03-01;2000-03-01;course;"))
    returned = text(HEADER, MALADIE)
    calls: list[Path] = []

    def read_bytes(self: Path) -> bytes:
        calls.append(self)
        return returned

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    journal = read_journal(tmp_path)
    assert calls == [tmp_path / JOURNAL_FILE]
    assert seen(journal) == [REFERENCE[0]]
    assert journal.sha256 == sha(returned)


def test_a_file_that_exists_but_cannot_be_read(tmp_path: Path) -> None:
    (tmp_path / JOURNAL_FILE).mkdir()
    with pytest.raises(JournalError) as caught:
        read_journal(tmp_path)
    message = str(caught.value)
    prefix, suffix = "journal.csv : lecture impossible (", ")"
    assert message.startswith(prefix)
    assert message.endswith(suffix)
    reason = message[len(prefix) : -len(suffix)]
    assert reason
    assert str(tmp_path) not in reason
    assert "Error" not in reason
    assert not any(c.isdigit() for c in reason)
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None


# --- les formes admises --------------------------------------------------------------

M = "2000-01-12"
N = "2000-01-14"
C = "2000-02-05"

FORMS = {
    "excel": BOM
    + text(HEADER, f"{M};{N};maladie;", f"{C};{C};course;une note", end="\r\n"),
    "virgule": text("debut,fin,type,note", f"{M},{N},maladie,", f"{C},{C},course,"),
    "sans note": BOM
    + text("debut,fin,type", f"{M},{N},maladie", f"{C},{C},course", end="\r\n"),
    "cr": text(HEADER, f"{M};{N};maladie;", f"{C};{C};course;", end="\r"),
    "majuscules": text("DEBUT;FIN;TYPE;NOTE", f"{M};{N};maladie;", f"{C};{C};course;"),
    "casse et blancs": text(
        " Debut ;\tFin\t; TyPe ;nOtE", f"{M};{N};maladie;", f"{C};{C};course;"
    ),
    "permutées": text("type;note;fin;debut", f"maladie;;{N};{M}", f"course;;{C};{C}"),
    "sans note lf": text("debut;fin;type", f"{M};{N};maladie", f"{C};{C};course"),
    "guillemets": text(
        HEADER, f'"{M}";"{N}";"maladie";"a ; b ""c"""', f'{C};{C};course;""'
    ),
    "virgule entre guillemets": text(
        "debut,fin,type,note", f'{M},{N},maladie,"a, b"', f"{C},{C},course,"
    ),
    "blancs après virgules": text(
        "debut, fin, type, note", f"{M}, {N}, maladie, ", f"{C}, {C}, course, "
    ),
    "blancs autour des dates": text(
        HEADER,
        f" {M}\t;\u00a0{N} ;maladie;",
        f'" {C} ";"\t{C}\u00a0";course;',
    ),
    "type en majuscules": text(HEADER, f"{M};{N}; MALADIE ;", f"{C};{C};Course;"),
    "sans fin de ligne finale": (
        f"{HEADER}\n{M};{N};maladie;\n{C};{C};course;".encode()
    ),
    "note hors ascii": text(
        HEADER, f"{M};{N};maladie;fièvre, « été »", f"{C};{C};course;"
    ),
}


@pytest.mark.parametrize("data", FORMS.values(), ids=FORMS.keys())
def test_each_admitted_form_gives_the_two_events(tmp_path: Path, data: bytes) -> None:
    assert seen(write(tmp_path, data)) == REFERENCE


def test_the_separator_comes_from_the_header(tmp_path: Path) -> None:
    one = write(tmp_path, text(HEADER, f"{M};{N};maladie;a, b"))
    assert len(one.events) == 1
    two = write(tmp_path, text("debut,fin,type,note", f"{M},{N},maladie,a; b"))
    assert len(two.events) == 1
    refused(
        tmp_path,
        text("debut;fin;type", f"{M},{N},maladie"),
        at(2, FIELD_COUNT_CAUSE.format(found=1, expected=3)),
    )
    refused(
        tmp_path,
        text('debut;fin;type;"note,x"', f"{M};{N};maladie;"),
        at(1, UNKNOWN_COLUMN_CAUSE.format(position=4)),
    )


def test_only_cr_and_lf_end_a_line(tmp_path: Path) -> None:
    note = "a\u000bb\u000cc\u001cd\u001de\u001ef\u0085g\u2028h\u2029i"
    journal = write(
        tmp_path, text(HEADER, f"{M};{N};maladie;{note}", f"{C};{C};course;")
    )
    assert seen(journal) == REFERENCE


def test_an_empty_line_is_ignored_and_counted(tmp_path: Path) -> None:
    data = text(
        "",
        ";;;",
        "   \t",
        HEADER,
        "",
        f"{M};{N};maladie;",
        ";;",
        '  ;"  ";;',
        f"{C};{C};course;",
        "",
        ";;;;;",
    )
    assert [e.line for e in write(tmp_path, data).events] == [6, 9]
    data = text(",,,", "", "debut,fin,type", f"{M},{N},maladie")
    assert [e.line for e in write(tmp_path, data).events] == [4]


def _multiline(extra: bytes) -> bytes:
    return (
        b"debut;fin;type;note\n"
        b'2000-01-12;2000-01-14;maladie;"un\r\ndeux\n\nquatre"\n'
        b"2000-02-05;2000-02-05;course;\n"
        b'2000-03-01;2000-03-01;autre;"un\ndeux"\n' + extra
    )


def test_a_record_on_several_lines_has_the_number_of_its_first(tmp_path: Path) -> None:
    (tmp_path / JOURNAL_FILE).write_bytes(_multiline(b"2000-04-01;2000-4-1;autre;\n"))
    with pytest.raises(JournalError) as caught:
        read_journal(tmp_path)
    assert str(caught.value).startswith("journal.csv, ligne 9 : ")
    assert [e.line for e in write(tmp_path, _multiline(b"")).events] == [2, 6, 7]


def test_each_type_is_read(tmp_path: Path) -> None:
    lines = [f"{M};{M};{member.value};" for member in JournalEventType]
    journal = write(tmp_path, text(HEADER, *lines))
    assert [e.event_type for e in journal.events] == list(JournalEventType)


def test_events_keep_the_order_of_the_file(tmp_path: Path) -> None:
    journal = write(
        tmp_path,
        text(HEADER, f"{C};{C};course;", f"{M};{N};maladie;", f"{M};{N};maladie;"),
    )
    assert [e.line for e in journal.events] == [2, 3, 4]
    assert [e.event_type for e in journal.events] == [RACE, ILLNESS, ILLNESS]


def test_the_note_is_not_kept() -> None:
    assert [f.name for f in dataclasses.fields(JournalEvent)] == [
        "start",
        "end",
        "event_type",
        "line",
    ]
    assert [f.name for f in dataclasses.fields(Journal)] == ["events", "sha256"]


def test_the_columns() -> None:
    assert REQUIRED_COLUMNS == ("debut", "fin", "type")
    assert JOURNAL_COLUMNS == ("debut", "fin", "type", "note")


# --- la marge d'Excel ----------------------------------------------------------------


@pytest.mark.parametrize(
    "data",
    [
        text(
            "debut;fin;type;note;;",
            f"{M};{N};maladie;;;",
            f"{C};{C};course;;;",
            end="\r\n",
        ),
        text(
            "debut,fin,type,note, ,\t",
            f'{M},{N},maladie,," ",',
            f"{C},{C},course,, ,",
        ),
        text("debut;fin;type;", ";;;;", f"{M};{N};maladie;", f"{C};{C};course;"),
    ],
)
def test_a_margin_of_unnamed_columns_is_ignored(tmp_path: Path, data: bytes) -> None:
    assert [(s, e, t) for s, e, t, _ in seen(write(tmp_path, data))] == [
        r[:3] for r in REFERENCE
    ]


def test_a_header_with_its_margin_alone(tmp_path: Path) -> None:
    data = text("debut;fin;type;;")
    assert write(tmp_path, data) == Journal((), sha(data))


@pytest.mark.parametrize(
    ("line", "position"),
    [("2000-02-05;2000-02-05;course;;x;", 5), ("2000-02-05;2000-02-05;course;;;x", 6)],
)
def test_a_non_empty_field_in_the_margin_stops(
    tmp_path: Path, line: str, position: int
) -> None:
    refused(
        tmp_path,
        text("debut;fin;type;note;;", f"{M};{N};maladie;;;", line),
        at(3, UNNAMED_FIELD_CAUSE.format(position=position)),
    )


@pytest.mark.parametrize(
    ("header", "position"),
    [
        ("debut;;fin;type", 2),
        (";debut;fin;type", 1),
        ("debut;fin; \t;type;;", 3),
        ("debut;fin;type;;note", 4),
    ],
)
def test_an_unnamed_column_before_a_named_one(
    tmp_path: Path, header: str, position: int
) -> None:
    refused(
        tmp_path,
        text(header),
        at(1, UNNAMED_COLUMN_CAUSE.format(position=position)),
    )


def test_the_columns_are_checked_in_order(tmp_path: Path) -> None:
    refused(
        tmp_path,
        text("debut;;x;fin;type"),
        at(1, UNNAMED_COLUMN_CAUSE.format(position=2)),
    )


def test_the_margin_counts_in_the_number_of_fields(tmp_path: Path) -> None:
    refused(
        tmp_path,
        text("debut;fin;type;note;;", f"{M};{N};maladie;"),
        at(2, FIELD_COUNT_CAUSE.format(found=4, expected=6)),
    )


# --- les causes d'arrêt --------------------------------------------------------------

ENCODING = f"journal.csv : {ENCODING_CAUSE}"
ENCODED_FAULTS = {
    "latin-1": text(HEADER).decode().encode()
    + f"{M};{N};maladie;été\n".encode("latin-1"),
    "utf-16": "debut;fin;type\n".encode("utf-16"),
    "bom utf-16": b"\xff\xfedebut;fin;type\n",
    "trop long": b"\xc0\xaf",
    "substitution": b"\xed\xa0\x80",
}


@pytest.mark.parametrize("data", ENCODED_FAULTS.values(), ids=ENCODED_FAULTS.keys())
def test_bytes_that_are_not_utf8(tmp_path: Path, data: bytes) -> None:
    refused(tmp_path, data, ENCODING)


@pytest.mark.parametrize(
    "data",
    [b"", BOM, b"\n", b"\r\n\r\n", b"  \t\n", b";;;\n", b",,\n", b"  ;\n"],
)
def test_an_empty_file_has_no_event_and_its_fingerprint(
    tmp_path: Path, data: bytes
) -> None:
    assert write(tmp_path, data) == Journal((), sha(data))


def test_a_single_non_empty_line_is_a_header(tmp_path: Path) -> None:
    refused(
        tmp_path,
        text("", ";;", "x", ""),
        at(3, UNKNOWN_COLUMN_CAUSE.format(position=1)),
    )
    refused(
        tmp_path,
        BOM + text(";;fin;;"),
        at(1, UNNAMED_COLUMN_CAUSE.format(position=1)),
    )


def _missing(column: str) -> str:
    return MISSING_COLUMN_CAUSE.format(column=column)


def _unknown(position: int) -> str:
    return UNKNOWN_COLUMN_CAUSE.format(position=position)


def _repeated(column: str) -> str:
    return REPEATED_COLUMN_CAUSE.format(column=column)


@pytest.mark.parametrize(
    ("data", "line", "cause"),
    [
        (text("fin;type;note"), 1, _missing("debut")),
        (text("debut;type"), 1, _missing("fin")),
        (text("debut,fin"), 1, _missing("type")),
        (text("note"), 1, _missing("debut")),
        (text("", ";;", "type;note"), 3, _missing("debut")),
        (text("debut;fin;type;remarque"), 1, _unknown(4)),
        (text("début;fin;type"), 1, _unknown(1)),
        (text("debut;fin;x;type"), 1, _unknown(3)),
        (BOM + BOM + text("debut;fin;type"), 1, _unknown(1)),
        (text("debut;fin;type;note;NOTE"), 1, _repeated("note")),
        (text("debut;fin;type; Debut"), 1, _repeated("debut")),
        (text("debut;debut;x"), 1, _repeated("debut")),
        (text("debut;x;debut"), 1, _unknown(2)),
        (text("fin;fin"), 1, _repeated("fin")),
    ],
)
def test_the_refusals_of_the_header(
    tmp_path: Path, data: bytes, line: int, cause: str
) -> None:
    refused(tmp_path, data, at(line, cause))


def test_a_field_under_a_trailing_unnamed_column(tmp_path: Path) -> None:
    refused(
        tmp_path,
        text("debut;fin;type;note;", f"{M};{N};maladie;;x"),
        at(2, UNNAMED_FIELD_CAUSE.format(position=5)),
    )


@pytest.mark.parametrize(
    ("line", "found"),
    [
        (f"{M};{N};maladie", 3),
        (f"{M};{N};maladie;;;", 6),
        (f"{M};{N};maladie;a;b", 5),
        ("x", 1),
        (";;;;x", 5),
    ],
)
def test_a_line_has_as_many_fields_as_the_header(
    tmp_path: Path, line: str, found: int
) -> None:
    refused(
        tmp_path,
        text(HEADER, line),
        at(2, FIELD_COUNT_CAUSE.format(found=found, expected=4)),
    )


def test_a_comma_line_with_a_field_too_many(tmp_path: Path) -> None:
    refused(
        tmp_path,
        text("debut,fin,type", f"{M},{N},maladie,"),
        at(2, FIELD_COUNT_CAUSE.format(found=4, expected=3)),
    )


BAD_DATES = [
    "12/01/2000",
    "2000/01/12",
    "2000-1-12",
    "2000-01-1",
    "20000112",
    "2000-01-12T00:00",
    "2000-01-12 00:00",
    "2000-W02-3",
    "2000- 01-12",
    "2000 -01-12",
    "2000-01- 12",
    "2000-01-1 2",
    "2000-02-30",
    "2001-02-29",
    "2000-13-01",
    "2000-00-10",
    "0000-01-01",
    "+2000-01-12",
    "".join(chr(0x660 + int(c)) if c.isdigit() else c for c in "2000-01-12"),
    "".join(chr(0xFF10 + int(c)) if c.isdigit() else c for c in "2000-01-12"),
    "x",
]


@pytest.mark.parametrize("value", [*BAD_DATES, "", "   "])
def test_a_bad_start_date(tmp_path: Path, value: str) -> None:
    refused(
        tmp_path,
        text(HEADER, f"{value};{N};maladie;"),
        at(2, UNREADABLE_DATE_CAUSE.format(column="debut")),
    )


@pytest.mark.parametrize("value", BAD_DATES)
def test_a_bad_end_date(tmp_path: Path, value: str) -> None:
    refused(
        tmp_path,
        text(HEADER, f"{M};{value};maladie;"),
        at(2, UNREADABLE_DATE_CAUSE.format(column="fin")),
    )


@pytest.mark.parametrize("day", ["0001-01-01", "9999-12-31", "2000-02-29"])
def test_extreme_dates_are_read(tmp_path: Path, day: str) -> None:
    journal = write(tmp_path, text(HEADER, f"{day};{day};autre;"))
    assert journal.events[0].start == date.fromisoformat(day)


@pytest.mark.parametrize("value", ["", "   ", '""', '"   "'])
def test_an_empty_end(tmp_path: Path, value: str) -> None:
    refused(tmp_path, text(HEADER, f"{M};{value};maladie;"), at(2, EMPTY_END_CAUSE))


@pytest.mark.parametrize(
    ("start", "end"), [("2000-01-14", "2000-01-13"), ("2000-01-01", "1999-12-31")]
)
def test_an_end_before_the_start(tmp_path: Path, start: str, end: str) -> None:
    refused(
        tmp_path,
        text(HEADER, f"{start};{end};maladie;"),
        at(2, END_BEFORE_START_CAUSE),
    )


def test_an_end_equal_to_the_start_is_admitted(tmp_path: Path) -> None:
    assert len(write(tmp_path, text(HEADER, f"{M};{M};maladie;")).events) == 1


@pytest.mark.parametrize(
    "value",
    [
        "grippe",
        "déplacement",
        "Séjour_altitude",
        "étalon",
        "déménagement",
        "",
        "   ",
        "mal adie",
        "maladie_",
        "1",
    ],
)
def test_an_unknown_type(tmp_path: Path, value: str) -> None:
    refused(tmp_path, text(HEADER, f"{M};{N};{value};"), at(2, UNKNOWN_TYPE_CAUSE))


def test_the_causes_say_what_is_admitted() -> None:
    assert UNKNOWN_TYPE_CAUSE == (
        "type inconnu (types admis : maladie, blessure, course, deplacement, "
        "demenagement, sejour_altitude, etalon, autre)"
    )
    assert "AAAA-MM-JJ" in UNREADABLE_DATE_CAUSE


@pytest.mark.parametrize(
    "line",
    [f'{M};{N};maladie;"ouvert', f'{M};"{N}"x;maladie;', f'{M};{N};maladie;"a" '],
)
def test_a_record_the_csv_module_refuses(tmp_path: Path, line: str) -> None:
    refused(
        tmp_path,
        text(HEADER, f"{C};{C};course;", line),
        at(3, UNREADABLE_CSV_CAUSE),
    )


def test_a_header_the_csv_module_refuses(tmp_path: Path) -> None:
    refused(tmp_path, text("", '"debut" ;fin;type'), at(2, UNREADABLE_CSV_CAUSE))


def test_a_note_too_long(tmp_path: Path) -> None:
    refused(
        tmp_path,
        text(HEADER, f"{M};{N};maladie;" + "x" * 200_000),
        at(2, UNREADABLE_CSV_CAUSE),
    )


@pytest.mark.parametrize(
    ("line", "cause"),
    [
        ("2000-01-1;;grippe", FIELD_COUNT_CAUSE.format(found=3, expected=4)),
        ("2000-01-1;;grippe;", UNREADABLE_DATE_CAUSE.format(column="debut")),
        ("2000-01-12;;grippe;", EMPTY_END_CAUSE),
        ("2000-01-12;2000-01-1;grippe;", UNREADABLE_DATE_CAUSE.format(column="fin")),
        ("2000-01-12;2000-01-11;grippe;", END_BEFORE_START_CAUSE),
        ("2000-01-12;2000-01-12;grippe;", UNKNOWN_TYPE_CAUSE),
    ],
)
def test_the_order_of_the_checks_of_a_line(
    tmp_path: Path, line: str, cause: str
) -> None:
    refused(tmp_path, text(HEADER, line), at(2, cause))


def test_the_margin_is_checked_before_the_dates(tmp_path: Path) -> None:
    refused(
        tmp_path,
        text("debut;fin;type;;", "2000-01-1;;grippe;x;"),
        at(2, UNNAMED_FIELD_CAUSE.format(position=4)),
    )


def test_the_first_faulty_line_is_named(tmp_path: Path) -> None:
    refused(
        tmp_path,
        text(HEADER, MALADIE, "x;;;", "2000-01-1;;;"),
        at(3, UNREADABLE_DATE_CAUSE.format(column="debut")),
    )


def test_a_line_before_the_header_the_csv_module_refuses_is_the_header(
    tmp_path: Path,
) -> None:
    refused(
        tmp_path,
        text("", "x" * 200_000, HEADER, MALADIE),
        at(2, UNREADABLE_CSV_CAUSE),
    )


# --- aucun message ne recopie une valeur du fichier ---------------------------------

MARK = "XQZW"
MARKED = {
    "encodage": f"{HEADER}\n{M};{N};maladie;{MARK}".encode() + "é".encode("latin-1"),
    "colonne": text(f"debut;fin;type;{MARK}"),
    "colonne type": text(f"debut;fin;{MARK}"),
    "champs": text(HEADER, f"{M};{N};maladie;{MARK};de trop"),
    "debut": text(HEADER, f"{MARK}-01-12;{N};maladie;{MARK}"),
    "fin": text(HEADER, f"{M};12/01/{MARK};maladie;{MARK}"),
    "fin vide": text(HEADER, f"{M};;maladie;{MARK}"),
    "fin avant": text(HEADER, f"{N};{M};maladie;{MARK}"),
    "type": text(HEADER, f"{M};{N};{MARK};{MARK}"),
    "csv": text(HEADER, f'{M};{N};maladie;"{MARK}'),
    "marge": text("debut;fin;type;note;", f"{M};{N};maladie;;{MARK}"),
}


@pytest.mark.parametrize("data", MARKED.values(), ids=MARKED.keys())
def test_no_message_copies_a_value_of_the_file(tmp_path: Path, data: bytes) -> None:
    (tmp_path / JOURNAL_FILE).write_bytes(data)
    with pytest.raises(JournalError) as caught:
        read_journal(tmp_path)
    assert MARK.casefold() not in str(caught.value).casefold()


# --- les invariants des objets rendus ------------------------------------------------


def event(start: date, end: date, line: int = 2) -> JournalEvent:
    return JournalEvent(start, end, ILLNESS, line)


D12 = date(2000, 1, 12)


def test_an_event_ends_on_its_first_day_or_after() -> None:
    assert event(D12, D12)
    with pytest.raises(
        ContractError, match=r"^JournalEvent : end doit être >= start\.$"
    ):
        event(D12, date(2000, 1, 11))


def test_an_event_comes_after_the_header() -> None:
    with pytest.raises(
        ContractError, match=r"^JournalEvent : line doit être >= 2, reçu 1\.$"
    ):
        event(D12, D12, 1)


def test_the_invariants_of_a_journal() -> None:
    a, b = event(D12, D12, 2), event(D12, D12, 3)
    assert Journal((a, b), "0" * 64).events == (a, b)
    with pytest.raises(
        ContractError,
        match=r"^Journal\.events doit être une séquence immuable : passer un tuple, "
        r"reçu list\.$",
    ):
        Journal(cast(Any, [a]), "0" * 64)
    for events in ((b, a), (a, a)):
        with pytest.raises(
            ContractError, match=r"^Journal\.events : lignes strictement croissantes\.$"
        ):
            Journal(events, "0" * 64)
    with pytest.raises(
        ContractError, match=r"^Journal : sans fichier \(sha256 absent\), rien lu\.$"
    ):
        Journal((a,), None)
    for sha256 in ("0" * 63, "0" * 65, "A" * 64, "g" * 64):
        with pytest.raises(
            ContractError,
            match=r"^Journal\.sha256 : 64 chiffres hexadécimaux minuscules\.$",
        ):
            Journal((), sha256)


# --- les types par jour --------------------------------------------------------------

JAN1, DEC31 = date(2000, 1, 1), date(2000, 12, 31)


def journal_of(*events: tuple[date, date, JournalEventType]) -> Journal:
    return Journal(
        tuple(
            JournalEvent(s, e, t, line)
            for line, (s, e, t) in enumerate(events, start=2)
        ),
        "0" * 64,
    )


def jan(day: int) -> date:
    return date(2000, 1, day)


BLESSURE = JournalEventType.INJURY
AUTRE = JournalEventType.OTHER
ALTITUDE = JournalEventType.ALTITUDE_STAY


def test_no_event_no_day() -> None:
    assert dict(journal_types_by_day(Journal((), None), JAN1, DEC31)) == {}


def test_an_event_covers_its_days_bounds_included() -> None:
    one = journal_types_by_day(journal_of((jan(12), jan(12), ILLNESS)), JAN1, DEC31)
    assert dict(one) == {jan(12): (ILLNESS,)}
    three = journal_types_by_day(journal_of((jan(12), jan(14), ILLNESS)), JAN1, DEC31)
    assert list(three) == [jan(12), jan(13), jan(14)]
    leap = journal_types_by_day(
        journal_of((date(2000, 2, 28), date(2000, 3, 1), BLESSURE)), JAN1, DEC31
    )
    assert list(leap) == [date(2000, 2, 28), date(2000, 2, 29), date(2000, 3, 1)]


def test_the_types_of_a_day_are_sorted_without_duplicate() -> None:
    days = journal_types_by_day(
        journal_of((jan(12), jan(14), ILLNESS), (jan(14), jan(15), RACE)), JAN1, DEC31
    )
    assert dict(days) == {
        jan(12): (ILLNESS,),
        jan(13): (ILLNESS,),
        jan(14): (RACE, ILLNESS),
        jan(15): (RACE,),
    }
    same_day = journal_types_by_day(
        journal_of(
            (jan(3), jan(3), ALTITUDE),
            (jan(3), jan(3), BLESSURE),
            (jan(3), jan(3), AUTRE),
        ),
        JAN1,
        DEC31,
    )
    assert same_day[jan(3)] == (AUTRE, BLESSURE, ALTITUDE)
    twice = journal_types_by_day(
        journal_of((jan(12), jan(13), ILLNESS), (jan(13), jan(14), ILLNESS)),
        JAN1,
        DEC31,
    )
    assert twice[jan(13)] == (ILLNESS,)


def test_the_days_are_sorted_whatever_the_order_of_the_file() -> None:
    march = date(2000, 3, 1)
    days = journal_types_by_day(
        journal_of((march, march, RACE), (jan(12), jan(12), ILLNESS)), JAN1, DEC31
    )
    assert list(days) == [jan(12), march]


def test_the_table_is_read_only() -> None:
    days = journal_types_by_day(journal_of((jan(12), jan(12), ILLNESS)), JAN1, DEC31)
    with pytest.raises(TypeError):
        cast(Any, days)[jan(1)] = ()


def test_from_the_file_to_the_days(tmp_path: Path) -> None:
    journal = write(tmp_path, BOM + text(HEADER, f"{M};{N};maladie;", end="\r\n"))
    assert dict(journal_types_by_day(journal, JAN1, DEC31)) == {
        jan(12): (ILLNESS,),
        jan(13): (ILLNESS,),
        jan(14): (ILLNESS,),
    }


def test_an_event_that_overflows_is_cut() -> None:
    days = journal_types_by_day(
        journal_of(
            (date(1999, 12, 30), jan(2), ILLNESS),
            (date(2000, 12, 30), date(2001, 1, 2), RACE),
        ),
        JAN1,
        DEC31,
    )
    assert dict(days) == {
        jan(1): (ILLNESS,),
        jan(2): (ILLNESS,),
        date(2000, 12, 30): (RACE,),
        DEC31: (RACE,),
    }
    bounds = journal_types_by_day(
        journal_of(
            (date(1999, 12, 1), JAN1, BLESSURE),
            (DEC31, date(2001, 2, 1), AUTRE),
        ),
        JAN1,
        DEC31,
    )
    assert dict(bounds) == {JAN1: (BLESSURE,), DEC31: (AUTRE,)}
    none = journal_types_by_day(
        journal_of(
            (date(1999, 12, 1), date(1999, 12, 2), ILLNESS),
            (date(2001, 1, 1), date(2001, 1, 1), RACE),
        ),
        JAN1,
        DEC31,
    )
    assert dict(none) == {}


def test_an_absurd_end_gives_only_the_days_of_the_table(tmp_path: Path) -> None:
    journal = write(tmp_path, text(HEADER, "2000-01-12;9999-12-31;maladie;"))
    days = journal_types_by_day(journal, JAN1, jan(31))
    assert next(iter(days)) == jan(12)
    assert list(days)[-1] == jan(31)
    assert len(days) == 20
    one = journal_types_by_day(
        journal_of((date(1999, 1, 1), date(2001, 1, 1), ILLNESS)), jan(12), jan(12)
    )
    assert dict(one) == {jan(12): (ILLNESS,)}


def test_the_bounds_of_the_calendar() -> None:
    last = journal_types_by_day(
        journal_of((date(9999, 12, 30), date.max, AUTRE)), date(9999, 12, 1), date.max
    )
    assert list(last) == [date(9999, 12, 30), date.max]
    first = journal_types_by_day(
        journal_of((date.min, date(1, 1, 2), AUTRE)), date.min, date(1, 1, 5)
    )
    assert list(first) == [date.min, date(1, 1, 2)]


def test_the_bounds_of_the_table() -> None:
    empty = Journal((), None)
    with pytest.raises(
        ValueError,
        match=r"^journal_types_by_day : first \(2000-01-13\) doit être <= last "
        r"\(2000-01-12\)\.$",
    ):
        journal_types_by_day(empty, jan(13), jan(12))
    assert dict(journal_types_by_day(empty, jan(12), jan(12))) == {}
    with pytest.raises(
        ValueError,
        match=r"^journal_types_by_day : first doit être une date, reçu datetime\.$",
    ):
        journal_types_by_day(empty, datetime(2000, 1, 1), DEC31)
    with pytest.raises(
        ValueError,
        match=r"^journal_types_by_day : last doit être une date, reçu datetime\.$",
    ):
        journal_types_by_day(empty, JAN1, datetime(2000, 1, 1))
    with pytest.raises(
        ValueError,
        match=r"^journal_types_by_day : first doit être une date, reçu str\.$",
    ):
        journal_types_by_day(empty, cast(Any, "2000-01-01"), DEC31)


def test_read_cause_is_a_template() -> None:
    assert READ_CAUSE.format(reason="x") == "lecture impossible (x)"


# --- la limite d'un champ, les fins de ligne, les garanties du module -----------------


def admitted(folder: Path, data: bytes) -> Journal:
    """Le journal de ``data`` ; un refus fait échouer le test, en disant son message."""
    try:
        return write(folder, data)
    except JournalError as error:
        pytest.fail(f"refusé à tort : {error}")


def test_a_note_at_the_limit_of_the_csv_module(tmp_path: Path) -> None:
    data = text(HEADER, f"{M};{N};maladie;" + "x" * 131_072)
    assert seen(admitted(tmp_path, data)) == [REFERENCE[0]]


def test_a_note_past_the_limit_of_the_csv_module(tmp_path: Path) -> None:
    refused(
        tmp_path,
        text(HEADER, f"{M};{N};maladie;" + "x" * 131_073),
        at(2, UNREADABLE_CSV_CAUSE),
    )


def test_before_the_header_a_blank_after_two_quotes_is_an_empty_line(
    tmp_path: Path,
) -> None:
    """Sans le mode strict, ``"" `` se lit comme un champ blanc."""
    data = text('"" ', HEADER, MALADIE)
    assert seen(admitted(tmp_path, data)) == [(*REFERENCE[0][:3], 3)]


def test_a_lone_cr_and_a_lf_in_the_same_file(tmp_path: Path) -> None:
    data = HEADER.encode() + b"\r" + text(MALADIE, f"{C};{C};course;")
    assert seen(admitted(tmp_path, data)) == REFERENCE


@pytest.mark.parametrize(
    ("value", "field"),
    [
        (JournalEvent(date(2000, 1, 1), date(2000, 1, 1), ILLNESS, 2), "line"),
        (Journal((), None), "sha256"),
    ],
    ids=["JournalEvent", "Journal"],
)
def test_the_contracts_of_the_journal_are_frozen(value: object, field: str) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(value, field, None)


def test_a_journal_error_is_a_value_error() -> None:
    assert issubclass(JournalError, ValueError)


def test_a_read_error_without_a_text_says_the_name_of_its_class(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def read_bytes(self: Path) -> bytes:
        raise PermissionError

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    with pytest.raises(JournalError) as caught:
        read_journal(tmp_path)
    assert str(caught.value) == (
        f"journal.csv : {READ_CAUSE.format(reason='PermissionError')}"
    )
