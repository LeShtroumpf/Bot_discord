import discord
from discord.ext import commands


class RolePlay(commands.Cog):
    """Commands used in RP, like mail sending"""

    def __init__(self, bot):
        print('RP initialized')
        self.bot = bot
        self.channel = self.bot.get_channel(751340877728841738)

    @commands.command(
        name="Mail",
        help="Envoyer un mail a quelqu'un. Pensez à noter son #ID",
        )
    async def mail(self, ctx, member, *, mail):
        origin = ctx.message.author
        member = member.split('#')
        user = discord.utils.get(
            ctx.guild.members,
            name=member[0],
            discriminator=member[1],
            )
        user = self.bot.get_user(user.id)
        if user:
            await origin.send(mail)
            await user.send(mail)
            await ctx.channel.purge(limit=1)
        else:
            await ctx.channel.send(
                "Cette personne est introuvable, si son pseudo",
                " est en deux mots met le entre guillement.",
                )


async def setup(bot):
    await bot.add_cog(RolePlay(bot))
