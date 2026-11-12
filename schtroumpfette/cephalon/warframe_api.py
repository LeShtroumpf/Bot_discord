"""Client de l'API warframestat.us : mods, objets et drops.

Résolution d'un nom : toujours par `/search/`. `GET /mods/{nom}` ne renvoie qu'un résultat approché, et parfois le
mauvais (`Continuity` donne le mod Défectueux à +12 % au lieu du vrai à +30 %, les deux portant le même nom).
"""
import asyncio
import re
import time
from dataclasses import dataclass, field
from urllib.parse import quote

import aiohttp

from cephalon.config import API_CACHE_SIZE, API_CACHE_TTL, API_TIMEOUT, INDEX_TIMEOUT
from cephalon.index import FLAWED_PATH, LISTS, MAX_MATCHES, Index

BASE_URL = "https://api.warframestat.us"
HEADERS = {"User-Agent": "Schtroumpfette-Discord-Bot"}
TIMEOUT = aiohttp.ClientTimeout(total=API_TIMEOUT)
LIST_TIMEOUT = aiohttp.ClientTimeout(total=INDEX_TIMEOUT)
WIKI_URL = "https://wiki.warframe.com/"

KINDS = ("mods", "items")
MAX_SUGGESTIONS = 10  # noms approchants proposés quand rien ne correspond
MAX_DROPS = 15

# Champs transmis à Claude : pas d'images, d'identifiants internes ni de drops de composants.
KEPT = (
    "name", "type", "category", "description",
    # mods
    "compatName", "polarity", "rarity", "baseDrain", "fusionLimit", "tradable", "transmutable",  # isAugment : faux dans l'API
    # frames
    "health", "shield", "armor", "power", "sprintSpeed", "masteryReq", "passiveDescription", "aura", "polarities",
    # armes
    "totalDamage", "criticalChance", "criticalMultiplier", "procChance", "fireRate", "magazineSize", "reloadTime",
    "multishot", "trigger", "noise", "accuracy", "disposition",
    "isPrime", "vaulted",
)
ATTACK_KEPT = ("name", "speed", "crit_chance", "crit_mult", "status_chance", "shot_type")
# Champs demandés à l'API (`only`) : ceux qu'on garde, plus ceux qu'on transforme ou qui servent en interne.
REQUESTED = ",".join(KEPT + ("uniqueName", "wikiaUrl", "levelStats", "abilities", "components", "damage", "attacks"))

FRENCH_TEXTS = "name,description,passiveDescription,abilities"  # textes du jeu en français, quand l'API les a
MARKUP = re.compile(r"<[A-Z_]+>")  # balises de couleur du jeu : <DT_POISON_COLOR>


class WarframeApiError(Exception):
    """API injoignable ou réponse invalide."""


@dataclass
class Lookup:
    """Résultat d'une recherche : fiches trouvées, sinon noms approchants. sources = (nom, page du wiki)."""
    found: list[dict] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    sources: list[tuple[str, str]] = field(default_factory=list)


def clean(text: str) -> str:
    return MARKUP.sub("", text).strip()


def nonzero(values: dict) -> dict:
    return {key: value for key, value in values.items() if value}


def simplify(item: dict) -> dict:
    """Fiche réduite aux champs utiles à une réponse."""
    out = {key: item[key] for key in KEPT if item.get(key) not in (None, "", [])}
    for key in ("description", "passiveDescription"):
        if key in out:
            out[key] = clean(out[key])
    if item.get("category") == "Mods":
        out.pop("isPrime", None)  # faux même pour un mod « Primed » : le modèle en déduisait une autre version
    if FLAWED_PATH in item.get("uniqueName", ""):
        out["flawed"] = True
    if item.get("levelStats"):  # un texte par rang, numéroté : sans numéro, le modèle prend le premier pour le rang 1
        out["levelStats"] = [f"rank {rank}: " + " / ".join(clean(stat) for stat in level.get("stats", []))
                             for rank, level in enumerate(item["levelStats"])]
    if item.get("abilities"):
        out["abilities"] = [{"name": a.get("name"), "description": clean(a.get("description", ""))} for a in item["abilities"]]
    if item.get("components"):
        out["components"] = [{"name": c.get("name"), "count": c.get("itemCount", 1)} for c in item["components"]]
    if isinstance(item.get("damage"), dict) and nonzero(item["damage"]):
        out["damage"] = nonzero(item["damage"])
    if item.get("attacks"):
        out["attacks"] = [{**{key: attack[key] for key in ATTACK_KEPT if key in attack},
                           "damage": nonzero(attack.get("damage") or {})} for attack in item["attacks"]]
    return out


