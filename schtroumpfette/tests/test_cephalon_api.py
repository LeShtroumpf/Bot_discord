import pytest

from cephalon.config import API_CACHE_SIZE, API_CACHE_TTL
from cephalon.index import LISTS
from cephalon.warframe_api import MAX_DROPS, REQUESTED, WarframeApi, WarframeApiError, simplify, source


# --- Résolution d'un nom ------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_english_name_returns_the_real_mod_before_the_flawed_one(fake_api):
    lookup = await fake_api.find("mods", "Continuity")
    normal, flawed = lookup.found
    assert normal["levelStats"][-1] == "rank 5: +30% Ability Duration" and "flawed" not in normal
    assert flawed["levelStats"][-1] == "rank 3: +12% Ability Duration" and flawed["flawed"] is True
    assert lookup.sources == [("Continuity", "https://wiki.warframe.com/w/Continuity"),
                              ("Continuity (Défectueux)", "https://wiki.warframe.com/w/Flawed_Continuity")]


@pytest.mark.asyncio
async def test_name_is_matched_without_case(fake_api, api_routes):
    api_routes[("/mods/search/continuity", None)] = api_routes[("/mods/search/Continuity", None)]
    assert len((await fake_api.find("mods", " continuity ")).found) == 2


@pytest.mark.asyncio
async def test_french_name_gives_the_english_name_too(fake_api, api_session):
    lookup = await fake_api.find("mods", "Continuité")
    assert [(m["name"], m["name_fr"]) for m in lookup.found] == [("Continuity", "Continuité")] * 2
    assert lookup.found[0]["levelStats"][-1] == "rank 5: +30% Ability Duration"
    assert lookup.sources[0] == ("Continuity", "https://wiki.warframe.com/w/Continuity")
    languages = [params.get("language") for path, params in api_session.calls if "/search/" in path]
    assert languages == [None, "fr"]  # anglais d'abord, français ensuite


@pytest.mark.asyncio
async def test_french_name_is_kept_when_the_english_one_is_not_confirmed(fake_api, api_routes):
    """La recherche par identifiant est approchée : une fiche d'un autre objet est ignorée."""
    for key in [key for key in api_routes if key[0].startswith("/mods/%2F")]:
        api_routes[key] = {"name": "Autre", "uniqueName": "/Lotus/Autre"}
    fiche = (await fake_api.find("mods", "Continuité")).found[0]
    assert fiche["name"] == "Continuité" and "name_fr" not in fiche


@pytest.mark.asyncio
async def test_english_name_gets_the_french_name_and_texts(fake_api):
    mod = (await fake_api.find("mods", "Continuity")).found[0]
    assert (mod["name"], mod["name_fr"]) == ("Continuity", "Continuité")
    frame = (await fake_api.find("items", "Rhino Prime")).found[0]
    assert "name_fr" not in frame  # même nom dans les deux langues
    assert frame["description"].startswith("Propulsez les anciens Pouvoirs")
    assert frame["passiveDescription"].startswith("Émet une onde de choc")
    assert frame["abilities"][1] == {"name": "Iron Skin", "description": "Rhino renforce sa peau afin de s'isoler de tout dégât "
                                                                         "et de gagner Garde Renforcée."}
    assert frame["health"] == 270  # les chiffres restent ceux de la fiche d'origine


@pytest.mark.asyncio
async def test_english_texts_are_kept_without_a_french_fiche(fake_api):
    weapon = (await fake_api.find("items", "Braton Prime")).found[0]
    assert weapon["description"].startswith("A classic Orokin weapon") and "name_fr" not in weapon


@pytest.mark.asyncio
async def test_unknown_name_suggests_close_names(fake_api):
    lookup = await fake_api.find("mods", "Contin")
    assert lookup.found == [] and lookup.sources == []
    assert lookup.suggestions[:2] == ["Continuité Archonte", "Continuité"]
    assert "Primed Continuity" in lookup.suggestions
    assert len(lookup.suggestions) == len(set(lookup.suggestions)) <= 10


@pytest.mark.asyncio
async def test_unknown_name_without_suggestion(fake_api):
    lookup = await fake_api.find("mods", "Continuty")
    assert (lookup.found, lookup.suggestions) == ([], [])


@pytest.mark.asyncio
async def test_unknown_kind(fake_api):
    with pytest.raises(ValueError):
        await fake_api.find("drops", "Continuity")


