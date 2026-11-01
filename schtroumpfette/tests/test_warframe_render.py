import copy
import datetime as dt

import discord

from warframe.arbitrations import Tier
from warframe.render import (TOPICS, Context, add_fields, invasion_progress, join_lines, next_deadline, render_all,
                             render_baro, render_fissures)
from warframe.arbitrations import DEFAULT_EMOJIS
from warframe.translations import Translator


def ws_date(when: dt.datetime) -> dict:
    return {"$date": {"$numberLong": str(int(when.timestamp() * 1000))}}


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
    assert rendered["events"][0].thumbnail.url.endswith(worldstate["Goals"][0]["Icon"])  # icône propre à l'event
    current = schedule.current(now)
    tier = tiers[current.node].tier if current.node in tiers else "F"
    assert rendered["arbitrage"][0].title == f"{DEFAULT_EMOJIS[tier]} {tier} Tier | {translator.node(current.node)}"


def test_fissures_grouped_by_era(worldstate, translator, now):
    ctx = Context(now=now, tr=translator, worldstate=worldstate, worldstate_at=now)
    normal = render_fissures(ctx)[0]
    eras = [f.name.split(" (")[0] for f in normal.fields]
    order = ["Lith", "Meso", "Méso", "Neo", "Néo", "Axi", "Requiem", "Omnia"]
    assert eras == sorted(eras, key=order.index)


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
    assert rendered["fissures"][0].fields  # identifiants reconstitués, pas de plantage


def test_baro_present_with_big_inventory(worldstate, translator, now):
    ws = copy.deepcopy(worldstate)
    ws["VoidTraders"][0].update(Activation=ws_date(now - dt.timedelta(hours=1)), Expiry=ws_date(now + dt.timedelta(days=2)),
                                Manifest=[{"ItemType": f"/Lotus/StoreItems/Types/Items/Truc{i}", "PrimePrice": 300,
                                           "RegularPrice": 150000} for i in range(120)])
    embed = render_baro(Context(now=now, tr=translator, worldstate=ws, worldstate_at=now))[0]
    assert embed.description.startswith("Présent au **Relais Kronia (Saturne)**")
    assert embed.fields[0].name.startswith("Inventaire (1/")
    assert "150 000 crédits" in embed.fields[0].value
    assert len(embed) <= 6000


def test_baro_coming(worldstate, translator, now):
    embed = render_baro(Context(now=now, tr=translator, worldstate=worldstate, worldstate_at=now))[0]
    assert embed.description.startswith("Arrive <t:")


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
    assert invasion_progress({"Count": 0, "Goal": 100, "Faction": "FC_CORPUS"}) == 50
    assert invasion_progress({"Count": 50, "Goal": 100, "Faction": "FC_GRINEER"}) == 75
    assert invasion_progress({"Count": -50, "Goal": 100, "Faction": "FC_INFESTATION"}) == 50
    assert invasion_progress({"Count": 500, "Goal": 100, "Faction": "FC_GRINEER"}) == 100


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
    assert embed.title.startswith("<:tierSP:6> Tier | ")             # la lettre est dans l'emoji
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
