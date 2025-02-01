import asyncio  # noqa
import json  # noqa

from discord.ext import commands, tasks
from discord.utils import get
import discord

from .twitch import twitch
from utils.embed import Role


class EventListener(commands.Bot):
    def __init__(self, command_prefix, description, intents):
        super().__init__(
            command_prefix=command_prefix,
            description=description,
            intents=intents,
        )
        self.GUILD = "Les Champions du dimanche"
        self.temp_voice = list()
        self.dict_role = dict()
        self.voice_allow_list_channel = list()
        self.dict_chan = dict()

    async def on_ready(self):
        """First event. Set the activity"""
        for guild in self.guilds:
            if guild.name == self.GUILD:
                break
        print(f'{self.user} has connected to the following guild:\n'
              f'{guild.name}(id: {guild.id})')
        activity = discord.Game(name="Subir les avances d'Onoz.")
        self.build()
        await self.change_presence(
            status=discord.Status.idle,
            activity=activity
        )
        await self.on_post_online_stream.start()

    def build(self):
        """Get all local data from settings.json"""
        try:
            with open('settings.json', mode='r') as file:
                data = json.load(file)
            self.dict_role = data['dict_role']
            self.dict_chan = data['dict_chan']
            for value in data['voice_allow_list_channel'].values():
                self.voice_allow_list_channel.append(value)
            return self.dict_role, self.dict_chan, self.voice_allow_list_channel
        except Exception as e:
            print("error build: ", e)

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.errors.CheckFailure):
            await ctx.send("Tu n'as pas le droit d'utiliser "
                           "cette commande petit chenapan! :wink:")

    async def on_member_join(self, member):
        """Send a private message to a new joiner."""
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
        """Add role when a member react to a message."""
        channelLog = self.get_channel(442710531271426058)
        member = self.get_guild(payload.guild_id).\
            get_member(payload.user_id)
        if payload.message_id != 757583327783026699:
            pass
        else:
            for key in self.dict_role.keys():
                if payload.emoji.name == key:
                    emoji_id = self.dict_role[key]
                    role = get(self.get_guild(
                        payload.guild_id).roles,
                               id=int(emoji_id)
                               )
                    await member.add_roles(role)
                    await Role.add_role(member, role, channelLog)

    async def on_raw_reaction_remove(self, payload):
        """Remove role when a member remove his reaction."""
        channelLog = self.get_channel(442710531271426058)
        member = self.get_guild(payload.guild_id).\
            get_member(payload.user_id)
        if payload.message_id != 757583327783026699:
            pass
        else:
            for key in self.dict_role.keys():
                if payload.emoji.name == key:
                    emoji_id = self.dict_role[key]
                    role = get(
                        self.get_guild(payload.guild_id).roles,
                        id=int(emoji_id)
                    )
                    await member.remove_roles(role)
                    await Role.remove_role(member, role, channelLog)

    async def on_voice_state_update(self, member, before, after):
        """Create a voice channel when member join
        specific voice channel in voice_allow_list_channel"""
        if after.channel is not None and \
                after.channel.id in self.voice_allow_list_channel:
            channel_id = after.channel.id
            channel_id = self.get_channel(channel_id)
            guild = self.get_guild(channel_id.guild.id)
            if after.channel == channel_id:
                await guild.create_voice_channel(
                    name=f"{member.display_name}",
                    category=after.channel.category,
                )
                new_chan = discord.utils.get(
                    guild.channels,
                    name=member.display_name
                )
                self.temp_voice.append(new_chan.id)
                await member.move_to(new_chan)
        if after.channel is not before.channel and \
                before.channel.id in self.temp_voice:
            voice_id = self.get_channel(before.channel.id)
            members = voice_id.members
            if not members:
                self.temp_voice.remove(before.channel.id)
                await before.channel.delete()

    @tasks.loop(minutes=1)
    async def on_post_online_stream(self):
        channel = self.get_channel(1039915997827694622)
        await twitch.is_online_streamer(channel)
