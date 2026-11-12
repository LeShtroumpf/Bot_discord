import json
from types import SimpleNamespace

import pytest

from cephalon import build
from cephalon.build import READER_SCHEMA, BuildError
from cephalon.config import Config
from cephalon.image import PreparedImage
from cephalon.llm import Usage

IMAGE = PreparedImage(media_type="image/png", data="aGVsbG8=", original=(2484, 891), size=(2484, 891), bytes=5)


def slot(name, kind="mod", rank=5, **extra):
    return {"slot": "normal", "kind": kind, "name": name, "readable": True, "drain": 9, "rank": rank, "max_rank": 5,
            "polarity": "madurai", **extra}


def reading(*slots, is_build=True):
    return {"is_build": is_build, "equipment_kind": "warframe", "equipment_name": "Rhino Prime",
            "capacity": {"remaining": 7, "total": 74},
            "displayed_stats": [{"name": "Duration", "value": "155%"}], "slots": list(slots)}


def reader_reply(claude, data, stop_reason="end_turn"):
    text = data if isinstance(data, str) else json.dumps(data)
    return claude.reply(stop_reason, SimpleNamespace(type="thinking", thinking=""), claude.text(text),
                        input_tokens=3000, output_tokens=500)


# --- Lecture ------------------------------------------------------------------------------------------------

def test_reader_schema_is_strict():
    def walk(schema):
        if schema.get("type") == "object":
            assert schema["additionalProperties"] is False and schema["required"] == list(schema["properties"])
            for child in schema["properties"].values():
                walk(child)
        for option in schema.get("anyOf", []):
            walk(option)
        if schema.get("type") == "array":
            walk(schema["items"])
    walk(READER_SCHEMA)
    assert READER_SCHEMA["properties"]["slots"]["items"]["properties"]["rank"] == {"anyOf": [{"type": "integer"},
                                                                                             {"type": "null"}]}


@pytest.mark.asyncio
async def test_read_build_request(claude):
    client = claude.client(reader_reply(claude, reading(slot("Continuity"))))
    usage = Usage()
    result = await build.read_build(client, IMAGE, Config(build_reader_model="claude-haiku-5-5"), usage)
    assert result["slots"][0]["name"] == "Continuity" and (usage.input, usage.output) == (3000, 500)
    request = client.requests[0]
    assert request["model"] == "claude-haiku-5-5" and "tools" not in request
    content = request["messages"][0]["content"]
    assert content[0] == IMAGE.block() and content[1]["type"] == "text"  # l'image avant le texte
    assert request["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": READER_SCHEMA}}


@pytest.mark.asyncio
@pytest.mark.parametrize("data, stop_reason, message", [
    ("{pas du json", "end_turn", "illisible"),
    ({"is_build": "oui", "slots": []}, "end_turn", "forme inattendue"),
    ({"is_build": True, "slots": [slot("x")] * 21}, "end_turn", "forme inattendue"),
    (reading(), "refusal", "interrompue"),
    (reading(), "max_tokens", "interrompue"),
])
async def test_unusable_reading(claude, data, stop_reason, message):
    usage = Usage()
    with pytest.raises(BuildError, match=message):
        await build.read_build(claude.client(reader_reply(claude, data, stop_reason)), IMAGE, Config(), usage)
    assert usage.input == 3000  # la lecture est facturée même inexploitable


def test_is_build():
    assert build.is_build(reading(slot("Continuity")))
    assert not build.is_build(reading(slot("Continuity"), is_build=False))
    assert not build.is_build(reading(slot(None)))  # aucune carte lue


# --- Vérification -------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_each_card(fake_api):
    checked = await build.verify(fake_api, reading(
        slot("Continuité"), slot("Continuty"), slot(None), slot("Vexi-Satilis", kind="riven"),
        slot("Crimson Archon Shard", kind="archon_shard"), slot("Contin")))
    statuses = [item.status for item in checked]
    assert statuses == ["verified", "unknown", "unknown", "riven", "not_checked", "uncertain"]
    assert "Continuité" in checked[5].candidates  # nom partiel : candidats, jamais complété
    assert checked[0].card["name_fr"] == "Continuité" and checked[0].card["levelStats"][-1] == "rank 5: +30% Ability Duration"
    assert build.sources(checked) == [("Continuity", "https://wiki.warframe.com/w/Continuity")]


@pytest.mark.asyncio
async def test_uncertain_card_lists_candidates(fake_api, monkeypatch):
    from cephalon.warframe_api import Lookup

    async def find(kind, name):
        assert kind == "items"  # un arcane se cherche parmi les objets
        return Lookup(suggestions=["Arcane Energize", "Arcane Grace"])
    monkeypatch.setattr(fake_api, "find", find)
    checked = await build.verify(fake_api, reading(slot("Arcane Enrgize", kind="arcane")))
    assert checked[0].status == "uncertain" and checked[0].candidates == ["Arcane Energize", "Arcane Grace"]


