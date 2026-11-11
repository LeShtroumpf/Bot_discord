import json
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import httpx2
import pytest

from cephalon import limits as limits_module
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
def cog(fake_api, limits):
    cog = Cephalon(bot=MagicMock())
    cog.api = fake_api
    cog.limits = limits
    return cog


def state(limits) -> dict:
    return json.loads(limits.path.read_text(encoding="utf-8"))


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
    assert embed.footer.text == "Données : warframestat.us · 19 questions restantes aujourd'hui"
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
async def test_load_and_unload(limits):
    cog = Cephalon(bot=MagicMock())
    assert cog.limits.path == limits_module.Limits(cog_module.STATE_DIR).path  # vrai dossier d'état par défaut
    cog.limits = limits
    await cog.cog_unload()  # jamais chargé : rien à fermer
    await cog.cog_load()
    assert cog.api.session is cog.session and cog.load_error is None
    await cog.cog_unload()
    assert cog.session.closed


# --- Limites ------------------------------------------------------------------------------------------------

def ok(claude):
    return claude.client(*(claude.reply("end_turn", claude.text("Oui, Tenno."), input_tokens=1000, output_tokens=1000)
                           for _ in range(5)))


@pytest.mark.asyncio
async def test_cooldown_refusal(cog, asking, settings, claude, clock):
    cog.claude = ok(claude)
    await cog.cephalon.callback(cog, asking, question="Continuité ?")
    clock.advance(17.5)
    await cog.cephalon.callback(cog, asking, question="Et Rhino ?")
    asking.response.send_message.assert_awaited_once_with(
        "Doucement, Tenno : je reprends mon souffle. Repose ta question dans 13 secondes.", ephemeral=True)
    asking.response.defer.assert_awaited_once()  # la seconde question n'a pas atteint Claude
    assert len(cog.claude.requests) == 1
    clock.advance(12.5)
    await cog.cephalon.callback(cog, asking, question="Et Rhino ?")
    assert len(cog.claude.requests) == 2


@pytest.mark.asyncio
async def test_quota_refusal(cog, asking, settings, settings_file, claude, clock, report):
    configure(settings_file, cephalon={"daily_questions": 2})
    cog.claude = ok(claude)
    for expected in ("1 question restante aujourd'hui", "Dernière question du jour"):
        await cog.cephalon.callback(cog, asking, question="Continuité ?")
        assert asking.followup.send.await_args.kwargs["embed"].footer.text == expected
        clock.advance(60)
    await cog.cephalon.callback(cog, asking, question="Continuité ?")
    asking.response.send_message.assert_awaited_once_with(
        "Tu as épuisé tes 2 consultations du jour, Tenno. Mes archives te rouvrent à minuit.", ephemeral=True)
    assert len(cog.claude.requests) == 2 and state(cog.limits)["questions"] == {"77": 2}


@pytest.mark.asyncio
async def test_budget_alerts_then_refusal(cog, asking, settings, settings_file, claude, clock, report):
    # 1000 tokens d'entrée + 1000 de sortie sur Haiku = 0,0006 $, soit 0,00054 € par question.
    configure(settings_file, cephalon={"monthly_budget": 0.0012})
    cog.claude = ok(claude)
    await cog.cephalon.callback(cog, asking, question="Une ?")  # 45 % du budget
    report.assert_not_awaited()
    clock.advance(60)
    await cog.cephalon.callback(cog, asking, question="Deux ?")  # 90 %
    report.assert_awaited_once_with(cog.bot, "80 % du budget mensuel atteint : 0,00 € sur 0,00 €", "cephalon : budget")
    clock.advance(60)
    await cog.cephalon.callback(cog, asking, question="Trois ?")  # 135 % : la question se termine quand même
    assert report.await_args.args[1].startswith("Budget mensuel atteint : ") and report.await_count == 2
    assert asking.followup.send.await_count == 3
    clock.advance(60)
    await cog.cephalon.callback(cog, asking, question="Quatre ?")
    asking.response.send_message.assert_awaited_once_with(persona.BUDGET_MESSAGE, ephemeral=True)
    assert len(cog.claude.requests) == 3 and state(cog.limits)["alerts"] == [80, 100]


def test_budget_alert_amounts():
    assert cog_module.euros(3.214) == "3,21 €" and cog_module.euros(4) == "4,00 €"


@pytest.mark.asyncio
async def test_outage_keeps_the_quota_but_counts_the_tokens(cog, asking, settings, claude, report, api_routes, failing_response):
    api_routes[("/mods/search/Continuity", None)] = failing_response("status")
    cog.claude = claude.client(claude.reply("tool_use", claude.tool("get_mod", "Continuity"), input_tokens=1000, output_tokens=1000))
    await cog.cephalon.callback(cog, asking, question="Continuity ?")
    saved = state(cog.limits)
    assert saved["questions"] == {} and saved["cost_usd"] == pytest.approx(0.0006)
    assert asking.followup.send.await_args.kwargs["embed"].footer.text is None  # pas de compteur sur un repli


