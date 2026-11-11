"""Embeds du salon de logs : une méthode par type de log, fonctions pures.

Noms de salons : mention quand le salon existe forcément (création, vocal rejoint), nom en texte quand il peut
avoir disparu au moment où on lit le log (suppression, vocal quitté) — Discord résout `<#id>` à l'affichage.
"""
import io
from dataclasses import dataclass
from datetime import datetime, timezone

import discord
from dateutil.relativedelta import relativedelta

GREEN, BLUE, ORANGE, SWITCH, RED, DARK_RED = 0x00ff10, 0x002aff, 0xff7d00, 0xff8333, 0xff0000, 0x8b0000

CHANNEL_TYPES = {
    discord.ChannelType.text: "texte",
    discord.ChannelType.voice: "vocal",
    discord.ChannelType.category: "catégorie",
    discord.ChannelType.news: "annonces",
    discord.ChannelType.forum: "forum",
    discord.ChannelType.stage_voice: "scène",
    discord.ChannelType.media: "média",
}


@dataclass
class InviteUse:
    """Invitation utilisée par un membre qui rejoint. code None = URL personnalisée du serveur."""
    code: str | None
    inviter: discord.abc.User | None = None
    uses: int = 0


def channel_type(channel) -> str:
    return CHANNEL_TYPES.get(getattr(channel, "type", None), "salon")


def duration_text(seconds: int | None) -> str:
    """Durée de validité d'une invitation : 0 ou None = illimitée."""
    if not seconds:
        return "illimitée"
    parts = []
    for size, singular, plural in ((86400, "jour", "jours"), (3600, "heure", "heures"), (60, "minute", "minutes")):
        count, seconds = divmod(seconds, size)
        if count:
            parts.append(f"{count} {singular if count == 1 else plural}")
    return " ".join(parts) or f"{seconds} secondes"


def voice_name(channel) -> str:
    return f"**🔊 {channel.name}**"


