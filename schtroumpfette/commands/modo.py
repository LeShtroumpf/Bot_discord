import os

from discord.ext import commands


class Modo(commands.Cog):
    """Outils de modération."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="Clear", help="Supprime le nombre "
                                         "de message voulu dans le channel.")
    @commands.has_role("Les Champions du Dimanche" or "Les colombus")
    async def clear(self, ctx, amount=2):
        await ctx.channel.purge(limit=amount+1)

    @commands.command(name="Restart", help="Redémarre le bot.")
    @commands.has_role("Les Champions du Dimanche" or "Les colombus")
    async def restart(self, ctx):
        await ctx.send('Je vais faire une petite sieste. '
                       'Je reviens de suite.'
                       )
        os._exit(1)


async def setup(bot):
    await bot.add_cog(Modo(bot))
