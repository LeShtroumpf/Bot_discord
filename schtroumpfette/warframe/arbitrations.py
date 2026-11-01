"""Arbitrages : planning (browse.wf) et tier list (Arbitration Goons).

Le worldstate officiel ne contient plus les arbitrages. La rotation est déterministe : browse.wf publie le
planning des années à venir (une ligne "timestamp,nœud" par heure). On le garde en cache disque.
"""
import bisect
import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

import aiohttp

SCHEDULE_URL = "https://browse.wf/arbys.txt"
SCHEDULE_TIMEOUT = aiohttp.ClientTimeout(total=60)
SCHEDULE_FILE = "arbys.txt"
MAX_AGE = dt.timedelta(days=7)
DURATION = dt.timedelta(hours=1)

DEFAULT_TIER = "F"
# Couleur de la barre de l'embed : la même que la lettre de l'emoji du tier (warframe/data/emojis/).
TIER_COLORS = {
    "S": 0xE74D15, "A": 0xDB2B2B, "B": 0xEEAE32, "C": 0x318DE3,
    "D": 0x15BA35, "SP": 0xC71DE9, "F": 0x6E6E6E,
}
NOTEWORTHY_TIERS = ("S", "A", "SP")
DEFAULT_EMOJIS = {"S": "🟦", "A": "🟩", "B": "🟨", "C": "🟧", "D": "🟥", "SP": "🟪", "F": "⬜"}


class ScheduleError(Exception):
    """Planning des arbitrages injoignable ou invalide."""


@dataclass(frozen=True)
class Arbitration:
    start: dt.datetime
    node: str

    @property
    def end(self) -> dt.datetime:
        return self.start + DURATION


@dataclass(frozen=True)
class Tier:
    tier: str = DEFAULT_TIER
    saryn: bool = False


def load_tiers(path: Path) -> dict[str, Tier]:
    """Tier list : {"tiers": {"SolNode450": {"tier": "S", "saryn": true}}}. Un nœud absent est en tier F."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {node: Tier(entry["tier"], bool(entry.get("saryn"))) for node, entry in data["tiers"].items()}


def load_tier_emojis(path: Path) -> dict[str, str]:
    """Emoji de chaque tier ("emojis" du fichier), complété par les emojis Unicode par défaut."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {**DEFAULT_EMOJIS, **data.get("emojis", {})}


class Schedule:
    def __init__(self, entries: list[tuple[int, str]] | None = None):
        self.entries = sorted(entries or [])
        self._starts = [start for start, _ in self.entries]

    @classmethod
    def parse(cls, text: str) -> "Schedule":
        entries = []
        for line in text.splitlines():
            start, _, node = line.strip().partition(",")
            if start.isdigit() and node:
                entries.append((int(start), node))
        return cls(entries)

    def __bool__(self) -> bool:
        return bool(self.entries)

    def _at(self, index: int) -> Arbitration:
        start, node = self.entries[index]
        return Arbitration(dt.datetime.fromtimestamp(start, tz=dt.UTC), node)

    def current(self, now: dt.datetime) -> Arbitration | None:
        index = bisect.bisect_right(self._starts, now.timestamp()) - 1
        if index < 0:
            return None
        arbitration = self._at(index)
        return arbitration if now < arbitration.end else None

    def upcoming(self, now: dt.datetime, within: dt.timedelta) -> list[Arbitration]:
        first = bisect.bisect_right(self._starts, now.timestamp())
        last = bisect.bisect_right(self._starts, (now + within).timestamp())
        return [self._at(i) for i in range(first, last)]


def noteworthy(schedule: Schedule, tiers: dict[str, Tier], now: dt.datetime, within: dt.timedelta,
               exclude: list[Arbitration], limit: int = 5) -> list[Arbitration]:
    """Prochains arbitrages S, A ou SP, sans ceux déjà listés dans `exclude`."""
    found = [a for a in schedule.upcoming(now, within)
             if tiers.get(a.node, Tier()).tier in NOTEWORTHY_TIERS and a not in exclude]
    return found[:limit]


def read_cache(cache_dir: Path) -> tuple[Schedule, dt.datetime] | None:
    path = cache_dir / SCHEDULE_FILE
    try:
        schedule = Schedule.parse(path.read_text(encoding="utf-8"))
        mtime = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.UTC)
    except OSError:
        return None
    return (schedule, mtime) if schedule else None


async def download_schedule(session: aiohttp.ClientSession, cache_dir: Path) -> Schedule:
    try:
        async with session.get(SCHEDULE_URL, timeout=SCHEDULE_TIMEOUT) as response:
            response.raise_for_status()
            text = await response.text()
    except (aiohttp.ClientError, TimeoutError) as error:
        raise ScheduleError(f"{type(error).__name__}: {error}") from error
    schedule = Schedule.parse(text)
    if not schedule:
        raise ScheduleError("planning vide ou illisible")
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = cache_dir / (SCHEDULE_FILE + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(cache_dir / SCHEDULE_FILE)
    return schedule
