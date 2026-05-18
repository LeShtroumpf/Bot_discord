from discord import app_commands
from discord.ext import commands

from utils.file_management import settings_file_management


class ModoTwitch(commands.Cog):
    """Outils de gestion twitch."""
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="add_streamer",
        description="Ajouter le suivi des streams d'un streamer twitch"
    )
    @app_commands.checks.has_any_role("Les Champions du Dimanche" or "Les colombus")
    async def add_streamer(self, ctx, streamer_url: str):
        settings_file_management.update_entry(
            main_key='streamer_followed',
            new_data={streamer_url: False},
        )

    @app_commands.command(
        name="remove_streamer",
        description="Supprime le suivi des streams d'un streamer twitch"
    )
    @app_commands.checks.has_any_role("Les Champions du Dimanche" or "Les colombus")
    async def remove_streamer(self, ctx, streamer_url: str):
        print("cmd launch")
        settings_file_management.remove_entry(
            main_key='streamer_followed',
            key=streamer_url,
        )

    @app_commands.command(
        name="get_streamer",
        description="Afficvhe les streamers dans la liste des streamers"
    )
    @app_commands.checks.has_any_role("Les Champions du Dimanche" or "Les colombus")
    async def get_streamer(self, ctx):
        response = "Streamer suivi: "
        list_streamers = settings_file_management.get_entry(
            main_key='streamer_followed'
        )

        for streamer in list_streamers.keys():
            response += f"\n* {streamer.split('/')[-1]}"
        await ctx.send(response)


async def setup(bot):  # pragma: no cover
    await bot.add_cog(ModoTwitch(bot))
