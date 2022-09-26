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



async def setup(bot):
    await bot.add_cog(Modo(bot))
