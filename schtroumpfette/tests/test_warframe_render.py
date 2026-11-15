import dataclasses
import datetime as dt

import discord

from warframe.arbitrations import DEFAULT_EMOJIS, Tier
from warframe.browsewf import INFESTED, Alert, Camp, Event, Fissure, Invasion, Reward, Trader, World
from warframe.cycles import circuit_rotation_end
from warframe.render import (ICONS, TOPICS, Context, add_fields, join_lines, next_deadline, render_all, render_alertes,
                             render_baro, render_circuit, render_events, render_fissures, render_invasions)
from warframe.translations import Translator

FORMA = "/Lotus/Types/Items/MiscItems/Forma"
MOONFLESH = "/Lotus/Types/Gameplay/Events/RoadToTauEvent/RoadToTauEventResource"


def all_text(embeds: list[discord.Embed]) -> str:
    """Texte visible des embeds (sans les URL d'icônes, qui contiennent légitimement /Lotus/)."""
    parts = []
    for e in embeds:
        parts += [e.title or "", e.description or "", e.author.name or "", e.footer.text or ""]
        parts += [f"{f.name}\n{f.value}" for f in e.fields]
    return "\n".join(parts)


def real_context(sources, translator, now, **extra) -> Context:
    fetched = {name: now for name in sources}
    return Context(now=now, tr=translator, world=sources["worldstate"], invasions=sources["invasions"],
                   bounty_end=sources["primes"], fetched_at=fetched, **extra)


def world_context(now, tr=None, **lists) -> Context:
    return Context(now=now, tr=tr or Translator(), world=World(**lists), fetched_at={"worldstate": now})


def test_render_all_real_data(sources, translator, schedule, tiers, now):
    rendered = render_all(real_context(sources, translator, now, schedule=schedule, tiers=tiers))
    assert list(rendered) == list(TOPICS)
    for topic, embeds in rendered.items():
        assert embeds, topic
        for embed in embeds:
            assert len(embed) <= 6000 and len(embed.fields) <= 25, topic
    text = all_text([e for embeds in rendered.values() for e in embeds])
    for raw in ("SolNode", "CrewBattleNode", "MT_", "FC_", "VoidT", "/Lotus/", "invasion/"):
        assert raw not in text, raw  # tout est traduit
    assert translator.missing == set()  # aucun identifiant inconnu dans les données réelles
    assert translator.topic == ""
    assert [e.author.name for e in rendered["fissures"]] == [
        "Fissures du Néant", "Fissures — Route de l'Acier", "Tempêtes du Néant (Railjack)"]
    assert rendered["cycles"][0].thumbnail.url is None  # pas de miniature pour les cycles
    for topic, embeds in rendered.items():  # chaque message a son en-tête et sa miniature
        if topic == "cycles":
            continue
        for embed in embeds:
            hosts = ("https://browse.wf/Lotus/", "https://wiki.warframe.com/images/",
                     "https://raw.githubusercontent.com/LeShtroumpf/Bot_discord/master/")
            assert embed.author.name and embed.thumbnail.url.startswith(hosts)
    assert rendered["events"][0].thumbnail.url == ICONS["events"]
    current = schedule.current(now)
    tier = tiers[current.node].tier if current.node in tiers else "F"
    assert rendered["arbitrage"][0].title == f"{tier} Tier | {translator.node(current.node)}"  # titre sans emoji
    assert all(e.footer.text is None for embeds in rendered.values() for e in embeds)  # rien de périmé


def test_real_names_are_french(sources, translator, now):
    rendered = render_all(real_context(sources, translator, now))
    text = all_text([e for embeds in rendered.values() for e in embeds])
    for name in ("Fractures Thermia", "Opération d'Époque : Vers Tau", "50 (sp 75) × Chair de Lune", "Offensive Grineer",
                 "Épidémie Infestés", "Siège Corpus", "Secteurs de Tuvul (Zariman) — Cascade du néant",
                 "Relais Strata (Terre)", "3× Forma, 10 000 crédits", "Lieu : Vallée Orbis (Vénus)"):
        assert name in text, name


def test_fissures_grouped_by_era(sources, translator, now):
    normal = render_fissures(real_context(sources, translator, now))[0]
    assert [f.name.split(" (")[0] for f in normal.fields] == ["Lith", "Meso", "Neo", "Axi", "Requiem", "Omnia"]


