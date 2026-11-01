import datetime as dt
import json
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from warframe import DATA_DIR, arbitrations
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
    """Worldstate réel enregistré (réduit aux clés utilisées)."""
    return json.loads((WARFRAME_DATA / "worldstate.json").read_text(encoding="utf-8"))


@pytest.fixture
def now(worldstate):
    return dt.datetime.fromtimestamp(worldstate["Time"], tz=dt.UTC)


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
