"""Le registre au format 4 (brief M4d-2 ; ``0010`` D14 et sa précision de M4d-2, D11,
D2.4) : le document des fourchettes d'une sortie.

- les versions, et le premier format du document : ``OutingBands`` au format 4, ni
  écrit ni relu avant ;
- un registre des formats 1, 2 et 3 — construit par le code du jour, puis récrit à son
  format par ``_to_format`` de ``test_backtest_registry_format2.py`` — relu, vérifié
  (ses lignes sans ``bands``, réécrites à l'octet), et suivi d'un ajout du format 4 ;
  une ligne d'un format antérieur qui porte ``bands`` (même ``null``) refusée, champ
  inconnu à son format ; l'invariant de ``RegistryEvent`` ;
- l'accord d'un RÉSULTAT du format 4 : une sortie scorée cite ses fourchettes si et
  seulement si elle a une référence, que les cinq modèles du rapport sont déclarés et
  que la déclaration ne porte pas d'expérience ; les fourchettes portent leur sortie,
  les jours de ``C_j`` et le statut de chaque membre que portent les calages de la
  sortie (population et retraits), le drapeau « plusieurs sorties », autant
  d'éléments que son ``K`` ; à l'ajout comme à la relecture ;
- les invariants d'``OutingResult`` et d'``OutingOutcome`` ; ``load_outcomes`` rend
  les fourchettes au bit.

Les fourchettes sont des ``OutingBands`` valides construites par les aides de
``test_schemas_bands.py`` (rien n'est recalculé par le registre : il n'a pas à l'être
ici) ; aucune donnée réelle. Les journaux récrits à la main le sont en JSON canonique,
la chaîne des empreintes recalculée.
"""

import re
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from fixtures.registry import (
    CALIBRATED_MODELS,
    OUTINGS,
    P03,
    at,
    declaration,
    not_calibrated,
    outcomes,
    performances,
    references,
    registry_root,
    v0_of,
)
from mountain_perf.backtest import (
    DOCUMENT_FIRST_FORMAT,
    DOCUMENT_TYPES,
    EVENTS_FILE,
    CodecError,
    RegistryError,
    append_declaration,
    append_result,
    content_hash,
    count_trials,
    declared_performance,
    decode_document,
    encode_document,
    load_outcomes,
    read_registry,
    verify_registry,
)
from mountain_perf.model.engine import ENGINE_VERSION
from mountain_perf.schemas import (
    BAND_LABEL,
    BAND_MODELS,
    BANDS_FIRST_FORMAT,
    REGISTRY_FORMAT_VERSION,
    REGISTRY_READABLE_FORMATS,
    Admission,
    CalibratedOutingScores,
    CalibrationWithdrawal,
    ContractError,
    Declaration,
    DeclaredModel,
    Exclusion,
    ModelKind,
    OutingBands,
    OutingOutcome,
    OutingResult,
    OutingScores,
    Performance,
    RegistryEvent,
    Unavailability,
)
from test_backtest_registry_format2 import _registry, _rewrite, _to_format
from test_backtest_registry_format3 import (
    _admission,
    _experiment,
    _journal,
    _lines,
)
from test_schemas_bands import band, bands, member

Q20_ID, Q27_ID, P03_ID = (outing.outing_id for outing in OUTINGS)
V0_RAW, V0_RECALIBRATED, CANDIDATE = CALIBRATED_MODELS
FIVE = (
    V0_RAW,
    V0_RECALIBRATED,
    *(
        DeclaredModel(kind, ENGINE_VERSION, None, "calage de 0010 D9.2")
        for kind in BAND_MODELS[2:]
    ),
)
"""Les cinq modèles du rapport ; les baselines déclarées à la version de la prévision
de v0 que portent leurs scores ``non calé`` (``not_calibrated``) : l'accord recoupe la
version, pas la nature."""
E01_DAY = date(2026, 5, 1)
E01 = replace(
    P03,
    outing_id="e-2026-05-01",
    start_time=P03.start_time.replace(month=5, day=1),
    end_time=P03.end_time.replace(month=5, day=1),
    traces=(
        replace(
            P03.traces[0],
            source=replace(
                P03.traces[0].source, identifier="e01.gpx", content_hash="9" * 64
            ),
            available_at=P03.traces[0].available_at.replace(month=5, day=1),
        ),
    ),
)
"""Une quatrième sortie, d'entraînement, déclarée et non scorée : le premier jour de
``C_j`` de q20 et de q27 (D2.4 : au moins huit jours avant leur origine)."""
UNSCORED = (Exclusion(E01.outing_id, "trace illisible"),)
WINDOW = (date(2026, 5, 1), date(2026, 5, 31))
U = Unavailability


