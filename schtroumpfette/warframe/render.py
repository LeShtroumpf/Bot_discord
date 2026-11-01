"""Embeds Discord des sujets Warframe. Fonctions pures : (données, heure) -> embeds."""
import datetime as dt
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import discord

from . import cycles
from .arbitrations import DEFAULT_EMOJIS, DURATION, TIER_COLORS, Schedule, Tier, noteworthy
from .translations import Translator
from .worldstate import ws_date

TOPICS = {
    "arbitrage": "Arbitrage",
    "fissures": "Fissures du Néant",
    "invasions": "Invasions",
    "alertes": "Alertes",
    "events": "Events",
    "cycles": "Cycles",
    "circuit": "Circuit (Duviri)",
    "baro": "Baro Ki'Teer",
}
UPCOMING_WINDOW = dt.timedelta(hours=3)
NOTEWORTHY_WINDOW = dt.timedelta(hours=24)

FIELD_MAX = 1024
FIELDS_MAX = 25
EMBED_MAX = 5800  # limite Discord : 6 000, on garde de la marge pour le pied de page
PARIS = ZoneInfo("Europe/Paris")
ERA_ORDER = ("VoidT1", "VoidT2", "VoidT3", "VoidT4", "VoidT5", "VoidT6")
# Miniatures des messages : icônes officielles du jeu servies par browse.wf.
ICON_BASE = "https://browse.wf"
ICONS = {
    "arbitrage": "/Lotus/Interface/Icons/Syndicates/FactionSigilJudge.png",          # Arbitres d'Hexis
    "fissures": "/Lotus/Interface/Icons/Relics/RelicAxiA.png",
    "fissures_sp": "/Lotus/Interface/Icons/Relics/RelicImmortalA.png",               # relique Requiem
    "tempetes": "/Lotus/Interface/Icons/StoreIcons/Resources/Railjack/RailjackComponentAsterite.png",
    "invasions": "/Lotus/Interface/Icons/Player/FactionGrineer.png",
    "alertes": "/Lotus/Interface/Icons/Sigils/ConclaveTacAlertEmblem.png",
    "events": "/Lotus/Interface/Icons/Sigils/ConclaveTacAlertEmblem.png",             # si l'event n'a pas d'icône
    "cycles": "/Lotus/Interface/Icons/Syndicates/FactionSigilEidolonCetusElder.png",  # Ostron
    "circuit": "/Lotus/Interface/Graphics/StartingZoneChoice/DuviriStartingZoneIconParadox.png",
    "baro": "/Lotus/Interface/Icons/Npcs/BaroKiTeerPortrait.png",
}
COLORS = {
    "fissures": 0xC9A227, "fissures_sp": 0xB71C1C, "tempetes": 0x5C6BC0, "invasions": 0x8D6E63,
    "alertes": 0xFFB300, "events": 0xEC407A, "cycles": 0x26A69A, "circuit": 0x7E57C2, "baro": 0x00897B,
}


@dataclass
class Context:
    """Tout ce qu'il faut pour calculer les embeds à un instant donné."""
    now: dt.datetime
    tr: Translator
    worldstate: dict | None = None
    worldstate_at: dt.datetime | None = None
    stale: bool = False
    schedule: Schedule = field(default_factory=Schedule)
    tiers: dict[str, Tier] = field(default_factory=dict)
    tier_emojis: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_EMOJIS))


# --- Outils ---------------------------------------------------------------------------------------------

def ts(when: dt.datetime, style: str = "R") -> str:
    """Horodatage Discord, actualisé côté client (« dans 9 minutes »)."""
    return f"<t:{int(when.timestamp())}:{style}>"


