from . import nsfw
from . game_cmd import guess_flag, geoguessr
from ressource import embed

from discord.ext import commands
import asyncio


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
            await geoguessr.GeoGuessr.challenge(channel)
        else:
            await ctx.channel.send(f"Mauvais channel. Retente "
                                   f"la commande dans {channel.mention}")

    @commands.command(
        name='gp',
        help='Poste un gif nsfw dans le channel nsfw',
    )
    async def gp(self, ctx):

        if ctx.channel.id == 436270715109376010:
            message = nsfw.Nsfw.get_gif()
            await ctx.channel.send(str(message))
        else:
            await ctx.channel.send('mauvais channel')

    @commands.command(
        name="private",
        help="Envoyer un nsfw en privée à quelqu'un",
    )
    async def mail(self, ctx, member):
        CARS_TO_REMOVE = '<>@'
        for car in CARS_TO_REMOVE:
            member = member.replace(car, '')
        user = self.bot.get_user(int(member))
        if user:
            message = nsfw.Nsfw.get_gif()
            await user.send(str(message))
            channel = self.bot.get_channel(ctx.channel.id)
            msg = await channel.fetch_message(ctx.message.id)
            await msg.delete()
        else:
            await ctx.channel.send(
                "Je n'ai pas trouvé l'utilisateur, "
                "es-tu sûr de l'avoir mentionné?"
            )

    @commands.command(
        name='Flag',
        help="Tu connais les drapeaux, alors devines celui-ci",
    )
    async def guessFlag(self, ctx):
        channel = self.bot.get_channel(780779953288773702)
        if ctx.channel.id == 780779953288773702:
            await guess_flag.GuessFlag.guessing_flag(ctx)
        else:
            await ctx.channel.send(f"Mauvais channel. Retente "
                                   f"la commande dans {channel.mention}")


async def setup(bot):
    await bot.add_cog(Everyone(bot))
