import copy
import datetime as dt

import discord

from warframe.arbitrations import Tier
from warframe.render import (ICONS, TOPICS, Context, add_fields, invasion_progress, join_lines, next_deadline, render_all,
                             render_alertes, render_baro, render_circuit, render_events, render_fissures, render_invasions)
from warframe.arbitrations import DEFAULT_EMOJIS
from warframe.cycles import circuit_rotation_end
from warframe.translations import Translator


def ws_date(when: dt.datetime) -> str:
    return when.isoformat().replace("+00:00", "Z")


def all_text(embeds: list[discord.Embed]) -> str:
    """Texte visible des embeds (sans les URL d'icônes, qui contiennent légitimement /Lotus/)."""
    parts = []
    for e in embeds:
        parts += [e.title or "", e.description or "", e.author.name or "", e.footer.text or ""]
        parts += [f"{f.name}\n{f.value}" for f in e.fields]
    return "\n".join(parts)


def test_render_all_real_data(worldstate, translator, schedule, tiers, now):
    ctx = Context(now=now, tr=translator, worldstate=worldstate, worldstate_at=now, schedule=schedule, tiers=tiers)
    rendered = render_all(ctx)
    assert list(rendered) == list(TOPICS)
    for topic, embeds in rendered.items():
        assert embeds, topic
        for embed in embeds:
            assert len(embed) <= 6000 and len(embed.fields) <= 25, topic
    text = all_text([e for embeds in rendered.values() for e in embeds])
    for raw in ("SolNode", "MT_", "FC_", "VoidT", "/Lotus/"):
        assert raw not in text, raw  # tout est traduit
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
    assert rendered["events"][0].thumbnail.url == ICONS["events"]  # l'API ne donne pas d'icône d'event
    current = schedule.current(now)
    tier = tiers[current.node].tier if current.node in tiers else "F"
    assert rendered["arbitrage"][0].title == f"{tier} Tier | {translator.node(current.node)}"  # titre sans emoji


def test_fissures_grouped_by_era(worldstate, translator, now):
    ctx = Context(now=now, tr=translator, worldstate=worldstate, worldstate_at=now)
    normal = render_fissures(ctx)[0]
    eras = [f.name.split(" (")[0] for f in normal.fields]
    order = ["Lith", "Meso", "Neo", "Axi", "Requiem", "Omnia"]
    assert eras == sorted(eras, key=order.index)


def fissure(**extra) -> dict:
    return {"node": "Mot (Le Néant)", "missionType": "Survie", "enemy": "Corrompus", "enemyKey": "Corrupted", "tier": "Axi",
            "tierNum": 4, **extra}


def test_fissures_split_by_kind(now):
    end = ws_date(now + dt.timedelta(hours=1))
    worldstate = {"fissures": [fissure(expiry=end), fissure(expiry=end, isHard=True), fissure(expiry=end, isStorm=True),
                               fissure(expiry=end, isStorm=True, isHard=True)]}
    normal, hard, storms = render_fissures(Context(now=now, tr=Translator(), worldstate=worldstate, worldstate_at=now))
    assert [e.fields[0].name for e in (normal, hard, storms)] == ["Axi (1)", "Axi (1)", "Axi (2)"]


def test_fissure_crossfire_label_is_repaired(now):
    worldstate = {"fissures": [fissure(expiry=ws_date(now + dt.timedelta(hours=1)), enemy="Feux Croisés Extermination",
                                       enemyKey="Crossfire")]}
    field = render_fissures(Context(now=now, tr=Translator(), worldstate=worldstate, worldstate_at=now))[0].fields[0]
    assert "— Feux Croisés — fin" in field.value


def test_expired_entries_disappear(worldstate, translator, now):
    later = now + dt.timedelta(days=3)
    ctx = Context(now=later, tr=translator, worldstate=worldstate, worldstate_at=now, stale=True)
    fissures = render_fissures(ctx)
    assert all(e.description == "Aucune fissure en cours." for e in fissures)
    assert "Données du" in fissures[0].footer.text  # données périmées signalées