# ---------------------------------------------------------------------------
# Aides : fourchettes des sorties du registre, résultats des cinq modèles
# ---------------------------------------------------------------------------


def _declared(**changes: object) -> Declaration:
    """La déclaration des cinq modèles sur les quatre sorties (``E01`` d'abord)."""
    e01 = declared_performance(Performance(E01_DAY, (E01,)))
    fields: dict[str, object] = {
        "models": FIVE,
        "performances": (e01, *performances()),
    }
    fields.update(changes)
    return declaration(**fields)


def _targets(outing_id: str) -> int:
    """``|K|`` de la sortie : les éléments de son observation."""
    return len(v0_of(outing_id).observation.targets)


def _bands(
    outing_id: str, days: tuple[date, ...] = (E01_DAY,), **changes: Any
) -> OutingBands:
    """Des fourchettes valides de la sortie, de membres ``days`` (par défaut ``C_j``
    de q20 comme de q27 : le jour de ``E01``) : un résidu de v0 brut par membre, des
    bornes sur chaque élément de ``K`` ; les modèles calés ``non calés`` (``support
    insuffisant``) ; sans membre, cinq modèles en ``support insuffisant``. Rien n'y
    est tiré des scores : le registre ne recalcule pas."""
    if not days:
        models = tuple(band([], model=kind) for kind in BAND_MODELS)
    else:
        size = _targets(outing_id)
        forecasts = tuple(1000.0 * (k + 1) for k in range(size))
        models = (
            band(
                [0.1 * k for k in range(len(days))],
                forecasts=forecasts,
                observed=tuple(1.05 * p for p in forecasts),
                weights=(1.0 / size,) * size,
            ),
            *(
                band([U.NOT_CALIBRATED] * len(days), model=kind)
                for kind in BAND_MODELS[1:]
            ),
        )
    base = bands(
        outing_id=outing_id,
        window_from=WINDOW[0],
        window_to=WINDOW[1],
        members=tuple(member(civil_date=day) for day in days),
        models=models,
    )
    return replace(base, **changes)


def _calibrated(
    outing_id: str,
    kind: ModelKind,
    v0: OutingScores,
    days: tuple[date, ...],
    withdrawals: tuple[CalibrationWithdrawal, ...],
) -> CalibratedOutingScores:
    """Les scores de ``kind`` de ``not_calibrated``, dont le calage d'usage porte, sous
    chaque horloge, ``C_j`` : ``days`` en population (le modèle en ``erreur du
    modèle``, la forme la plus simple d'un calage à population, sans scores) et
    ``withdrawals`` retirés ; sans l'un ni l'autre, tel quel."""
    scores = not_calibrated(outing_id, kind, v0)
    if scores.usage is None or not (days or withdrawals):
        return scores
    status = U.MODEL_ERROR if days else U.NOT_CALIBRATED
    clocks = tuple(
        replace(
            clock,
            calibration=replace(
                clock.calibration,
                population=days,
                withdrawals=withdrawals,
                unavailability=status,
            ),
        )
        for clock in scores.usage.clocks
    )
    return replace(scores, usage=replace(scores.usage, clocks=clocks))


