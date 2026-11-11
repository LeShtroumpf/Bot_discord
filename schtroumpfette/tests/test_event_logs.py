import datetime as dt
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from client.event import EventListener, log_errors
from client.event_logs import ERROR_WINDOW, EventLogs, event_logs
from client.message_cache import CachedMessage, MessageCache


def edit_payload(author_bot: bool, cached: str | None, content: str):
    payload = MagicMock()
    payload.message.author.bot = author_bot
    payload.message.author.mention = "<@42>"
    payload.message.content = content
    payload.cached_message = MagicMock(content=cached) if cached is not None else None
    payload.channel_id = 7
    return payload


def logs_channel():
    return MagicMock(send=AsyncMock())


@pytest.fixture
def logs():
    """Instance neuve : l'anti-spam garde un état."""
    return EventLogs()


@pytest.mark.asyncio
async def test_bot_edits_are_not_logged():
    listener = MagicMock(logs_channel_id="1")
    with patch.object(event_logs, "on_message_edit_log", new=AsyncMock()) as log:
        await EventListener.on_raw_message_edit(listener, edit_payload(author_bot=True, cached=None, content=""))
        log.assert_not_awaited()
        await EventListener.on_raw_message_edit(listener, edit_payload(author_bot=False, cached="a", content="b"))
        log.assert_awaited_once()


@pytest.mark.asyncio
async def test_edit_of_a_member_out_of_cache_is_logged(logs):
    """Le bug d'origine : get_user() renvoyait None et le bot envoyait un message vide."""
    bot, channel = MagicMock(), logs_channel()
    bot.get_user.return_value = None
    await logs.on_message_edit_log(bot, payload=edit_payload(False, None, "nouveau"), channel=channel)
    embed = channel.send.await_args.kwargs["embed"]
    assert embed.description == "<@42> a modifié son message dans <#7>."
    assert embed.fields[1].value == "(ancien texte inconnu)"


@pytest.mark.asyncio
async def test_unchanged_text_is_ignored(logs):
    channel = logs_channel()
    await logs.on_message_edit_log(MagicMock(), payload=edit_payload(False, "pareil", "pareil"), channel=channel)
    channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_link_preview_on_an_unedited_message_is_ignored(logs):
    channel = logs_channel()
    payload = edit_payload(False, None, "https://exemple.fr")
    payload.message.edited_at = None
    await logs.on_message_edit_log(MagicMock(), payload=payload, channel=channel)
    channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_join_is_logged_even_if_the_welcome_dm_fails():
    listener = MagicMock()
    listener.event_actions.on_member_join_action = AsyncMock(side_effect=RuntimeError("MP fermés"))
    with patch.object(event_logs, "on_member_join_log", new=AsyncMock()) as log, \
            patch.object(event_logs, "on_error_log", new=AsyncMock()) as error:
        await EventListener.on_member_join(listener, MagicMock())
    log.assert_awaited_once()
    assert error.await_args.kwargs["origine"] == "on_member_join"


@pytest.mark.asyncio
async def test_voice_is_logged_even_if_the_action_fails():
    listener = MagicMock()
    listener.event_actions.on_voice_state_update_action = AsyncMock(side_effect=RuntimeError("boum"))
    with patch.object(event_logs, "on_voice_state_update_log", new=AsyncMock()) as log, \
            patch.object(event_logs, "on_error_log", new=AsyncMock()) as error:
        await EventListener.on_voice_state_update(listener, MagicMock(), MagicMock(), MagicMock())
    log.assert_awaited_once()
    error.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_of_a_cached_message_names_the_author(logs):
    channel = logs_channel()
    payload = MagicMock(channel_id=7, cached_message=MagicMock(content="texte", author=MagicMock(mention="<@42>", bot=False)))
    await logs.on_message_delete_log(MagicMock(), payload=payload, channel=channel)
    assert channel.send.await_args.kwargs["embed"].description == "<@42> a supprimé son message dans <#7>."


@pytest.mark.asyncio
async def test_delete_out_of_cache_is_logged(logs):
    channel = logs_channel()
    await logs.on_message_delete_log(MagicMock(), payload=MagicMock(channel_id=7, cached_message=None), channel=channel)
    assert "auteur et texte inconnus" in channel.send.await_args.kwargs["embed"].description


