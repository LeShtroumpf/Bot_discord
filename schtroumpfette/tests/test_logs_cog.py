import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

import commands.logs as cog_module
from commands.logs import Logs
from logs.cache import CachedMessage, MessageCache
from logs.render import InviteUse

Action = discord.AuditLogAction


def user(user_id=42, bot=False, mention=None):
    u = MagicMock(id=user_id, bot=bot, mention=mention or f"<@{user_id}>")
    u.__str__.return_value = f"user{user_id}"
    return u


def entry(action, target, moderator=None, reason="raison", count=1, channel=None):
    e = MagicMock(action=action, reason=reason, user=moderator or user(99), created_at=discord.utils.utcnow())
    e.target = MagicMock(id=target)
    e.extra = MagicMock(count=count)
    e.extra.channel = MagicMock(id=channel) if channel is not None else None
    return e


@pytest.fixture
def channel():
    log_message = MagicMock(edit=AsyncMock())
    return MagicMock(send=AsyncMock(return_value=log_message))


@pytest.fixture
def cog(channel):
    bot = MagicMock(logs_channel=channel, guilds=[])
    c = Logs(bot)
    c.cache = MessageCache()
    c.audit.wait = 0  # pas d'attente d'entrée d'audit dans les tests
    return c


def sent(channel):
    return [call.kwargs["embed"].description for call in channel.send.await_args_list]


@pytest.fixture
def report():
    with patch.object(cog_module, "report_error", new=AsyncMock()) as mock:
        yield mock


# --- Configuration -----------------------------------------------------------------------------------------

def test_read_settings(cog, settings_file, monkeypatch):
    values = {
        "dict_chan": {"logs_channel": "1"},
        "warframe": {"info_channel": "2"},
        "voice_allow_list_channel": {"lobby": "10"},
        "static_voice_channel": {"afk": "11", "modele": "voice_channel_id", "vide": ""},
    }
    monkeypatch.setattr(cog_module.settings_file_management, "get_entry", lambda main_key: values[main_key])
    cog.read_settings()
    assert cog.cache.excluded == {1, 2}
    assert cog.permanent_voice == {10, 11}


def test_read_settings_without_optional_sections(cog, monkeypatch):
    def get_entry(main_key):
        raise KeyError(main_key)
    monkeypatch.setattr(cog_module.settings_file_management, "get_entry", get_entry)
    cog.read_settings()
    assert cog.cache.excluded == set() and cog.permanent_voice == set()
    assert (cog.step_timeout, cog.cache.history_timeout) == (60, 15)  # délais par défaut


@pytest.mark.parametrize("config, expected", [
    ({"step_timeout": 90, "history_timeout": 2.5}, (90, 2.5)),
    ({"step_timeout": 0, "history_timeout": -3}, (60, 15)),
    ({"step_timeout": "30", "history_timeout": True}, (60, 15)),
    ({}, (60, 15)),
], ids=["valeurs", "non positives", "pas des nombres", "clés absentes"])
def test_read_settings_timeouts(cog, monkeypatch, config, expected):
    monkeypatch.setattr(cog_module.settings_file_management, "get_entry", lambda main_key: config if main_key == "logs" else {})
    cog.read_settings()
    assert (cog.step_timeout, cog.cache.history_timeout) == expected


def test_example_settings_have_the_default_timeouts():
    import json
    from pathlib import Path
    example = json.loads((Path(__file__).resolve().parents[1] / "settings.example.json").read_text(encoding="utf-8"))
    assert example["logs"] == {"history_timeout": cog_module.HISTORY_TIMEOUT, "step_timeout": cog_module.STEP_TIMEOUT}


def test_temp_voice(cog):
    cog.permanent_voice = {10}
    assert cog.is_temp_voice(MagicMock(spec=discord.VoiceChannel, id=12))
    assert not cog.is_temp_voice(MagicMock(spec=discord.VoiceChannel, id=10))
    assert not cog.is_temp_voice(MagicMock(spec=discord.TextChannel, id=12))


@pytest.mark.asyncio
async def test_send_without_logs_channel_raises(cog):
    cog.bot.logs_channel = None
    with pytest.raises(LookupError):
        await cog.send(MagicMock())


# --- Chargement --------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_on_ready_reloads_but_never_twice_at_once(cog):
    started = []

    async def fake_load():
        started.append(True)
        await asyncio.sleep(0.01)
    cog.load = fake_load
    await cog.on_ready()
    await cog.on_ready()  # chargement en cours : rien
    await cog.load_task
    await cog.on_ready()  # reconnexion complète : on recharge
    await cog.load_task
    assert len(started) == 2