def test_without_worldstate(translator, schedule, tiers, now):
    rendered = render_all(Context(now=now, tr=translator, schedule=schedule, tiers=tiers))
    assert rendered["fissures"][0].description == "Les données Warframe arrivent…"
    assert "Tier |" in rendered["arbitrage"][0].title       # arbitrage calculé sans worldstate
    assert rendered["cycles"][0].fields[1].value.count("<t:") == 2  # Vallée Orbis calculée


def test_without_translations_or_schedule(worldstate, now):
    rendered = render_all(Context(now=now, tr=Translator(), worldstate=worldstate, worldstate_at=now))
    assert rendered["arbitrage"][0].description == "Planning des arbitrages indisponible pour le moment."
    assert rendered["fissures"][0].fields  # les noms viennent de l'API : rien à traduire


def test_baro_present_with_big_inventory(worldstate, translator, now):
    ws = copy.deepcopy(worldstate)
    ws["voidTraders"][0].update(activation=ws_date(now - dt.timedelta(hours=1)), expiry=ws_date(now + dt.timedelta(days=2)),
                                inventory=[{"item": f"Truc {i}", "ducats": 300, "credits": 150000} for i in range(120)])
    embed = render_baro(Context(now=now, tr=translator, worldstate=ws, worldstate_at=now))[0]
    assert embed.description.startswith(f"Présent au **{ws['voidTraders'][0]['location']}**")
    assert embed.fields[0].name.startswith("Inventaire (1/")
    assert "150 000 crédits" in embed.fields[0].value
    assert len(embed) <= 6000


def test_baro_coming(worldstate, translator, now):
    embed = render_baro(Context(now=now, tr=translator, worldstate=worldstate, worldstate_at=now))[0]
    assert embed.description.startswith("Arrive <t:")


def test_baro_inventory_without_prices(now):
    trader = {"activation": ws_date(now - dt.timedelta(hours=1)), "expiry": ws_date(now + dt.timedelta(days=2)), "location": "Relai",
              "inventory": [{"item": "Truc", "ducats": None, "credits": None}]}
    embed = render_baro(Context(now=now, tr=Translator(), worldstate={"voidTraders": [trader]}, worldstate_at=now))[0]
    assert embed.fields[0].value == "Truc — 0 ducats, 0 crédits"


def test_circuit_is_computed_without_worldstate():
    now = dt.datetime(2026, 11, 5, 8, 0, tzinfo=dt.UTC)
    embed = render_circuit(Context(now=now, tr=Translator()))[0]
    assert str(int(circuit_rotation_end(now).timestamp())) in embed.description
    assert [f.name for f in embed.fields] == ["Circuit", "Circuit — Route de l'Acier"]
    assert embed.fields[0].value == "Ivara, Inaros, Titania"
    assert embed.footer.text is None


def test_circuit_is_never_stale():
    now = dt.datetime(2026, 11, 5, 8, 0, tzinfo=dt.UTC)
    embed = render_circuit(Context(now=now, tr=Translator(), worldstate={}, worldstate_at=now - dt.timedelta(hours=1), stale=True))[0]
    assert embed.footer.text is None


def test_events_shows_score_node_and_rewards(now):
    event = {"expiry": ws_date(now + dt.timedelta(days=1)), "description": "Opération", "maximumScore": 1000, "currentScore": 250,
             "node": "Mot (Le Néant)", "rewards": [{"credits": 5000}]}
    field = render_events(Context(now=now, tr=Translator(), worldstate={"events": [event]}, worldstate_at=now))[0].fields[0]
    assert field.name == "Opération"
    assert "Progression 250 / 1 000" in field.value
    assert "Lieu : Mot (Le Néant)" in field.value
    assert "Récompenses : 5 000 crédits" in field.value


def test_personal_event_hides_the_score(now):
    event = {"expiry": ws_date(now + dt.timedelta(days=1)), "description": "Perso", "maximumScore": 1000, "isPersonal": True}
    field = render_events(Context(now=now, tr=Translator(), worldstate={"events": [event]}, worldstate_at=now))[0].fields[0]
    assert "Progression" not in field.value


