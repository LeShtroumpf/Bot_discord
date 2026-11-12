import datetime as dt
import json

import pytest

from cephalon.index import INDEX_FILE, MINIMUMS, Index, IndexError_, compact, normalize

BUILT_AT = dt.datetime(2026, 11, 12, 8, 0, tzinfo=dt.UTC)


def names(resolution) -> list[str]:
    return [entry["name"] for entry in resolution.matches]


# --- Noms ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("Continuité Accrue", "continuite accrue"), ("  RHINO   prime ", "rhino prime"), ("Arch-Gun", "arch gun"),
    ("Statuette Noggle - Rhino Prime", "statuette noggle rhino prime"), ("Éviscérateur", "eviscerateur"), ("!!!", ""),
])
def test_normalize(text, expected):
    assert normalize(text) == expected


@pytest.mark.parametrize("family, query, expected", [
    ("mods", "Primed Continuity", ["Primed Continuity"]),     # nom anglais exact
    ("mods", "Continuité Accrue", ["Primed Continuity"]),     # nom français exact
    ("mods", "continuite accrue", ["Primed Continuity"]),     # accents et majuscules oubliés
    ("mods", "continuité accru", ["Primed Continuity"]),      # faute de frappe
    ("items", "rino prime", ["Rhino Prime"]),
    ("items", "braton prme", ["Braton Prime"]),
    ("items", "Rhino", ["Rhino"]),                            # nom exact, même si d'autres le contiennent
])
def test_resolve_finds_the_item(index, family, query, expected):
    resolution = index.resolve(family, query)
    assert names(resolution) == expected and resolution.candidates == []


def test_resolve_gives_the_french_name_too(index):
    entry = index.resolve("mods", "continuite accrue").matches[0]
    assert (entry["name"], entry["name_fr"]) == ("Primed Continuity", "Continuité Accrue")
    assert entry["unique"] == "/Lotus/Upgrades/Mods/Warframe/Expert/AvatarAbilityDurationModExpert"


def test_resolve_returns_the_real_mod_before_the_flawed_one(index):
    matches = index.resolve("mods", "continuite").matches
    assert [entry["name"] for entry in matches] == ["Continuity", "Continuity"]
    assert "/Beginner/" not in matches[0]["unique"] and "/Beginner/" in matches[1]["unique"]


def test_internal_variants_of_a_mod_are_left_out(index, index_lists):
    """L'API liste trois « Serration » : le Défectueux (+40 %), une variante interne (+90 %) et le vrai (+165 %)."""
    assert sum(mod["name"] == "Serration" for mod in index_lists["mods"]) == 3
    matches = index.resolve("mods", "Dentelure").matches
    assert [entry["unique"].rsplit("/", 1)[-1] for entry in matches] == ["WeaponDamageAmountMod", "WeaponDamageAmountModBeginner"]
    assert [entry["unique"].rsplit("/", 1)[-1] for entry in index.resolve("items", "Serration").matches] == [
        "WeaponDamageAmountMod", "WeaponDamageAmountModBeginner"]
    effects = [row["effect_at_max_rank"] for row in index.search_mods(["Damage"], "rifle").rows if row["name"] == "Serration"]
    assert effects == ["+165% Damage"]


def test_expert_mod_with_its_own_name_is_kept(index):
    """« Primed Continuity » est sous /Expert/ mais ne double aucun mod du même nom."""
    assert names(index.resolve("mods", "Primed Continuity")) == ["Primed Continuity"]


def test_resolve_limits_items_with_the_same_name(index, monkeypatch):
    monkeypatch.setattr("cephalon.index.MAX_MATCHES", 1)
    assert len(index.resolve("mods", "continuite").matches) == 1


def test_resolve_proposes_candidates_when_unsure(index):
    resolution = index.resolve("mods", "continu")
    assert resolution.matches == []
    assert "Continuité" in resolution.candidates and len(resolution.candidates) <= 10
    partial = index.resolve("items", "prime rhino")  # mots dans le désordre : pas de certitude
    assert partial.matches == [] and partial.candidates == ["Rhino Prime"]


def test_resolve_finds_nothing_close(index):
    resolution = index.resolve("mods", "zorglub suprême")
    assert (resolution.matches, resolution.candidates) == ([], [])
    assert index.resolve("items", "  ").matches == []


def test_cosmetics_are_found_by_exact_name_only(index):
    assert names(index.resolve("items", "Casque Rhino Prime")) == ["Rhino Prime Helmet"]
    assert names(index.resolve("items", "rhino prime helmet")) == ["Rhino Prime Helmet"]
    close = index.resolve("items", "casque rino prime")  # faute de frappe sur un cosmétique : pas de rapprochement
    assert close.matches == [] and not any("Casque" in name or "Glyphe" in name for name in close.candidates)


