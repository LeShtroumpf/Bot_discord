"""Traduction en français des identifiants du worldstate.

Les noms viennent des exports officiels du jeu republiés par browse.wf. On ne garde en mémoire que des
tables compactes (identifiant -> texte français), écrites dans le cache disque pour les redémarrages.
Les textes absents des exports (noms d'events, envoyés par le serveur du jeu) sont dans une table locale tenue à la main
(warframe/data/textes_fr.json), prioritaire sur les exports.
"""
import asyncio
import datetime as dt
import json
import re
from pathlib import Path

import aiohttp

EXPORT_BASE = "https://browse.wf/warframe-public-export-plus/"
EXPORT_TIMEOUT = aiohttp.ClientTimeout(total=60)
MAX_AGE = dt.timedelta(hours=24)
CACHE_FILE = "translations.json"
REQUIRED_TABLES = {"nodes", "nodes_en", "enemies", "node_missions"}
OVERRIDES_FILE = "textes_fr.json"

# Exports dont chaque entrée est {"name": "/Lotus/Language/…"} : noms d'objets.
ITEM_EXPORTS = (
    "ExportResources", "ExportWeapons", "ExportWarframes", "ExportUpgrades", "ExportCustoms",
    "ExportFlavour", "ExportGear", "ExportKeys", "ExportSentinels", "ExportBoosters", "ExportBoosterPacks",
    "ExportArcanes", "ExportDrones", "ExportAvionics", "ExportRailjackWeapons", "ExportBundles",
)
BLUEPRINT_KEY = "/Lotus/Language/Items/BlueprintAndItem"  # "|ITEM| (Schéma)"
RELIC_KEY = "/Lotus/Language/Relics/VoidProjectionName"   # "Relique |ERA| |CATEGORY|"
# Ère des fissures : (clé du dictionnaire, nom de repli).
ERAS = {
    "VoidT1": ("/Lotus/Language/Relics/Era_LITH", "Lith"),
    "VoidT2": ("/Lotus/Language/Relics/Era_MESO", "Méso"),
    "VoidT3": ("/Lotus/Language/Relics/Era_NEO", "Néo"),
    "VoidT4": ("/Lotus/Language/Relics/Era_AXI", "Axi"),
    "VoidT5": ("/Lotus/Language/Relics/Era_REQUIEM", "Requiem"),
    "VoidT6": ("/Lotus/Language/Relics/Era_OMNI", "Omnia"),
}


class TranslationError(Exception):
    """Exports du jeu injoignables ou invalides."""


def humanize(identifier: str) -> str:
    """Nom lisible tiré d'un identifiant inconnu : "/Lotus/…/PumpkinMeleeDangle" -> "Pumpkin Melee Dangle"."""
    last = str(identifier).rstrip("/").split("/")[-1]
    last = re.sub(r"^(MT_|FC_)", "", last)
    last = re.sub(r"(Name|Title|Desc)$", "", last)  # clés de langue : "HalloweenNaberusName" -> "Halloween Naberus"
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", last).replace("_", " ").strip()
    return normalize_case(words) if words else str(identifier)


def normalize_case(text: str) -> str:
    """Le dictionnaire écrit certains noms en majuscules ("ESPIONNAGE") : on remet une casse normale."""
    return text.capitalize() if text.isupper() else text


