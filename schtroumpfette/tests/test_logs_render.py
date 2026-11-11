import datetime as dt
from unittest.mock import MagicMock

import pytest

import discord

from logs.cache import CachedMessage
from logs.render import InviteUse, channel_type, duration_text, render as logs_message


def user_without_photo():
    """Comme discord.py : avatar à None, display_avatar donne l'avatar par défaut."""
    user = MagicMock(mention="<@1>", avatar=None, created_at=dt.datetime(2020, 1, 1, tzinfo=dt.UTC))
    user.__str__.return_value = "Toto"
    user.display_avatar.url = "https://cdn.discordapp.com/embed/avatars/0.png"
    return user


def voice_state(channel=None):
    return MagicMock(channel=channel)


@pytest.mark.parametrize("build", [
    lambda u: logs_message.edit(u, 7, "avant", "après"),
    lambda u: logs_message.delete(u, 7, "texte"),
    lambda u: logs_message.join(u),
    lambda u: logs_message.leave(u),
    lambda u: logs_message.role_added(u, MagicMock()),
    lambda u: logs_message.role_removed(u, MagicMock()),
    lambda u: logs_message.voice(u, voice_state(), voice_state(MagicMock(mention="#vocal"))),
])
def test_user_without_photo_gets_the_default_avatar(build):
    embed = build(user_without_photo())
    assert embed.author.icon_url == "https://cdn.discordapp.com/embed/avatars/0.png"
    assert embed.author.name == "Toto"


def test_edit_with_unknown_previous_text():
    embed = logs_message.edit(user_without_photo(), 7, None, "nouveau")
    assert [(f.name, f.value) for f in embed.fields] == [("Après:", "nouveau"), ("Avant:", "(ancien texte inconnu)")]
    assert "<#7>" in embed.description


def test_message_without_text():
    assert logs_message.edit(user_without_photo(), 7, "", "").fields[0].value == "(pas de texte)"
    assert logs_message.delete(user_without_photo(), 7, "").fields[0].value == "(pas de texte)"


def test_long_text_is_cut():
    value = logs_message.delete(user_without_photo(), 7, "a" * 4000).fields[0].value
    assert len(value) == 1024
    assert value.endswith("…")


def test_delete_unknown_has_no_author():
    embed = logs_message.delete_unknown(7)
    assert embed.description == "Un message a été supprimé dans <#7> (auteur et texte inconnus)."
    assert embed.author.name is None


def test_voice_states_name_the_channel_that_may_be_gone():
    a, b = MagicMock(mention="#a"), MagicMock(mention="#b")
    a.name = "Salon de Toto"
    user = user_without_photo()
    assert "a rejoint le vocal #a" in logs_message.voice(user, voice_state(), voice_state(a)).description
    assert "a quitté le vocal **🔊 Salon de Toto**" in logs_message.voice(user, voice_state(a), voice_state()).description
    assert "a switch de vocal **🔊 Salon de Toto** -> #b" in logs_message.voice(user, voice_state(a), voice_state(b)).description


def test_delete_lists_attachments_only_when_there_are_some():
    assert [f.name for f in logs_message.delete(user_without_photo(), 7, "texte").fields] == ["Avant:"]
    embed = logs_message.delete(user_without_photo(), 7, "", ("a.png", "b.mp4"))
    assert [(f.name, f.value) for f in embed.fields] == [("Avant:", "(pas de texte)"), ("Pièces jointes:", "📎 a.png\n📎 b.mp4")]


def test_delete_truncates_a_long_attachment_list():
    embed = logs_message.delete(user_without_photo(), 7, "texte", tuple(f"fichier_{i}.png" for i in range(200)))
    assert len(embed.fields[1].value) == logs_message.FIELD_MAX


def moderator():
    return MagicMock(mention="<@99>")


def test_delete_by_a_moderator():
    embed = logs_message.delete(user_without_photo(), 7, "texte", moderator=moderator())
    assert embed.description == "Message de <@1> supprimé par <@99> dans <#7>."


def test_bulk_delete():
    assert logs_message.bulk_delete(7, 12, 0, moderator()).description == "🧹 12 messages supprimés dans <#7> par <@99>."
    assert logs_message.bulk_delete(7, 12, 3).description == "🧹 12 messages supprimés dans <#7>.\nDont 3 connus : voir le fichier joint."


