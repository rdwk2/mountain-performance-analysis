"""Contrats d'``interim/days/`` (AN2-1) : le document d'un jour de Garmin, celui de
Training Status, le rapport des jours ; et les énumérations des vues des jours.

Fidèles à la source, comme ceux des activités (``docs/decisions/0013``, point 1) : les
valeurs sont celles des familles journalières, « selon Garmin », sans rien de calculé
sur une série ; une grandeur absente de la source est absente (``None``), jamais nulle.
Chaque sous-objet tiré d'une famille porte sa provenance (``SourceRef`` : ``kind`` =
``garmin_<famille>``, ``identifier`` = ``<AAAA-MM-JJ>.json``, empreinte du fichier,
instant d'acquisition de son export) ; un morceau emprunté à un autre export garde
celle de son export.

Instants *aware*, dans le décalage de leur source (local − GMT), jamais ramenés en UTC ;
durées en secondes ; unités dans les noms. **Aucun seuil des vues ici** : ce qui demande
un seuil (nuit courte, décalée, partielle, statut de la FC de repos, couverture) se
calcule à la lecture, par une vue qui le reçoit en argument
(``mountain_perf.ingest.day_views``).

Les documents s'écrivent et se relisent par le codec commun (``mountain_perf.codec``),
au format ``INTERIM_FORMAT_VERSION`` : d'où des ``tuple`` partout, jamais de
``frozenset`` ni de ``Sequence``, que le codec n'écrit pas.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from enum import StrEnum
from types import MappingProxyType

from mountain_perf.schemas.common import (
    ELEVATION_RANGE_M,
    HEART_RATE_RANGE_BPM,
    UTC_OFFSET_RANGE_S,
    SourceRef,
)
from mountain_perf.schemas.interim import ReadFile, require_export_name
from mountain_perf.validation import (
    ContractError,
    require_all_finite,
    require_all_in_range,
    require_aware,
    require_finite,
    require_immutable_sequence,
    require_in_range,
    require_increasing,
    require_min_length,
    require_non_empty,
    require_same_length,
)

_INF = float("inf")
_DAY = timedelta(days=1)


def _require_instant(value: datetime, name: str) -> datetime:
    """Un instant *aware*, son décalage dans ``UTC_OFFSET_RANGE_S``, en secondes
    entières ; rendu dans un fuseau à décalage fixe."""
    offset = require_aware(value, name)
    require_in_range(
        offset.total_seconds(), *UTC_OFFSET_RANGE_S, f"décalage de {name} (s)"
    )
    if offset % timedelta(seconds=1):
        raise ContractError(
            f"le décalage de {name} doit être un nombre entier de secondes."
        )
    return value.astimezone(timezone(offset))


def _require_optional_in_range(
    value: float | None, name: str, low: float, high: float = _INF
) -> None:
    if value is not None:
        require_finite(value, name)
        require_in_range(value, low, high, name)


def _require_at_least(value: int, low: int, name: str) -> None:
    if value < low:
        raise ContractError(f"{name} doit être >= {low}, reçu {value}.")


def _require_strictly_sorted(keys: Sequence[tuple[object, ...]], name: str) -> None:
    """Refuse des clés non triées ou répétées : un document n'a qu'une écriture."""
    for i in range(1, len(keys)):
        if not keys[i - 1] < keys[i]:
            raise ContractError(
                f"{name} doit être trié sans doublon : rangs {i - 1} et {i}."
            )


def _require_relative_name(name: str) -> None:
    require_non_empty(name, "name")
    parts = name.split("/")
    if "\\" in name or ":" in name or any(part in ("", ".", "..") for part in parts):
        raise ContractError(
            "name doit être un chemin relatif à raw/, séparé par « / », sans partie "
            "vide, « . » ni « .. »."
        )


# ---------------------------------------------------------------------------
# Énumérations
# ---------------------------------------------------------------------------


class DayFamily(StrEnum):
    """Une famille journalière d'un export Garmin : un dossier
    ``raw/garmin/<export>/<famille>/``, un fichier ``<AAAA-MM-JJ>.json`` par jour.

    Champs
    ------
    Valeurs décrites dans ``DAY_FAMILY_DESCRIPTIONS`` : le nom du dossier de la famille.

    Invariants
    ----------
    Énumération fermée : les onze familles journalières.
    ``range/`` et le profil ne sont pas des familles journalières : ils ne s'ingèrent
    pas.

    Producteur
    ----------
    La lecture des familles (``mountain_perf.ingest.families``).

    Consommateurs
    -------------
    ``DayRecord.window_family`` ; le rapport des jours (``DaysReport``), qui compte par
    famille ; ``SourceRef.kind`` des sous-objets (``garmin_<famille>``).

    Non promis
    ----------
    Une famille présente un jour peut y être vide (``{}`` ou ``[]``) : elle est alors
    absente ce jour-là.
    """

    SLEEP = "sleep"
    HRV = "hrv"
    RESTING_HR = "resting_hr"
    HEART_RATE = "heart_rate"
    BODY_BATTERY = "body_battery"
    STRESS = "stress"
    RESPIRATION = "respiration"
    SPO2 = "spo2"
    DAILY_SUMMARY = "daily_summary"
    TRAINING_READINESS = "training_readiness"
    TRAINING_STATUS = "training_status"


DAY_FAMILY_DESCRIPTIONS: Mapping[DayFamily, str] = MappingProxyType(
    {
        DayFamily.SLEEP: (
            "La nuit principale rattachée au jour du réveil, ses phases, ses séries, "
            "ses résumés, et les siestes du jour."
        ),
        DayFamily.HRV: "La HRV de la nuit, de la semaine, son statut et ses bornes.",
        DayFamily.RESTING_HR: "La FC de repos selon Garmin.",
        DayFamily.HEART_RATE: "La série de FC de la journée et la fenêtre du jour.",
        DayFamily.BODY_BATTERY: (
            "Les repères de Body Battery du jour (copie contrôlée de daily_summary) ; "
            "ses événements ne s'ingèrent pas."
        ),
        DayFamily.STRESS: (
            "Les séries de stress et de Body Battery (avec statut et version) de la "
            "journée, et la fenêtre du jour."
        ),
        DayFamily.RESPIRATION: (
            "La série de respiration de la journée, les résumés de la nuit et de "
            "l'éveil, la fenêtre du jour ; les champs tomorrow… ne s'ingèrent pas."
        ),
        DayFamily.SPO2: (
            "Les moyennes horaires de SpO2, les résumés de la nuit et du jour, la "
            "fenêtre du jour ; les champs tomorrow… ne s'ingèrent pas."
        ),
        DayFamily.DAILY_SUMMARY: (
            "Le résumé du jour : fenêtre, indicateur de présence, stress, Body "
            "Battery, pas, intensité, étages, altitude moyenne."
        ),
        DayFamily.TRAINING_READINESS: (
            "Les entrées de Training Readiness du jour, de zéro à plusieurs."
        ),
        DayFamily.TRAINING_STATUS: (
            "Les blocs de Training Status, chacun à sa date propre : statut, équilibre "
            "de la charge, VO2max, acclimatations."
        ),
    }
)

DAY_WINDOW_FAMILIES: tuple[DayFamily, ...] = (
    DayFamily.DAILY_SUMMARY,
    DayFamily.HEART_RATE,
    DayFamily.STRESS,
    DayFamily.RESPIRATION,
    DayFamily.SPO2,
)
"""Les familles d'où peut venir la fenêtre du jour, dans l'ordre où elle s'y lit :
``daily_summary``, sinon la première qui en porte une."""

WAKING_CONTEXT = "AFTER_WAKEUP_RESET"
"""Le contexte d'une entrée « réveil » de Training Readiness
(``training_readiness[*].inputContext``, code de la source fixé en comptes sur les
exports) : l'un des contextes connus de la lecture des familles
(``mountain_perf.ingest.families.READINESS_CONTEXTS``), et celui que cherche la vue
``readiness_on_waking``. Un code, pas un seuil ; déclaré une seule fois, ici, pour la
lecture et pour les vues, qui ne s'importent pas l'une l'autre."""


class DayState(StrEnum):
    """L'état d'un jour, décidé à l'ingestion **dans l'ordre des membres** : le
    premier cas qui s'applique.

    Champs
    ------
    Valeurs décrites dans ``DAY_STATE_DESCRIPTIONS`` (entre guillemets, le terme de
    l'athlète).

    Invariants
    ----------
    Énumération fermée, ordonnée : ``empty``, ``no_measurement``, ``truncated``,
    ``complete``.

    Producteur
    ----------
    L'ingestion des jours (``mountain_perf.ingest.days``), sur l'export de référence
    du jour.

    Consommateurs
    -------------
    ``DayRecord.state`` ; le choix de l'export de référence ; les vues des jours ; la
    table ``jours`` (AN2-2), qui retire les grandeurs ``day`` des jours ``truncated``,
    ``empty`` et ``no_measurement``.

    Non promis
    ----------
    L'état ne retire rien d'``interim/`` : les valeurs restent telles que la source les
    donne, quel que soit l'état. ``absent`` (un jour du calendrier sans document)
    n'existe que dans ``jours``.
    """

    EMPTY = "empty"
    NO_MEASUREMENT = "no_measurement"
    TRUNCATED = "truncated"
    COMPLETE = "complete"


DAY_STATE_DESCRIPTIONS: Mapping[DayState, str] = MappingProxyType(
    {
        DayState.EMPTY: (
            "« vide » : aucune famille ne porte de fenêtre du jour (la fenêtre de la "
            "nuit de sleep n'en est pas une)."
        ),
        DayState.NO_MEASUREMENT: (
            "« sans_mesure » : l'indicateur de présence de daily_summary est faux ; "
            "ou, sans indicateur, aucun échantillon mesuré dans les séries du jour et "
            "pas de nuit."
        ),
        DayState.TRUNCATED: (
            "« tronqué » : fin_donnees précède début + 24 h (jour pris en cours de "
            "journée, montre non synchronisée, ou montre arrêtée)."
        ),
        DayState.COMPLETE: "« complet » : aucun des cas précédents.",
    }
)


class Support(StrEnum):
    """Le support d'une grandeur d'un jour : ce sur quoi elle porte, et d'où vient son
    instant propre.

    Champs
    ------
    Valeurs décrites dans ``SUPPORT_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée. Chaque grandeur de ``DayRecord`` déclare le sien, dans la
    docstring de son contrat et dans ``QUANTITY_SUPPORTS``.

    Producteur
    ----------
    Déclaré ici, une fois pour toutes (``QUANTITY_SUPPORTS``).

    Consommateurs
    -------------
    Les vues des jours (l'instant propre d'une grandeur) ; la table ``jours`` (AN2-2),
    qui retire les grandeurs ``day`` d'un jour ``truncated``, ``empty`` ou
    ``no_measurement``.

    Non promis
    ----------
    Le support ne dit pas la fenêtre exacte de calcul de Garmin, qui n'est pas publiée
    (la FC de repos peut venir du début de la nuit suivante, ``PIEGES_DATA``).
    """

    NIGHT = "night"
    WAKING = "waking"
    DAY = "day"
    INSTANT = "instant"


SUPPORT_DESCRIPTIONS: Mapping[Support, str] = MappingProxyType(
    {
        Support.NIGHT: (
            "« nuit » : la nuit principale rattachée au jour ; instant propre, la fin "
            "de la nuit."
        ),
        Support.WAKING: (
            "« reveil » : une grandeur que Garmin fixe au réveil, à la fin de la nuit "
            "principale (Body Battery au réveil, HRV de la semaine, statut et "
            "bornes) ; instant propre, la fin de la nuit."
        ),
        Support.DAY: (
            "« journee » : la journée de Garmin ; instant propre, la fin de la fenêtre "
            "du jour : le plus tard de son début + 24 h et de sa fin des données, lue "
            "dans le seul document du jour (un jour de 25 h complet : le minuit local "
            "qui suit ; un jour de 23 h : début + 24 h, une heure après sa vraie fin ; "
            "le jour du passage à l'heure d'hiver dont les données finissent au plus "
            "tard à début + 24 h, tronqué ou écrit sur 24 h : début + 24 h, au plus "
            "une heure avant son minuit local ; s'il finit entre début + 24 h et ce "
            "minuit : sa fin des données)."
        ),
        Support.INSTANT: (
            "« instant » : un point ou un épisode daté par lui-même (point de série, "
            "entrée de Training Readiness, sieste) ; instant propre, le sien (la fin "
            "d'une sieste ; l'instant d'un point d'une série de la nuit, une fois la "
            "nuit finie)."
        ),
    }
)


class SleepStage(StrEnum):
    """La phase d'un segment de sommeil.

    Champs
    ------
    Valeurs décrites dans ``SLEEP_STAGE_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée. Les codes de la source (``sleepLevels[*].activityLevel``) se
    traduisent par une table de la lecture des familles, fixée en comptes sur
    les exports : les durées des segments par code redonnent celles du résumé. Un code
    inconnu fait écarter son segment, compté avec son code.

    Producteur
    ----------
    La lecture des familles (``sleep``).

    Consommateurs
    -------------
    ``SleepSegment`` ; la vue ``sleep_within`` (l'union des segments de sommeil).

    Non promis
    ----------
    Les phases sont celles de l'algorithme de Garmin, non publié ; aucune question ne
    se bâtit sur le profond ou le paradoxal.
    """

    DEEP = "deep"
    LIGHT = "light"
    REM = "rem"
    AWAKE = "awake"
    UNMEASURABLE = "unmeasurable"


SLEEP_STAGE_DESCRIPTIONS: Mapping[SleepStage, str] = MappingProxyType(
    {
        SleepStage.DEEP: "Sommeil profond.",
        SleepStage.LIGHT: "Sommeil léger.",
        SleepStage.REM: "Sommeil paradoxal.",
        SleepStage.AWAKE: "Éveil.",
        SleepStage.UNMEASURABLE: (
            "Non mesurable : temps que la montre n'a pas classé (une sentinelle de la "
            "source, pas une phase)."
        ),
    }
)


class BodyBatteryStatus(StrEnum):
    """Le statut d'un point de la série de Body Battery du jour (codes de la source
    ``MEASURED``, ``MODELED``, ``RESET``).

    Champs
    ------
    Valeurs décrites dans ``BODY_BATTERY_STATUS_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée ; un code inconnu fait écarter son point, compté avec son code.

    Producteur
    ----------
    La lecture des familles (``stress.bodyBatteryValuesArray``, deuxième colonne).

    Consommateurs
    -------------
    ``BodyBatterySeries`` ; la vue ``body_battery_at`` ; ``bb_plafond`` (AN2-2), qu'une
    remise à zéro coupe.

    Non promis
    ----------
    Les points de la série de la nuit (``sleep``) n'ont pas de statut : la source n'en
    porte pas.
    """

    MEASURED = "measured"
    MODELED = "modeled"
    RESET = "reset"


BODY_BATTERY_STATUS_DESCRIPTIONS: Mapping[BodyBatteryStatus, str] = MappingProxyType(
    {
        BodyBatteryStatus.MEASURED: "MEASURED : valeur que Garmin dit mesurée.",
        BodyBatteryStatus.MODELED: "MODELED : valeur que Garmin dit modélisée.",
        BodyBatteryStatus.RESET: "RESET : remise à zéro de la série ; elle la coupe.",
    }
)


class DayFileRefusal(StrEnum):
    """Pourquoi la lecture des familles refuse un fichier journalier.

    Champs
    ------
    Valeurs décrites dans ``DAY_FILE_REFUSAL_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée. Un fichier refusé ne donne rien au jour ; il reste compté au
    rapport (``DayFileRefused``).

    Producteur
    ----------
    La lecture des familles.

    Consommateurs
    -------------
    ``DayFileRefused`` ; le rapport des jours.

    Non promis
    ----------
    Le motif ne dit pas la cause matérielle (export interrompu, format changé par
    Garmin).
    """

    UNREADABLE_JSON = "unreadable_json"
    UNEXPECTED_SHAPE = "unexpected_shape"
    DATE_MISMATCH = "date_mismatch"
    NO_PRIMARY_DEVICE = "no_primary_device"


DAY_FILE_REFUSAL_DESCRIPTIONS: Mapping[DayFileRefusal, str] = MappingProxyType(
    {
        DayFileRefusal.UNREADABLE_JSON: "Fichier qui ne se lit pas en JSON (UTF-8).",
        DayFileRefusal.UNEXPECTED_SHAPE: (
            "JSON dont la forme n'est pas celle de la famille (racine, type d'un champ "
            "lu)."
        ),
        DayFileRefusal.DATE_MISMATCH: (
            "Document dont la date n'est pas celle du nom de son fichier."
        ),
        DayFileRefusal.NO_PRIMARY_DEVICE: (
            "Training Status à plusieurs appareils, sans appareil que la source dit "
            "principal."
        ),
    }
)


class PointDiscard(StrEnum):
    """Pourquoi la lecture des familles écarte un point d'une série, un segment de
    phase, un épisode (nuit, sieste), la fenêtre du jour d'un fichier, une entrée de
    Training Readiness ou une valeur d'un résumé ; et pourquoi l'ingestion des jours
    jette les points et les segments qu'elle ne peut pas placer (``no_night``,
    ``no_window``).

    Champs
    ------
    Valeurs décrites dans ``POINT_DISCARD_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée. Le contrat est strict, l'ingestion tolérante et tracée : rien
    n'est corrigé en silence, tout point écarté est compté sous l'un de ces motifs
    (``0013``, point 5).

    Producteur
    ----------
    La lecture des familles ; l'ingestion des jours (``no_night``, ``no_window``).

    Consommateurs
    -------------
    ``PointDiscardCount`` ; le rapport des jours.

    Non promis
    ----------
    Un point gardé n'est pas garanti juste : seulement conforme au contrat. Un point
    hors de la fenêtre de son fichier n'est pas écarté : il est gardé et compté à part
    (``WindowEdgeCount``).
    """

    NULL_VALUE = "null_value"
    OUT_OF_RANGE = "out_of_range"
    UNKNOWN_CODE = "unknown_code"
    NOT_INCREASING = "not_increasing"
    DUPLICATE_INSTANT = "duplicate_instant"
    OVERLAPPING_SEGMENT = "overlapping_segment"
    NO_NIGHT = "no_night"
    NO_WINDOW = "no_window"


