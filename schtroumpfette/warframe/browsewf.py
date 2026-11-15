"""État du jeu (PC) via browse.wf : worldstate brut du jeu, invasions et cycle des primes.

C'est le seul module qui connaît le format brut : il le convertit en objets simples (identifiants du jeu, dates en UTC),
traduits ensuite au rendu. L'API officielle (api.warframe.com) refuse les serveurs OVH (403) ; browse.wf la republie.
Une entrée illisible est ignorée, les autres sont gardées.
"""
import datetime as dt
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

import aiohttp

BASE = "https://oracle.browse.wf/"
SOURCES = {
    "worldstate": BASE + "worldState.min.json",  # fissures, tempêtes, alertes, events, Baro
    "invasions": BASE + "invasions",
    "primes": BASE + "bounty-cycle",             # fin du cycle des primes d'Ostron (Cetus, Cambion)
}
HEADERS = {"User-Agent": "Schtroumpfette-Discord-Bot"}
TIMEOUT = aiohttp.ClientTimeout(total=10)
INFESTED = "FC_INFESTATION"


class SourceError(Exception):
    """Source injoignable ou réponse invalide. retry_after : attente demandée par le serveur, s'il en indique une."""

    def __init__(self, message: str, retry_after: dt.timedelta | None = None):
        super().__init__(message)
        self.retry_after = retry_after


# --- Objets ---------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Reward:
    counted: tuple[tuple[str, int], ...] = ()  # (chemin de l'objet, quantité)
    items: tuple[str, ...] = ()
    credits: int = 0


@dataclass(frozen=True)
class Fissure:
    node: str
    mission: str | None  # None pour une tempête : le type vient du nœud
    era: str             # "VoidT1" … "VoidT6"
    expiry: dt.datetime
    hard: bool = False
    storm: bool = False


@dataclass(frozen=True)
class Alert:
    node: str
    mission: str
    faction: str
    min_level: int | None
    max_level: int | None
    reward: Reward
    tag: str
    expiry: dt.datetime


@dataclass(frozen=True)
class Event:
    name: str            # clé de langue
    tag: str
    node: str | None
    count: int
    goal: int
    personal: bool
    reward: Reward
    expiry: dt.datetime


@dataclass(frozen=True)
class Camp:
    faction: str
    reward: Reward


@dataclass(frozen=True)
class Invasion:
    id: str
    node: str
    attacker: Camp
    defender: Camp

    @property
    def vs_infested(self) -> bool:
        return self.attacker.faction == INFESTED


@dataclass(frozen=True)
class Trader:
    node: str
    activation: dt.datetime
    expiry: dt.datetime
    manifest: tuple[tuple[str, int, int], ...] = ()  # (chemin de l'objet, ducats, crédits)


@dataclass(frozen=True)
class World:
    """Contenu de worldState.min.json utile au bot."""
    fissures: tuple[Fissure, ...] = ()
    alerts: tuple[Alert, ...] = ()
    events: tuple[Event, ...] = ()
    trader: Trader | None = None


# --- Lecture du format brut --------------------------------------------------------------------------------------

def mongo_date(value) -> dt.datetime:
    """{"$date": {"$numberLong": "1794755289285"}} (ms) -> datetime UTC."""
    return dt.datetime.fromtimestamp(int(value["$date"]["$numberLong"]) / 1000, dt.UTC)


