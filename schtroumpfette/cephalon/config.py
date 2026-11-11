"""Réglages du module : section `cephalon` de settings.json et constantes."""
from dataclasses import dataclass

from utils.file_management import settings_file_management

SETTINGS_KEY = "cephalon"
WARFRAME_KEY = "warframe"  # le salon autorisé est celui des commandes Warframe

MAX_TOOL_ROUNDS = 5        # appels à Claude par question, au plus
API_CACHE_TTL = 6 * 3600   # secondes : les données de warframestat ne changent qu'aux mises à jour du jeu
API_CACHE_SIZE = 500       # réponses gardées en mémoire, au plus
API_TIMEOUT = 10           # secondes par requête warframestat
LLM_TIMEOUT = 60           # secondes par requête à l'API Anthropic
LLM_RETRIES = 2            # nouveaux essais du SDK (429, 5xx, réseau)

EFFORTS = ("low", "medium", "high")


@dataclass(frozen=True)
class Config:
    model: str = "claude-haiku-5-5"
    max_tokens: int = 2000  # réflexion du modèle + réponse
    effort: str = "low"     # profondeur de réflexion, donc coût


def read_section(key: str) -> dict:
    try:
        section = settings_file_management.get_entry(main_key=key)
    except (KeyError, TypeError):
        return {}
    return section if isinstance(section, dict) else {}


def read_config() -> Config:
    """Section lue à chaque question. Valeur absente ou invalide = valeur par défaut."""
    section, default = read_section(SETTINGS_KEY), Config()
    model, max_tokens, effort = section.get("model"), section.get("max_tokens"), section.get("effort")
    return Config(
        model=model.strip() if isinstance(model, str) and model.strip() else default.model,
        max_tokens=max_tokens if type(max_tokens) is int and max_tokens > 0 else default.max_tokens,
        effort=effort if effort in EFFORTS else default.effort,
    )


def command_channel() -> int | None:
    """Salon des commandes Warframe, ou None si le module Warframe n'est pas configuré."""
    channel = str(read_section(WARFRAME_KEY).get("command_channel") or "")
    return int(channel) if channel.isdigit() else None
