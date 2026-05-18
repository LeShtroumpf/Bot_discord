import os
import time

import discord
from discord import app_commands
from discord.ext import commands

from commands.nsfw import nsfw


class Modo(commands.Cog):
    """Outils de modération."""

    def __init__(self, bot):
        self.bot = bot
        self.spam = False

    @app_commands.command(
        name="clear",
        description="Supprime le nombre de message voulu dans le channel."
    )
    @app_commands.checks.has_any_role("Les Champions du Dimanche", "Les colombus")
    async def clear(self, interaction: discord.Interaction, amount: int = 2):
        await interaction.channel.purge(limit=amount+1)

    @app_commands.command(name="restart", description="Redémarre le bot.")
    @app_commands.checks.has_any_role("Les Champions du Dimanche", "Les colombus")
    async def restart(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            'Je vais faire une petite sieste. Je reviens de suite.'
        )
        os._exit(1)

    @app_commands.command(
        name="spam",
        description="J'avais promis à Onoz une commande pour le spam"
    )
    @app_commands.checks.has_any_role("Les Champions du Dimanche", "Les colombus")
    async def spam(self, ctx):
        casse_couille = os.environ['CASSEBONBON']
        member = casse_couille.split('#')
        user = discord.utils.get(
            ctx.guild.members,
            name=member[0],
            discriminator=member[1],
        )
        user = self.bot.get_user(user.id)
        self.spam = True
        while self.spam:
            message = nsfw.get_gif()
            await user.send(str(message))
            time.sleep(0.5)

    @app_commands.command(
        name="stop_spam",
        description="Il faut toujours savoir s'arrêter."
    )
    @app_commands.checks.has_any_role("Les Champions du Dimanche", "Les colombus")
    async def stop_spam(self, interaction: discord.Interaction):
        self.spam = False


async def setup(bot):  # pragma: no cover
    await bot.add_cog(Modo(bot))
