import datetime as dt

from warframe import translations
from warframe.translations import Translator, build_tables, humanize


def tiny_tables():
    dict_fr = {
        "/Lotus/Language/Locations/TyanaPass": "Col de Tyane",
        "/Lotus/Language/Locations/Mars": "Mars",
        "/Lotus/Language/Missions/MissionName_Spy": "ESPIONNAGE",
        "/Lotus/Language/Game/Faction_CorpusUC": "Corpus",
        "/Lotus/Language/Items/Forma": "Forma",
        "/Lotus/Language/Items/BlueprintAndItem": "|ITEM| (Schéma)",
        "/Lotus/Language/Relics/Era_LITH": "Lith",
        "/Lotus/Language/G1Quests/TacAlertHalloweenTitle": "Cauchemars Hantés",
        "/Lotus/Language/Other/Unused": "pas gardé",
    }
    regions = {"SolNode450": {"name": "/Lotus/Language/Locations/TyanaPass", "systemName": "/Lotus/Language/Locations/Mars",
                              "missionType": "MT_INTEL", "faction": "FC_CORPUS"}}
    missions = {"MT_INTEL": {"name": "/Lotus/Language/Missions/MissionName_Spy"}}
    factions = {"FC_CORPUS": {"name": "/Lotus/Language/Game/Faction_CorpusUC"}, "FC_TENNO": {"index": 11}}
    items = [{"/Lotus/Types/Items/MiscItems/Forma": {"name": "/Lotus/Language/Items/Forma"}, "/Broken": "pas un dict"}]
    recipes = {"/Lotus/Types/Recipes/FormaBlueprint": {"resultType": "/Lotus/Types/Items/MiscItems/Forma"}}
    return build_tables(dict_fr, regions, missions, factions, items, recipes)


def test_build_tables():
    tables = tiny_tables()
    tr = Translator(tables)
    assert tr.node("SolNode450") == "Col de Tyane (Mars)"
    assert tr.node_mission("SolNode450") == "Espionnage"  # majuscules du dictionnaire normalisées
    assert tr.node_faction("SolNode450") == "Corpus"
    assert tr.item("/Lotus/Types/Recipes/FormaBlueprint") == "Forma (Schéma)"
    assert tr.era("VoidT1") == "Lith"
    assert tr.era("VoidT6") == "Omnia"  # absente du dictionnaire
    assert tr.text("/Lotus/Language/G1Quests/TacAlertHalloweenTitle") == "Cauchemars Hantés"
    assert "/Lotus/Language/Other/Unused" not in tables["strings"]


def test_translator_real_data(translator):
    assert translator.node("SolNode450") == "Col de Tyane (Mars)"
    assert translator.node("SaturnHUB") == "Relais Kronia (Saturne)"
    assert translator.faction("FC_INFESTATION") == "Infesté"
    assert translator.mission("MT_TERRITORY") == "Interception"


def test_store_items_path():
    tr = Translator({"items": {"/Lotus/Types/StoreItems/AvatarImages/Glyph": "Glyphe", "/Lotus/Upgrades/Mods/X": "Mod X"}})
    assert tr.item("/Lotus/StoreItems/Types/StoreItems/AvatarImages/Glyph") == "Glyphe"  # seul le 1er StoreItems saute
    assert tr.item("/Lotus/StoreItems/Upgrades/Mods/X") == "Mod X"


def test_unknown_identifiers_never_crash():
    tr = Translator()
    assert not tr.loaded
    assert tr.node("SolNode999") == "Sol Node999"
    assert tr.item("/Lotus/StoreItems/Upgrades/Skins/MeleeDangles/PumpkinMeleeDangle") == "Pumpkin Melee Dangle"
    assert tr.mission("MT_RAILJACK") == "Railjack"
    assert tr.text("/Lotus/Language/Events/HalloweenNaberusName") == "Halloween Naberus"
    assert tr.known_text("/Lotus/Language/Events/HalloweenNaberusName") is None
    assert tr.era("VoidT9") == "Void T9"
    assert tr.text(None) == ""


def test_humanize():
    assert humanize("MT_EXTERMINATION") == "Extermination"
    assert humanize("/Lotus/Language/TauPrologue/RoadToTauEventName") == "Road To Tau Event"


def test_cache_roundtrip(tmp_path):
    built_at = dt.datetime(2026, 11, 1, 12, tzinfo=dt.UTC)
    translations.write_cache(tmp_path, tiny_tables(), built_at)
    tr, at = translations.read_cache(tmp_path)
    assert at == built_at
    assert tr.node("SolNode450") == "Col de Tyane (Mars)"


def test_cache_missing_or_corrupt(tmp_path):
    assert translations.read_cache(tmp_path) is None
    (tmp_path / translations.CACHE_FILE).write_text("pas du json", encoding="utf-8")
    assert translations.read_cache(tmp_path) is None