POINT_DISCARD_DESCRIPTIONS: Mapping[PointDiscard, str] = MappingProxyType(
    {
        PointDiscard.NULL_VALUE: (
            "Point sans valeur (null) ni code ; point de Body Battery du jour sans "
            "statut ; épisode, fenêtre ou entrée à qui manque une borne ou son "
            "horodatage ; code texte blanc."
        ),
        PointDiscard.OUT_OF_RANGE: (
            "Valeur non finie, non entière pour un niveau ou un compte, ou hors de la "
            "plage déclarée de sa grandeur (un zéro de la FC en est une ; le zéro du "
            "stress et du Body Battery est dans leur plage) ; instant ou décalage hors "
            "de sa plage."
        ),
        PointDiscard.UNKNOWN_CODE: (
            "Code sentinelle, de statut ou de phase inconnu ; compté aussi avec sa "
            "valeur (CodeCount)."
        ),
        PointDiscard.NOT_INCREASING: (
            "Instant antérieur au dernier gardé de sa série ; segment, nuit ou sieste "
            "dont la fin ne suit pas strictement le début ; fenêtre du jour dont la "
            "fin précède le début."
        ),
        PointDiscard.DUPLICATE_INSTANT: (
            "Instant égal à celui du dernier point gardé de sa série : le premier est "
            "gardé, les suivants comptés."
        ),
        PointDiscard.OVERLAPPING_SEGMENT: (
            "Segment de phase qui recouvre le dernier segment gardé."
        ),
        PointDiscard.NO_NIGHT: (
            "Point d'une série de la nuit, ou segment de phase, d'un document sleep "
            "dont la nuit est absente ou écartée : ses instants partent du début de la "
            "nuit, il n'a pas où se ranger ; jeté par l'ingestion des jours, compté "
            "sous le chemin de sa série."
        ),
        PointDiscard.NO_WINDOW: (
            "Point d'une série du jour d'un jour sans fenêtre (empty) : ses instants "
            "partent du début de la fenêtre du jour ; jeté par l'ingestion des jours, "
            "compté sous le chemin de sa série."
        ),
    }
)


class BorrowingRefusal(StrEnum):
    """Pourquoi un morceau d'un autre export n'est pas emprunté par l'export de
    référence d'un jour.

    Champs
    ------
    Valeurs décrites dans ``BORROWING_REFUSAL_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée : les grandeurs communes dont le désaccord refuse l'emprunt.
    Rien en commun : l'emprunt se fait.

    Producteur
    ----------
    L'ingestion des jours.

    Consommateurs
    -------------
    ``BorrowingRefusalCount`` ; le rapport des jours.

    Non promis
    ----------
    Le refus ne dit pas lequel des deux exports a raison : le morceau reste absent.
    """

    DAY_WINDOW = "day_window"
    NIGHT_WINDOW = "night_window"
    NIGHT_DURATIONS = "night_durations"


BORROWING_REFUSAL_DESCRIPTIONS: Mapping[BorrowingRefusal, str] = MappingProxyType(
    {
        BorrowingRefusal.DAY_WINDOW: (
            "Début de la fenêtre du jour différent (instant ou décalage) : séries du "
            "jour, ou famille qui porte la fenêtre du jour."
        ),
        BorrowingRefusal.NIGHT_WINDOW: (
            "Fenêtre de la nuit différente à la seconde : séries et segments de la "
            "nuit, ou famille qui porte la fenêtre de la nuit."
        ),
        BorrowingRefusal.NIGHT_DURATIONS: (
            "Segments qui ne redonnent pas les durées du résumé de la nuit de la "
            "référence, à la tolérance de la nuit."
        ),
    }
)


class TrainingStatusKind(StrEnum):
    """La sorte d'un bloc de Training Status.

    Champs
    ------
    Valeurs décrites dans ``TRAINING_STATUS_KIND_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée : une suite de blocs par sorte dans
    ``TrainingStatusHistory``.

    Producteur
    ----------
    La lecture des familles (``training_status``).

    Consommateurs
    -------------
    ``TrainingStatusHistory`` ; la vue ``training_status_at`` ; le rapport des jours
    (blocs refusés, écarts, blocs sans instant propre).

    Non promis
    ----------
    Les sortes ne sont pas comparables entre elles : chacune a sa date propre.
    """

    STATUS = "status"
    LOAD_BALANCE = "load_balance"
    VO2_MAX = "vo2_max"
    HEAT_ACCLIMATION = "heat_acclimation"
    ALTITUDE_ACCLIMATION = "altitude_acclimation"


TRAINING_STATUS_KIND_DESCRIPTIONS: Mapping[TrainingStatusKind, str] = MappingProxyType(
    {
        TrainingStatusKind.STATUS: (
            "Le statut, son horodatage, les charges aiguë et chronique et leur rapport "
            "(mostRecentTrainingStatus.latestTrainingStatusData)."
        ),
        TrainingStatusKind.LOAD_BALANCE: (
            "L'équilibre de la charge : charges mensuelles et cibles "
            "(mostRecentTrainingLoadBalance)."
        ),
        TrainingStatusKind.VO2_MAX: (
            "La VO2max (mostRecentVO2Max.generic) ; elle peut être une valeur reportée."
        ),
        TrainingStatusKind.HEAT_ACCLIMATION: (
            "L'acclimatation à la chaleur (heatAltitudeAcclimation, "
            "heatAcclimationDate)."
        ),
        TrainingStatusKind.ALTITUDE_ACCLIMATION: (
            "L'acclimatation à l'altitude (heatAltitudeAcclimation, "
            "altitudeAcclimationDate)."
        ),
    }
)


class ComparisonClass(StrEnum):
    """La classe d'un écart entre deux exports pour un même jour.

    Champs
    ------
    Valeurs décrites dans ``COMPARISON_CLASS_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée : chaque écart compté l'est sous une seule classe.

    Producteur
    ----------
    L'ingestion des jours, qui compare l'export de référence aux autres exports qui
    portent le jour.

    Consommateurs
    -------------
    ``ComparisonCount`` ; le rapport des jours ; la charte, § 7 (une métrique dont les
    révisions ne sont pas nulles est signalée).

    Non promis
    ----------
    Une révision ne dit pas laquelle des deux valeurs est juste : la valeur gardée est
    celle de l'export de référence.
    """

    REVISION = "revision"
    DEGRADATION = "degradation"
    BORROWING = "borrowing"
    SET_APART = "set_apart"


COMPARISON_CLASS_DESCRIPTIONS: Mapping[ComparisonClass, str] = MappingProxyType(
    {
        ComparisonClass.REVISION: (
            "Révision : un champ présent dans les deux exports, de valeurs "
            "différentes, entre deux exports où le jour est complet et aussi riches "
            "(le détail dans les deux, ou dans aucun), hors d'un emprunt."
        ),
        ComparisonClass.DEGRADATION: (
            "Dégradation : le plus récent des deux exports n'a plus le détail que "
            "l'ancien avait ; tout écart de ce jour entre eux, hors d'un emprunt : un "
            "champ changé, disparu ou apparu."
        ),
        ComparisonClass.BORROWING: (
            "Emprunt : un écart sur ce que l'export de référence a reçu d'un autre "
            "export : toute feuille d'une famille reçue entière (ses copies et sa "
            "série du jour refusée à l'emprunt comprises), la feuille d'une série ou "
            "des segments reçus seuls."
        ),
        ComparisonClass.SET_APART: (
            "Reste à part : tout autre écart : un champ présent d'un seul côté entre "
            "deux exports où le jour est complet et aussi riches ; tout écart entre "
            "deux exports inégalement riches dont le récent est le plus riche, ou d'un "
            "jour qui n'est pas complet dans les deux."
        ),
    }
)


class NightState(StrEnum):
    """L'état de la nuit d'un jour, décidé par la vue ``night_assessment`` **dans
    l'ordre des membres**.

    Champs
    ------
    Valeurs décrites dans ``NIGHT_STATE_DESCRIPTIONS`` (entre guillemets, le terme de
    l'athlète).

    Invariants
    ----------
    Énumération fermée, ordonnée : ``missing``, ``declared``, ``in_progress``,
    ``partial``, ``complete`` ; d'où ``in_progress`` avant ``partial``.

    Producteur
    ----------
    La vue ``night_assessment`` (``mountain_perf.ingest.day_views``), avec ses seuils
    en arguments.

    Consommateurs
    -------------
    La table ``jours`` (AN2-2) ; la couche des manques de la page « récupération »
    (AN2-3).

    Non promis
    ----------
    Jamais écrit dans ``interim/days/`` : l'état dépend des seuils de la vue.
    """

    MISSING = "missing"
    DECLARED = "declared"
    IN_PROGRESS = "in_progress"
    PARTIAL = "partial"
    COMPLETE = "complete"


NIGHT_STATE_DESCRIPTIONS: Mapping[NightState, str] = MappingProxyType(
    {
        NightState.MISSING: (
            "« manquante » : pas de nuit principale rattachée au jour."
        ),
        NightState.DECLARED: (
            "« declaree » : nuit saisie sans montre, ssi la source ne la dit pas venue "
            "de la montre (Night.from_device faux)."
        ),
        NightState.IN_PROGRESS: (
            "« en_cours » : finie après fin_donnees, ou fenêtre provisoire (la source "
            "ne la dit pas confirmée : Night.window_confirmed faux) ; sans "
            "fin_donnees, seulement la seconde."
        ),
        NightState.PARTIAL: (
            "« partielle » : part non mesurable du temps au lit au-delà du seuil passé "
            "à la vue, ou inconnue (non mesurable absent)."
        ),
        NightState.COMPLETE: "« complete » : aucun des cas précédents.",
    }
)


class NightFlag(StrEnum):
    """Un drapeau de la nuit d'un jour, posé par la vue ``night_assessment``.

    Champs
    ------
    Valeurs décrites dans ``NIGHT_FLAG_DESCRIPTIONS`` (entre guillemets, le terme de
    l'athlète).

    Invariants
    ----------
    Énumération fermée ; les drapeaux se cumulent, à côté de l'état.

    Producteur
    ----------
    La vue ``night_assessment``, avec ses seuils en arguments.

    Consommateurs
    -------------
    La table ``jours`` (AN2-2) : une nuit ``short`` ou ``shifted`` n'entre dans aucune
    normale de mesure de nuit.

    Non promis
    ----------
    ``shifted`` est inconnu (ni posé ni exclu) sous le minimum de nuits du milieu
    habituel, ou si leurs milieux n'ont pas de moyenne circulaire.
    """

    SHORT = "short"
    SHIFTED = "shifted"


NIGHT_FLAG_DESCRIPTIONS: Mapping[NightFlag, str] = MappingProxyType(
    {
        NightFlag.SHORT: "« courte » : sommeil mesuré sous le seuil passé à la vue.",
        NightFlag.SHIFTED: (
            "« decalee » : milieu de la nuit plus loin du milieu habituel que le seuil "
            "passé à la vue (moyenne circulaire, heures locales de la source)."
        ),
    }
)


class RestingHrStatus(StrEnum):
    """Le statut de la FC de repos d'un jour, décidé par la vue ``resting_hr_on``
    **dans l'ordre des membres**.

    Champs
    ------
    Valeurs décrites dans ``RESTING_HR_STATUS_DESCRIPTIONS`` (entre guillemets, le
    terme de l'athlète).

    Invariants
    ----------
    Énumération fermée, ordonnée : ``absent``, ``provisional``, ``no_night``,
    ``valid``.

    Producteur
    ----------
    Les vues ``resting_hr_on`` et ``resting_hr_at``, avec leur seuil en argument.

    Consommateurs
    -------------
    La table ``jours`` (AN2-2) : seule ``valid`` entre dans les normales ; M7 (la FC de
    repos à l'instant).

    Non promis
    ----------
    Jamais écrit dans ``interim/days/`` : le statut dépend du seuil de la vue.
    """

    ABSENT = "absent"
    PROVISIONAL = "provisional"
    NO_NIGHT = "no_night"
    VALID = "valid"


RESTING_HR_STATUS_DESCRIPTIONS: Mapping[RestingHrStatus, str] = MappingProxyType(
    {
        RestingHrStatus.ABSENT: (
            "« absente » : la valeur manque, ou le jour est vide, sans mesure ou sans "
            "document."
        ),
        RestingHrStatus.PROVISIONAL: (
            "« provisoire » : jour tronqué, qu'il ait une nuit ou non."
        ),
        RestingHrStatus.NO_NIGHT: (
            "« sans_nuit » : la nuit rattachée au jour manque, ou son sommeil mesuré "
            "est absent ou sous le seuil passé à la vue."
        ),
        RestingHrStatus.VALID: "« valide » : aucun des cas précédents.",
    }
)


class SeriesKind(StrEnum):
    """Une série d'un jour que lit la vue ``series_between`` : une série de la journée
    (``DaySeries``, instants depuis le début de la fenêtre du jour) ou de la nuit
    (``NightSeries``, instants depuis le début de la nuit).

    Champs
    ------
    Valeurs décrites dans ``SERIES_KIND_DESCRIPTIONS`` (avec l'unité de la valeur que
    la vue rend pour chaque point).

    Invariants
    ----------
    Énumération fermée : une valeur par champ de ``DaySeries`` (préfixe ``day_``) et de
    ``NightSeries`` (préfixe ``night_``).

    Producteur
    ----------
    L'appelant de la vue ``series_between`` (M7, la piste).

    Consommateurs
    -------------
    La vue ``series_between`` (``mountain_perf.ingest.day_views``).

    Non promis
    ----------
    Une série de la journée et la série de la nuit de la même grandeur ne se recollent
    pas : la vue en lit une seule.
    """

    DAY_HEART_RATE = "day_heart_rate"
    DAY_STRESS = "day_stress"
    DAY_BODY_BATTERY = "day_body_battery"
    DAY_RESPIRATION = "day_respiration"
    DAY_SPO2 = "day_spo2"
    NIGHT_HEART_RATE = "night_heart_rate"
    NIGHT_STRESS = "night_stress"
    NIGHT_BODY_BATTERY = "night_body_battery"
    NIGHT_HRV = "night_hrv"
    NIGHT_RESPIRATION = "night_respiration"
    NIGHT_SPO2 = "night_spo2"
    NIGHT_RESTLESS_MOMENTS = "night_restless_moments"


SERIES_KIND_DESCRIPTIONS: Mapping[SeriesKind, str] = MappingProxyType(
    {
        SeriesKind.DAY_HEART_RATE: "FC de la journée (DaySeries.heart_rate), bpm.",
        SeriesKind.DAY_STRESS: (
            "Stress de la journée (DaySeries.stress) : niveau sans unité, ou code."
        ),
        SeriesKind.DAY_BODY_BATTERY: (
            "Body Battery de la journée (DaySeries.body_battery) : niveau sans unité "
            "et statut."
        ),
        SeriesKind.DAY_RESPIRATION: (
            "Respiration de la journée (DaySeries.respiration) : respirations par "
            "minute, ou code."
        ),
        SeriesKind.DAY_SPO2: (
            "Moyennes horaires de SpO2 de la journée (DaySeries.spo2), pourcentage."
        ),
        SeriesKind.NIGHT_HEART_RATE: "FC de la nuit (NightSeries.heart_rate), bpm.",
        SeriesKind.NIGHT_STRESS: (
            "Stress de la nuit (NightSeries.stress) : niveau sans unité, ou code."
        ),
        SeriesKind.NIGHT_BODY_BATTERY: (
            "Body Battery de la nuit (NightSeries.body_battery) : niveau sans unité, "
            "sans statut."
        ),
        SeriesKind.NIGHT_HRV: "HRV de 5 min de la nuit (NightSeries.hrv), ms.",
        SeriesKind.NIGHT_RESPIRATION: (
            "Respiration de la nuit (NightSeries.respiration) : respirations par "
            "minute, ou code."
        ),
        SeriesKind.NIGHT_SPO2: "SpO2 de la nuit (NightSeries.spo2), pourcentage.",
        SeriesKind.NIGHT_RESTLESS_MOMENTS: (
            "Moments agités de la nuit (NightSeries.restless_moments), nombre."
        ),
    }
)


class ViewAbsence(StrEnum):
    """Pourquoi une vue des jours rend une grandeur absente.

    Champs
    ------
    Valeurs décrites dans ``VIEW_ABSENCE_DESCRIPTIONS`` (entre parenthèses, la vue qui
    rend le motif).

    Invariants
    ----------
    Énumération fermée ; une grandeur absente porte un seul motif, le premier
    rencontré par la vue.

    Producteur
    ----------
    Les vues des jours (``mountain_perf.ingest.day_views``).

    Consommateurs
    -------------
    La table ``jours`` (AN2-2), qui écrit le motif d'une grandeur absente ; M7.

    Non promis
    ----------
    Le motif ne dit pas la cause matérielle (montre retirée, détail effacé par Garmin).
    """

    NO_SEGMENTS = "no_segments"
    NO_NIGHT = "no_night"
    NO_ENTRY_AFTER_NIGHT = "no_entry_after_night"
    BELOW_COVERAGE = "below_coverage"
    NO_POINT = "no_point"
    NO_EPISODE = "no_episode"
    NO_MEASURED_SLEEP = "no_measured_sleep"
    NO_UNMEASURABLE = "no_unmeasurable"
    BELOW_USUAL_MINIMUM = "below_usual_minimum"
    NO_NIGHT_BEFORE = "no_night_before"
    NO_BLOCK = "no_block"
    NO_ENTRY = "no_entry"
    NO_RESTING_HR = "no_resting_hr"
    DISPERSED_MIDPOINTS = "dispersed_midpoints"


