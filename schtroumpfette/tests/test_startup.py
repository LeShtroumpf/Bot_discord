from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import client.errors as errors_module
from client.event import EventListener
from utils.embed import startup_message

SHA = "0123456789abcdef0123456789abcdef01234567"


def test_startup_embed_with_a_commit():
    embed = startup_message.started(SHA)
    assert embed.description == f"🚀 Schtroumpfette démarrée sur [`0123456`](https://github.com/LeShtroumpf/Bot_discord/commit/{SHA})"


@pytest.mark.parametrize("sha", [None, ""])
def test_startup_embed_without_a_commit(sha):
    assert startup_message.started(sha).description == "🚀 Schtroumpfette démarrée (version locale)"


def listener():
    bot = MagicMock(announced=False)
    bot.tree.sync = AsyncMock(return_value=[])
    bot.event_actions.on_ready = AsyncMock()
    bot.logs_channel.send = AsyncMock()
    bot.announce_startup = lambda: EventListener.announce_startup(bot)
    return bot


@pytest.mark.asyncio
async def test_announced_once_per_launch(monkeypatch):
    monkeypatch.setenv("GIT_SHA", SHA)
    bot = listener()
    await EventListener.on_ready(bot)
    await EventListener.on_ready(bot)  # reconnexion : pas de seconde annonce
    bot.logs_channel.send.assert_awaited_once()
    assert "0123456" in bot.logs_channel.send.await_args.kwargs["embed"].description


@pytest.mark.asyncio
async def test_failed_announce_is_reported_and_on_ready_goes_on(monkeypatch):
    monkeypatch.delenv("GIT_SHA", raising=False)
    bot = listener()
    bot.logs_channel.send.side_effect = RuntimeError("refusé")
    with patch.object(errors_module, "report_error", new=AsyncMock()) as report:
        await EventListener.on_ready(bot)
    assert report.await_args.args[2] == "startup"
    assert bot.announced is True
