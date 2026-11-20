"""La page « Q2 » (AN3-5, § 6 du brief) par ``AppTest.from_function``, sans navigateur
ni serveur. Les dossiers de résultats sont écrits à la main sous ``data_dir()`` (le
dossier neuf de ``tests/conftest.py``), par les fonctions d'écriture de
``analyse/q2/results.py`` ; les tables actuelles sont celles du monde inventé de la
page récupération (``fixtures.recovery_world``). Toutes les valeurs sont inventées.
Sautés sans les extras ``tableau`` et ``analyse``."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("pyarrow")
pytest.importorskip("numpy")
pytest.importorskip("scipy")

import streamlit as st
from streamlit.testing.v1 import AppTest

from fixtures.recovery_world import base_tables, world_tables, write_world
from mountain_perf.analyse.q2.results import (
    FIGURE_HTML,
    POWER_COLUMNS,
    POWER_DIR,
    POWER_FILE,
    PROVENANCE_FILE,
    RESULTS_DIR,
    TRIALS_FILE,
    csv_text,
    essais_csv,
    json_text,
)
from mountain_perf.analyse.q2.trials import TRIALS, TrialRow
from mountain_perf.analyse.tables import Tables
from mountain_perf.config import data_dir
from mountain_perf.ui.q2 import (
    fraction_text,
    interval_text,
    level_text,
    sentence,
    share_text,
)

TIMEOUT_S = 30
NAME = "2026-01-02_aaaaaaaaaaaa"
POWER_NAME = "2026-01-01_eeeeeeeeeeee"
MESSAGE = "données insuffisantes pour juger un effet de 5 %/an"
FIGURE = "<p>Résidus partiels, montées longues</p>"
NO_RESULT = (
    "Aucun résultat de Q2 dans resultats/Q2/ : lancer just q2 puissance, puis just q2."
)
HEADER = (
    "Résultat du 02/01/2026 (resultats/Q2/2026-01-02_aaaaaaaaaaaa/), tel que just q2 "
    "l'a écrit ; montées du 01/03/2025 au 31/12/2025."
)
EXPLORATORY = (
    "Exploratoire : tout résultat de Q2 l'est (docs/decisions/0023) ; les estimations "
    "se lisent avec leurs intervalles, sans verdict."
)
FIGURE_CAPTION = (
    "Descriptive, sans verdict : les résidus partiels de la date et une courbe "
    "lissée ; le dernier tronçon, en pointillé, est provisoire."
)
TRIALS_CAPTION = (
    "Les secondaires se lisent sur leurs intervalles à 99 % (Holm), ou au niveau "
    "calibré que donne la colonne Niveau ; les sensibilités sont rapportées, jamais "
    "promues."
)
SUBHEADERS = [
    "La lecture principale",
    "Les mises en garde",
    "La figure",
    "Les essais",
]
EXPANDERS = [
    "Le flux (journées et montées écartées, par étape)",
    "L'autocorrélation des résidus, par écart en jours",
]
UNREADABLE_1 = "Dossiers de résultats illisibles, ignorés : 1."
PHI_BULLET = (
    "- Les intervalles dépendent de la covariance estimée entre journées (portée "
    "φ̂ = 7,4 jours aux montées longues)."
)
WARNINGS = (
    "- Montées longues : à effet nul simulé, la lecture dit « établi » dans 3,1 % des "
    "tirages, pour un seuil nominal de 5,0 %.\n"
    "- Ski de randonnée : à effet nul simulé, la lecture dit « établi » dans 1,0 % "
    "des tirages, pour un seuil nominal de 1,0 %.\n"
    "- Montées longues : sous l'erreur de mesure simulée de la FC de la montée "
    "(scénario 4), la régression directe s'écarte en moyenne de −0,7 % par an, à un "
    "effet simulé de +5,0 % par an.\n" + PHI_BULLET
)
COLUMNS = [
    "Essai",
    "Famille",
    "Régime",
    "Mesure",
    "Estimation",
    "Intervalle",
    "Inverse",
    "Intervalle inverse",
    "Niveau",
    "Lecture",
    "Statut",
    "Mention",
]


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory) -> Tables:
    return base_tables(tmp_path_factory.mktemp("base"))


@pytest.fixture(autouse=True)
def _empty_cache() -> Iterator[None]:
    st.cache_resource.clear()
    yield
    st.cache_resource.clear()


# --- les dossiers inventés ----------------------------------------------------------


def _principal(**changes: Any) -> TrialRow:
    values: dict[str, Any] = {
        "essai": "P",
        "indice": 0,
        "famille": "principale",
        "regime": "long_climb",
        "mesure": "M-P",
        "statut": "estime",
        "n_journees": 17,
        "n_montees": 23,
        "niveau": 0.95,
        "estimation_fraction": 0.237,
        "intervalle_fraction": (-0.062, 0.412),
        "inverse_fraction": 0.31,
        "intervalle_inverse_fraction": (0.01, 0.6),
        "lecture": "non_tranche",
        "phrase": "les données ne tranchent pas",
        "mention": "optimiste",
        "phi": 7.36,
        "phi_a_la_borne_basse": False,
        "phi_a_la_borne_haute": False,
    }
    values.update(changes)
    return TrialRow(**values)


def _trials(principal: TrialRow | None = None) -> list[TrialRow]:
    """Les 24 essais : le principal, puis 23 lignes inventées ; S3 n'est pas faite,
    S-MP-cotes a une borne haute +∞, S-MP-ski un niveau calibré à 99,5 %."""
    rows = [_principal() if principal is None else principal]
    for trial in TRIALS[1:]:
        row = TrialRow(
            essai=trial.name,
            indice=trial.index,
            famille=trial.family.value,
            regime=trial.regime.value,
            mesure=trial.measure.value,
            statut="estime",
            niveau=0.99,
            estimation_fraction=0.02 * trial.index,
            intervalle_fraction=(-0.1, 0.3),
            lecture="non_tranche",
        )
        if trial.name == "S3":
            row = dataclasses.replace(
                row,
                statut="non_faite",
                motif="principal non estimé",
                niveau=None,
                estimation_fraction=None,
                intervalle_fraction=None,
                lecture=None,
            )
        if trial.name == "S-MP-cotes":
            row = dataclasses.replace(
                row, intervalle_fraction=(0.05, math.inf), mention="optimiste"
            )
        if trial.name == "S-MP-ski":
            row = dataclasses.replace(row, niveau=0.995)
        rows.append(row)
    return rows


def _regime(p_zero: float, alpha: float, message: str | None) -> dict[str, object]:
    return {
        "statut": "calculee",
        "a_zero": {
            "1": {"p_etabli": p_zero, "p_absence_effet_utile": 0.0},
            "2": {"p_etabli": 0.4, "p_absence_effet_utile": 0.0},
        },
        "seuils": [alpha],
        "calibration": {"declenchee": False, "alpha": alpha},
        "message": message,
    }


def _power(data: Path) -> str:
    """Le dossier de puissance nommé ; rend l'empreinte de son ``provenance.json``."""
    folder = data / POWER_DIR / POWER_NAME
    folder.mkdir(parents=True)
    document = {
        "genere_le": "2026-01-01",
        "parametres": {"delta": 0.05},
        "regimes": {
            "long_climb": _regime(0.0312, 0.05, MESSAGE),
            "short_climb": {"statut": "non_estimable", "motif": "trop peu"},
            "ski_touring": _regime(0.01, 0.01, None),
        },
    }
    (folder / PROVENANCE_FILE).write_text(
        json_text(document), encoding="utf-8", newline=""
    )
    rows = [
        ["long_climb", 4, 0.0, 3, 0, 0.1, 0.0, 0.1, 0.1, 0.0, 1.0, 0.011],
        ["long_climb", 4, 0.05, 3, 0, 0.6, 0.0, 0.1, 0.6, 0.0, 1.1, -0.007],
    ]
    (folder / POWER_FILE).write_text(
        csv_text(POWER_COLUMNS, rows), encoding="utf-8", newline=""
    )
    return hashlib.sha256((folder / PROVENANCE_FILE).read_bytes()).hexdigest()


