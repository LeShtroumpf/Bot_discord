import asyncio  # noqa
import json  # noqa

import discord
from discord.ext import commands, tasks

from .twitch import twitch
from .event_action import EventAction
from .event_logs import event_logs
from utils.file_management import settings_file_management


class EventListener(commands.Bot):
    def __init__(self, command_prefix, description, intents):
        super().__init__(
            command_prefix=command_prefix,
            description=description,
            intents=intents,
            max_messages=50,
        )
        self.chunk_guilds_at_startup = False
        self.logs_channel_id = settings_file_management.get_entry(main_key="dict_chan")["logs_channel"]
        self.stream_channel = settings_file_management.get_entry(main_key="dict_chan")["stream_channel"]
        self.event_actions = EventAction()

    async def on_ready(self):
        synced = await self.tree.sync()
        print(f"Commandes synchronisées : {len(synced)}")
        await self.event_actions.on_ready(self)
        await self.on_post_online_stream.start()

    async def on_raw_message_edit(self, payload):
        """Called when a message is edited."""
        logs_channel = self.get_channel(int(self.logs_channel_id))
        await event_logs.on_message_edit_log(self, payload=payload, channel=logs_channel)

    async def on_raw_message_delete(self, payload):
        """Called when a message is deleted."""
        logs_channel = self.get_channel(int(self.logs_channel_id))
        await event_logs.on_message_delete_log(self, payload=payload, channel=logs_channel)

    async def on_raw_reaction_add(self, payload):
        """Called when a reaction is added to a message."""
        try:
            logs_channel = self.get_channel(int(self.logs_channel_id))
            await self.event_actions.on_reaction_add_action(self, payload)
        except Exception as error:
            await event_logs.on_error_log(self, error, origine="on_reaction_add", channel=logs_channel)

    async def on_raw_reaction_remove(self, payload):
        """Called when a reaction is removed from a message."""
        try:
            logs_channel = self.get_channel(int(self.logs_channel_id))
            await self.event_actions.on_reaction_remove_action(self, payload)
        except Exception as error:
            await event_logs.on_error_log(self, error, origine="on_reaction_remove", channel=logs_channel)

    async def on_member_join(self, member):
        """Called when a member joins the server."""
        try:
            logs_channel = self.get_channel(int(self.logs_channel_id))
            await self.event_actions.on_member_join_action(self, member)
            await event_logs.on_member_join_log(self, member, logs_channel)
        except Exception as error:
            await event_logs.on_error_log(self, error, origine="on_member_join", channel=logs_channel)

    async def on_raw_member_remove(self, payload):
        """Called when a member leaves the server."""
        try:
            logs_channel = self.get_channel(int(self.logs_channel_id))
            await event_logs.on_raw_member_remove_log(self, payload, logs_channel)
        except Exception as error:
            await event_logs.on_error_log(self, error, origine="on_raw_member_remove", channel=logs_channel)

    async def on_member_update(self, before, after):
        """Called when a member is updated (roles, nickname, etc.)."""
        try:
            logs_channel = self.get_channel(int(self.logs_channel_id))
            await event_logs.on_member_update_log(self, before, after, logs_channel)
        except Exception as error:
            await event_logs.on_error_log(self, error, origine="on_member_update", channel=logs_channel)

    async def on_voice_state_update(self, member, before, after):
        """Called when a member joins, leaves, or switches voice channels."""
        try:
            logs_channel = self.get_channel(int(self.logs_channel_id))
            await self.event_actions.on_voice_state_update_action(self, member, before, after)
            await event_logs.on_voice_state_update_log(self, member, before, after, logs_channel)
        except Exception as error:
            await event_logs.on_error_log(self, error, origine="on_voice_state_update", channel=logs_channel)

    async def on_message(self, message):
        if not message.content.startswith("$"):
            if self.voice_clients and self.voice_clients[0].channel.id== message.channel.id:
                await self.event_actions.on_message_tts_action(self, message)
            else:
                pass
        else:
            await self.process_commands(message)

    async def on_guild_channel_create(self, channel):
        """Called when a channel is created."""
        pass

    async def on_guild_channel_delete(self, channel):
        """Called when a channel is deleted."""
        pass

    async def on_guild_channel_update(self, before, after):
        """Called when a channel is updated."""
        pass

    async def on_guild_role_create(self, role):
        """Called when a role is created."""
        pass

    async def on_guild_role_delete(self, role):
        """Called when a role is deleted."""
        pass

    async def on_guild_role_update(self, before, after):
        """Called when a role is updated."""
        pass

    async def on_guild_update(self, before, after):
        """Called when the server is updated."""
        pass

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.errors.CheckFailure):
            logs_channel = self.get_channel(int(self.logs_channel_id))
            await ctx.send("Tu n'as pas le droit d'utiliser "
                           "cette commande petit chenapan! :wink:")
        await event_logs.on_error_log(self, error, origine="on_commande_error", channel=logs_channel)

    @tasks.loop(minutes=1)
    async def on_post_online_stream(self):
        try:
            channel = self.get_channel(int(self.stream_channel))
            if channel:
                await twitch.is_online_streamer(channel)
        except Exception as error:
            await event_logs.on_error_log(self, error, origine="on_post_online_stream",)

    @on_post_online_stream.before_loop
    async def before_on_post_online_stream(self):
        await self.wait_until_ready()

    async def setup_hook(self):
        self.gc_task.start()

    @tasks.loop(hours=2)
    async def gc_task(self):
        """Nettoie la mémoire toutes les 2 heures"""
        import gc
        collected = gc.collect()
        print(f"[GC] Objets collectés : {collected}")

        # Nettoie le cache des messages
        if hasattr(self, '_connection'):
            if hasattr(self._connection, '_messages'):
                self._connection._messages.clear()

    @tasks.loop(hours=2)
    async def gc_task(self):
        """Nettoie la mémoire toutes les 2 heures"""
        import gc
        collected = gc.collect()
        print(f"[GC] Objets collectés : {collected}")
        if hasattr(self, '_connection'):
            if hasattr(self._connection, '_messages'):
                self._connection._messages.clear()

    @gc_task.before_loop
    async def before_gc_task(self):
        await self.wait_until_ready()
