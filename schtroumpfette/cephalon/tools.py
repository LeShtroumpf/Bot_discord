"""Outils proposés à Claude et leur exécution.

La liste est fixe et dans un ordre fixe : elle fait partie du préfixe mis en cache par l'API.
"""
import json
from dataclasses import dataclass, field

from cephalon.index import FRAME_KINDS, FRAME_STATS, WEAPON_CATEGORIES, WEAPON_STATS
from cephalon.wikitext import INTRODUCTION
from cephalon.warframe_api import WarframeApi

ORDERS = ("desc", "asc")


def tool(name: str, description: str, properties: dict) -> dict:
    """Schéma strict : tous les paramètres sont obligatoires, un paramètre facultatif accepte `null`."""
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {"type": "object", "properties": properties, "required": list(properties),
                         "additionalProperties": False},
    }


def text(description: str) -> dict:
    return {"type": "string", "description": description}


def optional(schema: dict) -> dict:
    """Le même paramètre, ou `null`. (Un type en liste avec une énumération est refusé par l'API en mode strict.)"""
    value = {key: item for key, item in schema.items() if key != "description"}
    return {"anyOf": [value, {"type": "null"}], "description": schema["description"]}


def choice(values: tuple, description: str) -> dict:
    return {"type": "string", "enum": list(values), "description": description}


TOOLS = [
    tool("get_mod",
         "Fiche exacte d'un mod de Warframe : effet à chaque rang (levelStats, du rang 0 au rang max), polarité, "
         "coût, rareté. À appeler avant de donner la moindre valeur d'un mod. Le nom peut être mal orthographié : "
         "si rien ne correspond nettement, renvoie les noms approchants.",
         {"name": text("Nom du mod, en français ou en anglais, tel que le joueur l'a écrit.")}),
    tool("get_item",
         "Fiche exacte d'une Warframe, d'une arme ou d'un autre objet de Warframe : santé, bouclier, armure, "
         "énergie, pouvoirs, dégâts, critique, statut, composants, rang de maîtrise. À appeler avant de donner la "
         "moindre statistique. Le nom peut être mal orthographié : si rien ne correspond nettement, renvoie les "
         "noms approchants.",
         {"name": text("Nom de l'objet, en français ou en anglais, tel que le joueur l'a écrit.")}),
    tool("get_drops",
         "Lieux où obtenir un objet ou un mod, avec le taux de drop (chance, en pourcentage). Le nom doit être le "
         "nom anglais exact : si le joueur donne un nom français, appelle d'abord get_mod ou get_item pour "
         "l'obtenir. `total` est le nombre de lieux trouvés, `drops` les plus intéressants.",
         {"name": text("Nom anglais exact de l'objet ou du mod.")}),
    tool("search_mods",
         "Cherche des mods par leur effet, quand le joueur ne connaît pas le nom (« quel mod augmente la durée des "
         "pouvoirs ? »). Les effets sont en anglais : donne les mots tels qu'ils y figurent, par exemple Ability "
         "Duration, Ability Strength, Ability Range, Ability Efficiency, Critical Chance, Critical Damage, Status "
         "Chance, Multishot, Fire Rate, Reload Speed, Damage, Health, Shield, Armor, Energy, Sprint Speed, Heat, "
         "Cold, Toxin, Electricity, Slash, Impact, Puncture. Renvoie au plus 10 mods avec leur effet au rang max ; "
         "`total` est le nombre trouvé. `partial_match` signale que seuls certains mots-clés ont été trouvés.",
         {"keywords": {"type": "array", "items": {"type": "string"},
                       "description": "Mots-clés anglais de l'effet cherché, un terme du jeu par élément."},
          "type": optional(text("Type de mod ou d'équipement pour filtrer : Warframe, Rifle, Shotgun, Pistol, "
                                "Melee, Companion, Archwing… `null` pour tous."))}),
    tool("rank_weapons",
         "Classe les armes sur une statistique de base (« quelle arme primaire a la meilleure chance de "
         "critique ? »). criticalChance et procChance (chance de statut) sont des proportions (0.5 = 50 %). "
         "Renvoie les 10 premières ; `total` est le nombre d'armes qui correspondent aux filtres.",
         {"stat": choice(WEAPON_STATS, "Statistique du classement."),
          "order": choice(ORDERS, "desc : les plus élevées d'abord. asc : les plus basses (temps de rechargement, "
                                  "rang de maîtrise)."),
          "category": optional(choice(WEAPON_CATEGORIES, "Catégorie d'arme, ou `null` pour toutes.")),
          "type": optional(text("Type d'arme pour filtrer : Rifle, Shotgun, Bow, Sniper, Pistol, Melee… `null` pour "
                                "tous.")),
          "max_mastery": optional({"type": "integer", "description": "Rang de maîtrise maximum, ou `null`."})}),
    tool("rank_warframes",
         "Classe les Warframes sur une statistique de base (« quelle Warframe a le plus d'armure ? »). power est "
         "l'énergie. Les versions Prime et normales apparaissent toutes les deux. Renvoie les 10 premières.",
         {"stat": choice(FRAME_STATS, "Statistique du classement."),
          "order": choice(ORDERS, "desc : les plus élevées d'abord. asc : les plus basses."),
          "kind": optional(choice(FRAME_KINDS, "Warframe (défaut si `null`), Archwing ou Necramech."))}),
    tool("search_pages",
         "Cherche dans les pages du wiki gardées dans tes archives (mécaniques de jeu, lieux et conseils pour obtenir "
         "une ressource). Les pages sont en anglais : donne le titre anglais probable (Damage, Status Effect, Armor, "
         "Orokin Cell…) ou des mots-clés anglais. Cherche dans les titres de pages, puis de sections, puis dans le "
         "texte. Renvoie au plus 3 pages avec leur sommaire (`chars` = longueur de la section) ; `matching_sections` "
         "indique les sections où la recherche a trouvé quelque chose. Appelle ensuite read_section.",
         {"query": text("Titre de page ou mots-clés, en anglais.")}),
    tool("read_section",
         "Lit une section d'une page du wiki trouvée par search_pages (sous-sections comprises). Le texte est celui du "
         f"wiki, en anglais. `null` pour la section d'introduction ({INTRODUCTION}).",
         {"page": text("Titre exact de la page, tel que renvoyé par search_pages."),
          "section": optional(text("Titre exact de la section, tel que renvoyé par search_pages, ou `null`."))}),
]

