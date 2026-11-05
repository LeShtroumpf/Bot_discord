import functools

import discord
from discord import app_commands
from discord.ext import commands, tasks

from .twitch import twitch
from .event_action import EventAction
from .event_logs import event_logs
from utils.file_management import settings_file_management


def log_errors(origine: str):
    """Une exception dans un event ou une tâche part dans le salon de logs, avec son origine."""
    def decorator(handler):
        @functools.wraps(handler)
        async def wrapper(self, *args, **kwargs):
            try:
                await handler(self, *args, **kwargs)
            except Exception as error:
                await event_logs.on_error_log(self, error, origine=origine, channel=self.logs_channel)
        return wrapper
    return decorator


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

    @property
    def logs_channel(self) -> discord.abc.GuildChannel | None:
        return self.get_channel(int(self.logs_channel_id or 0))

    async def on_ready(self):
        synced = await self.tree.sync()
        print(f"Commandes synchronisées : {len(synced)}")
        await self.event_actions.on_ready(self)

    @log_errors("on_raw_message_edit")
    async def on_raw_message_edit(self, payload):
        """Called when a message is edited."""
        if payload.message.author.bot:
            return  # modifications des bots (dont les messages Warframe mis à jour en continu) : pas de log
        await event_logs.on_message_edit_log(self, payload=payload, channel=self.logs_channel)

    @log_errors("on_raw_message_delete")
    async def on_raw_message_delete(self, payload):
        """Called when a message is deleted."""
        await event_logs.on_message_delete_log(self, payload=payload, channel=self.logs_channel)

    @log_errors("on_reaction_add")
    async def on_raw_reaction_add(self, payload):
        """Called when a reaction is added to a message."""
        await self.event_actions.on_reaction_add_action(self, payload)

    @log_errors("on_reaction_remove")
    async def on_raw_reaction_remove(self, payload):
        """Called when a reaction is removed from a message."""
        await self.event_actions.on_reaction_remove_action(self, payload)

    @log_errors("on_member_join")
    async def on_member_join(self, member):
        """Called when a member joins the server."""
        await event_logs.on_member_join_log(self, member, channel=self.logs_channel)  # avant l'action : MP fermés = erreur
        await self.event_actions.on_member_join_action(self, member)

    @log_errors("on_raw_member_remove")
    async def on_raw_member_remove(self, payload):
        """Called when a member leaves the server."""
        await event_logs.on_raw_member_remove_log(self, payload, channel=self.logs_channel)

    @log_errors("on_member_update")
    async def on_member_update(self, before, after):
        """Called when a member is updated (roles, nickname, etc.)."""
        await event_logs.on_member_update_log(self, before, after, channel=self.logs_channel)

    @log_errors("on_voice_state_update")
    async def on_voice_state_update(self, member, before, after):
        """Called when a member joins, leaves, or switches voice channels."""
        await event_logs.on_voice_state_update_log(self, member, before, after, channel=self.logs_channel)
        await self.event_actions.on_voice_state_update_action(self, member, before, after)

    async def on_message(self, message):
        if not message.content.startswith("$"):
            if self.voice_clients and self.voice_clients[0].channel.id == message.channel.id:
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
            await ctx.send("Tu n'as pas le droit d'utiliser "
                           "cette commande petit chenapan! :wink:")
        await event_logs.on_error_log(self, error, origine="on_commande_error", channel=self.logs_channel)

    @tasks.loop(minutes=1)
    @log_errors("on_post_online_stream")
    async def on_post_online_stream(self):
        await twitch.check(self.get_channel(int(self.stream_channel or 0)))

    @on_post_online_stream.before_loop
    async def before_on_post_online_stream(self):
        await self.wait_until_ready()

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Called when a slash command raises (failed role checks included)."""
        if isinstance(error, app_commands.CheckFailure):
            message = "Tu n'as pas le droit d'utiliser cette commande petit chenapan! :wink:"
        else:
            message = "Une erreur est survenue !"
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass  # interaction expirée : on log quand même

        if isinstance(error, app_commands.CommandInvokeError):
            error = error.original
        command = f"/{interaction.command.name}" if interaction.command else "slash command"
        await event_logs.on_error_log(
            self,
            f"{interaction.user} : {type(error).__name__}: {error}",
            origine=command,
            channel=self.logs_channel,
        )

    async def setup_hook(self):
        self.tree.on_error = self.on_app_command_error
        self.gc_task.start()
        self.on_post_online_stream.start()

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

    @gc_task.before_loop
    async def before_gc_task(self):
        await self.wait_until_ready()
