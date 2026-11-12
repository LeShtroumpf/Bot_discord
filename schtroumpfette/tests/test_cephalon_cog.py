import asyncio
import datetime as dt
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import discord
import httpx2
import pytest

from cephalon import limits as limits_module
from cephalon import persona, render
from cephalon.config import INDEX_MAX_AGE, INDEX_RETRY, Config, command_channel, read_config
from cephalon.index import INDEX_FILE, LISTS, Index
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


KEEP_INDEX = Cephalon.keep_index  # la vraie tâche de fond, pour les tests qui la visent


@pytest.fixture(autouse=True)
def no_index_task(monkeypatch):
    """cog_load ne lance pas la vraie tâche de l'index : elle téléchargerait les listes de l'API."""
    monkeypatch.setattr(Cephalon, "keep_index", AsyncMock())


@pytest.fixture
def cog(fake_api, limits, tmp_path):
    cog = Cephalon(bot=MagicMock())
    cog.api = fake_api
    cog.limits = limits
    cog.index_dir = tmp_path / "index"
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
    assert cog.index_dir == cog_module.STATE_DIR and cog.index_task.get_name() == "cephalon_index"
    await asyncio.sleep(0)
    Cephalon.keep_index.assert_awaited_once()
    await cog.cog_unload()
    assert cog.session.closed and cog.index_task.done()


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


# --- Index local --------------------------------------------------------------------------------------------

NOW = dt.datetime(2026, 11, 12, 12, 0, tzinfo=dt.UTC)


@pytest.fixture
def at_noon(monkeypatch):
    monkeypatch.setattr(cog_module, "utcnow", lambda: NOW)


@pytest.fixture
def lists_online(api_routes, index_lists, monkeypatch):
    """Les six listes servies par l'API de test, sans les tailles minimales des vraies listes."""
    monkeypatch.setattr("cephalon.index.MINIMUMS", {})
    for name, (path, params) in LISTS.items():
        api_routes[(path, params.get("language"))] = index_lists[name]


