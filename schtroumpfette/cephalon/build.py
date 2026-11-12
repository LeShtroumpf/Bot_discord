"""/cephalon_build : lecture d'une capture (JSON imposé), vérification de chaque carte par le code, charge de l'analyse.

Principe : chaque mod lu est vérifié par le code (index local + API) avant que Claude n'écrive une ligne.
"""
import asyncio
import json
import math
from dataclasses import dataclass, field

from cephalon.config import READER_EFFORT, READER_MAX_TOKENS, Config
from cephalon.image import PreparedImage
from cephalon.llm import Profile, Usage, system_blocks
from cephalon.persona import BUILD_PROMPT, BUILD_READER_PROMPT, BUILD_READER_REQUEST
from cephalon.tools import BUILD_TOOLS, dump
from cephalon.warframe_api import WarframeApi

SLOTS = ("aura", "exilus", "normal", "stance", "arcane", "archon_shard")
KINDS = ("mod", "riven", "arcane", "archon_shard")
EQUIPMENT = ("warframe", "primary", "secondary", "melee", "companion", "archwing", "necramech", "other")
FAMILIES = {"mod": "mods", "arcane": "items"}  # cartes vérifiées par le code, et où les chercher
MAX_SLOTS = 20                                  # au-delà, la lecture est jugée aberrante
MAX_DRAIN = 30                                  # aucun mod ne coûte plus : au-delà, coût mal lu (symbole pris pour un chiffre)

VERIFIED, UNCERTAIN, UNKNOWN, RIVEN, NOT_CHECKED = "verified", "uncertain", "unknown", "riven", "not_checked"


def nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def strict_object(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


INTEGER, TEXT = {"type": "integer"}, {"type": "string"}
READER_SCHEMA = strict_object({
    "is_build": {"type": "boolean"},
    "equipment_kind": {"type": "string", "enum": list(EQUIPMENT)},
    "equipment_name": nullable(TEXT),
    "capacity": nullable(strict_object({"remaining": nullable(INTEGER), "total": nullable(INTEGER)})),
    "displayed_stats": {"type": "array", "items": strict_object({"name": TEXT, "value": TEXT})},
    "slots": {"type": "array", "items": strict_object({
        "slot": {"type": "string", "enum": list(SLOTS)},
        "kind": {"type": "string", "enum": list(KINDS)},
        "name": nullable(TEXT),
        "readable": {"type": "boolean"},
        "drain": nullable(INTEGER),
        "rank": nullable(INTEGER),
        "max_rank": nullable(INTEGER),
        "polarity": nullable(TEXT),
    })},
})


class BuildError(Exception):
    """Lecture inexploitable (refus du modèle, réponse coupée ou d'une forme inattendue)."""


@dataclass
class Checked:
    """Une carte lue puis vérifiée."""
    read: dict
    status: str
    card: dict | None = None
    candidates: list[str] = field(default_factory=list)
    sources: list[tuple[str, str]] = field(default_factory=list)
    rank: int | None = None          # rang retenu
    rank_from_drain: bool = False    # déduit du coût affiché (rang lu absent ou incompatible)


def drain_ranks(card: dict, drain: int, aura: bool) -> set[int]:
    """Rangs compatibles avec le coût affiché : coût de base + rang, divisé par deux (arrondi au-dessus) si la polarité
    correspond, majoré d'un quart sinon ; une aura ajoute de la capacité (doublée si la polarité correspond)."""
    base, top = card.get("baseDrain"), card.get("fusionLimit")
    if not isinstance(base, int) or not isinstance(top, int) or drain is None:
        return set()
    ranks = set()
    for rank in range(top + 1):
        raw = abs(base) + rank
        shown = {raw, raw * 2, math.floor(raw * 0.75), math.ceil(raw * 0.75)} if aura else \
            {raw, math.ceil(raw / 2), math.floor(raw * 1.25), math.ceil(raw * 1.25)}
        if drain in shown:
            ranks.add(rank)
    return ranks


def settle_rank(checked: "Checked") -> None:
    """Le rang lu aux points allumés est peu fiable, le coût affiché l'est. Rang max s'il colle au coût (cas courant :
    un build monté), sinon le rang lu s'il colle, sinon le plus haut rang compatible ; coût illisible = rang lu."""
    read = checked.read.get("rank")
    checked.rank = read if isinstance(read, int) and not isinstance(read, bool) else None
    if checked.card is None:
        return
    ranks = drain_ranks(checked.card, checked.read.get("drain"), checked.read.get("slot") == "aura")
    if not ranks:
        return
    top = checked.card.get("fusionLimit")
    best = top if top in ranks else (checked.rank if checked.rank in ranks else max(ranks))
    checked.rank, checked.rank_from_drain = best, best != checked.rank


# --- Lecture ------------------------------------------------------------------------------------------------

def valid_reading(data) -> dict:
    """Le JSON imposé est garanti par l'API ; la forme est revérifiée ici au cas où."""
    if not (isinstance(data, dict) and isinstance(data.get("is_build"), bool) and isinstance(data.get("slots"), list)
            and all(isinstance(slot, dict) for slot in data["slots"]) and len(data["slots"]) <= MAX_SLOTS):
        raise BuildError("lecture de la capture d'une forme inattendue")
    data.setdefault("displayed_stats", [])
    for slot in data["slots"]:
        drain = slot.get("drain")
        if not isinstance(drain, int) or isinstance(drain, bool) or not 0 <= drain <= MAX_DRAIN:
            slot["drain"] = None
    return data


async def read_build(client, image: PreparedImage, config: Config, usage: Usage) -> dict:
    """Un appel avec l'image : le contenu de l'écran, en JSON. `usage` est rempli même si la lecture échoue ensuite."""
    response = await client.messages.create(
        model=config.build_reader_model,
        max_tokens=READER_MAX_TOKENS,
        system=BUILD_READER_PROMPT,
        messages=[{"role": "user", "content": [image.block(), {"type": "text", "text": BUILD_READER_REQUEST}]}],
        output_config={"effort": READER_EFFORT, "format": {"type": "json_schema", "schema": READER_SCHEMA}},
    )
    usage.add(response.usage)
    if response.stop_reason in ("refusal", "max_tokens"):
        raise BuildError(f"lecture de la capture interrompue ({response.stop_reason})")
    text = next((block.text for block in response.content if block.type == "text"), "")
    try:
        return valid_reading(json.loads(text))
    except ValueError as error:
        raise BuildError(f"lecture de la capture illisible ({error})") from error


def is_build(reading: dict) -> bool:
    return reading["is_build"] and any(slot.get("name") for slot in reading["slots"])


# --- Vérification -------------------------------------------------------------------------------------------

async def check(api: WarframeApi, slot: dict) -> Checked:
    kind, name = slot.get("kind"), (slot.get("name") or "").strip()
    if kind == "riven":
        return Checked(slot, RIVEN)
    if kind not in FAMILIES:
        return Checked(slot, NOT_CHECKED)
    if not name:
        return Checked(slot, UNKNOWN)
    lookup = await api.find(FAMILIES[kind], name)
    if lookup.found:
        checked = Checked(slot, VERIFIED, card=lookup.found[0], sources=lookup.sources[:1])
        if kind == "mod":
            settle_rank(checked)
        else:
            checked.rank = slot.get("rank")
        return checked
    return Checked(slot, UNCERTAIN if lookup.suggestions else UNKNOWN, candidates=lookup.suggestions[:5])


async def verify(api: WarframeApi, reading: dict) -> list[Checked]:
    """Chaque carte vérifiée en parallèle. Une panne de warframestat (WarframeApiError) remonte."""
    return list(await asyncio.gather(*(check(api, slot) for slot in reading["slots"])))


def sources(checked: list[Checked]) -> list[tuple[str, str]]:
    return [source for item in checked for source in item.sources]


# --- Analyse ------------------------------------------------------------------------------------------------

def payload(reading: dict, checked: list[Checked], question: str | None) -> str:
    """Ce que reçoit l'analyse : le build lu et vérifié, sans l'image."""
    slots = []
    for item in checked:
        read = item.read
        rank = item.rank if item.status == VERIFIED else read.get("rank")
        entry = {"slot": read.get("slot"), "read_name": read.get("name"), "readable": read.get("readable"),
                 "rank": rank, "max_rank": read.get("max_rank"), "drain": read.get("drain"),
                 "polarity": read.get("polarity"), "status": item.status}
        if item.rank_from_drain:
            entry["rank_from_drain"] = True
        if item.card is not None:
            entry["card"] = item.card
        if item.candidates:
            entry["candidates"] = item.candidates
        slots.append(entry)
    return dump({"equipment": {"kind": reading.get("equipment_kind"), "name": reading.get("equipment_name")},
                 "capacity": reading.get("capacity"), "displayed_stats": reading.get("displayed_stats"),
                 "slots": slots, "question": question})


BUILD_SYSTEM = system_blocks(BUILD_PROMPT)


def profile(config: Config) -> Profile:
    # Sources : les cartes vérifiées et les fiches demandées, pas les premiers résultats d'une recherche.
    return Profile(BUILD_SYSTEM, BUILD_TOOLS, config.build_model, config.build_max_tokens, config.build_effort,
                   search_sources=False)
