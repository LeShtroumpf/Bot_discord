"""Index local des données de warframestat : noms tolérants aux fautes, mods par effet, classements.

Construit une fois par jour à partir des listes complètes de l'API, gardé en mémoire et dans un fichier.
L'index sert à trouver : la fiche détaillée d'un objet vient toujours de l'API. Tris et filtres sont faits ici, par le
code, jamais par le modèle.
"""
import datetime as dt
import difflib
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from cephalon.config import MAX_RESULTS

INDEX_FILE = "index.json"
VERSION = 2                 # format du fichier : un fichier d'une autre version est ignoré, puis reconstruit
FLAWED_PATH = "/Beginner/"  # mods Défectueux : même nom que le mod normal, valeurs plus faibles
MAX_MATCHES = 3             # objets au même nom renvoyés, au plus
# L'API liste sous le même nom des variantes internes d'un mod (Serration à +90 % et à +165 %, Vital Sense à +120 % et
# à +220 %), avec la même page du wiki. La fiche de référence est celle dont le chemin n'a aucun de ces segments.
VARIANT_PATHS = ("/Intermediate/", "/Expert/")

MODS, ITEMS = "mods", "items"
MOD_FIELDS = "name,uniqueName,type,compatName,polarity,rarity,baseDrain,fusionLimit,levelStats,wikiaUrl"
NAME_FIELDS = "name,uniqueName"
ITEM_FIELDS = "name,uniqueName,category,type"
WEAPON_STATS = ("criticalChance", "criticalMultiplier", "procChance", "fireRate", "totalDamage", "magazineSize",
                "reloadTime", "disposition", "masteryReq")
WEAPON_FIELDS = "name,uniqueName,category,type,wikiaUrl," + ",".join(WEAPON_STATS)
FRAME_STATS = ("health", "shield", "armor", "power", "sprintSpeed")
FRAME_FIELDS = "name,uniqueName,type,wikiaUrl," + ",".join(FRAME_STATS)

# Les six listes complètes demandées à l'API : nom -> (chemin, paramètres).
LISTS = {
    "mods": ("/mods", {"only": MOD_FIELDS}),
    "mods_fr": ("/mods", {"only": NAME_FIELDS, "language": "fr"}),
    "items": ("/items", {"only": ITEM_FIELDS}),
    "items_fr": ("/items", {"only": NAME_FIELDS, "language": "fr"}),
    "weapons": ("/weapons", {"only": WEAPON_FIELDS}),
    "warframes": ("/warframes", {"only": FRAME_FIELDS}),
}
# En dessous, la liste est jugée cassée : on garde l'index précédent plutôt que d'en construire un vide.
MINIMUMS = {"mods": 500, "mods_fr": 500, "items": 5000, "items_fr": 5000, "weapons": 200, "warframes": 50}

# Cosmétiques : jamais proposés pour un nom approchant, mais trouvés par leur nom exact.
COSMETIC_CATEGORIES = {"Skins", "Glyphs", "Sigils"}
COSMETIC_TYPES = {"Ship Decoration"}

CLOSE = 0.75   # ressemblance minimale d'un nom approchant (0 à 1)
SURE = 0.85    # au-dessus, et nettement devant le suivant, le nom approchant est pris pour le bon
MARGIN = 0.05

MARKUP = re.compile(r"<[A-Z_]+>")  # balises de couleur du jeu : <DT_POISON_COLOR>
WEAPON_CATEGORIES = ("Primary", "Secondary", "Melee", "Arch-Gun", "Arch-Melee")
FRAME_KINDS = ("Warframe", "Archwing", "Necramech")


class IndexError_(Exception):
    """Listes incomplètes ou fichier d'index illisible."""


def normalize(text: str) -> str:
    """Nom sans accents, sans casse ni ponctuation : « Continuité Accrue » et « continuite accrue » se valent."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char)).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def flawed(unique: str) -> bool:
    return FLAWED_PATH in unique


def doubtful_variants(mods: list[dict]) -> set[str]:
    """Identifiants des variantes internes qui doublent un mod de référence du même nom : écartées de l'index."""
    def variant(unique: str) -> bool:
        return any(path in unique for path in VARIANT_PATHS)

    reference = {mod["name"] for mod in mods if not variant(mod["uniqueName"]) and not flawed(mod["uniqueName"])}
    return {mod["uniqueName"] for mod in mods if variant(mod["uniqueName"]) and mod["name"] in reference}


def max_rank_effect(mod: dict) -> str:
    levels = mod.get("levelStats") or []
    stats = levels[-1].get("stats", []) if levels and isinstance(levels[-1], dict) else []
    return " / ".join(MARKUP.sub("", stat).strip() for stat in stats if isinstance(stat, str))


