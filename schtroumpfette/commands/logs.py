"""Logs d'activité du serveur dans le salon de logs.

Cog indépendant : le retirer de `cogs` (main.py) coupe tous les logs d'activité, rien d'autre. Les erreurs du bot
ne sont pas ici (client/errors.py) : elles continuent d'arriver dans le salon de logs.
"""
import asyncio

import discord
from discord.ext import commands

from client.errors import log_errors, report_error
from logs.audit import AuditTracker
from logs.cache import HISTORY_TIMEOUT, message_cache, CachedMessage
from logs.invites import InviteTracker
from logs.render import render
from utils.file_management import settings_file_management

Action = discord.AuditLogAction
MISSING_AUDIT = "Permission « Voir les logs du serveur » manquante : logs sans modo"
MISSING_INVITES = "Permission « Gérer le serveur » manquante : invitation des arrivées inconnue"
STEP_TIMEOUT = 60  # secondes (settings.json : logs.step_timeout) : une étape bloquée ne bloque pas les suivantes


def ids(values) -> set[int]:
    """IDs de salons stockés en chaînes ; valeur vide ou non numérique (modèle pas rempli) ignorée."""
    return {int(value) for value in values if str(value or "").isdigit()}


def positive(value, default: float) -> float:
    """Délai lu dans settings.json : nombre positif, sinon la valeur par défaut (section ou clé absente comprise)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return value
    return default


def read_setting(key: str) -> dict:
    try:
        return settings_file_management.get_entry(main_key=key) or {}
    except KeyError:
        return {}


class Logs(commands.Cog):
    """Logs du serveur : messages, membres, vocal, salons, rôles, invitations."""

    def __init__(self, bot):
        self.bot = bot
        self.cache = message_cache
        self.audit = AuditTracker()
        self.invites = InviteTracker()
        self.permanent_voice: set[int] = set()
        self.load_task: asyncio.Task | None = None
        self.step_timeout: float = STEP_TIMEOUT

    async def cog_load(self):
        self.read_settings()

    def read_settings(self):
        """Salons exclus du cache (logs, info Warframe), vocaux permanents (lobbys + statiques) et délais du chargement."""
        logs_channel = (read_setting("dict_chan")).get("logs_channel")
        warframe_channel = read_setting("warframe").get("info_channel")
        self.cache.excluded = ids((logs_channel, warframe_channel))
        self.permanent_voice = ids([*read_setting("voice_allow_list_channel").values(), *read_setting("static_voice_channel").values()])
        config = read_setting("logs")
        self.step_timeout = positive(config.get("step_timeout"), STEP_TIMEOUT)
        self.cache.history_timeout = positive(config.get("history_timeout"), HISTORY_TIMEOUT)

    def is_temp_voice(self, channel) -> bool:
        """Vocal temporaire : ni lobby ni permanent (créé et supprimé par le bot, ses logs feraient doublon)."""
        return isinstance(channel, discord.VoiceChannel) and channel.id not in self.permanent_voice

    async def send(self, embed: discord.Embed, file: discord.File | None = None) -> discord.Message:
        """Seul point d'envoi : salon introuvable = erreur, jamais d'envoi silencieux."""
        channel = self.bot.logs_channel
        if channel is None:
            raise LookupError("salon de logs introuvable")
        if file is None:
            return await channel.send(embed=embed)
        return await channel.send(embed=embed, file=file)

    # --- Chargement -------------------------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_ready(self):
        """À chaque on_ready (démarrage, reconnexion complète sans rejeu des events), un chargement à la fois."""
        if self.load_task is None or self.load_task.done():
            self.load_task = asyncio.create_task(self.load())

    @log_errors("logs_load")
    async def load(self):
        # Membres : déjà tous chargés par discord.py au démarrage (chunk_guilds_at_startup, voir EventListener).
        # Ne pas rappeler guild.chunk() : la seconde demande n'obtient jamais de réponse et bloquait tout le chargement.
        self.read_settings()
        for guild in self.bot.guilds:
            await self.load_step(self.invites.load(guild), "logs_invites", MISSING_INVITES)
            await self.load_step(self.audit.load_baseline(guild), "logs_audit", MISSING_AUDIT)
        # Pas de délai global sur le cache : chaque salon a le sien (history_timeout), les autres sont chargés quand même
        result = await self.load_step(self.cache.load(self.bot.guilds), "message_cache", limited=False)
        if result is None:
            return
        added, channels, failures = result
        print(f"[cache] {added} messages chargés depuis {channels} salons", flush=True)
        if failures:
            text = f"Chargement du cache : {len(failures)} salon(s) ignoré(s) : {', '.join(failures)}"
            await report_error(self.bot, text, "message_cache")

    async def load_step(self, coro, origine: str, forbidden: str | None = None, *, limited: bool = True):
        """Une étape du chargement, au plus step_timeout s (limited=False : sans limite) : son échec est signalé sans
        bloquer les suivantes. Retourne le résultat de l'étape, ou None si elle a échoué.
        """
        limit = self.step_timeout if limited else None
        try:
            return await asyncio.wait_for(coro, limit)
        except TimeoutError:
            await report_error(self.bot, f"étape bloquée plus de {limit:g} s, abandonnée", origine)
        except discord.Forbidden as error:
            await report_error(self.bot, forbidden or error, origine)
        except Exception as error:
            await report_error(self.bot, error, origine)
        return None

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry):
        await self.audit.add(entry)

    async def moderator(self, actions, target):
        """Auteur de l'entrée d'audit correspondante (attendue 2 s), ou None."""
        entry = await self.audit.find(actions, target)
        return entry.user if entry is not None else None

    # --- Messages ---------------------------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        self.cache.add(message)

    @commands.Cog.listener()
    @log_errors("on_raw_message_edit")
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent):
        message = payload.message
        if message.author.bot:
            return  # modifications des bots (messages Warframe mis à jour en continu, logs corrigés) : pas de log
        entry = self.cache.get(payload.message_id)
        try:
            if message.edited_at is None:
                return  # jamais édité par son auteur : mise à jour de Discord (ex. aperçu de lien ajouté)
            if payload.cached_message:
                before = payload.cached_message.content
            else:
                before = entry.content if entry else None
            if before != message.content:
                await self.send(render.edit(message.author, payload.channel_id, before, message.content))
        finally:
            self.cache.update_content(payload.message_id, message.content)

    @commands.Cog.listener()
    @log_errors("on_raw_message_delete")
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        entry = self.cache.pop(payload.message_id)
        message = CachedMessage.from_message(payload.cached_message) if payload.cached_message else entry
        if message is None:
            await self.send(render.delete_unknown(payload.channel_id))
            return
        if message.author.bot:
            return
        log = await self.send(render.delete(message.author, payload.channel_id, message.content, message.attachments))
        guild = self.bot.get_guild(payload.guild_id) if payload.guild_id else None
        try:
            moderator = await self.audit.message_delete_moderator(guild, message.author.id, payload.channel_id)
        except discord.Forbidden:
            await report_error(self.bot, MISSING_AUDIT, "logs_audit")
            return
        if moderator is not None and moderator.id != message.author.id:
            await log.edit(embed=render.delete(message.author, payload.channel_id, message.content, message.attachments, moderator))

    @commands.Cog.listener()
    @log_errors("on_raw_bulk_message_delete")
    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent):
        known = {m.id: CachedMessage.from_message(m) for m in payload.cached_messages}
        for message_id in payload.message_ids:
            entry = self.cache.pop(message_id)
            if entry is not None:
                known.setdefault(message_id, entry)
        messages = [m for m in known.values() if not m.author.bot]
        moderator = await self.moderator((Action.message_bulk_delete,), payload.channel_id)
        embed = render.bulk_delete(payload.channel_id, len(payload.message_ids), len(messages), moderator)
        await self.send(embed, render.bulk_file(messages) if messages else None)

    # --- Membres ----------------------------------------------------------------------------------------

    @commands.Cog.listener()
    @log_errors("on_member_join")
    async def on_member_join(self, member: discord.Member):
        try:
            invite = await self.invites.used_on_join(member.guild)
        except discord.Forbidden:
            invite = None
            await report_error(self.bot, MISSING_INVITES, "logs_invites")
        await self.send(render.join(member, invite))

    @commands.Cog.listener()
    @log_errors("on_raw_member_remove")
    async def on_raw_member_remove(self, payload: discord.RawMemberRemoveEvent):
        user = payload.user
        entry = await self.audit.find((Action.ban, Action.kick), user.id)
        if entry is None:
            await self.send(render.leave(user))
        elif entry.action == Action.kick:
            await self.send(render.kick(user, entry.user, entry.reason))
        # ban : le log de ban suffit

    @commands.Cog.listener()
    @log_errors("on_member_ban")
    async def on_member_ban(self, guild: discord.Guild, user: discord.abc.User):
        entry = await self.audit.find((Action.ban,), user.id)
        await self.send(render.ban(user, entry.user if entry else None, entry.reason if entry else None))

    @commands.Cog.listener()
    @log_errors("on_member_unban")
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        entry = await self.audit.find((Action.unban,), user.id)
        await self.send(render.unban(user, entry.user if entry else None, entry.reason if entry else None))

    @commands.Cog.listener()
    @log_errors("on_member_update")
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        before_roles, after_roles = set(before.roles), set(after.roles)
        for role in after_roles - before_roles:
            await self.send(render.role_added(after, role))
        for role in before_roles - after_roles:
            await self.send(render.role_removed(after, role))
        if before.nick != after.nick:
            await self.send(render.nick(after, before.nick, after.nick))

    @commands.Cog.listener()
    @log_errors("on_user_update")
    async def on_user_update(self, before: discord.User, after: discord.User):
        if before.name != after.name:
            await self.send(render.username(after, before.name, after.name))
        if before.global_name != after.global_name:
            await self.send(render.display_name(after, before.global_name, after.global_name))

    @commands.Cog.listener()
    @log_errors("on_voice_state_update")
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if before.channel is not None and after.channel is not None and before.channel.id == after.channel.id:
            return  # micro, casque, stream… : pas un changement de salon
        await self.send(render.voice(member, before, after, self.is_temp_voice))

    # --- Serveur ----------------------------------------------------------------------------------------

    @commands.Cog.listener()
    @log_errors("on_guild_channel_create")
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        if self.is_temp_voice(channel):
            return
        await self.send(render.channel_created(channel, await self.moderator((Action.channel_create,), channel.id)))

    @commands.Cog.listener()
    @log_errors("on_guild_channel_delete")
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        if self.is_temp_voice(channel):
            return
        await self.send(render.channel_deleted(channel, await self.moderator((Action.channel_delete,), channel.id)))

    @commands.Cog.listener()
    @log_errors("on_guild_role_create")
    async def on_guild_role_create(self, role: discord.Role):
        await self.send(render.role_created(role, await self.moderator((Action.role_create,), role.id)))

    @commands.Cog.listener()
    @log_errors("on_guild_role_delete")
    async def on_guild_role_delete(self, role: discord.Role):
        await self.send(render.role_deleted(role, await self.moderator((Action.role_delete,), role.id)))

    @commands.Cog.listener()
    @log_errors("on_invite_create")
    async def on_invite_create(self, invite: discord.Invite):
        self.invites.created(invite)
        await self.send(render.invite_created(invite))

    @commands.Cog.listener()
    @log_errors("on_invite_delete")
    async def on_invite_delete(self, invite: discord.Invite):
        state = self.invites.deleted(invite.code)
        moderator = await self.moderator((Action.invite_delete,), invite.code)
        await self.send(render.invite_deleted(invite, moderator, exhausted=state is not None and state.last_use))


async def setup(bot):  # pragma: no cover
    await bot.add_cog(Logs(bot))
