import datetime as dt
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from discord.ext import commands

import client.errors as errors_module
from client.errors import ERROR_WINDOW, ErrorReporter, log_errors, report_error
from client.event import EventListener
from utils.embed import error_message


def logs_channel():
    return MagicMock(send=AsyncMock())


@pytest.fixture
def reporter():
    """Instance neuve : l'anti-spam garde un état."""
    return ErrorReporter()


@pytest.mark.asyncio
async def test_error_without_channel_prints_the_real_error(reporter, capsys):
    await reporter.report(ValueError("la vraie erreur"), "test", None)
    assert "[test] la vraie erreur" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_error_report_never_raises(reporter, capsys):
    channel = logs_channel()
    channel.send.side_effect = RuntimeError("salon cassé")
    await reporter.report(ValueError("boum"), "test", channel)
    assert "log impossible : salon cassé" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_error_without_message_shows_its_type(reporter):
    channel = logs_channel()
    await reporter.report(ValueError(), "test", channel)
    assert channel.send.await_args.kwargs["embed"].fields[0].value == "ValueError"


@pytest.mark.asyncio
async def test_repeated_error_is_sent_once_then_counted(reporter, capsys):
    channel = logs_channel()
    for _ in range(4):
        await reporter.report("boum", "test", channel)
    assert channel.send.await_count == 1
    assert capsys.readouterr().out.count("[test] boum") == 4  # la console garde tout

    reporter.errors[("test", "boum")].sent_at -= ERROR_WINDOW
    await reporter.report("boum", "test", channel)
    assert channel.send.await_count == 2
    assert channel.send.await_args.kwargs["embed"].description.endswith("(répétée 3 fois)")


@pytest.mark.asyncio
async def test_different_errors_are_not_grouped(reporter):
    channel = logs_channel()
    await reporter.report("boum", "a", channel)
    await reporter.report("boum", "b", channel)
    await reporter.report("autre", "a", channel)
    assert channel.send.await_count == 3


def test_old_errors_are_forgotten(reporter):
    now = dt.datetime.now(dt.UTC)
    reporter.repeats(("a", "vieille"), now - ERROR_WINDOW)
    reporter.repeats(("b", "récente"), now)
    assert list(reporter.errors) == [("b", "récente")]


@pytest.mark.asyncio
async def test_report_error_uses_the_bot_logs_channel():
    bot = MagicMock()
    with patch.object(errors_module.error_reporter, "report", new=AsyncMock()) as report:
        await report_error(bot, "boum", "origine")
    report.assert_awaited_once_with("boum", "origine", bot.logs_channel)


@pytest.mark.asyncio
async def test_log_errors_on_the_bot():
    @log_errors("mon_event")
    async def handler(self):
        raise ValueError("boum")

    listener = MagicMock()
    with patch.object(errors_module, "report_error", new=AsyncMock()) as report:
        await handler(listener)
    assert report.await_args.args[0] is listener
    assert report.await_args.args[2] == "mon_event"


@pytest.mark.asyncio
async def test_log_errors_on_a_cog_reports_through_its_bot():
    class Cog(commands.Cog):
        def __init__(self, bot):
            self.bot = bot

        @log_errors("listener")
        async def handler(self):
            raise ValueError("boum")

    bot = MagicMock()
    with patch.object(errors_module, "report_error", new=AsyncMock()) as report:
        await Cog(bot).handler()
    assert report.await_args.args[0] is bot


@pytest.mark.asyncio
async def test_twitch_task_error_is_logged():
    listener = MagicMock(stream_channel="1")
    listener.get_channel.side_effect = ValueError("boum")
    with patch.object(errors_module, "report_error", new=AsyncMock()) as report:
        await EventListener.on_post_online_stream.coro(listener)
    assert report.await_args.args[2] == "on_post_online_stream"


@pytest.mark.asyncio
@pytest.mark.parametrize("handler, action, args", [
    ("on_member_join", "on_member_join_action", (MagicMock(),)),
    ("on_voice_state_update", "on_voice_state_update_action", (MagicMock(), MagicMock(), MagicMock())),
])
async def test_actions_errors_are_reported(handler, action, args):
    listener = MagicMock()
    setattr(listener.event_actions, action, AsyncMock(side_effect=RuntimeError("boum")))
    with patch.object(errors_module, "report_error", new=AsyncMock()) as report:
        await getattr(EventListener, handler)(listener, *args)
    assert report.await_args.args[2] == handler


def test_logs_channel_without_config():
    listener = MagicMock(logs_channel_id="")
    listener.get_channel.return_value = None
    assert EventListener.logs_channel.fget(listener) is None


def test_event_listener_has_no_activity_logs():
    """Les logs d'activité sont dans le cog : EventListener ne doit plus les gérer."""
    for name in ("on_raw_message_edit", "on_raw_message_delete", "on_raw_member_remove", "on_member_update"):
        assert name not in vars(EventListener)


def test_error_embed_is_truncated():
    embed = error_message.error("origine", "x" * 2000)
    assert len(embed.fields[0].value) == 1024
    assert error_message.error("origine", "boum", repeats=12).description.endswith("(répétée 12 fois)")


@pytest.mark.asyncio
async def test_gc_task_keeps_the_discord_message_cache():
    listener = MagicMock()
    listener._connection._messages = ["message"]
    await EventListener.gc_task.coro(listener)
    assert listener._connection._messages == ["message"]
