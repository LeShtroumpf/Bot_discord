from commands import game_cmd, nsfw
from discord.ext import commands


class Everyone(commands.Cog):
    """Commands which are for all user."""

    def __init__(self, bot):
        print('bot initialzed')
        self.bot = bot

    """Commande utilisateur."""
    @commands.command(
        name='Stop',
        help="Commande spécial pour notre casse pied préféré!",
        )
    async def stop(self, ctx):
        await ctx.channel.send(
            "Non {}, jamais. J'aime trop t'enmerder!".format(
                ctx.message.author.mention)
        )

    @commands.command(
        name='Geo',
        help="Vous donne un défi aléatoire.",
        )
    async def challenge(self, ctx):
        channel = self.bot.get_channel(780779953288773702)
        if ctx.channel.id == 780779953288773702:
            await game_cmd.GeoGuessr.challenge(channel)
        else:
            await ctx.channel.send(f"Mauvais channel. Retente "
                                   f"la commande dans {channel.mention}")

    @commands.command(
        name='gp',
        help='Poste un gif nsfw dans le channel nsfw',
    )
    async def gp(self, ctx):

        if ctx.channel.id == 751340877728841738:
            message = nsfw.Nsfw.get_gif()
            await ctx.channel.send(str(message))
        else:
            await ctx.channel.send('mauvais channel')


async def setup(bot):
    await bot.add_cog(Everyone(bot))