def source(item: dict) -> tuple[str, str] | None:
    """Page du wiki officiel de l'objet, s'il en a une."""
    url = item.get("wikiaUrl") or ""
    if not url.startswith(WIKI_URL):
        return None
    label = item.get("name", "Wiki")
    return (f"{label} (Défectueux)" if FLAWED_PATH in item.get("uniqueName", "") else label, url)


def names(items: list[dict]) -> list[str]:
    return [item["name"] for item in items if item.get("name")]


class WarframeApi:
    def __init__(self, session: aiohttp.ClientSession, clock=time.monotonic):
        self.session = session
        self.clock = clock
        self.cache: dict[tuple, tuple[float, object]] = {}  # (chemin, paramètres) -> (expiration, réponse)
        self.index: Index | None = None  # index local (cephalon/index.py), posé par le cog quand il est prêt
        self.pages = None                # pages choisies du wiki (cephalon/pages.py), posées par le cog

    async def get(self, path: str, expected: type, timeout: aiohttp.ClientTimeout, **params: str):
        """Réponse JSON du type attendu. 404 = None. Erreur ou réponse d'une autre forme : WarframeApiError."""
        try:
            async with self.session.get(f"{BASE_URL}{path}", params=params, headers=HEADERS, timeout=timeout) as response:
                if response.status == 404:
                    data = None
                else:
                    response.raise_for_status()
                    data = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as error:
            raise WarframeApiError(f"{path} : {str(error) or type(error).__name__}") from error
        if data is not None and not isinstance(data, expected):
            raise WarframeApiError(f"{path} : réponse inattendue")
        return data

    async def download_lists(self) -> dict[str, list]:
        """Les listes complètes dont l'index a besoin, l'une après l'autre, sans le cache (plusieurs Mo)."""
        lists = {}
        for name, (path, params) in LISTS.items():
            lists[name] = await self.get(path, list, LIST_TIMEOUT, **params) or []
        return lists

    async def fetch(self, path: str, expected: type, **params: str):
        """Réponse JSON du type attendu, depuis le cache si elle a moins de API_CACHE_TTL. 404 = None.

        Une erreur ou une réponse d'une autre forme lève WarframeApiError et n'est pas gardée en cache."""
        key = (path, tuple(sorted(params.items())))
        cached = self.cache.get(key)
        if cached and cached[0] > self.clock():
            return cached[1]
        data = await self.get(path, expected, TIMEOUT, **params)
        self.cache.pop(key, None)
        if len(self.cache) >= API_CACHE_SIZE:
            del self.cache[next(iter(self.cache))]  # la plus ancienne
        self.cache[key] = (self.clock() + API_CACHE_TTL, data)
        return data

    async def search(self, kind: str, name: str, **params: str) -> list[dict]:
        data = await self.fetch(f"/{kind}/search/{quote(name, safe='')}", list, only=REQUESTED, **params)
        return [item for item in data or [] if isinstance(item, dict)]

    async def fiche(self, kind: str, item: dict, only: str, **params: str) -> dict:
        """Fiche du même objet dans une autre langue, par son identifiant. {} si l'API ne la confirme pas."""
        unique = item.get("uniqueName")
        if not unique:
            return {}
        data = await self.fetch(f"/{kind}/{quote(unique, safe='')}", dict, by="uniqueName", only=f"uniqueName,{only}", **params)
        # La recherche de l'API est approchée : on ne garde la fiche que si c'est bien le même objet.
        return data if data and data.get("uniqueName") == unique else {}

    async def find(self, kind: str, name: str) -> Lookup:
        """Fiches dont le nom est exactement `name`, en anglais puis en français. Sinon, les noms approchants.

        Une fiche porte le nom anglais (`name`, celui des drops et du wiki), le nom français (`name_fr`) s'il diffère,
        les chiffres de l'API et les textes français du jeu quand l'API les fournit."""
        if kind not in KINDS:
            raise ValueError(f"type inconnu : {kind}")
        name = name.strip()
        if self.index:
            lookup = await self.find_indexed(kind, name)
            if lookup:
                return lookup
        wanted = name.casefold()
        english = await self.search(kind, name)
        exact = self.exact(english, wanted)
        if exact:
            french = await asyncio.gather(*(self.fiche(kind, item, FRENCH_TEXTS, language="fr") for item in exact))
            return self.lookup([(item, item.get("name"), fiche) for item, fiche in zip(exact, french)])
        french = await self.search(kind, name, language="fr")
        exact = self.exact(french, wanted)
        if exact:
            names_en = await asyncio.gather(*(self.fiche(kind, item, "name") for item in exact))
            return self.lookup([(item, fiche.get("name") or item["name"], item) for item, fiche in zip(exact, names_en)])
        suggestions = list(dict.fromkeys(names(french) + names(english)))[:MAX_SUGGESTIONS]
        return Lookup(suggestions=suggestions)

    async def find_indexed(self, kind: str, name: str) -> Lookup | None:
        """Le nom passé par l'index local (accents, fautes de frappe), les fiches par leur identifiant.

        None quand l'index ne tranche pas ou qu'une fiche ne se confirme pas : la recherche en direct prend le relais."""
        resolution = await asyncio.to_thread(self.index.resolve, kind, name)  # difflib sur des milliers de noms
        if resolution.candidates:
            return Lookup(suggestions=resolution.candidates)
        if not resolution.matches:
            return None
        english = await asyncio.gather(*(self.fiche(kind, {"uniqueName": entry["unique"]}, REQUESTED)
                                         for entry in resolution.matches))
        if not all(english):
            return None
        french = await asyncio.gather(*(self.fiche(kind, item, FRENCH_TEXTS, language="fr") for item in english))
        return self.lookup([(item, item.get("name"), fiche) for item, fiche in zip(english, french)])

    @staticmethod
    def exact(items: list[dict], wanted: str) -> list[dict]:
        """Objets au nom exact, la version normale avant la Défectueuse."""
        matches = [item for item in items if item.get("name", "").casefold() == wanted]
        return sorted(matches, key=lambda item: FLAWED_PATH in item.get("uniqueName", ""))[:MAX_MATCHES]

    @staticmethod
    def lookup(matches: list[tuple[dict, str, dict]]) -> Lookup:
        """matches : (fiche avec les chiffres, nom anglais, fiche française ou {})."""
        result = Lookup()
        for item, name, french in matches:
            texts = {key: french[key] for key in ("description", "passiveDescription", "abilities") if french.get(key)}
            fiche = {**simplify({**item, **texts}), "name": name}
            if french.get("name") and french["name"] != name:
                fiche["name_fr"] = french["name"]
            result.found.append(fiche)
            link = source({**item, "name": name})
            if link:
                result.sources.append(link)
        return result

    async def drops(self, name: str) -> dict:
        """Lieux de drop d'un objet (nom anglais) : l'objet exact d'abord, puis par chance décroissante."""
        name = name.strip()
        data = await self.fetch(f"/drops/search/{quote(name, safe='')}", list)
        rows = [row for row in data or [] if isinstance(row, dict)]
        rows.sort(key=lambda row: (str(row.get("item", "")).casefold() != name.casefold(), -(row.get("chance") or 0)))
        kept = [{key: row[key] for key in ("item", "place", "rarity", "chance") if key in row} for row in rows[:MAX_DROPS]]
        return {"total": len(rows), "drops": kept}
