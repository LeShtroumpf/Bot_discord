import discord
from datetime import datetime


class Role:

    async def add_role(self, member, role, channelLog):
        embed_add_role = discord.Embed(color=0x1608d9)
        embed_add_role.set_author(icon_url=f"{member.avatar_url}", name=f"{member}")
        embed_add_role.add_field(name=f"@{member} a obtenu le rôle: ", value=f"```{role}```", inline=True)
        embed_add_role.set_footer(text=f"Le {datetime.now()}")
        await channelLog.send(embed=embed_add_role)

    async def remove_role(self, member, role, channelLog):
        embed_remove_role = discord.Embed(color=0x1608d9)
        embed_remove_role.set_author(icon_url=f"{member.avatar_url}", name=f"{member}")
        embed_remove_role.add_field(name=f"@{member} a perdu le rôle: ", value=f"```{role}```", inline=True)
        embed_remove_role.set_footer(text=f"Le {datetime.now()}")
        await channelLog.send(embed=embed_remove_role)


class GeoGuessrChallenge:
    def __init__(self):
        pass

    async def challenge1(self, channel, map, challenge_geo, department):
        embed_challenge1 = discord.Embed(title=f"Voici la carte choisie: {map}", color=0xd1ec04)
        embed_challenge1.add_field(name=f"Voici le challenge sélectionné:", value=f"{challenge_geo}", inline=False)
        embed_challenge1.add_field(name=f"Et enfin voici le département sélectionné:", value=f"{department}", inline=False)
        await channel.send(embed=embed_challenge1)

    async def challenge2(self, channel, url):
        embed_challenge2 = discord.Embed(title=f"Battle Royal!", url=url, color=0xd1ec04)
        embed_challenge2.add_field(name=f"Que le destin vous soit favorable.", value="Pas de quartier!", inline=False)
        await channel.send(embed=embed_challenge2)

    async def challenge3(self, channel, map, url, challenge_geo):
        embed_challenge3 = discord.Embed(title=f"Voici la carte choisie: {map}", url=url, color=0xd1ec04)
        embed_challenge3.add_field(name=f"Et voici le challenge choisi: ", value=f"{challenge_geo}", inline=False)
        await channel.send(embed=embed_challenge3)


Role = Role()
GeoGuessrChallenge = GeoGuessrChallenge()