# Analyse d'un build : fiches et recherche de mods seulement (liste fixe, préfixe du cache propre aux builds).
BUILD_TOOLS = [tool for tool in TOOLS if tool["name"] in ("get_mod", "get_item", "search_mods")]

LOOKUPS = {"get_mod": "mods", "get_item": "items"}
INDEX_NOT_READY = "Erreur : l'index de recherche n'est pas encore prêt. Dis au joueur de réessayer dans une minute."


@dataclass
class Outcome:
    content: str
    is_error: bool = False
    sources: list[tuple[str, str]] = field(default_factory=list)
    wiki: bool = False  # une page du wiki a été lue (licence à afficher)


class BadCall(Exception):
    """Paramètres d'outil invalides : renvoyés à Claude comme une erreur d'outil."""


def dump(data) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def string(arguments: dict, key: str, required: bool = True) -> str | None:
    value = arguments.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise BadCall(f"le paramètre `{key}` est obligatoire." if required else f"`{key}` doit être un texte ou null.")
    return value.strip()


def among(arguments: dict, key: str, values: tuple, required: bool = True) -> str | None:
    value = arguments.get(key)
    if value is None and not required:
        return None
    if value not in values:
        raise BadCall(f"`{key}` doit valoir l'une de ces valeurs : {', '.join(values)}.")
    return value


def ranking(result) -> Outcome:
    return Outcome(dump({"total": result.total, "results": result.rows}), sources=result.sources)


def search(api: WarframeApi, name: str, arguments: dict) -> Outcome:
    """Recherches et classements de l'index local."""
    if api.index is None:
        return Outcome(INDEX_NOT_READY, is_error=True)
    if name == "search_mods":
        keywords = arguments.get("keywords")
        if not isinstance(keywords, list) or not keywords or not all(isinstance(k, str) and k.strip() for k in keywords):
            raise BadCall("`keywords` doit être une liste non vide de mots-clés.")
        return ranking(api.index.search_mods(keywords, string(arguments, "type", required=False)))
    descending = among(arguments, "order", ORDERS) == "desc"
    if name == "rank_weapons":
        mastery = arguments.get("max_mastery")
        if mastery is not None and (type(mastery) is not int or mastery < 0):
            raise BadCall("`max_mastery` doit être un entier positif ou null.")
        return ranking(api.index.rank_weapons(among(arguments, "stat", WEAPON_STATS), descending,
                                              among(arguments, "category", WEAPON_CATEGORIES, required=False),
                                              string(arguments, "type", required=False), mastery))
    return ranking(api.index.rank_warframes(among(arguments, "stat", FRAME_STATS), descending,
                                            among(arguments, "kind", FRAME_KINDS, required=False)))


SEARCHES = ("search_mods", "rank_weapons", "rank_warframes")
PAGE_TOOLS = ("search_pages", "read_section")
NO_PAGES = "Aucune page du wiki n'est disponible dans tes archives."


def pages_tool(api: WarframeApi, name: str, arguments: dict) -> Outcome:
    """Pages choisies du wiki (cephalon/pages.py)."""
    pages = api.pages
    if name == "search_pages":
        query = string(arguments, "query")
        if not pages:
            return Outcome(dump({"results": [], "message": NO_PAGES}))
        results = pages.search(query)
        return Outcome(dump({"results": results} if results else {"results": [], "message": "Rien trouvé."}))
    page, section = string(arguments, "page"), string(arguments, "section", required=False)
    if not pages:
        return Outcome(dump({"error": NO_PAGES}), is_error=True)
    result, source = pages.read_section(page, section)
    if source is None:
        return Outcome(dump(result), is_error=True)
    return Outcome(dump(result), sources=[source], wiki=True)


async def execute(api: WarframeApi, name: str, arguments) -> Outcome:
    """Exécute un outil. Une panne de l'API (WarframeApiError) remonte : la question s'arrête là."""
    if not isinstance(arguments, dict):
        arguments = {}
    try:
        if name in SEARCHES:
            return search(api, name, arguments)
        if name in PAGE_TOOLS:
            return pages_tool(api, name, arguments)
        if name in LOOKUPS:
            lookup = await api.find(LOOKUPS[name], string(arguments, "name"))
            if lookup.found:
                return Outcome(dump({"results": lookup.found}), sources=lookup.sources)
            return Outcome(dump({"results": [], "message": "Introuvable.", "similar_names": lookup.suggestions}))
        if name == "get_drops":
            return Outcome(dump(await api.drops(string(arguments, "name"))))
    except BadCall as error:
        return Outcome(f"Erreur : {error}", is_error=True)
    return Outcome(f"Erreur : outil inconnu ({name}).", is_error=True)