def test_event_with_null_scores_hides_the_score(now):
    event = {"expiry": ws_date(now + dt.timedelta(days=1)), "description": "Purge", "maximumScore": None, "currentScore": None}
    field = render_events(Context(now=now, tr=Translator(), worldstate={"events": [event]}, worldstate_at=now))[0].fields[0]
    assert field.name == "Purge"
    assert "Progression" not in field.value


def test_event_with_null_current_score_starts_at_zero(now):
    event = {"expiry": ws_date(now + dt.timedelta(days=1)), "description": "Opération", "maximumScore": 1000, "currentScore": None}
    field = render_events(Context(now=now, tr=Translator(), worldstate={"events": [event]}, worldstate_at=now))[0].fields[0]
    assert "Progression 0 / 1 000" in field.value


def test_no_event(now):
    embed = render_events(Context(now=now, tr=Translator(), worldstate={"events": []}, worldstate_at=now))[0]
    assert embed.description == "Aucun event en cours."


def test_join_lines_truncates():
    text = join_lines([f"ligne {i:03d}" for i in range(500)], limit=200)
    assert len(text) <= 200
    assert text.endswith("autres")


def test_add_fields_respects_limits():
    embed = add_fields(discord.Embed(title="x"), [(f"champ {i}", "v" * 300) for i in range(60)])
    assert len(embed.fields) <= 25
    assert len(embed) <= 6000
    assert embed.fields[-1].name == "…"


def test_invasion_progress():
    assert invasion_progress(invasion(attacker="Corpus", count=0)) == 50
    assert invasion_progress(invasion(attacker="Grineer", count=50)) == 75
    assert invasion_progress(invasion(attacker="Infested", count=-50)) == 50
    assert invasion_progress(invasion(attacker="Grineer", count=500)) == 100


FACTIONS = {"Infested": "Infesté", "Corpus": "Corpus", "Grineer": "Grineer"}


def invasions_embed(now, *invasions, faction_emojis=None) -> discord.Embed:
    ctx = Context(now=now, tr=Translator(), worldstate={"invasions": list(invasions)}, worldstate_at=now, schedule=None, tiers={},
                  faction_emojis=faction_emojis or {})
    return render_invasions(ctx)[0]


def invasion(node="Regna (Pluton)", attacker="Infested", defender="Corpus", count=-3, goal=100, attacker_reward=None, **extra) -> dict:
    return {"node": node, "count": count, "requiredRuns": goal,
            "attacker": {"factionKey": attacker, "faction": FACTIONS[attacker], "reward": attacker_reward},
            "defender": {"factionKey": defender, "faction": FACTIONS[defender],
                         "reward": {"countedItems": [{"type": "Fieldron", "count": 3}]}}, **extra}


def test_invasion_against_infested_shows_defender_advance(now):
    value = invasions_embed(now, invasion()).fields[0].value
    assert value == "🛡️ **Corpus** : 3× Fieldron\nAvancement : 3 % · contre les Infestés"


def test_invasion_against_infested_keeps_an_attacker_reward(now):
    reward = {"countedItems": [{"type": "Mutagene", "count": 1}]}
    value = invasions_embed(now, invasion(attacker_reward=reward)).fields[0].value
    assert value.splitlines()[0] == "⚔️ **Infesté** : 1× Mutagene"


def test_invasion_between_factions_shows_both_sides(now):
    value = invasions_embed(now, invasion(attacker="Grineer", count=90)).fields[0].value
    assert value.splitlines()[2] == "Progression : Grineer 95 % · Corpus 5 %"
    assert value.startswith("⚔️ **Grineer**")


def test_invasion_uses_faction_emojis(now):
    emojis = {"Corpus": "<:corpus:1>", "Grineer": "<:grineer:2>"}
    value = invasions_embed(now, invasion(attacker="Grineer"), faction_emojis=emojis).fields[0].value
    assert value.splitlines()[0].startswith("<:grineer:2> **Grineer**")
    assert value.splitlines()[1].startswith("<:corpus:1> **Corpus**")