def test_mods_are_also_items(index):
    """/items couvre les mods : get_item sur un nom de mod doit le trouver."""
    assert names(index.resolve("items", "continuité accrue")) == ["Primed Continuity"]


# --- Mods par effet -----------------------------------------------------------------------------------------

def test_search_mods_by_effect(index):
    result = index.search_mods(["Ability Duration"])
    found = [row["name"] for row in result.rows]
    assert {"Continuity", "Primed Continuity", "Narrow Minded", "Constitution"} <= set(found)
    assert found.index("Continuity") < found.index("Chaos Sphere")  # les effets courts avant un augment qui cite la durée
    assert result.total == len(result.rows) <= 10
    continuity = next(row for row in result.rows if row["name"] == "Continuity")
    assert continuity == {"name": "Continuity", "name_fr": "Continuité", "type": "Warframe Mod", "compatibility": "WARFRAME",
                          "polarity": "madurai", "rarity": "Rare", "max_rank": 5, "effect_at_max_rank": "+30% Ability Duration"}


def test_search_mods_leaves_flawed_mods_out(index):
    effects = [row["effect_at_max_rank"] for row in index.search_mods(["Ability Duration"]).rows if row["name"] == "Continuity"]
    assert effects == ["+30% Ability Duration"]


def test_search_mods_needs_every_keyword_when_possible(index):
    both = index.search_mods(["Ability Duration", "Ability Range"])
    assert [row["name"] for row in both.rows] == ["Narrow Minded"] and "partial_match" not in both.rows[0]


def test_search_mods_falls_back_to_partial_matches(index):
    result = index.search_mods(["Ability Duration", "Zorglub"])
    assert result.total > 1 and all(row["partial_match"] for row in result.rows)


def test_search_mods_filters_on_type_or_compatibility(index):
    rifle = index.search_mods(["Damage"], "rifle")
    assert rifle.rows and all("rifle" in normalize(f"{row['type']} {row['compatibility']}") for row in rifle.rows)
    assert "Serration" in [row["name"] for row in rifle.rows]
    assert index.search_mods(["Ability Duration"], "Shotgun").total == 0


def test_search_mods_by_french_or_english_name(index):
    assert [row["name"] for row in index.search_mods(["dentelure"]).rows][0] == "Serration"


def test_search_mods_without_result(index):
    result = index.search_mods(["Zorglub"])
    assert (result.total, result.rows, result.sources) == (0, [], [])
    assert index.search_mods(["  "]).total == 0


def test_search_results_are_limited_but_counted(index, monkeypatch):
    monkeypatch.setattr("cephalon.index.MAX_RESULTS", 3)
    result = index.search_mods(["Ability"])
    assert len(result.rows) == 3 < result.total


def test_search_sources_are_wiki_pages_of_the_first_results(index):
    sources = index.search_mods(["Ability Duration"]).sources
    assert 1 <= len(sources) <= 5 and all(url.startswith("https://wiki.warframe.com/w/") for _, url in sources)


# --- Classements --------------------------------------------------------------------------------------------

def test_rank_weapons(index):
    result = index.rank_weapons("criticalChance", category="Primary")
    assert [(row["name"], row["criticalChance"]) for row in result.rows[:5]] == [
        ("Dread", 0.5), ("Kuva Chakkhurr", 0.5), ("Lenz", 0.5), ("Prisma Lenz", 0.5), ("Paris Prime", 0.45)]
    assert set(result.rows[0]) == {"name", "category", "type", "masteryReq", "criticalChance"}
    assert all(row["category"] == "Primary" for row in result.rows) and result.total == 14


def test_rank_weapons_ascending(index):
    fastest = index.rank_weapons("reloadTime", descending=False).rows
    assert [row["reloadTime"] for row in fastest] == sorted(row["reloadTime"] for row in fastest)


def test_rank_weapons_filters(index):
    bows = index.rank_weapons("criticalChance", kind="bow", max_mastery=8)
    assert [row["name"] for row in bows.rows] == ["Dread", "Lenz", "Paris Prime"]
    assert index.rank_weapons("criticalChance", category="Arch-Gun").rows[0]["name"] == "Imperator Vandal"
    assert index.rank_weapons("criticalChance", category="Melee", kind="Bow").total == 0


def test_weapons_without_the_stat_are_left_out(index):
    """Les armes de mêlée n'ont pas de chargeur."""
    assert all(row["category"] != "Melee" for row in index.rank_weapons("magazineSize").rows)
    assert index.rank_weapons("magazineSize", category="Melee").total == 0