def _five(
    changed: dict[str, OutingBands | None] | None = None,
    days: tuple[date, ...] = (E01_DAY,),
    withdrawals: tuple[CalibrationWithdrawal, ...] = (),
) -> tuple[OutingOutcome, ...]:
    """Les trois sorties scorées sous les cinq modèles, chaque sortie à référence avec
    ses fourchettes (``_bands``), sauf ``changed`` ; les calages des modèles calés
    portent ``C_j`` = ``days`` (population) et ``withdrawals`` (``_calibrated``)."""
    chosen = changed or {}
    result = []
    for current in outcomes():
        outing_id = current.outing_id
        v0 = v0_of(outing_id)
        scores: tuple[tuple[ModelKind, OutingScores | CalibratedOutingScores], ...] = (
            (ModelKind.V0_RAW, v0),
            *(
                (kind, _calibrated(outing_id, kind, v0, days, withdrawals))
                for kind in BAND_MODELS[1:]
            ),
        )
        default = None if v0.usage is None else _bands(outing_id)
        result.append(
            OutingOutcome(
                outing_id,
                current.coverage,
                scores,
                chosen.get(outing_id, default),
            )
        )
    return tuple(result)


def _answer(
    root: Path,
    number: int,
    written: tuple[OutingOutcome, ...],
    minutes: int,
    admission: Admission | None = None,
) -> None:
    """Le RÉSULTAT de ``written`` ajouté à la déclaration ``number`` : ``E01`` non
    scorée, la référence D8 de ``r1``."""
    append_result(
        root,
        number,
        written,
        unscored=UNSCORED,
        references=references(),
        admission=admission,
        recorded_at=at(minutes),
    )


def _five_registry(tmp_path: Path) -> Path:
    """Une DÉCLARATION des cinq modèles et son RÉSULTAT au format 4."""
    root = registry_root(tmp_path)
    append_declaration(root, _declared(), recorded_at=at(0))
    _answer(root, 1, _five(), 1)
    return root


def _refused_append(
    tmp_path: Path,
    declared: Declaration,
    written: tuple[OutingOutcome, ...],
    message: str,
    admission: Admission | None = None,
) -> Path:
    """L'ajout du RÉSULTAT de ``written`` à ``declared`` est refusé par ``message`` ;
    le journal reste à la DÉCLARATION."""
    root = registry_root(tmp_path)
    append_declaration(root, declared, recorded_at=at(0))
    with pytest.raises(RegistryError, match=re.escape(message)):
        _answer(root, 1, written, 1, admission)
    assert len(read_registry(root).events) == 1
    return root


IFF = (
    "une sortie scorée cite ses fourchettes si et seulement si elle a une référence, "
    "que les cinq modèles du rapport sont déclarés et qu'il n'y a pas d'expérience "
    "(M4d-2)"
)


# ---------------------------------------------------------------------------
# Versions ; le document des fourchettes (codec)
# ---------------------------------------------------------------------------


def test_versions() -> None:
    """Précision de D14 (M4d-2) : le format écrit, les formats relus, le premier
    format des fourchettes et leur place parmi les documents (avant-dernière, la
    sensibilité du format 5 après elles, M4d-3)."""
    assert REGISTRY_FORMAT_VERSION == 5
    assert REGISTRY_READABLE_FORMATS == (1, 2, 3, 4, 5)
    assert BANDS_FIRST_FORMAT == 4
    assert DOCUMENT_FIRST_FORMAT[OutingBands] == 4
    assert DOCUMENT_TYPES[-2] is OutingBands
    assert tuple(DOCUMENT_FIRST_FORMAT) == DOCUMENT_TYPES


def test_bands_document_at_format_4() -> None:
    """Le document des fourchettes s'écrit au format 4 et se relit égal à l'objet
    écrit, à l'octet à la réécriture."""
    value = _bands(Q27_ID)
    data = encode_document(value, 4)
    assert data.startswith(b'{"type":"OutingBands","format":4,')
    back = decode_document(data, OutingBands, 4)
    assert back == value
    assert encode_document(back, 4) == data