def test_invasions_sorted_by_planet_then_node(now):
    nodes = ["Regna (Pluton)", "Neso (Neptune)", "Acheron (Pluton)", "Casta (Cérès)"]
    embed = invasions_embed(now, *[invasion(node=node) for node in nodes])
    assert [field.name for field in embed.fields] == ["Casta (Cérès)", "Neso (Neptune)", "Acheron (Pluton)", "Regna (Pluton)"]


def test_invasion_title_shows_the_api_description(now):
    embed = invasions_embed(now, invasion(desc="Offensive Grineer"))
    assert embed.fields[0].name == "Regna (Pluton) — Offensive Grineer"


def test_invasions_order_does_not_depend_on_the_api(now):
    invasions = [invasion(node=node) for node in ("Hydra (Pluton)", "Outer Terminus (Pluton)", "Minthe (Pluton)")]
    assert invasions_embed(now, *invasions).to_dict() == invasions_embed(now, *reversed(invasions)).to_dict()


def test_completed_invasions_are_hidden(now):
    embed = invasions_embed(now, invasion(completed=True), invasion(node="Casta (Cérès)"))
    assert [field.name for field in embed.fields] == ["Casta (Cérès)"]


def test_next_deadline(worldstate, translator, schedule, now):
    ctx = Context(now=now, tr=translator, worldstate=worldstate, worldstate_at=now, schedule=schedule)
    deadline = next_deadline(ctx)
    assert now < deadline <= schedule.current(now).end
    assert next_deadline(Context(now=now, tr=translator)) is not None  # Vallée Orbis toujours connue


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


def test_footer_only_when_stale(worldstate, translator, now):
    fresh = render_fissures(Context(now=now, tr=translator, worldstate=worldstate, worldstate_at=now))[0]
    assert fresh.footer.text is None  # plus de « Worldstate officiel de Warframe »


def test_blank_line_between_era_groups(worldstate, translator, now):
    embed = render_fissures(Context(now=now, tr=translator, worldstate=worldstate, worldstate_at=now))[0]
    assert len(embed.fields) >= 2
    assert all(f.value.endswith("\n\u200b") for f in embed.fields[:-1])
    assert not embed.fields[-1].value.endswith("\u200b")  # pas d'espace inutile après le dernier groupe


def test_arbitrage_blank_lines_between_blocks(translator, schedule, tiers, now):
    embed = render_all(Context(now=now, tr=translator, schedule=schedule, tiers=tiers))["arbitrage"][0]
    assert embed.description.endswith("\n\u200b")                      # après « Se termine »
    assert embed.fields[0].value.endswith("\n\u200b") and embed.fields[1].value.endswith("\n\u200b")
    assert embed.fields[2].value.endswith("\n\u200b")                  # entre prochains et notables
    assert not embed.fields[3].value.endswith("\u200b")


def alert(now, item, count, tag="RoadToTauEvent") -> dict:
    return {"expiry": ws_date(now + dt.timedelta(hours=1)), "tag": tag,
            "mission": {"reward": {"credits": 17000, "countedItems": [{"type": item, "count": count}]}}}


def event(now, expiry=dt.timedelta(days=1)) -> dict:
    return {"expiry": ws_date(now + expiry), "tag": "RoadToTauEvent"}


def alerts_value(now, *alerts, events=()) -> str:
    ctx = Context(now=now, tr=Translator(), worldstate={"alerts": list(alerts), "events": list(events)}, worldstate_at=now,
                  schedule=None, tiers={})
    return render_alertes(ctx)[0].fields[0].value


def test_alert_of_an_event_shows_steel_path_without_credits(now):
    value = alerts_value(now, alert(now, "Moonflesh", 50), events=[event(now)])
    assert "Récompenses : 50 (sp 75) × Moonflesh" in value
    assert "crédits" not in value


def test_alert_outside_events_keeps_a_single_quantity(now):
    value = alerts_value(now, alert(now, "Forma", 3, tag="LotusGift"), events=[event(now)])
    assert "Récompenses : 3× Forma, 17 000 crédits" in value


def test_alert_of_a_finished_event_has_no_steel_path(now):
    value = alerts_value(now, alert(now, "Moonflesh", 50), events=[event(now, dt.timedelta(days=-1))])
    assert "Récompenses : 50× Moonflesh, 17 000 crédits" in value