VIEW_ABSENCE_DESCRIPTIONS: Mapping[ViewAbsence, str] = MappingProxyType(
    {
        ViewAbsence.NO_SEGMENTS: (
            "Une nuit qui recouvre un autre épisode n'a pas ses segments (Garmin a "
            "effacé le détail) (sleep_within)."
        ),
        ViewAbsence.NO_NIGHT: (
            "« nuit_manquante » : pas de nuit principale rattachée au jour "
            "(readiness_on_waking ; drapeaux de night_assessment)."
        ),
        ViewAbsence.NO_ENTRY_AFTER_NIGHT: (
            "« aucune_apres_nuit » : aucune entrée « réveil » de Training Readiness "
            "d'instant au moins la fin de la nuit moins la tolérance, avant la sieste "
            "suivante (readiness_on_waking)."
        ),
        ViewAbsence.BELOW_COVERAGE: (
            "Couverture sous le minimum passé à la vue (series_between)."
        ),
        ViewAbsence.NO_POINT: (
            "Aucun point de la série dans l'intervalle demandé (series_between), ou au "
            "plus tard à l'instant (body_battery_at)."
        ),
        ViewAbsence.NO_EPISODE: (
            "Aucun épisode (nuit, sieste) fini au plus tard à la fin de l'intervalle "
            "qui le recoupe (sleep_within)."
        ),
        ViewAbsence.NO_MEASURED_SLEEP: (
            "Le sommeil mesuré d'une nuit manque (Night.measured_sleep_s absent : "
            "profond ou léger absent, ou paradoxal absent d'un appareil qui le "
            "détecte) (sleep_within ; drapeau short de night_assessment)."
        ),
        ViewAbsence.NO_UNMEASURABLE: (
            "Le non mesurable d'une nuit seule manque (Night.unmeasurable_s absent) : "
            "la couverture ne se calcule pas (sleep_within)."
        ),
        ViewAbsence.BELOW_USUAL_MINIMUM: (
            "Moins de nuits admises au milieu habituel que le minimum passé à la vue : "
            "le drapeau shifted est inconnu (night_assessment)."
        ),
        ViewAbsence.NO_NIGHT_BEFORE: (
            "Aucune nuit principale finie au plus tard à l'instant (night_before)."
        ),
        ViewAbsence.NO_BLOCK: (
            "Aucun bloc de la sorte d'instant propre au plus tard à l'instant "
            "(training_status_at)."
        ),
        ViewAbsence.NO_ENTRY: (
            "Aucune entrée de Training Readiness au plus tard à l'instant "
            "(readiness_at)."
        ),
        ViewAbsence.NO_RESTING_HR: (
            "Aucune FC de repos de statut autre qu'absent dont le jour a sa fenêtre "
            "finie au plus tard à l'instant (resting_hr_at)."
        ),
        ViewAbsence.DISPERSED_MIDPOINTS: (
            "Les milieux des nuits admises au milieu habituel n'ont pas de moyenne "
            "circulaire (également répartis sur 24 h : résultante nulle à la garde "
            "numérique près) : le milieu habituel et le drapeau shifted sont inconnus "
            "(night_assessment)."
        ),
    }
)


# ---------------------------------------------------------------------------
# Les séries
# ---------------------------------------------------------------------------


def _require_series_times(time_s: tuple[float, ...]) -> None:
    require_immutable_sequence(time_s, "time_s")
    require_min_length(time_s, 1, "time_s")
    require_all_finite(time_s, "time_s")
    require_increasing(time_s, "time_s", strict=True)


def _require_series_values(
    values: tuple[float, ...], name: str, low: float, high: float = _INF
) -> None:
    require_immutable_sequence(values, name)
    require_all_finite(values, name)
    require_all_in_range(values, low, high, name)


def _require_values_or_codes(
    values: tuple[float | None, ...],
    codes: tuple[int | None, ...],
    name: str,
    low: float,
    high: float,
) -> None:
    """Par point, exactement une valeur dans ``[low, high]`` ou un code négatif."""
    require_immutable_sequence(values, name)
    require_immutable_sequence(codes, "code")
    for i, (value, code) in enumerate(zip(values, codes, strict=False)):
        if (value is None) == (code is None):
            raise ContractError(
                f"le point {i} doit porter exactement une valeur ({name}) ou un code."
            )
        if value is not None:
            require_finite(value, f"{name}[{i}]")
            require_in_range(value, low, high, f"{name}[{i}]")
        elif code is not None and code >= 0:
            raise ContractError(f"code[{i}] doit être un code négatif, reçu {code}.")


@dataclass(frozen=True)
class HeartRateSeries:
    """Une série de FC : celle de la journée (``heart_rate.heartRateValues``) ou de la
    nuit (``sleep.sleepHeartRate``).

    Champs
    ------
    - ``time_s`` — secondes — depuis le début de la fenêtre (du jour, ou de la nuit) ;
      l'instant de la source (``[0]``, ou ``startGMT``, en ms).
    - ``heart_rate_bpm`` — battements par minute — FC (``[1]``, ou ``value``),
      ``[20, 250]``.
    - ``source`` — sans unité — provenance : le fichier de la famille.

    Support ``instant`` : l'instant propre d'un point est le sien.

    Invariants
    ----------
    - tableaux en tuples, de même longueur, au moins un point, valeurs finies ;
    - ``time_s`` strictement croissant ; FC dans sa plage.

    Producteur
    ----------
    La lecture des familles (``heart_rate``, ``sleep``).

    Consommateurs
    -------------
    La vue ``series_between`` ; ``DaySeries``, ``NightSeries``.

    Non promis
    ----------
    - aucun pas régulier, rien d'interpolé : un trou reste un trou ;
    - un point hors de la fenêtre de son fichier est gardé : ``time_s`` peut sortir de
      ``[0, durée]`` ;
    - un zéro de la source n'est pas une valeur : il est écarté.
    """

    time_s: tuple[float, ...]
    heart_rate_bpm: tuple[float, ...]
    source: SourceRef

    def __post_init__(self) -> None:
        _require_series_times(self.time_s)
        _require_series_values(
            self.heart_rate_bpm, "heart_rate_bpm", *HEART_RATE_RANGE_BPM
        )
        require_same_length(time_s=self.time_s, heart_rate_bpm=self.heart_rate_bpm)


@dataclass(frozen=True)
class StressSeries:
    """Une série de stress : celle de la journée (``stress.stressValuesArray``) ou de
    la nuit (``sleep.sleepStress``).

    Champs
    ------
    - ``time_s`` — secondes — depuis le début de la fenêtre (du jour, ou de la nuit).
    - ``stress_level`` — sans unité — niveau de stress selon Garmin, ``[0, 100]``,
      absent quand le point porte un code.
    - ``code`` — sans unité — code sentinelle de la source (négatif), absent quand le
      point porte un niveau.
    - ``source`` — sans unité — provenance.

    Support ``instant``.

    Invariants
    ----------
    - tableaux en tuples, de même longueur, au moins un point ; ``time_s`` fini,
      strictement croissant ;
    - **exactement un des deux par point** : un niveau dans ``[0, 100]``, ou un code
      négatif.

    Producteur
    ----------
    La lecture des familles (``stress``, ``sleep``), qui ne garde que les codes connus ;
    un code inconnu fait écarter son point.

    Consommateurs
    -------------
    La vue ``series_between`` ; ``stress_mesure_s`` (AN2-2).

    Non promis
    ----------
    Un code n'est pas une valeur : il dit pourquoi Garmin n'a pas de niveau (activité,
    mouvement…), d'après la table de la lecture des familles. Le niveau zéro est une
    valeur.
    """

    time_s: tuple[float, ...]
    stress_level: tuple[int | None, ...]
    code: tuple[int | None, ...]
    source: SourceRef

    def __post_init__(self) -> None:
        _require_series_times(self.time_s)
        _require_values_or_codes(self.stress_level, self.code, "stress_level", 0, 100)
        require_same_length(
            time_s=self.time_s, stress_level=self.stress_level, code=self.code
        )


@dataclass(frozen=True)
class BodyBatterySeries:
    """Une série de Body Battery : celle de la journée
    (``stress.bodyBatteryValuesArray``, avec statut) ou de la nuit
    (``sleep.sleepBodyBattery``, sans statut).

    Champs
    ------
    - ``time_s`` — secondes — depuis le début de la fenêtre (du jour, ou de la nuit).
    - ``level`` — sans unité — niveau de Body Battery, ``[0, 100]``.
    - ``status`` — sans unité — statut du point (journée : deuxième colonne de la
      source, présent pour chaque point, ``DaySeries``) ; absent pour chaque point de
      la nuit (``NightSeries``), la source n'en porte pas.
    - ``source`` — sans unité — provenance.

    Support ``instant``.

    Invariants
    ----------
    Tableaux en tuples, de même longueur, au moins un point ; ``time_s`` fini,
    strictement croissant ; niveaux dans leur plage.

    Producteur
    ----------
    La lecture des familles (``stress``, ``sleep``).

    Consommateurs
    -------------
    La vue ``body_battery_at`` (la série fusionnée : la nuit dans les fenêtres des
    nuits, la journée ailleurs) ; ``bb_plafond`` (AN2-2).

    Non promis
    ----------
    La version d'algorithme de chaque point (quatrième colonne de la journée) n'est pas
    portée par point : ``AlgorithmVersions`` en garde les valeurs distinctes. Un point
    sans niveau, ou de la journée sans statut, n'est pas une valeur : il est écarté à la
    lecture ; le niveau zéro est dans la plage.
    """

    time_s: tuple[float, ...]
    level: tuple[int, ...]
    status: tuple[BodyBatteryStatus | None, ...]
    source: SourceRef

    def __post_init__(self) -> None:
        _require_series_times(self.time_s)
        _require_series_values(self.level, "level", 0, 100)
        require_immutable_sequence(self.status, "status")
        require_same_length(time_s=self.time_s, level=self.level, status=self.status)


@dataclass(frozen=True)
class RespirationSeries:
    """Une série de respiration : celle de la journée
    (``respiration.respirationValuesArray``) ou de la nuit
    (``sleep.wellnessEpochRespirationDataDTOList``).

    Champs
    ------
    - ``time_s`` — secondes — depuis le début de la fenêtre (du jour, ou de la nuit).
    - ``breaths_per_min`` — respirations par minute — fréquence, ``>= 0``, absente
      quand le point porte un code.
    - ``code`` — sans unité — code sentinelle de la source (négatif), absent quand le
      point porte une valeur.
    - ``source`` — sans unité — provenance.

    Support ``instant``.

    Invariants
    ----------
    - tableaux en tuples, de même longueur, au moins un point ; ``time_s`` fini,
      strictement croissant ;
    - exactement un des deux par point : une valeur finie ``>= 0``, ou un code négatif.

    Producteur
    ----------
    La lecture des familles (``respiration``, ``sleep``), qui ne garde que les codes
    connus.

    Consommateurs
    -------------
    La vue ``series_between``.

    Non promis
    ----------
    Les moyennes par intervalle de la source (``respirationAveragesValuesArray``) ne
    s'ingèrent pas : ce sont des calculs de Garmin sur la série.
    """

    time_s: tuple[float, ...]
    breaths_per_min: tuple[float | None, ...]
    code: tuple[int | None, ...]
    source: SourceRef

    def __post_init__(self) -> None:
        _require_series_times(self.time_s)
        _require_values_or_codes(
            self.breaths_per_min, self.code, "breaths_per_min", 0.0, _INF
        )
        require_same_length(
            time_s=self.time_s, breaths_per_min=self.breaths_per_min, code=self.code
        )


@dataclass(frozen=True)
class SpO2Series:
    """Une série de SpO2 : les moyennes horaires de la journée
    (``spo2.spO2HourlyAverages``) ou les époques de la nuit
    (``sleep.wellnessEpochSPO2DataDTOList``).

    Champs
    ------
    - ``time_s`` — secondes — depuis le début de la fenêtre (du jour, ou de la nuit).
    - ``spo2_percent`` — pourcentage — saturation, ``[0, 100]``.
    - ``source`` — sans unité — provenance.

    Support ``instant``.

    Invariants
    ----------
    Tableaux en tuples, de même longueur, au moins un point ; ``time_s`` fini,
    strictement croissant ; valeurs dans leur plage.

    Producteur
    ----------
    La lecture des familles (``spo2``, ``sleep``).

    Consommateurs
    -------------
    La vue ``series_between``.

    Non promis
    ----------
    Une série de SpO2 peut s'arrêter à une date dans tous les exports : un réglage de
    la montre, pas la conservation ; elle ne compte pas pour « a son détail ».
    """

    time_s: tuple[float, ...]
    spo2_percent: tuple[float, ...]
    source: SourceRef

    def __post_init__(self) -> None:
        _require_series_times(self.time_s)
        _require_series_values(self.spo2_percent, "spo2_percent", 0.0, 100.0)
        require_same_length(time_s=self.time_s, spo2_percent=self.spo2_percent)


@dataclass(frozen=True)
class HrvSeries:
    """La série de HRV de 5 min de la nuit (``sleep.hrvData``).

    Champs
    ------
    - ``time_s`` — secondes — depuis le début de la nuit (``startGMT``, en ms).
    - ``hrv_ms`` — millisecondes — HRV selon Garmin, ``>= 0``.
    - ``source`` — sans unité — provenance.

    Support ``instant``.

    Invariants
    ----------
    Tableaux en tuples, de même longueur, au moins un point ; ``time_s`` fini,
    strictement croissant ; valeurs finies ``>= 0``.

    Producteur
    ----------
    La lecture des familles (``sleep`` ; la série de ``hrv``, ``hrvReadings``, est sa
    copie contrôlée).

    Consommateurs
    -------------
    La vue ``series_between`` ; les variantes des plans (plus tard).

    Non promis
    ----------
    La HRV d'une sieste n'est pas une mesure de nuit.
    """

    time_s: tuple[float, ...]
    hrv_ms: tuple[float, ...]
    source: SourceRef

    def __post_init__(self) -> None:
        _require_series_times(self.time_s)
        _require_series_values(self.hrv_ms, "hrv_ms", 0.0)
        require_same_length(time_s=self.time_s, hrv_ms=self.hrv_ms)


@dataclass(frozen=True)
class RestlessMomentsSeries:
    """La série des moments agités de la nuit (``sleep.sleepRestlessMoments``).

    Champs
    ------
    - ``time_s`` — secondes — depuis le début de la nuit (``startGMT``, en ms).
    - ``count`` — sans unité — nombre de moments agités du point (``value``), ``>= 0``.
    - ``source`` — sans unité — provenance.

    Support ``instant``.

    Invariants
    ----------
    Tableaux en tuples, de même longueur, au moins un point ; ``time_s`` fini,
    strictement croissant ; comptes ``>= 0``.

    Producteur
    ----------
    La lecture des familles (``sleep``).

    Consommateurs
    -------------
    La vue ``series_between``.

    Non promis
    ----------
    La définition d'un moment agité est celle de Garmin, non publiée.
    """

    time_s: tuple[float, ...]
    count: tuple[int, ...]
    source: SourceRef

    def __post_init__(self) -> None:
        _require_series_times(self.time_s)
        _require_series_values(self.count, "count", 0)
        require_same_length(time_s=self.time_s, count=self.count)


@dataclass(frozen=True)
class DaySeries:
    """Les séries de la journée, en secondes depuis le début de la fenêtre du jour.

    Champs
    ------
    - ``heart_rate`` — sans unité — FC (``heart_rate.heartRateValues``).
    - ``stress`` — sans unité — stress (``stress.stressValuesArray``).
    - ``body_battery`` — sans unité — Body Battery et statut
      (``stress.bodyBatteryValuesArray``).
    - ``respiration`` — sans unité — respiration
      (``respiration.respirationValuesArray``).
    - ``spo2`` — sans unité — moyennes horaires de SpO2 (``spo2.spO2HourlyAverages``).

    Chacune absente (``None``) si la source n'en porte aucun point gardé. Support
    ``instant``.

    Invariants
    ----------
    - ``body_battery`` : un statut pour chaque point (la lecture écarte un point du jour
      au statut nul, ``null_value``) ;
    - aucun entre séries : chacune a ses instants et sa provenance.

    Producteur
    ----------
    La lecture des familles ; l'ingestion des jours (emprunts).

    Consommateurs
    -------------
    Les vues ``series_between`` et ``body_battery_at`` ; « a son détail » (une série
    fine non vide, SpO2 exclue).

    Non promis
    ----------
    Garmin efface ces séries après une période récente : leur
    absence ne dit pas qu'il n'y a pas eu de mesure.
    """

    heart_rate: HeartRateSeries | None
    stress: StressSeries | None
    body_battery: BodyBatterySeries | None
    respiration: RespirationSeries | None
    spo2: SpO2Series | None

    def __post_init__(self) -> None:
        if self.body_battery is not None and any(
            status is None for status in self.body_battery.status
        ):
            raise ContractError(
                "body_battery : chaque point de la journée porte un statut."
            )


