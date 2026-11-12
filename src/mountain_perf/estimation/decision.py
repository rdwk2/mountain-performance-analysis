"""La décision de la règle à l'origine sur des instants, et la borne basse de la fenêtre
(OG-2) : du Python pur, sans horloge ni fichier, que la règle (``estimation/origin.py``)
et l'accord du registre (``backtest/registry.py``) appellent ; écrite une fois
(``0020``, précision OG-2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final, Literal
from zoneinfo import ZoneInfo

from mountain_perf.validation import ContractError, require_aware

PARIS: Final = ZoneInfo("Europe/Paris")
"""Le fuseau des origines et des bornes de la fenêtre (``0010`` D0, D2.5)."""

ALL_PAST: Final = "all"
"""La fenêtre « tout le passé », sans date fictive."""

type OriginWindow = int | Literal["all"]
"""Une fenêtre : un nombre entier de jours civils, au moins 1, ou :data:`ALL_PAST`."""


def check_origin(origin: datetime) -> datetime:
    """``origin`` en UTC, après contrôle : un instant à fuseau, minuit à Paris
    (``ContractError`` sinon)."""
    require_aware(origin, "origin")
    local = origin.astimezone(PARIS)
    if (local.hour, local.minute, local.second, local.microsecond) != (0, 0, 0, 0):
        raise ContractError(
            f"origin : 00:00 à Paris attendu, reçu {local.isoformat()} à Paris."
        )
    return origin.astimezone(UTC)


def check_window(window: object) -> None:
    """``window`` : un ``int`` d'au moins 1, non booléen, ou la chaîne ``"all"``
    (``ContractError`` sinon)."""
    if window == ALL_PAST:
        return
    if not isinstance(window, int) or isinstance(window, bool) or window < 1:
        raise ContractError(
            "window : un nombre entier de jours, au moins 1, ou 'all' ; reçu "
            f"{window!r}."
        )


def window_lower_bound(origin: datetime, window: OriginWindow) -> datetime | None:
    """La borne basse de la fenêtre, en UTC : 00:00 à Paris du jour civil de l'origine
    moins ``window`` jours (pas ``window`` × 24 h : la fenêtre traverse les changements
    d'heure) ; ``None`` pour :data:`ALL_PAST`, sans contrôler l'origine."""
    check_window(window)
    if isinstance(window, str):
        return None
    moment = check_origin(origin)
    try:
        day = moment.astimezone(PARIS).date() - timedelta(days=window)
        return datetime(day.year, day.month, day.day, tzinfo=PARIS).astimezone(UTC)
    except OverflowError as error:
        raise ContractError(
            f"window : {window} jours sortent du calendrier depuis l'origine."
        ) from error


class TemporalDecision(StrEnum):
    """Ce que la règle décide d'une activité inspectée."""

    CANDIDATE = "candidate"
    AFTER_ORIGIN = "finie à l'origine ou après"
    BEFORE_WINDOW = "finie avant la fenêtre"
    UNKNOWN_END = "fin inconnue"


def decide_on_index(
    index_end: datetime | None, origin: datetime, lower_bound: datetime | None
) -> TemporalDecision | None:
    """La décision de la règle sur la seule fin de l'index (OG-2) : ``None`` quand
    l'index ne suffit pas et que l'enregistrement doit être lu."""
    if index_end is None:
        return None
    if index_end >= origin:
        return TemporalDecision.AFTER_ORIGIN
    if lower_bound is not None and index_end < lower_bound:
        return TemporalDecision.BEFORE_WINDOW
    return None


def decide_on_safe_end(
    safe_end: datetime | None, origin: datetime, lower_bound: datetime | None
) -> TemporalDecision:
    """La décision de la règle sur la fin sûre, l'enregistrement lu (OG-2)."""
    if safe_end is None:
        return TemporalDecision.UNKNOWN_END
    if safe_end >= origin:
        return TemporalDecision.AFTER_ORIGIN
    if lower_bound is not None and safe_end < lower_bound:
        return TemporalDecision.BEFORE_WINDOW
    return TemporalDecision.CANDIDATE
