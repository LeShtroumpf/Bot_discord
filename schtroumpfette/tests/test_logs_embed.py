import datetime as dt
from unittest.mock import MagicMock

import pytest

from utils.embed import logs_message


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


def test_voice_states():
    a, b = MagicMock(mention="#a"), MagicMock(mention="#b")
    user = user_without_photo()
    assert "a rejoint le vocal #a" in logs_message.voice(user, voice_state(), voice_state(a)).description
    assert "a quitté le vocal #a" in logs_message.voice(user, voice_state(a), voice_state()).description
    assert "a switch de vocal #a -> #b" in logs_message.voice(user, voice_state(a), voice_state(b)).description


def test_error_embed():
    embed = logs_message.error("origine", "x" * 2000)
    assert embed.description == "Error with last event: origine"
    assert len(embed.fields[0].value) == 1024
    assert logs_message.error("origine", "boum", repeats=12).description.endswith("(répétée 12 fois)")
