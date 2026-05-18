from . import nsfw
from . game_cmd import guess_flag, geoguessr

import discord
from discord import app_commands
from discord.ext import commands


class Everyone(commands.Cog):
    """Commands which are for all user."""

    def __init__(self, bot):
        print('bot initialized')
        self.bot = bot

    @app_commands.command(
        name='stop',
        description="Commande spécial pour notre casse pied préféré!",
        )
    async def stop(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "Non {}, jamais. J'aime trop t'enmerder!".format(
                interaction.user.mention)
        )

    @app_commands.command(
        name='geo',
        description="Vous donne un défi aléatoire.",
        )
    async def challenge(self, interaction: discord.Interaction):
        channel = self.bot.get_channel(780779953288773702)
        if interaction.channel_id == 780779953288773702:
            geo = geoguessr.GeoGuessr()
            await geo.challenge(interaction)
        else:
            await interaction.response.send_message(
                f"Mauvais channel. Retente la commande dans {channel.mention}",
                ephemeral=True
            )

    @app_commands.command(
        name='gp',
        description='Poste un gif nsfw dans le channel nsfw',
    )
    @app_commands.checks.has_any_role(531584682207215616, 276408996577935360, 1346147451970650182)  # Champions, colombus, bro
    async def gp(self, interaction: discord.Interaction):
        if interaction.channel_id == 436270715109376010:
            message = nsfw.Nsfw().get_gif()
            await interaction.response.send_message(str(message))
        else:
            await interaction.response.send_message('mauvais channel')

    @app_commands.command(
        name="private",
        description="Envoyer un nsfw en privée à quelqu'un",
    )
    async def mail(self, interaction: discord.Interaction, member: discord.Member):
        if member:
            message = nsfw.Nsfw().get_gif()
            await member.send(str(message))
            await interaction.response.send_message("Message envoyé !", ephemeral=True)
        else:
            await interaction.response.send_message(
                "Je n'ai pas trouvé l'utilisateur, "
                "es-tu sûr de l'avoir mentionné?",
                ephemeral=True
            )

    @app_commands.command(
        name='flag',
        description="Tu connais les drapeaux, alors devines celui-ci",
    )
    async def guessFlag(self, interaction: discord.Interaction):
        channel = self.bot.get_channel(780779953288773702)
        if interaction.channel_id == 780779953288773702:
            await guess_flag.GuessFlag.guessing_flag(interaction)
        else:
            await interaction.response.send_message(f"Mauvais channel. Retente "
                                   f"la commande dans {channel.mention}")

    @app_commands.command(
        name='join',
        description="Connection pour le TTS"
    )
    async def join(self, interaction: discord.Interaction):
        # Vérifier si l'utilisateur est dans un channel vocal
        if not interaction.user.voice:
            await interaction.response.send_message("Tu dois être dans un channel vocal pour que je puisse te rejoindre !")
            return

        # Vérifier si le bot n'est pas déjà connecté
        if interaction.user.voice:
            await interaction.response.send_message("Je suis déjà connecté à un channel vocal !")
            return

        try:
            # Se connecter au channel vocal de l'utilisateur
            print('trying to join')
            voice_channel = interaction.user.voice.channel
            voice_client = discord.utils.get(self.bot.voice_clients, guild=interaction.guild)
            if not voice_client or not voice_client.is_connected():
                voice_client = await voice_channel.connect()
            print(f"Bot connecté à : {voice_channel.name}")

        except Exception as e:
            await interaction.response.send_message(f"Erreur lors de la connexion : {e}")
            print(f"Erreur : {e}")

    @app_commands.command(
        name='leave',
        description="Deconnexion pour le TTS"
    )
    async def leave(self, interaction: discord.Interaction):
        if interaction.guild.voice_client:
            await interaction.guild.voice_client.disconnect()
            await interaction.response.send_message("Déconnecté du channel vocal !")
        else:
            await interaction.response.send_message("Je ne suis pas connecté à un channel vocal.")


async def setup(bot):  # pragma: no cover
    await bot.add_cog(Everyone(bot))