def compact(lists: dict[str, list], minimums: dict[str, int] | None = None) -> dict:
    """Les six listes de l'API réduites à ce que l'index utilise. IndexError_ si l'une est absente ou trop courte."""
    for name, minimum in (MINIMUMS if minimums is None else minimums).items():
        rows = lists.get(name)
        if not isinstance(rows, list) or len(rows) < minimum:
            raise IndexError_(f"liste {name} incomplète ({len(rows) if isinstance(rows, list) else 'absente'})")

    def rows(name: str) -> list[dict]:
        return [row for row in lists.get(name) or [] if isinstance(row, dict) and row.get("name") and row.get("uniqueName")]

    french = {family: {row["uniqueName"]: row["name"] for row in rows(f"{family}_fr")} for family in (MODS, ITEMS)}
    doubtful = doubtful_variants(rows(MODS))
    names = [[family, row["uniqueName"], row["name"], french[family].get(row["uniqueName"], row["name"]),
              row.get("category") or "", row.get("type") or ""]
             for family in (MODS, ITEMS) for row in rows(family) if row["uniqueName"] not in doubtful]
    mods = [{"unique": row["uniqueName"], "name": row["name"], "name_fr": french[MODS].get(row["uniqueName"], row["name"]),
             "type": row.get("type") or "", "compat": row.get("compatName") or "", "polarity": row.get("polarity") or "",
             "rarity": row.get("rarity") or "", "drain": row.get("baseDrain"), "max_rank": row.get("fusionLimit"),
             "effect": max_rank_effect(row), "wiki": row.get("wikiaUrl") or ""}
            for row in rows(MODS) if not flawed(row["uniqueName"]) and row["uniqueName"] not in doubtful]
    weapons = [{"name": row["name"], "category": row.get("category") or "", "type": row.get("type") or "",
                "wiki": row.get("wikiaUrl") or "", **{stat: row[stat] for stat in WEAPON_STATS if number(row.get(stat))}}
               for row in rows("weapons")]
    warframes = [{"name": row["name"], "kind": row.get("type") or "", "wiki": row.get("wikiaUrl") or "",
                  **{stat: row[stat] for stat in FRAME_STATS if number(row.get(stat))}}
                 for row in rows("warframes")]
    return {"names": names, "mods": mods, "weapons": weapons, "warframes": warframes}


def number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


@dataclass
class Resolution:
    """Résultat d'un rapprochement de nom : les objets retenus, sinon des noms à proposer."""
    matches: list[dict] = field(default_factory=list)     # {unique, name, name_fr, category, type}
    candidates: list[str] = field(default_factory=list)


@dataclass
class Ranking:
    total: int
    rows: list[dict]
    sources: list[tuple[str, str]] = field(default_factory=list)  # (nom, page du wiki) des premiers résultats