def fissure(now, node="SolNode450", **extra) -> Fissure:
    return Fissure(**{"node": node, "mission": "MT_SURVIVAL", "era": "VoidT4", "expiry": now + dt.timedelta(hours=1), **extra})


def test_fissures_split_by_kind(now):
    fissures = (fissure(now), fissure(now, hard=True), fissure(now, storm=True, mission=None),
                fissure(now, storm=True, hard=True, mission=None))
    normal, hard, storms = render_fissures(world_context(now, fissures=fissures))
    assert [e.fields[0].name for e in (normal, hard, storms)] == ["Axi (1)", "Axi (1)", "Axi (2)"]


def test_storm_mission_comes_from_the_node(sources, translator, now):
    storms = render_fissures(real_context(sources, translator, now))[2]
    text = all_text([storms])
    assert "Amas Bendar (Proxima de la Terre) — Escarmouche — Grineer" in text
    assert "Railjack —" not in text


def test_fissure_order_does_not_depend_on_the_source(sources, translator, now):
    world = sources["worldstate"]
    shuffled = dataclasses.replace(world, fissures=tuple(reversed(world.fissures)))
    a = render_fissures(real_context(sources, translator, now))
    b = render_fissures(real_context({**sources, "worldstate": shuffled}, translator, now))
    assert [e.to_dict() for e in a] == [e.to_dict() for e in b]


def test_expired_entries_disappear(sources, translator, now):
    later = now + dt.timedelta(days=3)
    ctx = real_context(sources, translator, later, stale={"worldstate"})
    ctx.fetched_at = {name: now for name in sources}  # dernier succès il y a 3 jours
    fissures = render_fissures(ctx)
    assert all(e.description == "Aucune fissure en cours." for e in fissures)
    assert fissures[0].footer.text == "⚠️ Données du 15/11 à 15:30 : worldstate injoignable"  # heure de Paris


def test_stale_warning_only_on_the_failing_source(sources, translator, now):
    rendered = render_all(real_context(sources, translator, now, stale={"invasions"}))
    assert "worldstate injoignable" in rendered["invasions"][0].footer.text
    for topic in ("fissures", "alertes", "events", "baro", "cycles", "circuit", "arbitrage"):
        assert all(e.footer.text is None for e in rendered[topic]), topic


def test_without_data(translator, schedule, tiers, now):
    rendered = render_all(Context(now=now, tr=translator, schedule=schedule, tiers=tiers))
    for topic in ("fissures", "invasions", "alertes", "events", "baro"):
        assert rendered[topic][0].description == "Les données Warframe arrivent…", topic
    assert "Tier |" in rendered["arbitrage"][0].title       # arbitrage calculé sans worldstate
    assert rendered["cycles"][0].fields[0].value == "Inconnu pour le moment"
    assert rendered["cycles"][0].fields[1].value.count("<t:") == 2  # Vallée Orbis calculée


def test_without_translations_or_schedule(sources, now):
    tr = Translator()
    rendered = render_all(real_context(sources, tr, now))
    assert rendered["arbitrage"][0].description == "Planning des arbitrages indisponible pour le moment."
    assert rendered["fissures"][0].fields  # noms reconstitués, jamais d'erreur
    assert tr.missing == set()             # tables pas encore chargées : rien à signaler


def test_unknown_identifiers_are_noted_with_their_topic(translator, now):
    alert = Alert(node="SolNode9999", mission="MT_RAILJACK", faction="FC_GRINEER", min_level=1, max_level=2,
                  reward=Reward(), tag="", expiry=now + dt.timedelta(hours=1))
    ctx = world_context(now, translator, alerts=(alert,))
    render_all(ctx)
    assert ("alertes", "SolNode9999", "Sol Node9999") in translator.missing


# --- Baro ------------------------------------------------------------------------------------------------------

BARO_ITEMS = (("/Lotus/StoreItems/Upgrades/Mods/Pistol/Expert/WeaponRecoilReductionModExpert", 300, 220000),
              ("/Lotus/StoreItems/Types/Game/Projections/T4VoidProjectionBaroAkmagnusPrimeBronze", 125, 55000),
              ("/Lotus/Types/StoreItems/Boosters/ModDropChanceBooster3DayStoreItem", 500, 175000),
              ("/Lotus/StoreItems/Types/BoosterPacks/BaroTreasureBox", 0, 50000))


def trader(now, manifest=BARO_ITEMS, node="PlutoHUB", start=-1, end=47) -> Trader:
    return Trader(node=node, activation=now + dt.timedelta(hours=start), expiry=now + dt.timedelta(hours=end), manifest=manifest)


