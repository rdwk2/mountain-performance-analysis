"""Calendrier de Paris : jour civil, origine ``o_j``, disponibilité (``0010`` D0, D2.5).

Instants en UTC dans les calculs, dates civiles en Europe/Paris. Le calendrier —
heure d'été comprise — vient de ``zoneinfo`` et de sa base de fuseaux (``tzdata``
sous Windows) : aucune règle de changement d'heure n'est codée ici.
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from mountain_perf.validation import require_aware

PARIS = ZoneInfo("Europe/Paris")
"""Fuseau des dates civiles du backtest (``0010`` D0)."""

ORIGIN_LAG = timedelta(days=7)
"""Recul de l'origine : ``o_j`` est à 00:00 à Paris du jour civil ``J − 7``
(``0010`` D2.5)."""


def civil_date(instant: datetime) -> date:
    """Jour civil à Paris d'un instant ; un instant naïf lève ``ContractError``."""
    require_aware(instant, "instant")
    return instant.astimezone(PARIS).date()


def origin(day: date) -> datetime:
    """Origine ``o_j`` du jour ``day`` : 00:00 à Paris de ``day − 7 jours``, en UTC."""
    return datetime.combine(day - ORIGIN_LAG, time(0), tzinfo=PARIS).astimezone(UTC)


def available_at_origin(instant: datetime, origin: datetime) -> bool:
    """Une donnée est disponible à ``origin`` si ``instant`` lui est **strictement**
    antérieur (``0010`` D2.5) ; un instant naïf lève ``ContractError``."""
    require_aware(instant, "instant")
    require_aware(origin, "origin")
    return instant < origin
