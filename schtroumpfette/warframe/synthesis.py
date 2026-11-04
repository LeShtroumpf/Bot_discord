"""Cibles de synthèse de Cephalon Simaris : où les trouver.

Les cibles et leurs lieux viennent du wiki officiel (Module:Synthesis/data, CC BY-NC-SA 3.0), rechargé tous les
7 jours et gardé en cache disque. Les commandes ne lisent que la mémoire : aucune requête pendant une recherche.
Le wiki donne les noms en anglais ; les noms français viennent du Translator.
"""
import datetime as dt
import difflib
import re
import unicodedata
from pathlib import Path

import aiohttp

from .translations import Translator

WIKI_URL = "https://wiki.warframe.com/w/Module:Synthesis/data?action=raw"
WIKI_HEADERS = {"User-Agent": "Schtroumpfette-Discord-Bot"}
WIKI_TIMEOUT = aiohttp.ClientTimeout(total=30)
MAX_AGE = dt.timedelta(days=7)
CACHE_FILE = "synthesis.lua"
MIN_TARGETS = 20   # en dessous, le format du wiki a sûrement changé : on garde les données qu'on a
MAX_CHOICES = 25   # limite Discord de l'autocomplétion
MAX_SUGGESTIONS = 3
ENTRY = re.compile(r'^\t\["([^"]+)"\]\s*=\s*\{(.*?)^\t\},?', re.S | re.M)
LOCATIONS = re.compile(r"\bLocations\s*=\s*\{(.*?)\}", re.S)
IGNORED = re.compile(r"\b_IgnoreEntry\s*=\s*true\b")
COMMENT = re.compile(r"--.*")


class SynthesisError(Exception):
    """Wiki injoignable ou format du module inattendu."""


def parse(text: str, minimum: int = MIN_TARGETS) -> dict[str, tuple[str, ...]]:
    """Module Lua du wiki -> {nom anglais de la cible: lieux}."""
    targets = {}
    for name, body in ENTRY.findall(text):
        body = COMMENT.sub("", body)
        locations = LOCATIONS.search(body)
        if IGNORED.search(body) or not locations:
            continue
        places = tuple(place.strip() for place in re.findall(r'"([^"]+)"', locations.group(1)) if place.strip())
        if places:
            targets[name] = places
    if len(targets) < minimum:
        raise SynthesisError(f"format inattendu : {len(targets)} cibles lues")
    return targets


def read_cache(cache_dir: Path) -> tuple[dict[str, tuple[str, ...]], dt.datetime] | None:
    path = cache_dir / CACHE_FILE
    try:
        targets = parse(path.read_text(encoding="utf-8"))
        return targets, dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.UTC)
    except (OSError, SynthesisError):
        return None


async def download(session: aiohttp.ClientSession, cache_dir: Path) -> dict[str, tuple[str, ...]]:
    """Télécharge le module ; le cache n'est remplacé qu'une fois le contenu validé."""
    try:
        async with session.get(WIKI_URL, headers=WIKI_HEADERS, timeout=WIKI_TIMEOUT) as response:
            response.raise_for_status()
            text = await response.text()
    except (aiohttp.ClientError, TimeoutError) as error:
        raise SynthesisError(f"{type(error).__name__}: {error}") from error
    targets = parse(text)
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = cache_dir / (CACHE_FILE + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(cache_dir / CACHE_FILE)
    return targets


def normalize(text: str) -> str:
    """Pour comparer : sans accents, sans casse, ponctuation réduite à des espaces ("Homme d'Équipage" -> "homme d equipage")."""
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(char for char in decomposed if not unicodedata.combining(char)).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", plain).split())


def label(tr: Translator, name: str) -> str:
    """"Lancier (Lancer)", ou le nom seul s'il est identique dans les deux langues ou sans traduction."""
    french = tr.enemy(name)
    return f"{french} ({name})" if french and normalize(french) != normalize(name) else name


def search(targets: dict, tr: Translator, query: str, limit: int = MAX_CHOICES) -> list[str]:
    """Noms anglais des cibles dont le nom FR ou EN contient la recherche : nom exact, puis début de nom, puis le reste."""
    wanted = normalize(query)
    found = []
    for name in targets:
        french = normalize(tr.enemy(name) or name)
        names = (normalize(name), french)
        if any(wanted in candidate for candidate in names):
            rank = 0 if wanted in names else 1 if any(candidate.startswith(wanted) for candidate in names) else 2
            found.append((rank, french, name))
    return [name for _, _, name in sorted(found)][:limit]


def find(targets: dict, tr: Translator, query: str) -> str | None:
    """Nom anglais de la cible désignée exactement par son nom FR, son nom EN ou son libellé."""
    wanted = normalize(query)
    for name in targets:
        if wanted in (normalize(name), normalize(tr.enemy(name) or name), normalize(label(tr, name))):
            return name
    return None


def suggest(targets: dict, tr: Translator, query: str, limit: int = MAX_SUGGESTIONS) -> list[str]:
    """Libellés des cibles les plus proches d'une recherche sans résultat exact."""
    names = search(targets, tr, query, limit)
    if not names:
        candidates = {}
        for name in targets:
            candidates[normalize(name)] = name
            candidates[normalize(tr.enemy(name) or name)] = name
        closest = difflib.get_close_matches(normalize(query), candidates, n=limit * 2, cutoff=0.6)
        names = list(dict.fromkeys(candidates[match] for match in closest))[:limit]
    return [label(tr, name) for name in names]
