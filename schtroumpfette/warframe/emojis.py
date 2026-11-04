"""Emojis de tier des arbitrages et de faction des invasions, gérés par le bot comme emojis d'application.

Les images sont dans warframe/data/emojis/ (tier<TIER>.png, faction<NOM>.png). Chaque bot (test, prod) crée ses propres emojis au
démarrage et les retrouve par leur nom : aucun identifiant à recopier. Le nom contient une empreinte de l'image
("tierS_3fa2b1c4") : remplacer un PNG crée un nouvel emoji et supprime l'ancien.
"""
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import DATA_DIR

EMOJI_DIR = DATA_DIR / "emojis"
TIERS = ("S", "A", "B", "C", "D", "SP", "F")
FACTIONS = {"FC_CORPUS": "factionCorpus", "FC_GRINEER": "factionGrineer"}  # faction du worldstate -> nom de l'image
STEMS = {**{tier: f"tier{tier}" for tier in TIERS}, **FACTIONS}            # clé -> nom de l'image, sans extension
MAX_SIZE = 256 * 1024  # limite Discord pour un emoji
MANAGED_NAME = re.compile(r"^(tier(S|A|B|C|D|SP|F)|faction(Corpus|Grineer))_[0-9a-f]{8}$")


def emoji_name(key: str, image: bytes) -> str:
    return f"{STEMS[key]}_{hashlib.sha1(image).hexdigest()[:8]}"


def load_images(directory: Path = EMOJI_DIR) -> dict[str, bytes]:
    """Images présentes (clé -> PNG). Une clé sans fichier garde son emoji par défaut."""
    images = {}
    for key, stem in STEMS.items():
        path = directory / f"{stem}.png"
        if path.is_file():
            data = path.read_bytes()
            if len(data) > MAX_SIZE:
                raise ValueError(f"{path.name} dépasse 256 Ko")
            images[key] = data
    return images


@dataclass
class Plan:
    keep: dict[str, object] = field(default_factory=dict)              # clé -> emoji existant à jour
    create: dict[str, tuple[str, bytes]] = field(default_factory=dict)  # clé -> (nom, image)
    delete: list = field(default_factory=list)                          # emojis gérés devenus inutiles


def plan(existing: list, images: dict[str, bytes]) -> Plan:
    """Compare les emojis de l'application aux images du dépôt. Ne touche qu'aux emojis gérés (MANAGED_NAME)."""
    by_name = {emoji.name: emoji for emoji in existing}
    result = Plan()
    for key, image in images.items():
        name = emoji_name(key, image)
        if name in by_name:
            result.keep[key] = by_name[name]
        else:
            result.create[key] = (name, image)
    wanted = {emoji_name(key, image) for key, image in images.items()}
    result.delete = [emoji for emoji in existing if MANAGED_NAME.match(emoji.name) and emoji.name not in wanted]
    return result


async def sync_emojis(client, directory: Path = EMOJI_DIR) -> dict[str, str]:
    """Met les emojis d'application en accord avec les images, puis renvoie clé -> "<:nom:id>".

    Les anciens emojis ne sont supprimés qu'après la création des nouveaux.
    """
    images = load_images(directory)
    if not images:
        return {}
    todo = plan(await client.fetch_application_emojis(), images)
    emojis = dict(todo.keep)
    for key, (name, image) in todo.create.items():
        emojis[key] = await client.create_application_emoji(name=name, image=image)
    for emoji in todo.delete:
        await emoji.delete()
    return {key: str(emoji) for key, emoji in emojis.items()}