def _result(
    tables: object,
    *,
    name: str = NAME,
    trials: str | None = None,
    figure: bool = True,
    power: bool = True,
    named: bool = True,
    bounds: Mapping[str, object] | None = None,
) -> Path:
    """Un dossier ``resultats/Q2/<name>/`` sous ``data_dir()``, et sa puissance."""
    data = data_dir()
    digest = _power(data) if power else "0" * 64
    folder = data / RESULTS_DIR / name
    folder.mkdir(parents=True)
    document: dict[str, object] = {
        "genere_le": name.split("_")[0],
        "tables": tables,
        "periode": {"debut": "2025-03-01", "fin": "2025-12-31"},
        "bornes": {} if bounds is None else bounds,
    }
    if named:
        document["puissance"] = {"dossier": POWER_NAME, "empreinte": digest}
    (folder / PROVENANCE_FILE).write_text(
        json_text(document), encoding="utf-8", newline=""
    )
    (folder / TRIALS_FILE).write_text(
        essais_csv(_trials()) if trials is None else trials,
        encoding="utf-8",
        newline="",
    )
    if figure:
        (folder / FIGURE_HTML).write_text(FIGURE, encoding="utf-8", newline="")
    return folder


def _written(base: Tables) -> Tables:
    tables = world_tables(base)
    write_world(data_dir(), tables)
    return tables