@dataclass(frozen=True)
class NightSeries:
    """Les séries de la nuit, prises dans le document ``sleep``, en secondes depuis le
    début de la nuit.

    Champs
    ------
    - ``heart_rate`` — sans unité — FC (``sleepHeartRate``).
    - ``stress`` — sans unité — stress (``sleepStress``).
    - ``body_battery`` — sans unité — Body Battery, sans statut (``sleepBodyBattery``).
    - ``hrv`` — sans unité — HRV de 5 min (``hrvData``).
    - ``respiration`` — sans unité — respiration
      (``wellnessEpochRespirationDataDTOList``).
    - ``spo2`` — sans unité — SpO2 (``wellnessEpochSPO2DataDTOList``).
    - ``restless_moments`` — sans unité — moments agités (``sleepRestlessMoments``).

    Chacune absente (``None``) si la source n'en porte aucun point gardé. Support
    ``instant`` : l'instant propre d'un point est l'instant du point, une fois la nuit
    finie (les vues ne rendent les séries d'une nuit qu'une fois la nuit finie).

    Invariants
    ----------
    Les points de Body Battery de la nuit n'ont pas de statut (``status`` absent
    partout) : la source n'en porte pas.

    Producteur
    ----------
    La lecture des familles (``sleep``) ; l'ingestion des jours (emprunts).

    Consommateurs
    -------------
    Les vues ``series_between`` et ``body_battery_at`` ; la part mesurée de la série de
    Body Battery dans la nuit (AN2-2).

    Non promis
    ----------
    Les séries de ``sleep`` peuvent différer par endroits de celles des fichiers du
    jour : aucune n'est recollée à l'autre. La série de mouvement (``sleepMovement``)
    ne s'ingère pas.
    """

    heart_rate: HeartRateSeries | None
    stress: StressSeries | None
    body_battery: BodyBatterySeries | None
    hrv: HrvSeries | None
    respiration: RespirationSeries | None
    spo2: SpO2Series | None
    restless_moments: RestlessMomentsSeries | None

    def __post_init__(self) -> None:
        if self.body_battery is not None and any(
            status is not None for status in self.body_battery.status
        ):
            raise ContractError(
                "body_battery : les points de la nuit n'ont pas de statut."
            )


# ---------------------------------------------------------------------------
# La nuit, les siestes, les valeurs du jour
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SleepSegment:
    """Un segment de phase de la nuit (``sleep.sleepLevels[*]``).

    Champs
    ------
    - ``start_s`` — secondes — début, depuis le début de la nuit (``startGMT``).
    - ``end_s`` — secondes — fin, depuis le début de la nuit (``endGMT``).
    - ``stage`` — sans unité — la phase (code ``activityLevel`` traduit).

    Invariants
    ----------
    Bornes finies ; ``end_s > start_s``.

    Producteur
    ----------
    La lecture des familles (``sleep``).

    Consommateurs
    -------------
    ``Night.segments`` ; la vue ``sleep_within``.

    Non promis
    ----------
    Un segment peut sortir de la fenêtre de la nuit (bornes hors de ``[0, durée]``) :
    la source le place, l'ingestion ne le coupe pas.
    """

    start_s: float
    end_s: float
    stage: SleepStage

    def __post_init__(self) -> None:
        require_finite(self.start_s, "start_s")
        require_finite(self.end_s, "end_s")
        if not self.end_s > self.start_s:
            raise ContractError(
                f"end_s doit suivre start_s : reçu {self.start_s}, {self.end_s}."
            )


_NIGHT_DURATIONS = ("deep_s", "light_s", "rem_s", "awake_s", "unmeasurable_s")


@dataclass(frozen=True)
class Night:
    """La nuit principale d'un jour, rattachée au jour du réveil (``sleep``).

    Champs
    ------
    - ``start`` — instant — début (``dailySleepDTO.sleepStartTimestampGMT``, ms), dans
      le décalage de la nuit : ``sleepStartTimestampLocal`` −
      ``sleepStartTimestampGMT`` (ms d'heure murale).
    - ``end`` — instant — fin (``…EndTimestampGMT``), dans son décalage
      (``…EndTimestampLocal`` − ``…EndTimestampGMT``).
    - ``deep_s`` — secondes — profond (``dailySleepDTO.deepSleepSeconds``), ``>= 0``.
    - ``light_s`` — secondes — léger (``lightSleepSeconds``), ``>= 0``.
    - ``rem_s`` — secondes — paradoxal (``remSleepSeconds``), ``>= 0`` ; absent si
      l'appareil ne le détecte pas (``deviceRemCapable`` faux) : absent, pas nul.
    - ``awake_s`` — secondes — éveil (``awakeSleepSeconds``), ``>= 0``.
    - ``unmeasurable_s`` — secondes — non mesurable (``unmeasurableSleepSeconds``),
      ``>= 0``.
    - ``confirmation`` — sans unité — type de confirmation de la fenêtre, code de la
      source (``sleepWindowConfirmationType``), non vide.
    - ``window_confirmed`` — sans unité — la fenêtre est confirmée
      (``sleepWindowConfirmed``).
    - ``from_device`` — sans unité — la nuit vient de la montre (``sleepFromDevice``).
    - ``rem_capable`` — sans unité — l'appareil détecte le paradoxal
      (``deviceRemCapable``).
    - ``segments`` — sans unité — les segments de phase (``sleepLevels``), triés, sans
      recouvrement ; vide si la source n'en porte pas.
    - ``sleep_score`` — sans unité — score de sommeil selon Garmin
      (``sleepScores.overall.value``), ``[0, 100]``.
    - ``avg_stress`` — sans unité — stress moyen du sommeil (``avgSleepStress``),
      ``[0, 100]``.
    - ``avg_heart_rate_bpm`` — battements par minute — FC moyenne du sommeil
      (``avgHeartRate``), ``[20, 250]``.
    - ``body_battery_change`` — sans unité — changement de Body Battery du sommeil
      (racine ``bodyBatteryChange``), ``[-100, 100]``.
    - ``restless_moments`` — sans unité — nombre de moments agités (racine
      ``restlessMomentsCount``), ``>= 0``.
    - ``skin_temperature_deviation_c`` — °C — écart de température cutanée de la nuit
      (racine ``avgSkinTempDeviationC``), fini.
    - ``series`` — sans unité — les séries de la nuit.
    - ``source`` — sans unité — provenance : le fichier ``sleep``.

    Toutes les grandeurs de la nuit ont le support ``night`` (instant propre : ``end``),
    ses séries le support ``instant`` (l'instant du point, une fois la nuit finie). Les
    résumés sont « selon Garmin », chacun absent s'il n'est pas porté.

    Invariants
    ----------
    - ``start`` et ``end`` *aware*, décalages dans ``[-43200, 50400]`` s, en secondes
      entières, ramenés à un fuseau à décalage fixe ; ``end > start`` ;
    - durées finies et ``>= 0`` ; ``rem_s`` absent si ``rem_capable`` est faux ;
    - ``confirmation`` non vide s'il est présent ;
    - ``segments`` en tuple, triés : chacun commence au plus tôt à la fin du précédent ;
    - résumés dans leurs plages.

    Producteur
    ----------
    La lecture des familles (``sleep``) ; l'ingestion des jours (emprunts).

    Consommateurs
    -------------
    ``DayRecord.night`` ; les vues ``sleep_within``, ``night_before``,
    ``nights_after``, ``night_assessment``, ``readiness_on_waking``,
    ``body_battery_at`` ; la table ``jours`` (AN2-2).

    Non promis
    ----------
    - l'égalité ``end − start`` = phases + éveil + non mesurable n'est **pas** un
      invariant : la source peut la violer ; elle se vérifie à l'ingestion, à la
      tolérance déclarée, et ses écarts se comptent ;
    - les deux décalages peuvent différer (une nuit au changement d'heure) : aucune
      durée ne se tire des heures locales (``0006``) ;
    - la fenêtre peut avoir été corrigée à la main (``manually_confirmed``), sans être
      ni déclarée ni provisoire : la nuit est saisie sans montre si et seulement si
      ``from_device`` est faux, sa fenêtre provisoire si et seulement si
      ``window_confirmed`` est faux ; ``confirmation``
      reste un code de la source, compté au rapport s'il est inconnu ;
    - les champs de besoin de sommeil, d'alignement, de conseil, et la série de
      mouvement ne s'ingèrent pas.
    """

    start: datetime
    end: datetime
    deep_s: float | None
    light_s: float | None
    rem_s: float | None
    awake_s: float | None
    unmeasurable_s: float | None
    confirmation: str | None
    window_confirmed: bool | None
    from_device: bool | None
    rem_capable: bool | None
    segments: tuple[SleepSegment, ...]
    sleep_score: int | None
    avg_stress: float | None
    avg_heart_rate_bpm: float | None
    body_battery_change: int | None
    restless_moments: int | None
    skin_temperature_deviation_c: float | None
    series: NightSeries
    source: SourceRef

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", _require_instant(self.start, "start"))
        object.__setattr__(self, "end", _require_instant(self.end, "end"))
        if not self.end > self.start:
            raise ContractError("end doit suivre start : la nuit a une durée.")
        for name in _NIGHT_DURATIONS:
            _require_optional_in_range(getattr(self, name), name, 0.0)
        if self.rem_capable is False and self.rem_s is not None:
            raise ContractError(
                "rem_s doit être absent quand l'appareil ne détecte pas le paradoxal."
            )
        if self.confirmation is not None:
            require_non_empty(self.confirmation, "confirmation")
        require_immutable_sequence(self.segments, "segments")
        for i in range(1, len(self.segments)):
            if self.segments[i].start_s < self.segments[i - 1].end_s:
                raise ContractError(
                    f"segments doit être trié sans recouvrement : rangs {i - 1} et {i}."
                )
        _require_optional_in_range(self.sleep_score, "sleep_score", 0, 100)
        _require_optional_in_range(self.avg_stress, "avg_stress", 0.0, 100.0)
        _require_optional_in_range(
            self.avg_heart_rate_bpm, "avg_heart_rate_bpm", *HEART_RATE_RANGE_BPM
        )
        _require_optional_in_range(
            self.body_battery_change, "body_battery_change", -100, 100
        )
        if self.restless_moments is not None:
            _require_at_least(self.restless_moments, 0, "restless_moments")
        if self.skin_temperature_deviation_c is not None:
            require_finite(
                self.skin_temperature_deviation_c, "skin_temperature_deviation_c"
            )

    @property
    def measured_sleep_s(self) -> float | None:
        """Le sommeil mesuré : profond + léger, plus le paradoxal s'il est détecté ;
        absent si le profond ou le léger manque, ou si l'appareil détecte le
        paradoxal et que sa durée manque."""
        if self.deep_s is None or self.light_s is None:
            return None
        if self.rem_s is not None:
            return self.deep_s + self.light_s + self.rem_s
        if self.rem_capable is False:
            return self.deep_s + self.light_s
        return None


@dataclass(frozen=True)
class Nap:
    """Une sieste du jour (``sleep.dailySleepDTO.dailyNapDTOS[*]``).

    Champs
    ------
    - ``start`` — instant — début (``napStartTimestampGMT``, texte GMT), dans le
      décalage de la sieste (``napStartTimeOffset``, un nombre entier de minutes ; un
      flottant de valeur entière admis).
    - ``end`` — instant — fin (``napEndTimestampGMT``), dans son décalage
      (``napEndTimeOffset``, de même).
    - ``sleep_s`` — secondes — durée de sommeil selon Garmin (``napTimeSec``), ``>= 0``.
    - ``nap_source_code`` — sans unité — code de la source (``napSource``), tel quel.
    - ``source`` — sans unité — provenance : le fichier ``sleep``.

    Support ``instant`` : l'instant propre d'une sieste est sa fin.

    Invariants
    ----------
    ``start`` et ``end`` *aware*, décalages dans leur plage, en secondes entières,
    ramenés à un fuseau à décalage fixe ; ``end > start`` ; ``sleep_s`` fini ``>= 0``.

    Producteur
    ----------
    La lecture des familles (``sleep``).

    Consommateurs
    -------------
    ``DayRecord.naps`` ; les vues ``sleep_within`` et ``readiness_on_waking`` (« avant
    la sieste suivante »).

    Non promis
    ----------
    - ``sleep_s`` peut différer de ``end − start`` : aucun invariant entre eux ;
    - une sieste peut recouper la nuit : elle est gardée, et comptée au rapport ;
    - la HRV et la FC d'une sieste ne sont pas des mesures de nuit.
    """

    start: datetime
    end: datetime
    sleep_s: float
    nap_source_code: int | None
    source: SourceRef

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", _require_instant(self.start, "start"))
        object.__setattr__(self, "end", _require_instant(self.end, "end"))
        if not self.end > self.start:
            raise ContractError("end doit suivre start : la sieste a une durée.")
        require_finite(self.sleep_s, "sleep_s")
        require_in_range(self.sleep_s, 0.0, _INF, "sleep_s")


@dataclass(frozen=True)
class RestingHr:
    """La FC de repos d'un jour selon Garmin (``resting_hr``).

    Champs
    ------
    - ``resting_hr_bpm`` — battements par minute — la valeur
      (``allMetrics.metricsMap.WELLNESS_RESTING_HEART_RATE[0].value``), ``[20, 250]`` ;
      support ``day``.
    - ``source`` — sans unité — provenance : le fichier ``resting_hr``.

    Invariants
    ----------
    Valeur finie, dans sa plage.

    Producteur
    ----------
    La lecture des familles (``resting_hr`` ; celles de ``heart_rate``,
    ``daily_summary`` et ``sleep`` sont des copies contrôlées).

    Consommateurs
    -------------
    Les vues ``resting_hr_on`` et ``resting_hr_at`` ; la table ``jours`` (AN2-2).

    Non promis
    ----------
    Selon Garmin : la plus basse moyenne sur 30 min de la journée calendaire (à
    vérifier selon les firmwares) ; sans nuit portée, elle vient de la journée ; avec
    une nuit, elle peut venir du début de la nuit suivante. Elle peut encore
    baisser tant que le jour est tronqué.
    """

    resting_hr_bpm: float
    source: SourceRef

    def __post_init__(self) -> None:
        require_finite(self.resting_hr_bpm, "resting_hr_bpm")
        require_in_range(self.resting_hr_bpm, *HEART_RATE_RANGE_BPM, "resting_hr_bpm")


_HRV_VALUES = (
    "last_night_avg_ms",
    "last_night_5min_high_ms",
    "weekly_avg_ms",
    "baseline_balanced_low_ms",
    "baseline_balanced_upper_ms",
    "baseline_low_upper_ms",
    "baseline_marker_value",
)


@dataclass(frozen=True)
class HrvSummary:
    """La HRV selon Garmin : de la nuit, de la semaine, son statut et ses bornes
    (``hrv.hrvSummary``).

    Champs
    ------
    - ``last_night_avg_ms`` — millisecondes — moyenne de la nuit (``lastNightAvg``) ;
      support ``night``.
    - ``last_night_5min_high_ms`` — millisecondes — plus haute valeur de 5 min de la
      nuit (``lastNight5MinHigh``) ; support ``night``.
    - ``weekly_avg_ms`` — millisecondes — moyenne de la semaine (``weeklyAvg``) ;
      support ``waking``.
    - ``status`` — sans unité — statut HRV, code de la source (``status``) ; support
      ``waking``.
    - ``baseline_balanced_low_ms``, ``baseline_balanced_upper_ms``,
      ``baseline_low_upper_ms`` — millisecondes — bornes de la normale de Garmin
      (``baseline.balancedLow``, ``.balancedUpper``, ``.lowUpper``) ; support
      ``waking``.
    - ``baseline_marker_value`` — sans unité — position du repère de Garmin
      (``baseline.markerValue``) ; support ``waking``.
    - ``source`` — sans unité — provenance : le fichier ``hrv``.

    Chaque valeur absente si elle n'est pas portée.

    Invariants
    ----------
    Valeurs finies et ``>= 0`` ; ``status`` non vide s'il est présent.

    Producteur
    ----------
    La lecture des familles (``hrv`` ; la HRV de ``sleep`` est une copie contrôlée).

    Consommateurs
    -------------
    La table ``jours`` (AN2-2) ; la figure de la normale de Garmin (AN2-3).

    Non promis
    ----------
    Le statut et les bornes sont des composites de Garmin, sans normale de la piste.
    Garmin retire la HRV de la nuit et son statut d'un jour qui perd son détail.
    """

    last_night_avg_ms: float | None
    last_night_5min_high_ms: float | None
    weekly_avg_ms: float | None
    status: str | None
    baseline_balanced_low_ms: float | None
    baseline_balanced_upper_ms: float | None
    baseline_low_upper_ms: float | None
    baseline_marker_value: float | None
    source: SourceRef

    def __post_init__(self) -> None:
        for name in _HRV_VALUES:
            _require_optional_in_range(getattr(self, name), name, 0.0)
        if self.status is not None:
            require_non_empty(self.status, "status")


_RESPIRATION_VALUES = (
    "avg_sleep_breaths_per_min",
    "avg_waking_breaths_per_min",
    "highest_breaths_per_min",
    "lowest_breaths_per_min",
)


@dataclass(frozen=True)
class RespirationSummary:
    """La respiration selon Garmin : de la nuit, de l'éveil, ses extrêmes
    (``respiration``).

    Champs
    ------
    - ``avg_sleep_breaths_per_min`` — respirations par minute — moyenne du sommeil
      (``avgSleepRespirationValue``) ; support ``night``.
    - ``avg_waking_breaths_per_min`` — respirations par minute — moyenne des heures
      d'éveil (``avgWakingRespirationValue``) ; support ``day``.
    - ``highest_breaths_per_min``, ``lowest_breaths_per_min`` — respirations par
      minute — extrêmes du jour (``highestRespirationValue``,
      ``lowestRespirationValue``) ; support ``day``.
    - ``source`` — sans unité — provenance : le fichier ``respiration``.

    Invariants
    ----------
    Valeurs finies et ``>= 0``.

    Producteur
    ----------
    La lecture des familles (``respiration`` ; ``sleep`` et ``daily_summary`` portent
    des copies contrôlées).

    Consommateurs
    -------------
    La table ``jours`` (AN2-2) : la respiration de la nuit et sa normale.

    Non promis
    ----------
    Les champs de la nuit suivante (``avgTomorrowSleepRespirationValue``…) ne
    s'ingèrent pas : ils portent une mesure de J + 1. Garmin
    recalcule les extrêmes d'un jour qui perd son détail.
    """

    avg_sleep_breaths_per_min: float | None
    avg_waking_breaths_per_min: float | None
    highest_breaths_per_min: float | None
    lowest_breaths_per_min: float | None
    source: SourceRef

    def __post_init__(self) -> None:
        for name in _RESPIRATION_VALUES:
            _require_optional_in_range(getattr(self, name), name, 0.0)


