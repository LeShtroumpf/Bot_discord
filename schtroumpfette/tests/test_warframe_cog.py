import dataclasses
import datetime as dt
import json
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord import app_commands

from commands import warframe as cog_module
from commands.warframe import Warframe
from warframe.browsewf import Alert, Reward, SourceError
from warframe.render import TOPICS


def choice(topic: str) -> app_commands.Choice:
    return app_commands.Choice(name=TOPICS[topic], value=topic)


def not_found() -> discord.NotFound:
    return discord.NotFound(MagicMock(status=404, reason="Not Found"), "Unknown Message")


def configure(settings_file, **values):
    data = json.loads(settings_file.read_text())
    data["warframe"].update(values)
    settings_file.write_text(json.dumps(data))


def config(settings_file) -> dict:
    return json.loads(settings_file.read_text())["warframe"]


@pytest.fixture
def bot():
    bot = MagicMock()
    bot.logs_channel_id = "1"
    return bot


@pytest.fixture
def cog(bot):
    return Warframe(bot)


@pytest.fixture
def logs():
    with patch.object(cog_module, "report_error", new=AsyncMock()) as mock:
        yield mock


# --- /warframe ---------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_warframe_not_configured(cog, interaction, settings_file):
    await cog.warframe.callback(cog, interaction, choice("arbitrage"))
    args = interaction.response.send_message.call_args
    assert "pas encore configuré" in args.args[0] and args.kwargs["ephemeral"] is True


@pytest.mark.asyncio
async def test_warframe_wrong_channel(cog, interaction, settings_file):
    configure(settings_file, command_channel="123")
    interaction.channel_id = 999
    await cog.warframe.callback(cog, interaction, choice("arbitrage"))
    args = interaction.response.send_message.call_args
    assert args.args[0] == "Mauvais salon, utilise <#123>." and args.kwargs["ephemeral"] is True


@pytest.mark.asyncio
async def test_warframe_no_data_yet(cog, interaction, settings_file):
    configure(settings_file, command_channel="123")
    interaction.channel_id = 123
    await cog.warframe.callback(cog, interaction, choice("baro"))
    assert interaction.response.send_message.call_args.kwargs["ephemeral"] is True


@pytest.mark.asyncio
async def test_warframe_public_answer(cog, interaction, settings_file):
    configure(settings_file, command_channel="123")
    interaction.channel_id = 123
    embeds = [discord.Embed(title="Baro Ki'Teer")]
    cog.rendered = {"baro": embeds}
    await cog.warframe.callback(cog, interaction, choice("baro"))
    args = interaction.response.send_message.call_args
    assert args.kwargs == {"embeds": embeds}  # publique : pas d'ephemeral


@pytest.fixture
def cog_with_targets(cog, settings_file, targets, bilingual):
    configure(settings_file, command_channel="123")
    cog.targets, cog.translator = targets, bilingual
    return cog


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["lancer", "lancier"])
async def test_warframe_target_answer_is_ephemeral(cog_with_targets, interaction, query):
    cog, interaction.channel_id = cog_with_targets, 123
    await cog.warframe.callback(cog, interaction, cible=query)
    args = interaction.response.send_message.call_args
    assert args.kwargs["embed"].title == "Lancier (Lancer)" and args.kwargs["ephemeral"] is True


@pytest.mark.asyncio
async def test_warframe_unknown_target_suggests_names(cog_with_targets, interaction):
    cog, interaction.channel_id = cog_with_targets, 123
    await cog.warframe.callback(cog, interaction, cible="lansier")
    args = interaction.response.send_message.call_args
    assert args.args[0].startswith("Connais pas cette cible. Tu voulais dire : ") and "Lancier (Lancer)" in args.args[0]
    assert args.kwargs["ephemeral"] is True


