import datetime as dt

from warframe import DATA_DIR
from warframe.arbitrations import (DEFAULT_EMOJIS, Arbitration, Schedule, Tier, load_tier_emojis, noteworthy,
                                   read_cache)

T0 = 1793538000  # 2026-11-01 12:00 UTC


def at(seconds: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(T0 + seconds, tz=dt.UTC)


def make_schedule(*nodes: str) -> Schedule:
    return Schedule([(T0 + 3600 * i, node) for i, node in enumerate(nodes)])


def test_parse_ignores_garbage():
    schedule = Schedule.parse(f"{T0},SolNode1\n\nnimporte quoi\n{T0 + 3600},SolNode2\n")
    assert [node for _, node in schedule.entries] == ["SolNode1", "SolNode2"]


def test_current_changes_on_the_hour():
    schedule = make_schedule("A", "B")
    assert schedule.current(at(0)).node == "A"
    assert schedule.current(at(3599)).node == "A"
    assert schedule.current(at(3600)).node == "B"
    assert schedule.current(at(3600)).end == at(7200)
    assert schedule.current(at(-1)) is None
    assert schedule.current(at(7200)) is None  # planning épuisé


def test_upcoming_and_noteworthy():
    schedule = make_schedule("now", "x1", "x2", "s_soon", "y", "sp_later", "a_later", "f_later", "s_last")
    tiers = {"s_soon": Tier("S"), "sp_later": Tier("SP"), "a_later": Tier("A"), "s_last": Tier("S")}
    now = at(600)
    upcoming = schedule.upcoming(now, dt.timedelta(hours=3))
    assert [a.node for a in upcoming] == ["x1", "x2", "s_soon"]
    notable = noteworthy(schedule, tiers, now, dt.timedelta(hours=24), exclude=upcoming)
    assert [a.node for a in notable] == ["sp_later", "a_later", "s_last"]  # sans s_soon (déjà listé), sans F
    assert len(noteworthy(schedule, tiers, now, dt.timedelta(hours=24), exclude=[], limit=2)) == 2


def test_arbitration_equality_used_for_exclusion():
    assert Arbitration(at(0), "A") == Arbitration(at(0), "A")


def test_tiers_file(tiers):
    assert len(tiers) == 49
    assert tiers["SolNode711"] == Tier("SP")           # Terrorem
    assert tiers["SolNode23"].tier == "S"              # Cytherean
    assert tiers["SolNode149"] == Tier("A", saryn=True)  # Casta*
    assert tiers.get("SolNode999", Tier()).tier == "F"


def test_real_schedule_matches_tier_list(schedule, tiers, now):
    current = schedule.current(now)
    assert current is not None
    assert now < current.end <= now + dt.timedelta(hours=1)


def test_read_cache_absent(tmp_path):
    assert read_cache(tmp_path) is None


def test_tier_emojis_file(tmp_path):
    assert load_tier_emojis(DATA_DIR / "arbitration_tiers.json") == DEFAULT_EMOJIS
    partial = tmp_path / "tiers.json"
    partial.write_text('{"emojis": {"S": "<:tierS:1>"}, "tiers": {}}', encoding="utf-8")
    emojis = load_tier_emojis(partial)
    assert emojis["S"] == "<:tierS:1>" and emojis["SP"] == DEFAULT_EMOJIS["SP"]  # complété par défaut
