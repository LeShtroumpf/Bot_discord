import discord
from discord import app_commands
from discord.ext import commands

from client import twitch as twitch_client
from utils.file_management import settings_file_management

MODO_ROLES = ("Les Champions du Dimanche", "Les colombus")
UNKNOWN_INPUT = "Je ne reconnais pas ce streamer. Donne son pseudo ou son lien Twitch."


def followed_url(login: str) -> str | None:
    """URL enregistrée pour ce pseudo, quelle que soit sa casse."""
    followed = settings_file_management.get_entry(main_key='streamer_followed')
    return next((url for url in followed if twitch_client.login_from_url(url) == login), None)


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
        login = twitch_client.parse_streamer(streamer_url)
        if login is None:
            await interaction.response.send_message(UNKNOWN_INPUT, ephemeral=True)
            return
        if followed_url(login):
            await interaction.response.send_message(f"**{login}** est déjà suivi.", ephemeral=True)
            return
        settings_file_management.update_entry(
            main_key='streamer_followed',
            new_data={twitch_client.streamer_url(login): False},
        )
        await interaction.response.send_message(f"**{login}** est maintenant suivi.", ephemeral=True)

    @app_commands.command(
        name="remove_streamer",
        description="Supprime le suivi des streams d'un streamer twitch"
    )
    @app_commands.checks.has_any_role(*MODO_ROLES)
    async def remove_streamer(self, interaction: discord.Interaction, streamer_url: str):
        login = twitch_client.parse_streamer(streamer_url)
        if login is None:
            await interaction.response.send_message(UNKNOWN_INPUT, ephemeral=True)
            return
        url = followed_url(login)
        if url is None:
            await interaction.response.send_message(f"**{login}** n'est pas suivi.", ephemeral=True)
            return
        settings_file_management.remove_entry(main_key='streamer_followed', key=url)
        await interaction.response.send_message(f"**{login}** n'est plus suivi.", ephemeral=True)

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
