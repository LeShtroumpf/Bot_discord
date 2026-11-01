"""Traduction en français des identifiants du worldstate.

Les noms viennent des exports officiels du jeu republiés par browse.wf. On ne garde en mémoire que des
tables compactes (identifiant -> texte français), écrites dans le cache disque pour les redémarrages.
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

# Exports dont chaque entrée est {"name": "/Lotus/Language/…"} : noms d'objets.
ITEM_EXPORTS = (
    "ExportResources", "ExportWeapons", "ExportWarframes", "ExportUpgrades", "ExportCustoms",
    "ExportFlavour", "ExportGear", "ExportKeys", "ExportSentinels",
)
BLUEPRINT_KEY = "/Lotus/Language/Items/BlueprintAndItem"  # "|ITEM| (Schéma)"
# Ère des fissures : (clé du dictionnaire, nom de repli). Omnia est absente du dictionnaire.
ERAS = {
    "VoidT1": ("/Lotus/Language/Relics/Era_LITH", "Lith"),
    "VoidT2": ("/Lotus/Language/Relics/Era_MESO", "Méso"),
    "VoidT3": ("/Lotus/Language/Relics/Era_NEO", "Néo"),
    "VoidT4": ("/Lotus/Language/Relics/Era_AXI", "Axi"),
    "VoidT5": ("/Lotus/Language/Relics/Era_REQUIEM", "Requiem"),
    "VoidT6": (None, "Omnia"),
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
                 recipes: dict) -> dict:
    """Construit les tables compactes à partir des exports complets."""
    def fr(key):
        return dict_fr.get(key) if key else None

    tables = {"strings": {}, "nodes": {}, "missions": {}, "factions": {}, "items": {}, "eras": {}}
    for key, region in regions.items():
        tables["nodes"][key] = [fr(region.get("name")), fr(region.get("systemName")),
                                region.get("missionType"), region.get("faction")]
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
    for era, (key, fallback) in ERAS.items():
        tables["eras"][era] = fr(key) or fallback
    # Textes libres référencés par le worldstate (events, invasions) : seulement les clés de langue utiles.
    prefixes = ("/Lotus/Language/G1Quests/", "/Lotus/Language/Alerts/", "/Lotus/Language/Events/",
                "/Lotus/Language/Menu/")
    tables["strings"] = {k: v for k, v in dict_fr.items() if k.startswith(prefixes)}
    return tables


class Translator:
    """Traductions FR ; tout identifiant inconnu donne un nom lisible au lieu d'une erreur."""

    def __init__(self, tables: dict | None = None):
        tables = tables or {}
        self.strings = tables.get("strings", {})
        self.nodes = tables.get("nodes", {})
        self.missions = tables.get("missions", {})
        self.factions = tables.get("factions", {})
        self.items = tables.get("items", {})
        self.eras = tables.get("eras", {})

    @property
    def loaded(self) -> bool:
        return bool(self.nodes)

    def node(self, key: str) -> str:
        """"SolNode450" -> "Col de Tyane (Mars)"."""
        name, system, _, _ = self.nodes.get(key, (None, None, None, None))
        if not name:
            return humanize(key)
        name = normalize_case(name)  # quelques nœuds sont en majuscules dans le dictionnaire ("MUNIO")
        return f"{name} ({system})" if system else name

    def node_mission(self, key: str) -> str:
        mission = self.nodes.get(key, (None, None, None, None))[2]
        return self.mission(mission) if mission else "?"

    def node_faction(self, key: str) -> str:
        faction = self.nodes.get(key, (None, None, None, None))[3]
        return self.faction(faction) if faction else "?"

    def mission(self, key: str) -> str:
        return normalize_case(self.missions.get(key) or humanize(key))

    def faction(self, key: str) -> str:
        return self.factions.get(key) or humanize(key)

    def era(self, key: str) -> str:
        return self.eras.get(key) or ERAS.get(key, (None, humanize(key)))[1]

    def item(self, path: str) -> str:
        """Les récompenses utilisent souvent /Lotus/StoreItems/… : l'objet réel est le même chemin sans StoreItems."""
        if path in self.items:
            return self.items[path]
        alt = path.replace("/StoreItems/", "/", 1)
        return self.items.get(alt) or humanize(path)

    def text(self, key: str | None) -> str:
        if not key:
            return ""
        return self.strings.get(key) or humanize(key)

    def known_text(self, key: str | None) -> str | None:
        """Texte traduit, ou None si la clé est absente du dictionnaire (pas de nom reconstitué)."""
        return self.strings.get(key) if key else None


def read_cache(cache_dir: Path) -> tuple[Translator, dt.datetime] | None:
    """Traductions du cache disque et leur date, ou None si absent ou illisible."""
    try:
        data = json.loads((cache_dir / CACHE_FILE).read_text(encoding="utf-8"))
        return Translator(data["tables"]), dt.datetime.fromisoformat(data["built_at"])
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
             "ExportRecipes.json"] + [f"{name}.json" for name in ITEM_EXPORTS]
    try:
        results = await asyncio.gather(*(_fetch_json(session, name) for name in names))
    except (aiohttp.ClientError, TimeoutError, ValueError) as error:
        raise TranslationError(f"{type(error).__name__}: {error}") from error
    dict_fr, regions, mission_types, factions, recipes, *items = results
    return await asyncio.to_thread(build_tables, dict_fr, regions, mission_types, factions, items, recipes)