_SPO2_VALUES = ("avg_sleep_spo2_percent", "average_spo2_percent", "lowest_spo2_percent")


@dataclass(frozen=True)
class SpO2Summary:
    """La SpO2 selon Garmin : de la nuit, du jour, la plus basse (``spo2``).

    Champs
    ------
    - ``avg_sleep_spo2_percent`` — pourcentage — moyenne du sommeil (``avgSleepSpO2``) ;
      support ``night``.
    - ``average_spo2_percent`` — pourcentage — moyenne du jour (``averageSpO2``) ;
      support ``day``.
    - ``lowest_spo2_percent`` — pourcentage — plus basse du jour (``lowestSpO2``) ;
      support ``day``.
    - ``source`` — sans unité — provenance : le fichier ``spo2``.

    Invariants
    ----------
    Valeurs finies, dans ``[0, 100]``.

    Producteur
    ----------
    La lecture des familles (``spo2`` ; ``sleep`` et ``daily_summary`` portent des
    copies contrôlées).

    Consommateurs
    -------------
    La table ``jours`` (AN2-2).

    Non promis
    ----------
    ``avgTomorrowSleepSpO2`` ne s'ingère pas. La SpO2 reste hors de l'état de la nuit.
    """

    avg_sleep_spo2_percent: float | None
    average_spo2_percent: float | None
    lowest_spo2_percent: float | None
    source: SourceRef

    def __post_init__(self) -> None:
        for name in _SPO2_VALUES:
            _require_optional_in_range(getattr(self, name), name, 0.0, 100.0)


_STRESS_DURATIONS = (
    "rest_duration_s",
    "low_duration_s",
    "medium_duration_s",
    "high_duration_s",
    "activity_duration_s",
    "uncategorized_duration_s",
    "total_duration_s",
    "stress_duration_s",
)


@dataclass(frozen=True)
class StressSummary:
    """Le stress du jour selon Garmin (``daily_summary``).

    Champs
    ------
    - ``average_level`` — sans unité — stress moyen (``averageStressLevel``),
      ``[0, 100]`` ; absent quand la source porte un code à sa place.
    - ``average_level_code`` — sans unité — code sentinelle de la source à la place du
      stress moyen (négatif : ``-1``, ``-2`` connus).
    - ``max_level`` — sans unité — stress maximal (``maxStressLevel``), ``[0, 100]``.
    - ``rest_duration_s`` — secondes — au repos (``restStressDuration``).
    - ``low_duration_s`` — secondes — stress bas (``lowStressDuration``).
    - ``medium_duration_s`` — secondes — stress moyen (``mediumStressDuration``).
    - ``high_duration_s`` — secondes — stress haut (``highStressDuration``).
    - ``activity_duration_s`` — secondes — « activité » (``activityStressDuration``).
    - ``uncategorized_duration_s`` — secondes — « non classée »
      (``uncategorizedStressDuration``).
    - ``total_duration_s`` — secondes — total (``totalStressDuration``).
    - ``stress_duration_s`` — secondes — en stress (``stressDuration``).
    - ``source`` — sans unité — provenance : le fichier ``daily_summary``.

    Toutes au support ``day`` ; durées ``>= 0`` ; chacune absente si elle n'est pas
    portée.

    Invariants
    ----------
    Niveaux finis dans ``[0, 100]`` ; au plus un des deux, ``average_level`` ou
    ``average_level_code`` ; un code est négatif ; durées finies ``>= 0``.

    Producteur
    ----------
    La lecture des familles (``daily_summary`` ; ``stress`` porte une copie contrôlée
    de la moyenne et du maximum, ``avgStressLevel``).

    Consommateurs
    -------------
    La table ``jours`` (AN2-2) : le stress du jour et ``stress_mesure_s`` (repos, bas,
    moyen, haut).

    Non promis
    ----------
    Aucun invariant entre durées (leur somme et le total sont ceux de Garmin). Un code
    n'est pas un niveau : il dit pourquoi Garmin n'a pas de moyenne.
    """

    average_level: int | None
    average_level_code: int | None
    max_level: int | None
    rest_duration_s: float | None
    low_duration_s: float | None
    medium_duration_s: float | None
    high_duration_s: float | None
    activity_duration_s: float | None
    uncategorized_duration_s: float | None
    total_duration_s: float | None
    stress_duration_s: float | None
    source: SourceRef

    def __post_init__(self) -> None:
        for name in ("average_level", "max_level"):
            _require_optional_in_range(getattr(self, name), name, 0, 100)
        if self.average_level is not None and self.average_level_code is not None:
            raise ContractError(
                "average_level et average_level_code : au plus un des deux."
            )
        if self.average_level_code is not None and self.average_level_code >= 0:
            raise ContractError(
                "average_level_code doit être un code négatif, reçu "
                f"{self.average_level_code}."
            )
        for name in _STRESS_DURATIONS:
            _require_optional_in_range(getattr(self, name), name, 0.0)


@dataclass(frozen=True)
class BodyBatterySummary:
    """Le Body Battery du jour selon Garmin (``daily_summary``).

    Champs
    ------
    - ``charged`` — sans unité — chargé sur le jour (``bodyBatteryChargedValue``),
      ``>= 0`` ; support ``day``.
    - ``drained`` — sans unité — déchargé (``bodyBatteryDrainedValue``), ``>= 0`` ;
      support ``day``.
    - ``highest`` — sans unité — plus haut (``bodyBatteryHighestValue``), ``[0, 100]`` ;
      support ``day``.
    - ``lowest`` — sans unité — plus bas (``bodyBatteryLowestValue``), ``[0, 100]`` ;
      support ``day``.
    - ``at_wake`` — sans unité — au réveil (``bodyBatteryAtWakeTime``), ``[0, 100]`` ;
      support ``waking``.
    - ``during_sleep`` — sans unité — pendant le sommeil (``bodyBatteryDuringSleep``),
      ``[-100, 100]`` ; support ``night`` ; une grandeur distincte du changement de
      Body Battery du sommeil (``Night.body_battery_change``) : les deux diffèrent
      sur une part des nuits, aucune n'est la copie de l'autre.
    - ``source`` — sans unité — provenance : le fichier ``daily_summary``.

    Invariants
    ----------
    Valeurs dans leurs plages.

    Producteur
    ----------
    La lecture des familles (``daily_summary`` ; ``body_battery`` porte des copies
    contrôlées).

    Consommateurs
    -------------
    La table ``jours`` (AN2-2) ; la page « récupération » (AN2-3).

    Non promis
    ----------
    Le Body Battery est un composite de Garmin : pas une mesure de la récupération
    (Q9 le juge), sans normale de la piste.
    """

    charged: int | None
    drained: int | None
    highest: int | None
    lowest: int | None
    at_wake: int | None
    during_sleep: int | None
    source: SourceRef

    def __post_init__(self) -> None:
        for name in ("charged", "drained"):
            _require_optional_in_range(getattr(self, name), name, 0)
        for name in ("highest", "lowest", "at_wake"):
            _require_optional_in_range(getattr(self, name), name, 0, 100)
        _require_optional_in_range(self.during_sleep, "during_sleep", -100, 100)


@dataclass(frozen=True)
class ActivityTotals:
    """Les totaux d'activité du jour selon Garmin (``daily_summary``).

    Champs
    ------
    - ``steps`` — sans unité — pas (``totalSteps``), ``>= 0``.
    - ``moderate_intensity_s`` — secondes — intensité modérée
      (``moderateIntensityMinutes`` × 60), ``>= 0``.
    - ``vigorous_intensity_s`` — secondes — intensité vigoureuse
      (``vigorousIntensityMinutes`` × 60), ``>= 0``.
    - ``floors_ascended_m`` — mètres — dénivelé des étages montés
      (``floorsAscendedInMeters``), ``>= 0``.
    - ``floors_descended_m`` — mètres — dénivelé des étages descendus
      (``floorsDescendedInMeters``), ``>= 0``.
    - ``average_altitude_m`` — mètres — altitude moyenne du jour
      (``averageMonitoringEnvironmentAltitude``), ``[-500, 9000]``.
    - ``source`` — sans unité — provenance : le fichier ``daily_summary``.

    Toutes au support ``day`` ; chacune absente si elle n'est pas portée.

    Invariants
    ----------
    Valeurs finies, dans leurs plages.

    Producteur
    ----------
    La lecture des familles (``daily_summary``).

    Consommateurs
    -------------
    La table ``jours`` (AN2-2) ; ``sejour_altitude`` se lit au journal, pas ici.

    Non promis
    ----------
    Les minutes d'intensité sont celles de Garmin, converties en secondes à la lecture ;
    les calories ne s'ingèrent pas. L'altitude moyenne est celle de la montre, sans
    recalage.
    """

    steps: int | None
    moderate_intensity_s: float | None
    vigorous_intensity_s: float | None
    floors_ascended_m: float | None
    floors_descended_m: float | None
    average_altitude_m: float | None
    source: SourceRef

    def __post_init__(self) -> None:
        for name in (
            "steps",
            "moderate_intensity_s",
            "vigorous_intensity_s",
            "floors_ascended_m",
            "floors_descended_m",
        ):
            _require_optional_in_range(getattr(self, name), name, 0.0)
        _require_optional_in_range(
            self.average_altitude_m, "average_altitude_m", *ELEVATION_RANGE_M
        )


_SCALAR_VERSIONS = (
    "sleep_version",
    "sleep_respiration_version",
    "respiration_version",
    "summary_respiration_version",
    "summary_body_battery_version",
)


@dataclass(frozen=True)
class AlgorithmVersions:
    """Les versions d'algorithme que portent les familles du jour.

    Champs
    ------
    - ``sleep_version`` — sans unité — ``sleep.dailySleepDTO.sleepVersion``.
    - ``sleep_respiration_version`` — sans unité — ``sleep.respirationVersion``.
    - ``respiration_version`` — sans unité — ``respiration.respirationVersion``.
    - ``summary_respiration_version`` — sans unité —
      ``daily_summary.respirationAlgorithmVersion``.
    - ``summary_body_battery_version`` — sans unité —
      ``daily_summary.bodyBatteryVersion``.
    - ``body_battery_series_versions`` — sans unité — les versions distinctes, triées,
      de la quatrième colonne des points gardés de ``stress.bodyBatteryValuesArray``,
      lues dans la lecture d'où vient la série du jour : le prêteur quand elle est
      empruntée seule ; sinon la lecture ``stress`` retenue (la référence, ou le
      prêteur de la famille entière).

    Chacune absente (vide pour la dernière) si la lecture d'où elle vient n'en porte
    pas. Les versions de la série de Body Battery sont celles des points que garde
    cette lecture, même quand l'assemblage du jour les jette (un jour sans fenêtre,
    ``no_window``).

    Invariants
    ----------
    Versions ``>= 0`` ; ``body_battery_series_versions`` en tuple, trié, sans doublon.

    Producteur
    ----------
    La lecture des familles ; l'ingestion des jours (chaque version vient de la famille
    retenue, de l'export de référence ou d'un emprunt).

    Consommateurs
    -------------
    La rupture d'une mesure dans la table ``jours`` (AN2-2) : un changement de version
    d'algorithme de sa famille.

    Non promis
    ----------
    Pas de provenance propre : chaque version vient d'une famille dont le sous-objet
    porte la provenance ; sur un jour sans fenêtre, les versions de la série de Body
    Battery jetée (``no_window``) restent sans elle. Le firmware n'est pas connu par
    les familles journalières.
    """

    sleep_version: int | None
    sleep_respiration_version: int | None
    respiration_version: int | None
    summary_respiration_version: int | None
    summary_body_battery_version: int | None
    body_battery_series_versions: tuple[int, ...]

    def __post_init__(self) -> None:
        for name in _SCALAR_VERSIONS:
            value = getattr(self, name)
            if value is not None:
                _require_at_least(value, 0, name)
        versions = self.body_battery_series_versions
        require_immutable_sequence(versions, "body_battery_series_versions")
        for value in versions:
            _require_at_least(value, 0, "body_battery_series_versions")
        _require_strictly_sorted(
            [(value,) for value in versions], "body_battery_series_versions"
        )


@dataclass(frozen=True)
class ReadinessEntry:
    """Une entrée de Training Readiness (``training_readiness[*]``).

    Champs
    ------
    - ``instant`` — instant — l'horodatage (``timestamp``, texte GMT), dans le décalage
      de son heure locale (``timestampLocal`` − ``timestamp``).
    - ``input_context`` — sans unité — contexte de l'entrée, code de la source
      (``inputContext``), non vide.
    - ``score`` — sans unité — score selon Garmin (``score``), ``[0, 100]``.
    - ``level`` — sans unité — niveau, code de la source (``level``), non vide.
    - ``valid_sleep`` — sans unité — la source dit le sommeil valide (``validSleep``).
    - ``sleep_score`` — sans unité — copie du score de sommeil (``sleepScore``),
      ``[0, 100]``.
    - ``hrv_weekly_average_ms`` — millisecondes — copie de la HRV de la semaine
      (``hrvWeeklyAverage``), ``>= 0``.
    - ``acute_load`` — sans unité — copie de la charge aiguë (``acuteLoad``), ``>= 0``.
    - ``source`` — sans unité — provenance : le fichier ``training_readiness``.

    Support ``instant`` : l'instant propre d'une entrée est ``instant``.

    Invariants
    ----------
    ``instant`` *aware*, décalage dans sa plage, en secondes entières, ramené à un
    fuseau à décalage fixe ; codes non vides s'ils sont présents ; valeurs dans leurs
    plages.

    Producteur
    ----------
    La lecture des familles (``training_readiness``), qui ne garde que les entrées de
    l'appareil principal (les autres se comptent).

    Consommateurs
    -------------
    ``DayRecord.readiness`` ; les vues ``readiness_at`` et ``readiness_on_waking``.

    Non promis
    ----------
    Les copies sont celles du moment de l'entrée : elles peuvent différer du document
    final (« copie antérieure ») et restent hors du contrôle des copies. Une
    entrée « réveil » peut précéder la fin de la nuit retenue.
    """

    instant: datetime
    input_context: str | None
    score: int | None
    level: str | None
    valid_sleep: bool | None
    sleep_score: int | None
    hrv_weekly_average_ms: float | None
    acute_load: float | None
    source: SourceRef

    def __post_init__(self) -> None:
        object.__setattr__(self, "instant", _require_instant(self.instant, "instant"))
        for name in ("input_context", "level"):
            text = getattr(self, name)
            if text is not None:
                require_non_empty(text, name)
        _require_optional_in_range(self.score, "score", 0, 100)
        _require_optional_in_range(self.sleep_score, "sleep_score", 0, 100)
        _require_optional_in_range(
            self.hrv_weekly_average_ms, "hrv_weekly_average_ms", 0.0
        )
        _require_optional_in_range(self.acute_load, "acute_load", 0.0)