@pytest.mark.asyncio
async def test_every_role_change_is_logged(logs):
    channel = logs_channel()
    kept, new_a, new_b, lost = (MagicMock(name=f"role{i}") for i in range(4))
    await logs.on_member_update_log(MagicMock(), MagicMock(roles=[kept, lost]), MagicMock(roles=[kept, new_a, new_b]), channel=channel)
    descriptions = [call.kwargs["embed"].description for call in channel.send.await_args_list]
    assert sum("a obtenu le rôle" in d for d in descriptions) == 2
    assert sum("a perdu le rôle" in d for d in descriptions) == 1


@pytest.mark.asyncio
async def test_send_refuses_an_empty_log(logs):
    channel = logs_channel()
    with pytest.raises(ValueError):
        await logs.send(channel, None)
    channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_send_becomes_a_logged_error(logs):
    channel = logs_channel()
    channel.send.side_effect = [RuntimeError("refusé"), None]
    await logs.on_message_delete_log(MagicMock(), payload=MagicMock(channel_id=7, cached_message=None), channel=channel)
    embed = channel.send.await_args.kwargs["embed"]
    assert embed.description == "Error with last event: on_message_delete_log"
    assert embed.fields[0].value == "refusé"


@pytest.mark.asyncio
async def test_missing_logs_channel_goes_to_the_console(logs, capsys):
    await logs.on_message_delete_log(MagicMock(), payload=MagicMock(channel_id=7, cached_message=None), channel=None)
    assert "[on_message_delete_log] salon de logs introuvable" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_error_log_without_channel_prints_the_real_error(logs, capsys):
    await logs.on_error_log(MagicMock(), ValueError("la vraie erreur"), origine="test", channel=None)
    assert "[test] la vraie erreur" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_error_log_never_raises(logs, capsys):
    channel = logs_channel()
    channel.send.side_effect = RuntimeError("salon cassé")
    await logs.on_error_log(MagicMock(), ValueError("boum"), origine="test", channel=channel)
    assert "log impossible : salon cassé" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_error_without_message_shows_its_type(logs):
    channel = logs_channel()
    await logs.on_error_log(MagicMock(), ValueError(), origine="test", channel=channel)
    assert channel.send.await_args.kwargs["embed"].fields[0].value == "ValueError"


@pytest.mark.asyncio
async def test_repeated_error_is_sent_once_then_counted(logs, capsys):
    channel = logs_channel()
    for _ in range(4):
        await logs.on_error_log(MagicMock(), "boum", origine="test", channel=channel)
    assert channel.send.await_count == 1
    assert capsys.readouterr().out.count("[test] boum") == 4  # la console garde tout

    logs.errors[("test", "boum")].sent_at -= ERROR_WINDOW
    await logs.on_error_log(MagicMock(), "boum", origine="test", channel=channel)
    assert channel.send.await_count == 2
    assert channel.send.await_args.kwargs["embed"].description.endswith("(répétée 3 fois)")


@pytest.mark.asyncio
async def test_different_errors_are_not_grouped(logs):
    channel = logs_channel()
    await logs.on_error_log(MagicMock(), "boum", origine="a", channel=channel)
    await logs.on_error_log(MagicMock(), "boum", origine="b", channel=channel)
    await logs.on_error_log(MagicMock(), "autre", origine="a", channel=channel)
    assert channel.send.await_count == 3


def test_old_errors_are_forgotten(logs):
    now = dt.datetime.now(dt.UTC)
    logs.error_repeats(("a", "vieille"), now - ERROR_WINDOW)
    logs.error_repeats(("b", "récente"), now)
    assert list(logs.errors) == [("b", "récente")]


@pytest.mark.asyncio
async def test_log_errors_reports_the_origin():
    @log_errors("mon_event")
    async def handler(self):
        raise ValueError("boum")

    listener = MagicMock()
    with patch.object(event_logs, "on_error_log", new=AsyncMock()) as log:
        await handler(listener)
    assert log.await_args.kwargs == {"origine": "mon_event", "channel": listener.logs_channel}