@pytest.mark.asyncio
async def test_load_reports_each_failing_step_and_goes_on(cog, report, monkeypatch):
    monkeypatch.setattr(cog, "read_settings", lambda: None)
    guild = MagicMock(chunk=AsyncMock())
    cog.bot.guilds = [guild]
    cog.invites.load = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "non"))
    cog.audit.load_baseline = AsyncMock()
    cog.cache.load = AsyncMock(return_value=(3, 2, ["<#5> (RuntimeError: a)"]))
    await cog.load()
    origins = [call.args[2] for call in report.await_args_list]
    assert origins == ["logs_invites", "message_cache"]
    assert report.await_args_list[0].args[1] == cog_module.MISSING_INVITES
    cog.audit.load_baseline.assert_awaited_once_with(guild)
    guild.chunk.assert_not_called()  # membres déjà chargés par discord.py, et une seconde demande ne répond jamais


@pytest.mark.asyncio
async def test_blocked_step_is_abandoned_and_the_next_ones_run(cog, report, monkeypatch, capsys):
    monkeypatch.setattr(cog, "read_settings", lambda: None)
    cog.step_timeout = 0.01
    cog.bot.guilds = [MagicMock()]

    async def never_answers(guild):
        await asyncio.Event().wait()
    cog.invites.load = never_answers
    cog.audit.load_baseline = AsyncMock()
    cog.cache.load = AsyncMock(return_value=(4, 2, []))
    await cog.load()
    assert report.await_args.args[1:] == ("étape bloquée plus de 0.01 s, abandonnée", "logs_invites")
    cog.audit.load_baseline.assert_awaited_once()
    assert "[cache] 4 messages chargés depuis 2 salons" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_cache_load_has_no_global_timeout(cog, report, monkeypatch, capsys):
    monkeypatch.setattr(cog, "read_settings", lambda: None)
    cog.step_timeout = 0.01

    async def slow_but_fine(guilds):
        await asyncio.sleep(0.05)  # plus long que step_timeout : seul le délai par salon compte
        return (5, 3, [])
    cog.cache.load = slow_but_fine
    await cog.load()
    report.assert_not_awaited()
    assert "[cache] 5 messages chargés depuis 3 salons" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_failed_cache_load_is_reported_once(cog, report, monkeypatch, capsys):
    monkeypatch.setattr(cog, "read_settings", lambda: None)
    cog.cache.load = AsyncMock(side_effect=RuntimeError("API en panne"))
    await cog.load()
    assert [call.args[2] for call in report.await_args_list] == ["message_cache"]
    assert "[cache]" not in capsys.readouterr().out


# --- Messages ----------------------------------------------------------------------------------------------

def edit_payload(content, cached=None, author_bot=False, edited=True):
    payload = MagicMock(message_id=99, channel_id=7, cached_message=MagicMock(content=cached) if cached is not None else None)
    payload.message.author = user(bot=author_bot)
    payload.message.content = content
    payload.message.edited_at = MagicMock() if edited else None
    return payload


@pytest.mark.asyncio
async def test_bot_edits_are_not_logged(cog, channel):
    await cog.on_raw_message_edit(edit_payload("b", "a", author_bot=True))
    channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_edit_takes_the_previous_text_from_the_cache_then_updates_it(cog, channel):
    cog.cache.messages[99] = CachedMessage(author=user(), channel_id=7, content="v1")
    await cog.on_raw_message_edit(edit_payload("v2"))
    embed = channel.send.await_args.kwargs["embed"]
    assert [(f.name, f.value) for f in embed.fields] == [("Après:", "v2"), ("Avant:", "v1")]
    assert cog.cache.get(99).content == "v2"


@pytest.mark.asyncio
async def test_edit_without_change_or_link_preview_is_ignored(cog, channel):
    await cog.on_raw_message_edit(edit_payload("pareil", "pareil"))
    await cog.on_raw_message_edit(edit_payload("https://exemple.fr", edited=False))
    channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_edit_of_unknown_message(cog, channel):
    await cog.on_raw_message_edit(edit_payload("nouveau"))
    assert channel.send.await_args.kwargs["embed"].fields[1].value == "(ancien texte inconnu)"


def delete_payload(cached_message=None):
    return MagicMock(message_id=99, channel_id=7, guild_id=None, cached_message=cached_message)


@pytest.mark.asyncio
async def test_delete_unknown(cog, channel):
    await cog.on_raw_message_delete(delete_payload())
    assert "auteur et texte inconnus" in sent(channel)[0]