def epoch(value, unit: float = 1) -> dt.datetime:
    """Horodatage en secondes (unit=1) ou en millisecondes (unit=1000) -> datetime UTC."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"horodatage invalide : {value!r}")
    return dt.datetime.fromtimestamp(value / unit, dt.UTC)


def oid(value) -> str:
    return value["$oid"] if isinstance(value, dict) else str(value)


def reward(raw) -> Reward:
    raw = raw if isinstance(raw, dict) else {}
    counted = tuple((c["ItemType"], int(c.get("ItemCount", 1))) for c in raw.get("countedItems") or [])
    return Reward(counted=counted, items=tuple(str(i) for i in raw.get("items") or []), credits=int(raw.get("credits") or 0))


def _each(entries, parse) -> list:
    """Convertit chaque entrée ; une entrée illisible (champ manquant, date invalide) est ignorée."""
    out = []
    for entry in entries if isinstance(entries, list) else []:
        try:
            out.append(parse(entry))
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError, OSError):
            continue
    return out


def _fissure(raw) -> Fissure:
    return Fissure(node=raw["Node"], mission=raw["MissionType"], era=raw["Modifier"], expiry=mongo_date(raw["Expiry"]),
                   hard=bool(raw.get("Hard")))


def _storm(raw) -> Fissure:
    return Fissure(node=raw["Node"], mission=None, era=raw["ActiveMissionTier"], expiry=mongo_date(raw["Expiry"]), storm=True)


def _alert(raw) -> Alert:
    info = raw["MissionInfo"]
    return Alert(node=info["location"], mission=info["missionType"], faction=info["faction"],
                 min_level=info.get("minEnemyLevel"), max_level=info.get("maxEnemyLevel"),
                 reward=reward(info.get("missionReward")), tag=raw.get("Tag", ""), expiry=mongo_date(raw["Expiry"]))


def _event(raw) -> Event:
    return Event(name=raw["Desc"], tag=raw.get("Tag", ""), node=raw.get("Node"), count=int(raw.get("Count") or 0),
                 goal=int(raw.get("Goal") or 0), personal=bool(raw.get("Personal")), reward=reward(raw.get("Reward")),
                 expiry=mongo_date(raw["Expiry"]))


def _trader(raw) -> Trader:
    manifest = tuple((m["ItemType"], int(m.get("PrimePrice") or 0), int(m.get("RegularPrice") or 0))
                     for m in raw.get("Manifest") or [])
    return Trader(node=raw["Node"], activation=mongo_date(raw["Activation"]), expiry=mongo_date(raw["Expiry"]), manifest=manifest)


def parse_world(data: dict) -> World:
    fissures = _each(data.get("ActiveMissions"), _fissure) + _each(data.get("VoidStorms"), _storm)
    traders = _each(data.get("VoidTraders"), _trader)
    return World(fissures=tuple(fissures), alerts=tuple(_each(data.get("Alerts"), _alert)),
                 events=tuple(_each(data.get("Goals"), _event)), trader=traders[0] if traders else None)


def parse_invasions(data: dict) -> list[Invasion]:
    """Une entrée par camp : deux de même id pour une invasion entre factions (attaquant puis défenseur), une seule contre
    les Infestés (qui ne donnent rien : l'entrée est le défenseur)."""
    camps: dict[str, list[dict]] = {}
    for entry in data.get("invasions") or []:
        if isinstance(entry, dict) and entry.get("id") and entry.get("node") and entry.get("ally"):
            camps.setdefault(entry["id"], []).append(entry)
    invasions = []
    for invasion_id, entries in camps.items():
        try:
            sides = [Camp(faction=entry["ally"], reward=reward({"countedItems": entry.get("allyPay") or []})) for entry in entries]
        except (KeyError, TypeError, ValueError):
            continue
        attacker, defender = (sides[0], sides[1]) if len(sides) >= 2 else (Camp(INFESTED, Reward()), sides[0])
        invasions.append(Invasion(id=invasion_id, node=entries[0]["node"], attacker=attacker, defender=defender))
    return invasions


def parse_bounty_end(data: dict) -> dt.datetime:
    return epoch(data["expiry"], unit=1000)


def parse(source: str, data) -> World | list[Invasion] | dt.datetime:
    """Réponse JSON d'une source -> objets. SourceError si la structure n'est pas celle attendue."""
    if not isinstance(data, dict):
        raise SourceError("réponse inattendue (pas un objet JSON)")
    if source == "worldstate":
        if not isinstance(data.get("ActiveMissions"), list):
            raise SourceError("réponse inattendue (pas de champ ActiveMissions)")
        return parse_world(data)
    if source == "invasions":
        if not isinstance(data.get("invasions"), list):
            raise SourceError("réponse inattendue (pas de liste invasions)")
        return parse_invasions(data)
    try:
        return parse_bounty_end(data)
    except (KeyError, TypeError, ValueError, OverflowError, OSError) as error:
        raise SourceError("réponse inattendue (pas de champ expiry valide)") from error


# --- Requêtes ------------------------------------------------------------------------------------------------------

def parse_retry_after(value: str | None, now: dt.datetime) -> dt.timedelta | None:
    """En-tête Retry-After : un nombre de secondes ou une date HTTP. None si absent, illisible ou déjà passé."""
    if not value:
        return None
    if value.strip().isdigit():
        return dt.timedelta(seconds=int(value))
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.UTC)
    return when - now if when > now else None


async def fetch(session: aiohttp.ClientSession, source: str):
    """Récupère et convertit une source ("worldstate", "invasions", "primes")."""
    try:
        async with session.get(SOURCES[source], headers=HEADERS, timeout=TIMEOUT) as response:
            response.raise_for_status()
            data = await response.json(content_type=None)
    except aiohttp.ClientResponseError as error:
        retry_after = parse_retry_after((error.headers or {}).get("Retry-After"), dt.datetime.now(dt.UTC))
        raise SourceError(f"{type(error).__name__}: {error}", retry_after) from error
    except (aiohttp.ClientError, TimeoutError, ValueError) as error:
        raise SourceError(f"{type(error).__name__}: {error}") from error
    return parse(source, data)
