import discord
from datetime import datetime
import time


class GeoGuessrChallenge:

    async def challenge1(self, interaction, map_name, challenge_geo, department):
        embed = discord.Embed(title=f"Voici la carte choisie: {map_name}", color=0xd1ec04)
        embed.add_field(name='Challenge sélectionné:', value=challenge_geo, inline=False)
        embed.add_field(name='Département sélectionné:', value=str(department), inline=False)
        await interaction.response.send_message(embed=embed)

    async def challenge2(self, interaction, url):
        embed = discord.Embed(title='Battle Royal!', url=url, color=0xd1ec04)
        embed.add_field(name='Que le destin vous soit favorable.', value="Pas de quartier!", inline=False)
        await interaction.response.send_message(embed=embed)

    async def challenge3(self, interaction, map_name, url, challenge_geo):
        embed = discord.Embed(title=f"Voici la carte choisie: {map_name}", url=url, color=0xd1ec04)
        embed.add_field(name='Challenge choisi:', value=challenge_geo, inline=False)
        await interaction.response.send_message(embed=embed)


class TwitchMessage:

    async def message_online(self, stream, stream_url, channel, profil_img, viewer_tag):
        user_login = stream['user_login']
        game_name = stream['game_name'] or "Non renseigné"
        title = stream['title'] or "Sans titre"
        preview_image = stream['thumbnail_url'].replace('{width}x{height}', '1080x566') + "?t=" + str(int(time.time()))
        thumbnail_url = profil_img
        if viewer_tag:
            message = f"Hey <@&1347519191321804881> ! {user_login} est en live. N'hésites pas a aller lui dire bonjour"
        else:
            message = ""
        embed_twitch = discord.Embed(
            title=f'{user_login} vient de lancer un truc qui devrait te plaire.',
            url=stream_url,
            color=0x9b59b6,
            timestamp=datetime.now()
        )
        embed_twitch.set_thumbnail(url=thumbnail_url)
        embed_twitch.set_image(url=preview_image)
        embed_twitch.add_field(
            name='Titre du live:',
            value=title,
            inline=False
        )
        embed_twitch.add_field(
            name='Il joue à ',
            value=game_name,
            inline=True
        )

        await channel.send(message, embed=embed_twitch)


class ErrorMessage:
    """Embed d'erreur du salon de logs (client/errors.py). Les logs d'activité sont dans logs/render.py."""
    FIELD_MAX = 1024

    def error(self, origine: str, text: str, repeats: int = 0) -> discord.Embed:
        description = f"Error with last event: {origine}"
        if repeats:
            description += f" (répétée {repeats} fois)"
        embed = discord.Embed(color=0x000000, description=description, timestamp=datetime.now())
        if len(text) > self.FIELD_MAX:
            text = text[:self.FIELD_MAX - 1] + "…"
        embed.add_field(name="Error content:", value=text or "(vide)")
        return embed


GeoGuessrChallenge = GeoGuessrChallenge()
TwitchMessage = TwitchMessage()
error_message = ErrorMessage()