def build_tables(dict_fr: dict, regions: dict, mission_types: dict, factions: dict, item_exports: list[dict],
                 recipes: dict, dict_en: dict | None = None, enemies: dict | None = None, relics: dict | None = None) -> dict:
    """Construit les tables compactes à partir des exports complets."""
    def fr(key):
        return dict_fr.get(key) if key else None

    def en(key):
        return (dict_en or {}).get(key) if key else None

    tables = {"strings": {}, "nodes": {}, "nodes_en": {}, "enemies": {}, "missions": {}, "factions": {}, "items": {}, "eras": {},
              "node_missions": {}}
    for key, region in regions.items():
        tables["nodes"][key] = [fr(region.get("name")), fr(region.get("systemName")),
                                region.get("missionType"), region.get("faction")]
        # Nom de mission propre au nœud, plus précis que le type : les nœuds Railjack ont tous MT_RAILJACK mais
        # sont des Escarmouches, des Orphix… ; d'autres sont des « Défense Miroir », « Survie Conjonction ».
        if fr(region.get("missionName")):
            tables["node_missions"][key] = normalize_case(fr(region["missionName"]))
        if en(region.get("name")):
            tables["nodes_en"].setdefault(en(region["name"]).casefold(), [key, en(region.get("systemName"))])
    for enemy in (enemies or {}).get("avatars", {}).values():
        if en(enemy.get("name")) and fr(enemy.get("name")):
            tables["enemies"].setdefault(en(enemy["name"]).casefold(), normalize_case(fr(enemy["name"])))
    for key, mission in mission_types.items():
        if fr(mission.get("name")):
            tables["missions"][key] = normalize_case(fr(mission["name"]))
    for key, faction in factions.items():
        if fr(faction.get("name")):
            tables["factions"][key] = normalize_case(fr(faction["name"]))
    for export in item_exports:
        for path, item in export.items():
            if isinstance(item, dict) and fr(item.get("name")):
                tables["items"][path] = fr(item["name"])
    template = dict_fr.get(BLUEPRINT_KEY, "|ITEM| (Schéma)")
    for path, recipe in recipes.items():
        result = tables["items"].get(recipe.get("resultType"))
        if result and path not in tables["items"]:
            tables["items"][path] = template.replace("|ITEM|", result)
    relic_template = dict_fr.get(RELIC_KEY, "Relique |ERA| |CATEGORY|")
    for path, relic in (relics or {}).items():  # pas de nom dans l'export : « Relique Axi M5 »
        if isinstance(relic, dict) and relic.get("era") and relic.get("category") and path not in tables["items"]:
            era = fr(f"/Lotus/Language/Relics/Era_{relic['era'].upper()}") or relic["era"]
            tables["items"][path] = relic_template.replace("|ERA|", era).replace("|CATEGORY|", relic["category"])
    for era, (key, fallback) in ERAS.items():
        tables["eras"][era] = fr(key) or fallback
    # Textes libres référencés par le worldstate (events, invasions) : seulement les clés de langue utiles.
    prefixes = ("/Lotus/Language/G1Quests/", "/Lotus/Language/Alerts/", "/Lotus/Language/Events/",
                "/Lotus/Language/Menu/")
    tables["strings"] = {k: v for k, v in dict_fr.items() if k.startswith(prefixes)}
    return tables


class Translator:
    """Traductions FR ; tout identifiant inconnu donne un nom lisible au lieu d'une erreur.

    `overrides` (table locale) passe avant les exports. Les identifiants inconnus sont notés dans `missing`
    avec le sujet en cours de rendu (`topic`, posé par render_all), pour être signalés une fois dans le salon de logs."""

    def __init__(self, tables: dict | None = None, overrides: dict[str, str] | None = None):
        tables = tables or {}
        self.strings = tables.get("strings", {})
        self.nodes = tables.get("nodes", {})
        self.nodes_en = tables.get("nodes_en", {})
        self.enemies = tables.get("enemies", {})
        self.missions = tables.get("missions", {})
        self.factions = tables.get("factions", {})
        self.items = tables.get("items", {})
        self.eras = tables.get("eras", {})
        self.node_missions = tables.get("node_missions", {})
        self.overrides = overrides or {}
        self.topic = ""
        self.missing: set[tuple[str, str, str]] = set()  # (sujet, identifiant, nom reconstitué)

    @property
    def loaded(self) -> bool:
        return bool(self.nodes)

    def unknown(self, key: str) -> str:
        """Nom reconstitué d'un identifiant absent des tables, noté pour être signalé (sauf tables pas encore chargées :
        tout serait inconnu)."""
        guess = humanize(key)
        if self.loaded:
            self.missing.add((self.topic, str(key), guess))
        return guess

    def node(self, key: str) -> str:
        """"SolNode450" -> "Col de Tyane (Mars)"."""
        if key in self.overrides:
            return self.overrides[key]
        name, system, _, _ = self.nodes.get(key, (None, None, None, None))
        if not name:
            return self.unknown(key)
        name = normalize_case(name)  # quelques nœuds sont en majuscules dans le dictionnaire ("MUNIO")
        return f"{name} ({system})" if system else name

    def node_key(self, english_name: str) -> str | None:
        """"Copernicus" -> "MoonNode4", ou None si le nœud est inconnu."""
        return self.nodes_en.get(english_name.casefold(), (None, None))[0]

    def node_bilingual(self, english_name: str) -> str:
        """"Copernicus" -> "Copernic (Lune / Lua)". Nœud inconnu : le nom anglais tel quel."""
        key, system_en = self.nodes_en.get(english_name.casefold(), (None, None))
        if key is None or key not in self.nodes:
            return english_name
        name, system = normalize_case(self.nodes[key][0]), self.nodes[key][1]
        systems = system if not system_en or system == system_en else f"{system} / {system_en}"
        return f"{name} ({systems})" if systems else name

    def enemy(self, english_name: str) -> str | None:
        """Nom français d'un ennemi à partir de son nom anglais."""
        return self.enemies.get(english_name.casefold())

    def node_mission(self, key: str) -> str:
        """Mission propre au nœud ("Escarmouche" pour un nœud Railjack), sinon son type de mission."""
        if key in self.node_missions:
            return self.node_missions[key]
        mission = self.nodes.get(key, (None, None, None, None))[2]
        return self.mission(mission) if mission else "?"

    def node_faction(self, key: str) -> str:
        faction = self.nodes.get(key, (None, None, None, None))[3]
        return self.faction(faction) if faction else "?"

    def mission(self, key: str) -> str:
        if key in self.overrides:
            return self.overrides[key]
        return normalize_case(self.missions.get(key) or self.unknown(key))

    def faction(self, key: str) -> str:
        if key in self.overrides:
            return self.overrides[key]
        return self.factions.get(key) or self.unknown(key)

    def era(self, key: str) -> str:
        if key in self.eras:
            return self.eras[key]
        return ERAS[key][1] if key in ERAS else self.unknown(key)

    def item(self, path: str) -> str:
        """Les récompenses utilisent souvent /Lotus/StoreItems/… : l'objet réel est le même chemin sans StoreItems."""
        alt = path.replace("/StoreItems/", "/", 1)
        for candidate in (path, alt):
            if candidate in self.overrides:
                return self.overrides[candidate]
        return self.items.get(path) or self.items.get(alt) or self.unknown(path)

    def text(self, key: str | None) -> str:
        if not key:
            return ""
        return self.overrides.get(key) or self.strings.get(key) or self.unknown(key)

    def known_text(self, key: str | None) -> str | None:
        """Texte traduit, ou None si la clé est absente des tables (pas de nom reconstitué)."""
        return (self.overrides.get(key) or self.strings.get(key)) if key else None


