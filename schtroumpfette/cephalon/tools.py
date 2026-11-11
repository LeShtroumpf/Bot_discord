"""Outils proposés à Claude et leur exécution.

La liste est fixe et dans un ordre fixe : elle fait partie du préfixe mis en cache par l'API.
"""
import json
from dataclasses import dataclass, field

from cephalon.warframe_api import WarframeApi


def tool(name: str, description: str, argument: str) -> dict:
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": argument}},
            "required": ["name"],
            "additionalProperties": False,
        },
    }


TOOLS = [
    tool("get_mod",
         "Fiche exacte d'un mod de Warframe : effet à chaque rang (levelStats, du rang 0 au rang max), polarité, "
         "coût, rareté. À appeler avant de donner la moindre valeur d'un mod. Si rien ne correspond, renvoie les "
         "noms approchants : réessaie avec l'un d'eux s'il s'agit visiblement du même mod.",
         "Nom du mod, en français ou en anglais, tel que le joueur l'a écrit."),
    tool("get_item",
         "Fiche exacte d'une Warframe, d'une arme ou d'un autre objet de Warframe : santé, bouclier, armure, "
         "énergie, pouvoirs, dégâts, critique, statut, composants, rang de maîtrise. À appeler avant de donner la "
         "moindre statistique. Si rien ne correspond, renvoie les noms approchants.",
         "Nom de l'objet, en français ou en anglais, tel que le joueur l'a écrit."),
    tool("get_drops",
         "Lieux où obtenir un objet ou un mod, avec le taux de drop (chance, en pourcentage). Le nom doit être le "
         "nom anglais exact : si le joueur donne un nom français, appelle d'abord get_mod ou get_item pour "
         "l'obtenir. `total` est le nombre de lieux trouvés, `drops` les plus intéressants.",
         "Nom anglais exact de l'objet ou du mod."),
]

LOOKUPS = {"get_mod": "mods", "get_item": "items"}


@dataclass
class Outcome:
    content: str
    is_error: bool = False
    sources: list[tuple[str, str]] = field(default_factory=list)


def dump(data) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


async def execute(api: WarframeApi, name: str, arguments) -> Outcome:
    """Exécute un outil. Une panne de l'API (WarframeApiError) remonte : la question s'arrête là."""
    query = arguments.get("name") if isinstance(arguments, dict) else None
    if not isinstance(query, str) or not query.strip():
        return Outcome("Erreur : le paramètre `name` est obligatoire.", is_error=True)
    if name in LOOKUPS:
        lookup = await api.find(LOOKUPS[name], query)
        if lookup.found:
            return Outcome(dump({"results": lookup.found}), sources=lookup.sources)
        return Outcome(dump({"results": [], "message": "Introuvable.", "similar_names": lookup.suggestions}))
    if name == "get_drops":
        return Outcome(dump(await api.drops(query)))
    return Outcome(f"Erreur : outil inconnu ({name}).", is_error=True)