def test_bulk_file_lists_messages_oldest_first():
    def cached(message_id, text, attachments=()):
        author = MagicMock()
        author.__str__.return_value = "Toto"
        return CachedMessage(author=author, channel_id=7, content=text, attachments=attachments, message_id=message_id)
    newer = discord.utils.time_snowflake(dt.datetime(2026, 11, 11, 15, 0, tzinfo=dt.UTC))
    older = discord.utils.time_snowflake(dt.datetime(2026, 11, 11, 14, 0, tzinfo=dt.UTC))
    file = logs_message.bulk_file([cached(newer, "deux", ("a.png",)), cached(older, "un")])
    assert file.filename == "messages-supprimes.txt"
    lines = file.fp.read().decode().splitlines()
    assert lines[0].endswith("] Toto : un")
    assert lines[1].endswith("] Toto : deux 📎 a.png")
    assert lines[0].startswith("[11/11 ")


@pytest.mark.parametrize("build, description", [
    (lambda u, m: logs_message.kick(u, m, "spam"), "<@1> a été exclu par <@99>."),
    (lambda u, m: logs_message.ban(u, m, None), "<@1> a été banni par <@99>."),
    (lambda u, m: logs_message.unban(u, None, None), "<@1> a été débanni."),
])
def test_sanctions(build, description):
    embed = build(user_without_photo(), moderator())
    assert embed.description == description
    assert embed.fields[0].name == "Raison:"


def test_sanction_reason():
    assert logs_message.kick(user_without_photo(), None, "spam").fields[0].value == "spam"
    assert logs_message.ban(user_without_photo(), None, None).fields[0].value == "(pas de raison)"


def test_renames():
    user = user_without_photo()
    assert logs_message.nick(user, None, "Toto").description == "<@1> a changé de surnom : **(aucun)** → **Toto**"
    assert logs_message.username(user, "toto", "tata").description == "<@1> a changé de nom d'utilisateur : **toto** → **tata**"
    assert logs_message.display_name(user, "Toto", None).description == "<@1> a changé de nom d'affichage : **Toto** → **(aucun)**"


def test_join_shows_the_invite():
    user = user_without_photo()
    fields = {f.name: f.value for f in logs_message.join(user, InviteUse("abc", moderator(), 4)).fields}
    assert fields["Invitation:"] == "`abc` de <@99> (4 utilisations)"
    assert logs_message.invite_text(InviteUse(None)) == "URL personnalisée"
    assert logs_message.invite_text(None) == "inconnue"


def test_channels_and_roles():
    channel = MagicMock(mention="<#5>", type=discord.ChannelType.voice)
    channel.name = "Général"
    role = MagicMock(mention="<@&6>")
    role.name = "Modo"
    assert logs_message.channel_created(channel, moderator()).description == "Salon <#5> (vocal) créé par <@99>."
    assert logs_message.channel_deleted(channel).description == "Salon **Général** (vocal) supprimé."
    assert logs_message.role_created(role, moderator()).description == "Rôle <@&6> créé par <@99>."
    assert logs_message.role_deleted(role, moderator()).description == "Rôle **Modo** supprimé par <@99>."


def test_channel_type():
    assert channel_type(MagicMock(type=discord.ChannelType.category)) == "catégorie"
    assert channel_type(MagicMock(type=None)) == "salon"


@pytest.mark.parametrize("seconds, text", [
    (0, "illimitée"), (None, "illimitée"), (1800, "30 minutes"), (3600, "1 heure"), (43200, "12 heures"),
    (86400, "1 jour"), (604800, "7 jours"), (90061, "1 jour 1 heure 1 minute"),
])
def test_duration_text(seconds, text):
    assert duration_text(seconds) == text


def test_invites():
    invite = MagicMock(code="abc", inviter=moderator(), max_age=86400, max_uses=0)
    invite.channel.mention = "<#5>"
    invite.channel.name = "général"
    embed = logs_message.invite_created(invite)
    assert embed.description == "<@99> a créé une invitation pour <#5>."
    assert {f.name: f.value for f in embed.fields} == {"Code:": "abc", "Validité:": "1 jour", "Utilisations max:": "illimitées"}
    assert logs_message.invite_deleted(invite, moderator()).description == "Invitation **abc** pour **#général** supprimée par <@99>."
    assert logs_message.invite_deleted(invite, exhausted=True).description == "Invitation **abc** épuisée."