@pytest.mark.asyncio
async def test_search_only_asks_for_the_used_fields(fake_api, api_session):
    await fake_api.find("mods", "Continuity")
    assert api_session.calls[0] == ("/mods/search/Continuity", {"only": REQUESTED})
    texts = {"by": "uniqueName", "only": "uniqueName,name,description,passiveDescription,abilities", "language": "fr"}
    assert [params for _, params in api_session.calls[1:]] == [texts, texts]  # une fiche française par mod trouvé


# --- Filtrage -----------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_frame_keeps_stats_and_drops_the_rest(fake_api):
    frame = (await fake_api.find("items", "Rhino Prime")).found[0]
    assert (frame["health"], frame["shield"], frame["armor"]) == (270, 455, 290)
    assert [ability["name"] for ability in frame["abilities"]][:2] == ["Rhino Charge", "Iron Skin"]
    assert {"name": "Orokin Cell", "count": 3} in frame["components"]
    assert all(set(component) == {"name", "count"} for component in frame["components"])
    assert not {"uniqueName", "imageName", "wikiaUrl", "drops"} & set(frame)


@pytest.mark.asyncio
async def test_weapon_keeps_only_nonzero_damage(fake_api):
    weapon = (await fake_api.find("items", "Braton Prime")).found[0]
    assert weapon["damage"] == {"total": 35, "impact": 1.75, "puncture": 12.25, "slash": 21}
    assert weapon["criticalChance"] == 0.12 and weapon["magazineSize"] == 75
    assert weapon["attacks"][0]["name"] == "Normal Attack" and weapon["attacks"][0]["damage"]["slash"] == 21


def test_simplify_removes_game_markup_and_empty_values():
    stats = ["+5% Ability Duration", "<DT_POISON_COLOR>Toxin also applies <DT_CORROSIVE_COLOR>Corrosive."]
    mod = simplify({"name": "Archon Continuity", "description": "", "polarities": [], "levelStats": [{"stats": stats}]})
    assert mod == {"name": "Archon Continuity", "levelStats": ["rank 0: +5% Ability Duration / Toxin also applies Corrosive."]}


@pytest.mark.parametrize("url", ["https://warframe.fandom.com/wiki/Continuity", "", None])
def test_source_must_be_the_official_wiki(url):
    assert source({"name": "Continuity", "wikiaUrl": url}) is None


# --- Drops --------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_drops_are_sorted_and_limited(fake_api):
    result = await fake_api.drops("Continuity")
    assert result["total"] == 40 and len(result["drops"]) == MAX_DROPS
    chances = [drop["chance"] for drop in result["drops"]]
    assert chances == sorted(chances, reverse=True)
    assert all(drop["item"] == "Continuity" for drop in result["drops"])  # l'objet exact avant « Necramech Continuity »
    assert set(result["drops"][0]) == {"item", "place", "rarity", "chance"}


@pytest.mark.asyncio
async def test_drops_of_an_unknown_item(fake_api):
    assert await fake_api.drops("Rien") == {"total": 0, "drops": []}


# --- Cache et pannes ----------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cache_expires(api_session):
    now = [1000.0]
    api = WarframeApi(api_session, clock=lambda: now[0])
    await api.drops("Continuity")
    await api.drops("Continuity")
    assert len(api_session.calls) == 1
    now[0] += API_CACHE_TTL + 1
    await api.drops("Continuity")
    assert len(api_session.calls) == 2


@pytest.mark.asyncio
async def test_cache_is_bounded(fake_api):
    for index in range(API_CACHE_SIZE + 5):
        await fake_api.fetch(f"/drops/search/{index}", list)
    assert len(fake_api.cache) == API_CACHE_SIZE
    assert ("/drops/search/0", ()) not in fake_api.cache  # les plus anciennes sont sorties


@pytest.mark.asyncio
async def test_not_found_is_none(fake_api):
    assert await fake_api.fetch("/mods/inconnu", dict) is None


@pytest.mark.parametrize("failure", ["status", "timeout", "network", "json", "shape"])
@pytest.mark.asyncio
async def test_outage_raises_and_is_not_cached(fake_api, api_session, api_routes, failure, request):
    response = request.getfixturevalue("failing_response")(failure)
    api_routes[("/drops/search/Continuity", None)] = response
    with pytest.raises(WarframeApiError):
        await fake_api.drops("Continuity")
    api_routes[("/drops/search/Continuity", None)] = []
    assert await fake_api.drops("Continuity") == {"total": 0, "drops": []}
    assert len(api_session.calls) == 2


@pytest.mark.asyncio
async def test_search_with_an_unexpected_answer(fake_api, api_routes):
    api_routes[("/mods/search/Continuity", None)] = {"error": "oups"}
    with pytest.raises(WarframeApiError):
        await fake_api.find("mods", "Continuity")


