"""Cog Warframe : salon d'info mis à jour en continu + commande /warframe.

Une seule boucle « recalcule et compare » : à chaque tour, on récupère le worldstate, on recalcule les embeds
de chaque sujet et on ne modifie que les messages dont le contenu a changé. La boucle se réveille au plus
tard toutes les 30 s, ou plus tôt à la prochaine échéance connue (fin d'arbitrage, de cycle…).
"""
import asyncio
import datetime as dt
import hashlib
import json
import time

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from client.event_logs import event_logs
from commands.moderation.twitch_cmd import MODO_ROLES
from utils.file_management import settings_file_management
from warframe import CACHE_DIR, DATA_DIR, arbitrations, emojis, synthesis, translations
from warframe.render import TOPICS, Context, next_deadline, render_all, render_synthesis
from warframe.worldstate import WorldstateError, fetch_worldstate

SETTINGS_KEY = "warframe"
POLL_INTERVAL = 60          # secondes entre deux consultations du worldstate (et entre deux recalculs des embeds, au plus)
# Attente après 1, 2, 3, 4+ échecs d'affilée : aucune limite n'est publiée, on lève le pied dès que l'API refuse ou tombe.
FETCH_BACKOFF = tuple(dt.timedelta(minutes=minutes) for minutes in (1, 2, 5, 10))
STALE_AFTER = dt.timedelta(minutes=2)
RETRY_REFERENCE = dt.timedelta(minutes=10)  # délai entre deux essais de téléchargement des données de référence
STATS_EVERY = dt.timedelta(hours=1)


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def digest(embeds: list[discord.Embed]) -> str:
    """Empreinte du contenu, sans l'horodatage (sinon chaque tour verrait un « changement »)."""
    content = [{k: v for k, v in e.to_dict().items() if k != "timestamp"} for e in embeds]
    return hashlib.sha1(json.dumps(content, sort_keys=True).encode()).hexdigest()


def read_config() -> dict:
    try:
        config = settings_file_management.get_entry(main_key=SETTINGS_KEY) or {}
    except (KeyError, TypeError):
        config = {}
    config.setdefault("info_channel", "")
    config.setdefault("command_channel", "")
    config["messages"] = {topic: (config.get("messages") or {}).get(topic, "") for topic in TOPICS}
    return config


def write_config(config: dict) -> None:
    settings_file_management.update_entry(main_key=SETTINGS_KEY, new_data=config)


