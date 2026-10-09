"""Registre durci (§ 6.4 et § 8.1, test 12, du brief M4b-5 ; ``0010`` D14).

Le sceau (``line_hash``), les entiers géants et les instants hors du domaine des dates
relus en erreur du registre ou du codec, les décalages horaires à fraction de seconde
refusés à l'écriture ; puis le recoupement des références D8 par l'accord du registre
(précision de D14 de M4b-5, décisions Q11 et Q14), sur la fixture du registre de
M4b-4 : à l'ajout d'un RÉSULTAT comme à ``verify_registry``.
"""

import dataclasses
import hashlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from fixtures.registry import (
    OUTINGS,
    REFERENCE_R1,
    RETRIEVED_AT,
    _outing,
    at,
    d8_reference,
    declaration,
    outcomes,
    references,
    registry_root,
)
from fixtures.repeatability import MULTI, case_reference
from mountain_perf.backtest import (
    DOCUMENTS_DIR,
    EVENTS_FILE,
    CodecError,
    RegistryError,
    append_declaration,
    append_result,
    content_hash,
    declared_performance,
    decode_contract,
    decode_document,
    encode_contract,
    encode_document,
    encode_value,
    line_hash,
    read_registry,
    verify_registry,
)
from mountain_perf.schemas import (
    ArtifactRef,
    ArtifactRole,
    DataSet,
    Exclusion,
    Outing,
    OutingObservation,
    Performance,
    ReferenceKind,
    RegistryEvent,
    RepeatabilityReference,
    RouteReference,
    SourceRef,
)
from test_backtest_codec import SAMPLE, Sample
from test_backtest_registry import filled, journal_lines, rewrite_last, snapshot

# ---------------------------------------------------------------------------
# Le sceau : line_hash
# ---------------------------------------------------------------------------


def test_line_hash_is_the_previous_hash_of_the_next_line(tmp_path: Path) -> None:
    """Précision de D14 (M4b-5) : ``line_hash`` d'un événement est le ``sha256`` de sa
    ligne du journal, sans fin de ligne, et l'empreinte que porte l'événement
    suivant ; celle de la dernière ligne est le sceau."""
    root = filled(tmp_path)
    events = read_registry(root).events
    lines = journal_lines(root)
    assert [line_hash(event) for event in events] == [
        hashlib.sha256(line).hexdigest() for line in lines
    ]
    assert [event.previous_hash for event in events[1:]] == [
        line_hash(event) for event in events[:-1]
    ]


# ---------------------------------------------------------------------------
# Lignes et documents forgés (décision Q11)
# ---------------------------------------------------------------------------


def _forged_first_line(tmp_path: Path, old: bytes, new: bytes) -> Path:
    """Un registre d'une ligne, la DÉCLARATION, où ``old`` est remplacé par ``new``."""
    root = registry_root(tmp_path)
    append_declaration(root, declaration(), recorded_at=at(0))
    (line,) = journal_lines(root)
    assert line.count(old) == 1
    (root / EVENTS_FILE).write_bytes(line.replace(old, new) + b"\n")
    return root


def test_giant_integer_in_a_line_is_unreadable_json(tmp_path: Path) -> None:
    """Décision Q11 : un entier de 5 000 chiffres (``ValueError`` de CPython) est un
    « JSON illisible » du registre, pas une exception brute."""
    root = _forged_first_line(
        tmp_path, b'"number":1,', b'"number":' + b"9" * 5000 + b","
    )
    with pytest.raises(RegistryError) as raised:
        read_registry(root)
    assert type(raised.value) is RegistryError
    assert str(raised.value) == "evenements.jsonl, ligne 1 : JSON illisible"


def test_instant_out_of_the_date_range_is_a_registry_error(tmp_path: Path) -> None:
    """Décision Q11 : un instant que la normalisation en UTC fait sortir du domaine des
    dates (``OverflowError``) est une erreur du registre, qui le nomme."""
    old = b'"recorded_at":"' + at(0).isoformat().encode() + b'"'
    root = _forged_first_line(
        tmp_path, old, b'"recorded_at":"0001-01-01T00:30:00+01:00"'
    )
    with pytest.raises(RegistryError) as raised:
        read_registry(root)
    assert type(raised.value) is RegistryError
    assert str(raised.value) == (
        "evenements.jsonl, ligne 1 : recorded_at : instant hors du domaine des dates "
        "'0001-01-01T00:30:00+01:00'"
    )


def test_giant_integer_in_a_document_is_unreadable() -> None:
    """Décision Q11 : un document dont ``data`` est un entier de 5 000 chiffres est
    « illisible », en ``CodecError``."""
    data = b'{"type":"OutingObservation","format":1,"data":' + b"9" * 5000 + b"}"
    with pytest.raises(CodecError) as raised:
        decode_document(data, OutingObservation)
    assert type(raised.value) is CodecError
    assert str(raised.value) == "document illisible : JSON en UTF-8 attendu"


