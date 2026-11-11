import asyncio
import datetime as dt
from unittest.mock import MagicMock

import discord
import pytest

from logs.audit import KEEP, AuditTracker

Action = discord.AuditLogAction
NOW = dt.datetime(2026, 11, 11, 12, 0, tzinfo=dt.UTC)
_ids = iter(range(1000, 10**6))


def entry(action, target, *, ago=0, count=1, channel=None, moderator="modo", entry_id=None):
    e = MagicMock(id=entry_id or next(_ids), action=action, created_at=NOW - dt.timedelta(seconds=ago), reason="raison")
    e.target = MagicMock(id=target)
    e.user = moderator
    e.extra = MagicMock(count=count)
    e.extra.channel = MagicMock(id=channel) if channel is not None else None
    return e


class Guild:
    """Faux serveur : audit_logs() rend les entrées données (ou lève error)."""
    def __init__(self, entries=(), error=None):
        self.entries, self.error, self.calls = list(entries), error, 0

    def audit_logs(self, action, limit):
        self.calls += 1

        async def iterate():
            if self.error is not None:
                raise self.error
            for e in self.entries[:limit]:
                if e.action == action:
                    yield e
        return iterate()


@pytest.fixture
def tracker(monkeypatch):
    t = AuditTracker()
    monkeypatch.setattr(AuditTracker, "now", staticmethod(lambda: NOW))
    return t


@pytest.mark.asyncio
async def test_find_an_entry_already_there(tracker):
    await tracker.add(entry(Action.kick, 42))
    found = await tracker.find((Action.ban, Action.kick), 42, timeout=0)
    assert found.action == Action.kick


@pytest.mark.asyncio
async def test_find_waits_for_a_late_entry(tracker):
    async def late():
        await asyncio.sleep(0.01)
        await tracker.add(entry(Action.ban, 42))
    task = asyncio.create_task(late())
    found = await tracker.find((Action.ban,), 42, timeout=1)
    await task
    assert found is not None and found.action == Action.ban


@pytest.mark.asyncio
async def test_find_gives_up_after_the_timeout(tracker):
    await tracker.add(entry(Action.kick, 7))  # autre cible
    assert await tracker.find((Action.kick,), 42, timeout=0.01) is None


@pytest.mark.asyncio
async def test_old_entries_are_forgotten(tracker):
    await tracker.add(entry(Action.kick, 42, ago=KEEP.total_seconds() + 1))
    assert await tracker.find((Action.kick,), 42, timeout=0) is None
    assert len(tracker.recent) == 0


@pytest.mark.asyncio
async def test_invite_target_is_its_code(tracker):
    await tracker.add(entry(Action.invite_delete, "abc"))
    assert await tracker.find((Action.invite_delete,), "abc", timeout=0) is not None


@pytest.mark.asyncio
async def test_message_delete_entry_from_the_event_is_used_once(tracker):
    await tracker.add(entry(Action.message_delete, 42, channel=7))
    guild = Guild()
    assert await tracker.message_delete_moderator(guild, 42, 7) == "modo"
    assert guild.calls == 0  # pas de lecture du journal
    assert await tracker.message_delete_moderator(None, 42, 7) is None  # entrée déjà attribuée


@pytest.mark.asyncio
async def test_message_delete_other_channel_is_not_matched(tracker):
    await tracker.add(entry(Action.message_delete, 42, channel=8))
    assert await tracker.find((Action.message_delete,), 42, check=lambda e: e.extra.channel.id == 7, timeout=0) is None


@pytest.mark.asyncio
async def test_grouped_message_delete_is_found_by_its_count(tracker, monkeypatch):
    monkeypatch.setattr(tracker, "find", _no_event)
    grouped = entry(Action.message_delete, 42, ago=120, count=2, channel=7, entry_id=1)
    await tracker.load_baseline(Guild([grouped]))
    grouped.extra.count = 3  # Discord a regroupé une nouvelle suppression
    assert await tracker.message_delete_moderator(Guild([grouped]), 42, 7) == "modo"
    assert await tracker.message_delete_moderator(Guild([grouped]), 42, 7) is None  # compteur inchangé


@pytest.mark.asyncio
async def test_new_message_delete_entry_missed_by_the_event(tracker, monkeypatch):
    monkeypatch.setattr(tracker, "find", _no_event)
    fresh = entry(Action.message_delete, 42, ago=3, channel=7)
    old = entry(Action.message_delete, 42, ago=60, channel=7)
    assert await tracker.message_delete_moderator(Guild([old]), 42, 7) is None  # jamais vue mais ancienne
    assert await tracker.message_delete_moderator(Guild([fresh]), 42, 7) == "modo"


@pytest.mark.asyncio
async def test_self_deletion_has_no_moderator(tracker, monkeypatch):
    monkeypatch.setattr(tracker, "find", _no_event)
    other = entry(Action.message_delete, 99, ago=200, count=4, channel=7)
    guild = Guild([other])
    await tracker.load_baseline(guild)
    assert await tracker.message_delete_moderator(guild, 42, 7) is None


@pytest.mark.asyncio
async def test_forbidden_audit_log_goes_up(tracker, monkeypatch):
    monkeypatch.setattr(tracker, "find", _no_event)
    with pytest.raises(discord.Forbidden):
        await tracker.message_delete_moderator(Guild(error=discord.Forbidden(MagicMock(status=403), "non")), 42, 7)


async def _no_event(*args, **kwargs):
    return None
