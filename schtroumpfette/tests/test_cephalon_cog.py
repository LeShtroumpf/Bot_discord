import json
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import httpx2
import pytest

from cephalon import persona, render
from cephalon.config import Config, command_channel, read_config
from commands import cephalon as cog_module
from commands.cephalon import Cephalon

CHANNEL = 4242


def configure(settings_file, **sections):
    data = json.loads(settings_file.read_text())
    for key, value in sections.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    settings_file.write_text(json.dumps(data))


@pytest.fixture
def settings(settings_file):
    configure(settings_file, warframe={"command_channel": str(CHANNEL)})
    return settings_file


@pytest.fixture
def report():
    with patch.object(cog_module, "report_error", new=AsyncMock()) as mock:
        yield mock


@pytest.fixture
def cog(fake_api):
    cog = Cephalon(bot=MagicMock())
    cog.api = fake_api
    return cog


@pytest.fixture
def asking(interaction):
    interaction.channel_id = CHANNEL
    interaction.user.id = 77
    return interaction


def sent_embed(interaction):
    interaction.response.defer.assert_awaited_once_with()  # public
    interaction.followup.send.assert_awaited_once()
    return interaction.followup.send.await_args.kwargs["embed"]


# --- Salon --------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_not_configured(cog, asking, settings_file):
    await cog.cephalon.callback(cog, asking, question="Continuité ?")
    asking.response.send_message.assert_awaited_once_with("Le module Warframe n'est pas encore configuré.", ephemeral=True)
    asking.response.defer.assert_not_awaited()


@pytest.mark.asyncio
async def test_wrong_channel(cog, asking, settings):
    asking.channel_id = 1
    cog.claude = MagicMock()
    await cog.cephalon.callback(cog, asking, question="Continuité ?")
    asking.response.send_message.assert_awaited_once_with(f"Mauvais salon, utilise <#{CHANNEL}>.", ephemeral=True)
    asking.response.defer.assert_not_awaited()
    cog.claude.messages.create.assert_not_called()


# --- Réponse ------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_answer(cog, asking, settings, claude, report, capsys):
    cog.claude = claude.client(claude.reply("tool_use", claude.tool("get_mod", "Continuité"), cache_write=900),
                               claude.reply("end_turn", claude.text("+30 % de durée de pouvoir, Tenno."), cache_read=900))
    await cog.cephalon.callback(cog, asking, question="Que fait Continuité au rang max ?")
    embed = sent_embed(asking)
    assert embed.description == "> Que fait Continuité au rang max ?\n\n+30 % de durée de pouvoir, Tenno."
    assert "https://wiki.warframe.com/w/Continuity" in embed.fields[0].value
    assert capsys.readouterr().out.strip() == ("[cephalon] 77 : 2 tours, entrée 200 (cache lu 900, écrit 900), sortie 40, "
                                               "modèle claude-haiku-5-5")
    report.assert_not_awaited()


@pytest.mark.asyncio
async def test_settings_are_read_at_each_question(cog, asking, settings, settings_file, claude):
    configure(settings_file, cephalon={"model": "claude-sonnet-5-5", "max_tokens": 900, "effort": "high"})
    cog.claude = claude.client(claude.reply("end_turn", claude.text("Oui.")))
    await cog.cephalon.callback(cog, asking, question="Continuité ?")
    request = cog.claude.requests[0]
    assert (request["model"], request["max_tokens"], request["output_config"]) == ("claude-sonnet-5-5", 900, {"effort": "high"})


# --- Pannes -------------------------------------------------------------------------------------------------

@pytest.fixture
def seventh_message(monkeypatch):
    monkeypatch.setattr(persona.random, "choice", lambda messages: messages[6])
    return persona.ERROR_MESSAGES[6]


@pytest.mark.asyncio
async def test_anthropic_outage(cog, asking, settings, claude, report, seventh_message):
    cog.claude = claude.client(anthropic.AnthropicError("401 invalid x-api-key"))
    await cog.cephalon.callback(cog, asking, question="Continuité ?")
    embed = sent_embed(asking)
    assert embed.description == f"> Continuité ?\n\n{seventh_message}" and embed.color == render.FALLBACK_COLOR
    report.assert_awaited_once_with(cog.bot, "401 invalid x-api-key", "cephalon")