@pytest.mark.parametrize(
    "offset",
    [
        timedelta(microseconds=500_000),
        -timedelta(microseconds=500_000),
        timedelta(hours=1, microseconds=500_000),
    ],
    ids=["+0.5s", "-0.5s", "+1h0.5s"],
)
def test_offset_with_a_fraction_of_second_is_refused(offset: timedelta) -> None:
    """§ 6.4 : un décalage horaire qui n'est pas un nombre entier de secondes est
    refusé à l'écriture, quelle que soit la version de Python (certaines le relisent
    sans sa fraction)."""
    value = dataclasses.replace(
        SAMPLE, instant=datetime(2026, 10, 3, 15, 0, tzinfo=timezone(offset))
    )
    with pytest.raises(CodecError) as raised:
        encode_value(value, Sample)
    assert type(raised.value) is CodecError
    assert str(raised.value) == (
        "instant : instant dont le décalage horaire n'est pas un nombre entier de "
        "secondes"
    )


@pytest.mark.parametrize(
    "offset",
    [timedelta(hours=2), timedelta(seconds=30), timedelta(0)],
    ids=["2h", "30s", "0"],
)
def test_whole_second_offsets_are_read_back_identically(offset: timedelta) -> None:
    """§ 6.4 : un décalage entier s'écrit et se relit à l'identique, décalage
    compris."""
    instant = datetime(2026, 10, 3, 15, 0, tzinfo=timezone(offset))
    value = dataclasses.replace(SAMPLE, instant=instant)
    back = decode_contract(Sample, encode_contract(value))
    assert back.instant == instant
    assert back.instant.utcoffset() == offset


# ---------------------------------------------------------------------------
# Recoupement des références D8 (décisions Q11 et Q14)
# ---------------------------------------------------------------------------


def _source(identifier: str, digit: str) -> SourceRef:
    return SourceRef("gpx", identifier, digit * 64, RETRIEVED_AT)


def _reference(identifier: str, digit: str) -> RouteReference:
    """Une référence déclarée de fichier ``identifier``, d'empreinte ``digit * 64``."""
    return RouteReference(
        ReferenceKind.PREPARED,
        ArtifactRef(
            _source(identifier, digit),
            REFERENCE_R1.artifact.available_at,
            ArtifactRole.FORECAST_INPUT,
        ),
    )


COPY_R1 = _reference("parcours-copie.gpx", "5")
"""La référence de ``r1`` sous un autre nom, de même empreinte."""

OTHER = _reference("parcours.gpx", "9")
"""Une référence de même nom que celle de ``r1``, d'une autre empreinte."""


def _on_r1(
    reference: RepeatabilityReference, source: SourceRef
) -> RepeatabilityReference:
    return dataclasses.replace(reference, reference=source)


def _day_outing(
    outing_id: str,
    day: date,
    digit: str,
    route: str | None,
    reference: RouteReference | None,
    dataset: DataSet,
) -> Outing:
    outing = _outing(outing_id, day, f"{outing_id}.gpx", digit, "r1", None, dataset)
    return dataclasses.replace(outing, route_id=route, reference=reference)


def _declared_with(tmp_path: Path, *extra: Performance) -> Path:
    """Un registre qui porte la déclaration de M4b-4, ses performances augmentées de
    ``extra`` (jours civils croissants)."""
    base = [Performance(o.start_time.date(), (o,)) for o in OUTINGS]
    performances = sorted([*base, *extra], key=lambda p: p.civil_date)
    declared = tuple(declared_performance(p) for p in performances)
    root = registry_root(tmp_path)
    append_declaration(root, declaration(performances=declared), recorded_at=at(0))
    return root


def _unscored(*performances: Performance) -> tuple[Exclusion, ...]:
    return tuple(
        Exclusion(o.outing_id, "sortie non tracée")
        for p in performances
        for o in p.outings
    )


MESSAGE = (
    "la référence de 'r1' ne nomme pas la référence déclarée de la sortie {} "
    "(empreinte différente)"
)