# ---------------------------------------------------------------------------
# Le document d'un jour
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DayRecord:
    """Le document d'un jour de Garmin (``interim/days/<AAAA-MM-JJ>.json``) : un par
    jour qu'au moins un export porte (au moins un fichier d'une famille à cette date,
    même vide).

    Champs
    ------
    - ``day`` — date — le jour de Garmin, celui du nom des fichiers.
    - ``window_start`` — instant — début de la fenêtre du jour (minuit local), dans son
      décalage ; absent si et seulement si le jour est ``empty``.
    - ``data_end`` — instant — ``fin_donnees`` : la fin GMT de la fenêtre de la source,
      ramenée au décalage de ``window_start`` ; présente avec lui.
    - ``window_family`` — sans unité — la famille d'où vient la fenêtre
      (``daily_summary``, sinon ``heart_rate``, ``stress``, ``respiration``, ``spo2``,
      dans cet ordre) ; présente avec la fenêtre.
    - ``wellness_data`` — sans unité — l'indicateur de présence
      (``daily_summary.includesWellnessData``), s'il est porté.
    - ``state`` — sans unité — l'état du jour, décidé dans l'ordre de ``DayState``.
    - ``reference_export`` — sans unité — le nom de l'export de référence du jour.
    - ``night`` — sans unité — la nuit principale, rattachée au jour du réveil ;
      support ``night``.
    - ``naps`` — sans unité — les siestes, triées par début ; support ``instant``.
    - ``resting_hr`` — sans unité — la FC de repos (``resting_hr``) ; support ``day``.
    - ``hrv`` — sans unité — la HRV selon Garmin (``hrv``) ; supports dans
      ``HrvSummary``.
    - ``respiration`` — sans unité — la respiration (``respiration``) ; supports dans
      ``RespirationSummary``.
    - ``spo2`` — sans unité — la SpO2 (``spo2``) ; supports dans ``SpO2Summary``.
    - ``stress`` — sans unité — le stress du jour (``daily_summary``) ; support
      ``day``.
    - ``body_battery`` — sans unité — le Body Battery du jour (``daily_summary``) ;
      supports dans ``BodyBatterySummary``.
    - ``activity_totals`` — sans unité — pas, intensité, étages, altitude moyenne
      (``daily_summary``) ; support ``day``.
    - ``series`` — sans unité — les séries de la journée ; support ``instant``.
    - ``readiness`` — sans unité — les entrées de Training Readiness de l'appareil
      principal, triées par instant ; support ``instant``.
    - ``versions`` — sans unité — les versions d'algorithme portées.
    - ``device_ranks`` — sans unité — les rangs des appareils que nomment les familles
      du jour, triés, sans doublon ; rang = ordre de première apparition sur tous les
      jours (dates croissantes), depuis 1, jamais l'identifiant.

    Les supports de chaque grandeur sont aussi dans ``QUANTITY_SUPPORTS``.

    Invariants
    ----------
    - ``window_start``, ``data_end`` et ``window_family`` présents ensemble, si et
      seulement si ``state`` n'est pas ``empty`` ;
    - ``window_start`` *aware*, décalage dans sa plage, en secondes entières, ramené à
      un fuseau à décalage fixe ; sa date locale est ``day`` ; ``data_end`` ramené à
      son décalage, au plus tôt ``window_start`` ;
    - ``window_family`` l'une des familles qui portent une fenêtre du jour
      (``DAY_WINDOW_FAMILIES``) ;
    - ``truncated`` : ``data_end`` précède ``window_start`` + 24 h ; ``complete`` :
      ``data_end`` au plus tôt ``window_start`` + 24 h ;
    - sans fenêtre, aucune série du jour (leurs instants partent de la fenêtre) ;
    - ``reference_export`` : lettres et chiffres ASCII, ``_``, ``.``, ``-`` ;
    - ``naps`` triées par début, ``readiness`` par instant (au sens large) ;
    - ``device_ranks`` en tuple, ``>= 1``, strictement croissant.

    Producteur
    ----------
    L'ingestion des jours (``mountain_perf.ingest.days``), sur la lecture des familles
    de tous les exports ; écrit par ``write_days``.

    Consommateurs
    -------------
    ``read_days`` ; les vues des jours ; la table ``jours`` (AN2-2).

    Non promis
    ----------
    - ``interim/days/`` ne porte aucun seuil : états de la nuit, statut de la FC de
      repos, couverture se calculent à la lecture ;
    - les valeurs restent telles que la source les donne quel que soit l'état ; les
      grandeurs ``day`` d'un jour ``truncated`` peuvent encore changer ;
    - ``wellness_data`` peut venir d'une famille empruntée : ni lui ni les séries ne
      se vérifient ici contre ``state``, décidé sur l'export de référence ;
    - un jour ``empty`` peut porter une nuit (un export qui n'a que ``sleep``) ;
    - les copies d'une grandeur dans d'autres familles ne sont pas portées : leurs
      désaccords sont comptés au rapport ;
    - aucun identifiant d'appareil ni d'utilisateur ; les rangs ne se comparent pas
      à l'appareil d'un FIT.
    """

    day: date
    window_start: datetime | None
    data_end: datetime | None
    window_family: DayFamily | None
    wellness_data: bool | None
    state: DayState
    reference_export: str
    night: Night | None
    naps: tuple[Nap, ...]
    resting_hr: RestingHr | None
    hrv: HrvSummary | None
    respiration: RespirationSummary | None
    spo2: SpO2Summary | None
    stress: StressSummary | None
    body_battery: BodyBatterySummary | None
    activity_totals: ActivityTotals | None
    series: DaySeries
    readiness: tuple[ReadinessEntry, ...]
    versions: AlgorithmVersions
    device_ranks: tuple[int, ...]

    def __post_init__(self) -> None:
        parts = (self.window_start, self.data_end, self.window_family)
        if len({part is None for part in parts}) > 1:
            raise ContractError(
                "window_start, data_end et window_family vont ensemble."
            )
        if (self.window_start is None) != (self.state is DayState.EMPTY):
            raise ContractError(
                "window_start doit être absent si et seulement si state est empty."
            )
        if self.window_start is not None and self.data_end is not None:
            start = _require_instant(self.window_start, "window_start")
            object.__setattr__(self, "window_start", start)
            require_aware(self.data_end, "data_end")
            end = self.data_end.astimezone(start.tzinfo)
            object.__setattr__(self, "data_end", end)
            if start.date() != self.day:
                raise ContractError(
                    "window_start doit tomber le jour day, dans son décalage."
                )
            if end < start:
                raise ContractError("data_end ne peut pas précéder window_start.")
            if self.window_family not in DAY_WINDOW_FAMILIES:
                raise ContractError(
                    "window_family doit être une famille qui porte une fenêtre du jour."
                )
            if self.state is DayState.TRUNCATED and end >= start + _DAY:
                raise ContractError(
                    "state truncated : data_end doit précéder window_start + 24 h."
                )
            if self.state is DayState.COMPLETE and end < start + _DAY:
                raise ContractError(
                    "state complete : data_end doit valoir au moins window_start + "
                    "24 h."
                )
        elif any(
            series is not None
            for series in (
                self.series.heart_rate,
                self.series.stress,
                self.series.body_battery,
                self.series.respiration,
                self.series.spo2,
            )
        ):
            raise ContractError("series : sans fenêtre du jour, aucune série du jour.")
        require_export_name(self.reference_export)
        require_immutable_sequence(self.naps, "naps")
        require_increasing(
            [nap.start.timestamp() for nap in self.naps], "naps (début)", strict=False
        )
        require_immutable_sequence(self.readiness, "readiness")
        require_increasing(
            [entry.instant.timestamp() for entry in self.readiness],
            "readiness (instant)",
            strict=False,
        )
        require_immutable_sequence(self.device_ranks, "device_ranks")
        for rank in self.device_ranks:
            _require_at_least(rank, 1, "device_ranks")
        _require_strictly_sorted(
            [(rank,) for rank in self.device_ranks], "device_ranks"
        )


QUANTITY_SUPPORTS: Mapping[str, Support] = MappingProxyType(
    {
        "night": Support.NIGHT,
        "night.series": Support.INSTANT,
        "naps": Support.INSTANT,
        "resting_hr.resting_hr_bpm": Support.DAY,
        "hrv.last_night_avg_ms": Support.NIGHT,
        "hrv.last_night_5min_high_ms": Support.NIGHT,
        "hrv.weekly_avg_ms": Support.WAKING,
        "hrv.status": Support.WAKING,
        "hrv.baseline_balanced_low_ms": Support.WAKING,
        "hrv.baseline_balanced_upper_ms": Support.WAKING,
        "hrv.baseline_low_upper_ms": Support.WAKING,
        "hrv.baseline_marker_value": Support.WAKING,
        "respiration.avg_sleep_breaths_per_min": Support.NIGHT,
        "respiration.avg_waking_breaths_per_min": Support.DAY,
        "respiration.highest_breaths_per_min": Support.DAY,
        "respiration.lowest_breaths_per_min": Support.DAY,
        "spo2.avg_sleep_spo2_percent": Support.NIGHT,
        "spo2.average_spo2_percent": Support.DAY,
        "spo2.lowest_spo2_percent": Support.DAY,
        "stress.average_level": Support.DAY,
        "stress.average_level_code": Support.DAY,
        "stress.max_level": Support.DAY,
        "stress.rest_duration_s": Support.DAY,
        "stress.low_duration_s": Support.DAY,
        "stress.medium_duration_s": Support.DAY,
        "stress.high_duration_s": Support.DAY,
        "stress.activity_duration_s": Support.DAY,
        "stress.uncategorized_duration_s": Support.DAY,
        "stress.total_duration_s": Support.DAY,
        "stress.stress_duration_s": Support.DAY,
        "body_battery.charged": Support.DAY,
        "body_battery.drained": Support.DAY,
        "body_battery.highest": Support.DAY,
        "body_battery.lowest": Support.DAY,
        "body_battery.at_wake": Support.WAKING,
        "body_battery.during_sleep": Support.NIGHT,
        "activity_totals.steps": Support.DAY,
        "activity_totals.moderate_intensity_s": Support.DAY,
        "activity_totals.vigorous_intensity_s": Support.DAY,
        "activity_totals.floors_ascended_m": Support.DAY,
        "activity_totals.floors_descended_m": Support.DAY,
        "activity_totals.average_altitude_m": Support.DAY,
        "series": Support.INSTANT,
        "readiness": Support.INSTANT,
    }
)
"""Le support de chaque grandeur d'un ``DayRecord``, par son chemin dans le document :
un champ d'un résumé (``hrv.weekly_avg_ms``), ou un objet entier dont toutes les
grandeurs ont le même (``night`` : fenêtre, durées, résumés et segments). Les séries de
la nuit, ``night.series``, ont le support ``instant`` : l'instant propre d'un point est
l'instant du point, une fois la nuit finie (les vues ne rendent les séries d'une nuit
qu'une fois la nuit finie). Les docstrings des contrats le disent aussi."""


# ---------------------------------------------------------------------------
# Training Status
# ---------------------------------------------------------------------------


def _set_proper_instant(block: object, value: datetime | None) -> None:
    if value is not None:
        object.__setattr__(
            block, "proper_instant", _require_instant(value, "proper_instant")
        )


@dataclass(frozen=True)
class TrainingStatusBlock:
    """Un bloc « statut » de Training Status, à sa date propre
    (``mostRecentTrainingStatus.latestTrainingStatusData.<n>``, l'appareil principal).

    Champs
    ------
    - ``day`` — date — sa date propre (``calendarDate``).
    - ``file_day`` — date — le jour du fichier choisi : dans l'export choisi, le fichier
      du jour de la date propre du bloc s'il le porte, sinon le plus ancien qui le
      porte.
    - ``timestamp`` — instant — l'horodatage du statut (``timestamp``, ms GMT), s'il est
      porté, **en UTC** : la source ne donne que les millisecondes GMT, sans heure
      locale.
    - ``proper_instant`` — instant — l'instant propre, calculé à l'ingestion :
      ``timestamp`` s'il est porté ; sinon comme ``LoadBalanceBlock`` (la fin de la
      fenêtre du jour ``day``, sinon le début de la fenêtre du lendemain, sinon le
      minuit local qui suit ``day``, sinon absent).
    - ``status_code`` — sans unité — le statut, code de la source (``trainingStatus``),
      ``>= 0``.
    - ``acute_load`` — sans unité — charge aiguë
      (``acuteTrainingLoadDTO.dailyTrainingLoadAcute``), ``>= 0``.
    - ``chronic_load`` — sans unité — charge chronique (``dailyTrainingLoadChronic``),
      ``>= 0``.
    - ``acute_chronic_ratio`` — sans unité — leur rapport
      (``dailyAcuteChronicWorkloadRatio``), ``>= 0``.
    - ``acwr_percent`` — pourcentage — le rapport en pourcentage (``acwrPercent``),
      ``>= 0``.
    - ``acwr_status`` — sans unité — statut du rapport, code de la source
      (``acwrStatus``), non vide.
    - ``min_chronic_load``, ``max_chronic_load`` — sans unité — bornes de la charge
      chronique selon Garmin (``minTrainingLoadChronic``, ``maxTrainingLoadChronic``),
      ``>= 0``.
    - ``paused`` — sans unité — entraînement en pause (``trainingPaused``).
    - ``fitness_trend`` — sans unité — tendance de forme, code de la source
      (``fitnessTrend``).
    - ``source`` — sans unité — provenance : le fichier ``training_status`` choisi.

    Invariants
    ----------
    - ``timestamp`` et ``proper_instant`` *aware*, décalages dans leur plage, en
      secondes entières, ramenés à un fuseau à décalage fixe ;
    - avec ``timestamp``, ``proper_instant`` est le même instant ;
    - valeurs finies ``>= 0`` ; codes texte non vides.

    Producteur
    ----------
    La lecture des familles (``training_status``) ; l'ingestion des jours (l'export
    de référence du jour de sa date propre s'il le porte, sinon le plus récent qui le
    porte ; dans l'export choisi, le fichier du jour de la date propre du bloc s'il le
    porte, sinon le plus ancien qui le porte).

    Consommateurs
    -------------
    ``TrainingStatusHistory.statuses`` ; la vue ``training_status_at`` ; la page
    « récupération » (la charge aiguë, à sa date propre).

    Non promis
    ----------
    Un composite de Garmin, non publié ; la source le range sous l'identifiant de la
    montre, que l'ingestion ne garde pas. Le décalage de ``timestamp`` (UTC) n'est pas
    celui d'une heure locale : la source n'en donne pas.
    """

    day: date
    file_day: date
    timestamp: datetime | None
    proper_instant: datetime | None
    status_code: int | None
    acute_load: float | None
    chronic_load: float | None
    acute_chronic_ratio: float | None
    acwr_percent: float | None
    acwr_status: str | None
    min_chronic_load: float | None
    max_chronic_load: float | None
    paused: bool | None
    fitness_trend: int | None
    source: SourceRef

    def __post_init__(self) -> None:
        _set_proper_instant(self, self.proper_instant)
        if self.timestamp is not None:
            object.__setattr__(
                self, "timestamp", _require_instant(self.timestamp, "timestamp")
            )
            if self.proper_instant != self.timestamp:
                raise ContractError(
                    "proper_instant doit être l'horodatage du statut quand il est "
                    "porté."
                )
        if self.status_code is not None:
            _require_at_least(self.status_code, 0, "status_code")
        for name in (
            "acute_load",
            "chronic_load",
            "acute_chronic_ratio",
            "acwr_percent",
            "min_chronic_load",
            "max_chronic_load",
        ):
            _require_optional_in_range(getattr(self, name), name, 0.0)
        if self.acwr_status is not None:
            require_non_empty(self.acwr_status, "acwr_status")


_LOAD_BALANCE_VALUES = (
    "monthly_aerobic_low",
    "monthly_aerobic_low_target_min",
    "monthly_aerobic_low_target_max",
    "monthly_aerobic_high",
    "monthly_aerobic_high_target_min",
    "monthly_aerobic_high_target_max",
    "monthly_anaerobic",
    "monthly_anaerobic_target_min",
    "monthly_anaerobic_target_max",
)


@dataclass(frozen=True)
class LoadBalanceBlock:
    """Un bloc « équilibre de la charge » de Training Status, à sa date propre
    (``mostRecentTrainingLoadBalance.metricsTrainingLoadBalanceDTOMap.<n>``).

    Champs
    ------
    - ``day`` — date — sa date propre (``calendarDate``).
    - ``file_day`` — date — le jour du fichier choisi.
    - ``proper_instant`` — instant — l'instant propre, calculé à l'ingestion : la fin
      de la fenêtre du jour ``day``, celle des grandeurs ``day`` (le plus tard de son
      début + 24 h et de sa fin des données ; le lendemain n'y entre pas) ; sans
      fenêtre de ce jour, le début de la fenêtre du lendemain, si ce lendemain a une
      fenêtre (un document ``empty`` n'en a pas ; l'instant propre dépend alors du
      lendemain : avec ou sans sa fenêtre, il diffère de l'écart des deux
      décalages) ; sinon le minuit local qui suit ``day``
      au décalage de la fenêtre du jour du fichier (une heure trop tôt ou trop tard
      quand ce fichier est de l'autre côté d'un changement d'heure, de l'écart des
      décalages après un voyage) ; sinon absent (compté au rapport, aucune vue ne le
      rend).
    - ``monthly_aerobic_low`` — sans unité — charge mensuelle aérobie basse
      (``monthlyLoadAerobicLow``), ``>= 0``.
    - ``monthly_aerobic_low_target_min``, ``monthly_aerobic_low_target_max`` — sans
      unité — sa cible (``…TargetMin``, ``…TargetMax``), ``>= 0``.
    - ``monthly_aerobic_high`` — sans unité — aérobie haute
      (``monthlyLoadAerobicHigh``), ``>= 0``.
    - ``monthly_aerobic_high_target_min``, ``monthly_aerobic_high_target_max`` — sans
      unité — sa cible, ``>= 0``.
    - ``monthly_anaerobic`` — sans unité — anaérobie (``monthlyLoadAnaerobic``),
      ``>= 0``.
    - ``monthly_anaerobic_target_min``, ``monthly_anaerobic_target_max`` — sans unité —
      sa cible, ``>= 0``.
    - ``source`` — sans unité — provenance : le fichier ``training_status`` choisi.

    Invariants
    ----------
    ``proper_instant`` *aware*, décalage dans sa plage, en secondes entières, ramené à
    un fuseau à décalage fixe ; valeurs finies ``>= 0``.

    Producteur
    ----------
    La lecture des familles (``training_status``) ; l'ingestion des jours.

    Consommateurs
    -------------
    ``TrainingStatusHistory.load_balances`` ; la vue ``training_status_at``.

    Non promis
    ----------
    Le bloc n'a qu'une date, pas d'horodatage : avec ``t`` au matin de ``day``, il n'est
    pas rendu.
    """

    day: date
    file_day: date
    proper_instant: datetime | None
    monthly_aerobic_low: float | None
    monthly_aerobic_low_target_min: float | None
    monthly_aerobic_low_target_max: float | None
    monthly_aerobic_high: float | None
    monthly_aerobic_high_target_min: float | None
    monthly_aerobic_high_target_max: float | None
    monthly_anaerobic: float | None
    monthly_anaerobic_target_min: float | None
    monthly_anaerobic_target_max: float | None
    source: SourceRef

    def __post_init__(self) -> None:
        _set_proper_instant(self, self.proper_instant)
        for name in _LOAD_BALANCE_VALUES:
            _require_optional_in_range(getattr(self, name), name, 0.0)


@dataclass(frozen=True)
class Vo2MaxBlock:
    """Un bloc « VO2max » de Training Status, à sa date propre
    (``mostRecentVO2Max.generic``).

    Champs
    ------
    - ``day`` — date — sa date propre (``calendarDate``).
    - ``file_day`` — date — le jour du fichier choisi.
    - ``proper_instant`` — instant — l'instant propre, calculé à l'ingestion (comme
      ``LoadBalanceBlock``).
    - ``vo2_max_precise_ml_kg_min`` — ml/kg/min — valeur précise
      (``vo2MaxPreciseValue``), ``>= 0``.
    - ``vo2_max_ml_kg_min`` — ml/kg/min — valeur entière affichée (``vo2MaxValue``),
      ``>= 0``.
    - ``source`` — sans unité — provenance : le fichier ``training_status`` choisi.

    Invariants
    ----------
    ``proper_instant`` *aware*, décalage dans sa plage, en secondes entières, ramené à
    un fuseau à décalage fixe ; valeurs finies ``>= 0``.

    Producteur
    ----------
    La lecture des familles (``training_status``) ; l'ingestion des jours.

    Consommateurs
    -------------
    ``TrainingStatusHistory.vo2_max`` ; la vue ``training_status_at`` ; M7.

    Non promis
    ----------
    La VO2max peut être une valeur reportée d'un jour antérieur ; c'est une
    estimation de Garmin.
    """

    day: date
    file_day: date
    proper_instant: datetime | None
    vo2_max_precise_ml_kg_min: float | None
    vo2_max_ml_kg_min: float | None
    source: SourceRef

    def __post_init__(self) -> None:
        _set_proper_instant(self, self.proper_instant)
        for name in ("vo2_max_precise_ml_kg_min", "vo2_max_ml_kg_min"):
            _require_optional_in_range(getattr(self, name), name, 0.0)


