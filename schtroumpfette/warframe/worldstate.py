"""Récupération du worldstate officiel de Warframe (PC)."""
import datetime as dt

import aiohttp

WORLDSTATE_URL = "https://api.warframe.com/cdn/worldState.php"
TIMEOUT = aiohttp.ClientTimeout(total=10)


class WorldstateError(Exception):
    """Worldstate injoignable ou réponse invalide."""


async def fetch_worldstate(session: aiohttp.ClientSession) -> dict:
    try:
        async with session.get(WORLDSTATE_URL, timeout=TIMEOUT) as response:
            response.raise_for_status()
            data = await response.json(content_type=None)
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
