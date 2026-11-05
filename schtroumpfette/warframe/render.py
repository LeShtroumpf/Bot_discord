"""Embeds Discord des sujets Warframe. Fonctions pures : (données, heure) -> embeds."""
import datetime as dt
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import discord

from . import cycles, synthesis
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
STEEL_PATH_EVENT_RATIO = 1.5  # ressource d'event en Steel Path : 50 → 75 (quantité absente de l'API)

FIELD_MAX = 1024
FIELDS_MAX = 25
EMBED_MAX = 5800  # limite Discord : 6 000, on garde de la marge pour le pied de page
PARIS = ZoneInfo("Europe/Paris")
BLANK_LINE = "\n\u200b"  # ligne vide en fin de valeur (Discord supprime les lignes vides finales, pas un \u200b)
# Miniatures des messages. Icônes officielles du jeu : servies par browse.wf (chemins du jeu) ou, pour les icônes
# de la barre des activités en jeu (blanches sur fond transparent), par le wiki officiel.
ICON_BASE = "https://browse.wf"
WIKI_IMAGES = "https://wiki.warframe.com/images/"
# Icônes du dépôt (warframe/data/icons/), servies par GitHub depuis master : exclues de l'image Docker.
REPO_ICONS = "https://raw.githubusercontent.com/LeShtroumpf/Bot_discord/master/schtroumpfette/warframe/data/icons/"
VOID_TRACES = ICON_BASE + "/Lotus/Interface/Icons/StoreIcons/Currency/Luminous.png"  # Traces du Néant
ALERT_TRIANGLE = REPO_ICONS + "AlertTriangle.png"  # triangle d'alerte du menu en jeu, redessiné
VOID_TEAR = WIKI_IMAGES + "VoidTearIcon%28xWhite%29.png"  # icône des fissures du menu en jeu
ICONS = {
    "arbitrage": WIKI_IMAGES + "EliteAlertIcon%28xWhite%29.png",  # insigne d'alerte d'élite du menu en jeu (512 px)
    "fissures": VOID_TEAR,
    "fissures_sp": VOID_TEAR,
    "tempetes": WIKI_IMAGES + "IconRailjack%28xWhite%29.png",
    "invasions": WIKI_IMAGES + "InvasionIcon%28xWhite%29.png",
    "alertes": ALERT_TRIANGLE,
    "events": ALERT_TRIANGLE,  # si l'event n'a pas d'icône propre
    "cycles": None,  # pas de miniature (l'icône Ostron ne représentait que Cetus)
    "circuit": ICON_BASE + "/Lotus/Interface/Graphics/StartingZoneChoice/DuviriStartingZoneIconParadox.png",
    "baro": ICON_BASE + "/Lotus/Interface/Icons/Npcs/BaroKiTeerPortrait.png",
    "synthese": ICON_BASE + "/Lotus/Interface/Icons/Categories/IconLibrarian256.png",  # sigil de Simaris
}
COLORS = {
    "fissures": 0xC9A227, "fissures_sp": 0xB71C1C, "tempetes": 0x5C6BC0, "invasions": 0x8D6E63,
    "alertes": 0xFFB300, "events": 0xEC407A, "cycles": 0x26A69A, "circuit": 0x7E57C2, "baro": 0x00897B,
    "synthese": 0x4FC3F7,
}
SYNTHESIS_SOURCE = "[Source : wiki Warframe](https://wiki.warframe.com/w/Synthesis)"  # un pied de page ne peut pas contenir de lien


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
    faction_emojis: dict[str, str] = field(default_factory=dict)


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
    url = ICONS[icon] if icon in ICONS else ICON_BASE + icon  # sinon : chemin du jeu (icône propre à un event)
    if url:
        embed.set_thumbnail(url=url)
    return embed


def finish(embed: discord.Embed, ctx: Context, needs_worldstate: bool = True) -> discord.Embed:
    """Pied de page : seulement un avertissement si les données sont périmées (API injoignable).
    L'heure de dernière modification (embed.timestamp) est posée par le cog, à la publication."""
    if needs_worldstate and ctx.stale and ctx.worldstate_at:
        when = ctx.worldstate_at.astimezone(PARIS).strftime("%d/%m à %H:%M")
        embed.set_footer(text=f"⚠️ Données du {when} : worldstate injoignable")
    return embed