@pytest.mark.parametrize("format_version", [1, 2, 3])
def test_bands_document_does_not_exist_before_format_4(format_version: int) -> None:
    """Précision de D14 (M4d-2) : le document ne s'écrit pas avant le format 4 ; relu
    à un format antérieur, il est refusé — au format de son enveloppe d'abord, puis,
    d'une enveloppe du format antérieur, parce que ce format ne le connaît pas."""
    value = _bands(Q20_ID)
    with pytest.raises(
        TypeError,
        match=re.escape(
            "OutingBands n'existe qu'à partir du format 4, demandé au format "
            f"{format_version}."
        ),
    ):
        encode_document(value, format_version)
    data = encode_document(value, 4)
    with pytest.raises(
        CodecError, match=re.escape(f"document au format 4, {format_version} attendu")
    ):
        decode_document(data, OutingBands, format_version)
    forged = data.replace(b'"format":4,', f'"format":{format_version},'.encode(), 1)
    with pytest.raises(
        CodecError,
        match=re.escape(
            f"document de type 'OutingBands' au format {format_version}, qui ne le "
            "connaît pas"
        ),
    ):
        decode_document(forged, OutingBands, format_version)


# ---------------------------------------------------------------------------
# Les formats 1 à 3 relus par le code du format 4
# ---------------------------------------------------------------------------


def _old_registry(tmp_path: Path, version: int) -> Path:
    """Une DÉCLARATION de v0 brut et son RÉSULTAT, écrits par le code du jour puis
    récrits au format ``version``."""
    root = _registry(tmp_path)
    _to_format(root, version)
    return root


@pytest.mark.parametrize("version", [1, 2, 3])
def test_old_registry_is_read(tmp_path: Path, version: int) -> None:
    """Précision de D14 (M4d-2) : un registre des formats 1 à 3 se relit et se vérifie
    par le code du format 4 ; ses sorties ne portent pas ``bands`` (``_line`` le
    retire : chaque ligne relue se réécrit à l'octet), et se relisent sans
    fourchettes."""
    root = _old_registry(tmp_path, version)
    before = (root / EVENTS_FILE).read_bytes()
    _, answered = _lines(root)
    assert all("bands" not in outing for outing in answered["result"]["outings"])
    log = verify_registry(root)
    assert [event.format_version for event in log.events] == [version, version]
    result = log.events[1].result
    assert result is not None
    assert all(outing.bands is None for outing in result.outings)
    assert load_outcomes(root, log, 2) == outcomes()
    assert (root / EVENTS_FILE).read_bytes() == before


@pytest.mark.parametrize("version", [1, 2, 3])
def test_append_follows_old_format(tmp_path: Path, version: int) -> None:
    """Précision de D14 (M4d-2) : une exécution du format 4 — les cinq modèles, des
    fourchettes pour q20 et q27, aucune pour p03, sans référence — s'enchaîne à un
    registre d'un format antérieur ; le journal entier se vérifie, les lignes
    anciennes restent à l'octet ; la ligne du format 4 cite les fourchettes."""
    root = _old_registry(tmp_path, version)
    before = (root / EVENTS_FILE).read_bytes()
    append_declaration(root, _declared(), recorded_at=at(2))
    written = _five()
    _answer(root, 3, written, 3)
    log = verify_registry(root)
    assert [event.format_version for event in log.events] == [
        version,
        version,
        5,
        5,
    ]
    assert (root / EVENTS_FILE).read_bytes().startswith(before)
    assert count_trials(log).declarations == 2
    assert load_outcomes(root, log, 4) == written
    cited = [outing["bands"] for outing in _lines(root)[3]["result"]["outings"]]
    assert cited == [
        content_hash(encode_document(_bands(Q20_ID), 5)),
        content_hash(encode_document(_bands(Q27_ID), 5)),
        None,
    ]


