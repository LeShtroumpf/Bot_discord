import discord
from datetime import datetime
import asyncio

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

    async def online(self, data, stream_url, channel, profil_img):
        data = data['data'][0]
        user_login = data['user_login']
        game_name = data['game_name']
        title = data['title']
        thumbnail_url = profil_img
        embed_twitch = discord.Embed(
            title=f'Hey! {user_login} est en live.',
            url=stream_url,
            color=0x9b59b6
        )
        embed_twitch.set_thumbnail(url=thumbnail_url)
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


class GuessFlagEmbeded:

    async def flag(self, data: dict, country_list: list, channel):
        global good_answer_reply
        description = f":one: {data[country_list[0]]}\n :two: {data[country_list[1]]}\n :three: {data[country_list[2]]}\n :four:{data[country_list[3]]}\n"
        flag_url = f"https://flagcdn.com/h240/{country_list[0]}.png"
        good_answer = data[country_list[0]]
        embed_flag = discord.Embed(title="Quel est ce pays?",
                              description=description,
                              colour=0x6312b4,
                              timestamp=datetime.now())
        embed_flag.set_author(name="La Schtroumpfette")
        embed_flag.set_image(url=flag_url)
        embed_flag.set_footer(text="Schtroumpfette inc")
        await channel.send(embed=embed_flag)
        good_answer_reply = good_answer


Role = Role()
GeoGuessrChallenge = GeoGuessrChallenge()
TwitchMessage = TwitchMessage()
GuessFlagEmbeded = GuessFlagEmbeded()
