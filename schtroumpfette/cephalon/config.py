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
    cooldown: float = 30           # secondes entre deux questions d'un même joueur
    daily_questions: int = 20      # questions répondues par joueur et par jour
    monthly_budget: float = 4      # euros par mois, tous joueurs confondus (coût estimé)
    usd_to_eur: float = 0.9        # conversion du coût estimé, à ajuster au cours du moment


def read_section(key: str) -> dict:
    try:
        section = settings_file_management.get_entry(main_key=key)
    except (KeyError, TypeError):
        return {}
    return section if isinstance(section, dict) else {}


def positive(value, default, integer: bool = False):
    """Une limite ne se coupe pas par accident : valeur absente, non numérique, nulle ou négative = défaut."""
    if isinstance(value, bool) or not isinstance(value, int if integer else (int, float)) or value <= 0:
        return default
    return value


def read_config() -> Config:
    """Section lue à chaque question. Valeur absente ou invalide = valeur par défaut."""
    section, default = read_section(SETTINGS_KEY), Config()
    model, max_tokens, effort = section.get("model"), section.get("max_tokens"), section.get("effort")
    return Config(
        model=model.strip() if isinstance(model, str) and model.strip() else default.model,
        max_tokens=max_tokens if type(max_tokens) is int and max_tokens > 0 else default.max_tokens,
        effort=effort if effort in EFFORTS else default.effort,
        cooldown=positive(section.get("cooldown"), default.cooldown),
        daily_questions=positive(section.get("daily_questions"), default.daily_questions, integer=True),
        monthly_budget=positive(section.get("monthly_budget"), default.monthly_budget),
        usd_to_eur=positive(section.get("usd_to_eur"), default.usd_to_eur),
    )


def command_channel() -> int | None:
    """Salon des commandes Warframe, ou None si le module Warframe n'est pas configuré."""
    channel = str(read_section(WARFRAME_KEY).get("command_channel") or "")
    return int(channel) if channel.isdigit() else None