@pytest.mark.parametrize("version", [1, 2, 3])
@pytest.mark.parametrize("cited", [None, "b" * 64], ids=["null", "empreinte"])
def test_old_line_carrying_bands_is_refused(
    tmp_path: Path, version: int, cited: str | None
) -> None:
    """Précision de D14 (M4d-2) : une ligne d'un format antérieur au 4 qui porte
    ``bands`` sur une sortie, même ``null``, n'est pas relue : champ inconnu à son
    format."""
    root = _old_registry(tmp_path, version)

    def with_bands(data: dict[str, Any]) -> None:
        if data["result"] is not None:
            data["result"]["outings"][0]["bands"] = cited

    _journal(root, with_bands)
    with pytest.raises(
        RegistryError,
        match=re.escape(
            f"ligne 2 : result.outings : champ inconnu au format {version} : 'bands'"
        ),
    ):
        read_registry(root)


@pytest.mark.parametrize("version", [2, 3])
def test_old_line_of_the_five_models_needs_no_bands(
    tmp_path: Path, version: int
) -> None:
    """Précision de D14 (M4d-2) : la règle des fourchettes ne vaut qu'au format 4 ; un
    RÉSULTAT des cinq modèles d'un format antérieur — comme ceux que `just backtest` a
    écrits aux formats 2 et 3 — n'en cite pas, et se vérifie."""
    root = _five_registry(tmp_path)

    def without_bands(event: RegistryEvent) -> RegistryEvent:
        if event.result is None:
            return event
        outings = tuple(replace(o, bands=None) for o in event.result.outings)
        return replace(event, result=replace(event.result, outings=outings))

    _to_format(root, version, without_bands)
    log = verify_registry(root)
    assert [event.format_version for event in log.events] == [version, version]
    assert [o.bands for o in load_outcomes(root, log, 2)] == [None, None, None]


@pytest.mark.parametrize("version", [1, 2, 3])
def test_event_before_format_4_cites_no_bands(tmp_path: Path, version: int) -> None:
    """Invariant 2 de ``RegistryEvent`` (M4d-2) : un RÉSULTAT d'un format antérieur au
    4 ne cite pas de fourchettes."""
    root = _five_registry(tmp_path)
    event = read_registry(root).events[1]
    with pytest.raises(
        ContractError,
        match=re.escape(
            f"un RÉSULTAT du format {version} ne cite pas de fourchettes (format 4)."
        ),
    ):
        replace(event, format_version=version)


# ---------------------------------------------------------------------------
# L'accord d'un RÉSULTAT du format 4
# ---------------------------------------------------------------------------


def test_five_models_result_is_read_back_at_bit(tmp_path: Path) -> None:
    """Un RÉSULTAT des cinq modèles se relit, se vérifie et rend ses fourchettes au
    bit ; ses fourchettes sont des documents du format 4."""
    root = _five_registry(tmp_path)
    log = verify_registry(root)
    assert [event.format_version for event in log.events] == [5, 5]
    outcomes_ = load_outcomes(root, log, 2)
    assert outcomes_ == _five()
    assert [o.bands for o in outcomes_] == [_bands(Q20_ID), _bands(Q27_ID), None]


def test_missing_bands_are_refused_at_append(tmp_path: Path) -> None:
    """Une sortie à référence sans fourchettes, sous les cinq modèles et sans
    expérience, est refusée à l'ajout."""
    _refused_append(
        tmp_path,
        _declared(),
        _five({Q27_ID: None}),
        f"ajout refusé : {Q27_ID!r}, {IFF}",
    )


def test_bands_without_the_five_models_are_refused(tmp_path: Path) -> None:
    """Des fourchettes sous une déclaration qui ne déclare pas les cinq modèles (v0
    brut et v0 recalé) sont refusées à l'ajout ; sans elles, le même RÉSULTAT est
    accepté."""
    two = (V0_RAW, V0_RECALIBRATED)
    written = tuple(
        OutingOutcome(o.outing_id, o.coverage, o.scores[:2], o.bands) for o in _five()
    )
    root = _refused_append(
        tmp_path,
        _declared(models=two),
        written,
        f"ajout refusé : {Q20_ID!r}, {IFF}",
    )
    _answer(root, 1, tuple(replace(o, bands=None) for o in written), 1)
    assert len(verify_registry(root).events) == 2


