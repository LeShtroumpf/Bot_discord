import asyncio
import os

import discord
from discord import app_commands
from discord.ext import commands

from commands.nsfw import nsfw


class Modo(commands.Cog):
    """Outils de modération."""

    def __init__(self, bot):
        self.bot = bot
        self.spam_running = False

    @app_commands.command(
        name="clear",
        description="Supprime le nombre de message voulu dans le channel."
    )
    @app_commands.checks.has_any_role("Les Champions du Dimanche", "Les colombus")
    async def clear(self, interaction: discord.Interaction, amount: int = 2):
        # La suppression peut prendre plus de 3 s : on diffère la réponse.
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"{len(deleted)} message(s) supprimé(s).", ephemeral=True)

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
    async def spam(self, interaction: discord.Interaction):
        casse_couille = os.environ['CASSEBONBON']
        member = casse_couille.split('#')
        user = discord.utils.get(
            interaction.guild.members,
            name=member[0],
            discriminator=member[1],
        )
        user = self.bot.get_user(user.id)
        await interaction.response.send_message(f"C'est parti pour {user.mention} !", ephemeral=True)
        self.spam_running = True
        while self.spam_running:
            message = nsfw.get_gif()
            await user.send(str(message))
            await asyncio.sleep(0.5)

    @app_commands.command(
        name="stop_spam",
        description="Il faut toujours savoir s'arrêter."
    )
    @app_commands.checks.has_any_role("Les Champions du Dimanche", "Les colombus")
    async def stop_spam(self, interaction: discord.Interaction):
        if not self.spam_running:
            await interaction.response.send_message("Aucun spam en cours.", ephemeral=True)
            return
        self.spam_running = False
        await interaction.response.send_message("Spam arrêté.", ephemeral=True)


async def setup(bot):  # pragma: no cover
    await bot.add_cog(Modo(bot))
