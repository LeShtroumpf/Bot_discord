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



Role = Role()