import asyncio
import datetime as dt
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from client.event import EventListener
from client.event_logs import event_logs
from client.message_cache import HISTORY_PER_CHANNEL, MessageCache

T0 = dt.datetime(2026, 11, 11, 16, 52, tzinfo=dt.UTC)


def channel(channel_id, history=(), *, allowed=True, error=None):
    """Salon simulé : history() rend les messages donnés (ou lève error), permissions_for selon allowed."""
    c = MagicMock(id=channel_id, mention=f"<#{channel_id}>")
    c.permissions_for.return_value = MagicMock(view_channel=allowed, read_message_history=allowed)
    c.limits = []

    def history_call(limit):
        c.limits.append(limit)

        async def iterate():
            if error is not None:
                raise error
            for message in history:
                yield message
        return iterate()
    c.history = history_call
    return c


def message(message_id, channel_id=10, *, bot=False, content="salut", attachments=(), guild=True, minutes=0, thread_parent=None):
    if thread_parent is not None:
        chan = MagicMock(spec=discord.Thread, id=channel_id, parent_id=thread_parent)
    else:
        chan = MagicMock(id=channel_id)
    return MagicMock(
        id=message_id, channel=chan, content=content, guild=MagicMock() if guild else None,
        author=MagicMock(bot=bot), attachments=[MagicMock(filename=name) for name in attachments],
        created_at=T0 + dt.timedelta(minutes=minutes),
    )


def guild(text=(), voice=()):
    return MagicMock(text_channels=list(text), voice_channels=list(voice))


def test_add_keeps_author_channel_text_and_attachment_names():
    cache = MessageCache()
    msg = message(1, content="regarde", attachments=("photo.png", "son.mp3"))
    assert cache.add(msg)
    entry = cache.get(1)
    assert (entry.author, entry.channel_id, entry.content, entry.attachments) == (msg.author, 10, "regarde", ("photo.png", "son.mp3"))


@pytest.mark.parametrize("msg", [
    message(1, bot=True),
    message(1, guild=False),
    message(1, channel_id=666),
    message(1, channel_id=50, thread_parent=666),
], ids=["bot", "hors serveur", "salon exclu", "fil d'un salon exclu"])
def test_add_ignores(msg):
    cache = MessageCache()
    cache.excluded = {666}
    assert not cache.add(msg)
    assert len(cache) == 0


def test_thread_of_a_normal_channel_is_cached():
    cache = MessageCache()
    cache.excluded = {666}
    assert cache.add(message(1, channel_id=50, thread_parent=10))
    assert cache.get(1).channel_id == 50


def test_oldest_message_leaves_when_full():
    cache = MessageCache(max_messages=3)
    for i in range(5):
        cache.add(message(i))
    assert list(cache.messages) == [2, 3, 4]


def test_same_id_is_not_duplicated():
    cache = MessageCache()
    cache.add(message(1, content="a"))
    cache.add(message(1, content="b"))
    assert len(cache) == 1
    assert cache.get(1).content == "b"
    assert not cache.add(message(1, content="c"), replace=False)
    assert cache.get(1).content == "b"


def test_update_and_pop():
    cache = MessageCache()
    cache.add(message(1, content="avant"))
    cache.update_content(1, "après")
    cache.update_content(2, "rien")  # absent : sans effet
    assert cache.get(1).content == "après"
    assert cache.get(2) is None
    assert cache.pop(1).content == "après"
    assert cache.pop(1) is None


@pytest.mark.asyncio
async def test_load_reads_the_last_messages_of_text_and_voice_channels():
    cache = MessageCache()
    text = channel(10, [message(2, 10, minutes=2), message(1, 10, minutes=1)])
    voice = channel(20, [message(3, 20, minutes=3), message(4, 20, bot=True, minutes=4)])
    added, channels, failures = await cache.load([guild([text], [voice])])
    assert (added, channels, failures) == (3, 2, [])
    assert list(cache.messages) == [1, 2, 3]  # ordre chronologique, sans le bot
    assert text.limits == voice.limits == [HISTORY_PER_CHANNEL]