def test_reference_of_another_hash_is_refused_at_append(tmp_path: Path) -> None:
    """Précision de D14 (M4b-5), décision Q11 : la référence D8 de ``r1`` nomme
    ``parcours.gpx`` d'une autre empreinte que la référence déclarée de ses sorties ;
    l'ajout est refusé, et rien n'est écrit."""
    root = registry_root(tmp_path)
    append_declaration(root, declaration(), recorded_at=at(0))
    pairs = (("r1", _on_r1(case_reference("Deux jours"), OTHER.artifact.source)),)
    before = snapshot(root)
    with pytest.raises(RegistryError) as raised:
        append_result(root, 1, outcomes(), references=pairs, recorded_at=at(1))
    assert type(raised.value) is RegistryError
    assert str(raised.value) == "ajout refusé : " + MESSAGE.format("'q-2026-05-20'")
    assert snapshot(root) == before


def test_rewritten_last_result_is_refused_by_verification(tmp_path: Path) -> None:
    """Décision Q11 : le même RÉSULTAT réécrit en dernière ligne d'un registre rempli
    (le document de sa référence écrit sous son empreinte) se relit, mais
    ``verify_registry`` le refuse en nommant la ligne 2."""
    root = filled(tmp_path)
    forged = _on_r1(references()[0][1], OTHER.artifact.source)
    data = encode_document(forged)
    sha = content_hash(data)
    (root / DOCUMENTS_DIR / f"{sha}.json").write_bytes(data)

    def change(event: RegistryEvent) -> RegistryEvent:
        assert event.result is not None
        record = dataclasses.replace(event.result.references[0], reference=sha)
        result = dataclasses.replace(event.result, references=(record,))
        return dataclasses.replace(event, result=result)

    rewrite_last(root, change)
    read_registry(root)
    with pytest.raises(RegistryError) as raised:
        verify_registry(root)
    assert type(raised.value) is RegistryError
    assert str(raised.value) == (
        "evenements.jsonl, ligne 2 : " + MESSAGE.format("'q-2026-05-20'")
    )


MAY_24 = date(2026, 5, 24)


def _multi_outing_day(reference: RouteReference | None) -> Performance:
    """Le jour multi-sorties 2026-05-24 : ``q-2026-05-24`` sur ``r1``, de référence
    ``reference``, et ``x-2026-05-24`` sans parcours."""
    return Performance(
        MAY_24,
        (
            _day_outing(
                "q-2026-05-24", MAY_24, "1", "r1", reference, DataSet.REPEATABILITY
            ),
            _day_outing("x-2026-05-24", MAY_24, "2", None, None, DataSet.DEVELOPMENT),
        ),
    )


def _multi_reference() -> tuple[tuple[str, RepeatabilityReference], ...]:
    """Le cas « Multi-sorties » de M4b-3, son fichier remplacé par celui de
    ``REFERENCE_R1`` : jours 2026-05-20 et 2026-05-27, jour multi-sorties
    2026-05-24."""
    reference = _on_r1(case_reference("Multi-sorties"), REFERENCE_R1.artifact.source)
    assert reference.multi_outing_days == (MAY_24,)
    return (("r1", reference),)


def test_multi_outing_day_with_the_same_hash_is_accepted(tmp_path: Path) -> None:
    """Précision de D14 (M4b-5) : au jour multi-sorties de la référence, la sortie de
    ``r1`` nomme ``parcours-copie.gpx`` de même empreinte — seule l'empreinte compte ;
    la sortie sans parcours n'y est pas tenue."""
    day = _multi_outing_day(COPY_R1)
    root = _declared_with(tmp_path, day)
    append_result(
        root,
        1,
        outcomes(),
        unscored=_unscored(day),
        references=_multi_reference(),
        recorded_at=at(1),
    )
    verify_registry(root)


@pytest.mark.parametrize(
    "reference", [OTHER, None], ids=["other-hash", "without-reference"]
)
def test_multi_outing_day_of_another_hash_is_refused(
    tmp_path: Path, reference: RouteReference | None
) -> None:
    """Précision de D14 (M4b-5) : les jours multi-sorties de la référence D8 sont
    recoupés, jours multi-sorties compris : une référence d'une autre empreinte, puis
    l'absence de référence, sont refusées en nommant ``q-2026-05-24``."""
    day = _multi_outing_day(reference)
    root = _declared_with(tmp_path, day)
    before = snapshot(root)
    with pytest.raises(RegistryError) as raised:
        append_result(
            root,
            1,
            outcomes(),
            unscored=_unscored(day),
            references=_multi_reference(),
            recorded_at=at(1),
        )
    assert type(raised.value) is RegistryError
    assert str(raised.value) == "ajout refusé : " + MESSAGE.format("'q-2026-05-24'")
    assert snapshot(root) == before


