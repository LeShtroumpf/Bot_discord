"""Le « qui » des logs, depuis le journal d'audit.

Discord pousse chaque nouvelle entrée (`on_audit_log_entry_create`) : on garde celles des KEEP dernières secondes
et un event qui a besoin du modo attend au plus WAIT secondes que la sienne arrive.

Cas particulier des suppressions de messages : Discord regroupe les entrées `message_delete` (même modo, même
auteur, même salon, quelques minutes) en augmentant leur compteur, sans nouvel event. Repli : lecture des dernières
entrées et comparaison des compteurs avec ceux déjà vus.
"""
import asyncio
import datetime as dt
from collections import deque

import discord

KEEP = dt.timedelta(seconds=30)
WAIT = 2.0
FRESH = dt.timedelta(seconds=10)  # une entrée jamais vue plus récente que ça vient d'être créée
FETCH_LIMIT = 20

MESSAGE_DELETE = discord.AuditLogAction.message_delete


def target_id(entry):
    return getattr(entry.target, "id", None)


def extra_channel_id(entry):
    return getattr(getattr(entry.extra, "channel", None), "id", None)


class AuditTracker:
    def __init__(self):
        self.recent: deque[discord.AuditLogEntry] = deque()
        self.used: set[int] = set()  # entrées message_delete déjà attribuées
        self.counts: dict[int, int] = {}  # id d'entrée message_delete → compteur vu
        self.condition = asyncio.Condition()
        self.wait = WAIT

    @staticmethod
    def now() -> dt.datetime:
        return dt.datetime.now(dt.UTC)

    def prune(self):
        limit = self.now() - KEEP
        while self.recent and self.recent[0].created_at < limit:
            self.used.discard(self.recent.popleft().id)

    async def add(self, entry: discord.AuditLogEntry):
        self.recent.append(entry)
        if entry.action == MESSAGE_DELETE:
            self.counts[entry.id] = getattr(entry.extra, "count", 1) or 1
        self.prune()
        async with self.condition:
            self.condition.notify_all()

    def match(self, actions, target, check=None, consume=False):
        self.prune()
        for entry in reversed(self.recent):
            if entry.action in actions and target_id(entry) == target and entry.id not in self.used and (check is None or check(entry)):
                if consume:
                    self.used.add(entry.id)
                return entry
        return None

    async def find(self, actions, target, *, check=None, consume=False, timeout: float | None = None):
        """Entrée récente pour cette cible, attendue au plus `timeout` secondes (défaut : self.wait). None si rien."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + (self.wait if timeout is None else timeout)
        async with self.condition:
            while True:
                entry = self.match(actions, target, check, consume)
                remaining = deadline - loop.time()
                if entry is not None or remaining <= 0:
                    return entry
                try:
                    await asyncio.wait_for(self.condition.wait(), remaining)
                except TimeoutError:
                    return self.match(actions, target, check, consume)

    async def fetch_counts(self, guild) -> list[tuple[discord.AuditLogEntry, bool]]:
        """Lit les dernières entrées message_delete. Retourne (entrée, a augmenté depuis la dernière lecture)."""
        result, counts = [], {}
        async for entry in guild.audit_logs(action=MESSAGE_DELETE, limit=FETCH_LIMIT):
            count = getattr(entry.extra, "count", 1) or 1
            previous = self.counts.get(entry.id)
            grew = count > previous if previous is not None else self.now() - entry.created_at < FRESH
            counts[entry.id] = count
            result.append((entry, grew))
        self.counts = counts
        return result

    async def load_baseline(self, guild):
        await self.fetch_counts(guild)

    async def message_delete_moderator(self, guild, author_id: int, channel_id: int):
        """Modo qui a supprimé le message de author_id dans channel_id, ou None (l'auteur lui-même, ou inconnu).

        discord.Forbidden remonte : à l'appelant de le signaler.
        """
        def same_channel(entry):
            return extra_channel_id(entry) == channel_id

        entry = await self.find((MESSAGE_DELETE,), author_id, check=same_channel, consume=True)
        if entry is not None:
            return entry.user
        if guild is None:
            return None
        for entry, grew in await self.fetch_counts(guild):
            if grew and target_id(entry) == author_id and same_channel(entry):
                return entry.user
        return None
