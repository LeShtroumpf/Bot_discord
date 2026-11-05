import discord
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
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


class LogsMessage:
    """Embeds du salon de logs : une méthode par type de log."""
    FIELD_MAX = 1024
    NO_TEXT = "(pas de texte)"
    UNKNOWN_TEXT = "(ancien texte inconnu)"

    def _embed(self, color: int, description: str, user=None) -> discord.Embed:
        embed = discord.Embed(color=color, description=description, timestamp=datetime.now())
        if user is not None:
            embed.set_author(name=str(user), icon_url=user.display_avatar.url)  # avatar par défaut si pas de photo
        return embed

    def _field_text(self, text: str | None) -> str:
        """Texte d'un message pour un champ d'embed : jamais vide, jamais trop long. None = texte inconnu."""
        if text is None:
            return self.UNKNOWN_TEXT
        if len(text) > self.FIELD_MAX:
            return text[:self.FIELD_MAX - 1] + "…"
        return text or self.NO_TEXT

    def edit(self, user, channel_id: int, before: str | None, after: str) -> discord.Embed:
        embed = self._embed(0xff7d00, f"{user.mention} a modifié son message dans <#{channel_id}>.", user)
        embed.add_field(name="Après:", value=self._field_text(after), inline=False)
        embed.add_field(name="Avant:", value=self._field_text(before), inline=False)
        return embed

    def delete(self, user, channel_id: int, text: str) -> discord.Embed:
        embed = self._embed(0xff0000, f"{user.mention} a supprimé son message dans <#{channel_id}>.", user)
        embed.add_field(name="Avant:", value=self._field_text(text), inline=False)
        return embed

    def delete_unknown(self, channel_id: int) -> discord.Embed:
        """Message absent du cache : Discord ne donne ni l'auteur ni le texte."""
        return self._embed(0xff0000, f"Un message a été supprimé dans <#{channel_id}> (auteur et texte inconnus).")

    def join(self, user) -> discord.Embed:
        embed = self._embed(0x00ff10, f"{user.mention} a rejoints le serveur.", user)
        age = relativedelta(datetime.now(timezone.utc), user.created_at)
        embed.add_field(name="Date de création de compte:", value=f"{age.years} année, {age.months} mois, {age.days} jours")
        return embed.set_thumbnail(url=user.display_avatar.url)

    def leave(self, user) -> discord.Embed:
        embed = self._embed(0xff0000, f"{user.mention} a quitté le serveur.", user)
        return embed.set_thumbnail(url=user.display_avatar.url)

    def role_added(self, user, role) -> discord.Embed:
        return self._embed(0x002aff, f"{user.mention} a obtenu le rôle {role.name}", user)

    def role_removed(self, user, role) -> discord.Embed:
        return self._embed(0xff0000, f"{user.mention} a perdu le rôle {role.name}", user)

    def voice(self, user, before, after) -> discord.Embed:
        if after.channel is None:
            return self._embed(0xff0000, f"{user.mention} a quitté le vocal {before.channel.mention}", user)
        if before.channel is None:
            return self._embed(0x002aff, f"{user.mention} a rejoint le vocal {after.channel.mention}", user)
        return self._embed(0xff8333, f"{user.mention} a switch de vocal {before.channel.mention} -> {after.channel.mention}", user)

    def error(self, origine: str, text: str, repeats: int = 0) -> discord.Embed:
        description = f"Error with last event: {origine}"
        if repeats:
            description += f" (répétée {repeats} fois)"
        embed = self._embed(0x000000, description)
        embed.add_field(name="Error content:", value=self._field_text(text))
        return embed


GeoGuessrChallenge = GeoGuessrChallenge()
TwitchMessage = TwitchMessage()
logs_message = LogsMessage()
