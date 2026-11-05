"""Cycles des zones ouvertes : Cetus (Plaines d'Eidolon), Vallée Orbis, Puits Cambion."""
import datetime as dt
import json
from dataclasses import dataclass

from . import DATA_DIR
from .worldstate import ws_date

# Cetus et Cambion suivent le cycle des primes d'Ostron : 150 min, dont les 50 dernières de nuit (Vome).
CETUS_CYCLE = dt.timedelta(minutes=150)
CETUS_NIGHT = dt.timedelta(minutes=50)

# Vallée Orbis : cycle fixe de 1 600 s (400 s chaud puis 1 200 s froid), référence reprise de warframestat.
VALLIS_REFERENCE = dt.datetime.fromtimestamp(1541837628, tz=dt.UTC)
VALLIS_CYCLE = dt.timedelta(seconds=1600)
VALLIS_WARM = dt.timedelta(seconds=400)

# Circuit : rotation hebdomadaire fixe. Tables reprises de browse.wf (warframestat ne donne pas la date de rotation et tombe souvent).
CIRCUIT = json.loads((DATA_DIR / "circuit_rotation.json").read_text(encoding="utf-8"))
CIRCUIT_EPOCH = dt.datetime.fromtimestamp(CIRCUIT["epoch"], tz=dt.UTC)
WEEK = dt.timedelta(days=7)


@dataclass(frozen=True)
class Cycle:
    state: str
    ends_at: dt.datetime
    next_state: str


def cetus_bounty_end(worldstate: dict | None) -> dt.datetime | None:
    """Fin du cycle de primes d'Ostron dans le worldstate."""
    for mission in (worldstate or {}).get("syndicateMissions", []):
        if mission.get("syndicateKey") == "Ostrons":
            return ws_date(mission.get("expiry"))
    return None


def _cetus_phase(bounty_end: dt.datetime, now: dt.datetime) -> tuple[bool, dt.datetime]:
    """(jour ?, fin de la phase). Le cycle étant fixe, une fin de primes passée est extrapolée."""
    if now >= bounty_end:
        bounty_end += CETUS_CYCLE * ((now - bounty_end) // CETUS_CYCLE + 1)
    night_start = bounty_end - CETUS_NIGHT
    return (True, night_start) if now < night_start else (False, bounty_end)


def cetus(bounty_end: dt.datetime, now: dt.datetime) -> Cycle:
    day, ends_at = _cetus_phase(bounty_end, now)
    return Cycle("jour", ends_at, "nuit") if day else Cycle("nuit", ends_at, "jour")


def cambion(bounty_end: dt.datetime, now: dt.datetime) -> Cycle:
    day, ends_at = _cetus_phase(bounty_end, now)
    return Cycle("Fass", ends_at, "Vome") if day else Cycle("Vome", ends_at, "Fass")


def circuit_rotation_end(now: dt.datetime) -> dt.datetime:
    """Fin de la rotation en cours : le lundi suivant à 00:00 UTC."""
    return CIRCUIT_EPOCH + WEEK * ((now - CIRCUIT_EPOCH) // WEEK + 1)


def circuit_choices(now: dt.datetime) -> tuple[list[str], list[str]]:
    """(Warframes, armes Incarnon) de la semaine contenant now."""
    week = (now - CIRCUIT_EPOCH) // WEEK
    return CIRCUIT["warframes"][week % len(CIRCUIT["warframes"])], CIRCUIT["incarnon"][week % len(CIRCUIT["incarnon"])]


def vallis(now: dt.datetime) -> Cycle:
    elapsed = (now - VALLIS_REFERENCE) % VALLIS_CYCLE
    cycle_start = now - elapsed
    if elapsed < VALLIS_WARM:
        return Cycle("chaud", cycle_start + VALLIS_WARM, "froid")
    return Cycle("froid", cycle_start + VALLIS_CYCLE, "chaud")
