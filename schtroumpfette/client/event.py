import os

import discord
from discord import app_commands
from discord.ext import commands, tasks

from .twitch import twitch
from .event_action import EventAction
from .errors import log_errors, report_error
from utils.embed import startup_message
from utils.file_management import settings_file_management


class EventListener(commands.Bot):
    def __init__(self, command_prefix, description, intents):
        super().__init__(
            command_prefix=command_prefix,
            description=description,
            intents=intents,
            max_messages=50,
            # Tous les membres en cache au démarrage : sans ça, pas d'on_member_update (rôles, surnoms) pour un membre
            # hors cache. (L'ancien `self.chunk_guilds_at_startup = False` posé après coup n'avait aucun effet.)
            chunk_guilds_at_startup=True,
        )
        self.logs_channel_id = settings_file_management.get_entry(main_key="dict_chan")["logs_channel"]
        self.stream_channel = settings_file_management.get_entry(main_key="dict_chan")["stream_channel"]
        self.event_actions = EventAction()
        self.announced = False

    @property
    def logs_channel(self) -> discord.abc.GuildChannel | None:
        return self.get_channel(int(self.logs_channel_id or 0))

    async def on_ready(self):
        synced = await self.tree.sync()
        print(f"Commandes synchronisées : {len(synced)}")
        await self.event_actions.on_ready(self)
        if not self.announced:  # une annonce par lancement, pas à chaque reconnexion
            self.announced = True
            await self.announce_startup()

    @log_errors("startup")
    async def announce_startup(self):
        """Version déployée dans le salon de logs (GIT_SHA posé par l'image, absent en local)."""
        channel = self.logs_channel
        if channel is None:
            raise LookupError("salon de logs introuvable")
        await channel.send(embed=startup_message.started(os.getenv("GIT_SHA")))

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
        """Message de bienvenue (le log d'arrivée est dans le cog des logs)."""
        await self.event_actions.on_member_join_action(self, member)

    @log_errors("on_voice_state_update")
    async def on_voice_state_update(self, member, before, after):
        """Vocaux temporaires et départ du bot quand il reste seul (le log est dans le cog des logs)."""
        await self.event_actions.on_voice_state_update_action(self, member, before, after)

    @log_errors("on_message")
    async def on_message(self, message):
        if not message.content.startswith("$"):
            if self.voice_clients and self.voice_clients[0].channel.id == message.channel.id:
                await self.event_actions.on_message_tts_action(self, message)
            else:
                pass
        else:
            await self.process_commands(message)

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.errors.CheckFailure):
            await ctx.send("Tu n'as pas le droit d'utiliser "
                           "cette commande petit chenapan! :wink:")
        await report_error(self, error, "on_commande_error")

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
        await report_error(self, f"{interaction.user} : {type(error).__name__}: {error}", command)

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

    @gc_task.before_loop
    async def before_gc_task(self):
        await self.wait_until_ready()
