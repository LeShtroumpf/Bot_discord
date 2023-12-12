import os
import time
from datetime import datetime

from commands import nsfw


import discord
from discord.ext import commands


class Modo(commands.Cog):
    """Outils de modération."""

    def __init__(self, bot):
        self.bot = bot
        self.spam = False

    @commands.command(
        name="Clear",
        help="Supprime le nombre de message voulu dans le channel."
    )
    @commands.has_role("Les Champions du Dimanche" or "Les colombus")
    async def clear(self, ctx, amount=2):
        await ctx.channel.purge(limit=amount+1)

    @commands.command(name="Restart", help="Redémarre le bot.")
    @commands.has_role("Les Champions du Dimanche" or "Les colombus")
    async def restart(self, ctx):
        await ctx.send(
            'Je vais faire une petite sieste. Je reviens de suite.'
        )
        os._exit(1)

    @commands.command(
        name="Spam",
        help="J'avais promis à Onoz une commande pour le spam"
    )
    @commands.has_role("Les Champions du Dimanche" or "Les colombus")
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
            message = nsfw.Nsfw.get_gif()
            await user.send(str(message))
            time.sleep(0.5)

    @commands.command(
        name="Stop_spam",
        help="Il faut toujours savoir s'arrêter."
    )
    @commands.has_role("Les Champions du Dimanche" or "Les colombus")
    async def stop_spam(self, ctx):
        self.spam = False


async def setup(bot):
    await bot.add_cog(Modo(bot))
