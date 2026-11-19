import copy
import datetime as dt
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from warframe import browsewf
from warframe.browsewf import INFESTED, SOURCES, Reward, SourceError, epoch, fetch, mongo_date, parse, parse_retry_after

NOW = dt.datetime(2026, 11, 4, 12, 0, tzinfo=dt.UTC)


def date(ms: int) -> dict:
    return {"$date": {"$numberLong": str(ms)}}


# --- Dates ---------------------------------------------------------------------------------------------------

def test_dates_of_the_three_formats():
    when = dt.datetime(2026, 11, 15, 14, 0, tzinfo=dt.UTC)
    ms = int(when.timestamp() * 1000)
    assert mongo_date(date(ms)) == when                     # worldState.min.json : ms dans $date.$numberLong
    assert epoch(ms // 1000) == when                        # invasions : secondes
    assert epoch(ms, unit=1000) == when                     # bounty-cycle : millisecondes
    with pytest.raises(TypeError):
        epoch("1794755289285", unit=1000)


@pytest.mark.parametrize("value, expected", [
    ("120", dt.timedelta(minutes=2)),
    ("Wed, 04 Nov 2026 12:05:00 GMT", dt.timedelta(minutes=5)),
    ("Wed, 04 Nov 2026 11:55:00 GMT", None),  # déjà passé
    ("bientôt", None),
    ("", None),
    (None, None),
])
def test_parse_retry_after(value, expected):
    assert parse_retry_after(value, NOW) == expected


# --- Worldstate réel -------------------------------------------------------------------------------------------

def test_world_real_data(sources, now):
    world = sources["worldstate"]
    normal = [f for f in world.fissures if not f.storm and not f.hard]
    hard = [f for f in world.fissures if f.hard]
    storms = [f for f in world.fissures if f.storm]
    assert (len(normal), len(hard), len(storms)) == (11, 11, 12)
    assert all(f.expiry > now for f in world.fissures)
    assert {f.era for f in world.fissures} == {"VoidT1", "VoidT2", "VoidT3", "VoidT4", "VoidT5", "VoidT6"}
    assert all(f.mission is None for f in storms) and all(f.mission.startswith("MT_") for f in normal + hard)
    assert all(f.node.startswith("CrewBattleNode") for f in storms)


def test_alerts_real_data(sources):
    alerts = sources["worldstate"].alerts
    gift = next(a for a in alerts if a.tag == "LotusGift")
    assert (gift.node, gift.mission, gift.faction, gift.min_level, gift.max_level) == (
        "SolNode122", "MT_DEFENSE", "FC_GRINEER", 20, 30)
    assert gift.reward == Reward(counted=(("/Lotus/Types/Items/MiscItems/Forma", 3),), credits=10000)
    assert sum(a.tag == "RoadToTauEvent" for a in alerts) == 3


def test_events_real_data(sources):
    events = {e.tag: e for e in sources["worldstate"].events}
    thermia = events["HeatFissure"]
    assert thermia.name == "/Lotus/Language/G1Quests/HeatFissuresEventName"
    assert (thermia.node, thermia.goal, thermia.personal) == ("SolNode129", 100, True)
    assert thermia.reward.items == ("/Lotus/StoreItems/Weapons/Corpus/LongGuns/CrpBFG/Vandal/VandalCrpBFG",)
    tau = events["RoadToTauEvent"]
    assert (tau.node, tau.goal, tau.personal) == (None, 0, False)


def test_trader_real_data(sources):
    trader = sources["worldstate"].trader
    assert trader.node == "EarthHUB" and trader.manifest == ()   # prochaine visite annoncée, inventaire pas encore connu
    assert trader.activation < trader.expiry


def test_invasions_real_data(sources):
    invasions = sources["invasions"]
    assert len(invasions) == 6 and len({i.id for i in invasions}) == 6
    between = [i for i in invasions if not i.vs_infested]
    infested = [i for i in invasions if i.vs_infested]
    assert len(between) == len(infested) == 3
    assert all({i.attacker.faction, i.defender.faction} == {"FC_CORPUS", "FC_GRINEER"} for i in between)
    assert all(i.attacker.reward == Reward() and i.defender.faction != INFESTED for i in infested)
    assert all(i.defender.reward.counted for i in invasions)


def test_bounty_end_real_data(sources):
    assert sources["primes"] == dt.datetime(2026, 11, 15, 15, 8, 9, 285000, tzinfo=dt.UTC)


# --- Invasions --------------------------------------------------------------------------------------------------

def camp(invasion_id, ally, item="/Lotus/Types/Items/Research/EnergyComponent", node="SolNode1"):
    return {"id": invasion_id, "node": node, "ally": ally, "allyPay": [{"ItemType": item, "ItemCount": 3}], "missions": []}


def test_invasion_between_factions_first_entry_attacks():
    [invasion] = browsewf.parse_invasions({"invasions": [camp("a", "FC_GRINEER"), camp("a", "FC_CORPUS")]})
    assert (invasion.attacker.faction, invasion.defender.faction) == ("FC_GRINEER", "FC_CORPUS")
    assert not invasion.vs_infested


def test_invasion_against_infested_has_a_single_entry():
    [invasion] = browsewf.parse_invasions({"invasions": [camp("b", "FC_CORPUS")]})
    assert invasion.attacker == browsewf.Camp(INFESTED, Reward())
    assert invasion.defender.faction == "FC_CORPUS" and invasion.vs_infested


def test_invasion_unreadable_entries_are_skipped():
    entries = [camp("a", "FC_GRINEER"), {"id": "c"}, "pas un dict", {"id": "d", "node": "SolNode2", "ally": "FC_CORPUS",
                                                                     "allyPay": [{"ItemCount": 3}]}]
    assert [i.id for i in browsewf.parse_invasions({"invasions": entries})] == ["a"]


# --- Entrées illisibles ------------------------------------------------------------------------------------------

def test_unreadable_entries_are_ignored(raw_sources):
    data = copy.deepcopy(raw_sources["worldstate"])
    data["ActiveMissions"][0].pop("Node")
    data["ActiveMissions"][1]["Expiry"] = "demain"
    data["Alerts"].append({"Tag": "Cassée"})
    data["Goals"].append(None)
    world = parse("worldstate", data)
    assert len([f for f in world.fissures if not f.storm]) == len(raw_sources["worldstate"]["ActiveMissions"]) - 2
    assert len(world.alerts) == len(raw_sources["worldstate"]["Alerts"])
    assert len(world.events) == len(raw_sources["worldstate"]["Goals"])


def test_world_without_optional_lists():
    world = parse("worldstate", {"ActiveMissions": []})
    assert world == browsewf.World()


@pytest.mark.parametrize("source, data, message", [
    ("worldstate", {"Time": 1}, "ActiveMissions"),
    ("worldstate", ["pas un objet"], "objet JSON"),
    ("invasions", {"activation": 1}, "invasions"),
    ("primes", {"rot": "A"}, "expiry"),
    ("primes", {"expiry": "bientôt"}, "expiry"),
])
def test_unexpected_structure(source, data, message):
    with pytest.raises(SourceError, match=message):
        parse(source, data)


# --- Requêtes ----------------------------------------------------------------------------------------------------

def session_answering(response) -> MagicMock:
    session = MagicMock()
    session.get.return_value.__aenter__ = AsyncMock(return_value=response)
    session.get.return_value.__aexit__ = AsyncMock(return_value=False)
    return session


@pytest.mark.asyncio
async def test_fetch_each_source(raw_sources, sources):
    for name, data in raw_sources.items():
        response = MagicMock()
        response.json = AsyncMock(return_value=data)
        session = session_answering(response)
        assert await fetch(session, name) == sources[name]
        assert session.get.call_args.args == (SOURCES[name],)
    assert all(url.startswith("https://oracle.browse.wf/") for url in SOURCES.values())


@pytest.mark.asyncio
async def test_fetch_not_found_is_reported():
    response = MagicMock()
    response.raise_for_status.side_effect = aiohttp.ClientResponseError(MagicMock(), (), status=404, message="Not Found")
    with pytest.raises(SourceError, match="404"):
        await fetch(session_answering(response), "worldstate")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure, text", [
    (TimeoutError(), "pas de réponse en 10 s"),
    (aiohttp.ServerTimeoutError("Timeout on reading data from socket"), "pas de réponse en 10 s"),
    (aiohttp.ClientConnectionError("down"), "ClientConnectionError: down"),
    (aiohttp.ClientConnectionError(), "ClientConnectionError"),
])
async def test_fetch_error_text_is_readable(failure, text):
    session = MagicMock()
    session.get.side_effect = failure
    with pytest.raises(SourceError) as error:
        await fetch(session, "worldstate")
    assert str(error.value) == text