class Index:
    def __init__(self, data: dict, built_at: dt.datetime):
        self.data = data
        self.built_at = built_at
        self.mods: list[dict] = data["mods"]
        self.weapons: list[dict] = data["weapons"]
        self.warframes: list[dict] = data["warframes"]
        self.names: dict[str, dict[str, list[dict]]] = {MODS: {}, ITEMS: {}}  # famille -> nom normalisé -> objets
        self.display: dict[str, dict[str, str]] = {MODS: {}, ITEMS: {}}       # famille -> nom normalisé -> nom à proposer
        for family, unique, name, name_fr, category, kind in data["names"]:
            entry = {"unique": unique, "name": name, "name_fr": name_fr, "category": category, "type": kind}
            cosmetic = category in COSMETIC_CATEGORIES or kind in COSMETIC_TYPES
            for label in dict.fromkeys((name_fr, name)):  # le nom français d'abord : c'est lui qu'on propose
                key = normalize(label)
                if not key:
                    continue
                self.names[family].setdefault(key, []).append(entry)
                if not cosmetic:
                    self.display[family].setdefault(key, label)
        self.mod_texts = [normalize(f"{mod['name']} {mod['name_fr']} {mod['effect']}") for mod in self.mods]

    @classmethod
    def build(cls, lists: dict[str, list], built_at: dt.datetime, minimums: dict[str, int] | None = None) -> "Index":
        return cls(compact(lists, minimums), built_at)

    def summary(self) -> str:
        objects = len({entry[1] for entry in self.data["names"] if entry[0] == ITEMS})
        return f"{len(self.mods)} mods, {len(self.weapons)} armes, {len(self.warframes)} Warframes, {objects} objets"

    def age(self, now: dt.datetime) -> float:
        return (now - self.built_at).total_seconds()

    # --- Fichier (appels bloquants : à lancer dans un thread) ----------------------------------------------

    @classmethod
    def read(cls, directory: Path) -> "Index | None":
        """L'index gardé sur disque, None s'il n'y en a pas. IndexError_ s'il est illisible."""
        try:
            saved = json.loads((Path(directory) / INDEX_FILE).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as error:
            raise IndexError_(f"index illisible : {error}") from error
        try:
            if saved["version"] != VERSION:
                return None
            built_at = dt.datetime.fromisoformat(saved["built_at"])
            if built_at.tzinfo is None:
                raise ValueError("date sans fuseau")
            return cls(saved["data"], built_at)
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise IndexError_(f"index d'une forme inattendue : {error or type(error).__name__}") from error

    def write(self, directory: Path) -> None:
        """Écriture atomique : un fichier temporaire, puis un renommage."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        tmp = directory / (INDEX_FILE + ".tmp")
        saved = {"version": VERSION, "built_at": self.built_at.isoformat(), "data": self.data}
        tmp.write_text(json.dumps(saved, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, directory / INDEX_FILE)

    # --- Noms ---------------------------------------------------------------------------------------------

    def resolve(self, family: str, name: str) -> Resolution:
        """Les objets de ce nom, malgré un accent oublié ou une faute de frappe ; sinon des noms à proposer."""
        table, display = self.names[family], self.display[family]
        key = normalize(name)
        if not key:
            return Resolution()
        if key in table:
            return Resolution(matches=sorted(table[key], key=lambda entry: flawed(entry["unique"]))[:MAX_MATCHES])
        close = difflib.get_close_matches(key, display, n=MAX_RESULTS, cutoff=CLOSE)
        if close:
            scores = [difflib.SequenceMatcher(None, key, candidate).ratio() for candidate in close[:2]]
            if scores[0] >= SURE and (len(scores) == 1 or scores[0] - scores[1] >= MARGIN):
                return Resolution(matches=sorted(table[close[0]], key=lambda entry: flawed(entry["unique"]))[:MAX_MATCHES])
        words = key.split()
        partial = [candidate for candidate in display if all(word in candidate.split() for word in words)]
        partial.sort(key=lambda candidate: (len(candidate), candidate))
        proposed = list(dict.fromkeys(close + partial))[:MAX_RESULTS]
        return Resolution(candidates=[display[candidate] for candidate in proposed])

    # --- Recherches et classements ------------------------------------------------------------------------

    def search_mods(self, keywords: list[str], kind: str | None = None) -> Ranking:
        """Mods dont le nom ou l'effet contient tous les mots-clés ; à défaut, ceux qui en contiennent le plus."""
        wanted = [key for key in (normalize(keyword) for keyword in keywords) if key]
        kind = normalize(kind or "")
        scored = []
        for mod, text in zip(self.mods, self.mod_texts):
            if kind and kind not in normalize(f"{mod['type']} {mod['compat']}"):
                continue
            hits = sum(1 for key in wanted if key in text)
            if hits:
                scored.append((hits, mod))
        best = max((hits for hits, _ in scored), default=0)
        # Les effets courts d'abord : « +30% Ability Duration » avant un augment qui cite la durée en passant.
        found = sorted((mod for hits, mod in scored if hits == best), key=lambda mod: (len(mod["effect"]), mod["name"]))
        rows = [{"name": mod["name"], "name_fr": mod["name_fr"], "type": mod["type"], "compatibility": mod["compat"],
                 "polarity": mod["polarity"], "rarity": mod["rarity"], "max_rank": mod["max_rank"],
                 "effect_at_max_rank": mod["effect"]} for mod in found[:MAX_RESULTS]]
        result = Ranking(total=len(found), rows=rows, sources=sources(found))
        if found and best < len(wanted):
            result.rows = [{**row, "partial_match": True} for row in rows]
        return result

    def rank_weapons(self, stat: str, descending: bool = True, category: str | None = None, kind: str | None = None,
                     max_mastery: int | None = None) -> Ranking:
        kind = normalize(kind or "")
        found = [weapon for weapon in self.weapons if stat in weapon
                 and (not category or weapon["category"] == category)
                 and (not kind or kind in normalize(weapon["type"]))
                 and (max_mastery is None or weapon.get("masteryReq", 0) <= max_mastery)]
        found.sort(key=lambda weapon: weapon["name"])
        found.sort(key=lambda weapon: weapon[stat], reverse=descending)
        rows = [{"name": weapon["name"], "category": weapon["category"], "type": weapon["type"],
                 "masteryReq": weapon.get("masteryReq"), stat: round(weapon[stat], 4)} for weapon in found[:MAX_RESULTS]]
        return Ranking(total=len(found), rows=rows, sources=sources(found))

    def rank_warframes(self, stat: str, descending: bool = True, kind: str | None = None) -> Ranking:
        kind = kind or FRAME_KINDS[0]
        found = [frame for frame in self.warframes if stat in frame and frame["kind"] == kind]
        found.sort(key=lambda frame: frame["name"])
        found.sort(key=lambda frame: frame[stat], reverse=descending)
        rows = [{"name": frame["name"], stat: round(frame[stat], 4)} for frame in found[:MAX_RESULTS]]
        return Ranking(total=len(found), rows=rows, sources=sources(found))


def sources(found: list[dict], limit: int = 5) -> list[tuple[str, str]]:
    """Pages du wiki officiel des premiers résultats."""
    return [(row["name"], row["wiki"]) for row in found[:limit] if row.get("wiki", "").startswith("https://wiki.warframe.com/")]