def test_bands_of_an_experiment_are_refused(tmp_path: Path) -> None:
    """Un RÉSULTAT d'expérience ne cite pas de fourchettes, même si la déclaration
    déclare les cinq modèles : l'ajout est refusé ; sans elles, le même RÉSULTAT, son
    document d'admission compris, est accepté."""
    declared = _declared(models=(*FIVE, CANDIDATE), experiment=_experiment())
    written = tuple(
        replace(
            o,
            scores=(
                *o.scores,
                (
                    ModelKind.CANDIDATE,
                    not_calibrated(
                        o.outing_id, ModelKind.CANDIDATE, v0_of(o.outing_id)
                    ),
                ),
            ),
        )
        for o in _five()
    )
    root = _refused_append(
        tmp_path,
        declared,
        written,
        f"ajout refusé : {Q20_ID!r}, {IFF}",
        _admission(),
    )
    _answer(root, 1, tuple(replace(o, bands=None) for o in written), 1, _admission())
    assert len(verify_registry(root).events) == 2


def test_missing_bands_are_refused_on_reading(tmp_path: Path) -> None:
    """La règle tient à la relecture : une ligne du format 4 dont une sortie à
    référence ne cite plus ses fourchettes est refusée."""
    root = _five_registry(tmp_path)

    def drop(event: RegistryEvent) -> RegistryEvent:
        if event.result is None:
            return event
        outings = tuple(
            replace(o, bands=None) if o.outing_id == Q27_ID else o
            for o in event.result.outings
        )
        return replace(event, result=replace(event.result, outings=outings))

    _rewrite(root, drop)
    with pytest.raises(RegistryError, match=re.escape(f"ligne 2 : {Q27_ID!r}, {IFF}")):
        read_registry(root)


def test_bands_of_another_outing_are_refused(tmp_path: Path) -> None:
    """Les fourchettes citées par une sortie portent cette sortie : deux sorties qui
    échangent leurs documents sont refusées à la vérification."""
    root = _five_registry(tmp_path)

    def swap(event: RegistryEvent) -> RegistryEvent:
        if event.result is None:
            return event
        first, second, third = event.result.outings
        outings = (
            replace(first, bands=second.bands),
            replace(second, bands=first.bands),
            third,
        )
        return replace(event, result=replace(event.result, outings=outings))

    _rewrite(root, swap)
    with pytest.raises(
        RegistryError,
        match=re.escape(
            f"ligne 2 : {Q20_ID!r}, les fourchettes portent la sortie {Q27_ID!r}"
        ),
    ):
        verify_registry(root)


@pytest.mark.parametrize(
    ("outing_id", "days", "changes", "message"),
    [
        (
            Q27_ID,
            (),
            {},
            "les membres des fourchettes ne sont pas les jours de C_j du calage de "
            "v0_recalibrated (population et retraits, D2.4)",
        ),
        (
            Q20_ID,
            (E01_DAY, date(2026, 5, 13)),
            {},
            "les membres des fourchettes ne sont pas les jours de C_j du calage de",
        ),
        (
            Q20_ID,
            (E01_DAY,),
            {"multi_outing": True},
            "les fourchettes disent mal si la performance a plusieurs sorties",
        ),
    ],
    ids=["q27-sans-membre", "q20-un-membre-de-trop", "plusieurs-sorties"],
)
def test_bands_disagreeing_with_the_declaration_are_refused(
    tmp_path: Path,
    outing_id: str,
    days: tuple[date, ...],
    changes: dict[str, Any],
    message: str,
) -> None:
    """Les fourchettes portent les jours de ``C_j`` que portent les calages de leur
    sortie (D2.4), et le drapeau « plusieurs sorties » de sa performance : un écart
    est refusé à l'ajout."""
    _refused_append(
        tmp_path,
        _declared(),
        _five({outing_id: _bands(outing_id, days, **changes)}),
        f"ajout refusé : {outing_id!r}, {message}",
    )


