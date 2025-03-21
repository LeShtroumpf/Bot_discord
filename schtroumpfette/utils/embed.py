import discord
from datetime import datetime
import time


class Role:

    async def add_role(self, member, role, channellog):
        embed_add_role = discord.Embed(color=0x1608d9)
        embed_add_role.set_author(
            icon_url=f"{member.avatar_url}",
            name=f"{member}"
        )
        embed_add_role.add_field(
            name=f"@{member} a obtenu le rôle: ",
            value=f"```{role}```",
            inline=True
        )
        embed_add_role.set_footer(text=f"Le {datetime.now()}")
        await channellog.send(embed=embed_add_role)

    async def remove_role(self, member, role, channellog):
        embed_remove_role = discord.Embed(color=0x1608d9)
        embed_remove_role.set_author(
            icon_url=f"{member.avatar_url}",
            name=f"{member}"
        )
        embed_remove_role.add_field(name=f"@{member} a perdu le rôle: ",
                                    value=f"```{role}```",
                                    inline=True
                                    )
        embed_remove_role.set_footer(
            text=f"Le {datetime.now()}"
        )
        await channellog.send(
            embed=embed_remove_role
        )


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
            embed_twitch = discord.Embed(
                title=f'Hey <@&1347519191321804881> ! {user_login} est en live.',
                url=stream_url,
                color=0x9b59b6,
                timestamp = datetime.now()
            )
        else:
            embed_twitch = discord.Embed(
                title=f'Hey! {user_login} est en live.',
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

        await channel.send(embed=embed_twitch)


Role = Role()
GeoGuessrChallenge = GeoGuessrChallenge()
TwitchMessage = TwitchMessage()