def test_baro_present_with_translated_inventory(translator, now):
    embed = render_baro(world_context(now, translator, trader=trader(now)))[0]
    assert embed.description.startswith("Présent au **Relais Orcus (Pluton)**")
    assert embed.fields[0].value.splitlines() == [
        "Mains Stables Accrues — 300 ducats, 220 000 crédits", "Relique Axi M5 — 125 ducats, 55 000 crédits",
        "Booster de Chances de Mods de 3 jours — 500 ducats, 175 000 crédits", "Surplus du Néant — 0 ducats, 50 000 crédits"]
    assert translator.missing == set()


def test_baro_present_with_big_inventory(translator, now):
    manifest = tuple((f"/Lotus/StoreItems/Truc{i}", 300, 150000) for i in range(120))
    embed = render_baro(world_context(now, translator, trader=trader(now, manifest)))[0]
    assert embed.fields[0].name.startswith("Inventaire (1/")
    assert "150 000 crédits" in embed.fields[0].value
    assert len(embed) <= 6000


def test_baro_coming_real_data(sources, translator, now):
    embed = render_baro(real_context(sources, translator, now))[0]
    assert embed.description.startswith("Arrive <t:") and "**Relais Strata (Terre)**" in embed.description


def test_baro_gone(translator, now):
    embed = render_baro(world_context(now, translator, trader=trader(now, start=-48, end=-1)))[0]
    assert embed.description.startswith("Baro Ki'Teer est reparti.")


def test_no_baro_at_all(now):
    assert render_baro(world_context(now))[0].description == "Pas d'info sur Baro Ki'Teer pour le moment."


# --- Circuit -----------------------------------------------------------------------------------------------------

def test_circuit_is_computed_without_worldstate():
    now = dt.datetime(2026, 11, 5, 8, 0, tzinfo=dt.UTC)
    embed = render_circuit(Context(now=now, tr=Translator()))[0]
    assert str(int(circuit_rotation_end(now).timestamp())) in embed.description
    assert [f.name for f in embed.fields] == ["Circuit", "Circuit — Route de l'Acier"]
    assert embed.fields[0].value == "Ivara, Inaros, Titania"
    assert embed.footer.text is None


def test_circuit_is_never_stale():
    now = dt.datetime(2026, 11, 5, 8, 0, tzinfo=dt.UTC)
    ctx = Context(now=now, tr=Translator(), fetched_at={"worldstate": now - dt.timedelta(hours=1)}, stale={"worldstate"})
    assert render_circuit(ctx)[0].footer.text is None


# --- Events ------------------------------------------------------------------------------------------------------

def event(now, name="/Lotus/Language/Events/Operation", goal=1000, count=250, personal=False, node="SolNode450",
          reward=Reward(credits=5000), tag="Op", expiry=dt.timedelta(days=1)) -> Event:
    return Event(name=name, tag=tag, node=node, count=count, goal=goal, personal=personal, reward=reward, expiry=now + expiry)


def events_field(now, *events, tr=None):
    return render_events(world_context(now, tr, events=events))[0].fields[0]


def test_events_shows_score_node_and_rewards(translator, now):
    tr = Translator({"nodes": translator.nodes}, {"/Lotus/Language/Events/Operation": "Opération"})
    field = events_field(now, event(now), tr=tr)
    assert field.name == "Opération"
    assert "Progression 250 / 1 000" in field.value
    assert "Lieu : Col de Tyane (Mars)" in field.value
    assert "Récompenses : 5 000 crédits" in field.value


def test_personal_event_hides_the_score(now):
    assert "Progression" not in events_field(now, event(now, personal=True)).value


def test_event_without_goal_hides_the_score(now):
    field = events_field(now, event(now, goal=0, count=98, node=None, reward=Reward()))
    assert field.value.startswith("Fin <t:") and "\n" not in field.value  # ni progression, ni lieu, ni récompense


def test_no_event(now):
    assert render_events(world_context(now))[0].description == "Aucun event en cours."


# --- Invasions -----------------------------------------------------------------------------------------------------

def invasion(node="SolNode450", attacker=INFESTED, defender="FC_CORPUS", attacker_reward=Reward(), invasion_id="1") -> Invasion:
    fieldron = Reward(counted=(("/Lotus/Types/Items/Research/EnergyComponent", 3),))
    return Invasion(id=invasion_id, node=node, attacker=Camp(attacker, attacker_reward), defender=Camp(defender, fieldron))