@pytest.mark.asyncio
async def test_warframe_unknown_target_without_suggestion(cog_with_targets, interaction):
    cog, interaction.channel_id = cog_with_targets, 123
    await cog.warframe.callback(cog, interaction, cible="xyz")
    assert interaction.response.send_message.call_args.args[0] == "Connais pas cette cible."


@pytest.mark.asyncio
async def test_warframe_target_data_missing(cog, interaction, settings_file):
    configure(settings_file, command_channel="123")
    interaction.channel_id = 123
    await cog.warframe.callback(cog, interaction, cible="lancer")
    args = interaction.response.send_message.call_args
    assert "pas dispo" in args.args[0] and args.kwargs["ephemeral"] is True


@pytest.mark.asyncio
async def test_warframe_target_wrong_channel(cog_with_targets, interaction):
    cog, interaction.channel_id = cog_with_targets, 999
    await cog.warframe.callback(cog, interaction, cible="lancer")
    assert interaction.response.send_message.call_args.args[0] == "Mauvais salon, utilise <#123>."


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{}, {"activite": choice("baro"), "cible": "lancer"}])
async def test_warframe_needs_exactly_one_parameter(cog_with_targets, interaction, kwargs):
    cog, interaction.channel_id = cog_with_targets, 123
    await cog.warframe.callback(cog, interaction, **kwargs)
    args = interaction.response.send_message.call_args
    assert "`activite`" in args.args[0] and args.kwargs["ephemeral"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("current", ["lancer", "lancier"])
async def test_target_autocomplete_in_both_languages(cog_with_targets, interaction, current):
    cog = cog_with_targets
    choices = await cog.target_autocomplete(interaction, current)
    assert choices[0].name == "Lancier (Lancer)" and choices[0].value == "Lancer"
    assert {choice.value for choice in choices} == {"Lancer", "Shield Lancer", "Corrupted Lancer"}


@pytest.mark.asyncio
async def test_target_autocomplete_without_data(cog, interaction):
    assert await cog.target_autocomplete(interaction, "lancer") == []


# --- /warframe_setup ---------------------------------------------------------------------------------------

def text_channel(channel_id: int):
    channel = MagicMock(id=channel_id, mention=f"<#{channel_id}>")
    ids = iter(range(1000, 2000))
    channel.send = AsyncMock(side_effect=lambda **kwargs: MagicMock(id=next(ids)))
    return channel


@pytest.mark.asyncio
async def test_setup_creates_messages(cog, interaction, settings_file):
    info, commands_channel = text_channel(10), text_channel(20)
    await cog.warframe_setup.callback(cog, interaction, info, commands_channel)
    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    assert interaction.followup.send.call_args.kwargs["ephemeral"] is True
    saved = config(settings_file)
    assert (saved["info_channel"], saved["command_channel"]) == ("10", "20")
    assert list(saved["messages"]) == list(TOPICS)
    assert sorted(saved["messages"].values()) == [str(i) for i in range(1000, 1008)]
    assert cog.wakeup.is_set()


@pytest.mark.asyncio
async def test_setup_same_channel_keeps_messages(cog, interaction, settings_file):
    configure(settings_file, info_channel="10", messages={t: str(i) for i, t in enumerate(TOPICS, 500)})
    info = text_channel(10)
    await cog.warframe_setup.callback(cog, interaction, info, text_channel(20))
    info.send.assert_not_awaited()
    assert config(settings_file)["messages"]["arbitrage"] == "500"


@pytest.mark.asyncio
async def test_setup_new_channel_deletes_old_messages(cog, bot, interaction, settings_file):
    configure(settings_file, info_channel="10", messages={t: str(i) for i, t in enumerate(TOPICS, 500)})
    old = MagicMock()
    old.get_partial_message.return_value.delete = AsyncMock(side_effect=[None, not_found()] + [None] * 6)
    bot.get_channel.return_value = old
    await cog.warframe_setup.callback(cog, interaction, text_channel(11), text_channel(20))
    assert old.get_partial_message.return_value.delete.await_count == 8  # un échec n'arrête pas le nettoyage
    assert config(settings_file)["info_channel"] == "11"
    assert "500" not in config(settings_file)["messages"].values()


# --- Publication -------------------------------------------------------------------------------------------

@pytest.fixture
def info_channel(bot, settings_file):
    configure(settings_file, info_channel="10", messages={t: str(i) for i, t in enumerate(TOPICS, 500)})
    channel = text_channel(10)
    channel.get_partial_message.return_value.edit = AsyncMock()
    bot.get_channel.return_value = channel
    return channel


def rendered(suffix=""):
    return {topic: [discord.Embed(title=label + suffix)] for topic, label in TOPICS.items()}


@pytest.mark.asyncio
async def test_publish_only_changed_messages(cog, info_channel, logs):
    edit = info_channel.get_partial_message.return_value.edit
    cog.rendered = rendered()
    await cog.publish()
    assert edit.await_count == 8  # premier tour : tout est mis à jour (rattrapage)
    await cog.publish()
    assert edit.await_count == 8  # rien n'a changé
    cog.rendered["baro"] = [discord.Embed(title="Baro est là")]
    await cog.publish()
    assert edit.await_count == 9
    info_channel.get_partial_message.assert_called_with(507)


@pytest.mark.asyncio
async def test_publish_recreates_deleted_message(cog, info_channel, settings_file, logs):
    info_channel.get_partial_message.return_value.edit = AsyncMock(side_effect=[not_found()] + [None] * 7)
    cog.rendered = rendered()
    await cog.publish()
    info_channel.send.assert_awaited_once()
    assert config(settings_file)["messages"]["arbitrage"] == "1000"
    assert config(settings_file)["messages"]["baro"] == "507"


@pytest.mark.asyncio
async def test_publish_without_configuration(cog, bot, settings_file):
    cog.rendered = rendered()
    await cog.publish()
    bot.get_channel.assert_not_called()


@pytest.mark.asyncio
async def test_publish_missing_channel_logged_once(cog, bot, settings_file, logs):
    configure(settings_file, info_channel="10")
    bot.get_channel.return_value = None
    bot.fetch_channel = AsyncMock(side_effect=not_found())
    cog.rendered = rendered()
    await cog.publish()
    await cog.publish()
    assert logs.await_count == 1


# --- Boucle --------------------------------------------------------------------------------------------------

@pytest.fixture
def ready(cog, schedule, translator):
    """Cog avec données de référence à jour : un tour ne touche qu'aux sources de browse.wf."""
    now = dt.datetime.now(dt.UTC)
    cog.translator, cog.translations_at = translator, now
    cog.schedule, cog.schedule_at = schedule, now
    cog.targets_at = now
    return cog


def fetch_with(sources, failing=(), error=None):
    """Faux browsewf.fetch : les sources de `failing` échouent, les autres renvoient les données réelles."""
    async def fetch(session, name):
        if name in failing:
            raise error or SourceError("timeout")
        return sources[name]
    return AsyncMock(side_effect=fetch)


def due(cog):
    for state in cog.sources.values():
        state.next_fetch = None


@pytest.mark.asyncio
async def test_tick_all_sources(ready, logs, settings_file, sources):
    fetch = fetch_with(sources)
    with patch.object(cog_module.browsewf, "fetch", fetch):
        await ready.tick()
    assert sorted(call.args[1] for call in fetch.await_args_list) == ["invasions", "primes", "worldstate"]
    assert ready.rendered["invasions"][0].fields and ready.rendered["fissures"][0].fields
    assert "Inconnu" not in ready.rendered["cycles"][0].fields[0].value
    logs.assert_not_awaited()  # rien d'inconnu, aucune panne


@pytest.mark.asyncio
async def test_one_source_down_does_not_touch_the_others(ready, logs, settings_file, sources):
    with patch.object(cog_module.browsewf, "fetch", fetch_with(sources)):
        await ready.tick()
    later = dt.datetime.now(dt.UTC) + dt.timedelta(minutes=5)
    with patch.object(cog_module.browsewf, "fetch", fetch_with(sources, failing={"invasions"})), \
            patch.object(cog_module, "utcnow", return_value=later):
        due(ready)
        await ready.tick()
        due(ready)
        await ready.tick()
    assert logs.await_count == 1  # une seule alerte pour la panne
    assert logs.call_args.args[1] == "invasions injoignable : timeout"
    assert logs.call_args.args[2] == "warframe_invasions"
    assert ready.sources["invasions"].failures == 2 and ready.sources["worldstate"].failures == 0
    assert ready.rendered["invasions"][0].fields                                 # anciennes données gardées
    assert "worldstate injoignable" in ready.rendered["invasions"][0].footer.text  # … et signalées
    assert ready.rendered["fissures"][0].footer.text is None                      # les autres sont à jour
    with patch.object(cog_module.browsewf, "fetch", fetch_with(sources)), \
            patch.object(cog_module, "utcnow", return_value=later + dt.timedelta(minutes=10)):
        due(ready)
        await ready.tick()
    assert logs.await_count == 2 and logs.call_args.args[1] == "invasions de nouveau joignable"


@pytest.mark.asyncio
async def test_all_sources_down_at_startup(ready, logs, settings_file, sources):
    with patch.object(cog_module.browsewf, "fetch", fetch_with(sources, failing=set(sources))):
        await ready.tick()
    assert logs.await_count == 3
    assert ready.rendered["fissures"][0].description == "Les données Warframe arrivent…"
    assert ready.rendered["invasions"][0].description == "Les données Warframe arrivent…"
    assert ready.rendered["cycles"][0].fields[0].value == "Inconnu pour le moment"
    assert "<t:" in ready.rendered["cycles"][0].fields[1].value  # la Vallée Orbis continue d'être calculée


@pytest.mark.asyncio
async def test_source_fetch_is_throttled(cog, logs, sources):
    now = dt.datetime.now(dt.UTC)
    fetch = fetch_with(sources)
    with patch.object(cog_module.browsewf, "fetch", fetch):
        await cog.refresh_source("worldstate", now)
        await cog.refresh_source("worldstate", now + dt.timedelta(seconds=1))  # réveil sur une échéance : pas de requête
        await cog.refresh_source("worldstate", now + dt.timedelta(seconds=59))
        assert fetch.await_count == 1
        await cog.refresh_source("worldstate", now + dt.timedelta(seconds=60))
        await cog.refresh_source("primes", now + dt.timedelta(seconds=1))      # chaque source a son propre rythme
    assert fetch.await_count == 3


@pytest.mark.asyncio
async def test_source_backoff_grows_then_resets(cog, logs, sources):
    now = dt.datetime.now(dt.UTC)
    waits, state = [], cog.sources["primes"]
    with patch.object(cog_module.browsewf, "fetch", fetch_with(sources, failing={"primes"}, error=SourceError("429"))):
        for _ in range(5):
            await cog.refresh_source("primes", now)
            waits.append((state.next_fetch - now).total_seconds() / 60)
            now = state.next_fetch
    assert waits == [1, 2, 5, 10, 10]
    with patch.object(cog_module.browsewf, "fetch", fetch_with(sources)):
        await cog.refresh_source("primes", now)
    assert state.failures == 0 and state.at == now
    assert state.next_fetch - now == dt.timedelta(seconds=cog_module.POLL_INTERVAL)


@pytest.mark.asyncio
@pytest.mark.parametrize("retry_after, expected", [(dt.timedelta(minutes=30), 30), (dt.timedelta(seconds=5), 1), (None, 1)])
async def test_source_backoff_honours_longer_retry_after(cog, logs, sources, retry_after, expected):
    now = dt.datetime.now(dt.UTC)
    with patch.object(cog_module.browsewf, "fetch", fetch_with(sources, {"worldstate"}, SourceError("429", retry_after))):
        await cog.refresh_source("worldstate", now)
    assert cog.sources["worldstate"].next_fetch - now == dt.timedelta(minutes=expected)


@pytest.mark.asyncio
async def test_unexpected_fetch_error_still_throttles(cog, logs):
    now = dt.datetime.now(dt.UTC)
    with patch.object(cog_module.browsewf, "fetch", AsyncMock(side_effect=RuntimeError("bug"))):
        with pytest.raises(RuntimeError):
            await cog.refresh_source("invasions", now)
    assert cog.sources["invasions"].next_fetch - now == dt.timedelta(seconds=cog_module.POLL_INTERVAL)


def test_no_more_warframestat_in_the_warframe_module():
    from pathlib import Path

    from warframe import MODULE_DIR
    files = [*MODULE_DIR.glob("*.py"), Path(cog_module.__file__)]
    assert all("warframestat.us" not in path.read_text(encoding="utf-8") for path in files)


# --- Traductions manquantes -----------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_translations_reported_once(ready, logs, settings_file, sources):
    alert = Alert(node="SolNode9999", mission="MT_DEFENSE", faction="FC_GRINEER", min_level=1, max_level=2, reward=Reward(),
                  tag="", expiry=dt.datetime.now(dt.UTC) + dt.timedelta(days=1))
    world = dataclasses.replace(sources["worldstate"], alerts=(alert,))
    with patch.object(cog_module.browsewf, "fetch", fetch_with({**sources, "worldstate": world})):
        await ready.tick()
        due(ready)
        await ready.tick()
    assert logs.await_count == 1
    message = logs.call_args.args[1]
    assert message.startswith("Traductions manquantes, à ajouter dans warframe/data/textes_fr.json :")
    assert "- alertes : `SolNode9999` → Sol Node9999" in message
    assert logs.call_args.args[2] == "warframe_traductions"


@pytest.mark.asyncio
async def test_overrides_loaded_at_startup(cog, logs, tmp_path, monkeypatch):
    monkeypatch.setattr(cog_module, "CACHE_DIR", tmp_path)
    await cog.load_caches()
    assert cog.overrides["invasion/FC_CORPUS"] == "Siège Corpus"
    assert cog.translator.text("invasion/FC_CORPUS") == "Siège Corpus"
    logs.assert_not_awaited()


@pytest.mark.asyncio
async def test_unreadable_overrides_are_reported(cog, logs, tmp_path, monkeypatch):
    broken = tmp_path / "textes_fr.json"
    broken.write_text("{", encoding="utf-8")
    monkeypatch.setattr(cog_module, "OVERRIDES", broken)
    monkeypatch.setattr(cog_module, "CACHE_DIR", tmp_path)
    await cog.load_caches()
    assert cog.overrides == {}
    assert "textes_fr.json illisible" in logs.call_args.args[1]


@pytest.mark.asyncio
async def test_reloaded_translations_keep_the_overrides(cog, logs):
    cog.overrides = {"/Lotus/X": "X"}
    with patch.object(cog_module.translations, "download_tables", AsyncMock(return_value={"nodes": {}})), \
            patch.object(cog_module.translations, "write_cache"):
        await cog.refresh_translations(dt.datetime.now(dt.UTC))
    assert cog.translator.text("/Lotus/X") == "X"


@pytest.mark.asyncio
async def test_reference_retry_is_throttled(cog, logs):
    now = dt.datetime.now(dt.UTC)
    cog.refresh_translations = AsyncMock(side_effect=cog_module.translations.TranslationError("down"))
    cog.refresh_schedule = AsyncMock()
    cog.refresh_targets = AsyncMock()
    await cog.refresh_reference(now)
    await cog.refresh_reference(now + dt.timedelta(minutes=5))
    assert cog.refresh_translations.await_count == 1  # pas de nouvel essai avant 10 min
    await cog.refresh_reference(now + dt.timedelta(minutes=11))
    assert cog.refresh_translations.await_count == 2


@pytest.mark.asyncio
async def test_targets_reload_every_seven_days(cog, logs):
    now = dt.datetime.now(dt.UTC)
    cog.translations_at = cog.schedule_at = now
    cog.refresh_targets = AsyncMock()
    cog.targets_at = now - dt.timedelta(days=6)
    await cog.refresh_reference(now)
    cog.refresh_targets.assert_not_awaited()
    cog.targets_at = now - dt.timedelta(days=8)
    await cog.refresh_reference(now)
    cog.refresh_targets.assert_awaited_once()


@pytest.mark.asyncio
async def test_targets_failure_keeps_data_and_logs_once(cog, logs, targets):
    now = dt.datetime.now(dt.UTC)
    cog.translations_at = cog.schedule_at = now
    cog.targets = targets
    failing = AsyncMock(side_effect=cog_module.synthesis.SynthesisError("wiki en panne"))
    with patch.object(cog_module.synthesis, "download", failing):
        await cog.refresh_reference(now)
        await cog.refresh_reference(now + dt.timedelta(minutes=5))   # pas de nouvel essai avant 10 min
        assert failing.await_count == 1
        await cog.refresh_reference(now + dt.timedelta(minutes=11))
    assert failing.await_count == 2
    assert cog.targets == targets
    assert logs.await_count == 1 and "cibles injoignable" in logs.call_args.args[1]


def test_delay_bounds(cog, sources, schedule, now):
    cog.sources["worldstate"].data, cog.schedule = sources["worldstate"], schedule
    assert 1 <= cog.delay(now) <= cog_module.POLL_INTERVAL
    hour_end = schedule.current(now).end
    assert cog.delay(hour_end - dt.timedelta(seconds=5)) <= 6  # réveil à l'heure pile


def test_delay_wakes_for_next_fetch(cog):
    now = dt.datetime.now(dt.UTC)
    cog.sources["invasions"].next_fetch = now + dt.timedelta(seconds=7)
    assert cog.delay(now) <= 7
    cog.sources["invasions"].next_fetch = now - dt.timedelta(seconds=7)  # requête en retard : pas de boucle serrée pour autant
    assert cog.delay(now) >= 1


# --- Horodatage ---------------------------------------------------------------------------------------------

def test_digest_ignores_timestamp():
    a, b = discord.Embed(title="x"), discord.Embed(title="x")
    a.timestamp, b.timestamp = dt.datetime(2026, 1, 1, tzinfo=dt.UTC), dt.datetime(2026, 6, 1, tzinfo=dt.UTC)
    assert cog_module.digest([a]) == cog_module.digest([b])


def test_stamp_changes_only_with_content(cog):
    t1, t2, t3 = (dt.datetime(2026, 11, 1, h, tzinfo=dt.UTC) for h in (10, 11, 12))
    cog.rendered = rendered()
    cog.stamp(t1)
    assert cog.rendered["baro"][0].timestamp == t1
    cog.rendered = rendered()          # nouveau tour, même contenu
    cog.stamp(t2)
    assert cog.rendered["baro"][0].timestamp == t1
    cog.rendered = rendered(" (changé)")
    cog.stamp(t3)
    assert cog.rendered["baro"][0].timestamp == t3


@pytest.mark.asyncio
async def test_stamped_content_is_not_republished(cog, info_channel, logs):
    edit = info_channel.get_partial_message.return_value.edit
    cog.rendered = rendered()
    cog.stamp(dt.datetime(2026, 11, 1, 10, tzinfo=dt.UTC))
    await cog.publish()
    cog.rendered = rendered()
    cog.stamp(dt.datetime(2026, 11, 1, 11, tzinfo=dt.UTC))
    await cog.publish()
    assert edit.await_count == 8  # l'horodatage seul ne déclenche pas de modification
