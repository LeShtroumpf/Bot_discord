"""Limites d'usage de /cephalon : cooldown par joueur, quota quotidien par joueur, plafond mensuel global.

Le coût est une estimation (tokens × prix du modèle) : le bot ne lit pas la facture. Les compteurs du jour et du mois
vivent dans un fichier dédié, pas dans settings.json : une écriture ratée ne peut pas abîmer la config du bot.
"""
import datetime as dt
import json
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

from cephalon.config import Config

PARIS = ZoneInfo("Europe/Paris")  # le quota repart à minuit, le plafond le 1er du mois, heure de Paris
STATE_FILE = "usage.json"
ALERTS = (80, 100)                # seuils du plafond mensuel signalés dans le salon de logs, en pourcentage
MAX_COOLDOWNS = 1000              # joueurs suivis en mémoire avant de purger les cooldowns expirés

# Dollars par million de tokens : entrée, sortie, écriture de cache (5 min), lecture de cache.
# Source : https://platform.claude.com/docs/en/about-claude/pricing (relevé le 2026-11-11). À mettre à jour si les
# tarifs changent ou si un autre modèle est configuré. Haiku : tarif des prompts de moins de 100 000 tokens.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50, 0.125, 0.01),
    "claude-sonnet-5-5": (2.0, 10.0, 2.50, 0.10),
    "claude-opus-5-5": (4.0, 20.0, 5.0, 0.20),
    "claude-fable-5-2": (8.0, 40.0, 10.0, 0.20),
}
# Modèle absent de la table : on surestime plutôt que de dépasser le budget.
HIGHEST = tuple(max(price[index] for price in PRICES.values()) for index in range(4))

BUDGET, QUOTA, COOLDOWN = "budget", "quota", "cooldown"


class StateError(Exception):
    """Fichier d'état illisible ou d'une forme inattendue."""


@dataclass
class Refusal:
    kind: str         # BUDGET, QUOTA ou COOLDOWN
    seconds: int = 0  # attente restante, pour un cooldown


@dataclass
class Outcome:
    remaining: int                 # questions que le joueur peut encore poser aujourd'hui
    spent: float                   # coût estimé du mois, en euros
    alerts: list[int] = field(default_factory=list)  # seuils franchis par cette question
    unknown_model: bool = False    # prix absent de PRICES : coût compté au tarif le plus cher


def cost(model: str, usage) -> tuple[float, bool]:
    """Coût estimé d'un usage, en dollars, et si le prix du modèle est connu."""
    prices = PRICES.get(model)
    price_in, price_out, price_write, price_read = prices or HIGHEST
    dollars = (usage.input * price_in + usage.output * price_out
               + usage.cache_write * price_write + usage.cache_read * price_read) / 1_000_000
    return dollars, prices is not None


def empty_state() -> dict:
    return {"month": "", "cost_usd": 0.0, "alerts": [], "day": "", "questions": {}}


def valid_state(data) -> dict:
    """L'état lu sur disque, ou StateError s'il n'a pas la forme attendue."""
    number = (int, float)
    if not (isinstance(data, dict) and isinstance(data.get("month"), str) and isinstance(data.get("day"), str)
            and isinstance(data.get("cost_usd"), number) and not isinstance(data.get("cost_usd"), bool)
            and isinstance(data.get("alerts"), list) and isinstance(data.get("questions"), dict)
            and all(type(count) is int for count in data["questions"].values())):
        raise StateError("état des limites d'une forme inattendue")
    return {"month": data["month"], "cost_usd": float(data["cost_usd"]), "alerts": [a for a in data["alerts"] if a in ALERTS],
            "day": data["day"], "questions": {str(user): count for user, count in data["questions"].items()}}


class Limits:
    def __init__(self, directory: Path, clock=time.monotonic):
        self.path = Path(directory) / STATE_FILE
        self.clock = clock
        self.state = empty_state()
        self.cooldowns: dict[int, float] = {}  # joueur -> instant de sa dernière question acceptée (en mémoire)

    # --- Persistance (appels bloquants : à lancer dans un thread) -----------------------------------------

    def load(self) -> None:
        """Relit les compteurs. Fichier absent = premier lancement ; illisible = StateError, compteurs à zéro."""
        self.state = empty_state()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as error:
            raise StateError(f"état des limites illisible : {error}") from error
        self.state = valid_state(data)

    def save(self) -> None:
        """Écriture atomique : un fichier temporaire, puis un renommage."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=4), encoding="utf-8")
        os.replace(tmp, self.path)

    # --- Limites ------------------------------------------------------------------------------------------

    def roll(self, now: dt.datetime) -> None:
        """Remet les compteurs à zéro au changement de jour ou de mois (heure de Paris)."""
        today = now.astimezone(PARIS).date()
        day, month = today.isoformat(), today.strftime("%Y-%m")
        if self.state["day"] != day:
            self.state["day"], self.state["questions"] = day, {}
        if self.state["month"] != month:
            self.state["month"], self.state["cost_usd"], self.state["alerts"] = month, 0.0, []

    def spent(self, config: Config) -> float:
        """Coût estimé du mois, en euros."""
        return self.state["cost_usd"] * config.usd_to_eur

    def check(self, user_id: int, config: Config, now: dt.datetime) -> Refusal | None:
        """None si le joueur peut poser sa question (son cooldown démarre), sinon le refus le plus durable."""
        self.roll(now)
        if self.spent(config) >= config.monthly_budget:
            return Refusal(BUDGET)
        if self.state["questions"].get(str(user_id), 0) >= config.daily_questions:
            return Refusal(QUOTA)
        instant, last = self.clock(), self.cooldowns.get(user_id)
        if last is not None and instant - last < config.cooldown:
            return Refusal(COOLDOWN, seconds=math.ceil(config.cooldown - (instant - last)))
        if len(self.cooldowns) >= MAX_COOLDOWNS:
            self.cooldowns = {user: at for user, at in self.cooldowns.items() if instant - at < config.cooldown}
        self.cooldowns[user_id] = instant
        return None

    def record(self, user_id: int, model: str, usage, answered: bool, config: Config, now: dt.datetime) -> Outcome:
        """Ajoute le coût de la question au mois et, si elle a reçu une réponse, la compte dans le quota du joueur."""
        self.roll(now)
        dollars, known = cost(model, usage)
        self.state["cost_usd"] += dollars
        questions = self.state["questions"]
        if answered:
            questions[str(user_id)] = questions.get(str(user_id), 0) + 1
        spent = self.spent(config)
        percent = spent / config.monthly_budget * 100
        alerts = [threshold for threshold in ALERTS if percent >= threshold and threshold not in self.state["alerts"]]
        self.state["alerts"].extend(alerts)
        remaining = max(0, config.daily_questions - questions.get(str(user_id), 0))
        return Outcome(remaining=remaining, spent=spent, alerts=alerts, unknown_model=not known)