def read_overrides(path: Path) -> tuple[dict[str, str], str | None]:
    """Table locale (identifiant -> texte français) et message d'erreur s'il y en a une (table vide dans ce cas)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return {}, f"{path.name} illisible : {type(error).__name__}: {error}"
    if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
        return {}, f"{path.name} invalide : un objet JSON {{\"identifiant\": \"texte\"}} est attendu"
    return data, None


def read_cache(cache_dir: Path, overrides: dict[str, str] | None = None) -> tuple[Translator, dt.datetime] | None:
    """Traductions du cache disque et leur date, ou None si absent ou illisible."""
    try:
        data = json.loads((cache_dir / CACHE_FILE).read_text(encoding="utf-8"))
        if not REQUIRED_TABLES <= data["tables"].keys():  # cache d'une ancienne version : on reconstruit
            return None
        return Translator(data["tables"], overrides), dt.datetime.fromisoformat(data["built_at"])
    except (OSError, ValueError, KeyError):
        return None


def write_cache(cache_dir: Path, tables: dict, built_at: dt.datetime) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = cache_dir / (CACHE_FILE + ".tmp")
    tmp.write_text(json.dumps({"built_at": built_at.isoformat(), "tables": tables}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(cache_dir / CACHE_FILE)


async def _fetch_json(session: aiohttp.ClientSession, name: str) -> dict:
    async with session.get(EXPORT_BASE + name, timeout=EXPORT_TIMEOUT) as response:
        response.raise_for_status()
        return await response.json(content_type=None)


async def download_tables(session: aiohttp.ClientSession) -> dict:
    """Télécharge les exports et construit les tables (le calcul tourne hors de la boucle asyncio)."""
    names = ["dict.fr.json", "ExportRegions.json", "ExportMissionTypes.json", "ExportFactions.json",
             "ExportRecipes.json", "dict.en.json", "ExportEnemies.json", "ExportRelics.json"]
    names += [f"{name}.json" for name in ITEM_EXPORTS]
    try:
        results = await asyncio.gather(*(_fetch_json(session, name) for name in names))
    except (aiohttp.ClientError, TimeoutError, ValueError) as error:
        raise TranslationError(f"{type(error).__name__}: {error}") from error
    dict_fr, regions, mission_types, factions, recipes, dict_en, enemies, relics, *items = results
    return await asyncio.to_thread(build_tables, dict_fr, regions, mission_types, factions, items, recipes, dict_en, enemies,
                                   relics)
