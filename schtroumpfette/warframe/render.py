"""Embeds Discord des sujets Warframe. Fonctions pures : (données, heure) -> embeds."""
import datetime as dt
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import discord

from . import cycles, synthesis
from .arbitrations import DEFAULT_EMOJIS, DURATION, TIER_COLORS, Schedule, Tier, noteworthy
from .browsewf import Alert, Event, Fissure, Invasion, Reward, World
from .translations import Translator

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


# Source de browse.wf dont dépend chaque sujet (avertissement de données périmées) ; les autres sont calculés.
TOPIC_SOURCES = {"fissures": "worldstate", "alertes": "worldstate", "events": "worldstate", "baro": "worldstate",
                 "invasions": "invasions"}
ERA_ORDER = ("VoidT1", "VoidT2", "VoidT3", "VoidT4", "VoidT5", "VoidT6")


@dataclass
class Context:
    """Tout ce qu'il faut pour calculer les embeds à un instant donné."""
    now: dt.datetime
    tr: Translator
    world: World | None = None                   # worldState.min.json
    invasions: list[Invasion] | None = None
    bounty_end: dt.datetime | None = None        # fin du cycle des primes d'Ostron
    fetched_at: dict[str, dt.datetime] = field(default_factory=dict)  # source -> heure du dernier succès
    stale: set[str] = field(default_factory=set)  # sources dont les données sont périmées
    schedule: Schedule = field(default_factory=Schedule)
    tiers: dict[str, Tier] = field(default_factory=dict)
    tier_emojis: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_EMOJIS))
    faction_emojis: dict[str, str] = field(default_factory=dict)


# --- Outils ---------------------------------------------------------------------------------------------------

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


def finish(embed: discord.Embed, ctx: Context, source: str | None = None) -> discord.Embed:
    """Pied de page : seulement un avertissement si les données de la source sont périmées (source injoignable).
    L'heure de dernière modification (embed.timestamp) est posée par le cog, à la publication."""
    fetched_at = ctx.fetched_at.get(source) if source else None
    if source in ctx.stale and fetched_at:
        when = fetched_at.astimezone(PARIS).strftime("%d/%m à %H:%M")
        embed.set_footer(text=f"⚠️ Données du {when} : worldstate injoignable")
    return embed


def rewards(reward: Reward | None, tr: Translator) -> str:
    reward = reward or Reward()
    parts = [f"{number(count)}× {tr.item(path)}" for path, count in reward.counted]
    parts += [tr.item(path) for path in reward.items]
    if reward.credits:
        parts.append(f"{number(reward.credits)} crédits")
    return ", ".join(parts) or "—"


def alert_rewards(reward: Reward, tr: Translator, event_alert: bool) -> str:
    """Récompenses d'une alerte. Sur une alerte d'event, seule la ressource compte : quantité normale et Steel Path
    (absente du worldstate, d'où le calcul), sans les crédits."""
    if not event_alert or not reward.counted:
        return rewards(reward, tr)
    return ", ".join(f"{number(count)} (sp {number(int(count * STEEL_PATH_EVENT_RATIO))}) × {tr.item(path)}"
                     for path, count in reward.counted)


def active(entries, now: dt.datetime) -> list:
    """Entrées non expirées, triées par fin."""
    return sorted((entry for entry in entries if entry.expiry > now), key=lambda entry: entry.expiry)


def worldstate_missing(topic: str, color: int, ctx: Context) -> list[discord.Embed]:
    embed = header(discord.Embed(description="Les données Warframe arrivent…", color=color), TOPICS[topic], topic)
    return [finish(embed, ctx, TOPIC_SOURCES.get(topic))]


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
        return [finish(header(embed, "Arbitrage", "arbitrage"), ctx)]
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
    return [finish(embed, ctx)]


def fissure_line(fissure: Fissure, tr: Translator) -> str:
    """Nœud — mission — ennemi — fin. Tempête : le type de mission (Escarmouche, Orphix…) est celui du nœud."""
    mission = tr.mission(fissure.mission) if fissure.mission else tr.node_mission(fissure.node)
    return f"{tr.node(fissure.node)} — {mission} — {tr.node_faction(fissure.node)} — fin {ts(fissure.expiry)}"


def era_rank(era: str) -> int:
    return ERA_ORDER.index(era) if era in ERA_ORDER else len(ERA_ORDER)


