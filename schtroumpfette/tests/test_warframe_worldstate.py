import datetime as dt
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from warframe.worldstate import WORLDSTATE_URL, WorldstateError, fetch_worldstate, parse_retry_after, ws_date

NOW = dt.datetime(2026, 11, 4, 12, 0, tzinfo=dt.UTC)


@pytest.mark.parametrize("value, expected", [
    ("120", dt.timedelta(minutes=2)),
    ("Wed, 04 Nov 2026 12:05:00 GMT", dt.timedelta(minutes=5)),
    ("Wed, 04 Nov 2026 11:55:00 GMT", None),  # déjà passé
    ("bientôt", None),
    ("", None),
    (None, None),
])
def test_parse_retry_after(value, expected):
    assert parse_retry_after(value, NOW) == expected


def session_answering(response) -> MagicMock:
    session = MagicMock()
    session.get.return_value.__aenter__ = AsyncMock(return_value=response)
    session.get.return_value.__aexit__ = AsyncMock(return_value=False)
    return session


@pytest.mark.parametrize("value, expected", [
    ("2026-11-05T08:00:00.000Z", dt.datetime(2026, 11, 5, 8, 0, tzinfo=dt.UTC)),
    ("+275760-09-13T00:00:00.000Z", None),  # date hors limites envoyée par l'API
    ("bientôt", None),
    (None, None),
])
def test_ws_date(value, expected):
    assert ws_date(value) == expected


@pytest.mark.asyncio
async def test_fetch_uses_the_french_path():
    response = MagicMock()
    response.json = AsyncMock(return_value={"timestamp": "2026-11-05T08:00:00.000Z"})
    session = session_answering(response)
    assert await fetch_worldstate(session) == {"timestamp": "2026-11-05T08:00:00.000Z"}
    assert WORLDSTATE_URL.endswith("/pc/fr/")
    assert session.get.call_args.args == (WORLDSTATE_URL,)


@pytest.mark.asyncio
async def test_fetch_rejects_an_unexpected_answer():
    response = MagicMock()
    response.json = AsyncMock(return_value={"Time": 1})
    with pytest.raises(WorldstateError, match="timestamp"):
        await fetch_worldstate(session_answering(response))


@pytest.mark.asyncio
async def test_fetch_forbidden_is_reported():
    response = MagicMock()
    response.raise_for_status.side_effect = aiohttp.ClientResponseError(MagicMock(), (), status=403, message="Forbidden")
    with pytest.raises(WorldstateError, match="403"):
        await fetch_worldstate(session_answering(response))


@pytest.mark.asyncio
async def test_fetch_rate_limited_exposes_retry_after():
    response = MagicMock()
    response.raise_for_status.side_effect = aiohttp.ClientResponseError(
        MagicMock(), (), status=429, message="Too Many Requests", headers={"Retry-After": "300"})
    with pytest.raises(WorldstateError) as error:
        await fetch_worldstate(session_answering(response))
    assert error.value.retry_after == dt.timedelta(minutes=5)
    assert "429" in str(error.value)


@pytest.mark.asyncio
async def test_fetch_network_error_has_no_retry_after():
    session = MagicMock()
    session.get.side_effect = aiohttp.ClientConnectionError("down")
    with pytest.raises(WorldstateError) as error:
        await fetch_worldstate(session)
    assert error.value.retry_after is None
