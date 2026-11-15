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
    assert tr.era("VoidT6") == "Omnia"  # absente de ce petit dictionnaire : nom de repli
    assert tr.text("/Lotus/Language/G1Quests/TacAlertHalloweenTitle") == "Cauchemars Hantés"
    assert "/Lotus/Language/Other/Unused" not in tables["strings"]


def english_tables():
    dict_fr = {"/Node": "Copernic", "/Lua": "Lua", "/Earth": "Terre", "/Cambria": "Cambria", "/Lancer": "Lancier", "/Loud": "HURLEUR"}
    dict_en = {"/Node": "Copernicus", "/Lua": "Lua", "/Earth": "Earth", "/Cambria": "Cambria", "/Lancer": "Lancer", "/Loud": "Howler"}
    regions = {"MoonNode4": {"name": "/Node", "systemName": "/Lua", "missionType": "MT_INTEL", "faction": "FC_CORPUS"},
               "SolNode1": {"name": "/Cambria", "systemName": "/Earth", "missionType": "MT_INTEL", "faction": "FC_CORPUS"}}
    enemies = {"avatars": {"/Enemy/Lancer": {"name": "/Lancer"}, "/Enemy/Loud": {"name": "/Loud"}, "/Enemy/NoName": {}}}
    return build_tables(dict_fr, regions, {}, {}, [], {}, dict_en, enemies)


def test_english_tables():
    tr = Translator(english_tables())
    assert tr.node_key("Copernicus") == "MoonNode4"
    assert tr.node_key("COPERNICUS") == "MoonNode4"
    assert tr.node_bilingual("Copernicus") == "Copernic (Lua)"
    assert tr.node_bilingual("Cambria") == "Cambria (Terre / Earth)"
    assert tr.enemy("Lancer") == "Lancier"
    assert tr.enemy("Howler") == "Hurleur"


def test_unknown_english_names():
    tr = Translator(english_tables())
    assert tr.node_key("Atlantide") is None
    assert tr.node_bilingual("Atlantide") == "Atlantide"
    assert tr.enemy("Inconnu") is None


def test_cache_without_english_tables_is_rebuilt(tmp_path):
    tables = {key: value for key, value in tiny_tables().items() if key not in ("nodes_en", "enemies")}
    translations.write_cache(tmp_path, tables, dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
    assert translations.read_cache(tmp_path) is None


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


# --- Ajouts pour browse.wf : reliques, missions des nœuds, table locale, identifiants inconnus ---------------------

def test_relics_and_node_missions():
    dict_fr = {"/Lotus/Language/Relics/VoidProjectionName": "Relique |ERA| |CATEGORY|", "/Lotus/Language/Relics/Era_AXI": "Axi",
               "/Lotus/Language/Relics/Era_OMNI": "Omnia", "/Lotus/Language/Locations/Bendar": "Amas Bendar",
               "/Lotus/Language/Missions/MissionName_Railjack": "ESCARMOUCHE"}
    regions = {"CrewBattleNode522": {"name": "/Lotus/Language/Locations/Bendar", "missionType": "MT_RAILJACK",
                                     "missionName": "/Lotus/Language/Missions/MissionName_Railjack", "faction": "FC_GRINEER"}}
    relics = {"/Lotus/Types/Game/Projections/T4VoidProjectionBaroAkmagnusPrimeBronze": {"era": "Axi", "category": "M5"},
              "/Lotus/Types/Game/Projections/Broken": {"era": "Axi"}}
    tr = Translator(build_tables(dict_fr, regions, {}, {}, [], {}, relics=relics))
    assert tr.item("/Lotus/StoreItems/Types/Game/Projections/T4VoidProjectionBaroAkmagnusPrimeBronze") == "Relique Axi M5"
    assert tr.node_mission("CrewBattleNode522") == "Escarmouche"  # MT_RAILJACK ne dit rien du type réel
    assert tr.era("VoidT6") == "Omnia"


def test_new_item_exports_are_downloaded():
    for name in ("ExportBoosters", "ExportBoosterPacks", "ExportArcanes", "ExportDrones", "ExportAvionics",
                 "ExportRailjackWeapons", "ExportBundles"):
        assert name in translations.ITEM_EXPORTS


def test_cache_without_node_missions_is_rebuilt(tmp_path):
    tables = {key: value for key, value in tiny_tables().items() if key != "node_missions"}
    translations.write_cache(tmp_path, tables, dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
    assert translations.read_cache(tmp_path) is None


def test_overrides_come_first():
    overrides = {"/Lotus/Language/G1Quests/TacAlertHalloweenTitle": "Cauchemars", "/Lotus/Types/Items/MiscItems/Forma": "Forma !",
                 "MT_INTEL": "Espionnage corrigé", "FC_CORPUS": "Les Corpus", "/Lotus/Language/Events/New": "Nouveau"}
    tr = Translator(tiny_tables(), overrides)
    assert tr.text("/Lotus/Language/G1Quests/TacAlertHalloweenTitle") == "Cauchemars"
    assert tr.item("/Lotus/StoreItems/Types/Items/MiscItems/Forma") == "Forma !"  # chemin StoreItems aussi
    assert tr.mission("MT_INTEL") == "Espionnage corrigé"
    assert tr.faction("FC_CORPUS") == "Les Corpus"
    assert tr.known_text("/Lotus/Language/Events/New") == "Nouveau"
    assert not tr.missing


def test_real_overrides_cover_the_test_events(translator, sources):
    for event in sources["worldstate"].events:
        assert translator.known_text(event.name)
    assert translator.item("/Lotus/StoreItems/Types/Gameplay/Events/RoadToTauEvent/RoadToTauEventResource") == "Chair de Lune"


def test_read_overrides(tmp_path):
    path = tmp_path / "textes_fr.json"
    path.write_text('{"/Lotus/X": "X"}', encoding="utf-8")
    assert translations.read_overrides(path) == ({"/Lotus/X": "X"}, None)
    path.write_text('{"/Lotus/X": 3}', encoding="utf-8")
    table, error = translations.read_overrides(path)
    assert table == {} and "invalide" in error
    path.write_text("{pas du json", encoding="utf-8")
    table, error = translations.read_overrides(path)
    assert table == {} and "illisible" in error
    table, error = translations.read_overrides(tmp_path / "absent.json")
    assert table == {} and "illisible" in error


def test_unknown_identifiers_are_tracked_with_their_topic():
    tr = Translator(tiny_tables())
    tr.topic = "events"
    assert tr.text("/Lotus/Language/Events/HalloweenNaberusName") == "Halloween Naberus"
    tr.topic = "baro"
    tr.item("/Lotus/StoreItems/Upgrades/Skins/X/Pumpkin")
    tr.node("SolNode450"), tr.mission("MT_INTEL"), tr.faction("FC_CORPUS")  # connus : pas notés
    assert tr.missing == {("events", "/Lotus/Language/Events/HalloweenNaberusName", "Halloween Naberus"),
                          ("baro", "/Lotus/StoreItems/Upgrades/Skins/X/Pumpkin", "Pumpkin")}


def test_nothing_is_tracked_before_the_tables_are_loaded():
    tr = Translator()
    tr.text("/Lotus/Language/Events/HalloweenNaberusName")
    tr.node("SolNode999")
    assert tr.missing == set()
