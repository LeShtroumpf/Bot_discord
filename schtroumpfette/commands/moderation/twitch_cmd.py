import discord
from discord import app_commands
from discord.ext import commands

from utils.file_management import settings_file_management

MODO_ROLES = ("Les Champions du Dimanche", "Les colombus")


class ModoTwitch(commands.Cog):
    """Outils de gestion twitch."""
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="add_streamer",
        description="Ajouter le suivi des streams d'un streamer twitch"
    )
    @app_commands.checks.has_any_role(*MODO_ROLES)
    async def add_streamer(self, interaction: discord.Interaction, streamer_url: str):
        streamer_url = streamer_url.strip().rstrip('/')
        name = streamer_url.split('/')[-1]
        if streamer_url in settings_file_management.get_entry(main_key='streamer_followed'):
            await interaction.response.send_message(f"**{name}** est déjà suivi.", ephemeral=True)
            return
        settings_file_management.update_entry(
            main_key='streamer_followed',
            new_data={streamer_url: False},
        )
        await interaction.response.send_message(f"**{name}** est maintenant suivi.", ephemeral=True)

    @app_commands.command(
        name="remove_streamer",
        description="Supprime le suivi des streams d'un streamer twitch"
    )
    @app_commands.checks.has_any_role(*MODO_ROLES)
    async def remove_streamer(self, interaction: discord.Interaction, streamer_url: str):
        streamer_url = streamer_url.strip().rstrip('/')
        name = streamer_url.split('/')[-1]
        if streamer_url not in settings_file_management.get_entry(main_key='streamer_followed'):
            await interaction.response.send_message(f"**{name}** n'est pas suivi.", ephemeral=True)
            return
        settings_file_management.remove_entry(
            main_key='streamer_followed',
            key=streamer_url,
        )
        await interaction.response.send_message(f"**{name}** n'est plus suivi.", ephemeral=True)

    @app_commands.command(
        name="get_streamer",
        description="Affiche les streamers dans la liste des streamers"
    )
    @app_commands.checks.has_any_role(*MODO_ROLES)
    async def get_streamer(self, interaction: discord.Interaction):
        list_streamers = settings_file_management.get_entry(
            main_key='streamer_followed'
        )
        response = "Streamer suivi: "
        for streamer in list_streamers.keys():
            response += f"\n* {streamer.split('/')[-1]}"
        await interaction.response.send_message(response, ephemeral=True)


async def setup(bot):  # pragma: no cover
    await bot.add_cog(ModoTwitch(bot))
