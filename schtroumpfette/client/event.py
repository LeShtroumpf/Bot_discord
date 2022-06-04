
from discord.ext import commands
from discord.utils import get
from ressource.embed import Role
from settings import dict_role
import discord


class EventListener(commands.Bot):
    def __init__(self, command_prefix, description, intents):
        super().__init__(
            command_prefix=command_prefix,
            description=description,
            intents=intents,
        )
        self.GUILD = "Les Champions du dimanche"

    async def on_ready(self):
        for guild in self.guilds:
            if guild.name == self.GUILD:
                break
        print(f'{self.user} has connected to the following guild:\n'
              f'{guild.name}(id: {guild.id})')
        activity = discord.Game(name="Subir les avances d'Onoz.")
        await self.change_presence(status=discord.Status.idle, activity=activity)

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.errors.CheckFailure):
            await ctx.send("Tu n'as pas le droit d'utiliser "
                           "cette commande petit chenapan! :wink:")

    async def on_member_join(self, member):
        channel = self.get_channel(442710531271426058)
        await member.send(
            f"Bonjour {member.mention} et bienvenue sur "
            f"le discord: __**{self.GUILD}**__.\n"
            f" Nous sommes une communauté de joueurs sur "
            f"divers jeux mais sur une seule platforme: PC.\n"
            f"Tu peux aller dans la section 'rôles' pour choisir"
            f" le jeu sur lequel tu es et si jamais "
            f"tu souhaites ajouter un jeu, n'hésites pas à demander.")
        await channel.send(f"{member.mention} vient de rejoindre le serveur.")

    async def on_raw_reaction_add(self, payload):
        channelLog = self.get_channel(442710531271426058)
        member = self.get_guild(payload.guild_id).\
            get_member(payload.user_id)
        if payload.message_id != 757583327783026699:
            pass
        else:
            for key in dict_role.keys():
                if payload.emoji.name == key:
                    emoji_id = dict_role[key]
                    role = get(self.get_guild(payload.guild_id).
                               roles, id=int(emoji_id))
                    await member.add_roles(role)
                    await Role.add_role(member, role, channelLog)

    async def on_raw_reaction_remove(self, payload):
        channelLog = self.get_channel(442710531271426058)
        member = self.get_guild(payload.guild_id).\
            get_member(payload.user_id)
        if payload.message_id != 757583327783026699:
            pass
        else:
            for key in dict_role.keys():
                if payload.emoji.name == key:
                    emoji_id = dict_role[key]
                    role = get(self.get_guild(payload.guild_id).
                               roles, id=int(emoji_id))
                    await member.remove_roles(role)
                    await Role.remove_role(member, role, channelLog)

    async def on_voice_state_update(self, member, before, after):
        print(f"before: {before.channel}, after:{after.channel}")
        channel_id = self.get_channel(750998493908303872)
        guild = self.get_guild(276405667059859456)
        dust_chan = []
        print(f"first dust_chan: {dust_chan}")
        if before.channel is None and after.channel is not None:
            print('fuck you')
            print(f"channel_id: {channel_id}")
            if after.channel == channel_id:
                await guild.create_voice_channel(
                    name=f"{member.display_name}",
                    category=after.channel.category,
                )
                print(member.display_name)
                new_chan = discord.utils.get(guild.channels, name=member.display_name)
                dust_chan = dust_chan.append(new_chan.id)
#                new_chan = self.get_channel(member.display_name)
                print(f"new_chan: {new_chan}")
                print(f"dust_chan 2: {dust_chan}")
                await member.move_to(new_chan)
        if before.channel is not None and after.channel is None:
            print(f"dust_chan 3: {dust_chan}")
            if before.channel in dust_chan:
                print('remove chan')