def rewards(reward: dict | None) -> str:
    reward = reward or {}
    parts = [f"{number(item.get('count', 1))}× {item.get('type', '?')}" for item in reward.get("countedItems", [])]
    parts += [str(item) for item in reward.get("items", [])]
    if reward.get("credits"):
        parts.append(f"{number(reward['credits'])} crédits")
    return ", ".join(parts) or "—"


def alert_rewards(reward: dict | None, event_alert: bool) -> str:
    """Récompenses d'une alerte. Sur une alerte d'event, seule la ressource compte : quantité normale et Steel Path
    (absente de l'API, d'où le calcul), sans les crédits."""
    counted = (reward or {}).get("countedItems", [])
    if not event_alert or not counted:
        return rewards(reward)
    parts = []
    for item in counted:
        count = item.get("count", 1)
        parts.append(f"{number(count)} (sp {number(int(count * STEEL_PATH_EVENT_RATIO))}) × {item.get('type', '?')}")
    return ", ".join(parts)


def active(entries: list[dict], now: dt.datetime) -> list[dict]:
    """Entrées non expirées, triées par fin."""
    out = [e for e in entries if (ws_date(e.get("expiry")) or now) > now]
    return sorted(out, key=lambda e: ws_date(e.get("expiry")) or now)


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
    description += BLANK_LINE  # 1. détache l'en-tête des champs
    # Titre en texte, comme sur la maquette : un emoji personnalisé y est mal aligné (décalé vers le haut).
    embed = discord.Embed(title=f"{tier.tier} Tier | {ctx.tr.node(current.node)}",
                          description=description, color=TIER_COLORS.get(tier.tier, TIER_COLORS["F"]))
    header(embed, "Arbitrage", "arbitrage")
    # 2. ligne vide sous le bloc Ennemi / Type de mission (sur les deux colonnes, pour qu'elles restent alignées)
    embed.add_field(name="Ennemi", value=ctx.tr.node_faction(current.node) + BLANK_LINE)
    embed.add_field(name="Type de mission", value=ctx.tr.node_mission(current.node) + BLANK_LINE)

    def line(arbitration):
        emoji, label = tier_label(ctx.tiers.get(arbitration.node, Tier()), ctx.tier_emojis)
        return f"{emoji} **{label} | {ctx.tr.node(arbitration.node)}** {ts(arbitration.start)}".strip()

    upcoming = ctx.schedule.upcoming(ctx.now, UPCOMING_WINDOW)
    notable = noteworthy(ctx.schedule, ctx.tiers, ctx.now, NOTEWORTHY_WINDOW, exclude=upcoming)
    upcoming_value = join_lines([line(a) for a in upcoming], FIELD_MAX - len(BLANK_LINE)) or "—"
    embed.add_field(name="Prochains arbitrages", value=upcoming_value + BLANK_LINE, inline=False)  # 3. avant les notables
    embed.add_field(name="Arbitrages notables (24 h)", value=join_lines([line(a) for a in notable]) or "Aucun S, A ou SP",
                    inline=False)
    return [finish(embed, ctx, needs_worldstate=False)]


def fissure_enemy(fissure: dict) -> str:
    """Ennemi d'une fissure. L'API abîme le Feu croisé en français (« Feux Croisés Extermination »)."""
    return "Feux Croisés" if fissure.get("enemyKey") == "Crossfire" else fissure.get("enemy", "?")


def fissure_line(fissure: dict) -> str:
    return (f"{fissure.get('node', '?')} — {fissure.get('missionType', '?')} — {fissure_enemy(fissure)}"
            f" — fin {ts(ws_date(fissure.get('expiry')))}")


def _fissure_embed(title: str, icon: str, fissures: list[dict], ctx: Context) -> discord.Embed:
    embed = header(discord.Embed(color=COLORS[icon]), title, icon)
    if not fissures:
        embed.description = "Aucune fissure en cours."
        return finish(embed, ctx)
    fields = []
    for tier_num in sorted({fissure.get("tierNum", 0) for fissure in fissures}):
        group = [fissure for fissure in fissures if fissure.get("tierNum", 0) == tier_num]
        lines = [fissure_line(fissure) for fissure in group]
        fields.append((f"{group[0].get('tier', '?')} ({len(lines)})", join_lines(lines, FIELD_MAX - len(BLANK_LINE))))
    # Une ligne vide entre deux groupes d'ère, pour aérer (pas de champ vide : ils comptent dans les 25 champs).
    fields = [(name, value + BLANK_LINE) for name, value in fields[:-1]] + fields[-1:]
    return finish(add_fields(embed, fields), ctx)