@pytest.mark.asyncio
async def test_load_skips_excluded_and_forbidden_channels_silently():
    cache = MessageCache()
    cache.excluded = {30}
    excluded = channel(30, [message(1, 30)])
    no_permission = channel(31, [message(2, 31)], allowed=False)
    forbidden = channel(32, error=discord.Forbidden(MagicMock(status=403), "non"))
    ok = channel(33, [message(3, 33)])
    added, channels, failures = await cache.load([guild([excluded, no_permission, forbidden, ok])])
    assert (added, channels, failures) == (1, 1, [])
    assert excluded.limits == no_permission.limits == []


@pytest.mark.asyncio
async def test_load_failure_does_not_stop_other_channels():
    cache = MessageCache()
    broken = channel(40, error=RuntimeError("API en panne"))
    ok = channel(41, [message(1, 41)])
    added, channels, failures = await cache.load([guild([broken, ok])])
    assert (added, channels) == (1, 1)
    assert failures == ["<#40> (RuntimeError: API en panne)"]


@pytest.mark.asyncio
async def test_load_does_not_overwrite_a_live_message():
    cache = MessageCache()
    cache.add(message(1, content="modifié en direct"))
    added, _, _ = await cache.load([guild([channel(10, [message(1, content="historique"), message(2)])])])
    assert added == 1
    assert cache.get(1).content == "modifié en direct"


def listener(settings_warframe=None, logs_channel_id="5"):
    bot = MagicMock(logs_channel_id=logs_channel_id, guilds=[], message_cache_task=None)
    bot.message_cache_excluded = lambda: EventListener.message_cache_excluded(bot)
    bot.load_message_cache = lambda: EventListener.load_message_cache(bot)
    return bot


def test_excluded_channels_are_logs_and_warframe_info(monkeypatch):
    monkeypatch.setattr("client.event.settings_file_management.get_entry", lambda main_key: {"info_channel": "7"})
    assert EventListener.message_cache_excluded(listener()) == {5, 7}


def test_excluded_without_warframe_section(monkeypatch):
    def missing(main_key):
        raise KeyError(main_key)
    monkeypatch.setattr("client.event.settings_file_management.get_entry", missing)
    assert EventListener.message_cache_excluded(listener()) == {5}


@pytest.mark.asyncio
async def test_load_failures_are_reported_once(monkeypatch):
    cache = MessageCache()
    monkeypatch.setattr("client.event.message_cache", cache)
    monkeypatch.setattr("client.event.settings_file_management.get_entry", lambda main_key: {})
    bot = listener()
    bot.guilds = [guild([channel(1, error=RuntimeError("a")), channel(2, error=RuntimeError("b"))])]
    with patch.object(event_logs, "on_error_log", new=AsyncMock()) as error:
        await EventListener.load_message_cache(bot)
    error.assert_awaited_once()
    assert "2 salon(s) ignoré(s)" in error.await_args.args[1]
    assert error.await_args.kwargs["origine"] == "message_cache"


@pytest.mark.asyncio
async def test_on_ready_reloads_but_never_twice_at_once(monkeypatch):
    bot = listener()
    started = []

    async def fake_load():
        started.append(True)
        await asyncio.sleep(0.01)
    bot.load_message_cache = fake_load

    EventListener.start_message_cache_load(bot)
    EventListener.start_message_cache_load(bot)  # chargement en cours : rien
    await bot.message_cache_task
    EventListener.start_message_cache_load(bot)  # reconnexion complète : on recharge
    await bot.message_cache_task
    assert len(started) == 2


@pytest.mark.asyncio
async def test_on_message_feeds_the_cache(monkeypatch):
    cache = MessageCache()
    monkeypatch.setattr("client.event.message_cache", cache)
    bot = MagicMock(voice_clients=[])
    msg = message(1)
    msg.content = "coucou"
    await EventListener.on_message(bot, msg)
    assert cache.get(1).content == "coucou"
