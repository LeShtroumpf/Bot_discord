import datetime as dt
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import quote

import aiohttp
import pytest

from cephalon.warframe_api import WarframeApi
from warframe import DATA_DIR, arbitrations, synthesis
from warframe.translations import Translator

ROOT = Path(__file__).resolve().parents[1]
WARFRAME_DATA = Path(__file__).resolve().parent / "warframe"


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    """settings.json temporaire copié du modèle, cwd placé dessus."""
    shutil.copy(ROOT / "settings.example.json", tmp_path / "settings.json")
    monkeypatch.chdir(tmp_path)
    return tmp_path / "settings.json"


@pytest.fixture
def interaction():
    i = MagicMock()
    i.response.send_message = AsyncMock()
    i.response.defer = AsyncMock()
    i.response.is_done = MagicMock(return_value=False)
    i.followup.send = AsyncMock()
    return i


# --- Warframe ---------------------------------------------------------------------------------------------

@pytest.fixture
def worldstate():
    """Réponse réelle de warframestat.us (/pc/fr/), réduite aux clés utilisées."""
    return json.loads((WARFRAME_DATA / "worldstate.json").read_text(encoding="utf-8"))


@pytest.fixture
def now(worldstate):
    return dt.datetime.fromisoformat(worldstate["timestamp"])


@pytest.fixture
def translator():
    """Traductions réelles, réduites aux identifiants présents dans les données de test."""
    return Translator(json.loads((WARFRAME_DATA / "translations.json").read_text(encoding="utf-8")))


@pytest.fixture
def schedule():
    """Planning réel des arbitrages autour de la date du worldstate de test."""
    return arbitrations.Schedule.parse((WARFRAME_DATA / "arbys.txt").read_text(encoding="utf-8"))


@pytest.fixture
def tiers():
    return arbitrations.load_tiers(DATA_DIR / "arbitration_tiers.json")


@pytest.fixture
def synthesis_lua():
    """Extrait réel du module Synthesis/data du wiki."""
    return (WARFRAME_DATA / "synthesis.lua").read_text(encoding="utf-8")


@pytest.fixture
def targets(synthesis_lua):
    return synthesis.parse(synthesis_lua, minimum=1)


@pytest.fixture
def bilingual():
    """Traductions avec les tables anglaises, comme les construit build_tables."""
    return Translator({
        "nodes": {"SolNode1": ["Cambria", "Terre", "MT_INTEL", "FC_GRINEER"],
                  "SolNode2": ["Caloris", "Mercure", "MT_RESCUE", "FC_GRINEER"],
                  "SolNode3": ["Elion", "Mercure", "MT_CAPTURE", "FC_GRINEER"],
                  "MoonNode4": ["Copernic", "Lua", "MT_CAPTURE", "FC_GRINEER"],
                  "SolNode4": ["Ara", "Mars", "MT_CAPTURE", "FC_GRINEER"]},
        "nodes_en": {"cambria": ["SolNode1", "Earth"], "caloris": ["SolNode2", "Mercury"], "elion": ["SolNode3", "Mercury"],
                     "copernicus": ["MoonNode4", "Lua"], "ara": ["SolNode4", "Mars"]},
        "enemies": {"lancer": "Lancier", "shield lancer": "Lancier à Bouclier", "corrupted lancer": "Lancier Corrompu",
                    "eviscerator": "Éviscérateur", "arid eviscerator": "Éviscérateur Aride", "hellion": "Hellion"},
        "missions": {"MT_INTEL": "Espionnage", "MT_RESCUE": "Sauvetage", "MT_CAPTURE": "Capture"},
        "factions": {"FC_GRINEER": "Grineer"},
    })


# --- Cephalon ---------------------------------------------------------------------------------------------

CEPHALON_DATA = Path(__file__).resolve().parent / "cephalon"
CONTINUITY = "/Lotus/Upgrades/Mods/Warframe/AvatarAbilityDurationMod"
RHINO_PRIME = "/Lotus/Powersuits/Rhino/RhinoPrime"
FLAWED_CONTINUITY = "/Lotus/Upgrades/Mods/Warframe/Beginner/AvatarAbilityDurationModBeginner"