@dataclass(frozen=True)
class HeatAcclimationBlock:
    """Un bloc « acclimatation à la chaleur » de Training Status, à sa date propre
    (``mostRecentVO2Max.heatAltitudeAcclimation``, ``heatAcclimationDate``).

    Champs
    ------
    - ``day`` — date — sa date propre (``heatAcclimationDate``).
    - ``file_day`` — date — le jour du fichier choisi.
    - ``proper_instant`` — instant — l'instant propre, calculé à l'ingestion (comme
      ``LoadBalanceBlock``).
    - ``heat_acclimation_percent`` — pourcentage — acclimatation
      (``heatAcclimationPercentage``), ``>= 0``.
    - ``heat_trend`` — sans unité — tendance, code de la source (``heatTrend``), non
      vide.
    - ``source`` — sans unité — provenance : le fichier ``training_status`` choisi.

    Invariants
    ----------
    ``proper_instant`` *aware*, décalage dans sa plage, en secondes entières, ramené à
    un fuseau à décalage fixe ; valeur finie ``>= 0`` ; code non vide.

    Producteur
    ----------
    La lecture des familles (``training_status``) ; l'ingestion des jours.

    Consommateurs
    -------------
    ``TrainingStatusHistory.heat_acclimation`` ; la vue ``training_status_at`` ; M7.

    Non promis
    ----------
    Sa date propre peut précéder le jour du fichier ; l'horodatage local du bloc
    (sans décalage) ne date rien et ne s'ingère pas.
    """

    day: date
    file_day: date
    proper_instant: datetime | None
    heat_acclimation_percent: float | None
    heat_trend: str | None
    source: SourceRef

    def __post_init__(self) -> None:
        _set_proper_instant(self, self.proper_instant)
        _require_optional_in_range(
            self.heat_acclimation_percent, "heat_acclimation_percent", 0.0
        )
        if self.heat_trend is not None:
            require_non_empty(self.heat_trend, "heat_trend")


@dataclass(frozen=True)
class AltitudeAcclimationBlock:
    """Un bloc « acclimatation à l'altitude » de Training Status, à sa date propre
    (``mostRecentVO2Max.heatAltitudeAcclimation``, ``altitudeAcclimationDate``).

    Champs
    ------
    - ``day`` — date — sa date propre (``altitudeAcclimationDate``).
    - ``file_day`` — date — le jour du fichier choisi.
    - ``proper_instant`` — instant — l'instant propre, calculé à l'ingestion (comme
      ``LoadBalanceBlock``).
    - ``acclimation_altitude_m`` — mètres — altitude d'acclimatation selon Garmin
      (``altitudeAcclimation``), ``[-500, 9000]`` ; l'unité est celle de Garmin, lue
      comme des mètres, **non vérifiée**.
    - ``current_altitude_m`` — mètres — altitude courante (``currentAltitude``),
      ``[-500, 9000]``.
    - ``altitude_trend`` — sans unité — tendance, code de la source
      (``altitudeTrend``), non vide.
    - ``source`` — sans unité — provenance : le fichier ``training_status`` choisi.

    Invariants
    ----------
    ``proper_instant`` *aware*, décalage dans sa plage, en secondes entières, ramené à
    un fuseau à décalage fixe ; altitudes finies dans leur plage ; code non vide.

    Producteur
    ----------
    La lecture des familles (``training_status``) ; l'ingestion des jours.

    Consommateurs
    -------------
    ``TrainingStatusHistory.altitude_acclimation`` ; la vue ``training_status_at`` ;
    M7.

    Non promis
    ----------
    Sa date propre peut précéder le jour du fichier, et différer de celle de la chaleur
    dans le même bloc de la source ; l'horodatage local ne date rien. L'unité de
    ``acclimation_altitude_m`` n'est pas publiée par Garmin : le mètre est supposé, pas
    vérifié.
    """

    day: date
    file_day: date
    proper_instant: datetime | None
    acclimation_altitude_m: float | None
    current_altitude_m: float | None
    altitude_trend: str | None
    source: SourceRef

    def __post_init__(self) -> None:
        _set_proper_instant(self, self.proper_instant)
        for name in ("acclimation_altitude_m", "current_altitude_m"):
            _require_optional_in_range(getattr(self, name), name, *ELEVATION_RANGE_M)
        if self.altitude_trend is not None:
            require_non_empty(self.altitude_trend, "altitude_trend")


_HISTORY_SUITES = (
    "statuses",
    "load_balances",
    "vo2_max",
    "heat_acclimation",
    "altitude_acclimation",
)


@dataclass(frozen=True)
class TrainingStatusHistory:
    """Les blocs de Training Status, une suite par sorte (document
    ``interim/days/training_status.json``).

    Champs
    ------
    - ``statuses`` — sans unité — les blocs « statut ».
    - ``load_balances`` — sans unité — les blocs « équilibre de la charge ».
    - ``vo2_max`` — sans unité — les blocs « VO2max ».
    - ``heat_acclimation`` — sans unité — les blocs « acclimatation à la chaleur ».
    - ``altitude_acclimation`` — sans unité — les blocs « acclimatation à
      l'altitude ».

    Invariants
    ----------
    Chaque suite en tuple, triée par date propre (``day``), une seule entrée par date.

    Producteur
    ----------
    L'ingestion des jours (un bloc de date propre D : l'export de référence du jour D
    s'il le porte, sinon le plus récent qui le porte ; dans l'export choisi, le
    fichier du jour D s'il le porte, sinon le plus ancien qui le porte) ; écrit par
    ``write_days``.

    Consommateurs
    -------------
    ``read_training_status`` ; la vue ``training_status_at``, qui ne lit que ce
    document ; la table ``jours`` (AN2-2), chaque bloc à la ligne de sa date propre.

    Non promis
    ----------
    Un bloc peut dater d'un jour qu'aucun fichier ne porte ; un bloc sans instant
    propre reste dans le document, et aucune vue ne le rend.
    """

    statuses: tuple[TrainingStatusBlock, ...]
    load_balances: tuple[LoadBalanceBlock, ...]
    vo2_max: tuple[Vo2MaxBlock, ...]
    heat_acclimation: tuple[HeatAcclimationBlock, ...]
    altitude_acclimation: tuple[AltitudeAcclimationBlock, ...]

    def __post_init__(self) -> None:
        for name in _HISTORY_SUITES:
            require_immutable_sequence(getattr(self, name), name)
        for name in _HISTORY_SUITES:
            blocks = getattr(self, name)
            _require_strictly_sorted([(block.day,) for block in blocks], name)


# ---------------------------------------------------------------------------
# Le rapport des jours
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DaysExportReport:
    """Un export, vu par l'ingestion des jours.

    Champs
    ------
    - ``name`` — sans unité — le nom de son dossier sous ``raw/garmin/``.
    - ``retrieved_at`` — instant — son instant d'acquisition, stocké en UTC.
    - ``first_day``, ``last_day`` — date — premier et dernier jour de ses fichiers
      journaliers ; absents s'il n'en a pas.
    - ``files`` — sans unité — ses fichiers journaliers lus, ``>= 0``.
    - ``families`` — sans unité — les familles qu'il porte (au moins un fichier),
      triées.

    Invariants
    ----------
    - ``name`` : lettres et chiffres ASCII, ``_``, ``.``, ``-`` ; ``retrieved_at``
      *aware*, ramené en UTC ;
    - ``first_day`` et ``last_day`` présents ensemble, ``first_day <= last_day`` ;
      absents sans fichier ;
    - ``families`` en tuple, trié, sans doublon.

    Producteur
    ----------
    L'ingestion des jours.

    Consommateurs
    -------------
    ``DaysReport`` ; ``mperf ingest``.

    Non promis
    ----------
    Un export sans familles journalières est admis : ``files`` vaut 0.
    """

    name: str
    retrieved_at: datetime
    first_day: date | None
    last_day: date | None
    files: int
    families: tuple[DayFamily, ...]

    def __post_init__(self) -> None:
        require_export_name(self.name)
        require_aware(self.retrieved_at, "retrieved_at")
        object.__setattr__(self, "retrieved_at", self.retrieved_at.astimezone(UTC))
        _require_at_least(self.files, 0, "files")
        if (self.first_day is None) != (self.last_day is None):
            raise ContractError("first_day et last_day vont ensemble.")
        if (
            self.first_day is not None
            and self.last_day is not None
            and self.first_day > self.last_day
        ):
            raise ContractError("first_day ne peut pas suivre last_day.")
        if self.files == 0 and self.first_day is not None:
            raise ContractError("first_day : un export sans fichier, sans jour.")
        require_immutable_sequence(self.families, "families")
        _require_strictly_sorted([(family,) for family in self.families], "families")


@dataclass(frozen=True)
class DayFileRefused:
    """Un fichier journalier que la lecture des familles a refusé, et pourquoi.

    Champs
    ------
    - ``name`` — sans unité — chemin relatif à ``raw/``
      (``garmin/<export>/<famille>/<date>.json``).
    - ``reason`` — sans unité — le motif.

    Invariants
    ----------
    ``name`` comme dans ``ReadFile``.

    Producteur
    ----------
    La lecture des familles.

    Consommateurs
    -------------
    ``DaysReport``.

    Non promis
    ----------
    Le message du lecteur JSON n'est pas gardé.
    """

    name: str
    reason: DayFileRefusal

    def __post_init__(self) -> None:
        _require_relative_name(self.name)


@dataclass(frozen=True)
class ExportDayCount:
    """Le nombre de jours dont un export est l'export de référence.

    Champs
    ------
    - ``export`` — sans unité — le nom de l'export.
    - ``days`` — sans unité — le nombre de jours, ``> 0``.

    Invariants
    ----------
    ``export`` : lettres et chiffres ASCII, ``_``, ``.``, ``-`` ; ``days > 0``.

    Producteur
    ----------
    L'ingestion des jours.

    Consommateurs
    -------------
    ``DaysReport.reference_days``.

    Non promis
    ----------
    Un export de référence de nul jour n'y figure pas.
    """

    export: str
    days: int

    def __post_init__(self) -> None:
        require_export_name(self.export)
        _require_at_least(self.days, 1, "days")


@dataclass(frozen=True)
class FamilyDayCount:
    """Un nombre de jours, par famille.

    Champs
    ------
    - ``family`` — sans unité — la famille.
    - ``days`` — sans unité — le nombre de jours, ``> 0``.

    Invariants
    ----------
    ``days > 0``.

    Producteur
    ----------
    L'ingestion des jours.

    Consommateurs
    -------------
    ``DaysReport.window_families`` (jours dont la fenêtre vient de cette famille, pas
    de ``daily_summary``) et ``DaysReport.window_mismatches`` (jours où la fenêtre de
    cette famille diffère de celle du jour).

    Non promis
    ----------
    Une famille à zéro jour n'y figure pas.
    """

    family: DayFamily
    days: int

    def __post_init__(self) -> None:
        _require_at_least(self.days, 1, "days")


@dataclass(frozen=True)
class BorrowingCount:
    """Le nombre d'emprunts d'un morceau d'une famille, d'un autre export que l'export
    de référence du jour. Une famille empruntée entière compte un emprunt par morceau
    de ``FAMILY_PIECES`` qu'elle porte chez le prêteur (un morceau qu'il n'a pas — des
    siestes ``()``, des totaux d'activité absents — ne se compte pas) ; sa série du
    jour refusée (``day_window``) compte un refus, pas un emprunt.

    Champs
    ------
    - ``family`` — sans unité — la famille du morceau.
    - ``piece`` — sans unité — le chemin du morceau dans ``DayRecord`` (``night``,
      ``night.series.hrv``, ``night.segments``, ``series.heart_rate``…), non vide.
    - ``count`` — sans unité — le nombre de jours, ``> 0``.

    Invariants
    ----------
    ``piece`` non vide ; ``count > 0``.

    Producteur
    ----------
    L'ingestion des jours.

    Consommateurs
    -------------
    ``DaysReport.borrowings``.

    Non promis
    ----------
    L'export prêteur n'est pas dit : il est dans la provenance du morceau.
    """

    family: DayFamily
    piece: str
    count: int

    def __post_init__(self) -> None:
        require_non_empty(self.piece, "piece")
        _require_at_least(self.count, 1, "count")


@dataclass(frozen=True)
class BorrowingRefusalCount:
    """Le nombre d'emprunts refusés d'un morceau d'une famille, pour un motif. Un refus
    d'une famille entière compte chaque morceau de ``FAMILY_PIECES`` qu'elle porte chez
    le prêteur.

    Champs
    ------
    - ``family`` — sans unité — la famille du morceau.
    - ``piece`` — sans unité — le chemin du morceau dans ``DayRecord``, non vide.
    - ``reason`` — sans unité — le motif du refus.
    - ``count`` — sans unité — le nombre de jours, ``> 0``.

    Invariants
    ----------
    ``piece`` non vide ; ``count > 0``.

    Producteur
    ----------
    L'ingestion des jours.

    Consommateurs
    -------------
    ``DaysReport.borrowing_refusals``.

    Non promis
    ----------
    Le morceau refusé reste absent du jour.
    """

    family: DayFamily
    piece: str
    reason: BorrowingRefusal
    count: int

    def __post_init__(self) -> None:
        require_non_empty(self.piece, "piece")
        _require_at_least(self.count, 1, "count")


@dataclass(frozen=True)
class ComparisonCount:
    """Le nombre de jours où un champ d'une famille diffère entre deux exports, pour
    une classe d'écart.

    Champs
    ------
    - ``family`` — sans unité — la famille.
    - ``field_path`` — sans unité — la feuille comparée (``FamilyRead.fields``) : le
      chemin d'une valeur dans la source (``dailySleepDTO.sleepScores.overall.value``) ;
      d'une liste, ``<chemin>[*]`` (``sleepLevels[*]``, ``heartRateValues[*]``) ; d'une
      racine liste (``body_battery``, ``training_readiness``), ``[*]`` ; non vide.
    - ``comparison`` — sans unité — la classe de l'écart.
    - ``days`` — sans unité — le nombre de jours, ``> 0``.

    Invariants
    ----------
    ``field_path`` non vide ; ``days > 0``.

    Producteur
    ----------
    L'ingestion des jours.

    Consommateurs
    -------------
    ``DaysReport.comparisons`` ; la charte, § 7 (les révisions non nulles).

    Non promis
    ----------
    Un jour compte une fois par champ et par classe, quel que soit le nombre d'exports
    qui diffèrent.
    """

    family: DayFamily
    field_path: str
    comparison: ComparisonClass
    days: int

    def __post_init__(self) -> None:
        require_non_empty(self.field_path, "field_path")
        _require_at_least(self.days, 1, "days")


@dataclass(frozen=True)
class WindowEdgeCount:
    """Les comptes des bords de fenêtre pour une série d'une famille : les points
    hors de la fenêtre de leur fichier, et les instants présents dans deux fichiers
    voisins.

    Champs
    ------
    - ``family`` — sans unité — la famille.
    - ``series_path`` — sans unité — le chemin de la série dans la source
      (``heartRateValues``, ``sleepHeartRate``…), non vide.
    - ``outside_window`` — sans unité — points hors de la fenêtre de leur fichier,
      gardés au jour du fichier, ``>= 0``.
    - ``shared_instants`` — sans unité — instants présents dans deux fichiers voisins,
      ``>= 0``.

    Invariants
    ----------
    ``series_path`` non vide ; comptes ``>= 0``, l'un au moins ``> 0``.

    Producteur
    ----------
    L'ingestion des jours.

    Consommateurs
    -------------
    ``DaysReport.window_edges`` ; la vue ``series_between``, qui dédoublonne par
    instant.

    Non promis
    ----------
    L'écart entre le dernier instant d'un jour et le premier du suivant est à part
    (``DayBoundaryGap``).
    """

    family: DayFamily
    series_path: str
    outside_window: int
    shared_instants: int

    def __post_init__(self) -> None:
        require_non_empty(self.series_path, "series_path")
        _require_at_least(self.outside_window, 0, "outside_window")
        _require_at_least(self.shared_instants, 0, "shared_instants")
        if self.outside_window == 0 and self.shared_instants == 0:
            raise ContractError(
                "outside_window ou shared_instants doit être > 0 : un compte nul n'est "
                "pas écrit."
            )


@dataclass(frozen=True)
class DayBoundaryGap:
    """Le plus grand écart, pour une série du jour d'une famille, entre le dernier
    instant d'un jour et le premier du jour suivant.

    Champs
    ------
    - ``family`` — sans unité — la famille.
    - ``series_path`` — sans unité — le chemin de la série dans la source
      (``heartRateValues``, ``stressValuesArray``…), non vide.
    - ``pairs`` — sans unité — le nombre de couples de jours consécutifs (J, J + 1)
      qui portent tous deux la série, ``> 0``.
    - ``max_gap_s`` — secondes — le plus grand écart (premier instant de J + 1 moins
      dernier instant de J) sur ces couples, fini ; négatif si les deux fichiers se
      recouvrent (un instant présent dans les deux, le changement d'heure du
      printemps).

    Invariants
    ----------
    ``series_path`` non vide ; ``pairs > 0`` ; ``max_gap_s`` fini.

    Producteur
    ----------
    L'ingestion des jours, sur les séries du jour des documents écrits (après choix
    de l'export de référence et emprunts).

    Consommateurs
    -------------
    ``DaysReport.day_boundary_gaps`` ; le plan des questions qui recollent deux jours
    (la vue ``series_between``, sa couverture).

    Non promis
    ----------
    Les séries de la nuit n'y sont pas : deux nuits voisines ne se recollent pas. Un
    écart dit un trou entre deux fichiers, pas sa cause (montre retirée, détail
    effacé, changement d'heure de l'automne).
    """

    family: DayFamily
    series_path: str
    pairs: int
    max_gap_s: float

    def __post_init__(self) -> None:
        require_non_empty(self.series_path, "series_path")
        _require_at_least(self.pairs, 1, "pairs")
        require_finite(self.max_gap_s, "max_gap_s")


