from types import SimpleNamespace

import pytest

from cephalon import llm, tools
from cephalon.config import MAX_TOOL_ROUNDS, Config
from cephalon.persona import SYSTEM_PROMPT
from cephalon.warframe_api import WarframeApiError

CONFIG = Config(model="claude-test", max_tokens=1234, effort="medium")


@pytest.mark.asyncio
async def test_direct_answer(claude, fake_api, api_session):
    client = claude.client(claude.reply("end_turn", claude.text("Je ne parle que de Warframe, Tenno.")))
    answer = await llm.ask(client, fake_api, "Quel temps fait-il ?", CONFIG)
    assert (answer.status, answer.text, answer.rounds) == (llm.OK, "Je ne parle que de Warframe, Tenno.", 1)
    assert answer.sources == [] and api_session.calls == []


@pytest.mark.asyncio
async def test_request_uses_the_config_and_a_cached_prefix(claude, fake_api):
    client = claude.client(claude.reply("end_turn", claude.text("Oui.")))
    await llm.ask(client, fake_api, "Que fait Continuité ?", CONFIG)
    request = client.requests[0]
    assert (request["model"], request["max_tokens"], request["output_config"]) == ("claude-test", 1234, {"effort": "medium"})
    assert request["tools"] is tools.TOOLS
    assert request["system"] == [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
    assert request["messages"] == [{"role": "user", "content": "Que fait Continuité ?"}]
    assert not {"thinking", "temperature", "tool_choice"} & set(request)


@pytest.mark.asyncio
async def test_tool_round_then_answer(claude, fake_api):
    first = claude.reply("tool_use", claude.text("Je consulte."), claude.tool("get_mod", "Continuité", "toolu_a"))
    client = claude.client(first, claude.reply("end_turn", claude.text("+30 % de durée de pouvoir.")))
    answer = await llm.ask(client, fake_api, "Que fait Continuité au rang max ?", CONFIG)
    assert (answer.status, answer.text, answer.rounds) == (llm.OK, "+30 % de durée de pouvoir.", 2)
    assert answer.sources[0] == ("Continuity", "https://wiki.warframe.com/w/Continuity")
    question, assistant, results = client.requests[1]["messages"]
    assert assistant == {"role": "assistant", "content": first.content}  # contenu remis tel quel
    assert results["role"] == "user" and len(results["content"]) == 1
    result = results["content"][0]
    assert (result["type"], result["tool_use_id"], result["is_error"]) == ("tool_result", "toolu_a", False)
    assert "+30% Ability Duration" in result["content"]
    assert client.requests[1]["system"] == client.requests[0]["system"]  # préfixe identique : relu en cache


@pytest.mark.asyncio
async def test_two_tools_in_one_round_share_one_message(claude, fake_api):
    first = claude.reply("tool_use", claude.tool("get_mod", "Continuity", "toolu_a"), claude.tool("get_drops", "Continuity", "toolu_b"),
                         claude.tool("get_mod", "Continuity", "toolu_c"))
    client = claude.client(first, claude.reply("end_turn", claude.text("Voilà.")))
    answer = await llm.ask(client, fake_api, "Continuity : effet et drops ?", CONFIG)
    results = client.requests[1]["messages"][2]["content"]
    assert [result["tool_use_id"] for result in results] == ["toolu_a", "toolu_b", "toolu_c"]
    assert [url for _, url in answer.sources] == ["https://wiki.warframe.com/w/Continuity",
                                                  "https://wiki.warframe.com/w/Flawed_Continuity"]  # sans doublon


@pytest.mark.asyncio
async def test_bad_tool_call_goes_back_as_an_error(claude, fake_api):
    first = claude.reply("tool_use", claude.tool("get_lore", "Rhino"))
    client = claude.client(first, claude.reply("end_turn", claude.text("Je ne sais pas.")))
    assert (await llm.ask(client, fake_api, "Qui est Rhino ?", CONFIG)).status == llm.OK
    assert client.requests[1]["messages"][2]["content"][0]["is_error"] is True


@pytest.mark.asyncio
async def test_round_limit(claude, fake_api):
    client = claude.client(*(claude.reply("tool_use", claude.tool("get_mod", "Continuity")) for _ in range(MAX_TOOL_ROUNDS + 2)))
    answer = await llm.ask(client, fake_api, "Continuity ?", CONFIG)
    assert (answer.status, answer.text, answer.rounds) == (llm.ROUNDS, "", MAX_TOOL_ROUNDS)
    assert len(client.requests) == MAX_TOOL_ROUNDS  # pas un appel de plus


@pytest.mark.asyncio
async def test_truncated_answer(claude, fake_api):
    client = claude.client(claude.reply("max_tokens", claude.text("Continuité augmente la durée")))
    answer = await llm.ask(client, fake_api, "Continuité ?", CONFIG)
    assert (answer.status, answer.text) == (llm.OK, "Continuité augmente la durée…")


@pytest.mark.parametrize("stop_reason", ["max_tokens", "end_turn"])
@pytest.mark.asyncio
async def test_empty_answer(claude, fake_api, stop_reason):
    client = claude.client(claude.reply(stop_reason))
    assert (await llm.ask(client, fake_api, "Continuité ?", CONFIG)).status == llm.ROUNDS


@pytest.mark.asyncio
async def test_refusal(claude, fake_api):
    client = claude.client(claude.reply("refusal", claude.text("Non.")))
    answer = await llm.ask(client, fake_api, "…", CONFIG)
    assert (answer.status, answer.text) == (llm.REFUSAL, "")


@pytest.mark.asyncio
async def test_usage_is_summed_over_rounds(claude, fake_api):
    first = claude.reply("tool_use", claude.tool("get_mod", "Continuity"), input_tokens=50, output_tokens=30, cache_write=900)
    second = claude.reply("end_turn", claude.text("Voilà."), input_tokens=400, output_tokens=120, cache_read=900)
    usage = (await llm.ask(claude.client(first, second), fake_api, "Continuity ?", CONFIG)).usage
    assert (usage.input, usage.output, usage.cache_read, usage.cache_write) == (450, 150, 900, 900)


def test_usage_ignores_missing_counters():
    usage = llm.Usage()
    usage.add(type("U", (), {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": None})())
    assert (usage.input, usage.output, usage.cache_read, usage.cache_write) == (10, 5, 0, 0)


@pytest.mark.asyncio
async def test_api_outage_stops_the_question(claude, fake_api, api_routes, failing_response):
    api_routes[("/drops/search/Continuity", None)] = failing_response("timeout")
    first = claude.reply("tool_use", claude.tool("get_mod", "Continuity", "toolu_a"), claude.tool("get_drops", "Continuity", "toolu_b"))
    client = claude.client(first, claude.reply("end_turn", claude.text("Jamais atteint.")))
    with pytest.raises(WarframeApiError):
        await llm.ask(client, fake_api, "Continuity ?", CONFIG)
    assert len(client.requests) == 1  # aucun appel à Claude après la panne


@pytest.mark.asyncio
async def test_given_usage_is_filled_even_when_an_outage_stops_the_loop(claude, fake_api, api_routes, failing_response):
    api_routes[("/drops/search/Continuity", None)] = failing_response("timeout")
    first = claude.reply("tool_use", claude.tool("get_mod", "Continuity", "toolu_a"), input_tokens=300, output_tokens=40)
    second = claude.reply("tool_use", claude.tool("get_drops", "Continuity", "toolu_b"), input_tokens=700, output_tokens=60)
    usage = llm.Usage()
    with pytest.raises(WarframeApiError):
        await llm.ask(claude.client(first, second), fake_api, "Continuity ?", CONFIG, usage)
    assert (usage.input, usage.output) == (1000, 100)  # les deux tours déjà facturés


@pytest.mark.asyncio
async def test_given_usage_is_the_answer_usage(claude, fake_api):
    usage = llm.Usage()
    answer = await llm.ask(claude.client(claude.reply("end_turn", claude.text("Oui."))), fake_api, "?", CONFIG, usage)
    assert answer.usage is usage and usage.input == 100


@pytest.mark.asyncio
async def test_search_sources_can_be_left_out(claude, fake_api, index):
    fake_api.index = index
    search = SimpleNamespace(type="tool_use", id="toolu_1", name="search_mods",
                             input={"keywords": ["Ability Duration"], "type": None})
    for cite, expected in ((True, True), (False, False)):
        client = claude.client(claude.reply("tool_use", search), claude.reply("end_turn", claude.text("Ok.")))
        profile = llm.Profile(llm.SYSTEM, tools.TOOLS, "claude-haiku-5-5", 1000, "low", search_sources=cite)
        answer = await llm.ask(client, fake_api, "Quel mod ?", Config(), profile=profile)
        assert bool(answer.sources) is expected