def _fissure_embed(title: str, icon: str, fissures: list[Fissure], ctx: Context) -> discord.Embed:
    embed = header(discord.Embed(color=COLORS[icon]), title, icon)
    if not fissures:
        embed.description = "Aucune fissure en cours."
        return finish(embed, ctx, "worldstate")
    fields = []
    for era in sorted({fissure.era for fissure in fissures}, key=lambda era: (era_rank(era), era)):
        group = [fissure for fissure in fissures if fissure.era == era]
        lines = [fissure_line(fissure, ctx.tr) for fissure in group]
        fields.append((f"{ctx.tr.era(era)} ({len(lines)})", join_lines(lines, FIELD_MAX - len(BLANK_LINE))))
    # Une ligne vide entre deux groupes d'ère, pour aérer (pas de champ vide : ils comptent dans les 25 champs).
    fields = [(name, value + BLANK_LINE) for name, value in fields[:-1]] + fields[-1:]
    return finish(add_fields(embed, fields), ctx, "worldstate")


def render_fissures(ctx: Context) -> list[discord.Embed]:
    if ctx.world is None:
        return worldstate_missing("fissures", COLORS["fissures"], ctx)
    # Tri par fin puis par nœud : l'ordre du worldstate peut changer d'une requête à l'autre (éditions inutiles).
    fissures = sorted(active(ctx.world.fissures, ctx.now), key=lambda f: (f.expiry, f.node))
    storms = [fissure for fissure in fissures if fissure.storm]
    hard = [fissure for fissure in fissures if fissure.hard and not fissure.storm]
    normal = [fissure for fissure in fissures if not fissure.hard and not fissure.storm]
    return [
        _fissure_embed("Fissures du Néant", "fissures", normal, ctx),
        _fissure_embed("Fissures — Route de l'Acier", "fissures_sp", hard, ctx),
        _fissure_embed("Tempêtes du Néant (Railjack)", "tempetes", storms, ctx),
    ]


def invasion_title(invasion: Invasion, tr: Translator) -> str:
    """"Titan (Saturne) — Siège Corpus" : le libellé (absent des exports) vient de la table locale, selon l'attaquant."""
    return f"{tr.node(invasion.node)} — {tr.text(f'invasion/{invasion.attacker.faction}')}"


def invasion_sort_key(invasion: Invasion, tr: Translator) -> tuple[str, str]:
    """Planète puis nœud : l'ordre de la source change d'une requête à l'autre, ce qui provoquerait des éditions inutiles."""
    node, _, planet = tr.node(invasion.node).rpartition(" (")
    return planet, node


def invasion_value(ctx: Context, invasion: Invasion) -> str:
    """Un camp par ligne. Pas de progression : browse.wf ne la donne pas. Contre les Infestés, la ligne de l'attaquant
    n'apparaît que s'il donne quelque chose."""
    lines = []
    for camp, fallback in ((invasion.attacker, "⚔️"), (invasion.defender, "🛡️")):
        reward = rewards(camp.reward, ctx.tr)
        if camp is invasion.attacker and invasion.vs_infested and reward == "—":
            continue
        lines.append(f"{ctx.faction_emojis.get(camp.faction, fallback)} **{ctx.tr.faction(camp.faction)}** : {reward}")
    return "\n".join(lines)


def render_invasions(ctx: Context) -> list[discord.Embed]:
    if ctx.invasions is None:
        return worldstate_missing("invasions", COLORS["invasions"], ctx)
    embed = header(discord.Embed(color=COLORS["invasions"]), "Invasions", "invasions")
    fields = [(invasion_title(invasion, ctx.tr), invasion_value(ctx, invasion))
              for invasion in sorted(ctx.invasions, key=lambda invasion: invasion_sort_key(invasion, ctx.tr))]
    if not fields:
        embed.description = "Aucune invasion en cours."
    return [finish(add_fields(embed, fields), ctx, "invasions")]


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


def alert_value(alert: Alert, ctx: Context, event_tags: set[str]) -> str:
    return (f"{ctx.tr.faction(alert.faction)} niv. {alert.min_level or '?'}-{alert.max_level or '?'}"
            f" · fin {ts(alert.expiry)}"
            f"\nRécompenses : {alert_rewards(alert.reward, ctx.tr, alert.tag in event_tags)}")


def render_alertes(ctx: Context) -> list[discord.Embed]:
    if ctx.world is None:
        return worldstate_missing("alertes", COLORS["alertes"], ctx)
    embed = header(discord.Embed(color=COLORS["alertes"]), "Alertes", "alertes")
    event_tags = {event.tag for event in active(ctx.world.events, ctx.now) if event.tag}
    fields = [(f"{ctx.tr.node(alert.node)} — {ctx.tr.mission(alert.mission)}", alert_value(alert, ctx, event_tags))
              for alert in active(ctx.world.alerts, ctx.now)]
    if not fields:
        embed.description = "Aucune alerte en cours."
    return [finish(add_fields(embed, fields), ctx, "worldstate")]