# --- Avec l'index local -------------------------------------------------------------------------------------

EXPERT = "/Lotus/Upgrades/Mods/Warframe/Expert/AvatarAbilityDurationModExpert"


def fiche_path(kind: str, unique: str) -> str:
    return f"/{kind}/" + unique.replace("/", "%2F")


@pytest.fixture
def indexed_api(fake_api, index, api_routes):
    """API avec l'index local et la fiche de Continuité Accrue servie par son identifiant."""
    fake_api.index = index
    primed = next(mod for mod in api_routes[("/mods/search/Continuity", None)] if mod["name"] == "Primed Continuity")
    api_routes[(fiche_path("mods", EXPERT), None)] = primed
    api_routes[(fiche_path("mods", EXPERT), "fr")] = {"name": "Continuité Accrue", "uniqueName": EXPERT}
    return fake_api


@pytest.mark.parametrize("query", ["continuite accrue", "Primed Continuity", "continuité accru"])
@pytest.mark.asyncio
async def test_index_finds_the_card_by_its_identifier(indexed_api, api_session, query):
    lookup = await indexed_api.find("mods", query)
    assert [(mod["name"], mod["name_fr"]) for mod in lookup.found] == [("Primed Continuity", "Continuité Accrue")]
    assert lookup.found[0]["levelStats"][-1] == "rank 10: +55% Ability Duration"
    assert lookup.sources == [("Primed Continuity", "https://wiki.warframe.com/w/Primed_Continuity")]
    assert [path for path, _ in api_session.calls] == [fiche_path("mods", EXPERT)] * 2  # fiche anglaise, textes français
    assert not any("/search/" in path for path, _ in api_session.calls)


@pytest.mark.asyncio
async def test_index_returns_the_real_mod_and_the_flawed_one(indexed_api, api_routes):
    by_unique = {mod["uniqueName"]: mod for mod in api_routes[("/mods/search/Continuity", None)]}
    for unique, mod in by_unique.items():
        api_routes[(fiche_path("mods", unique), None)] = mod
    lookup = await indexed_api.find("mods", "continuite")
    assert [mod.get("flawed", False) for mod in lookup.found] == [False, True]
    assert lookup.found[0]["levelStats"][-1] == "rank 5: +30% Ability Duration"


@pytest.mark.asyncio
async def test_index_proposes_its_candidates(indexed_api, api_session):
    lookup = await indexed_api.find("mods", "continu")
    assert lookup.found == [] and "Continuité" in lookup.suggestions
    assert api_session.calls == []  # aucun appel réseau pour proposer des noms


@pytest.mark.asyncio
async def test_unconfirmed_card_falls_back_to_the_live_search(indexed_api, api_routes, api_session):
    """Index plus ancien ou plus récent que l'API : la fiche ne se confirme pas, la recherche en direct reprend."""
    api_routes[(fiche_path("mods", EXPERT), None)] = {"name": "Autre", "uniqueName": "/Lotus/Autre"}
    api_routes[("/mods/search/Primed%20Continuity", None)] = api_routes[("/mods/search/Continuity", None)]
    lookup = await indexed_api.find("mods", "Primed Continuity")
    assert [mod["name"] for mod in lookup.found] == ["Primed Continuity"]
    assert any("/search/" in path for path, _ in api_session.calls)


@pytest.mark.asyncio
async def test_name_unknown_to_the_index_falls_back_to_the_live_search(indexed_api, api_session):
    lookup = await indexed_api.find("mods", "Continuty Zorglub")
    assert (lookup.found, lookup.suggestions) == ([], [])
    assert [params.get("language") for path, params in api_session.calls if "/search/" in path] == [None, "fr"]


@pytest.mark.asyncio
async def test_lists_are_downloaded_without_the_cache(fake_api, api_session, api_routes, index_lists):
    for name, (path, params) in LISTS.items():
        api_routes[(path, params.get("language"))] = index_lists[name]
    lists = await fake_api.download_lists()
    assert lists == index_lists and fake_api.cache == {}
    assert [(path, params) for path, params in api_session.calls] == [(path, params) for path, params in LISTS.values()]


@pytest.mark.asyncio
async def test_list_download_fails_as_a_whole(fake_api, api_routes, index_lists, failing_response):
    for name, (path, params) in LISTS.items():
        api_routes[(path, params.get("language"))] = index_lists[name]
    api_routes[("/weapons", None)] = failing_response("status")
    with pytest.raises(WarframeApiError, match="/weapons"):
        await fake_api.download_lists()
