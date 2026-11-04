"""Récupération du worldstate officiel de Warframe (PC)."""
import datetime as dt
from email.utils import parsedate_to_datetime

import aiohttp

WORLDSTATE_URL = "https://api.warframe.com/cdn/worldState.php"
TIMEOUT = aiohttp.ClientTimeout(total=10)


class WorldstateError(Exception):
    """Worldstate injoignable ou réponse invalide. retry_after : attente demandée par le serveur, s'il en indique une."""

    def __init__(self, message: str, retry_after: dt.timedelta | None = None):
        super().__init__(message)
        self.retry_after = retry_after


def parse_retry_after(value: str | None, now: dt.datetime) -> dt.timedelta | None:
    """En-tête Retry-After : un nombre de secondes ou une date HTTP. None si absent, illisible ou déjà passé."""
    if not value:
        return None
    if value.strip().isdigit():
        return dt.timedelta(seconds=int(value))
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.UTC)
    return when - now if when > now else None


async def fetch_worldstate(session: aiohttp.ClientSession) -> dict:
    try:
        async with session.get(WORLDSTATE_URL, timeout=TIMEOUT) as response:
            response.raise_for_status()
            data = await response.json(content_type=None)
    except aiohttp.ClientResponseError as error:
        retry_after = parse_retry_after((error.headers or {}).get("Retry-After"), dt.datetime.now(dt.UTC))
        raise WorldstateError(f"{type(error).__name__}: {error}", retry_after) from error
    except (aiohttp.ClientError, TimeoutError, ValueError) as error:
        raise WorldstateError(f"{type(error).__name__}: {error}") from error
    if not isinstance(data, dict) or "Time" not in data:
        raise WorldstateError("réponse inattendue (pas de champ Time)")
    return data


def ws_date(value) -> dt.datetime | None:
    """Convertit une date du worldstate ({"$date": {"$numberLong": "…"}}) en datetime UTC."""
    try:
        return dt.datetime.fromtimestamp(int(value["$date"]["$numberLong"]) / 1000, tz=dt.UTC)
    except (KeyError, TypeError, ValueError):
        return None
