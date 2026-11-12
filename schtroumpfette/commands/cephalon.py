"""Cog Cephalon : /cephalon (une question sur Warframe), /cephalon_build (avis sur un build), /cephalon_pages.

Module indépendant : le retirer de `cogs` (main.py) suffit à le couper.
"""
import asyncio
import datetime as dt
import os
import time

import aiohttp
import anthropic
import discord
from discord import app_commands
from discord.ext import commands

from cephalon import STATE_DIR, build, limits, llm, persona, render
from cephalon.config import (IMAGE_MAX_BYTES, INDEX_MAX_AGE, INDEX_RETRY, LLM_RETRIES, LLM_TIMEOUT, Config, command_channel,
                             read_config)
from cephalon.image import ImageError, prepare
from cephalon.index import Index, IndexError_
from cephalon.pages import Pages, PagesError, Report
from cephalon.warframe_api import WarframeApi, WarframeApiError
from client.errors import report_error
from commands.moderation.twitch_cmd import MODO_ROLES

API_KEY = "ANTHROPIC_API_KEY"
BUDGET_ORIGIN = "cephalon : budget"
INDEX_ORIGIN = "cephalon : index"
PAGES_ORIGIN = "cephalon : pages"
BUILD_ORIGIN = "cephalon : build"
PAGES_DIR = "pages"  # dossier de dépôt des exports du wiki, dans le dossier d'état


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def euros(amount: float) -> str:
    return f"{amount:.2f}".replace(".", ",") + " €"


class MissingKeyError(Exception):
    def __init__(self):
        super().__init__(f"{API_KEY} absente du .env")


def describe(error: Exception) -> str:
    """Texte d'une erreur de l'API Anthropic sans l'identifiant de requête : il change à chaque appel, et
    l'anti-spam du salon de logs compare les textes."""
    if isinstance(error, anthropic.APIStatusError):
        body = error.body if isinstance(error.body, dict) else {}
        detail = (body.get("error") or {}).get("message") or type(error).__name__
        return f"{error.status_code} {detail}"
    return str(error) or type(error).__name__