@pytest.mark.asyncio
async def test_warframestat_outage_stops_the_build(fake_api, api_routes, failing_response):
    from cephalon.warframe_api import WarframeApiError
    api_routes[("/mods/search/Continuity", None)] = failing_response("status")
    with pytest.raises(WarframeApiError):
        await build.verify(fake_api, reading(slot("Continuity")))


# --- Analyse ------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_payload(fake_api):
    data = reading(slot("Continuité"), slot("Vexi-Satilis", kind="riven"))
    checked = await build.verify(fake_api, data)
    sent = json.loads(build.payload(data, checked, "build pour l'Acier ?"))
    assert sent["equipment"] == {"kind": "warframe", "name": "Rhino Prime"} and sent["question"] == "build pour l'Acier ?"
    assert sent["capacity"] == {"remaining": 7, "total": 74} and sent["displayed_stats"][0]["value"] == "155%"
    assert sent["slots"][0]["status"] == "verified" and sent["slots"][0]["card"]["name"] == "Continuity"
    assert sent["slots"][0]["rank"] == 5 and sent["slots"][0]["drain"] == 9
    assert sent["slots"][1] == {"slot": "normal", "read_name": "Vexi-Satilis", "readable": True, "rank": 5,
                                "max_rank": 5, "drain": 9, "polarity": "madurai", "status": "riven"}


def test_profile():
    profile = build.profile(Config(build_model="claude-opus-5-5", build_max_tokens=7000, build_effort="high"))
    assert (profile.model, profile.max_tokens, profile.effort) == ("claude-opus-5-5", 7000, "high")
    assert [tool["name"] for tool in profile.tools] == ["get_mod", "get_item", "search_mods"]
    assert profile.system[0]["cache_control"] == {"type": "ephemeral"} and "Mods lus" in profile.system[0]["text"]


@pytest.mark.asyncio
async def test_impossible_drain_is_dropped(claude):
    data = reading(slot("Vacuum", drain=41), slot("Regen", drain=4), slot("Investigator", drain=-1), slot("x", drain=True))
    result = await build.read_build(claude.client(reader_reply(claude, data)), IMAGE, Config(), Usage())
    assert [item["drain"] for item in result["slots"]] == [None, 4, None, None]  # symbole Precept lu comme un 1


def test_build_profile_does_not_cite_search_results():
    assert build.profile(Config()).search_sources is False


# --- Rang déduit du coût affiché ----------------------------------------------------------------------------

def checked_card(base, top, drain, rank, slot_name="normal"):
    item = build.Checked({"slot": slot_name, "drain": drain, "rank": rank}, "verified",
                         card={"baseDrain": base, "fusionLimit": top})
    build.settle_rank(item)
    return item.rank, item.rank_from_drain


@pytest.mark.parametrize("base, top, drain, rank, slot_name, expected", [
    (4, 10, 7, 10, "normal", (10, False)),     # Continuité Accrue : 4 + 10 = 14, polarité identique → 7 : rang lu gardé
    (6, 10, 8, 5, "normal", (10, True)),       # Intensité Archonte : 8 est impossible au rang 5 → rang 10
    (6, 10, 8, None, "normal", (10, True)),    # rang illisible → déduit du coût
    (6, 5, 6, 5, "normal", (5, False)),        # Super-Étendu : 11 / 2 arrondi au-dessus
    (4, 5, 9, 3, "exilus", (5, True)),         # Art de la Puissance : rang 5 sans polarité ou 3 polarité opposée → max
    (4, 10, 9, 3, "normal", (3, False)),       # max exclu par le coût (rangs 3 ou 5 possibles) : rang lu gardé
    (4, 10, 9, 8, "normal", (5, True)),        # max exclu, rang lu incompatible : plus haut rang compatible
    (-2, 5, 14, 5, "aura", (5, False)),        # aura : (2 + 5) × 2
    (4, 5, None, 2, "normal", (2, False)),     # coût illisible : rang lu
    (4, 5, 30, 2, "normal", (2, False)),       # aucun rang compatible : rang lu
])
def test_rank_from_drain(base, top, drain, rank, slot_name, expected):
    assert checked_card(base, top, drain, rank, slot_name) == expected


@pytest.mark.asyncio
async def test_payload_marks_a_rank_taken_from_the_drain(fake_api):
    data = reading(slot("Continuité", rank=1, drain=9))  # Continuity : 2 + 5 = 7, majoré d'un quart → 9 au rang 5
    checked = await build.verify(fake_api, data)
    sent = json.loads(build.payload(data, checked, None))["slots"][0]
    assert sent["rank"] == 5 and sent["rank_from_drain"] is True