def invasions_embed(now, *invasions, tr=None, faction_emojis=None) -> discord.Embed:
    ctx = Context(now=now, tr=tr or Translator(), invasions=list(invasions), faction_emojis=faction_emojis or {})
    return render_invasions(ctx)[0]


def test_invasions_real_data(sources, translator, now):
    embed = render_invasions(real_context(sources, translator, now))[0]
    names = [f.name for f in embed.fields]
    assert len(names) == 6
    assert sum(name.endswith("— Épidémie Infestés") for name in names) == 3
    assert all("Progression" not in f.value and "Avancement" not in f.value for f in embed.fields)


def test_invasion_against_infested_hides_an_empty_attacker(translator, now):
    value = invasions_embed(now, invasion(), tr=translator).fields[0].value
    assert value == "🛡️ **Corpus** : 3× Fieldron"


def test_invasion_against_infested_keeps_an_attacker_reward(translator, now):
    reward = Reward(counted=(("/Lotus/Types/Items/Research/EnergyComponent", 1),))
    value = invasions_embed(now, invasion(attacker_reward=reward), tr=translator).fields[0].value
    assert value.splitlines()[0] == "⚔️ **Infesté** : 1× Fieldron"


def test_invasion_between_factions_shows_both_sides(translator, now):
    reward = Reward(counted=(("/Lotus/Types/Items/Research/ChemComponent", 3),))
    field = invasions_embed(now, invasion(attacker="FC_GRINEER", attacker_reward=reward), tr=translator).fields[0]
    assert field.name == "Col de Tyane (Mars) — Offensive Grineer"
    assert field.value == "⚔️ **Grineer** : 3× Injecteur de Détonite\n🛡️ **Corpus** : 3× Fieldron"


def test_invasion_uses_faction_emojis(now):
    emojis = {"FC_CORPUS": "<:corpus:1>", "FC_GRINEER": "<:grineer:2>"}
    value = invasions_embed(now, invasion(attacker="FC_GRINEER"), faction_emojis=emojis).fields[0].value
    assert value.splitlines()[0].startswith("<:grineer:2> **")
    assert value.splitlines()[1].startswith("<:corpus:1> **")


def test_invasions_sorted_by_planet_then_node(now):
    tr = Translator({"nodes": {"A": ["Regna", "Pluton", None, None], "B": ["Neso", "Neptune", None, None],
                               "C": ["Acheron", "Pluton", None, None], "D": ["Casta", "Cérès", None, None]}},
                    {"invasion/FC_INFESTATION": "Épidémie"})
    embed = invasions_embed(now, *[invasion(node=key, invasion_id=key) for key in "ABCD"], tr=tr)
    assert [field.name for field in embed.fields] == [
        "Casta (Cérès) — Épidémie", "Neso (Neptune) — Épidémie", "Acheron (Pluton) — Épidémie", "Regna (Pluton) — Épidémie"]


def test_invasions_order_does_not_depend_on_the_source(sources, translator, now):
    a = render_invasions(real_context(sources, translator, now))[0]
    b = render_invasions(real_context({**sources, "invasions": list(reversed(sources["invasions"]))}, translator, now))[0]
    assert a.to_dict() == b.to_dict()


def test_no_invasion(now):
    assert invasions_embed(now).description == "Aucune invasion en cours."


# --- Alertes -------------------------------------------------------------------------------------------------------

def alert(now, item, count, tag="RoadToTauEvent") -> Alert:
    return Alert(node="SolNode450", mission="MT_DEFENSE", faction="FC_INFESTATION", min_level=50, max_level=50,
                 reward=Reward(counted=((item, count),), credits=17000), tag=tag, expiry=now + dt.timedelta(hours=1))


def alerts_value(now, translator, *alerts, events=()) -> str:
    return render_alertes(world_context(now, translator, alerts=alerts, events=events))[0].fields[0].value


def test_alert_of_an_event_shows_steel_path_without_credits(translator, now):
    value = alerts_value(now, translator, alert(now, MOONFLESH, 50), events=(event(now, tag="RoadToTauEvent"),))
    assert "Récompenses : 50 (sp 75) × Chair de Lune" in value
    assert "crédits" not in value


def test_alert_outside_events_keeps_a_single_quantity(translator, now):
    value = alerts_value(now, translator, alert(now, FORMA, 3, tag="LotusGift"), events=(event(now, tag="RoadToTauEvent"),))
    assert "Récompenses : 3× Forma, 17 000 crédits" in value


