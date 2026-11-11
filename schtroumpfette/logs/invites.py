"""Invitation utilisée par un membre qui rejoint : comparaison des compteurs d'utilisation.

Discord ne dit pas quelle invitation a servi : on garde les compteurs (chargés à on_ready, suivis à la création
et à la suppression) et on cherche, à chaque arrivée, celle qui a bougé. Une invitation qui disparaît à sa
dernière utilisation compte aussi. Plusieurs candidates = inconnue.

Lire la liste des invitations demande la permission « Gérer le serveur » : discord.Forbidden remonte à l'appelant.
"""
from time import monotonic
from dataclasses import dataclass

from .render import InviteUse

DELETED_KEEP = 60  # secondes pendant lesquelles une invitation supprimée reste candidate


@dataclass
class InviteState:
    uses: int
    max_uses: int
    inviter: object = None
    deleted_at: float | None = None

    @property
    def last_use(self) -> bool:
        """La prochaine utilisation l'épuise."""
        return bool(self.max_uses) and self.uses + 1 >= self.max_uses


class InviteTracker:
    def __init__(self):
        self.invites: dict[str, InviteState] = {}
        self.vanity_uses: int | None = None

    @staticmethod
    def state(invite) -> InviteState:
        return InviteState(uses=invite.uses or 0, max_uses=invite.max_uses or 0, inviter=invite.inviter)

    async def vanity(self, guild) -> int | None:
        if "VANITY_URL" not in guild.features:
            return None
        invite = await guild.vanity_invite()
        return invite.uses if invite is not None else None

    async def load(self, guild):
        self.invites = {invite.code: self.state(invite) for invite in await guild.invites()}
        self.vanity_uses = await self.vanity(guild)

    def created(self, invite):
        self.invites[invite.code] = self.state(invite)

    def deleted(self, code: str) -> InviteState | None:
        """Marque l'invitation supprimée (elle reste candidate DELETED_KEEP s) et retourne son dernier état connu."""
        now = monotonic()
        self.invites = {c: s for c, s in self.invites.items() if s.deleted_at is None or now - s.deleted_at < DELETED_KEEP}
        state = self.invites.get(code)
        if state is not None:
            state.deleted_at = now
        return state

    async def used_on_join(self, guild) -> InviteUse | None:
        current = {invite.code: invite for invite in await guild.invites()}
        now = monotonic()
        candidates: list[InviteUse] = []
        for code, state in self.invites.items():
            invite = current.get(code)
            if invite is not None:
                if (invite.uses or 0) > state.uses:
                    candidates.append(InviteUse(code, invite.inviter or state.inviter, invite.uses))
            elif state.last_use and (state.deleted_at is None or now - state.deleted_at < DELETED_KEEP):
                candidates.append(InviteUse(code, state.inviter, state.uses + 1))
        vanity = await self.vanity(guild)
        if vanity is not None and self.vanity_uses is not None and vanity > self.vanity_uses:
            candidates.append(InviteUse(None))
        self.vanity_uses = vanity
        self.invites = {code: self.state(invite) for code, invite in current.items()}
        return candidates[0] if len(candidates) == 1 else None