class Warframe(commands.Cog):
    """Infos du monde de Warframe."""

    def __init__(self, bot):
        self.bot = bot
        self.translator = translations.Translator()
        self.translations_at: dt.datetime | None = None
        self.schedule = arbitrations.Schedule()
        self.schedule_at: dt.datetime | None = None
        self.tiers = arbitrations.load_tiers(DATA_DIR / "arbitration_tiers.json")
        self.tier_emojis = arbitrations.load_tier_emojis(DATA_DIR / "arbitration_tiers.json")
        self.faction_emojis: dict[str, str] = {}  # faction du worldstate -> emoji ; vide = ⚔️ / 🛡️ dans les invasions
        self.worldstate: dict | None = None
        self.worldstate_at: dt.datetime | None = None
        self.rendered: dict[str, list[discord.Embed]] = {}
        self.published: dict[str, str] = {}   # sujet -> empreinte du dernier contenu publié
        self.changed_at: dict[str, tuple[str, dt.datetime]] = {}  # sujet -> (empreinte, heure du dernier changement)
        self.failing: set[str] = set()        # sources en panne déjà signalées (un seul log par panne)
        self.targets: dict[str, tuple[str, ...]] = {}  # cibles de synthèse : nom anglais -> lieux
        self.targets_at: dt.datetime | None = None
        self.next_reference_try: dict[str, dt.datetime] = {}
        self.next_fetch: dt.datetime | None = None  # pas de requête worldstate avant cette heure
        self.fetch_failures = 0               # échecs d'affilée du worldstate
        self.stats = {"tours": 0, "total": 0.0, "max": 0.0, "since": utcnow()}
        self.session: aiohttp.ClientSession | None = None
        self.wakeup = asyncio.Event()
        self.task: asyncio.Task | None = None

    async def cog_load(self):
        self.session = aiohttp.ClientSession()
        self.task = asyncio.create_task(self.run(), name="warframe_loop")

    async def cog_unload(self):
        if self.task:
            self.task.cancel()
        if self.session:
            await self.session.close()

    # --- Logs -------------------------------------------------------------------------------------------

    async def log(self, error, origine: str):
        channel = self.bot.get_channel(int(self.bot.logs_channel_id)) if getattr(self.bot, "logs_channel_id", None) else None
        await event_logs.on_error_log(self.bot, error, origine=origine, channel=channel)

    async def report(self, source: str, error: Exception | None):
        """Signale une panne une seule fois, puis son rétablissement."""
        if error is not None and source not in self.failing:
            self.failing.add(source)
            await self.log(f"{source} injoignable : {error}", origine=f"warframe_{source}")
        elif error is None and source in self.failing:
            self.failing.discard(source)
            await self.log(f"{source} de nouveau joignable", origine=f"warframe_{source}")

    # --- Boucle -----------------------------------------------------------------------------------------

    async def run(self):
        await self.bot.wait_until_ready()
        await self.load_caches()
        await self.sync_emojis()
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # la boucle ne doit jamais s'arrêter
                await self.log(f"{type(error).__name__}: {error}", origine="warframe_loop")
            try:
                await asyncio.wait_for(self.wakeup.wait(), timeout=self.delay(utcnow()))
            except TimeoutError:
                pass
            self.wakeup.clear()

    async def sync_emojis(self):
        """Emojis de tier et de faction : créés / retrouvés comme emojis d'application à partir de warframe/data/emojis/.
        En cas d'échec, on garde les emojis du fichier de tiers (carrés de couleur par défaut) et ⚔️ / 🛡️."""
        try:
            managed = await emojis.sync_emojis(self.bot)
        except (discord.DiscordException, OSError, ValueError) as error:
            await self.report("emojis", error)
            return
        self.tier_emojis = {**self.tier_emojis, **{key: managed[key] for key in emojis.TIERS if key in managed}}
        self.faction_emojis = {key: managed[key] for key in emojis.FACTIONS if key in managed}
        self.published.clear()  # republier l'arbitrage et les invasions avec les nouveaux emojis

    async def load_caches(self):
        cached = await asyncio.to_thread(translations.read_cache, CACHE_DIR)
        if cached:
            self.translator, self.translations_at = cached
        cached = await asyncio.to_thread(arbitrations.read_cache, CACHE_DIR)
        if cached:
            self.schedule, self.schedule_at = cached
        cached = await asyncio.to_thread(synthesis.read_cache, CACHE_DIR)
        if cached:
            self.targets, self.targets_at = cached

    def context(self, now: dt.datetime) -> Context:
        stale = self.worldstate_at is not None and now - self.worldstate_at > STALE_AFTER
        return Context(now=now, tr=self.translator, worldstate=self.worldstate, worldstate_at=self.worldstate_at,
                       stale=stale, schedule=self.schedule, tiers=self.tiers, tier_emojis=self.tier_emojis,
                       faction_emojis=self.faction_emojis)

    def delay(self, now: dt.datetime) -> float:
        """Temps avant le prochain tour : échéance à afficher ou requête à faire, selon ce qui vient en premier."""
        delay = POLL_INTERVAL
        deadline = next_deadline(self.context(now))
        if deadline is not None:
            delay = min(delay, (deadline - now).total_seconds() + 1)
        if self.next_fetch is not None and self.next_fetch > now:
            delay = min(delay, (self.next_fetch - now).total_seconds())
        return max(1.0, delay)

    async def tick(self):
        started = time.monotonic()
        now = utcnow()
        await self.refresh_reference(now)
        await self.refresh_worldstate(now)
        self.rendered = render_all(self.context(utcnow()))
        self.stamp(utcnow())
        await self.publish()
        self.record(time.monotonic() - started)

    async def refresh_worldstate(self, now: dt.datetime):
        """Une requête au plus toutes les POLL_INTERVAL secondes, quel que soit le nombre de tours de la boucle."""
        if self.next_fetch is not None and now < self.next_fetch:
            return
        self.next_fetch = now + dt.timedelta(seconds=POLL_INTERVAL)  # posé avant l'appel : vaut aussi pour une erreur imprévue
        try:
            self.worldstate = await fetch_worldstate(self.session)
        except WorldstateError as error:
            backoff = FETCH_BACKOFF[min(self.fetch_failures, len(FETCH_BACKOFF) - 1)]
            self.fetch_failures += 1
            self.next_fetch = now + max(backoff, error.retry_after or backoff)
            await self.report("worldstate", error)
            return
        self.worldstate_at = now
        self.fetch_failures = 0
        await self.report("worldstate", None)

    async def refresh_reference(self, now: dt.datetime):
        """Traductions (24 h), planning des arbitrages et cibles de synthèse (7 j), avec un nouvel essai au plus
        toutes les 10 min."""
        jobs = [("traductions", self.translations_at, translations.MAX_AGE, self.refresh_translations),
                ("planning", self.schedule_at, arbitrations.MAX_AGE, self.refresh_schedule),
                ("cibles", self.targets_at, synthesis.MAX_AGE, self.refresh_targets)]
        for name, loaded_at, max_age, refresh in jobs:
            if loaded_at and now - loaded_at < max_age:
                continue
            if now < self.next_reference_try.get(name, now):
                continue
            self.next_reference_try[name] = now + RETRY_REFERENCE
            try:
                await refresh(now)
                await self.report(name, None)
            except (translations.TranslationError, arbitrations.ScheduleError, synthesis.SynthesisError, OSError) as error:
                await self.report(name, error)

    async def refresh_translations(self, now: dt.datetime):
        tables = await translations.download_tables(self.session)
        await asyncio.to_thread(translations.write_cache, CACHE_DIR, tables, now)
        self.translator, self.translations_at = translations.Translator(tables), now

    async def refresh_schedule(self, now: dt.datetime):
        self.schedule = await arbitrations.download_schedule(self.session, CACHE_DIR)
        self.schedule_at = now

    async def refresh_targets(self, now: dt.datetime):
        self.targets = await synthesis.download(self.session, CACHE_DIR)
        self.targets_at = now

    def record(self, duration: float):
        stats = self.stats
        stats["tours"] += 1
        stats["total"] += duration
        stats["max"] = max(stats["max"], duration)
        if utcnow() - stats["since"] >= STATS_EVERY:
            print(f"[warframe] {stats['tours']} tours, moyenne {stats['total'] / stats['tours']:.2f} s, "
                  f"max {stats['max']:.2f} s", flush=True)
            self.stats = {"tours": 0, "total": 0.0, "max": 0.0, "since": utcnow()}

    # --- Salon d'info -----------------------------------------------------------------------------------

    async def info_channel(self, config: dict) -> discord.abc.Messageable | None:
        if not config["info_channel"]:
            return None
        channel_id = int(config["info_channel"])
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden) as error:
                await self.report("salon d'info", error)
                return None
        await self.report("salon d'info", None)
        return channel

    def stamp(self, now: dt.datetime):
        """Horodatage de chaque embed = heure du dernier changement de contenu du sujet (affiché par Discord
        en pied de page, dans le fuseau de chaque membre). Un contenu inchangé garde son heure."""
        for topic, embeds in self.rendered.items():
            fingerprint = digest(embeds)
            previous = self.changed_at.get(topic)
            if previous is None or previous[0] != fingerprint:
                self.changed_at[topic] = previous = (fingerprint, now)
            for embed in embeds:
                embed.timestamp = previous[1]

    async def publish(self):
        """Modifie les messages dont le contenu a changé ; recrée ceux qui ont disparu."""
        config = read_config()
        channel = await self.info_channel(config)
        if channel is None:
            return
        messages, recreated = config["messages"], False
        for topic in TOPICS:
            embeds = self.rendered.get(topic)
            if not embeds:
                continue
            fingerprint = digest(embeds)
            if self.published.get(topic) == fingerprint:
                continue
            if not await self.edit_message(channel, messages.get(topic), embeds):
                message = await channel.send(embeds=embeds)
                messages[topic] = str(message.id)
                recreated = True
            self.published[topic] = fingerprint
        if recreated:
            write_config(config)

    @staticmethod
    async def edit_message(channel, message_id: str, embeds: list[discord.Embed]) -> bool:
        """Modifie le message ; False s'il n'existe pas (jamais créé ou supprimé à la main)."""
        if not message_id:
            return False
        try:
            await channel.get_partial_message(int(message_id)).edit(content=None, embeds=embeds)
        except discord.NotFound:
            return False
        return True

    # --- Commandes --------------------------------------------------------------------------------------

    @app_commands.command(name="warframe", description="Événements, alertes, timers et cibles de synthèse de Warframe")
    @app_commands.describe(activite="Les événements, alertes et timers en cours",
                           cible="La cible de synthèse à chercher, en français ou en anglais")
    @app_commands.choices(activite=[app_commands.Choice(name=label, value=topic) for topic, label in TOPICS.items()])
    async def warframe(self, interaction: discord.Interaction, activite: app_commands.Choice[str] | None = None,
                       cible: str | None = None):
        config = read_config()
        if not config["command_channel"]:
            await interaction.response.send_message("Le module Warframe n'est pas encore configuré.", ephemeral=True)
            return
        if interaction.channel_id != int(config["command_channel"]):
            await interaction.response.send_message(f"Mauvais salon, utilise <#{config['command_channel']}>.",
                                                    ephemeral=True)
            return
        if (activite is None) == (cible is None):
            await interaction.response.send_message("Choisis une `activite` ou une `cible`, mais pas les deux.", ephemeral=True)
            return
        if cible is not None:
            await self.answer_target(interaction, cible)
            return
        embeds = self.rendered.get(activite.value)
        if not embeds:
            await interaction.response.send_message("Les données Warframe arrivent, réessaie dans quelques secondes.",
                                                    ephemeral=True)
            return
        await interaction.response.send_message(embeds=embeds)

    @warframe.autocomplete("cible")
    async def target_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return [app_commands.Choice(name=synthesis.label(self.translator, name), value=name)
                for name in synthesis.search(self.targets, self.translator, current)]

    async def answer_target(self, interaction: discord.Interaction, query: str):
        if not self.targets:
            await interaction.response.send_message("Les données de synthèse ne sont pas dispo pour l'instant, réessaie plus tard.",
                                                    ephemeral=True)
            return
        name = synthesis.find(self.targets, self.translator, query)
        if name is None:
            close = synthesis.suggest(self.targets, self.translator, query)
            hint = f" Tu voulais dire : {', '.join(close)} ?" if close else ""
            await interaction.response.send_message(f"Connais pas cette cible.{hint}", ephemeral=True)
            return
        await interaction.response.send_message(embed=render_synthesis(self.translator, name, self.targets[name]), ephemeral=True)

    @app_commands.command(name="warframe_setup", description="Configure les salons Warframe")
    @app_commands.describe(salon_info="Salon où les infos sont mises à jour en continu",
                           salon_commandes="Salon où /warframe est autorisée")
    @app_commands.checks.has_any_role(*MODO_ROLES)
    async def warframe_setup(self, interaction: discord.Interaction, salon_info: discord.TextChannel,
                             salon_commandes: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        config = read_config()
        messages = config["messages"]
        if config["info_channel"] and config["info_channel"] != str(salon_info.id):
            await self.delete_messages(config["info_channel"], messages)
            messages = {topic: "" for topic in TOPICS}
        placeholder = [discord.Embed(title=label, description="Chargement…") for label in TOPICS.values()]
        for (topic, _), fallback in zip(TOPICS.items(), placeholder):
            if not messages.get(topic):
                message = await salon_info.send(embeds=self.rendered.get(topic) or [fallback])
                messages[topic] = str(message.id)
        config.update(info_channel=str(salon_info.id), command_channel=str(salon_commandes.id), messages=messages)
        write_config(config)
        self.published.clear()  # tout republier au prochain tour
        self.wakeup.set()
        await interaction.followup.send(
            f"Salons Warframe configurés : infos dans {salon_info.mention}, commandes dans {salon_commandes.mention}.",
            ephemeral=True)

    async def delete_messages(self, channel_id: str, messages: dict):
        channel = self.bot.get_channel(int(channel_id))
        if channel is None:
            return
        for message_id in filter(None, messages.values()):
            try:
                await channel.get_partial_message(int(message_id)).delete()
            except discord.HTTPException:
                pass  # déjà supprimé ou plus accessible


async def setup(bot):  # pragma: no cover
    await bot.add_cog(Warframe(bot))
