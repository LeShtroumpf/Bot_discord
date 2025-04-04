import discord
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
import time


class GeoGuessrChallenge:
    def __init__(self):
        pass

    async def challenge1(self, channel, map, challenge_geo, department):
        embed_challenge1 = discord.Embed(
            title=f"Voici la carte choisie: {map}",
            color=0xd1ec04
        )
        embed_challenge1.add_field(
            name='Voici le challenge sélectionné:',
            value=f"{challenge_geo}",
            inline=False
        )
        embed_challenge1.add_field(
            name='Et enfin voici le département sélectionné:',
            value=f"{department}",
            inline=False
        )
        await channel.send(embed=embed_challenge1)

    async def challenge2(self, channel, url):
        embed_challenge2 = discord.Embed(
            title='Battle Royal!',
            url=url, color=0xd1ec04
        )
        embed_challenge2.add_field(
            name='Que le destin vous soit favorable.',
            value="Pas de quartier!",
            inline=False
        )
        await channel.send(embed=embed_challenge2)

    async def challenge3(self, channel, map, url, challenge_geo):
        embed_challenge3 = discord.Embed(
            title=f"Voici la carte choisie: {map}",
            url=url,
            color=0xd1ec04
        )
        embed_challenge3.add_field(
            name='Et voici le challenge choisi: ',
            value=f"{challenge_geo}",
            inline=False
        )
        await channel.send(embed=embed_challenge3)


class TwitchMessage:

    async def message_online(self, data, stream_url, channel, profil_img, viewer_tag):
        data = data['data'][0]
        user_login = data['user_login']
        game_name = data['game_name']
        title = data['title']
        preview_image = data['thumbnail_url'].replace('{width}x{height}', '1080x566') + "?t=" + str(int(time.time()))
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
    def create_embed(self, data, type: str):
        if type in ['edit', 'delete']:  # message management
            try:
                user = data['user']
                message_before = data['message_before']
                channel = data["channel"]
                if type == 'edit':
                    message_after = data['message_after']
                    embed_logs = discord.Embed(
                        color=int("ff7d00", 16),
                        description=f"{user.mention} a modifié son message dans {channel.mention}.",
                        timestamp=datetime.now()
                    )
                    embed_logs.add_field(
                        name="Après:",
                        value=f"{message_after}",
                        inline=False
                    )
                if type == 'delete':
                    embed_logs = discord.Embed(
                        color=int("ff0000", 16),
                        description=f"{user.mention} a supprimé son message dans {channel.mention}.",
                        timestamp=datetime.now()
                    )
                embed_logs.set_author(
                    icon_url=f"{user.avatar}",
                    name=f"{user}"
                )
                embed_logs.add_field(
                    name="Avant:\n",
                    value=f"{message_before}",
                    inline=False
                )

                return embed_logs
            except Exception as e:
                Exception(f"error with type edit or delete: {e}")

        elif type in ['join', 'leave']:  # member join or leave
            try:
                user = data['user']
                if type == 'join':
                    embed_logs = discord.Embed(
                        color=int("00ff10", 16),
                        description=f"{user.mention} a rejoints le serveur.",
                        timestamp=datetime.now()
                    )
                    date_creation_account = datetime.fromisoformat(str(user.created_at))
                    age_account = relativedelta(datetime.now(timezone.utc), date_creation_account)
                    embed_logs.add_field(
                        name="Date de création de compte:",
                        value=f"{age_account.years} année, {age_account.months} mois, {age_account.days} jours"
                    )
                elif type == 'leave':
                    embed_logs = discord.Embed(
                        color=int("ff0000", 16),
                        description=f"{user.mention} a quitté le serveur.",
                        timestamp=datetime.now()
                    )

                embed_logs.set_author(
                    icon_url=f"{user.avatar}",
                    name=f"{user}"
                )
                embed_logs.set_thumbnail(url=user.avatar)
                return embed_logs
            except Exception as e:
                raise Exception(f"error with join or leave type: {e}")

        elif type in ['add', 'remove']:  # role management
            try:
                user = data["user"]
                role = data["role"]
                if type == 'add':
                    embed_logs = discord.Embed(
                        color=int("002aff", 16),
                        description=f"{user.mention} a obtenu le rôle {role.name}",
                        timestamp=datetime.now()
                    )
                    embed_logs.set_author(
                        icon_url=f"{user.avatar}",
                        name=f"{user}"
                    )
                    return embed_logs
                if type == 'remove':
                    embed_logs = discord.Embed(
                        color=int("ff0000", 16),
                        description=f"{user.mention} a perdu le rôle {role.name}",
                        timestamp=datetime.now()
                    )
                    embed_logs.set_author(
                        icon_url=f"{user.avatar}",
                        name=f"{user}"
                    )
                    return embed_logs
            except Exception as e:
                raise Exception(f"error with add or remove type: {e}")

        elif type == "voice":  # voice management
            try:
                after = data["after"]
                before = data["before"]
                user = data["user"]
                if after.channel is None:
                    embed_logs = discord.Embed(
                        color=int("ff0000", 16),
                        description=f"{user.mention} a quitté le vocal {before.channel.mention}",
                        timestamp=datetime.now()
                    )
                elif before.channel is None:
                    embed_logs = discord.Embed(
                        color=int("002aff", 16),
                        description=f"{user.mention} a rejoint le vocal {after.channel.mention}",
                        timestamp=datetime.now()
                    )
                else:
                    embed_logs = discord.Embed(
                        color=int("ff8333", 16),
                        description=f"{user.mention} a switch de vocal {before.channel.mention} -> {after.channel.mention}",
                        timestamp=datetime.now()
                    )
                embed_logs.set_author(
                    icon_url=f"{user.avatar}",
                    name=f"{user}"
                )
                return embed_logs
            except Exception as e:
                raise Exception(f"error with join_voice or leave_voice or move_voice type: {e}")

        elif type == 'error':
            try:
                error = data["error"]
                origine = data["origine"]
                embed_logs = discord.Embed(
                    color=int("000000", 16),
                    description=f"Error with last event: {origine}",
                    timestamp=datetime.now()
                )
                embed_logs.add_field(
                    name="Error content:",
                    value=error
                )
                return embed_logs
            except Exception as e:
                raise Exception(f"error with error: {e}")


GeoGuessrChallenge = GeoGuessrChallenge()
TwitchMessage = TwitchMessage()
logs_message = LogsMessage()
