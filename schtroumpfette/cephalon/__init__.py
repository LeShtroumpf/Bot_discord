"""Module Cephalon : la Cephalon Schtroumpfette répond aux questions sur Warframe.

Module indépendant : le cog `commands.cephalon` est le seul point d'entrée.
Principe : tout chiffre d'une réponse vient d'un résultat d'outil (API warframestat), jamais de la mémoire du modèle.
"""
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
STATE_DIR = MODULE_DIR / "state"  # compteurs d'usage (ignoré par git, monté en volume en prod)