def test_alert_of_a_finished_event_has_no_steel_path(translator, now):
    finished = event(now, tag="RoadToTauEvent", expiry=dt.timedelta(days=-1))
    value = alerts_value(now, translator, alert(now, MOONFLESH, 50), events=(finished,))
    assert "Récompenses : 50× Chair de Lune, 17 000 crédits" in value


def test_alert_title_and_levels(translator, now):
    embed = render_alertes(world_context(now, translator, alerts=(alert(now, FORMA, 3, tag="LotusGift"),)))[0]
    assert embed.fields[0].name == "Col de Tyane (Mars) — Défense"
    assert embed.fields[0].value.startswith("Infesté niv. 50-50 · fin <t:")


# --- Échéances, pied de page, mise en page --------------------------------------------------------------------------

def test_next_deadline(sources, translator, schedule, now):
    deadline = next_deadline(real_context(sources, translator, now, schedule=schedule))
    first_fissure = min(f.expiry for f in sources["worldstate"].fissures)
    assert now < deadline <= min(schedule.current(now).end, first_fissure)
    assert next_deadline(Context(now=now, tr=translator)) is not None  # Vallée Orbis toujours connue


def test_footer_only_when_stale(sources, translator, now):
    fresh = render_fissures(real_context(sources, translator, now))[0]
    assert fresh.footer.text is None


def test_blank_line_between_era_groups(sources, translator, now):
    embed = render_fissures(real_context(sources, translator, now))[0]
    assert len(embed.fields) >= 2
    assert all(f.value.endswith("\n​") for f in embed.fields[:-1])
    assert not embed.fields[-1].value.endswith("​")  # pas d'espace inutile après le dernier groupe


def test_join_lines_truncates():
    text = join_lines([f"ligne {i:03d}" for i in range(500)], limit=200)
    assert len(text) <= 200
    assert text.endswith("autres")


def test_add_fields_respects_limits():
    embed = add_fields(discord.Embed(title="x"), [(f"champ {i}", "v" * 300) for i in range(60)])
    assert len(embed.fields) <= 25
    assert len(embed) <= 6000
    assert embed.fields[-1].name == "…"


def test_tier_emojis_in_arbitrage(translator, schedule, now):
    custom = {"S": "<:tierS:1>", "A": "<:tierA:2>", "B": "<:tierB:3>", "C": "<:tierC:4>", "D": "<:tierD:5>",
              "SP": "<:tierSP:6>", "F": "<:tierF:7>"}
    tiers = {a.node: Tier("SP") for a in schedule.upcoming(now - dt.timedelta(hours=2), dt.timedelta(hours=40))}
    embed = render_all(Context(now=now, tr=translator, schedule=schedule, tiers=tiers, tier_emojis=custom))["arbitrage"][0]
    assert embed.title.startswith("SP Tier | ")                      # titre en texte, sans emoji
    assert embed.fields[2].value.startswith("<:tierSP:6> **Tier | ")


def test_unicode_emojis_keep_the_letter(translator, schedule, tiers, now):
    embed = render_all(Context(now=now, tr=translator, schedule=schedule, tiers=tiers))["arbitrage"][0]
    first = embed.fields[2].value.splitlines()[0]
    assert first.split(" ", 1)[0] in DEFAULT_EMOJIS.values()
    assert " Tier | " in first and first.split(" ")[1].startswith("**")


def test_repo_icons_exist():
    """Les icônes servies depuis GitHub doivent exister dans le dépôt (sinon miniature vide une fois sur master)."""
    from pathlib import Path

    from warframe import DATA_DIR
    from warframe.render import ICONS, REPO_ICONS
    for url in filter(None, ICONS.values()):
        if url.startswith(REPO_ICONS):
            assert (DATA_DIR / "icons" / url[len(REPO_ICONS):]).is_file(), url
    assert Path(DATA_DIR / "icons" / "AlertTriangle.png").is_file()


def test_arbitrage_blank_lines_between_blocks(translator, schedule, tiers, now):
    embed = render_all(Context(now=now, tr=translator, schedule=schedule, tiers=tiers))["arbitrage"][0]
    assert embed.description.endswith("\n\u200b")                      # après « Se termine »
    assert embed.fields[0].value.endswith("\n\u200b") and embed.fields[1].value.endswith("\n\u200b")
    assert embed.fields[2].value.endswith("\n\u200b")                  # entre prochains et notables
    assert not embed.fields[3].value.endswith("\u200b")
