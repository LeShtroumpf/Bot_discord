import json

import pytest

from cephalon import tools
from cephalon.warframe_api import WarframeApiError


def test_tools_are_strict_and_in_a_fixed_order():
    assert [tool["name"] for tool in tools.TOOLS] == ["get_mod", "get_item", "get_drops"]
    for tool in tools.TOOLS:
        schema = tool["input_schema"]
        assert tool["strict"] is True and tool["description"]
        assert schema["additionalProperties"] is False and schema["required"] == list(schema["properties"]) == ["name"]


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