@pytest.mark.asyncio
async def test_delete_from_the_cache_with_attachments(cog, channel):
    cog.cache.messages[99] = CachedMessage(author=user(), channel_id=7, content="texte", attachments=("a.png",))
    await cog.on_raw_message_delete(delete_payload())
    embed = channel.send.await_args.kwargs["embed"]
    assert embed.description == "<@42> a supprimé son message dans <#7>."
    assert embed.fields[1].value == "📎 a.png"
    assert cog.cache.get(99) is None
    channel.send.return_value.edit.assert_not_awaited()


@pytest.mark.asyncio
async def test_discord_cache_wins_over_the_message_cache(cog, channel):
    cog.cache.messages[99] = CachedMessage(author=user(), channel_id=7, content="vieux")
    await cog.on_raw_message_delete(delete_payload(MagicMock(content="discord", author=user(), attachments=[])))
    assert channel.send.await_args.kwargs["embed"].fields[0].value == "discord"


@pytest.mark.asyncio
async def test_deleted_bot_message_is_not_logged(cog, channel):
    await cog.on_raw_message_delete(delete_payload(MagicMock(author=user(bot=True), attachments=[])))
    channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_by_a_moderator_edits_the_log(cog, channel):
    cog.cache.messages[99] = CachedMessage(author=user(), channel_id=7, content="texte")
    await cog.audit.add(entry(Action.message_delete, 42, channel=7))
    await cog.on_raw_message_delete(delete_payload())
    assert sent(channel) == ["<@42> a supprimé son message dans <#7>."]  # envoyé tout de suite
    edited = channel.send.return_value.edit.await_args.kwargs["embed"]
    assert edited.description == "Message de <@42> supprimé par <@99> dans <#7>."


@pytest.mark.asyncio
async def test_delete_without_audit_permission(cog, channel, report):
    cog.cache.messages[99] = CachedMessage(author=user(), channel_id=7, content="texte")
    cog.audit.message_delete_moderator = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "non"))
    await cog.on_raw_message_delete(delete_payload())
    assert len(sent(channel)) == 1
    assert report.await_args.args[1] == cog_module.MISSING_AUDIT


@pytest.mark.asyncio
async def test_bulk_delete_with_known_messages(cog, channel):
    cog.cache.messages[2] = CachedMessage(author=user(), channel_id=7, content="deux", message_id=2)
    cog.cache.messages[3] = CachedMessage(author=user(bot=True), channel_id=7, content="bot", message_id=3)
    discord_cached = MagicMock(id=1, content="un", author=user(), attachments=[])
    await cog.audit.add(entry(Action.message_bulk_delete, 7))
    payload = MagicMock(channel_id=7, message_ids={1, 2, 3, 4}, cached_messages=[discord_cached])
    await cog.on_raw_bulk_message_delete(payload)
    call = channel.send.await_args
    assert call.kwargs["embed"].description == "🧹 4 messages supprimés dans <#7> par <@99>.\nDont 2 connus : voir le fichier joint."
    assert call.kwargs["file"].filename == "messages-supprimes.txt"
    assert len(cog.cache) == 0


@pytest.mark.asyncio
async def test_bulk_delete_without_known_messages_has_no_file(cog, channel):
    await cog.on_raw_bulk_message_delete(MagicMock(channel_id=7, message_ids={1}, cached_messages=[]))
    assert "file" not in channel.send.await_args.kwargs


@pytest.mark.asyncio
async def test_on_message_feeds_the_cache(cog):
    message = MagicMock(id=1, content="coucou", attachments=[])
    message.author.bot = False
    await cog.on_message(message)
    assert cog.cache.get(1).content == "coucou"


# --- Membres -----------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_join_with_invite(cog, channel):
    cog.invites.used_on_join = AsyncMock(return_value=InviteUse("abc", user(7), 3))
    member = user()
    member.created_at = discord.utils.utcnow()
    await cog.on_member_join(member)
    fields = {f.name: f.value for f in channel.send.await_args.kwargs["embed"].fields}
    assert fields["Invitation:"] == "`abc` de <@7> (3 utilisations)"


@pytest.mark.asyncio
async def test_join_without_invites_permission(cog, channel, report):
    cog.invites.used_on_join = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "non"))
    member = user()
    member.created_at = discord.utils.utcnow()
    await cog.on_member_join(member)
    assert len(sent(channel)) == 1
    assert report.await_args.args[1] == cog_module.MISSING_INVITES


@pytest.mark.asyncio
async def test_member_remove_leave_kick_ban(cog, channel):
    await cog.on_raw_member_remove(MagicMock(user=user(1)))
    await cog.audit.add(entry(Action.kick, 2, reason="spam"))
    await cog.on_raw_member_remove(MagicMock(user=user(2)))
    await cog.audit.add(entry(Action.ban, 3))
    await cog.on_raw_member_remove(MagicMock(user=user(3)))
    assert sent(channel) == ["<@1> a quitté le serveur.", "<@2> a été exclu par <@99>."]


