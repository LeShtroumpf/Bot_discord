import json

import pytest

from cephalon import tools
from cephalon.warframe_api import WarframeApiError


def test_tools_are_strict_and_in_a_fixed_order():
    assert [tool["name"] for tool in tools.TOOLS] == ["get_mod", "get_item", "get_drops", "search_mods", "rank_weapons",
                                                      "rank_warframes"]
    for tool in tools.TOOLS:
        schema = tool["input_schema"]
        assert tool["strict"] is True and tool["description"]
        assert schema["additionalProperties"] is False and schema["required"] == list(schema["properties"])


def test_optional_parameters_accept_null():
    """Schéma strict : tout paramètre est obligatoire, un paramètre facultatif accepte `null`."""
    properties = {tool["name"]: tool["input_schema"]["properties"] for tool in tools.TOOLS}
    null = {"type": "null"}
    assert properties["search_mods"]["type"]["anyOf"] == [{"type": "string"}, null]
    categories = ["Primary", "Secondary", "Melee", "Arch-Gun", "Arch-Melee"]
    assert properties["rank_weapons"]["category"]["anyOf"] == [{"type": "string", "enum": categories}, null]
    assert properties["rank_weapons"]["max_mastery"]["anyOf"] == [{"type": "integer"}, null]
    assert properties["rank_weapons"]["stat"]["enum"][0] == "criticalChance"  # obligatoire : pas de null
    assert properties["rank_warframes"]["kind"]["anyOf"] == [{"type": "string", "enum": ["Warframe", "Archwing", "Necramech"]}, null]
    for name in ("search_mods", "rank_weapons", "rank_warframes"):
        assert all(schema.get("description") for schema in properties[name].values())


@pytest.mark.asyncio
async def test_get_mod(fake_api):
    outcome = await tools.execute(fake_api, "get_mod", {"name": "Continuité"})
    results = json.loads(outcome.content)["results"]
    assert results[0]["name_fr"] == "Continuité" and results[0]["levelStats"][-1] == "rank 5: +30% Ability Duration"
    assert outcome.is_error is False and outcome.sources[0][1] == "https://wiki.warframe.com/w/Continuity"
    assert "é" in outcome.content and ", " not in outcome.content.split('"levelStats"')[0]  # JSON compact, accents lisibles


@pytest.mark.asyncio
async def test_get_item(fake_api):
    outcome = await tools.execute(fake_api, "get_item", {"name": "Rhino Prime"})
    assert json.loads(outcome.content)["results"][0]["shield"] == 455
    assert outcome.sources == [("Rhino Prime", "https://wiki.warframe.com/w/Rhino%2FPrime")]


@pytest.mark.asyncio
async def test_not_found_lists_similar_names(fake_api):
    outcome = await tools.execute(fake_api, "get_mod", {"name": "Contin"})
    data = json.loads(outcome.content)
    assert data["results"] == [] and "Continuité" in data["similar_names"]
    assert outcome.is_error is False and outcome.sources == []


@pytest.mark.asyncio
async def test_get_drops(fake_api):
    outcome = await tools.execute(fake_api, "get_drops", {"name": "Continuity"})
    data = json.loads(outcome.content)
    assert data["total"] == 40 and data["drops"][0]["chance"] == 7.69
    assert outcome.sources == []


@pytest.mark.parametrize("name, arguments", [
    ("get_mod", {}), ("get_mod", {"name": "  "}), ("get_mod", {"name": 3}), ("get_mod", None), ("get_lore", {"name": "Rhino"}),
])
@pytest.mark.asyncio
async def test_bad_call_is_an_error_result(fake_api, api_session, name, arguments):
    outcome = await tools.execute(fake_api, name, arguments)
    assert outcome.is_error is True and outcome.content.startswith("Erreur")
    assert api_session.calls == []


@pytest.mark.asyncio
async def test_api_outage_is_raised(fake_api, api_routes, failing_response):
    api_routes[("/mods/search/Continuity", None)] = failing_response("status")
    with pytest.raises(WarframeApiError):
        await tools.execute(fake_api, "get_mod", {"name": "Continuity"})