class Cephalon(commands.Cog):
    """Questions sur Warframe."""

    def __init__(self, bot):
        self.bot = bot
        self.session: aiohttp.ClientSession | None = None
        self.api: WarframeApi | None = None
        self.claude: anthropic.AsyncAnthropic | None = None  # créé à la première question
        self.limits = limits.Limits(STATE_DIR)
        self.load_error: Exception | None = None  # état illisible au chargement : signalé à la première question
        self.index_dir = STATE_DIR
        self.index_task: asyncio.Task | None = None
        self.index_failing = False                # panne de l'index déjà signalée (un seul log par panne)
        self.pages_lock = asyncio.Lock()          # un seul traitement des pages à la fois
        self.pages_error: Exception | None = None  # pages.json illisible au chargement : signalé plus tard

    async def cog_load(self):
        self.session = aiohttp.ClientSession()
        self.api = WarframeApi(self.session)
        try:
            await asyncio.to_thread(self.limits.load)
        except limits.StateError as error:  # compteurs à zéro ; le salon de logs n'est pas encore joignable
            self.load_error = error
        await self.read_pages()
        self.index_task = asyncio.create_task(self.keep_index(), name="cephalon_index")

    async def cog_unload(self):
        if self.index_task:
            self.index_task.cancel()
        if self.session:
            await self.session.close()
        if self.claude:
            await self.claude.close()

    # --- Index local --------------------------------------------------------------------------------------

    async def keep_index(self):
        """Tâche de fond : relit l'index du disque, le reconstruit s'il a plus d'un jour, puis une fois par jour.

        Le bot répond sans attendre : tant que l'index n'est pas prêt, les fiches passent par l'API en direct."""
        await self.read_index()
        while True:
            index = self.api.index
            age = index.age(utcnow()) if index else INDEX_MAX_AGE
            if age < INDEX_MAX_AGE:
                await asyncio.sleep(INDEX_MAX_AGE - age)
            elif not await self.refresh_index():
                await asyncio.sleep(INDEX_RETRY)

    async def read_index(self) -> None:
        try:
            index = await asyncio.to_thread(Index.read, self.index_dir)
        except IndexError_ as error:  # fichier ignoré : l'index sera téléchargé
            await report_error(self.bot, error, INDEX_ORIGIN)
            return
        if index:
            self.api.index = index
            print(f"[cephalon] index : {index.summary()} (lu du disque)", flush=True)

    async def refresh_index(self) -> bool:
        """Télécharge les listes et reconstruit l'index. En cas d'échec, l'index précédent reste en service."""
        started = time.perf_counter()
        try:
            lists = await self.api.download_lists()
            index = await asyncio.to_thread(Index.build, lists, utcnow())
        except (WarframeApiError, IndexError_) as error:
            if not self.index_failing:
                self.index_failing = True
                await report_error(self.bot, f"index non mis à jour : {error}", INDEX_ORIGIN)
            return False
        self.api.index = index
        seconds = f"{time.perf_counter() - started:.1f}".replace(".", ",")
        print(f"[cephalon] index : {index.summary()} (téléchargé en {seconds} s)", flush=True)
        if self.index_failing:
            self.index_failing = False
            await report_error(self.bot, "index de nouveau à jour", INDEX_ORIGIN)
        try:
            await asyncio.to_thread(index.write, self.index_dir)
        except OSError as error:  # l'index reste en mémoire
            await report_error(self.bot, f"index non écrit sur disque : {error}", INDEX_ORIGIN)
        return True

    # --- Pages du wiki ------------------------------------------------------------------------------------

    async def read_pages(self) -> None:
        try:
            pages = await asyncio.to_thread(Pages.read, self.index_dir)
        except PagesError as error:  # aucune page ; le salon de logs n'est pas encore joignable
            self.pages_error = error
            return
        if pages:
            self.api.pages = pages
            print(f"[cephalon] pages : {pages.summary()} (lu du disque)", flush=True)

    async def report_pages_error(self) -> None:
        if self.pages_error:
            error, self.pages_error = self.pages_error, None
            await report_error(self.bot, error, PAGES_ORIGIN)

    def reload_pages(self) -> tuple[Pages | None, Report]:
        """Traitement complet, dans un thread : rien ne change (None) en cas d'échec total."""
        pages, report = Pages.reload(self.index_dir / PAGES_DIR, self.api.pages)
        if pages is not None:
            try:
                pages.write(self.index_dir)
            except OSError as error:  # disque et mémoire restent cohérents : rien ne change
                report.fatal = f"écriture de pages.json impossible : {error}"
                return None, report
        return pages, report

    @app_commands.command(name="cephalon_pages", description="Recharge les pages du wiki déposées pour la Cephalon")
    @app_commands.checks.has_any_role(*MODO_ROLES)
    async def cephalon_pages(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.report_pages_error()
        async with self.pages_lock:
            pages, report = await asyncio.to_thread(self.reload_pages)
            if pages is not None:
                self.api.pages = pages  # remplacement d'un coup : une question en cours garde l'ancien ensemble
        print(f"[cephalon] pages : {report.pages} pages, {report.sections} sections, {len(report.problems)} problèmes"
              + (f", échec : {report.fatal}" if report.fatal else ""), flush=True)
        embed = render.pages_report(report, interaction.user.mention)
        await interaction.followup.send(embed=embed, ephemeral=True)
        channel = getattr(self.bot, "logs_channel", None)
        if channel is None:
            await report_error(self.bot, "salon de logs introuvable pour le rapport des pages", PAGES_ORIGIN)
        else:
            await channel.send(embed=embed)

    # --- Questions ----------------------------------------------------------------------------------------

    def claude_client(self) -> anthropic.AsyncAnthropic:
        """Clé absente : le bot démarre quand même, c'est la question qui échoue."""
        if self.claude is None:
            if not os.getenv(API_KEY):
                raise MissingKeyError()
            self.claude = anthropic.AsyncAnthropic(timeout=LLM_TIMEOUT, max_retries=LLM_RETRIES)
        return self.claude

    @staticmethod
    async def right_channel(interaction: discord.Interaction) -> bool:
        """Le salon des commandes Warframe ; sinon une réponse éphémère et False."""
        channel = command_channel()
        if channel is None:
            await interaction.response.send_message("Le module Warframe n'est pas encore configuré.", ephemeral=True)
            return False
        if interaction.channel_id != channel:
            await interaction.response.send_message(f"Mauvais salon, utilise <#{channel}>.", ephemeral=True)
            return False
        return True

    @app_commands.command(name="cephalon", description="Pose une question sur Warframe à la Cephalon Schtroumpfette")
    @app_commands.describe(question="Ta question : un mod, une arme, une Warframe, où farmer un objet…")
    async def cephalon(self, interaction: discord.Interaction, question: app_commands.Range[str, 1, 500]):
        if not await self.right_channel(interaction):
            return
        config = read_config()
        refusal = self.limits.check(interaction.user.id, config, utcnow())
        if refusal:
            await interaction.response.send_message(self.refusal_message(refusal, config), ephemeral=True)
            return
        await interaction.response.defer()
        await interaction.followup.send(embed=await self.answer(interaction.user.id, question, config))

    @staticmethod
    def refusal_message(refusal: limits.Refusal, config: Config, kind: str = limits.QUESTION) -> str:
        if refusal.kind == limits.BUDGET:
            return persona.BUDGET_MESSAGE
        if refusal.kind == limits.QUOTA:
            if kind == limits.BUILD:
                return persona.build_quota_message(config.build_daily)
            return persona.quota_message(config.daily_questions)
        return persona.cooldown_message(refusal.seconds)

    async def answer(self, user_id: int, question: str, config: Config) -> discord.Embed:
        """L'embed de réponse, ou l'embed de repli avec l'erreur envoyée dans le salon de logs."""
        usage, result = llm.Usage(), None
        try:
            result = await llm.ask(self.claude_client(), self.api, question, config, usage)
        except WarframeApiError as error:
            await report_error(self.bot, error, "cephalon : warframestat")
        except (anthropic.AnthropicError, MissingKeyError) as error:
            await report_error(self.bot, describe(error), "cephalon")
        answered = result is not None and result.status == llm.OK
        # Les tokens des tours déjà faits sont facturés même si la question finit en panne.
        outcome = await self.record(user_id, usage, answered, config)
        if result is None:
            return render.fallback(question, persona.error_message())
        print(f"[cephalon] {user_id} : {result.rounds} tours, entrée {usage.input} (cache lu {usage.cache_read}, "
              f"écrit {usage.cache_write}), sortie {usage.output}, modèle {config.model}", flush=True)
        if result.status == llm.REFUSAL:
            await report_error(self.bot, "question refusée par le modèle", "cephalon")
            return render.fallback(question, persona.error_message())
        if result.status == llm.ROUNDS:
            return render.fallback(question, persona.ROUNDS_MESSAGE)
        return render.answer(question, result.text, result.sources, outcome.remaining, wiki=result.wiki)

    # --- Builds -------------------------------------------------------------------------------------------

    @app_commands.command(name="cephalon_build",
                          description="Montre ton build à la Cephalon Schtroumpfette (capture de l'écran de configuration)")
    @app_commands.describe(image="Capture de l'écran de configuration (mods) d'une Warframe, d'une arme ou d'un compagnon",
                           question="Facultatif : ce que tu veux savoir (« build pour l'Acier ? », « critique ou statut ? »)")
    async def cephalon_build(self, interaction: discord.Interaction, image: discord.Attachment,
                             question: app_commands.Range[str, 1, 300] | None = None):
        if not await self.right_channel(interaction):
            return
        if not (image.content_type or "").startswith("image/"):
            await interaction.response.send_message(persona.NOT_AN_IMAGE_MESSAGE, ephemeral=True)
            return
        if image.size > IMAGE_MAX_BYTES:
            await interaction.response.send_message(persona.IMAGE_TOO_BIG_MESSAGE.format(
                size=round(image.size / 1024 / 1024), limit=IMAGE_MAX_BYTES // 1024 // 1024), ephemeral=True)
            return
        config = read_config()
        refusal = self.limits.check(interaction.user.id, config, utcnow(), kind=limits.BUILD)
        if refusal:
            await interaction.response.send_message(self.refusal_message(refusal, config, limits.BUILD), ephemeral=True)
            return
        await interaction.response.defer()
        await interaction.followup.send(embed=await self.analyze_build(interaction.user.id, image, question, config))

    async def analyze_build(self, user_id: int, attachment: discord.Attachment, question: str | None,
                            config: Config) -> discord.Embed:
        """Lecture de la capture, vérification de chaque carte par le code, puis analyse. Repli en cas de panne."""
        title, thumbnail = question or render.BUILD_TITLE, attachment.url
        try:
            image = await asyncio.to_thread(prepare, await attachment.read())
        except ImageError:  # pas d'appel à Claude : rien à compter
            return render.fallback(title, persona.UNREADABLE_IMAGE_MESSAGE, thumbnail)
        except discord.HTTPException as error:
            await report_error(self.bot, f"capture non téléchargée : {error}", BUILD_ORIGIN)
            return render.fallback(title, persona.error_message(), thumbnail)
        reader_usage, usage, reading, checked, result = llm.Usage(), llm.Usage(), None, [], None
        try:
            client = self.claude_client()
            reading = await build.read_build(client, image, config, reader_usage)
            if build.is_build(reading):
                checked = await build.verify(self.api, reading)
                result = await llm.ask(client, self.api, build.payload(reading, checked, question), config, usage,
                                       profile=build.profile(config))
        except WarframeApiError as error:
            await report_error(self.bot, error, "cephalon : warframestat")
        except (anthropic.AnthropicError, MissingKeyError) as error:
            await report_error(self.bot, describe(error), "cephalon")
        except build.BuildError as error:
            await report_error(self.bot, error, BUILD_ORIGIN)
        answered = result is not None and result.status == llm.OK
        # Les tokens déjà facturés (lecture comprise) comptent même si le build finit en panne ou hors sujet.
        outcome = await self.record(user_id, usage, answered, config, kind=limits.BUILD, model=config.build_model,
                                    extra=[(config.build_reader_model, reader_usage)])
        verified = sum(item.status == build.VERIFIED for item in checked)
        dollars = limits.cost(config.build_reader_model, reader_usage)[0] + limits.cost(config.build_model, usage)[0]
        print(f"[cephalon] build {user_id} : image {image.summary()}, {len(checked)} cartes ({verified} vérifiées), "
              f"lecture entrée {reader_usage.input} sortie {reader_usage.output} ({config.build_reader_model}), "
              f"analyse {result.rounds if result else 0} tours entrée {usage.input} (cache lu {usage.cache_read}, "
              f"écrit {usage.cache_write}) sortie {usage.output} ({config.build_model}), "
              f"coût {euros(dollars * config.usd_to_eur)}", flush=True)
        if reading is not None and not build.is_build(reading):
            return render.fallback(title, persona.NOT_A_BUILD_MESSAGE, thumbnail)
        if result is None:
            return render.fallback(title, persona.error_message(), thumbnail)
        if result.status == llm.REFUSAL:
            await report_error(self.bot, "build refusé par le modèle", BUILD_ORIGIN)
            return render.fallback(title, persona.error_message(), thumbnail)
        if result.status == llm.ROUNDS:
            return render.fallback(title, persona.ROUNDS_MESSAGE, thumbnail)
        sources = build.sources(checked)
        llm.add_sources(sources, result.sources)
        return render.build_answer(question, result.text, sources, outcome.remaining, thumbnail)

    # --- Comptes --------------------------------------------------------------------------------------------

    async def record(self, user_id: int, usage: llm.Usage, answered: bool, config: Config, kind: str = limits.QUESTION,
                     model: str | None = None, extra: list[tuple[str, llm.Usage]] = ()) -> limits.Outcome:
        """Compte la demande, écrit l'état et signale ce qui doit l'être dans le salon de logs.

        `extra` : appels déjà faits sur d'autres modèles (lecture d'une capture), ajoutés au budget."""
        await self.report_pages_error()
        if self.load_error:
            error, self.load_error = self.load_error, None
            await report_error(self.bot, f"{error} — compteurs remis à zéro", BUDGET_ORIGIN)
        model = model or config.model
        unknown = [name for name, extra_usage in extra if not self.limits.add_cost(name, extra_usage, utcnow())]
        outcome = self.limits.record(user_id, model, usage, answered, config, utcnow(), kind=kind)
        if outcome.unknown_model:
            unknown.append(model)
        try:
            await asyncio.to_thread(self.limits.save)
        except OSError as error:  # les compteurs continuent en mémoire
            await report_error(self.bot, f"état des limites non écrit : {error}", BUDGET_ORIGIN)
        for name in dict.fromkeys(unknown):
            await report_error(self.bot, f"prix inconnu pour le modèle {name} : coût compté au tarif le plus cher",
                               BUDGET_ORIGIN)
        spent = f"{euros(outcome.spent)} sur {euros(config.monthly_budget)}"
        for threshold in outcome.alerts:
            if threshold >= 100:
                text = f"Budget mensuel atteint : {spent}. /cephalon est fermé jusqu'au 1er du mois."
            else:
                text = f"{threshold} % du budget mensuel atteint : {spent}"
            await report_error(self.bot, text, BUDGET_ORIGIN)
        return outcome


async def setup(bot):  # pragma: no cover
    await bot.add_cog(Cephalon(bot))