@pytest.mark.asyncio
async def test_ban_and_unban(cog, channel):
    await cog.audit.add(entry(Action.ban, 3, reason="relou"))
    await cog.on_member_ban(MagicMock(), user(3))
    await cog.on_member_unban(MagicMock(), user(3))  # pas d'entrée : sans modo
    assert sent(channel) == ["<@3> a été banni par <@99>.", "<@3> a été débanni."]
    assert channel.send.await_args_list[0].kwargs["embed"].fields[0].value == "relou"


@pytest.mark.asyncio
async def test_member_update_roles_and_nick(cog, channel):
    kept, new = MagicMock(), MagicMock()
    new.name = "Nouveau"
    before = MagicMock(roles=[kept], nick=None)
    after = user()
    after.roles, after.nick = [kept, new], "Toto"
    await cog.on_member_update(before, after)
    assert sent(channel) == ["<@42> a obtenu le rôle Nouveau", "<@42> a changé de surnom : **(aucun)** → **Toto**"]


@pytest.mark.asyncio
async def test_user_update(cog, channel):
    before = MagicMock(global_name="Toto")
    before.name = "toto"
    after = user()
    after.name, after.global_name = "tata", "Toto"
    await cog.on_user_update(before, after)
    assert sent(channel) == ["<@42> a changé de nom d'utilisateur : **toto** → **tata**"]


@pytest.mark.asyncio
async def test_voice_temp_channel_has_no_mention(cog, channel):
    cog.permanent_voice = {1}
    lobby = MagicMock(spec=discord.VoiceChannel, id=1, mention="<#1>")
    temp = MagicMock(spec=discord.VoiceChannel, id=2, mention="<#2>")
    lobby.name, temp.name = "Lobby", "Salon de Toto"
    await cog.on_voice_state_update(user(), MagicMock(channel=lobby), MagicMock(channel=temp))
    assert sent(channel) == ["<@42> a switch de vocal **🔊 Lobby** (<#1>) -> **🔊 Salon de Toto**"]


@pytest.mark.asyncio
async def test_voice_same_channel_is_ignored(cog, channel):
    same = MagicMock(id=1)
    await cog.on_voice_state_update(user(), MagicMock(channel=same), MagicMock(channel=same))
    channel.send.assert_not_awaited()


# --- Serveur -----------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_temp_voice_channels_are_not_logged(cog, channel):
    temp = MagicMock(spec=discord.VoiceChannel, id=12)
    await cog.on_guild_channel_create(temp)
    await cog.on_guild_channel_delete(temp)
    channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_channel_and_role_logs_name_the_moderator(cog, channel):
    text = MagicMock(spec=discord.TextChannel, id=5, mention="<#5>", type=discord.ChannelType.text)
    text.name = "général"
    await cog.audit.add(entry(Action.channel_create, 5))
    await cog.on_guild_channel_create(text)
    await cog.on_guild_channel_delete(text)
    role = MagicMock(id=6, mention="<@&6>")
    role.name = "Modo"
    await cog.audit.add(entry(Action.role_delete, 6))
    await cog.on_guild_role_create(role)
    await cog.on_guild_role_delete(role)
    assert sent(channel) == [
        "Salon **général** (<#5>, texte) créé par <@99>.",
        "Salon **général** (texte) supprimé.",
        "Rôle **Modo** (<@&6>) créé.",
        "Rôle **Modo** supprimé par <@99>.",
    ]


@pytest.mark.asyncio
async def test_invites(cog, channel):
    invite = MagicMock(code="abc", inviter=user(), max_age=0, max_uses=1, uses=0)
    invite.channel.mention = "<#5>"
    invite.channel.name = "général"
    await cog.on_invite_create(invite)
    assert "abc" in cog.invites.invites
    await cog.on_invite_delete(invite)  # dernière utilisation, pas d'entrée d'audit : épuisée
    await cog.audit.add(entry(Action.invite_delete, "xyz"))
    other = MagicMock(code="xyz")
    other.channel.name = "général"
    await cog.on_invite_delete(other)
    assert sent(channel)[1:] == ["Invitation **abc** épuisée.", "Invitation **xyz** pour **#général** supprimée par <@99>."]


@pytest.mark.asyncio
async def test_failed_send_is_reported_with_the_listener_name(cog, channel):
    channel.send.side_effect = RuntimeError("refusé")
    with patch("client.errors.report_error", new=AsyncMock()) as report:
        await cog.on_raw_message_delete(delete_payload())
    assert report.await_args.args[1].args[0] == "refusé"
    assert report.await_args.args[2] == "on_raw_message_delete"