class LogsRender:
    FIELD_MAX = 1024
    NO_TEXT = "(pas de texte)"
    UNKNOWN_TEXT = "(ancien texte inconnu)"
    NO_REASON = "(pas de raison)"
    NO_NAME = "(aucun)"

    def _embed(self, color: int, description: str, user=None) -> discord.Embed:
        embed = discord.Embed(color=color, description=description, timestamp=datetime.now())
        if user is not None:
            embed.set_author(name=str(user), icon_url=user.display_avatar.url)  # avatar par défaut si pas de photo
        return embed

    def _field_text(self, text: str | None) -> str:
        """Texte pour un champ d'embed : jamais vide, jamais trop long. None = texte inconnu."""
        if text is None:
            return self.UNKNOWN_TEXT
        if len(text) > self.FIELD_MAX:
            return text[:self.FIELD_MAX - 1] + "…"
        return text or self.NO_TEXT

    @staticmethod
    def _by(moderator) -> str:
        return f" par {moderator.mention}" if moderator is not None else ""

    def _sanction(self, color: int, user, verb: str, moderator, reason: str | None) -> discord.Embed:
        embed = self._embed(color, f"{user.mention} a été {verb}{self._by(moderator)}.", user)
        embed.add_field(name="Raison:", value=self._field_text(reason or self.NO_REASON), inline=False)
        return embed

    # --- Messages ------------------------------------------------------------------------------------

    def edit(self, user, channel_id: int, before: str | None, after: str) -> discord.Embed:
        embed = self._embed(ORANGE, f"{user.mention} a modifié son message dans <#{channel_id}>.", user)
        embed.add_field(name="Après:", value=self._field_text(after), inline=False)
        embed.add_field(name="Avant:", value=self._field_text(before), inline=False)
        return embed

    def delete(self, user, channel_id: int, text: str, attachments: tuple[str, ...] = (), moderator=None) -> discord.Embed:
        if moderator is not None:
            description = f"Message de {user.mention} supprimé par {moderator.mention} dans <#{channel_id}>."
        else:
            description = f"{user.mention} a supprimé son message dans <#{channel_id}>."
        embed = self._embed(RED, description, user)
        embed.add_field(name="Avant:", value=self._field_text(text), inline=False)
        if attachments:
            embed.add_field(name="Pièces jointes:", value=self._field_text("\n".join(f"📎 {name}" for name in attachments)), inline=False)
        return embed

    def delete_unknown(self, channel_id: int) -> discord.Embed:
        """Message absent des caches : Discord ne donne ni l'auteur ni le texte."""
        return self._embed(RED, f"Un message a été supprimé dans <#{channel_id}> (auteur et texte inconnus).")

    def bulk_delete(self, channel_id: int, total: int, known: int, moderator=None) -> discord.Embed:
        description = f"🧹 {total} messages supprimés dans <#{channel_id}>{self._by(moderator)}."
        if known:
            description += f"\nDont {known} connus : voir le fichier joint."
        return self._embed(RED, description)

    def bulk_file(self, messages) -> discord.File:
        """Messages connus d'une suppression en masse (CachedMessage), du plus ancien au plus récent."""
        lines = []
        for message in sorted(messages, key=lambda m: m.message_id):
            when = message.created_at.astimezone().strftime("%d/%m %H:%M")
            line = f"[{when}] {message.author} : {message.content}"
            if message.attachments:
                line += " " + " ".join(f"📎 {name}" for name in message.attachments)
            lines.append(line)
        return discord.File(io.BytesIO("\n".join(lines).encode("utf-8")), filename="messages-supprimes.txt")

    # --- Membres -------------------------------------------------------------------------------------

    def join(self, user, invite: InviteUse | None = None) -> discord.Embed:
        embed = self._embed(GREEN, f"{user.mention} a rejoints le serveur.", user)
        age = relativedelta(datetime.now(timezone.utc), user.created_at)
        embed.add_field(name="Date de création de compte:", value=f"{age.years} année, {age.months} mois, {age.days} jours")
        embed.add_field(name="Invitation:", value=self.invite_text(invite), inline=False)
        return embed.set_thumbnail(url=user.display_avatar.url)

    @staticmethod
    def invite_text(invite: InviteUse | None) -> str:
        if invite is None:
            return "inconnue"
        if invite.code is None:
            return "URL personnalisée"
        inviter = invite.inviter.mention if invite.inviter is not None else "inconnu"
        return f"`{invite.code}` de {inviter} ({invite.uses} utilisations)"

    def leave(self, user) -> discord.Embed:
        embed = self._embed(RED, f"{user.mention} a quitté le serveur.", user)
        return embed.set_thumbnail(url=user.display_avatar.url)

    def kick(self, user, moderator, reason: str | None) -> discord.Embed:
        return self._sanction(RED, user, "exclu", moderator, reason)

    def ban(self, user, moderator, reason: str | None) -> discord.Embed:
        return self._sanction(DARK_RED, user, "banni", moderator, reason)

    def unban(self, user, moderator, reason: str | None) -> discord.Embed:
        return self._sanction(GREEN, user, "débanni", moderator, reason)

    def role_added(self, user, role) -> discord.Embed:
        return self._embed(BLUE, f"{user.mention} a obtenu le rôle {role.name}", user)

    def role_removed(self, user, role) -> discord.Embed:
        return self._embed(RED, f"{user.mention} a perdu le rôle {role.name}", user)

    def _renamed(self, user, what: str, before: str | None, after: str | None) -> discord.Embed:
        return self._embed(BLUE, f"{user.mention} a changé de {what} : **{before or self.NO_NAME}** → **{after or self.NO_NAME}**", user)

    def nick(self, user, before: str | None, after: str | None) -> discord.Embed:
        return self._renamed(user, "surnom", before, after)

    def username(self, user, before: str, after: str) -> discord.Embed:
        return self._renamed(user, "nom d'utilisateur", before, after)

    def display_name(self, user, before: str | None, after: str | None) -> discord.Embed:
        return self._renamed(user, "nom d'affichage", before, after)

    def voice(self, user, before, after) -> discord.Embed:
        if after.channel is None:
            return self._embed(RED, f"{user.mention} a quitté le vocal {voice_name(before.channel)}", user)
        if before.channel is None:
            return self._embed(BLUE, f"{user.mention} a rejoint le vocal {after.channel.mention}", user)
        return self._embed(SWITCH, f"{user.mention} a switch de vocal {voice_name(before.channel)} -> {after.channel.mention}", user)

    # --- Serveur -------------------------------------------------------------------------------------

    def channel_created(self, channel, moderator=None) -> discord.Embed:
        return self._embed(GREEN, f"Salon {channel.mention} ({channel_type(channel)}) créé{self._by(moderator)}.", moderator)

    def channel_deleted(self, channel, moderator=None) -> discord.Embed:
        return self._embed(RED, f"Salon **{channel.name}** ({channel_type(channel)}) supprimé{self._by(moderator)}.", moderator)

    def role_created(self, role, moderator=None) -> discord.Embed:
        return self._embed(GREEN, f"Rôle {role.mention} créé{self._by(moderator)}.", moderator)

    def role_deleted(self, role, moderator=None) -> discord.Embed:
        return self._embed(RED, f"Rôle **{role.name}** supprimé{self._by(moderator)}.", moderator)

    def invite_created(self, invite) -> discord.Embed:
        inviter = invite.inviter
        who = inviter.mention if inviter is not None else "Quelqu'un"
        channel = invite.channel.mention if invite.channel is not None else "le serveur"
        embed = self._embed(BLUE, f"{who} a créé une invitation pour {channel}.", inviter)
        embed.add_field(name="Code:", value=invite.code)
        embed.add_field(name="Validité:", value=duration_text(invite.max_age))
        embed.add_field(name="Utilisations max:", value=str(invite.max_uses) if invite.max_uses else "illimitées")
        return embed

    def invite_deleted(self, invite, moderator=None, exhausted: bool = False) -> discord.Embed:
        if exhausted and moderator is None:
            return self._embed(RED, f"Invitation **{invite.code}** épuisée.")
        name = getattr(invite.channel, "name", None)
        channel = f" pour **#{name}**" if name else ""
        return self._embed(RED, f"Invitation **{invite.code}**{channel} supprimée{self._by(moderator)}.", moderator)


render = LogsRender()