def _as_json(tables: Tables) -> object:
    return json.loads(json.dumps(dataclasses.asdict(tables.provenance)))


def _current(base: Tables) -> object:
    return _as_json(_written(base))


def _q2() -> None:
    from mountain_perf.ui.q2 import q2_page

    q2_page()


def _app() -> AppTest:
    return AppTest.from_function(_q2, default_timeout=TIMEOUT_S).run()


def _values(elements: Any) -> list[str]:
    return [element.value for element in elements]


def _iframes(at: AppTest) -> list[Any]:
    return list(at.get("iframe"))


def _table(at: AppTest, index: int = 0) -> Any:
    return at.dataframe[index].value


# --- U1 à U3 : l'en-tête -------------------------------------------------------------


def test_u1_without_result_asks_for_just_q2() -> None:
    at = _app()
    assert not at.exception
    assert [title.value for title in at.title] == ["Q2"]
    assert _values(at.info) == [NO_RESULT]
    assert not at.caption
    assert not _iframes(at)


def test_u2_a_whole_result_of_the_current_tables(base: Tables) -> None:
    _result(_current(base))
    at = _app()
    assert not at.exception
    assert not at.warning
    assert not at.error
    assert not at.info
    assert _values(at.caption) == [
        HEADER,
        EXPLORATORY,
        "Mention : optimiste.",
        FIGURE_CAPTION,
        TRIALS_CAPTION,
    ]
    assert _values(at.subheader) == SUBHEADERS
    assert [expander.label for expander in at.expander] == EXPANDERS
    (frame,) = _iframes(at)
    assert frame.proto.srcdoc == FIGURE


def test_u3_tables_of_another_run_warn(base: Tables) -> None:
    tables = _written(base)
    other = dataclasses.replace(tables.provenance, commit="d" * 40)
    _result(json.loads(json.dumps(dataclasses.asdict(other))))
    at = _app()
    assert not at.exception
    assert _values(at.warning) == [
        "Ce résultat ne vient pas des tables actuelles : just process a été relancé "
        "depuis (autre commit, autres paramètres, journal.csv retouché…). Relancer "
        "just q2 puissance, puis just q2, pour le refaire."
    ]


def test_u3_unreadable_tables_say_the_comparison_is_impossible() -> None:
    _result({"commit": "autre"})
    at = _app()
    assert not at.exception
    assert _values(at.warning) == [
        "Comparaison impossible : les tables actuelles ne se relisent pas. Le "
        "résultat est celui du dernier just q2."
    ]
    assert _values(at.subheader) == SUBHEADERS


# --- U4 à U6, U13 : la lecture principale ---------------------------------------------

DIRECT = "Régression directe : +23,7 % par an (de −6,2 % à +41,2 %, à 95 %)."
INVERSE = "Régression inverse : +31,0 % par an (de +1,0 % à +60,0 %, à 95 %)."


