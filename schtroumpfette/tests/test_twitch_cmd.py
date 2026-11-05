import json
from unittest.mock import MagicMock

import pytest

from commands.moderation.twitch_cmd import UNKNOWN_INPUT, ModoTwitch


def followed(settings_file) -> dict:
    return json.loads(settings_file.read_text(encoding="utf-8"))["streamer_followed"]


def set_followed(settings_file, value: dict):
    data = json.loads(settings_file.read_text(encoding="utf-8"))
    data["streamer_followed"] = value
    settings_file.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def cog():
    return ModoTwitch(bot=MagicMock())


def answer(interaction) -> str:
    call = interaction.response.send_message.call_args
    assert call.kwargs["ephemeral"] is True
    return call.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["Toto", "twitch.tv/toto", "https://www.twitch.tv/Toto/"])
async def test_add_streamer_normalizes(cog, interaction, settings_file, text):
    set_followed(settings_file, {"https://www.twitch.tv/autre": False})
    await cog.add_streamer.callback(cog, interaction, text)
    assert followed(settings_file)["https://www.twitch.tv/toto"] is False
    assert answer(interaction) == "**toto** est maintenant suivi."


@pytest.mark.asyncio
async def test_add_streamer_on_an_empty_list(cog, interaction, settings_file):
    set_followed(settings_file, {})
    await cog.add_streamer.callback(cog, interaction, "toto")
    assert followed(settings_file) == {"https://www.twitch.tv/toto": False}


@pytest.mark.asyncio
async def test_add_streamer_refuses_anything_else(cog, interaction, settings_file):
    before = followed(settings_file)
    await cog.add_streamer.callback(cog, interaction, "https://youtube.com/toto")
    assert answer(interaction) == UNKNOWN_INPUT
    assert followed(settings_file) == before


@pytest.mark.asyncio
async def test_add_streamer_detects_a_duplicate_whatever_the_case(cog, interaction, settings_file):
    set_followed(settings_file, {"https://www.twitch.tv/Toto": True})
    await cog.add_streamer.callback(cog, interaction, "toto")
    assert answer(interaction) == "**toto** est déjà suivi."
    assert followed(settings_file) == {"https://www.twitch.tv/Toto": True}


@pytest.mark.asyncio
async def test_remove_streamer_whatever_the_case(cog, interaction, settings_file):
    set_followed(settings_file, {"https://www.twitch.tv/Toto": True, "https://www.twitch.tv/autre": False})
    await cog.remove_streamer.callback(cog, interaction, "toto")
    assert answer(interaction) == "**toto** n'est plus suivi."
    assert followed(settings_file) == {"https://www.twitch.tv/autre": False}


@pytest.mark.asyncio
async def test_remove_unknown_streamer(cog, interaction, settings_file):
    await cog.remove_streamer.callback(cog, interaction, "inconnu")
    assert answer(interaction) == "**inconnu** n'est pas suivi."


@pytest.mark.asyncio
async def test_remove_refuses_anything_else(cog, interaction, settings_file):
    await cog.remove_streamer.callback(cog, interaction, "pas un pseudo")
    assert answer(interaction) == UNKNOWN_INPUT
