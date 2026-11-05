import datetime as dt
import functools
from dataclasses import dataclass

import discord
from discord.ext import commands

from utils.embed import logs_message

ERROR_WINDOW = dt.timedelta(minutes=10)  # une même erreur n'est pas renvoyée dans le salon avant ce délai


@dataclass
class ErrorState:
    sent_at: dt.datetime
    repeats: int = 0  # occurrences non envoyées depuis sent_at


def log_failures(method):
    """Un log qui échoue (construction de l'embed ou envoi) devient une erreur loggée, sous le nom de la méthode."""
    @functools.wraps(method)
    async def wrapper(self, bot, *args, channel, **kwargs):
        try:
            await method(self, bot, *args, channel=channel, **kwargs)
        except Exception as error:
            await self.on_error_log(bot, error, origine=method.__name__, channel=channel)
    return wrapper


class EventLogs:
    def __init__(self):
        self.errors: dict[tuple[str, str], ErrorState] = {}

    async def send(self, channel: discord.TextChannel | None, embed: discord.Embed):
        """Seul point d'envoi des logs : un embed absent ou un salon introuvable est une erreur, jamais un envoi vide."""
        if embed is None:
            raise ValueError("embed de log absent")
        if channel is None:
            raise LookupError("salon de logs introuvable")
        await channel.send(embed=embed)

    def error_repeats(self, key: tuple[str, str], now: dt.datetime) -> int | None:
        """Occurrences à signaler avec cette erreur, ou None si elle a déjà été envoyée il y a moins de ERROR_WINDOW."""
        state = self.errors.get(key)
        if state and now - state.sent_at < ERROR_WINDOW:
            state.repeats += 1
            return None
        self.errors = {k: s for k, s in self.errors.items() if s.repeats or now - s.sent_at < ERROR_WINDOW}
        self.errors[key] = ErrorState(sent_at=now)
        return state.repeats if state else 0

    async def on_error_log(self, bot: commands.Bot, error, origine: str, channel: discord.TextChannel | None = None):
        """Ne lève jamais d'exception : la console reçoit chaque erreur, le salon une seule par ERROR_WINDOW."""
        text = str(error) or type(error).__name__
        print(f"[{origine}] {text}", flush=True)
        repeats = self.error_repeats((origine, text), dt.datetime.now(dt.UTC))
        if channel is None or repeats is None:
            return
        try:
            await channel.send(embed=logs_message.error(origine, text, repeats))
        except Exception as e:
            print(f"[{origine}] log impossible : {e}", flush=True)

    @log_failures
    async def on_member_join_log(self, bot: commands.Bot, member: discord.Member, *, channel: discord.TextChannel):
        await self.send(channel, logs_message.join(member))

    @log_failures
    async def on_message_edit_log(self, bot: commands.Bot, payload: discord.RawMessageUpdateEvent, *, channel: discord.TextChannel):
        after = payload.message.content
        before = payload.cached_message.content if payload.cached_message else None
        if before == after:
            return  # pas de changement de texte (ex. aperçu de lien ajouté)
        await self.send(channel, logs_message.edit(payload.message.author, payload.channel_id, before, after))

    @log_failures
    async def on_message_delete_log(self, bot: commands.Bot, payload: discord.RawMessageDeleteEvent, *, channel: discord.TextChannel):
        message = payload.cached_message
        if message:
            await self.send(channel, logs_message.delete(message.author, payload.channel_id, message.content))
        else:
            await self.send(channel, logs_message.delete_unknown(payload.channel_id))

    @log_failures
    async def on_raw_member_remove_log(self, bot: commands.Bot, payload: discord.RawMemberRemoveEvent, *, channel: discord.TextChannel):
        await self.send(channel, logs_message.leave(payload.user))

    @log_failures
    async def on_voice_state_update_log(self, bot: commands.Bot, member: discord.Member, before: discord.VoiceState,
                                        after: discord.VoiceState, *, channel: discord.TextChannel):
        if before.channel is not None and after.channel is not None and before.channel.id == after.channel.id:
            return
        await self.send(channel, logs_message.voice(member, before, after))

    @log_failures
    async def on_member_update_log(self, bot: commands.Bot, before: discord.Member, after: discord.Member, *, channel: discord.TextChannel):
        before_roles, after_roles = set(before.roles), set(after.roles)
        for role in after_roles - before_roles:
            await self.send(channel, logs_message.role_added(after, role))
        for role in before_roles - after_roles:
            await self.send(channel, logs_message.role_removed(after, role))


event_logs = EventLogs()