# --- Recherches de l'index ----------------------------------------------------------------------------------

@pytest.fixture
def indexed_api(fake_api, index):
    fake_api.index = index
    return fake_api


@pytest.mark.asyncio
async def test_search_mods(indexed_api, api_session):
    outcome = await tools.execute(indexed_api, "search_mods", {"keywords": ["Ability Duration"], "type": None})
    data = json.loads(outcome.content)
    assert data["total"] == len(data["results"]) and "Continuité Accrue" in [row["name_fr"] for row in data["results"]]
    assert outcome.is_error is False and outcome.sources and api_session.calls == []  # aucun appel réseau


@pytest.mark.asyncio
async def test_search_mods_with_a_type(indexed_api):
    outcome = await tools.execute(indexed_api, "search_mods", {"keywords": ["Damage"], "type": "Rifle"})
    assert "Serration" in [row["name"] for row in json.loads(outcome.content)["results"]]


@pytest.mark.asyncio
async def test_rank_weapons(indexed_api):
    outcome = await tools.execute(indexed_api, "rank_weapons", {"stat": "criticalChance", "order": "desc", "category": "Primary",
                                                                "type": "bow", "max_mastery": 8})
    data = json.loads(outcome.content)
    assert [row["name"] for row in data["results"]] == ["Dread", "Lenz", "Paris Prime"] and data["total"] == 3
    slowest = await tools.execute(indexed_api, "rank_weapons", {"stat": "masteryReq", "order": "asc", "category": None, "type": None,
                                                                "max_mastery": None})
    assert json.loads(slowest.content)["results"][0]["masteryReq"] == 0


@pytest.mark.asyncio
async def test_rank_warframes(indexed_api):
    outcome = await tools.execute(indexed_api, "rank_warframes", {"stat": "armor", "order": "desc", "kind": None})
    data = json.loads(outcome.content)
    assert data["results"][0] == {"name": "Valkyr Prime", "armor": 1000} and data["total"] == 10
    assert outcome.sources[0] == ("Valkyr Prime", "https://wiki.warframe.com/w/Valkyr%2FPrime")
    necramechs = await tools.execute(indexed_api, "rank_warframes", {"stat": "armor", "order": "asc", "kind": "Necramech"})
    assert [row["name"] for row in json.loads(necramechs.content)["results"]] == ["Voidrig", "Bonewidow"]


@pytest.mark.parametrize("name", ["search_mods", "rank_weapons", "rank_warframes"])
@pytest.mark.asyncio
async def test_search_without_an_index_is_an_error(fake_api, name):
    outcome = await tools.execute(fake_api, name, {"keywords": ["Health"], "stat": "armor", "order": "desc"})
    assert outcome.is_error is True and "pas encore prêt" in outcome.content


@pytest.mark.parametrize("name, arguments", [
    ("search_mods", {"keywords": [], "type": None}), ("search_mods", {"keywords": "Health", "type": None}),
    ("search_mods", {"keywords": ["Health", 3], "type": None}), ("search_mods", {"keywords": ["Health"], "type": 5}),
    ("search_mods", {"keywords": ["Health"], "type": " "}),
    ("rank_weapons", {"stat": "beauté", "order": "desc"}), ("rank_weapons", {"stat": "criticalChance", "order": "up"}),
    ("rank_weapons", {"stat": "criticalChance", "order": "desc", "category": "Gros calibre"}),
    ("rank_weapons", {"stat": "criticalChance", "order": "desc", "max_mastery": "8"}),
    ("rank_weapons", {"stat": "criticalChance", "order": "desc", "max_mastery": -1}),
    ("rank_weapons", {"stat": "criticalChance", "order": "desc", "max_mastery": True}),
    ("rank_warframes", {"stat": "criticalChance", "order": "desc"}),
    ("rank_warframes", {"stat": "armor", "order": "desc", "kind": "Robot"}), ("rank_warframes", None),
])
@pytest.mark.asyncio
async def test_bad_search_call_is_an_error_result(indexed_api, name, arguments):
    outcome = await tools.execute(indexed_api, name, arguments)
    assert outcome.is_error is True and outcome.content.startswith("Erreur : ")