def number(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def join_lines(lines: list[str], limit: int = FIELD_MAX) -> str:
    """Joint des lignes sans dépasser `limit` caractères, avec « … et N autres » si besoin."""
    out, size = [], 0
    for index, line in enumerate(lines):
        rest = len(lines) - index
        suffix = f"… et {rest} autres"
        if size + len(line) + 1 > limit - (len(suffix) + 1 if rest > 1 else 0):
            out.append(suffix)
            break
        out.append(line)
        size += len(line) + 1
    return "\n".join(out)


def add_fields(embed: discord.Embed, fields: list[tuple[str, str]], inline: bool = False) -> discord.Embed:
    """Ajoute des champs en respectant les limites Discord (25 champs, 6 000 caractères)."""
    for index, (name, value) in enumerate(fields):
        rest = len(fields) - index
        if len(embed.fields) >= FIELDS_MAX - 1 and rest > 1 or len(embed) + len(name) + len(value) > EMBED_MAX:
            embed.add_field(name="…", value=f"et {rest} autres", inline=False)
            break
        embed.add_field(name=name[:256], value=value[:FIELD_MAX] or "—", inline=inline)
    return embed


def header(embed: discord.Embed, name: str, icon: str) -> discord.Embed:
    """En-tête de l'embed : nom du sujet en haut, icône en miniature (~80 px) à droite.
    L'icône d'auteur (~24 px, taille fixée par Discord) était trop petite ; la miniature réduit en revanche
    la largeur du texte."""
    embed.set_author(name=name)
    embed.set_thumbnail(url=ICON_BASE + (ICONS.get(icon) or icon))
    return embed


def finish(embed: discord.Embed, ctx: Context, needs_worldstate: bool = True) -> discord.Embed:
    """Pied de page : la date des données n'apparaît que si elles sont périmées (API injoignable)."""
    if needs_worldstate and ctx.stale and ctx.worldstate_at:
        when = ctx.worldstate_at.astimezone(PARIS).strftime("%d/%m à %H:%M")
        embed.set_footer(text=f"⚠️ Données du {when} : worldstate injoignable")
    else:
        embed.set_footer(text="Worldstate officiel de Warframe")
    return embed


def rewards(tr: Translator, reward: dict | None) -> str:
    reward = reward or {}
    parts = [f"{number(item.get('ItemCount', 1))}× {tr.item(item.get('ItemType', '?'))}" for item in reward.get("countedItems", [])]
    parts += [tr.item(item) for item in reward.get("items", [])]
    if reward.get("credits"):
        parts.append(f"{number(reward['credits'])} crédits")
    return ", ".join(parts) or "—"


def active(entries: list[dict], now: dt.datetime) -> list[dict]:
    """Entrées non expirées, triées par fin."""
    out = [e for e in entries if (ws_date(e.get("Expiry")) or now) > now]
    return sorted(out, key=lambda e: ws_date(e.get("Expiry")) or now)


def worldstate_missing(topic: str, color: int, ctx: Context) -> list[discord.Embed]:
    embed = header(discord.Embed(description="Les données Warframe arrivent…", color=color), TOPICS[topic], topic)
    return [finish(embed, ctx)]


# --- Sujets ---------------------------------------------------------------------------------------------

def tier_label(tier: Tier, emojis: dict[str, str]) -> tuple[str, str]:
    """(emoji, texte). Emoji personnalisé : la lettre est dans l'emoji, comme chez les Arbitration Goons
    -> ("<:tierSP:…>", "Tier"). Emoji Unicode : il ne porte que la couleur -> ("🟪", "SP Tier")."""
    emoji = emojis.get(tier.tier, "")
    return (emoji, "Tier") if emoji.startswith("<") else (emoji, f"{tier.tier} Tier")


def render_arbitrage(ctx: Context) -> list[discord.Embed]:
    current = ctx.schedule.current(ctx.now)
    if current is None:
        embed = discord.Embed(color=TIER_COLORS["F"], description="Planning des arbitrages indisponible pour le moment.")
        return [finish(header(embed, "Arbitrage", "arbitrage"), ctx, needs_worldstate=False)]
    tier = ctx.tiers.get(current.node, Tier())
    description = f"Se termine {ts(current.end)}"
    if tier.saryn:
        description += "\nSaryn viable sur ce nœud"
    emoji, label = tier_label(tier, ctx.tier_emojis)
    embed = discord.Embed(title=f"{emoji} {label} | {ctx.tr.node(current.node)}".strip(),
                          description=description, color=TIER_COLORS.get(tier.tier, TIER_COLORS["F"]))
    header(embed, "Arbitrage", "arbitrage")
    embed.add_field(name="Ennemi", value=ctx.tr.node_faction(current.node))
    embed.add_field(name="Type de mission", value=ctx.tr.node_mission(current.node))

    def line(arbitration):
        emoji, label = tier_label(ctx.tiers.get(arbitration.node, Tier()), ctx.tier_emojis)
        return f"{emoji} **{label} | {ctx.tr.node(arbitration.node)}** {ts(arbitration.start)}".strip()

    upcoming = ctx.schedule.upcoming(ctx.now, UPCOMING_WINDOW)
    notable = noteworthy(ctx.schedule, ctx.tiers, ctx.now, NOTEWORTHY_WINDOW, exclude=upcoming)
    embed.add_field(name="Prochains arbitrages", value=join_lines([line(a) for a in upcoming]) or "—", inline=False)
    embed.add_field(name="Arbitrages notables (24 h)", value=join_lines([line(a) for a in notable]) or "Aucun S, A ou SP",
                    inline=False)
    return [finish(embed, ctx, needs_worldstate=False)]


def _fissure_embed(title: str, icon: str, missions: list[tuple[str, str, str, dt.datetime]], ctx: Context) -> discord.Embed:
    """missions : (ère, nœud, type de mission traduit, fin)."""
    embed = header(discord.Embed(color=COLORS[icon]), title, icon)
    if not missions:
        embed.description = "Aucune fissure en cours."
        return finish(embed, ctx)
    fields = []
    for era in ERA_ORDER:
        lines = [f"{ctx.tr.node(node)} — {mission} — {ctx.tr.node_faction(node)} — fin {ts(end)}"
                 for e, node, mission, end in missions if e == era]
        if lines:
            fields.append((f"{ctx.tr.era(era)} ({len(lines)})", join_lines(lines)))
    return finish(add_fields(embed, fields), ctx)


def render_fissures(ctx: Context) -> list[discord.Embed]:
    if ctx.worldstate is None:
        return worldstate_missing("fissures", COLORS["fissures"], ctx)
    normal, hard = [], []
    for mission in active(ctx.worldstate.get("ActiveMissions", []), ctx.now):
        entry = (mission.get("Modifier"), mission.get("Node"), ctx.tr.mission(mission.get("MissionType")),
                 ws_date(mission.get("Expiry")))
        (hard if mission.get("Hard") else normal).append(entry)
    storms = [(storm.get("ActiveMissionTier"), storm.get("Node"), ctx.tr.node_mission(storm.get("Node")),
               ws_date(storm.get("Expiry"))) for storm in active(ctx.worldstate.get("VoidStorms", []), ctx.now)]
    return [
        _fissure_embed("Fissures du Néant", "fissures", normal, ctx),
        _fissure_embed("Fissures — Route de l'Acier", "fissures_sp", hard, ctx),
        _fissure_embed("Tempêtes du Néant (Railjack)", "tempetes", storms, ctx),
    ]


def invasion_progress(invasion: dict) -> float:
    """Avancée du camp attaquant, en % (formule de warframestat)."""
    goal = invasion.get("Goal") or 1
    scale = 100 if invasion.get("Faction") == "FC_INFESTATION" else 50
    return max(0.0, min(100.0, (1 + invasion.get("Count", 0) / goal) * scale))


def render_invasions(ctx: Context) -> list[discord.Embed]:
    if ctx.worldstate is None:
        return worldstate_missing("invasions", COLORS["invasions"], ctx)
    embed = header(discord.Embed(color=COLORS["invasions"]), "Invasions", "invasions")
    fields = []
    for invasion in ctx.worldstate.get("Invasions", []):
        if invasion.get("Completed"):
            continue
        attacker, defender = ctx.tr.faction(invasion.get("Faction")), ctx.tr.faction(invasion.get("DefenderFaction"))
        progress = invasion_progress(invasion)
        name = ctx.tr.node(invasion.get("Node"))
        if ctx.tr.known_text(invasion.get("LocTag")):
            name += f" — {ctx.tr.known_text(invasion.get('LocTag'))}"
        value = (f"⚔️ **{attacker}** : {rewards(ctx.tr, invasion.get('AttackerReward'))}\n"
                 f"🛡️ **{defender}** : {rewards(ctx.tr, invasion.get('DefenderReward'))}\n"
                 f"Progression : {attacker} {progress:.0f} % · {defender} {100 - progress:.0f} %")
        fields.append((name, value))
    if not fields:
        embed.description = "Aucune invasion en cours."
    return [finish(add_fields(embed, fields), ctx)]


def render_alertes(ctx: Context) -> list[discord.Embed]:
    if ctx.worldstate is None:
        return worldstate_missing("alertes", COLORS["alertes"], ctx)
    embed = header(discord.Embed(color=COLORS["alertes"]), "Alertes", "alertes")
    fields = []
    for alert in active(ctx.worldstate.get("Alerts", []), ctx.now):
        info = alert.get("MissionInfo", {})
        name = f"{ctx.tr.node(info.get('location'))} — {ctx.tr.mission(info.get('missionType'))}"
        value = (f"{ctx.tr.faction(info.get('faction'))} niv. {info.get('minEnemyLevel', '?')}-{info.get('maxEnemyLevel', '?')}"
                 f" · fin {ts(ws_date(alert.get('Expiry')))}\nRécompenses : {rewards(ctx.tr, info.get('missionReward'))}")
        fields.append((name, value))
    if not fields:
        embed.description = "Aucune alerte en cours."
    return [finish(add_fields(embed, fields), ctx)]


def render_events(ctx: Context) -> list[discord.Embed]:
    if ctx.worldstate is None:
        return worldstate_missing("events", COLORS["events"], ctx)
    goals = active(ctx.worldstate.get("Goals", []), ctx.now)
    icon = next((goal["Icon"] for goal in goals if str(goal.get("Icon", "")).startswith("/Lotus/")), "events")
    embed = header(discord.Embed(color=COLORS["events"]), "Events", icon)
    fields = []
    for goal in goals:
        name = ctx.tr.text(goal.get("Desc")) or goal.get("Tag") or "Event"
        value = f"Fin {ts(ws_date(goal.get('Expiry')))}"
        if goal.get("Goal", 0) > 1 and not goal.get("Personal"):
            value += f" · Progression {number(goal.get('Count', 0))} / {number(goal['Goal'])}"
        if goal.get("Node") in ctx.tr.nodes:
            value += f"\nLieu : {ctx.tr.node(goal['Node'])}"
        if goal.get("Reward"):
            value += f"\nRécompenses : {rewards(ctx.tr, goal['Reward'])}"
        fields.append((name, value))
    if not fields:
        embed.description = "Aucun event en cours."
    return [finish(add_fields(embed, fields), ctx)]


def _cycle_value(cycle: cycles.Cycle, icon: str) -> str:
    return f"{icon} **{cycle.state.capitalize()}** — {cycle.next_state} {ts(cycle.ends_at)} ({ts(cycle.ends_at, 't')})"


def render_cycles(ctx: Context) -> list[discord.Embed]:
    embed = header(discord.Embed(color=COLORS["cycles"]), "Cycles", "cycles")
    bounty_end = cycles.cetus_bounty_end(ctx.worldstate)
    if bounty_end:
        cetus = cycles.cetus(bounty_end, ctx.now)
        cambion = cycles.cambion(bounty_end, ctx.now)
        cetus_value = _cycle_value(cetus, "☀️" if cetus.state == "jour" else "🌙")
        cambion_value = _cycle_value(cambion, "🟠" if cambion.state == "Fass" else "🟣")
    else:
        cetus_value = cambion_value = "Inconnu pour le moment"
    vallis = cycles.vallis(ctx.now)
    embed.add_field(name="Cetus — Plaines d'Eidolon", value=cetus_value, inline=False)
    embed.add_field(name="Vallée Orbis", value=_cycle_value(vallis, "🔥" if vallis.state == "chaud" else "❄️"), inline=False)
    embed.add_field(name="Puits Cambion", value=cambion_value, inline=False)
    # Cetus / Cambion sont extrapolés à partir du dernier worldstate connu : jamais « périmés ».
    return [finish(embed, ctx, needs_worldstate=False)]


def render_circuit(ctx: Context) -> list[discord.Embed]:
    if ctx.worldstate is None:
        return worldstate_missing("circuit", COLORS["circuit"], ctx)
    embed = header(discord.Embed(color=COLORS["circuit"]), "Circuit (Duviri)", "circuit")
    schedule = active(ctx.worldstate.get("EndlessXpSchedule", []), ctx.now)
    if not schedule:
        embed.description = "Rotation inconnue pour le moment."
        return [finish(embed, ctx)]
    rotation = schedule[0]
    embed.description = f"Nouvelle rotation {ts(ws_date(rotation.get('Expiry')))}"
    labels = {"EXC_NORMAL": "Normal — Warframes", "EXC_HARD": "Route de l'Acier — Adaptateurs Incarnon Genesis"}
    fields = [(labels.get(c.get("Category"), c.get("Category", "?")), ", ".join(c.get("Choices", [])) or "—")
              for c in rotation.get("CategoryChoices", [])]
    return [finish(add_fields(embed, fields), ctx)]


def render_baro(ctx: Context) -> list[discord.Embed]:
    if ctx.worldstate is None:
        return worldstate_missing("baro", COLORS["baro"], ctx)
    embed = header(discord.Embed(color=COLORS["baro"]), "Baro Ki'Teer", "baro")
    traders = ctx.worldstate.get("VoidTraders", [])
    if not traders:
        embed.description = "Pas d'info sur Baro Ki'Teer pour le moment."
        return [finish(embed, ctx)]
    trader = traders[0]
    arrival, departure = ws_date(trader.get("Activation")), ws_date(trader.get("Expiry"))
    relay = ctx.tr.node(trader.get("Node"))
    if arrival and ctx.now < arrival:
        embed.description = f"Arrive {ts(arrival)} ({ts(arrival, 'f')}) au **{relay}**"
    elif departure and ctx.now < departure:
        embed.description = f"Présent au **{relay}**, repart {ts(departure)} ({ts(departure, 'f')})"
        lines = [f"{ctx.tr.item(item.get('ItemType', '?'))} — {item.get('PrimePrice', 0)} ducats, "
                 f"{number(item.get('RegularPrice', 0))} crédits" for item in trader.get("Manifest", [])]
        fields, chunk = [], []
        for line in lines:
            if len("\n".join(chunk + [line])) > FIELD_MAX:
                fields.append(chunk)
                chunk = []
            chunk.append(line)
        if chunk:
            fields.append(chunk)
        add_fields(embed, [(f"Inventaire ({i}/{len(fields)})", "\n".join(c)) for i, c in enumerate(fields, 1)])
    else:
        embed.description = "Baro Ki'Teer est reparti. Prochaine visite annoncée dès qu'elle est connue."
    return [finish(embed, ctx)]


RENDERERS = {
    "arbitrage": render_arbitrage,
    "fissures": render_fissures,
    "invasions": render_invasions,
    "alertes": render_alertes,
    "events": render_events,
    "cycles": render_cycles,
    "circuit": render_circuit,
    "baro": render_baro,
}


def render_all(ctx: Context) -> dict[str, list[discord.Embed]]:
    return {topic: renderer(ctx) for topic, renderer in RENDERERS.items()}


# --- Échéances --------------------------------------------------------------------------------------------

def next_deadline(ctx: Context) -> dt.datetime | None:
    """Prochain instant où un message doit changer : fin d'arbitrage, de cycle, de fissure, arrivée de Baro…"""
    candidates = []
    current = ctx.schedule.current(ctx.now)
    if current:
        candidates.append(current.end)
    elif ctx.schedule:
        candidates.append(ctx.now.replace(minute=0, second=0, microsecond=0) + DURATION)
    candidates.append(cycles.vallis(ctx.now).ends_at)
    bounty_end = cycles.cetus_bounty_end(ctx.worldstate)
    if bounty_end:
        candidates.append(cycles.cetus(bounty_end, ctx.now).ends_at)
    for key in ("ActiveMissions", "VoidStorms", "Alerts", "Goals", "EndlessXpSchedule"):
        candidates += [ws_date(entry.get("Expiry")) for entry in (ctx.worldstate or {}).get(key, [])]
    for trader in (ctx.worldstate or {}).get("VoidTraders", []):
        candidates += [ws_date(trader.get("Activation")), ws_date(trader.get("Expiry"))]
    future = [when for when in candidates if when and when > ctx.now]
    return min(future, default=None)