def render_fissures(ctx: Context) -> list[discord.Embed]:
    if ctx.worldstate is None:
        return worldstate_missing("fissures", COLORS["fissures"], ctx)
    fissures = active(ctx.worldstate.get("fissures", []), ctx.now)
    storms = [fissure for fissure in fissures if fissure.get("isStorm")]
    hard = [fissure for fissure in fissures if fissure.get("isHard") and not fissure.get("isStorm")]
    normal = [fissure for fissure in fissures if not fissure.get("isHard") and not fissure.get("isStorm")]
    return [
        _fissure_embed("Fissures du Néant", "fissures", normal, ctx),
        _fissure_embed("Fissures — Route de l'Acier", "fissures_sp", hard, ctx),
        _fissure_embed("Tempêtes du Néant (Railjack)", "tempetes", storms, ctx),
    ]


def vs_infested(invasion: dict) -> bool:
    return invasion.get("attacker", {}).get("factionKey") == "Infested"


def invasion_progress(invasion: dict) -> float:
    """Avancée du camp attaquant, en % (formule de warframestat)."""
    goal = invasion.get("requiredRuns") or 1
    scale = 100 if vs_infested(invasion) else 50
    return max(0.0, min(100.0, (1 + invasion.get("count", 0) / goal) * scale))


def invasion_sort_key(invasion: dict) -> tuple[str, str]:
    """Planète puis nœud : l'ordre de l'API change d'une requête à l'autre, ce qui provoquerait des éditions inutiles."""
    node, _, planet = invasion.get("node", "?").rpartition(" (")
    return planet, node


def invasion_value(ctx: Context, invasion: dict) -> str:
    attacker, defender = invasion.get("attacker", {}), invasion.get("defender", {})
    attacker_name, defender_name = attacker.get("faction", "?"), defender.get("faction", "?")
    attacker_reward, defender_reward = rewards(attacker.get("reward")), rewards(defender.get("reward"))
    progress = invasion_progress(invasion)
    attacker_line = f"{ctx.faction_emojis.get(attacker.get('factionKey'), '⚔️')} **{attacker_name}** : {attacker_reward}"
    defender_line = f"{ctx.faction_emojis.get(defender.get('factionKey'), '🛡️')} **{defender_name}** : {defender_reward}"
    if not vs_infested(invasion):
        return (f"{attacker_line}\n{defender_line}\n"
                f"Progression : {attacker_name} {progress:.0f} % · {defender_name} {100 - progress:.0f} %")
    # Contre les Infestés, la jauge part de 100 % côté Infestés et descend vers 0 : seul l'avancement du défenseur parle.
    lines = [attacker_line] if attacker_reward != "—" else []
    return "\n".join([*lines, defender_line, f"Avancement : {100 - progress:.0f} % · contre les Infestés"])


def render_invasions(ctx: Context) -> list[discord.Embed]:
    if ctx.worldstate is None:
        return worldstate_missing("invasions", COLORS["invasions"], ctx)
    embed = header(discord.Embed(color=COLORS["invasions"]), "Invasions", "invasions")
    fields = []
    running = [invasion for invasion in ctx.worldstate.get("invasions", []) if not invasion.get("completed")]
    for invasion in sorted(running, key=invasion_sort_key):
        name = invasion.get("node", "?")
        if invasion.get("desc"):
            name += f" — {invasion['desc']}"
        fields.append((name, invasion_value(ctx, invasion)))
    if not fields:
        embed.description = "Aucune invasion en cours."
    return [finish(add_fields(embed, fields), ctx)]


def synthesis_location(tr: Translator, place: str) -> str:
    """"Cambria (Terre / Earth) · Espionnage · Grineer", ou le nom du wiki si le nœud est inconnu."""
    key = tr.node_key(place)
    location = tr.node_bilingual(place)
    return f"{location} · {tr.node_mission(key)} · {tr.node_faction(key)}" if key else location


def render_synthesis(tr: Translator, name: str, places: tuple[str, ...]) -> discord.Embed:
    """Réponse à /warframe cible: : les lieux d'une cible, par planète puis par nœud."""
    def by_planet(place: str) -> tuple[str, str]:
        node, _, planet = tr.node_bilingual(place).partition(" (")
        return synthesis.normalize(planet), synthesis.normalize(node)

    lines = [synthesis_location(tr, place) for place in sorted(places, key=by_planet)]
    description = "\n".join(lines) + f"\n\n{SYNTHESIS_SOURCE}"
    embed = discord.Embed(title=synthesis.label(tr, name), description=description, color=COLORS["synthese"])
    return embed.set_thumbnail(url=ICONS["synthese"])


