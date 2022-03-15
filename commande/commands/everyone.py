from commande.commands.game_cmd import GeoGuessr
from discord.ext import commands


class Everyone(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    """Commande utilisateur."""
    @commands.command(name='Stop', help="Commande spécial "
                                        "pour notre casse pied préféré!")
    async def stop(self, ctx, member):
        await ctx.channel.send(f" Non {member.mention}, "
                               f"jamais. J'aime trop t'enmerder!")

    @commands.command(name='Geo', help="Vous "
                                       "donne un défi aléatoire.")
    async def challenge(self, ctx):

        channel = self.bot.get_channel(780779953288773702)
        if ctx.channel.id == 780779953288773702:
            await GeoGuessr.challenge(channel)
        else:
            print(ctx.channel.id)
            await ctx.channel.send(f"Mauvais channel. Retente "
                                   f"la commande dans {channel.mention}")


def setup(bot):
    bot.add_cog(Everyone(bot))
