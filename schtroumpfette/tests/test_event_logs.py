from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from client.event import EventListener
from client.event_logs import event_logs


def edit_payload(author_bot: bool, cached: str | None, content: str):
    payload = MagicMock()
    payload.message.author.bot = author_bot
    payload.cached_message = MagicMock(content=cached) if cached is not None else None
    payload.data = {"content": content, "author": {"id": "42"}}
    payload.channel_id = 7
    return payload


@pytest.mark.asyncio
async def test_bot_edits_are_not_logged():
    listener = MagicMock(logs_channel_id="1")
    with patch.object(event_logs, "on_message_edit_log", new=AsyncMock()) as log:
        await EventListener.on_raw_message_edit(listener, edit_payload(author_bot=True, cached=None, content=""))
        log.assert_not_awaited()
        await EventListener.on_raw_message_edit(listener, edit_payload(author_bot=False, cached="a", content="b"))
        log.assert_awaited_once()


@pytest.mark.asyncio
async def test_edit_of_uncached_message_is_logged_without_error():
    channel = MagicMock(send=AsyncMock())
    with patch.object(event_logs, "on_error_log", new=AsyncMock()) as error:
        await event_logs.on_message_edit_log(MagicMock(), payload=edit_payload(False, None, "nouveau"), channel=channel)
    error.assert_not_awaited()
    channel.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_unchanged_text_is_ignored():
    channel = MagicMock(send=AsyncMock())
    await event_logs.on_message_edit_log(MagicMock(), payload=edit_payload(False, "pareil", "pareil"), channel=channel)
    channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_error_log_without_channel_prints_the_real_error(capsys):
    await event_logs.on_error_log(MagicMock(), ValueError("la vraie erreur"), origine="test", channel=None)
    assert "[test] la vraie erreur" in capsys.readouterr().out