def api_error(status: int, body) -> anthropic.APIStatusError:
    response = httpx2.Response(status, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    return anthropic.APIStatusError(f"Error code: {status} - {body}", response=response, body=body)


@pytest.mark.parametrize("error, expected", [
    (api_error(401, {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"},
                     "request_id": "req_011Cgwh"}), "401 invalid x-api-key"),
    (api_error(529, "surcharge"), "529 APIStatusError"),
    (anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com")), "Connection error."),
    (cog_module.MissingKeyError(), "ANTHROPIC_API_KEY absente du .env"),
])
def test_error_text_has_no_request_id(error, expected):
    """Le même texte d'une fois sur l'autre : sinon l'anti-spam du salon de logs ne retient rien."""
    assert cog_module.describe(error) == expected


@pytest.mark.asyncio
async def test_warframestat_outage(cog, asking, settings, claude, report, api_routes, failing_response, seventh_message):
    api_routes[("/mods/search/Continuity", None)] = failing_response("status")
    cog.claude = claude.client(claude.reply("tool_use", claude.tool("get_mod", "Continuity")))
    await cog.cephalon.callback(cog, asking, question="Continuity ?")
    assert sent_embed(asking).description == f"> Continuity ?\n\n{seventh_message}"
    assert report.await_args.args[2] == "cephalon : warframestat"
    assert "/mods/search/Continuity" in str(report.await_args.args[1])


@pytest.mark.asyncio
async def test_missing_key(cog, asking, settings, report, monkeypatch, seventh_message):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    await cog.cephalon.callback(cog, asking, question="Continuité ?")
    assert sent_embed(asking).description.endswith(seventh_message)
    assert report.await_args.args[1:] == ("ANTHROPIC_API_KEY absente du .env", "cephalon")
    assert cog.claude is None


@pytest.mark.asyncio
async def test_refusal(cog, asking, settings, claude, report, seventh_message):
    cog.claude = claude.client(claude.reply("refusal"))
    await cog.cephalon.callback(cog, asking, question="…")
    assert sent_embed(asking).description.endswith(seventh_message)
    report.assert_awaited_once_with(cog.bot, "question refusée par le modèle", "cephalon")


@pytest.mark.asyncio
async def test_round_limit(cog, asking, settings, claude, report):
    cog.claude = claude.client(*(claude.reply("tool_use", claude.tool("get_mod", "Continuity")) for _ in range(5)))
    await cog.cephalon.callback(cog, asking, question="Continuity ?")
    assert sent_embed(asking).description.endswith(persona.ROUNDS_MESSAGE)
    report.assert_not_awaited()


# --- Client et session --------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_client_is_created_once_with_the_key(cog, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    client = cog.claude_client()
    assert client is cog.claude_client()
    assert (client.timeout, client.max_retries) == (60, 2)
    await cog.cog_unload()


@pytest.mark.asyncio
async def test_load_and_unload():
    cog = Cephalon(bot=MagicMock())
    await cog.cog_unload()  # jamais chargé : rien à fermer
    await cog.cog_load()
    assert cog.api.session is cog.session
    await cog.cog_unload()
    assert cog.session.closed


# --- Configuration ------------------------------------------------------------------------------------------

def test_default_config(settings_file):
    assert read_config() == Config(model="claude-haiku-5-5", max_tokens=2000, effort="low")
    configure(settings_file, cephalon=None)
    assert read_config() == Config()


@pytest.mark.parametrize("section", [
    {"model": "", "max_tokens": 0, "effort": "extrême"}, {"model": 5, "max_tokens": "2000", "effort": None},
    {"max_tokens": True}, {"max_tokens": -5}, "n'importe quoi", [],
])
def test_invalid_config_falls_back_to_defaults(settings_file, section):
    configure(settings_file, cephalon=section)
    assert read_config() == Config()


def test_valid_config(settings_file):
    configure(settings_file, cephalon={"model": " claude-sonnet-5-5 ", "max_tokens": 3000, "effort": "medium"})
    assert read_config() == Config(model="claude-sonnet-5-5", max_tokens=3000, effort="medium")


@pytest.mark.parametrize("warframe, expected", [
    ({"command_channel": "4242"}, 4242), ({"command_channel": 4242}, 4242), ({"command_channel": ""}, None),
    ({"command_channel": "salon"}, None), ({}, None), (None, None),
])
def test_command_channel(settings_file, warframe, expected):
    configure(settings_file, warframe=warframe)
    assert command_channel() == expected