def _zero_time_bands(outing_id: str) -> OutingBands:
    """Des fourchettes dont l'unique membre, le jour de ``E01``, est retiré pour
    ``temps nul`` : les cinq modèles en ``support insuffisant``."""
    hidden = member(civil_date=E01_DAY, observed_s=None, unavailability=U.ZERO_TIME)
    return _bands(
        outing_id,
        members=(hidden,),
        models=tuple(band([U.ZERO_TIME], model=kind) for kind in BAND_MODELS),
    )


def test_bands_members_follow_the_calibrations(tmp_path: Path) -> None:
    """Chaque membre a le statut que lui donne chaque calage de la sortie : disponible
    s'il est dans la population, retiré au même motif sinon. Un membre retiré pour
    ``temps nul`` est accepté contre des calages qui le retirent au même motif, et
    refusé contre des calages qui l'ont en population, ou le retirent pour ``support
    insuffisant``. Le code du calage n'est pas appelé : les documents se recoupent."""
    changed: dict[str, OutingBands | None] = {
        Q20_ID: _zero_time_bands(Q20_ID),
        Q27_ID: _zero_time_bands(Q27_ID),
    }
    same = (CalibrationWithdrawal(E01_DAY, U.ZERO_TIME),)
    for name in ("accepte", "population", "motif"):
        (tmp_path / name).mkdir()
    root = registry_root(tmp_path / "accepte")
    append_declaration(root, _declared(), recorded_at=at(0))
    _answer(root, 1, _five(changed, days=(), withdrawals=same), 1)
    verify_registry(root)
    _refused_append(
        tmp_path / "population",
        _declared(),
        _five(changed),
        f"ajout refusé : {Q20_ID!r}, le membre du 2026-05-01 des fourchettes n'a pas "
        "le statut que lui donne le calage de v0_recalibrated (D9.2)",
    )
    other = (CalibrationWithdrawal(E01_DAY, U.INSUFFICIENT_SUPPORT),)
    _refused_append(
        tmp_path / "motif",
        _declared(),
        _five(changed, days=(), withdrawals=other),
        f"ajout refusé : {Q20_ID!r}, le membre du 2026-05-01 des fourchettes n'a pas "
        "le statut que lui donne le calage de",
    )


def _recalibrated(
    outcomes: tuple[OutingOutcome, ...],
    kind: ModelKind,
    clock: int,
    withdrawals: tuple[CalibrationWithdrawal, ...],
) -> tuple[OutingOutcome, ...]:
    """``outcomes``, où le calage d'usage de ``kind`` sous l'horloge de rang ``clock``
    n'a plus que ``withdrawals`` (population vide, ``non calé``) ; les autres modèles
    et les autres horloges inchangés."""
    result = []
    for outcome in outcomes:
        scores: list[tuple[ModelKind, OutingScores | CalibratedOutingScores]] = []
        for model, current in outcome.scores:
            if (
                model is kind
                and isinstance(current, CalibratedOutingScores)
                and current.usage is not None
            ):
                clocks = list(current.usage.clocks)
                calibration = replace(
                    clocks[clock].calibration,
                    population=(),
                    withdrawals=withdrawals,
                    unavailability=U.NOT_CALIBRATED,
                )
                clocks[clock] = replace(clocks[clock], calibration=calibration)
                current = replace(
                    current, usage=replace(current.usage, clocks=tuple(clocks))
                )
            scores.append((model, current))
        result.append(replace(outcome, scores=tuple(scores)))
    return tuple(result)


def test_bands_are_checked_against_each_model_under_the_elapsed_clock(
    tmp_path: Path,
) -> None:
    """L'accord lit le calage de **chaque** modèle calé, **sous l'écoulé** : un calage
    de Tobler seul en désaccord (le membre retiré ; les trois autres modèles l'ont en
    population) est refusé ; un calage dont seule l'horloge ``M_θ1`` diffère est
    accepté."""
    withdrawn = (CalibrationWithdrawal(E01_DAY, U.ZERO_TIME),)
    for name in ("tobler", "horloge"):
        (tmp_path / name).mkdir()
    _refused_append(
        tmp_path / "tobler",
        _declared(),
        _recalibrated(_five(), ModelKind.TOBLER, 0, withdrawn),
        f"ajout refusé : {Q20_ID!r}, le membre du 2026-05-01 des fourchettes n'a pas "
        "le statut que lui donne le calage de tobler (D9.2)",
    )
    root = registry_root(tmp_path / "horloge")
    append_declaration(root, _declared(), recorded_at=at(0))
    _answer(root, 1, _recalibrated(_five(), ModelKind.V0_RECALIBRATED, 1, withdrawn), 1)
    verify_registry(root)