def test_u4_the_principal_reading(base: Tables) -> None:
    _result(_current(base))
    at = _app()
    assert not at.exception
    assert _values(at.markdown)[:4] == [
        "**Les données ne tranchent pas.**",
        "Données insuffisantes pour juger un effet de 5 %/an.",
        DIRECT,
        INVERSE,
    ]
    assert "Mention : optimiste." in _values(at.caption)


def test_u4_without_inverse_nor_mention(base: Tables) -> None:
    principal = _principal(
        inverse_fraction=None, intervalle_inverse_fraction=None, mention=None
    )
    _result(_current(base), trials=essais_csv(_trials(principal)))
    at = _app()
    assert not at.exception
    markdowns = _values(at.markdown)
    assert DIRECT in markdowns
    assert not [m for m in markdowns if m.startswith("Régression inverse")]
    assert not [c for c in _values(at.caption) if c.startswith("Mention")]


def test_u5_a_principal_not_estimated(base: Tables) -> None:
    principal = _principal(
        statut="non_estimable",
        motif="moins de 10 journées",
        estimation_fraction=None,
        intervalle_fraction=None,
        inverse_fraction=None,
        intervalle_inverse_fraction=None,
        phrase=None,
    )
    _result(_current(base), trials=essais_csv(_trials(principal)))
    at = _app()
    assert not at.exception
    markdowns = _values(at.markdown)
    assert markdowns[0] == "Non estimé : moins de 10 journées."
    assert not [m for m in markdowns if m.startswith("Régression")]


def test_u5_a_principal_not_estimated_without_motif(base: Tables) -> None:
    principal = _principal(statut="non_estimable", motif=None, phrase=None)
    _result(_current(base), trials=essais_csv(_trials(principal)))
    at = _app()
    assert not at.exception
    assert _values(at.markdown)[0] == "Non estimé."


def _bounds_captions(at: AppTest) -> list[str]:
    return [c for c in _values(at.caption) if c.startswith("Bornes")]


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        (
            {
                "statut": "declenchees",
                "journees_imputees": 1,
                "b_basse_fraction": 0.12,
                "b_haute_fraction": -0.03,
            },
            [
                "Bornes d'exclusion déclenchées (1 journée imputée) : aux deux bornes, "
                "la régression directe vaut +12,0 % et −3,0 % par an."
            ],
        ),
        (
            {
                "statut": "declenchees",
                "journees_imputees": 3,
                "b_basse_fraction": 0.12,
                "b_haute_fraction": None,
            },
            [
                "Bornes d'exclusion déclenchées (3 journées imputées) : aux deux "
                "bornes, la régression directe vaut +12,0 % et — par an."
            ],
        ),
        (
            {"statut": "non calculees", "motif": "x"},
            ["Bornes d'exclusion déclenchées, mais non calculées."],
        ),
        ({"statut": "non declenchees", "parts": {}}, []),
        ({"statut": "sans période"}, []),
    ],
)
def test_u6_the_bounds(
    base: Tables, entry: dict[str, object], expected: list[str]
) -> None:
    _result(_current(base), bounds={"long_climb": entry})
    at = _app()
    assert not at.exception
    captions = _bounds_captions(at)
    assert captions == expected
    for caption in captions:
        assert "basse" not in caption
        assert "haute" not in caption


def test_u6_bounds_of_another_regime_are_not_shown(base: Tables) -> None:
    entry = {"statut": "non calculees", "motif": "x"}
    _result(_current(base), bounds={"ski_touring": entry})
    assert _bounds_captions(_app()) == []


def test_u13_without_principal(base: Tables) -> None:
    _result(_current(base), trials=essais_csv(_trials()[1:]))
    at = _app()
    assert not at.exception
    assert _values(at.error) == ["essais.csv n'a pas d'essai principal (P)."]
    assert _values(at.subheader) == SUBHEADERS
    markdowns = _values(at.markdown)
    assert len(markdowns) == 1
    assert "φ̂" not in markdowns[0]
    assert markdowns[0].startswith("- Montées longues : à effet nul simulé")
    assert len(_iframes(at)) == 1
    assert len(_table(at)) == 23
    assert [expander.label for expander in at.expander] == EXPANDERS