@dataclass(frozen=True)
class ReadinessCopyCount:
    """Les copies d'une grandeur que portent les entrées de Training Readiness
    (« copie antérieure ») : comptées à part, hors du contrôle des copies.

    Champs
    ------
    - ``quantity`` — sans unité — la grandeur finale que l'entrée recopie, par son
      chemin : ``night.sleep_score`` (``sleepScore``), ``hrv.weekly_avg_ms``
      (``hrvWeeklyAverage``) dans ``DayRecord`` ; ``statuses.acute_load``
      (``acuteLoad``), la charge aiguë du bloc « statut » de la date du jour, dans
      ``TrainingStatusHistory``.
    - ``entries`` — sans unité — les entrées retenues qui portent la copie, ``> 0``.
    - ``differing`` — sans unité — parmi elles, celles dont la copie diffère de la
      grandeur finale, quand celle-ci est portée, ``>= 0``.

    Invariants
    ----------
    ``quantity`` non vide ; ``entries > 0`` ; ``0 <= differing <= entries``.

    Producteur
    ----------
    L'ingestion des jours, sur les entrées retenues de chaque jour.

    Consommateurs
    -------------
    ``DaysReport.readiness_prior_copies``.

    Non promis
    ----------
    Une copie qui diffère n'est pas une erreur : elle date du moment de l'entrée,
    avant le document final ; aucune des deux n'est corrigée.
    Une entrée dont la grandeur finale manque compte dans ``entries``, pas dans
    ``differing``.
    """

    quantity: str
    entries: int
    differing: int

    def __post_init__(self) -> None:
        require_non_empty(self.quantity, "quantity")
        _require_at_least(self.entries, 1, "entries")
        _require_at_least(self.differing, 0, "differing")
        if self.differing > self.entries:
            raise ContractError("differing ne peut pas dépasser entries.")


@dataclass(frozen=True)
class CopyDisagreementCount:
    """Le nombre de jours où la copie d'une grandeur dans une autre famille ne
    s'accorde pas avec la source de la grandeur.

    Champs
    ------
    - ``quantity`` — sans unité — la grandeur, par son chemin dans ``DayRecord``
      (``resting_hr.resting_hr_bpm``…), non vide.
    - ``family`` — sans unité — la famille qui porte la copie.
    - ``days`` — sans unité — le nombre de jours, ``> 0``.

    Invariants
    ----------
    ``quantity`` non vide ; ``days > 0``.

    Producteur
    ----------
    L'ingestion des jours (les copies contrôlées de la lecture des familles,
    ``COPY_FIELDS``).

    Consommateurs
    -------------
    ``DaysReport.copy_disagreements``.

    Non promis
    ----------
    Les copies de Training Readiness ne sont pas contrôlées (« copie antérieure ») :
    elles se comptent à part (``ReadinessCopyCount``).
    """

    quantity: str
    family: DayFamily
    days: int

    def __post_init__(self) -> None:
        require_non_empty(self.quantity, "quantity")
        _require_at_least(self.days, 1, "days")


@dataclass(frozen=True)
class PointDiscardCount:
    """Le nombre de points (ou de segments, d'épisodes, de valeurs) d'une série d'une
    famille écartés pour un motif.

    Champs
    ------
    - ``family`` — sans unité — la famille.
    - ``series_path`` — sans unité — le chemin de la série dans la source
      (``heartRateValues``, ``sleepLevels``…), ou du champ d'une valeur écartée
      (``dailySleepDTO.avgHeartRate``…), ou ``night``, ``naps``, ``window``,
      ``readiness`` pour la nuit, une sieste, la fenêtre du jour, une entrée ; non vide.
    - ``reason`` — sans unité — le motif.
    - ``count`` — sans unité — le nombre de points, ``> 0``.

    Invariants
    ----------
    ``series_path`` non vide ; ``count > 0``.

    Producteur
    ----------
    La lecture des familles.

    Consommateurs
    -------------
    ``DaysReport.point_discards``.

    Non promis
    ----------
    Les points écartés ne sont pas listés.
    """

    family: DayFamily
    series_path: str
    reason: PointDiscard
    count: int

    def __post_init__(self) -> None:
        require_non_empty(self.series_path, "series_path")
        _require_at_least(self.count, 1, "count")


@dataclass(frozen=True)
class CodeCount:
    """Le nombre de fois qu'un code de la source, inconnu de la lecture des familles,
    apparaît dans un champ.

    Champs
    ------
    - ``family`` — sans unité — la famille.
    - ``field_path`` — sans unité — le chemin du champ dans la source, non vide.
    - ``code`` — sans unité — la valeur du code, en texte (``-3``, ``AUTO_SLEEP``…),
      non vide.
    - ``count`` — sans unité — le nombre d'apparitions, ``> 0``.

    Invariants
    ----------
    Textes non vides ; ``count > 0``.

    Producteur
    ----------
    La lecture des familles.

    Consommateurs
    -------------
    ``DaysReport.unknown_codes`` et ``DaysReport.unknown_confirmations``.

    Non promis
    ----------
    Un code est une étiquette de la source, jamais un identifiant ni un texte libre :
    ni nom d'activité, ni phrase de conseil.
    """

    family: DayFamily
    field_path: str
    code: str
    count: int

    def __post_init__(self) -> None:
        require_non_empty(self.field_path, "field_path")
        require_non_empty(self.code, "code")
        _require_at_least(self.count, 1, "count")


@dataclass(frozen=True)
class BlockCount:
    """Un nombre de blocs de Training Status, par sorte.

    Champs
    ------
    - ``kind`` — sans unité — la sorte.
    - ``count`` — sans unité — le nombre de blocs, ``> 0``.

    Invariants
    ----------
    ``count > 0``.

    Producteur
    ----------
    L'ingestion des jours.

    Consommateurs
    -------------
    ``DaysReport.refused_blocks`` (sans date propre) et
    ``DaysReport.blocks_without_proper_instant``.

    Non promis
    ----------
    Une sorte à zéro bloc n'y figure pas.
    """

    kind: TrainingStatusKind
    count: int

    def __post_init__(self) -> None:
        _require_at_least(self.count, 1, "count")


@dataclass(frozen=True)
class BlockFieldCount:
    """Le nombre de blocs de Training Status dont un champ diffère d'une copie à
    l'autre du même bloc.

    Champs
    ------
    - ``kind`` — sans unité — la sorte.
    - ``field_path`` — sans unité — le chemin du champ dans le bloc de la source, non
      vide.
    - ``count`` — sans unité — le nombre de blocs (une sorte, une date propre) dont ce
      champ diffère, ``> 0`` : un bloc compte une fois, quel que soit le nombre
      d'exports où l'écart se voit.

    Invariants
    ----------
    ``field_path`` non vide ; ``count > 0``.

    Producteur
    ----------
    L'ingestion des jours.

    Consommateurs
    -------------
    ``DaysReport.block_differences_in_export`` (deux fichiers d'un même export) et
    ``DaysReport.block_differences_between_exports``.

    Non promis
    ----------
    La copie gardée est celle du fichier choisi : dans l'export choisi, le fichier
    du jour de la date propre du bloc s'il le porte, sinon le plus ancien qui le porte.
    """

    kind: TrainingStatusKind
    field_path: str
    count: int

    def __post_init__(self) -> None:
        require_non_empty(self.field_path, "field_path")
        _require_at_least(self.count, 1, "count")


_REPORT_LISTS = (
    "exports",
    "read",
    "refused",
    "reference_days",
    "window_families",
    "window_mismatches",
    "borrowings",
    "borrowing_refusals",
    "comparisons",
    "window_edges",
    "day_boundary_gaps",
    "copy_disagreements",
    "readiness_prior_copies",
    "point_discards",
    "unknown_codes",
    "unknown_confirmations",
    "refused_blocks",
    "block_differences_in_export",
    "block_differences_between_exports",
    "blocks_without_proper_instant",
)

_REPORT_SCALARS = (
    "night_equality_violations",
    "naps_overlapping_night",
    "readiness_non_primary",
)


def _count_key(item: object) -> tuple[object, ...]:
    """La clé de tri d'un compte du rapport : tous ses champs sauf ses nombres."""
    match item:
        case FamilyDayCount(family=family):
            return (family,)
        case BorrowingCount(family=family, piece=piece):
            return (family, piece)
        case BorrowingRefusalCount(family=family, piece=piece, reason=reason):
            return (family, piece, reason)
        case ComparisonCount(family=family, field_path=path, comparison=comparison):
            return (family, path, comparison)
        case WindowEdgeCount(family=family, series_path=path):
            return (family, path)
        case DayBoundaryGap(family=family, series_path=path):
            return (family, path)
        case CopyDisagreementCount(quantity=quantity, family=family):
            return (quantity, family)
        case ReadinessCopyCount(quantity=quantity):
            return (quantity,)
        case PointDiscardCount(family=family, series_path=path, reason=reason):
            return (family, path, reason)
        case CodeCount(family=family, field_path=path, code=code):
            return (family, path, code)
        case BlockCount(kind=kind):
            return (kind,)
        case BlockFieldCount(kind=kind, field_path=path):
            return (kind, path)
    raise TypeError(f"pas un compte du rapport : {type(item).__name__}")


_SORTED_COUNTS = (
    "window_families",
    "window_mismatches",
    "borrowings",
    "borrowing_refusals",
    "comparisons",
    "window_edges",
    "day_boundary_gaps",
    "copy_disagreements",
    "readiness_prior_copies",
    "point_discards",
    "unknown_codes",
    "unknown_confirmations",
    "refused_blocks",
    "blocks_without_proper_instant",
    "block_differences_in_export",
    "block_differences_between_exports",
)

_FAMILY_VALUES = frozenset(family.value for family in DayFamily)


@dataclass(frozen=True)
class DaysReport:
    """Le rapport des jours de la dernière ingestion (document
    ``interim/days/report.json``).

    Champs
    ------
    - ``exports`` — sans unité — les exports, par instant d'acquisition croissant.
    - ``read`` — sans unité — les fichiers journaliers lus, triés par nom
      (``garmin/<export>/<famille>/<date>.json``).
    - ``refused`` — sans unité — les fichiers refusés, triés par nom.
    - ``reference_days`` — sans unité — les jours par export de référence, triés par
      export.
    - ``window_families`` — sans unité — les jours dont la fenêtre ne vient pas de
      ``daily_summary``, par famille.
    - ``window_mismatches`` — sans unité — par famille, les jours où sa fenêtre diffère
      de celle du jour.
    - ``borrowings`` — sans unité — les emprunts, par famille et morceau.
    - ``borrowing_refusals`` — sans unité — les refus d'emprunt, par famille, morceau
      et motif.
    - ``comparisons`` — sans unité — les écarts entre exports, par famille, chemin de
      champ et classe, en jours.
    - ``window_edges`` — sans unité — les comptes des bords de fenêtre, par famille
      et série.
    - ``day_boundary_gaps`` — sans unité — par famille et série du jour, le plus
      grand écart entre le dernier instant d'un jour et le premier du suivant.
    - ``copy_disagreements`` — sans unité — les désaccords entre copies, par grandeur
      et famille de la copie.
    - ``readiness_prior_copies`` — sans unité — les copies de Training Readiness
      (« copie antérieure »), par grandeur copiée, hors du contrôle des copies.
    - ``night_equality_violations`` — sans unité — les nuits dont l'égalité
      ``end − start`` = phases + éveil + non mesurable est fausse au-delà de la
      tolérance de la nuit, ``>= 0``.
    - ``point_discards`` — sans unité — les points et segments écartés, par famille,
      série et motif.
    - ``unknown_codes`` — sans unité — les codes inconnus et les contextes de Training
      Readiness inconnus, avec leur valeur.
    - ``unknown_confirmations`` — sans unité — les types de confirmation inconnus de la
      nuit, avec leur valeur.
    - ``naps_overlapping_night`` — sans unité — les siestes qui recoupent la nuit,
      ``>= 0``.
    - ``refused_blocks`` — sans unité — les blocs de Training Status refusés (sans
      date propre), par sorte.
    - ``block_differences_in_export`` — sans unité — les écarts d'un même bloc entre
      deux fichiers d'un export, par sorte et champ.
    - ``block_differences_between_exports`` — sans unité — les écarts d'un même bloc
      entre deux exports, par sorte et champ.
    - ``blocks_without_proper_instant`` — sans unité — les blocs sans instant propre,
      par sorte.
    - ``readiness_non_primary`` — sans unité — les entrées de Training Readiness d'un
      appareil que la source ne dit pas principal, non retenues, ``>= 0``.

    Invariants
    ----------
    - au moins un export ; instants d'acquisition strictement croissants ; noms
      uniques ;
    - chaque fichier lu est nommé ``garmin/<export>/<famille>/<fichier>``, d'un export
      du rapport et d'une famille journalière ; par export, ``files`` et ``families``
      sont ceux de ses fichiers lus ;
    - un fichier refusé a été lu ;
    - les exports de ``reference_days`` sont des exports du rapport ; les familles de
      ``window_families`` portent une fenêtre du jour, autre que ``daily_summary`` ;
    - listes en tuples, triées par leur clé, sans doublon ; comptes ``>= 0``.

    Producteur
    ----------
    L'ingestion des jours ; écrit par ``write_days``.

    Consommateurs
    -------------
    L'athlète (``mperf ingest`` en affiche les comptes) ; la vérification de
    l'ingestion ; le contrôle réel d'AN2-1, en comptes.

    Non promis
    ----------
    Aucun instant d'exécution : deux ingestions des mêmes fichiers écrivent le même
    rapport. Aucune valeur ni date tirée des données, hors des noms de fichiers et des
    jours extrêmes de chaque export. Le rapport des activités est à côté
    (``interim/activities/report.json``).
    """

    exports: tuple[DaysExportReport, ...]
    read: tuple[ReadFile, ...]
    refused: tuple[DayFileRefused, ...]
    reference_days: tuple[ExportDayCount, ...]
    window_families: tuple[FamilyDayCount, ...]
    window_mismatches: tuple[FamilyDayCount, ...]
    borrowings: tuple[BorrowingCount, ...]
    borrowing_refusals: tuple[BorrowingRefusalCount, ...]
    comparisons: tuple[ComparisonCount, ...]
    window_edges: tuple[WindowEdgeCount, ...]
    day_boundary_gaps: tuple[DayBoundaryGap, ...]
    copy_disagreements: tuple[CopyDisagreementCount, ...]
    readiness_prior_copies: tuple[ReadinessCopyCount, ...]
    night_equality_violations: int
    point_discards: tuple[PointDiscardCount, ...]
    unknown_codes: tuple[CodeCount, ...]
    unknown_confirmations: tuple[CodeCount, ...]
    naps_overlapping_night: int
    refused_blocks: tuple[BlockCount, ...]
    block_differences_in_export: tuple[BlockFieldCount, ...]
    block_differences_between_exports: tuple[BlockFieldCount, ...]
    blocks_without_proper_instant: tuple[BlockCount, ...]
    readiness_non_primary: int

    def __post_init__(self) -> None:
        for name in _REPORT_LISTS:
            require_immutable_sequence(getattr(self, name), name)
        for name in _REPORT_SCALARS:
            _require_at_least(getattr(self, name), 0, name)
        require_min_length(self.exports, 1, "exports")
        _require_strictly_sorted(
            [(export.retrieved_at,) for export in self.exports],
            "exports (instant d'acquisition)",
        )
        names = [export.name for export in self.exports]
        if len(set(names)) != len(names):
            raise ContractError("exports : nom d'export répété.")
        _require_strictly_sorted([(item.name,) for item in self.read], "read")
        _require_strictly_sorted([(item.name,) for item in self.refused], "refused")
        read_names = {item.name for item in self.read}
        if any(item.name not in read_names for item in self.refused):
            raise ContractError("refused : un fichier refusé doit figurer dans read.")
        files: dict[str, int] = dict.fromkeys(names, 0)
        families: dict[str, set[str]] = {name: set() for name in names}
        for item in self.read:
            parts = item.name.split("/")
            if (
                len(parts) != 4
                or parts[0] != "garmin"
                or parts[1] not in files
                or parts[2] not in _FAMILY_VALUES
            ):
                raise ContractError(
                    "read : un fichier lu se nomme "
                    "garmin/<export>/<famille>/<fichier>, d'un export du rapport et "
                    "d'une famille journalière."
                )
            files[parts[1]] += 1
            families[parts[1]].add(parts[2])
        for export in self.exports:
            if (
                export.files != files[export.name]
                or {family.value for family in export.families} != families[export.name]
            ):
                raise ContractError(
                    "exports : files et families d'un export sont ceux de ses fichiers "
                    "lus."
                )
        _require_strictly_sorted(
            [(count.export,) for count in self.reference_days], "reference_days"
        )
        if any(count.export not in files for count in self.reference_days):
            raise ContractError(
                "reference_days : un export de référence doit être l'un des exports."
            )
        if any(
            count.family not in DAY_WINDOW_FAMILIES
            or count.family is DayFamily.DAILY_SUMMARY
            for count in self.window_families
        ):
            raise ContractError(
                "window_families : une famille qui porte une fenêtre du jour, autre "
                "que daily_summary."
            )
        for name in _SORTED_COUNTS:
            _require_strictly_sorted(
                [_count_key(item) for item in getattr(self, name)], name
            )