@pytest.mark.asyncio
async def test_fetch_http_error_text():
    response = MagicMock()
    response.raise_for_status.side_effect = aiohttp.ClientResponseError(MagicMock(), (), status=503, message="Unavailable")
    with pytest.raises(SourceError) as error:
        await fetch(session_answering(response), "primes")
    assert str(error.value) == "HTTP 503"


@pytest.mark.asyncio
async def test_fetch_rate_limited_exposes_retry_after():
    response = MagicMock()
    response.raise_for_status.side_effect = aiohttp.ClientResponseError(
        MagicMock(), (), status=429, message="Too Many Requests", headers={"Retry-After": "300"})
    with pytest.raises(SourceError) as error:
        await fetch(session_answering(response), "invasions")
    assert error.value.retry_after == dt.timedelta(minutes=5)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [aiohttp.ClientConnectionError("down"), TimeoutError()])
async def test_fetch_network_error_has_no_retry_after(failure):
    session = MagicMock()
    session.get.side_effect = failure
    with pytest.raises(SourceError) as error:
        await fetch(session, "primes")
    assert error.value.retry_after is None


@pytest.mark.asyncio
async def test_fetch_invalid_json():
    response = MagicMock()
    response.json = AsyncMock(side_effect=ValueError("pas du JSON"))
    with pytest.raises(SourceError, match="JSON"):
        await fetch(session_answering(response), "worldstate")
