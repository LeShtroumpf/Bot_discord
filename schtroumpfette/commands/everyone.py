from . import nsfw
from . game_cmd import guess_flag, geoguessr

import discord
from discord.ext import commands


class Everyone(commands.Cog):
    """Commands which are for all user."""

    def __init__(self, bot):
        print('bot initialized')
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
        GeoGuessr = geoguessr.GeoGuessr()
        channel = self.bot.get_channel(780779953288773702)
        if ctx.channel.id == 780779953288773702:
            await GeoGuessr.challenge(channel)
        else:
            await ctx.channel.send(f"Mauvais channel. Retente "
                                   f"la commande dans {channel.mention}")

    @commands.command(
        name='gp',
        help='Poste un gif nsfw dans le channel nsfw',
    )
    @commands.has_any_role(531584682207215616, 276408996577935360, 1346147451970650182)  # Champions, colombus, bro
    async def gp(self, ctx):
        if ctx.channel.id == 436270715109376010:
            message = nsfw.Nsfw().get_gif()
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
            message = nsfw.Nsfw().get_gif()
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

    @commands.command(
        name='join',
        help="Connection pour le TTS"
    )
    async def join(self, ctx):
        # Vérifier si l'utilisateur est dans un channel vocal
        if not ctx.author.voice:
            await ctx.send("Tu dois être dans un channel vocal pour que je puisse te rejoindre !")
            return

        # Vérifier si le bot n'est pas déjà connecté
        if ctx.voice_client:
            await ctx.send("Je suis déjà connecté à un channel vocal !")
            return

        try:
            # Se connecter au channel vocal de l'utilisateur
            print('trying to join')
            voice_channel = ctx.author.voice.channel
            voice_client = discord.utils.get(self.bot.voice_clients, guild=ctx.guild)
            if not voice_client or not voice_client.is_connected():
                voice_client = await voice_channel.connect()
            print(f"Bot connecté à : {voice_channel.name}")

        except Exception as e:
            await ctx.send(f"Erreur lors de la connexion : {e}")
            print(f"Erreur : {e}")

    @commands.command(
        name='leave',
        help="Deconnexion pour le TTS"
    )
    async def leave(self, ctx):
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            await ctx.send("Déconnecté du channel vocal !")
        else:
            await ctx.send("Je ne suis pas connecté à un channel vocal.")


async def setup(bot):  # pragma: no cover
    await bot.add_cog(Everyone(bot))