def render_alertes(ctx: Context) -> list[discord.Embed]:
    if ctx.worldstate is None:
        return worldstate_missing("alertes", COLORS["alertes"], ctx)
    embed = header(discord.Embed(color=COLORS["alertes"]), "Alertes", "alertes")
    fields = []
    event_tags = {event.get("tag") for event in active(ctx.worldstate.get("events", []), ctx.now) if event.get("tag")}
    for alert in active(ctx.worldstate.get("alerts", []), ctx.now):
        mission = alert.get("mission", {})
        name = f"{mission.get('node', '?')} — {mission.get('type', '?')}"
        value = (f"{mission.get('faction', '?')} niv. {mission.get('minEnemyLevel', '?')}-{mission.get('maxEnemyLevel', '?')}"
                 f" · fin {ts(ws_date(alert.get('expiry')))}"
                 f"\nRécompenses : {alert_rewards(mission.get('reward'), alert.get('tag') in event_tags)}")
        fields.append((name, value))
    if not fields:
        embed.description = "Aucune alerte en cours."
    return [finish(add_fields(embed, fields), ctx)]


def render_events(ctx: Context) -> list[discord.Embed]:
    if ctx.worldstate is None:
        return worldstate_missing("events", COLORS["events"], ctx)
    embed = header(discord.Embed(color=COLORS["events"]), "Events", "events")
    fields = []
    for event in active(ctx.worldstate.get("events", []), ctx.now):
        name = event.get("description") or event.get("tag") or "Event"
        value = f"Fin {ts(ws_date(event.get('expiry')))}"
        if event.get("maximumScore", 0) > 1 and not event.get("isPersonal"):
            value += f" · Progression {number(event.get('currentScore', 0))} / {number(event['maximumScore'])}"
        if event.get("node"):
            value += f"\nLieu : {event['node']}"
        if event.get("rewards"):
            value += f"\nRécompenses : {', '.join(rewards(reward) for reward in event['rewards'])}"
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
    choices = (ctx.worldstate.get("duviriCycle") or {}).get("choices", [])
    if not choices:
        embed.description = "Rotation inconnue pour le moment."
        return [finish(embed, ctx)]
    embed.description = f"Nouvelle rotation {ts(cycles.circuit_rotation_end(ctx.now))}"
    labels = {"EXC_NORMAL": "Normal — Warframes", "EXC_HARD": "Route de l'Acier — Adaptateurs Incarnon Genesis"}
    fields = [(labels.get(c.get("categoryKey"), c.get("category", "?")), ", ".join(c.get("choices", [])) or "—") for c in choices]
    return [finish(add_fields(embed, fields), ctx)]


def render_baro(ctx: Context) -> list[discord.Embed]:
    if ctx.worldstate is None:
        return worldstate_missing("baro", COLORS["baro"], ctx)
    embed = header(discord.Embed(color=COLORS["baro"]), "Baro Ki'Teer", "baro")
    traders = ctx.worldstate.get("voidTraders", [])
    if not traders:
        embed.description = "Pas d'info sur Baro Ki'Teer pour le moment."
        return [finish(embed, ctx)]
    trader = traders[0]
    arrival, departure = ws_date(trader.get("activation")), ws_date(trader.get("expiry"))
    relay = trader.get("location", "?")
    if arrival and ctx.now < arrival:
        embed.description = f"Arrive {ts(arrival)} ({ts(arrival, 'f')}) au **{relay}**"
    elif departure and ctx.now < departure:
        embed.description = f"Présent au **{relay}**, repart {ts(departure)} ({ts(departure, 'f')})"
        lines = [f"{item.get('item', '?')} — {item.get('ducats') or 0} ducats, {number(item.get('credits') or 0)} crédits"
                 for item in trader.get("inventory", [])]
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
    if ctx.worldstate:
        candidates.append(cycles.circuit_rotation_end(ctx.now))
    for key in ("fissures", "alerts", "events"):
        candidates += [ws_date(entry.get("expiry")) for entry in (ctx.worldstate or {}).get(key, [])]
    for trader in (ctx.worldstate or {}).get("voidTraders", []):
        candidates += [ws_date(trader.get("activation")), ws_date(trader.get("expiry"))]
    future = [when for when in candidates if when and when > ctx.now]
    return min(future, default=None)
