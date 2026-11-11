"""Cog Cephalon : /cephalon, une question sur Warframe posée à la Cephalon Schtroumpfette.

Module indépendant : le retirer de `cogs` (main.py) suffit à le couper.
"""
import os

import aiohttp
import anthropic
import discord
from discord import app_commands
from discord.ext import commands

from cephalon import llm, persona, render
from cephalon.config import LLM_RETRIES, LLM_TIMEOUT, command_channel, read_config
from cephalon.warframe_api import WarframeApi, WarframeApiError
from client.errors import report_error

API_KEY = "ANTHROPIC_API_KEY"


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

    async def cog_load(self):
        self.session = aiohttp.ClientSession()
        self.api = WarframeApi(self.session)

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
        await interaction.response.defer()
        await interaction.followup.send(embed=await self.answer(interaction.user.id, question))

    async def answer(self, user_id: int, question: str) -> discord.Embed:
        """L'embed de réponse, ou l'embed de repli avec l'erreur envoyée dans le salon de logs."""
        config = read_config()
        try:
            result = await llm.ask(self.claude_client(), self.api, question, config)
        except WarframeApiError as error:
            await report_error(self.bot, error, "cephalon : warframestat")
            return render.fallback(question, persona.error_message())
        except (anthropic.AnthropicError, MissingKeyError) as error:
            await report_error(self.bot, describe(error), "cephalon")
            return render.fallback(question, persona.error_message())
        usage = result.usage
        print(f"[cephalon] {user_id} : {result.rounds} tours, entrée {usage.input} (cache lu {usage.cache_read}, "
              f"écrit {usage.cache_write}), sortie {usage.output}, modèle {config.model}", flush=True)
        if result.status == llm.REFUSAL:
            await report_error(self.bot, "question refusée par le modèle", "cephalon")
            return render.fallback(question, persona.error_message())
        if result.status == llm.ROUNDS:
            return render.fallback(question, persona.ROUNDS_MESSAGE)
        return render.answer(question, result.text, result.sources)


async def setup(bot):  # pragma: no cover
    await bot.add_cog(Cephalon(bot))
