import datetime as dt
import json
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

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
