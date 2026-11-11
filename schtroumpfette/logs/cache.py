"""Cache maison des messages, pour que les logs de suppression / modification connaissent l'auteur et le texte.

Le cache de discord.py est petit (max_messages) et vide après un redémarrage : ce cache garde l'essentiel
des MAX_MESSAGES derniers messages, et se complète avec l'historique récent de chaque salon à chaque on_ready.
"""
from collections import OrderedDict
from dataclasses import dataclass

import discord

MAX_MESSAGES = 2000
HISTORY_PER_CHANNEL = 10


@dataclass
class CachedMessage:
    author: discord.abc.User
    channel_id: int
    content: str
    attachments: tuple[str, ...] = ()
    message_id: int = 0

    @property
    def created_at(self):
        return discord.utils.snowflake_time(self.message_id)

    @classmethod
    def from_message(cls, message: discord.Message) -> "CachedMessage":
        return cls(
            author=message.author,
            channel_id=message.channel.id,
            content=message.content,
            attachments=tuple(a.filename for a in message.attachments),
            message_id=message.id,
        )


def root_channel_id(channel) -> int:
    """Un fil est rattaché à son salon parent pour les exclusions."""
    parent_id = getattr(channel, "parent_id", None) if isinstance(channel, discord.Thread) else None
    return parent_id or channel.id


class MessageCache:
    def __init__(self, max_messages: int = MAX_MESSAGES):
        self.max_messages = max_messages
        self.messages: OrderedDict[int, CachedMessage] = OrderedDict()
        self.excluded: set[int] = set()

    def __len__(self) -> int:
        return len(self.messages)

    def accepts(self, message: discord.Message) -> bool:
        return message.guild is not None and not message.author.bot and root_channel_id(message.channel) not in self.excluded

    def add(self, message: discord.Message, *, replace: bool = True) -> bool:
        """Met le message en cache s'il est accepté. replace=False : un ID déjà présent n'est pas écrasé."""
        if not self.accepts(message) or (not replace and message.id in self.messages):
            return False
        self.messages[message.id] = CachedMessage.from_message(message)
        while len(self.messages) > self.max_messages:
            self.messages.popitem(last=False)
        return True

    def get(self, message_id: int) -> CachedMessage | None:
        return self.messages.get(message_id)

    def update_content(self, message_id: int, content: str) -> None:
        entry = self.messages.get(message_id)
        if entry is not None:
            entry.content = content

    def pop(self, message_id: int) -> CachedMessage | None:
        return self.messages.pop(message_id, None)

    async def load(self, guilds, *, limit: int = HISTORY_PER_CHANNEL) -> tuple[int, int, list[str]]:
        """Complète le cache avec les `limit` derniers messages de chaque salon texte et vocal.

        Retourne (messages ajoutés, salons lus, échecs). Un salon sans permission est ignoré sans échec.
        """
        history: list[discord.Message] = []
        channels, failures = 0, []
        for guild in guilds:
            for channel in [*guild.text_channels, *guild.voice_channels]:
                if channel.id in self.excluded:
                    continue
                permissions = channel.permissions_for(guild.me)
                if not (permissions.view_channel and permissions.read_message_history):
                    continue
                try:
                    history += [message async for message in channel.history(limit=limit)]
                except discord.Forbidden:
                    continue
                except Exception as error:
                    failures.append(f"{channel.mention} ({type(error).__name__}: {error})")
                    continue
                channels += 1
        history.sort(key=lambda message: message.created_at)
        added = sum(self.add(message, replace=False) for message in history)
        return added, channels, failures


message_cache = MessageCache()