async def run_index_task(cog, monkeypatch) -> list[float]:
    """Lance la vraie tâche de fond jusqu'à sa troisième attente et renvoie les durées demandées."""
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(cog_module.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        await KEEP_INDEX(cog)
    return sleeps


@pytest.mark.asyncio
async def test_index_is_downloaded_then_kept_for_a_day(cog, report, lists_online, at_noon, api_session, monkeypatch, capsys):
    sleeps = await run_index_task(cog, monkeypatch)
    assert cog.api.index.summary() == "27 mods, 22 armes, 14 Warframes, 87 objets" and cog.api.index.built_at == NOW
    assert sleeps == [INDEX_MAX_AGE] * 3     # à jour : prochaine construction dans un jour (l'horloge de test est figée)
    assert len(api_session.calls) == 6       # une seule construction, six listes
    assert (cog.index_dir / INDEX_FILE).exists()
    assert "[cephalon] index : 27 mods, 22 armes, 14 Warframes, 87 objets (téléchargé en " in capsys.readouterr().out
    report.assert_not_awaited()


@pytest.mark.asyncio
async def test_recent_index_file_is_used_without_download(cog, index, report, at_noon, api_session, monkeypatch, capsys):
    index.write(cog.index_dir)  # construit à 8 h : 4 heures d'âge
    monkeypatch.setattr(cog, "refresh_index", AsyncMock(return_value=True))
    sleeps = await run_index_task(cog, monkeypatch)
    assert sleeps[0] == INDEX_MAX_AGE - 4 * 3600 and api_session.calls == []
    assert cog.api.index.built_at == index.built_at
    assert "[cephalon] index : 27 mods, 22 armes, 14 Warframes, 87 objets (lu du disque)" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_old_index_file_serves_until_the_new_one_is_built(cog, index_lists, report, lists_online, at_noon):
    old = Index.build(index_lists, NOW - dt.timedelta(days=3))
    old.write(cog.index_dir)
    await cog.read_index()
    assert cog.api.index.built_at == old.built_at
    assert await cog.refresh_index() is True
    assert cog.api.index.built_at == NOW and Index.read(cog.index_dir).built_at == NOW


@pytest.mark.asyncio
async def test_outage_keeps_the_old_index_and_is_reported_once(cog, index, report, at_noon, api_routes, failing_response, monkeypatch):
    cog.api.index = index
    api_routes[("/mods", None)] = failing_response("status")
    monkeypatch.setattr("cephalon.index.MINIMUMS", {})
    assert await cog.refresh_index() is False and await cog.refresh_index() is False
    assert cog.api.index is index
    report.assert_awaited_once()
    assert report.await_args.args[1].startswith("index non mis à jour : /mods") and report.await_args.args[2] == "cephalon : index"


@pytest.mark.asyncio
async def test_outage_is_retried_then_recovery_is_reported(cog, report, lists_online, at_noon, api_routes, index_lists,
                                                           failing_response, monkeypatch):
    api_routes[("/weapons", None)] = failing_response("timeout")
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 1:
            api_routes[("/weapons", None)] = index_lists["weapons"]  # l'API revient
        if len(sleeps) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(cog_module.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        await KEEP_INDEX(cog)
    assert sleeps == [INDEX_RETRY, INDEX_MAX_AGE]
    assert [call.args[1] for call in report.await_args_list] == [
        "index non mis à jour : /weapons : TimeoutError", "index de nouveau à jour"]
    assert cog.index_failing is False and cog.api.index is not None


@pytest.mark.asyncio
async def test_short_list_is_an_outage(cog, report, lists_online, at_noon, api_routes, monkeypatch):
    monkeypatch.setattr("cephalon.index.MINIMUMS", {"warframes": 50})
    assert await cog.refresh_index() is False and cog.api.index is None
    assert report.await_args.args[1] == "index non mis à jour : liste warframes incomplète (14)"


@pytest.mark.asyncio
async def test_unreadable_index_file_is_reported_and_ignored(cog, report):
    cog.index_dir.mkdir()
    (cog.index_dir / INDEX_FILE).write_text("{ pas du json", encoding="utf-8")
    await cog.read_index()
    assert cog.api.index is None
    assert "index illisible" in str(report.await_args.args[1]) and report.await_args.args[2] == "cephalon : index"


@pytest.mark.asyncio
async def test_index_that_cannot_be_written_stays_in_memory(cog, report, lists_online, at_noon, monkeypatch):
    monkeypatch.setattr(Index, "write", MagicMock(side_effect=OSError("disque plein")))
    assert await cog.refresh_index() is True and cog.api.index is not None
    report.assert_awaited_once_with(cog.bot, "index non écrit sur disque : disque plein", "cephalon : index")


@pytest.mark.asyncio
async def test_question_uses_the_index(cog, asking, settings, claude, index, report):
    cog.api.index = index
    cog.claude = claude.client(
        claude.reply("tool_use", SimpleNamespace(type="tool_use", id="toolu_1", name="rank_warframes",
                                                 input={"stat": "armor", "order": "desc", "kind": None})),
        claude.reply("end_turn", claude.text("Valkyr Prime, avec 1000 d'armure de base.")))
    await cog.cephalon.callback(cog, asking, question="Quelle Warframe a le plus d'armure ?")
    embed = sent_embed(asking)
    assert "[Valkyr Prime](https://wiki.warframe.com/w/Valkyr%2FPrime)" in embed.fields[0].value
    assert '"armor":1000' in cog.claude.requests[1]["messages"][2]["content"][0]["content"]


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


# --- Pages du wiki ------------------------------------------------------------------------------------------

@pytest.fixture
def modo(interaction, cog, wiki_dir):
    """Un modérateur lance /cephalon_pages ; les exports de test sont dans le dossier d'état du cog."""
    interaction.user.mention = "@modo"
    cog.index_dir = wiki_dir.parent
    cog.bot.logs_channel.send = AsyncMock()
    return interaction


def pages_embed(interaction, cog):
    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    kwargs = interaction.followup.send.await_args.kwargs
    assert kwargs["ephemeral"] is True
    cog.bot.logs_channel.send.assert_awaited_once_with(embed=kwargs["embed"])  # même embed dans le salon de logs
    return kwargs["embed"]


@pytest.mark.asyncio
async def test_pages_command(cog, modo, report, capsys):
    await cog.cephalon_pages.callback(cog, modo)
    embed = pages_embed(modo, cog)
    assert embed.color == discord.Color.green() and embed.description == "par @modo"
    assert embed.fields[0].value == "Argon Crystal (4 sections)\nDamage (4 sections)\nStatus Effect (1 section)"
    assert sorted(cog.api.pages.pages) == ["Argon Crystal", "Damage", "Status Effect"]
    assert (cog.index_dir / "pages.json").exists()
    assert "[cephalon] pages : 3 pages, 9 sections, 0 problèmes" in capsys.readouterr().out
    report.assert_not_awaited()


@pytest.mark.asyncio
async def test_pages_command_with_a_broken_file(cog, modo, report):
    (cog.index_dir / "pages" / "broken.xml").write_text("<mediawiki><page>", encoding="utf-8")
    await cog.cephalon_pages.callback(cog, modo)
    embed = pages_embed(modo, cog)
    assert embed.color == discord.Color.orange() and embed.fields[-1].value.startswith("broken.xml : XML illisible")
    assert len(cog.api.pages) == 3


@pytest.mark.asyncio
async def test_pages_command_without_directory(cog, modo, report, tmp_path):
    cog.api.pages = previous = MagicMock()
    cog.index_dir = tmp_path / "vide"
    await cog.cephalon_pages.callback(cog, modo)
    embed = pages_embed(modo, cog)
    assert embed.color == discord.Color.red() and "introuvable" in embed.description
    assert cog.api.pages is previous


@pytest.mark.asyncio
async def test_pages_command_cannot_write(cog, modo, report, monkeypatch):
    def fail(self, directory):
        raise OSError("disque plein")
    monkeypatch.setattr(cog_module.Pages, "write", fail)
    await cog.cephalon_pages.callback(cog, modo)
    embed = pages_embed(modo, cog)
    assert embed.color == discord.Color.red() and "écriture de pages.json impossible : disque plein" in embed.description
    assert cog.api.pages is None


@pytest.mark.asyncio
async def test_pages_command_without_logs_channel(cog, modo, report):
    cog.bot.logs_channel = None
    await cog.cephalon_pages.callback(cog, modo)
    modo.followup.send.assert_awaited_once()
    report.assert_awaited_once()
    assert report.await_args.args[2] == "cephalon : pages"


@pytest.mark.asyncio
async def test_pages_commands_run_one_at_a_time(cog, modo, report, interaction, monkeypatch):
    running, overlaps = [], []
    original = Cephalon.reload_pages

    def slow_reload(self):
        overlaps.append(bool(running))
        running.append(1)
        import time
        time.sleep(0.05)
        running.pop()
        return original(self)
    monkeypatch.setattr(Cephalon, "reload_pages", slow_reload)
    second = MagicMock()
    second.response.defer, second.followup.send, second.user.mention = AsyncMock(), AsyncMock(), "@autre"
    await asyncio.gather(cog.cephalon_pages.callback(cog, modo), cog.cephalon_pages.callback(cog, second))
    assert overlaps == [False, False]
    second.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_pages_are_read_at_load(limits, wiki_dir, tmp_path, monkeypatch, capsys):
    from cephalon.pages import Pages
    pages, _ = Pages.reload(wiki_dir)
    pages.write(tmp_path)
    monkeypatch.setattr(cog_module, "STATE_DIR", tmp_path)
    cog = Cephalon(bot=MagicMock())
    cog.limits = limits
    await cog.cog_load()
    assert len(cog.api.pages) == 3 and cog.pages_error is None
    assert "[cephalon] pages : 3 pages, 9 sections (lu du disque)" in capsys.readouterr().out
    await cog.cog_unload()


@pytest.mark.asyncio
async def test_unreadable_pages_are_reported_at_the_first_question(limits, tmp_path, monkeypatch, asking, settings,
                                                                   claude, report):
    (tmp_path / "pages.json").write_text("{", encoding="utf-8")
    monkeypatch.setattr(cog_module, "STATE_DIR", tmp_path)
    cog = Cephalon(bot=MagicMock())
    cog.limits = limits
    await cog.cog_load()
    assert cog.api.pages is None and cog.pages_error is not None
    cog.claude = ok(claude)
    await cog.cephalon.callback(cog, asking, question="Salut ?")
    await cog.cephalon.callback(cog, asking, question="Encore ?")  # signalé une seule fois
    origins = [call.args[2] for call in report.await_args_list]
    assert origins == ["cephalon : pages"]
    await cog.cog_unload()


@pytest.mark.asyncio
async def test_answer_from_a_wiki_page(cog, asking, settings, claude, report, wiki_dir):
    from cephalon.pages import Pages
    cog.api.pages, _ = Pages.reload(wiki_dir)
    read = SimpleNamespace(type="tool_use", id="toolu_1", name="read_section",
                           input={"page": "Argon Crystal", "section": "Acquisition"})
    cog.claude = claude.client(claude.reply("tool_use", read), claude.reply("end_turn", claude.text("Sur Ani, Tenno.")))
    await cog.cephalon.callback(cog, asking, question="Où farmer l'argon ?")
    embed = sent_embed(asking)
    assert embed.fields[0].value == "[Argon Crystal — Acquisition](https://wiki.warframe.com/w/Argon_Crystal#Acquisition)"
    assert embed.footer.text.startswith("Données : warframestat.us, wiki.warframe.com (CC BY-NC-SA) · ")


# --- /cephalon_build ----------------------------------------------------------------------------------------

def png(size=(1200, 500)) -> bytes:
    import io
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", size, "purple").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def capture():
    attachment = MagicMock()
    attachment.content_type, attachment.url = "image/png", "https://cdn.discordapp.com/attachments/1/2/build.png"
    attachment.read = AsyncMock(return_value=png())
    attachment.size = 300_000
    return attachment


def build_reading(*names, is_build=True):
    slots = [{"slot": "normal", "kind": "mod", "name": name, "readable": True, "drain": 9, "rank": 5, "max_rank": 5,
              "polarity": None} for name in names]
    return {"is_build": is_build, "equipment_kind": "warframe", "equipment_name": "Rhino Prime", "capacity": None,
            "displayed_stats": [], "slots": slots}


def reader(claude, data):
    return claude.reply("end_turn", claude.text(json.dumps(data)), input_tokens=3000, output_tokens=500)


@pytest.mark.asyncio
async def test_build(cog, asking, settings, claude, report, capture, capsys):
    cog.claude = claude.client(reader(claude, build_reading("Continuité")),
                               claude.reply("end_turn", claude.text("**Mods lus**\n- Continuité…"), input_tokens=4000,
                                            output_tokens=900))
    await cog.cephalon_build.callback(cog, asking, image=capture, question="Pour l'Acier ?")
    embed = sent_embed(asking)
    assert embed.description == "> Pour l'Acier ?\n\n**Mods lus**\n- Continuité…"
    assert embed.thumbnail.url == capture.url
    assert embed.fields[0].value == "[Continuity](https://wiki.warframe.com/w/Continuity)"
    assert embed.footer.text == "Données : warframestat.us · Dernière analyse de build du jour"
    reading_request, analysis_request = cog.claude.requests
    assert reading_request["model"] == "claude-sonnet-5-5" and "format" in reading_request["output_config"]
    assert analysis_request["model"] == "claude-sonnet-5-5" and analysis_request["output_config"] == {"effort": "medium"}
    sent = json.loads(analysis_request["messages"][0]["content"])
    assert sent["question"] == "Pour l'Acier ?" and sent["slots"][0]["card"]["name_fr"] == "Continuité"
    saved = state(cog.limits)
    assert saved["builds"] == {"77": 1} and saved["questions"] == {}       # le quota des questions n'est pas touché
    assert saved["cost_usd"] == pytest.approx((3000 * 2 + 500 * 10 + 4000 * 2 + 900 * 10) / 1e6)
    out = capsys.readouterr().out
    assert "[cephalon] build 77 : image 1200x500, PNG" in out and "1 cartes (1 vérifiées)" in out and "coût 0,03 €" in out
    report.assert_not_awaited()


@pytest.mark.asyncio
async def test_second_build_of_the_day_is_refused(cog, asking, settings, claude, report, capture, clock):
    cog.claude = claude.client(reader(claude, build_reading("Continuité")), claude.reply("end_turn", claude.text("Ok.")))
    await cog.cephalon_build.callback(cog, asking, image=capture, question=None)
    clock.advance(200)
    asking.response.send_message.reset_mock()
    await cog.cephalon_build.callback(cog, asking, image=capture, question=None)
    asking.response.send_message.assert_awaited_once_with(
        "Tu as utilisé tes 1 analyse de build du jour, Tenno. Mes archives te rouvrent à minuit.", ephemeral=True)
    assert cog.limits.check(77, read_config(), cog_module.utcnow()) is None  # /cephalon reste ouvert


@pytest.mark.asyncio
async def test_build_quota_is_read_from_settings(cog, asking, settings, settings_file, claude, report, capture, clock):
    configure(settings_file, warframe={"command_channel": str(CHANNEL)}, cephalon={"build_daily": 2})
    for _ in range(2):
        cog.claude = claude.client(reader(claude, build_reading("Continuité")), claude.reply("end_turn", claude.text("Ok.")))
        asking.followup.send.reset_mock()
        asking.response.defer.reset_mock()
        await cog.cephalon_build.callback(cog, asking, image=capture, question=None)
        clock.advance(200)
        assert sent_embed(asking).color == render.ANSWER_COLOR
    assert state(cog.limits)["builds"] == {"77": 2}


@pytest.mark.asyncio
async def test_not_a_build(cog, asking, settings, claude, report, capture):
    cog.claude = claude.client(reader(claude, build_reading(is_build=False)))
    await cog.cephalon_build.callback(cog, asking, image=capture, question=None)
    embed = sent_embed(asking)
    assert persona.NOT_A_BUILD_MESSAGE in embed.description and embed.color == render.FALLBACK_COLOR
    assert len(cog.claude.requests) == 1 and state(cog.limits)["builds"] == {}  # quota intact
    assert state(cog.limits)["cost_usd"] > 0                                     # la lecture est comptée
    report.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("content_type, size, message", [
    (None, 100, persona.NOT_AN_IMAGE_MESSAGE),
    ("application/pdf", 100, persona.NOT_AN_IMAGE_MESSAGE),
    ("image/png", 30 * 1024 * 1024, "Cette capture est trop lourde pour mes archives, Tenno (30 Mo, 20 Mo au plus)."),
])
async def test_attachment_refused(cog, asking, settings, capture, content_type, size, message):
    capture.content_type, capture.size = content_type, size
    await cog.cephalon_build.callback(cog, asking, image=capture, question=None)
    asking.response.send_message.assert_awaited_once_with(message, ephemeral=True)
    capture.read.assert_not_awaited()
    assert cog.limits.build_cooldowns == {}


@pytest.mark.asyncio
async def test_build_wrong_channel(cog, asking, settings, capture):
    asking.channel_id = 1
    await cog.cephalon_build.callback(cog, asking, image=capture, question=None)
    asking.response.send_message.assert_awaited_once_with(f"Mauvais salon, utilise <#{CHANNEL}>.", ephemeral=True)


@pytest.mark.asyncio
async def test_unreadable_capture(cog, asking, settings, claude, report, capture):
    capture.read = AsyncMock(return_value=b"pas une image")
    cog.claude = claude.client()
    await cog.cephalon_build.callback(cog, asking, image=capture, question=None)
    assert persona.UNREADABLE_IMAGE_MESSAGE in sent_embed(asking).description
    assert cog.claude.requests == [] and not cog.limits.path.exists()


@pytest.mark.asyncio
async def test_unusable_reading_is_reported(cog, asking, settings, claude, report, capture, seventh_message):
    cog.claude = claude.client(claude.reply("refusal"))
    await cog.cephalon_build.callback(cog, asking, image=capture, question=None)
    assert sent_embed(asking).color == render.FALLBACK_COLOR
    assert report.await_args.args[2] == "cephalon : build" and state(cog.limits)["builds"] == {}


@pytest.mark.asyncio
async def test_build_warframestat_outage(cog, asking, settings, claude, report, capture, api_routes, failing_response,
                                         seventh_message):
    api_routes[("/mods/search/Continuit%C3%A9", None)] = failing_response("status")
    cog.claude = claude.client(reader(claude, build_reading("Continuité")))
    await cog.cephalon_build.callback(cog, asking, image=capture, question=None)
    assert sent_embed(asking).color == render.FALLBACK_COLOR and len(cog.claude.requests) == 1
    assert report.await_args.args[2] == "cephalon : warframestat"
    assert state(cog.limits)["builds"] == {} and state(cog.limits)["cost_usd"] > 0


@pytest.mark.asyncio
async def test_build_round_limit(cog, asking, settings, claude, report, capture):
    cog.claude = claude.client(reader(claude, build_reading("Continuité")),
                               *(claude.reply("tool_use", claude.tool("get_mod", "Continuité")) for _ in range(5)))
    await cog.cephalon_build.callback(cog, asking, image=capture, question=None)
    assert persona.ROUNDS_MESSAGE in sent_embed(asking).description and state(cog.limits)["builds"] == {}


@pytest.mark.asyncio
async def test_unknown_reader_model_is_reported(cog, asking, settings, settings_file, claude, report, capture):
    configure(settings_file, warframe={"command_channel": str(CHANNEL)}, cephalon={"build_reader_model": "claude-x"})
    cog.claude = claude.client(reader(claude, build_reading("Continuité")), claude.reply("end_turn", claude.text("Ok.")))
    await cog.cephalon_build.callback(cog, asking, image=capture, question=None)
    assert [call.args[1] for call in report.await_args_list] == [
        "prix inconnu pour le modèle claude-x : coût compté au tarif le plus cher"]
