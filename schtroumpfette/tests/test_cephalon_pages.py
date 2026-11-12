import json
import os

import pytest

from cephalon import pages as pages_module
from cephalon.pages import PAGES_FILE, Pages, PagesError
from conftest import ARGON_CRYSTAL, wiki_export


def write(directory, name, *pages, mtime=None, **kwargs):
    path = directory / name
    path.write_text(wiki_export(*pages, **kwargs), encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def pages(wiki_dir):
    loaded, report = Pages.reload(wiki_dir)
    assert report.problems == [] and report.fatal is None
    return loaded


# --- Traitement des exports ---------------------------------------------------------------------------------

def test_first_load(wiki_dir):
    pages, report = Pages.reload(wiki_dir)
    assert report.added == [("Argon Crystal", 4), ("Damage", 4), ("Status Effect", 1)]
    assert report.modified == report.removed == [] and (report.pages, report.sections) == (3, 9)
    assert pages.summary() == "3 pages, 9 sections"
    assert pages.pages["Argon Crystal"]["url"] == "https://wiki.warframe.com/w/Argon_Crystal"
    assert pages.pages["Damage"]["file"] == "mechanics.xml"


def test_second_load_reports_changes(wiki_dir, pages):
    (wiki_dir / "argon.xml").unlink()
    write(wiki_dir, "mechanics.xml", ("Damage", "== Autre ==\ntexte"),
          ("Status Effect", "== Overview ==\nA status effect applies a debuff.\n"))
    write(wiki_dir, "cell.xml", ("Orokin Cell", "Une ressource."))
    loaded, report = Pages.reload(wiki_dir, pages)
    assert report.added == [("Orokin Cell", 1)] and report.modified == [("Damage", 1)]
    assert report.removed == [("Argon Crystal", 4)] and report.problems == []
    assert sorted(loaded.pages) == ["Damage", "Orokin Cell", "Status Effect"]


def test_unchanged_load(wiki_dir, pages):
    _, report = Pages.reload(wiki_dir, pages)
    assert report.added == report.modified == report.removed == report.problems == []


def test_failed_file_keeps_its_previous_pages(wiki_dir, pages):
    (wiki_dir / "mechanics.xml").write_text("<mediawiki><page>", encoding="utf-8")
    loaded, report = Pages.reload(wiki_dir, pages)
    assert report.problems[0].startswith("mechanics.xml : XML illisible")
    assert sorted(loaded.pages) == ["Argon Crystal", "Damage", "Status Effect"] and report.removed == []


def test_empty_page_keeps_its_previous_version(wiki_dir, pages):
    write(wiki_dir, "argon.xml", ("Argon Crystal", "{{Infobox|name=Argon}}[[Category:Resources]]"))
    loaded, report = Pages.reload(wiki_dir, pages)
    assert report.problems == ["argon.xml : page vide après nettoyage : Argon Crystal"]
    assert loaded.pages["Argon Crystal"] == pages.pages["Argon Crystal"] and report.modified == []


def test_redirect_too_big_wrong_domain_and_not_an_export(wiki_dir, monkeypatch):
    write(wiki_dir, "redirect.xml", ("Argon", "#REDIRECT [[Argon Crystal]]", True))
    write(wiki_dir, "fandom.xml", ("Fandom", "texte"), base="https://warframe.fandom.com/wiki/WARFRAME_Wiki")
    (wiki_dir / "page.xml").write_text("<html>Not found</html>", encoding="utf-8")
    (wiki_dir / "notes.txt").write_text("ignoré", encoding="utf-8")
    monkeypatch.setattr(pages_module, "PAGE_MAX_BYTES", 900)  # argon.xml : 979 octets
    loaded, report = Pages.reload(wiki_dir)
    assert sorted(report.problems) == sorted([
        "argon.xml : fichier trop gros (> 0 Mo)",
        "redirect.xml : redirection ignorée : Argon (exporte plutôt la page cible)",
        "fandom.xml : domaine inattendu : warframe.fandom.com (seul wiki.warframe.com est accepté)",
        "page.xml : pas un export du wiki"])
    assert sorted(loaded.pages) == ["Damage", "Status Effect"]


def test_same_title_in_two_files_keeps_the_most_recent(wiki_dir):
    write(wiki_dir, "argon.xml", ("Argon Crystal", ARGON_CRYSTAL), mtime=1000)
    write(wiki_dir, "argon-new.xml", ("Argon Crystal", "Nouvelle version."), mtime=2000)
    loaded, report = Pages.reload(wiki_dir)
    assert report.problems == ["Argon Crystal présent dans argon.xml et argon-new.xml, gardé : argon-new.xml (le plus récent)"]
    assert loaded.pages["Argon Crystal"]["sections"][0]["text"] == "Nouvelle version."


def test_empty_and_missing_directory(tmp_path):
    (tmp_path / "pages").mkdir()
    loaded, report = Pages.reload(tmp_path / "pages")
    assert len(loaded) == 0 and report.fatal is None and report.pages == 0
    loaded, report = Pages.reload(tmp_path / "absent")
    assert loaded is None and report.fatal.startswith("dossier `absent` introuvable")


# --- Fichier ------------------------------------------------------------------------------------------------

def test_write_and_read(tmp_path, pages):
    pages.write(tmp_path)
    again = Pages.read(tmp_path)
    assert again.pages == pages.pages and not (tmp_path / (PAGES_FILE + ".tmp")).exists()


def test_read_missing_unreadable_and_old_file(tmp_path):
    assert Pages.read(tmp_path) is None
    (tmp_path / PAGES_FILE).write_text("{", encoding="utf-8")
    with pytest.raises(PagesError, match="illisibles"):
        Pages.read(tmp_path)
    (tmp_path / PAGES_FILE).write_text(json.dumps({"version": 0, "pages": []}), encoding="utf-8")
    with pytest.raises(PagesError, match="relance /cephalon_pages"):
        Pages.read(tmp_path)
    (tmp_path / PAGES_FILE).write_text(json.dumps({"version": 1, "pages": [{"titre": "x"}]}), encoding="utf-8")
    with pytest.raises(PagesError, match="forme inattendue"):
        Pages.read(tmp_path)


# --- Recherche ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("query", ["Argon Crystal", "argon crystal", "argon cristal", "Argon Crystals", "farm argon crystal"])
def test_search_by_title(pages, query):
    results = pages.search(query)
    assert results[0]["page"] == "Argon Crystal" and results[0]["found_by"] == "title"
    assert results[0]["sections"][1] == {"title": "Acquisition", "level": 2, "chars": len(pages.section_text("Argon Crystal", 1))}


def test_search_by_section_title(pages):
    result = pages.search("heat")[0]
    assert result["page"] == "Damage" and result["found_by"] == "section" and result["matching_sections"] == ["Heat"]


def test_search_in_the_text(pages):
    result = pages.search("Smeeta Kavat")[0]
    assert result["page"] == "Argon Crystal" and result["found_by"] == "text"
    assert result["matching_sections"] == ["Acquisition"]


def test_search_in_the_text_with_partial_words(pages):
    results = pages.search("armor strip zzzz")
    assert results[0]["page"] == "Damage" and results[0]["matching_sections"] == ["Heat"]


def test_search_finds_nothing(pages):
    assert pages.search("Helminth") == [] and pages.search("the") == []


def test_search_returns_at_most_three_pages(tmp_path):
    directory = tmp_path / "pages"
    directory.mkdir()
    write(directory, "many.xml", *((f"Page {i}", "Orokin text") for i in range(5)))
    loaded, _ = Pages.reload(directory)
    assert len(loaded.search("orokin")) == 3


# --- Lecture ------------------------------------------------------------------------------------------------

def test_read_introduction(pages):
    result, source = pages.read_section("argon crystal", None)
    assert result["page"] == "Argon Crystal" and result["section"] == "Introduction" and result["truncated"] is False
    assert result["text"].startswith("Argon Crystals are rare")
    assert source == ("Argon Crystal", "https://wiki.warframe.com/w/Argon_Crystal")


def test_read_section_with_its_subsections(pages):
    result, source = pages.read_section("Argon Crystal", "acquisition")
    assert "Best farmed on Ani" in result["text"] and "=== Drop table ===\nSource | Chance" in result["text"]
    assert "Notes" not in result["text"]
    assert source == ("Argon Crystal — Acquisition", "https://wiki.warframe.com/w/Argon_Crystal#Acquisition")


def test_read_missing_page_or_section(pages):
    result, source = pages.read_section("Helminth", None)
    assert source is None and "search_pages" in result["error"]
    result, source = pages.read_section("Damage", "Armor")
    assert source is None and result["sections"] == ["Introduction", "Damage Types", "Status Effect", "Heat"]


def test_page_without_introduction_reads_its_first_section(pages):
    result, source = pages.read_section("Status Effect", None)
    assert result["section"] == "Overview" and source[1].endswith("#Overview")


def test_long_section_is_truncated(pages, monkeypatch):
    monkeypatch.setattr(pages_module, "SECTION_LIMIT", 20)
    result, _ = pages.read_section("Argon Crystal", None)
    assert result["truncated"] is True and result["text"] == "Argon Crystals are r\n(suite tronquée)"


def test_duplicate_section_anchor(tmp_path):
    directory = tmp_path / "pages"
    directory.mkdir()
    write(directory, "notes.xml", ("Damage", "== Notes ==\na\n== Notes ==\nb"))
    loaded, _ = Pages.reload(directory)
    _, source = loaded.read_section("Damage", "Notes (2)")
    assert source[1] == "https://wiki.warframe.com/w/Damage#Notes_2"


# --- Vrai export (extrait réduit) ---------------------------------------------------------------------------

@pytest.fixture
def real_pages(tmp_path, real_export):
    directory = tmp_path / "real"
    directory.mkdir()
    (directory / "wiki_export.xml").write_bytes(real_export)
    loaded, report = Pages.reload(directory)
    assert report.problems == [] and report.added == [("Disruption", 3), ("Status Effect", 8)]
    return loaded


@pytest.mark.parametrize("query, page, how, sections", [
    ("status effect", "Status Effect", "title", None),
    ("disruption", "Disruption", "title", None),
    ("demolisher drops", "Disruption", "section", ["Demolisher Drops"]),
    ("Vessel Capillaries", "Disruption", "text", ["Demolisher Drops"]),
    ("Corrosive armor", "Status Effect", "text", ["General"]),
])
def test_real_search(real_pages, query, page, how, sections):
    results = real_pages.search(query)
    assert len(results) == 1 and results[0]["page"] == page and results[0]["found_by"] == how
    assert results[0].get("matching_sections") == sections


def test_real_section(real_pages):
    result, source = real_pages.read_section("Disruption", "Demolisher Drops")
    assert "Kuva Fortress | Kuva x 50 | 100%" in result["text"]
    assert source == ("Disruption — Demolisher Drops", "https://wiki.warframe.com/w/Disruption#Demolisher_Drops")
    result, _ = real_pages.read_section("Status Effect", "Status Effects")  # section vide lue avec ses sous-sections
    assert result["text"].startswith("=== General ===\nDamage Type | Status Effect Internal Name | Status Effects")
