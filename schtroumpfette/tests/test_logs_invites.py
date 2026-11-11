from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from logs import invites as invites_module
from logs.invites import InviteTracker


def invite(code, uses=0, max_uses=0, inviter="toto"):
    return MagicMock(code=code, uses=uses, max_uses=max_uses, inviter=inviter)


def guild(*invites, vanity=None):
    g = MagicMock(features=["VANITY_URL"] if vanity is not None else [])
    g.invites = AsyncMock(return_value=list(invites))
    g.vanity_invite = AsyncMock(return_value=MagicMock(uses=vanity))
    return g


@pytest.mark.asyncio
async def test_invite_whose_count_grew_is_found():
    tracker = InviteTracker()
    await tracker.load(guild(invite("a", 1), invite("b", 5)))
    used = await tracker.used_on_join(guild(invite("a", 1), invite("b", 6)))
    assert (used.code, used.inviter, used.uses) == ("b", "toto", 6)


@pytest.mark.asyncio
async def test_invite_gone_at_its_last_use_is_found():
    tracker = InviteTracker()
    await tracker.load(guild(invite("a", 0, max_uses=1), invite("b", 2)))
    used = await tracker.used_on_join(guild(invite("b", 2)))
    assert (used.code, used.uses) == ("a", 1)


@pytest.mark.asyncio
async def test_invite_deleted_by_hand_is_not_a_candidate():
    tracker = InviteTracker()
    await tracker.load(guild(invite("a", 0, max_uses=10)))
    tracker.deleted("a")
    assert await tracker.used_on_join(guild()) is None


@pytest.mark.asyncio
async def test_exhausted_invite_deleted_just_before_the_join(monkeypatch):
    tracker = InviteTracker()
    await tracker.load(guild(invite("a", 4, max_uses=5)))
    state = tracker.deleted("a")
    assert state.last_use
    used = await tracker.used_on_join(guild())
    assert used.code == "a"


def test_deleted_invites_are_forgotten_after_a_while(monkeypatch):
    tracker = InviteTracker()
    tracker.created(invite("a"))
    clock = iter([0, 30, invites_module.DELETED_KEEP + 1])
    monkeypatch.setattr(invites_module, "monotonic", lambda: next(clock))
    tracker.deleted("a")
    tracker.created(invite("b"))
    tracker.deleted("b")
    tracker.deleted("c")  # inconnue : None, et "a" est oubliée
    assert set(tracker.invites) == {"b"}


@pytest.mark.asyncio
async def test_two_candidates_means_unknown():
    tracker = InviteTracker()
    await tracker.load(guild(invite("a", 1), invite("b", 1)))
    assert await tracker.used_on_join(guild(invite("a", 2), invite("b", 2))) is None


@pytest.mark.asyncio
async def test_vanity_url():
    tracker = InviteTracker()
    await tracker.load(guild(invite("a", 1), vanity=10))
    used = await tracker.used_on_join(guild(invite("a", 1), vanity=11))
    assert used.code is None


@pytest.mark.asyncio
async def test_new_invites_are_tracked_after_a_join():
    tracker = InviteTracker()
    await tracker.load(guild())
    await tracker.used_on_join(guild(invite("new", 0)))
    used = await tracker.used_on_join(guild(invite("new", 1)))
    assert used.code == "new"


@pytest.mark.asyncio
async def test_forbidden_goes_up():
    g = guild()
    g.invites.side_effect = discord.Forbidden(MagicMock(status=403), "non")
    with pytest.raises(discord.Forbidden):
        await InviteTracker().used_on_join(g)
