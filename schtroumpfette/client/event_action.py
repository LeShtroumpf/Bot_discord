import asyncio  # noqa
import json  # noqa/

from discord.ext import commands
from discord.utils import get
import discord

from utils.file_management import settings_file_management


class EventAction:
    def __init__(self):
        self.GUILD = "Les Champions du dimanche"
        self.temp_voice = list()
        self.dict_role = dict()
        self.voice_allow_list_channel = list()
        self.dict_chan = dict()
        self.message_role_id = int()

    async def on_ready(self, bot: commands.Bot):
        print('on ready state')
        activity = discord.Game(name="Subir les avance d'Onoz!")
        self.build()
        await bot.change_presence(
            status=discord.Status.idle,
            activity=activity
        )

    def build(self):
        """Get all local data from settings.json"""
        try:
            self.dict_role = settings_file_management.get_entry(main_key='dict_role')
            self.dict_chan = settings_file_management.get_entry(main_key='dict_chan')
            temp_voice_channel = settings_file_management.get_entry(main_key='voice_allow_list_channel')
            self.message_role_id = settings_file_management.get_entry(main_key='message_role_id')
            for value in temp_voice_channel.values():
                self.voice_allow_list_channel.append(value)
            return self.dict_role, self.dict_chan, self.voice_allow_list_channel
        except Exception as e:
            print("error build: ", e)

    async def on_member_join_action(self, bot: commands.Bot, member: discord.Member):
        try:
            await member.send(
                    f"Bonjour {member.mention} et bienvenue sur "
                    f"le discord: __**{self.GUILD}**__.\n"
                    f" Nous sommes une communauté de joueurs sur "
                    f"divers jeux mais sur une seule platforme: PC.\n"
                    f"Tu peux aller dans la section 'rôles' pour choisir"
                    f" le jeu sur lequel tu es et si jamais "
                    f"tu souhaites ajouter un jeu, n'hésites pas à demander.")
        except Exception as e:
            raise Exception(f"Error on_member_join_action: {e}")

    async def on_reaction_add_action(self, bot: commands.Bot, payload):
        try:
            member = payload.member
            if payload.message_id == int(self.message_role_id):
                for key in self.dict_role.keys():
                    if payload.emoji.name == key:
                        emoji_id = self.dict_role[key]
                        role = get(bot.get_guild(payload.guild_id).roles, id=int(emoji_id))
                        await member.add_roles(role)
        except Exception as e:
            raise Exception(f"Error on_reaction_add_action: {e}")

    async def on_reaction_remove_action(self, bot: commands.Bot, payload):
        try:
            member = bot.get_guild(payload.guild_id).get_member(int(payload.user_id))
            if payload.message_id == int(self.message_role_id):
                for key in self.dict_role.keys():
                    if payload.emoji.name == key:
                        emoji_id = self.dict_role[key]
                        role = get(bot.get_guild(payload.guild_id).roles, id=int(emoji_id))
                        await member.remove_roles(role)
        except Exception as e:
            raise Exception(f"Error on_reaction_remove_action: {e}")

    async def on_voice_state_update_action(self, bot: commands.Bot, member: discord.Member, before, after):
        """Create a voice channel when member join specific voice channel in voice_allow_list_channel"""
        try:
            if after.channel is not None and str(after.channel.id) in self.voice_allow_list_channel:
                guild = after.channel.guild
                overwrites = {
                    member: discord.PermissionOverwrite(manage_channels=True)
                }
                new_channel = await guild.create_voice_channel(
                    name=f"{member.display_name}",
                    category=after.channel.category,
                    overwrites=overwrites,
                )
                await member.move_to(new_channel)

            if before.channel is not None and after.channel != before.channel:
                if str(before.channel.id) not in self.voice_allow_list_channel:
                    members = before.channel.members
                    if not members:
                        await before.channel.delete()
        except Exception as e:
            raise Exception(f"Error on_voice_state_update_action: {e}")