# --- U7, U8, U16, U17 : les mises en garde --------------------------------------------


def test_u7_the_warnings(base: Tables) -> None:
    _result(_current(base))
    at = _app()
    assert not at.exception
    assert _values(at.markdown)[-1] == WARNINGS


def test_u8_without_the_power_the_rest_is_shown(base: Tables) -> None:
    _result(_current(base), power=False)
    at = _app()
    assert not at.exception
    assert _values(at.warning) == [
        "La puissance que nomme ce résultat (resultats/Q2/puissance/"
        "2026-01-01_eeeeeeeeeeee/) manque ou a changé : ses mises en garde ne "
        "s'affichent pas."
    ]
    markdowns = _values(at.markdown)
    assert markdowns[-1] == PHI_BULLET
    assert sentence(MESSAGE) not in markdowns
    assert _values(at.subheader) == SUBHEADERS
    assert len(_iframes(at)) == 1
    assert len(_table(at)) == 23


def test_u16_phi_at_an_edge(base: Tables) -> None:
    principal = _principal(phi_a_la_borne_haute=True)
    _result(_current(base), trials=essais_csv(_trials(principal)))
    at = _app()
    assert not at.exception
    assert _values(at.markdown)[-1].endswith(
        "\n- Les intervalles dépendent de la covariance estimée entre journées "
        "(portée φ̂ = 7,4 jours aux montées longues, à une borne de sa plage)."
    )


def test_u17_no_power_named(base: Tables) -> None:
    _result(_current(base), named=False)
    at = _app()
    assert not at.exception
    assert _values(at.warning) == [
        "Ce résultat ne nomme aucune puissance : ses mises en garde ne s'affichent pas."
    ]
    assert _values(at.markdown)[-1] == PHI_BULLET


# --- U9 à U11 : la figure, le tableau, sans verdict -----------------------------------


def test_u9_without_figure_the_table_still(base: Tables) -> None:
    _result(_current(base), figure=False)
    at = _app()
    assert not at.exception
    assert _values(at.error) == [
        "figure.html manque dans resultats/Q2/2026-01-02_aaaaaaaaaaaa/."
    ]
    assert not _iframes(at)
    assert FIGURE_CAPTION not in _values(at.caption)
    assert _values(at.subheader) == SUBHEADERS
    assert len(_table(at)) == 23


def test_u10_the_trials_table(base: Tables) -> None:
    _result(_current(base))
    at = _app()
    assert not at.exception
    table = _table(at)
    assert list(table.columns) == COLUMNS
    assert len(table) == 23
    rows = table.to_dict("records")
    assert [row["Essai"] for row in rows] == [t.name for t in TRIALS[1:]]
    by_name = {row["Essai"]: row for row in rows}
    assert by_name["S3"] == {
        "Essai": "S3",
        "Famille": "sensibilité",
        "Régime": "Montées longues",
        "Mesure": "M-P",
        "Estimation": "—",
        "Intervalle": "—",
        "Inverse": "—",
        "Intervalle inverse": "—",
        "Niveau": "—",
        "Lecture": "—",
        "Statut": "non faite : principal non estimé",
        "Mention": "",
    }
    cotes = by_name["S-MP-cotes"]
    assert cotes["Famille"] == "secondaire"
    assert cotes["Régime"] == "Côtes"
    assert cotes["Estimation"] == "+2,0 %"
    assert cotes["Intervalle"] == "de +5,0 % à +∞ %"
    assert cotes["Statut"] == "estimé"
    assert cotes["Mention"] == "optimiste"
    assert by_name["S-MP-ski"]["Niveau"] == "99,5 %"
    assert by_name["S-MP-ski"]["Régime"] == "Ski de randonnée"
    assert by_name["S-MS-longues"]["Niveau"] == "99 %"


def _texts(at: AppTest) -> list[str]:
    elements = [
        *at.title,
        *at.subheader,
        *at.caption,
        *at.markdown,
        *at.info,
        *at.warning,
        *at.error,
    ]
    return [str(element.value) for element in elements]