@pytest.mark.asyncio
async def test_twitch_task_error_is_logged():
    listener = MagicMock(stream_channel="1")
    listener.get_channel.side_effect = ValueError("boum")
    with patch.object(event_logs, "on_error_log", new=AsyncMock()) as log:
        await EventListener.on_post_online_stream.coro(listener)
    assert log.await_args.kwargs["origine"] == "on_post_online_stream"
    assert log.await_args.kwargs["channel"] is listener.logs_channel


def test_logs_channel_without_config():
    listener = MagicMock(logs_channel_id="")
    listener.get_channel.return_value = None
    assert EventListener.logs_channel.fget(listener) is None


def cached(content="vieux texte", bot=False, attachments=()):
    return CachedMessage(author=MagicMock(mention="<@42>", bot=bot), channel_id=7, content=content, attachments=attachments)


@pytest.mark.asyncio
async def test_delete_falls_back_on_the_message_cache(logs):
    channel = logs_channel()
    payload = MagicMock(channel_id=7, cached_message=None)
    await logs.on_message_delete_log(MagicMock(), payload, cached(attachments=("photo.png",)), channel=channel)
    embed = channel.send.await_args.kwargs["embed"]
    assert embed.description == "<@42> a supprimé son message dans <#7>."
    assert [(f.name, f.value) for f in embed.fields] == [("Avant:", "vieux texte"), ("Pièces jointes:", "📎 photo.png")]


@pytest.mark.asyncio
async def test_discord_cache_wins_over_the_message_cache(logs):
    channel = logs_channel()
    message = MagicMock(content="texte discord", author=MagicMock(mention="<@1>", bot=False), attachments=[])
    await logs.on_message_delete_log(MagicMock(), MagicMock(channel_id=7, cached_message=message), cached(), channel=channel)
    embed = channel.send.await_args.kwargs["embed"]
    assert embed.fields[0].value == "texte discord"
    assert len(embed.fields) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("from_discord", [True, False])
async def test_deleted_bot_message_is_not_logged(logs, from_discord):
    channel = logs_channel()
    bot_message = MagicMock(author=MagicMock(bot=True), attachments=[])
    payload = MagicMock(channel_id=7, cached_message=bot_message if from_discord else None)
    await logs.on_message_delete_log(MagicMock(), payload, None if from_discord else cached(bot=True), channel=channel)
    channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_edit_takes_the_previous_text_from_the_message_cache(logs):
    channel = logs_channel()
    await logs.on_message_edit_log(MagicMock(), edit_payload(False, None, "nouveau"), cached("ancien"), channel=channel)
    embed = channel.send.await_args.kwargs["embed"]
    assert [(f.name, f.value) for f in embed.fields] == [("Après:", "nouveau"), ("Avant:", "ancien")]


def listener_with_cache(monkeypatch, entry):
    cache = MessageCache()
    if entry is not None:
        cache.messages[99] = entry
    monkeypatch.setattr("client.event.message_cache", cache)
    return MagicMock(logs_channel_id="1"), cache


@pytest.mark.asyncio
async def test_edit_updates_the_message_cache(monkeypatch):
    listener, cache = listener_with_cache(monkeypatch, cached("v1"))
    payload = edit_payload(False, None, "v2")
    payload.message_id = 99
    seen = []
    log = AsyncMock(side_effect=lambda bot, payload, entry, channel: seen.append(entry.content))
    with patch.object(event_logs, "on_message_edit_log", new=log):
        await EventListener.on_raw_message_edit(listener, payload)
    assert seen == ["v1"]  # le log voit l'ancien texte
    assert cache.get(99).content == "v2"


@pytest.mark.asyncio
async def test_delete_removes_the_entry_and_passes_it_to_the_log(monkeypatch):
    entry = cached()
    listener, cache = listener_with_cache(monkeypatch, entry)
    with patch.object(event_logs, "on_message_delete_log", new=AsyncMock()) as log:
        await EventListener.on_raw_message_delete(listener, MagicMock(message_id=99))
    assert log.await_args.args[2] is entry
    assert cache.get(99) is None


@pytest.mark.asyncio
async def test_gc_task_keeps_the_discord_message_cache():
    listener = MagicMock()
    listener._connection._messages = ["message"]
    await EventListener.gc_task.coro(listener)
    assert listener._connection._messages == ["message"]