def test_rank_warframes(index):
    result = index.rank_warframes("armor")
    assert [(row["name"], row["armor"]) for row in result.rows[:4]] == [
        ("Valkyr Prime", 1000), ("Qorvex", 875), ("Valkyr", 855), ("Lavos", 575)]
    assert "Bonewidow" not in [row["name"] for row in result.rows] and result.total == 10  # Warframes seulement
    assert result.sources[0][1].startswith("https://wiki.warframe.com/w/")


def test_rank_warframes_by_kind_and_order(index):
    assert [row["name"] for row in index.rank_warframes("armor", kind="Necramech").rows] == ["Bonewidow", "Voidrig"]
    assert [row["name"] for row in index.rank_warframes("armor", descending=False, kind="Archwing").rows] == ["Itzal", "Odonata"]
    assert {"Rhino", "Rhino Prime"} <= {row["name"] for row in index.rank_warframes("health").rows}  # Prime et normale


# --- Construction -------------------------------------------------------------------------------------------

def test_summary_and_age(index):
    assert index.summary() == "27 mods, 22 armes, 14 Warframes, 87 objets"
    assert index.age(BUILT_AT + dt.timedelta(hours=3)) == 3 * 3600


@pytest.mark.parametrize("broken", ["mods", "mods_fr", "items", "items_fr", "weapons", "warframes"])
def test_a_missing_or_short_list_fails_the_whole_build(index_lists, broken):
    minimums = {name: 1 for name in MINIMUMS}
    Index.build(index_lists, BUILT_AT, minimums)
    for value in ([], None, {"error": "oups"}):
        with pytest.raises(IndexError_, match=broken):
            Index.build({**index_lists, broken: value}, BUILT_AT, minimums)


def test_real_lists_are_expected_to_be_large(index_lists):
    with pytest.raises(IndexError_, match="mods"):
        Index.build(index_lists, BUILT_AT)  # 53 mods : bien moins que la vraie liste


def test_odd_rows_are_skipped(index_lists):
    lists = {**index_lists, "mods": index_lists["mods"] + ["texte", {"name": "Sans identifiant"}, {"uniqueName": "/sans/nom"}],
             "weapons": index_lists["weapons"] + [{"name": "Arme étrange", "uniqueName": "/x", "criticalChance": "beaucoup"}]}
    data = compact(lists, {})
    assert len(data["mods"]) == 27  # 53 lignes valides, moins 15 mods Défectueux et 11 variantes internes
    assert "criticalChance" not in next(weapon for weapon in data["weapons"] if weapon["name"] == "Arme étrange")


# --- Fichier ------------------------------------------------------------------------------------------------

def test_index_is_written_and_read_back(index, tmp_path):
    index.write(tmp_path / "state")
    assert [path.name for path in (tmp_path / "state").iterdir()] == [INDEX_FILE]  # pas de fichier temporaire restant
    read = Index.read(tmp_path / "state")
    assert read.built_at == index.built_at and read.summary() == index.summary()
    assert [entry["name"] for entry in read.resolve("items", "rino prime").matches] == ["Rhino Prime"]
    assert read.search_mods(["Ability Duration"]).rows == index.search_mods(["Ability Duration"]).rows


def test_missing_index_file(tmp_path):
    assert Index.read(tmp_path) is None


def test_index_file_of_another_version_is_ignored(index, tmp_path):
    index.write(tmp_path)
    saved = json.loads((tmp_path / INDEX_FILE).read_text(encoding="utf-8"))
    (tmp_path / INDEX_FILE).write_text(json.dumps({**saved, "version": 0}), encoding="utf-8")
    assert Index.read(tmp_path) is None


@pytest.mark.parametrize("content", [
    "{ pas du json", "[]", "{}", '{"version": 2, "built_at": "hier", "data": {}}',
    '{"version": 2, "built_at": "2026-11-12T08:00:00", "data": {}}',
    '{"version": 2, "built_at": "2026-11-12T08:00:00+00:00", "data": {"names": []}}',
    '{"version": 2, "built_at": "2026-11-12T08:00:00+00:00", "data": {"names": [["mods"]], "mods": [], "weapons": [], "warframes": []}}',
])
def test_unreadable_index_file(tmp_path, content):
    (tmp_path / INDEX_FILE).write_text(content, encoding="utf-8")
    with pytest.raises(IndexError_):
        Index.read(tmp_path)


def test_index_file_that_is_a_directory(tmp_path):
    (tmp_path / INDEX_FILE).mkdir()
    with pytest.raises(IndexError_):
        Index.read(tmp_path)
