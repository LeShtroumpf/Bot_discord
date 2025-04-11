import asyncio  # noqa
import json  # noqa

from discord.ext import commands
import discord

from utils.embed import logs_message


class EventLogs:
    def __init__(self):
        pass

    async def on_error_log(self, bot: commands.Bot, error, origine: str, channel: discord.TextChannel):
        try:
            data = {
                'error': str(error),
                'origine': origine,
            }
            create_embed = logs_message.create_embed(data=data, type='error')
            await channel.send(embed=create_embed)
        except Exception as e:
            print(e)

    async def on_member_join_log(self, bot: commands.Bot, member: discord.Member, channel: discord.TextChannel):
        try:
            data = {"user": member}
            create_embed = logs_message.create_embed(data=data, type='join')
            await channel.send(embed=create_embed)
        except Exception as e:
            await self.on_error_log(bot, e, origine="on_member_join_log", channel=channel)

    async def on_message_edit_log(self, bot: commands.Bot, payload: discord.Message, channel: discord.TextChannel):
        try:
            if payload.cached_message.content == payload.data["content"]:
                return
            member = bot.get_user(int(payload.data["author"]["id"]))
            if not payload.cached_message:
                message_before = ""
            else:
                message_before = payload.cached_message.content
            data = {
                "user": member,
                "message_before": message_before,
                "message_after": payload.data["content"],
                "channel": bot.get_channel(int(payload.channel_id))
            }
            create_embed = logs_message.create_embed(data=data, type='edit')
            await channel.send(embed=create_embed)
        except Exception as e:
            await self.on_error_log(bot, e, origine="on_message_edit_log", channel=channel)

    async def on_message_delete_log(self, bot: commands.Bot, payload: discord.Message, channel: discord.TextChannel):
        try:
            if payload.cached_message:
                member = bot.get_user(int(payload.cached_message.author.id))
                message_before = payload.cached_message.content
                data = {
                    "user": member,
                    "message_before": message_before,
                    "channel": bot.get_channel(int(payload.channel_id))
                }
                create_embed = logs_message.create_embed(data=data, type='delete')
                await channel.send(embed=create_embed)
        except Exception as e:
            await self.on_error_log(bot, e, origine="on_message_delete_log", channel=channel)

    async def on_raw_member_remove_log(self, bot: commands.Bot, payload: discord.RawReactionActionEvent, channel: discord.TextChannel):
        try:
            member = payload.user
            data = {"user": member}
            create_embed = logs_message.create_embed(data=data, type='leave')
            await channel.send(embed=create_embed)
        except Exception as e:
            await self.on_error_log(bot, e, origine="on_raw_member_remove_log", channel=channel)

    async def on_voice_state_update_log(self, bot: commands.Bot, member: discord.Member, before: discord.VoiceState,
                                        after: discord.VoiceState, channel: discord.TextChannel):
        try:
            if before.channel is not None and after.channel is not None and before.channel.id == after.channel.id:
                return
            data = {
                "user": member,
                "before": before,
                "after": after
            }
            create_embed = logs_message.create_embed(data=data, type='voice')
            await channel.send(embed=create_embed)
        except Exception as e:
            await self.on_error_log(bot, e, origine="on_voice_state_update_log", channel=channel)

    async def on_member_update_log(self, bot: commands.Bot, before: discord.Member, after: discord.Member, channel: discord.TextChannel):
        try:
            before_role = set(before.roles)
            after_role = set(after.roles)
            role_added = list(after_role - before_role)
            role_removed = list(before_role - after_role)
            if role_added:
                data = {
                    "user": after,
                    "role": role_added[0]
                }
                create_embed = logs_message.create_embed(data=data, type='add')
                await channel.send(embed=create_embed)
            elif role_removed:
                data = {
                    "user": after,
                    "role": role_removed[0]
                }
                create_embed = logs_message.create_embed(data=data, type='remove')
                await channel.send(embed=create_embed)
        except Exception as e:
            await self.on_error_log(bot, e, origine="on_member_update_log", channel=channel)


event_logs = EventLogs()