def test_u11_no_success_and_no_verdict(base: Tables) -> None:
    principal = _principal(lecture="etabli")
    _result(_current(base), trials=essais_csv(_trials(principal)))
    at = _app()
    assert not at.exception
    assert not at.success
    texts = " ".join(_texts(at)).lower()
    assert "significati" not in texts
    assert "★" not in texts
    assert "*" not in texts.replace("**", "")


# --- U12 : la mise en forme -----------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "—"),
        (math.inf, "+∞ %"),
        (-math.inf, "−∞ %"),
        (0.237, "+23,7 %"),
        (-0.062, "−6,2 %"),
        (2.15, "+215,0 %"),
        (0.0004, "0,0 %"),
        (-0.0004, "0,0 %"),
        (0.0, "0,0 %"),
    ],
)
def test_u12_fraction_text(value: float | None, expected: str) -> None:
    assert fraction_text(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, "—"), (0.0312, "3,1 %"), (0.01, "1,0 %"), (0.0, "0,0 %")],
)
def test_u12_share_text(value: float | None, expected: str) -> None:
    assert share_text(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "—"),
        (0.95, "95 %"),
        (0.99, "99 %"),
        (0.995, "99,5 %"),
        (0.975, "97,5 %"),
        (0.992, "99,2 %"),
    ],
)
def test_u12_level_text(value: float | None, expected: str) -> None:
    assert level_text(value) == expected


def test_u12_interval_text_and_sentence() -> None:
    assert interval_text(-0.062, 0.412) == "de −6,2 % à +41,2 %"
    assert interval_text(None, None) == "—"
    assert interval_text(0.05, math.inf) == "de +5,0 % à +∞ %"
    assert sentence("les données ne tranchent pas") == "Les données ne tranchent pas."
    assert sentence("déjà un point.") == "Déjà un point."


# --- U14, U15 : les dossiers illisibles, une case illisible ---------------------------


def test_u14_an_unreadable_folder_beside_the_result(base: Tables) -> None:
    _result(_current(base))
    broken = data_dir() / RESULTS_DIR / "2026-01-05_bbbbbbbbbbbb"
    broken.mkdir()
    (broken / PROVENANCE_FILE).write_text("{", encoding="utf-8")
    at = _app()
    assert not at.exception
    captions = _values(at.caption)
    assert captions[:3] == [HEADER, EXPLORATORY, UNREADABLE_1]


def test_u14_only_unreadable_folders_are_counted() -> None:
    broken = data_dir() / RESULTS_DIR / "2026-01-05_bbbbbbbbbbbb"
    broken.mkdir(parents=True)
    (broken / PROVENANCE_FILE).write_text("{", encoding="utf-8")
    at = _app()
    assert not at.exception
    assert _values(at.info) == [NO_RESULT]
    assert _values(at.caption) == [UNREADABLE_1]


def test_u15_an_unreadable_cell_stops_the_page_after_the_header() -> None:
    text = essais_csv(_trials()).replace("0.237", "abc", 1)
    _result({"commit": "autre"}, trials=text)
    broken = data_dir() / RESULTS_DIR / "2026-01-01_bbbbbbbbbbbb"
    broken.mkdir()
    at = _app()
    assert not at.exception
    assert _values(at.caption) == [
        "Résultat du 02/01/2026 (resultats/Q2/2026-01-02_aaaaaaaaaaaa/), tel que just "
        "q2 l'a écrit.",
        EXPLORATORY,
        UNREADABLE_1,
    ]
    assert len(at.warning) == 1
    (error,) = _values(at.error)
    assert "resultats/Q2/2026-01-02_aaaaaaaaaaaa/essais.csv" in error
    assert "estimation_fraction" in error
    assert not at.subheader
    assert not at.markdown
    assert not _iframes(at)
    assert not at.dataframe
    assert not at.expander


def test_the_page_writes_nothing_under_the_data_dir(base: Tables) -> None:
    _result(_current(base))
    root = data_dir()
    before = {
        p.relative_to(root).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(root.rglob("*"))
    }
    at = _app()
    assert not at.exception
    after = {
        p.relative_to(root).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(root.rglob("*"))
    }
    assert after == before