def event_value(event: Event, ctx: Context) -> str:
    value = f"Fin {ts(event.expiry)}"
    if event.goal > 1 and not event.personal:
        value += f" · Progression {number(event.count)} / {number(event.goal)}"
    if event.node:
        value += f"\nLieu : {ctx.tr.node(event.node)}"
    reward = rewards(event.reward, ctx.tr)
    if reward != "—":
        value += f"\nRécompenses : {reward}"
    return value


def render_events(ctx: Context) -> list[discord.Embed]:
    if ctx.world is None:
        return worldstate_missing("events", COLORS["events"], ctx)
    embed = header(discord.Embed(color=COLORS["events"]), "Events", "events")
    fields = [(ctx.tr.text(event.name) or event.tag or "Event", event_value(event, ctx))
              for event in active(ctx.world.events, ctx.now)]
    if not fields:
        embed.description = "Aucun event en cours."
    return [finish(add_fields(embed, fields), ctx, "worldstate")]


def _cycle_value(cycle: cycles.Cycle, icon: str) -> str:
    return f"{icon} **{cycle.state.capitalize()}** — {cycle.next_state} {ts(cycle.ends_at)} ({ts(cycle.ends_at, 't')})"


def render_cycles(ctx: Context) -> list[discord.Embed]:
    embed = header(discord.Embed(color=COLORS["cycles"]), "Cycles", "cycles")
    if ctx.bounty_end:
        cetus = cycles.cetus(ctx.bounty_end, ctx.now)
        cambion = cycles.cambion(ctx.bounty_end, ctx.now)
        cetus_value = _cycle_value(cetus, "☀️" if cetus.state == "jour" else "🌙")
        cambion_value = _cycle_value(cambion, "🟠" if cambion.state == "Fass" else "🟣")
    else:
        cetus_value = cambion_value = "Inconnu pour le moment"
    vallis = cycles.vallis(ctx.now)
    embed.add_field(name="Cetus — Plaines d'Eidolon", value=cetus_value, inline=False)
    embed.add_field(name="Vallée Orbis", value=_cycle_value(vallis, "🔥" if vallis.state == "chaud" else "❄️"), inline=False)
    embed.add_field(name="Puits Cambion", value=cambion_value, inline=False)
    # Cetus / Cambion sont extrapolés à partir de la dernière fin de primes connue : jamais « périmés ».
    return [finish(embed, ctx)]


def render_circuit(ctx: Context) -> list[discord.Embed]:
    embed = header(discord.Embed(color=COLORS["circuit"]), "Circuit (Duviri)", "circuit")
    embed.description = f"Nouvelle rotation {ts(cycles.circuit_rotation_end(ctx.now))}"
    warframes, incarnon = cycles.circuit_choices(ctx.now)
    fields = [("Circuit", ", ".join(warframes)), ("Circuit — Route de l'Acier", ", ".join(incarnon))]
    # Rotation calculée : pas de données périmées possibles.
    return [finish(add_fields(embed, fields), ctx)]


def render_baro(ctx: Context) -> list[discord.Embed]:
    if ctx.world is None:
        return worldstate_missing("baro", COLORS["baro"], ctx)
    embed = header(discord.Embed(color=COLORS["baro"]), "Baro Ki'Teer", "baro")
    trader = ctx.world.trader
    if trader is None:
        embed.description = "Pas d'info sur Baro Ki'Teer pour le moment."
        return [finish(embed, ctx, "worldstate")]
    relay = ctx.tr.node(trader.node)
    if ctx.now < trader.activation:
        embed.description = f"Arrive {ts(trader.activation)} ({ts(trader.activation, 'f')}) au **{relay}**"
    elif ctx.now < trader.expiry:
        embed.description = f"Présent au **{relay}**, repart {ts(trader.expiry)} ({ts(trader.expiry, 'f')})"
        lines = [f"{ctx.tr.item(path)} — {ducats} ducats, {number(credits)} crédits" for path, ducats, credits in trader.manifest]
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
    return [finish(embed, ctx, "worldstate")]


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
    """Tous les sujets. Le sujet en cours est indiqué au traducteur pour situer les identifiants inconnus."""
    rendered = {}
    for topic, renderer in RENDERERS.items():
        ctx.tr.topic = topic
        rendered[topic] = renderer(ctx)
    ctx.tr.topic = ""
    return rendered


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
    if ctx.bounty_end:
        candidates.append(cycles.cetus(ctx.bounty_end, ctx.now).ends_at)
    candidates.append(cycles.circuit_rotation_end(ctx.now))
    if ctx.world is not None:
        candidates += [entry.expiry for entry in (*ctx.world.fissures, *ctx.world.alerts, *ctx.world.events)]
        if ctx.world.trader:
            candidates += [ctx.world.trader.activation, ctx.world.trader.expiry]
    future = [when for when in candidates if when > ctx.now]
    return min(future, default=None)
