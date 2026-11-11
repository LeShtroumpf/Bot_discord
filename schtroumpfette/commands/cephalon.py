"""Cog Cephalon : /cephalon, une question sur Warframe posée à la Cephalon Schtroumpfette.

Module indépendant : le retirer de `cogs` (main.py) suffit à le couper.
"""
import asyncio
import datetime as dt
import os

import aiohttp
import anthropic
import discord
from discord import app_commands
from discord.ext import commands

from cephalon import STATE_DIR, limits, llm, persona, render
from cephalon.config import LLM_RETRIES, LLM_TIMEOUT, Config, command_channel, read_config
from cephalon.warframe_api import WarframeApi, WarframeApiError
from client.errors import report_error

API_KEY = "ANTHROPIC_API_KEY"
BUDGET_ORIGIN = "cephalon : budget"


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

    async def cog_load(self):
        self.session = aiohttp.ClientSession()
        self.api = WarframeApi(self.session)
        try:
            await asyncio.to_thread(self.limits.load)
        except limits.StateError as error:  # compteurs à zéro ; le salon de logs n'est pas encore joignable
            self.load_error = error

    async def cog_unload(self):
        if self.session:
            await self.session.close()
        if self.claude:
            await self.claude.close()

    def claude_client(self) -> anthropic.AsyncAnthropic:
        """Clé absente : le bot démarre quand même, c'est la question qui échoue."""
        if self.claude is None:
            if not os.getenv(API_KEY):
                raise MissingKeyError()
            self.claude = anthropic.AsyncAnthropic(timeout=LLM_TIMEOUT, max_retries=LLM_RETRIES)
        return self.claude

    @app_commands.command(name="cephalon", description="Pose une question sur Warframe à la Cephalon Schtroumpfette")
    @app_commands.describe(question="Ta question : un mod, une arme, une Warframe, où farmer un objet…")
    async def cephalon(self, interaction: discord.Interaction, question: app_commands.Range[str, 1, 500]):
        channel = command_channel()
        if channel is None:
            await interaction.response.send_message("Le module Warframe n'est pas encore configuré.", ephemeral=True)
            return
        if interaction.channel_id != channel:
            await interaction.response.send_message(f"Mauvais salon, utilise <#{channel}>.", ephemeral=True)
            return
        config = read_config()
        refusal = self.limits.check(interaction.user.id, config, utcnow())
        if refusal:
            await interaction.response.send_message(self.refusal_message(refusal, config), ephemeral=True)
            return
        await interaction.response.defer()
        await interaction.followup.send(embed=await self.answer(interaction.user.id, question, config))

    @staticmethod
    def refusal_message(refusal: limits.Refusal, config: Config) -> str:
        if refusal.kind == limits.BUDGET:
            return persona.BUDGET_MESSAGE
        if refusal.kind == limits.QUOTA:
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
        return render.answer(question, result.text, result.sources, outcome.remaining)

    async def record(self, user_id: int, usage: llm.Usage, answered: bool, config: Config) -> limits.Outcome:
        """Compte la question, écrit l'état et signale ce qui doit l'être dans le salon de logs."""
        if self.load_error:
            error, self.load_error = self.load_error, None
            await report_error(self.bot, f"{error} — compteurs remis à zéro", BUDGET_ORIGIN)
        outcome = self.limits.record(user_id, config.model, usage, answered, config, utcnow())
        try:
            await asyncio.to_thread(self.limits.save)
        except OSError as error:  # les compteurs continuent en mémoire
            await report_error(self.bot, f"état des limites non écrit : {error}", BUDGET_ORIGIN)
        if outcome.unknown_model:
            await report_error(self.bot, f"prix inconnu pour le modèle {config.model} : coût compté au tarif le plus cher",
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