@pytest.mark.asyncio
async def test_missing_key_costs_nothing(cog, asking, settings, report, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    await cog.cephalon.callback(cog, asking, question="Continuité ?")
    assert state(cog.limits)["questions"] == {} and state(cog.limits)["cost_usd"] == 0


@pytest.mark.asyncio
async def test_round_limit_keeps_the_quota(cog, asking, settings, claude, report):
    cog.claude = claude.client(*(claude.reply("tool_use", claude.tool("get_mod", "Continuity")) for _ in range(5)))
    await cog.cephalon.callback(cog, asking, question="Continuity ?")
    assert state(cog.limits)["questions"] == {} and state(cog.limits)["cost_usd"] > 0


@pytest.mark.asyncio
async def test_unknown_model_price_is_reported(cog, asking, settings, settings_file, claude, report):
    configure(settings_file, cephalon={"model": "claude-futur-9"})
    cog.claude = ok(claude)
    await cog.cephalon.callback(cog, asking, question="Continuité ?")
    report.assert_awaited_once_with(cog.bot, "prix inconnu pour le modèle claude-futur-9 : coût compté au tarif le plus cher",
                                    "cephalon : budget")
    assert state(cog.limits)["cost_usd"] == pytest.approx((1000 * 8 + 1000 * 40) / 1_000_000)


@pytest.mark.asyncio
async def test_unreadable_state_is_reported_at_the_first_question(cog, asking, settings, claude, report):
    cog.limits.path.parent.mkdir(parents=True)
    cog.limits.path.write_text("{ pas du json", encoding="utf-8")
    await cog.cog_load()
    assert isinstance(cog.load_error, limits_module.StateError)
    cog.claude = ok(claude)
    await cog.cephalon.callback(cog, asking, question="Continuité ?")
    assert "illisible" in report.await_args.args[1] and report.await_args.args[1].endswith("compteurs remis à zéro")
    assert cog.load_error is None and state(cog.limits)["questions"] == {"77": 1}  # le bot répond et repart de zéro
    await cog.cog_unload()


@pytest.mark.asyncio
async def test_state_that_cannot_be_written_is_reported(cog, asking, settings, claude, report, monkeypatch):
    monkeypatch.setattr(cog.limits, "save", MagicMock(side_effect=OSError("disque plein")))
    cog.claude = ok(claude)
    await cog.cephalon.callback(cog, asking, question="Continuité ?")
    report.assert_awaited_once_with(cog.bot, "état des limites non écrit : disque plein", "cephalon : budget")
    assert sent_embed(asking).footer.text == "19 questions restantes aujourd'hui"  # les compteurs continuent en mémoire


@pytest.mark.asyncio
async def test_state_survives_a_restart(cog, asking, settings, claude, fake_api, clock):
    cog.claude = ok(claude)
    await cog.cephalon.callback(cog, asking, question="Continuité ?")
    restarted = Cephalon(bot=MagicMock())
    restarted.limits = limits_module.Limits(cog.limits.path.parent, clock=clock)
    await restarted.cog_load()
    restarted.api, restarted.claude = fake_api, ok(claude)
    asking.followup.send.reset_mock()
    await restarted.cephalon.callback(restarted, asking, question="Et encore ?")  # cooldown en mémoire : reparti de zéro
    assert asking.followup.send.await_args.kwargs["embed"].footer.text.endswith("18 questions restantes aujourd'hui")
    await restarted.cog_unload()


# --- Configuration ------------------------------------------------------------------------------------------

def test_default_config(settings_file):
    assert read_config() == Config(model="claude-haiku-5-5", max_tokens=2000, effort="low", cooldown=30, daily_questions=20,
                                   monthly_budget=4, usd_to_eur=0.9)
    configure(settings_file, cephalon=None)
    assert read_config() == Config()


@pytest.mark.parametrize("section", [
    {"model": "", "max_tokens": 0, "effort": "extrême"}, {"model": 5, "max_tokens": "2000", "effort": None},
    {"max_tokens": True}, {"max_tokens": -5}, "n'importe quoi", [],
    {"cooldown": 0, "daily_questions": 0, "monthly_budget": 0, "usd_to_eur": 0},
    {"cooldown": -1, "daily_questions": 2.5, "monthly_budget": "4", "usd_to_eur": True}, {"cooldown": None, "daily_questions": "20"},
])
def test_invalid_config_falls_back_to_defaults(settings_file, section):
    configure(settings_file, cephalon=section)
    assert read_config() == Config()


def test_valid_config(settings_file):
    configure(settings_file, cephalon={"model": " claude-sonnet-5-5 ", "max_tokens": 3000, "effort": "medium", "cooldown": 2.5,
                                       "daily_questions": 5, "monthly_budget": 0.5, "usd_to_eur": 0.87})
    assert read_config() == Config(model="claude-sonnet-5-5", max_tokens=3000, effort="medium", cooldown=2.5, daily_questions=5,
                                   monthly_budget=0.5, usd_to_eur=0.87)


@pytest.mark.parametrize("warframe, expected", [
    ({"command_channel": "4242"}, 4242), ({"command_channel": 4242}, 4242), ({"command_channel": ""}, None),
    ({"command_channel": "salon"}, None), ({}, None), (None, None),
])
def test_command_channel(settings_file, warframe, expected):
    configure(settings_file, warframe=warframe)
    assert command_channel() == expected