def test_a_day_the_reference_does_not_cover_is_not_held(tmp_path: Path) -> None:
    """Précision de D14 (M4b-5) : une sortie de ``r1`` d'un jour que la référence ne
    couvre pas (``q-2026-06-10``, écartée, de référence d'une autre empreinte) n'est
    pas tenue."""
    june_10 = date(2026, 6, 10)
    day = Performance(
        june_10,
        (
            _day_outing(
                "q-2026-06-10", june_10, "1", "r1", OTHER, DataSet.REPEATABILITY
            ),
        ),
    )
    root = _declared_with(tmp_path, day)
    append_result(
        root,
        1,
        outcomes(),
        unscored=_unscored(day),
        references=references(),
        recorded_at=at(1),
    )
    verify_registry(root)


def test_outings_of_another_set_or_route_are_not_held(tmp_path: Path) -> None:
    """Décision Q14 : au jour multi-sorties 2026-05-24, ``v-2026-05-24``, sur ``r1``
    mais en développement (une variante), et ``w-2026-05-24``, de répétabilité sur
    ``r2``, ont des références d'une autre empreinte : seules les sorties du jeu de
    répétabilité du parcours sont tenues ; l'ajout et la vérification acceptent."""
    day = Performance(
        MAY_24,
        (
            _day_outing(
                "q-2026-05-24", MAY_24, "1", "r1", COPY_R1, DataSet.REPEATABILITY
            ),
            _day_outing("v-2026-05-24", MAY_24, "2", "r1", OTHER, DataSet.DEVELOPMENT),
            _day_outing(
                "w-2026-05-24", MAY_24, "3", "r2", OTHER, DataSet.REPEATABILITY
            ),
        ),
    )
    root = _declared_with(tmp_path, day)
    # w-2026-05-24 fait de r2 un parcours du jeu de répétabilité : sa référence D8 n'a
    # que ce jour multi-sorties (M4c-2 : une référence par parcours, jours exacts).
    r2 = d8_reference(OTHER.artifact.source, [MULTI[1]])
    append_result(
        root,
        1,
        outcomes(),
        unscored=_unscored(day),
        references=(*_multi_reference(), ("r2", r2)),
        recorded_at=at(1),
    )
    verify_registry(root)


# ---------------------------------------------------------------------------
# Correctifs de la relecture de la PR #20
# ---------------------------------------------------------------------------


def _refused_at_append(root: Path, *days: Performance) -> None:
    before = snapshot(root)
    with pytest.raises(RegistryError) as raised:
        append_result(
            root,
            1,
            outcomes(),
            unscored=_unscored(*days),
            references=_multi_reference(),
            recorded_at=at(1),
        )
    assert str(raised.value) == "ajout refusé : " + MESSAGE.format("'q-2026-05-24'")
    assert snapshot(root) == before


def test_a_day_outside_the_reference_does_not_stop_the_check(tmp_path: Path) -> None:
    """Précision de D14 (M4b-5) : les performances se parcourent toutes — un jour que
    la référence ne couvre pas (2026-05-22) avant le jour multi-sorties n'arrête pas le
    recoupement : la référence d'une autre empreinte de ``q-2026-05-24`` est
    refusée."""
    may_22 = date(2026, 5, 22)
    other = Performance(
        may_22,
        (_day_outing("x-2026-05-22", may_22, "3", None, None, DataSet.DEVELOPMENT),),
    )
    day = _multi_outing_day(OTHER)
    _refused_at_append(_declared_with(tmp_path, other, day), other, day)


def test_an_outing_not_held_does_not_stop_the_check(tmp_path: Path) -> None:
    """Décision Q14 : les sorties d'un jour se parcourent toutes — au jour
    multi-sorties, ``p-2026-05-24``, sans parcours, avant celle de ``r1`` n'arrête pas
    le recoupement : la référence d'une autre empreinte de ``q-2026-05-24`` est
    refusée."""
    held = _multi_outing_day(OTHER).outings[0]
    first = _day_outing("p-2026-05-24", MAY_24, "2", None, None, DataSet.DEVELOPMENT)
    day = Performance(MAY_24, (first, held))
    assert [o.outing_id for o in day.outings] == ["p-2026-05-24", "q-2026-05-24"]
    _refused_at_append(_declared_with(tmp_path, day), day)


@pytest.mark.parametrize(
    "offset",
    [timedelta(seconds=1), -timedelta(minutes=5, seconds=59)],
    ids=["+1s", "-5min59s"],
)
def test_odd_whole_second_offsets_are_read_back_identically(offset: timedelta) -> None:
    """§ 6.4 : la règle porte sur la seconde entière — un décalage d'un nombre impair
    de secondes s'écrit et se relit à l'identique, décalage compris."""
    instant = datetime(2026, 10, 3, 15, 0, tzinfo=timezone(offset))
    value = dataclasses.replace(SAMPLE, instant=instant)
    back = decode_contract(Sample, encode_contract(value))
    assert back.instant == instant
    assert back.instant.utcoffset() == offset