def test_bands_with_another_number_of_elements_are_refused(tmp_path: Path) -> None:
    """Un modèle à bornes a autant d'éléments que le ``K`` de l'observation de sa
    sortie : un élément de trop est refusé à l'ajout."""
    size = _targets(Q27_ID) + 1
    forecasts = tuple(1000.0 * (k + 1) for k in range(size))
    wrong = band(
        [0.0],
        forecasts=forecasts,
        observed=forecasts,
        weights=(1.0 / size,) * size,
    )
    current = _bands(Q27_ID)
    changed = replace(current, models=(wrong, *current.models[1:]))
    _refused_append(
        tmp_path,
        _declared(),
        _five({Q27_ID: changed}),
        f"ajout refusé : {Q27_ID!r}, {ModelKind.V0_RAW} : {size} éléments de "
        f"fourchette pour un K de {size - 1}",
    )


def test_bands_document_must_be_stored(tmp_path: Path) -> None:
    """Le document des fourchettes est un document cité (``_cited``) : absent, la
    relecture le nomme, avant tout accord."""
    root = _five_registry(tmp_path)
    sha = content_hash(encode_document(_bands(Q27_ID), 5))
    (root / "documents" / f"{sha}.json").unlink()
    with pytest.raises(
        RegistryError, match=re.escape(f"documents/{sha}.json : document introuvable")
    ):
        read_registry(root)


def test_bands_citing_another_document_type_are_refused(tmp_path: Path) -> None:
    """Le document cité par ``bands`` est un ``OutingBands`` : l'empreinte d'une
    observation à sa place est refusée à la vérification."""
    root = _five_registry(tmp_path)

    def observation_as_bands(event: RegistryEvent) -> RegistryEvent:
        if event.result is None:
            return event
        outings = tuple(
            replace(o, bands=o.observation) if o.bands is not None else o
            for o in event.result.outings
        )
        return replace(event, result=replace(event.result, outings=outings))

    _rewrite(root, observation_as_bands)
    with pytest.raises(RegistryError, match="OutingBands"):
        verify_registry(root)


# ---------------------------------------------------------------------------
# Contrats
# ---------------------------------------------------------------------------


def test_outing_result_bands_invariants(tmp_path: Path) -> None:
    """``OutingResult`` : ``bands`` présent est un ``sha256`` et demande l'usage."""
    result = read_registry(_five_registry(tmp_path)).events[1].result
    assert result is not None
    with_usage, _, without_usage = result.outings
    with pytest.raises(ContractError, match="bands"):
        replace(with_usage, bands="pas-une-empreinte")
    with pytest.raises(
        ContractError,
        match=re.escape("des fourchettes demandent l'usage (0010 D11)"),
    ):
        replace(without_usage, bands="c" * 64)
    assert replace(with_usage, bands=None).bands is None
    assert isinstance(with_usage, OutingResult)


def test_outing_outcome_bands_invariants() -> None:
    """``OutingOutcome`` : des fourchettes de cette sortie, et la sortie a l'usage."""
    q20, _, p03 = _five()
    with pytest.raises(
        ContractError,
        match=re.escape(f"les fourchettes portent la sortie {Q27_ID!r}, {Q20_ID!r}"),
    ):
        replace(q20, bands=_bands(Q27_ID))
    with pytest.raises(
        ContractError,
        match=re.escape("des fourchettes demandent l'usage (0010 D11)"),
    ):
        replace(p03, bands=replace(_bands(Q20_ID), outing_id=P03_ID))
    assert q20.bands is not None
    assert q20.bands.label == BAND_LABEL