def cephalon_json(name: str):
    """Réponse réelle de warframestat.us, réduite."""
    return json.loads((CEPHALON_DATA / f"{name}.json").read_text(encoding="utf-8"))


class FakeResponse:
    def __init__(self, data, status=200):
        self.data, self.status = data, status

    def raise_for_status(self):
        if self.status >= 400:
            raise aiohttp.ClientResponseError(MagicMock(), (), status=self.status, message="erreur")

    async def json(self, content_type=None):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class FakeSession:
    """Session aiohttp de test : routes (chemin, langue) -> données, FakeResponse ou exception. Route absente = 404."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, params=None, **kwargs):
        path = url.removeprefix("https://api.warframestat.us")
        params = params or {}
        self.calls.append((path, params))
        answer = self.routes.get((path, params.get("language")), FakeResponse({"error": "No Result", "code": 404}, 404))
        if isinstance(answer, Exception):
            raise answer
        return answer if isinstance(answer, FakeResponse) else FakeResponse(answer)


@pytest.fixture
def api_routes():
    """Routes de l'API de test : modifiables par un test avant le premier appel."""
    return {
        ("/mods/search/Continuity", None): cephalon_json("mods_search_continuity"),
        ("/mods/search/Continuit%C3%A9", None): [],
        ("/mods/search/Continuit%C3%A9", "fr"): cephalon_json("mods_search_continuite_fr"),
        (f"/mods/{quote(CONTINUITY, safe='')}", None): {"name": "Continuity", "uniqueName": CONTINUITY},
        (f"/mods/{quote(FLAWED_CONTINUITY, safe='')}", None): {"name": "Continuity", "uniqueName": FLAWED_CONTINUITY},
        (f"/mods/{quote(CONTINUITY, safe='')}", "fr"): {"name": "Continuité", "uniqueName": CONTINUITY},
        (f"/items/{quote(RHINO_PRIME, safe='')}", "fr"): cephalon_json("items_rhino_prime_fr"),
        ("/mods/search/Continuty", None): [],
        ("/mods/search/Continuty", "fr"): [],
        ("/mods/search/Contin", None): cephalon_json("mods_search_continuity"),
        ("/mods/search/Contin", "fr"): cephalon_json("mods_search_continuite_fr"),
        ("/items/search/Rhino%20Prime", None): cephalon_json("items_search_rhino_prime"),
        ("/items/search/Braton%20Prime", None): cephalon_json("items_search_braton_prime"),
        ("/drops/search/Continuity", None): cephalon_json("drops_search_continuity"),
        ("/drops/search/Rien", None): [],
    }


@pytest.fixture
def failing_response():
    """Pannes de l'API : statut 500, délai dépassé, réseau coupé, JSON illisible, forme inattendue."""
    def build(failure: str):
        return {"status": FakeResponse({}, 500), "timeout": TimeoutError(), "network": aiohttp.ClientConnectionError("coupé"),
                "json": FakeResponse(ValueError("illisible")), "shape": {"error": "oups"}}[failure]
    return build


@pytest.fixture
def api_session(api_routes):
    return FakeSession(api_routes)


@pytest.fixture
def fake_api(api_session):
    return WarframeApi(api_session)


def claude_text(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def claude_tool(name: str, query: str, call_id: str = "toolu_1") -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=call_id, name=name, input={"name": query})


def claude_reply(stop_reason: str, *content, input_tokens=100, output_tokens=20, cache_read=0, cache_write=0):
    usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens,
                            cache_read_input_tokens=cache_read, cache_creation_input_tokens=cache_write)
    return SimpleNamespace(stop_reason=stop_reason, content=list(content), usage=usage)


class FakeClaude:
    """Faux client Anthropic : rejoue des réponses (ou lève une exception) et garde une copie de chaque requête."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests: list[dict] = []
        self.messages = SimpleNamespace(create=self.create)

    async def create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def claude():
    """Fabriques du faux Claude : claude.client(*réponses), claude.reply(stop_reason, *blocs), claude.text, claude.tool."""
    return SimpleNamespace(client=FakeClaude, reply=claude_reply, text=claude_text, tool=claude_tool)
