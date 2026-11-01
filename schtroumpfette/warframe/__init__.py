"""Module Warframe : état du monde du jeu (worldstate) affiché sur Discord.

Module indépendant : le cog `commands.warframe` est le seul point d'entrée.
"""
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
DATA_DIR = MODULE_DIR / "data"
CACHE_DIR = MODULE_DIR / "cache"
