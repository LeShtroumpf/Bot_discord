import pytest

from cephalon.wikitext import ExportError, clean, page_url, parse_export, split_sections
from conftest import ARGON_CRYSTAL, wiki_export


# --- Lecture de l'export ------------------------------------------------------------------------------------

def test_export_with_two_pages_and_a_redirect():
    export = parse_export(wiki_export(("Damage", "== A ==\nx"), ("Argon", "y"), ("Old", "#REDIRECT [[Damage]]", True))
                          .encode())
    assert export.host == "wiki.warframe.com"
    assert [(page.title, page.redirect) for page in export.pages] == [("Damage", False), ("Argon", False), ("Old", True)]
    assert export.pages[0].text == "== A ==\nx"


def test_last_revision_is_read():
    data = wiki_export(("Damage", "ancienne")).replace(
        "</revision>", '</revision><revision><id>2</id><text xml:space="preserve">récente</text></revision>')
    assert parse_export(data.encode()).pages[0].text == "récente"


def test_empty_export_has_no_page():
    export = parse_export(wiki_export().encode())
    assert export.pages == [] and export.base == "https://wiki.warframe.com/"


@pytest.mark.parametrize("data, reason", [
    (b"<mediawiki><page>", "XML illisible"),
    (b"<html><body>Not found</body></html>", "pas un export du wiki"),
])
def test_unreadable_export(data, reason):
    with pytest.raises(ExportError, match=reason):
        parse_export(data)


def test_page_url():
    assert page_url("Argon Crystal") == "https://wiki.warframe.com/w/Argon_Crystal"
    assert page_url("Damage", "Status Effect") == "https://wiki.warframe.com/w/Damage#Status_Effect"
    assert page_url("Orokin Cell/Farming") == "https://wiki.warframe.com/w/Orokin_Cell/Farming"


# --- Nettoyage ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("wikitext, expected", [
    ("[[Void]]", "Void"),
    ("[[Orokin Vault|vaults]]", "vaults"),
    ("[[Damage#Heat]]", "Damage"),
    ("[[#Notes]]", "Notes"),
    ("[[File:Argon.png|thumb|Un [[cristal]] du [[Void]]]]texte", "texte"),
    ("[[Category:Resources]]", ""),
    ("[[fr:Cristal d'Argon]]", ""),
    ("[[:Category:Resources|les ressources]]", "les ressources"),
    ("[https://example.com le site]", "le site"),
    ("[https://example.com]", ""),
])
def test_links(wikitext, expected):
    assert clean(wikitext) == expected


@pytest.mark.parametrize("wikitext, expected", [
    ("{{D|Heat}} et {{Proc|Cold}}", "Heat et Cold"),           # modèles en ligne connus
    ("{{M|[[Serration]]}}", "Serration"),                      # lien dans un modèle
    ("{{Infobox|name = X|image = Y.png}}texte", "texte"),      # infobox retirée
    ("{{Navbox|{{D|Heat}}|{{D|Cold}}}}texte", "texte"),         # modèles imbriqués
    ("{{Main|Damage/Overview}}texte", "texte"),                 # bandeau de renvoi retiré
    ("{{Stub}}texte", "texte"),
    ("{{#if: x | y }}texte", "texte"),                          # fonction de l'analyseur
    ("{{Inconnu|court}}", "court"),                              # modèle court inconnu : texte gardé
    ("{{Inconnu|un|deux|trois}}texte", "texte"),                # trop d'arguments : retiré
    ("{{ouvert sans fin texte", ""),
    ("{{Text|red|'''attention'''}}", "attention"),               # texte dans le dernier argument
    ("{{Transclude|Damage#Empyrean}}texte", "texte"),           # contenu d'une autre page : retiré
    ("{{Ver/Lu|29.5}}texte", "texte"),                          # sous-modèle inconnu : retiré
    ("{{ver|27.2}}", "Update 27.2"),
    ("{{:Fire Walker}}texte", "texte"),                         # transclusion d'une page
])
def test_templates(wikitext, expected):
    assert clean(wikitext) == expected


def test_markup():
    text = clean("'''Gras''' et ''italique''<ref name=a>source</ref><ref name=b /><!-- note -->&nbsp;fin__NOTOC__<br/>"
                 "<span style='x'>balise</span>\n<gallery>\nA.png\n</gallery>")
    assert text == "Gras et italique fin\nbalise"


def test_lists():
    assert clean("* un\n** deux\n# trois\n: indenté\n;terme") == "- un\n  - deux\n- trois\nindenté\nterme"


def test_tables():
    text = clean('{| class="wikitable"\n|+ Légende\n! A !! B\n|-\n| 1 || style="color:red" | 2\n|-\n| suite\n'
                 'sur deux lignes\n|}\naprès')
    assert text == "Légende\nA | B\n1 | 2\nsuite sur deux lignes\naprès"


def test_real_looking_page():
    text = clean(ARGON_CRYSTAL)
    assert text.startswith("Argon Crystals are rare resources found on the Void. They decay after a day.")
    assert "Containers | 5%" in text and "Enemies | 2%" in text
    assert "{{" not in text and "[[" not in text and "<" not in text and "Category" not in text


# --- Découpage ----------------------------------------------------------------------------------------------

def test_sections():
    sections = split_sections(clean(ARGON_CRYSTAL))
    assert [(section.title, section.level) for section in sections] == [
        ("Introduction", 1), ("Acquisition", 2), ("Drop table", 3), ("Notes", 2)]
    assert sections[1].text.startswith("Argon Crystals drop from") and "Containers" not in sections[1].text


def test_empty_sections_and_duplicates():
    sections = split_sections("== Vide ==\n== Parent ==\n=== Notes ===\na\n== Notes ==\nb\n===== Profond =====\nc")
    assert [(section.title, section.text) for section in sections] == [
        ("Parent", ""), ("Notes", "a"), ("Notes (2)", "b\nProfond\nc")]


def test_page_without_heading():
    assert [(section.title, section.text) for section in split_sections("juste du texte")] == [("Introduction", "juste du texte")]
    assert split_sections("") == []


# --- Vrai export (extrait réduit) ---------------------------------------------------------------------------

@pytest.fixture
def real_pages(real_export):
    return {page.title: clean(page.text) for page in parse_export(real_export).pages}


def test_real_export_is_clean(real_pages):
    for text in real_pages.values():
        assert not any(mark in text for mark in ("{{", "}}", "[[", "]]", "<", "'''", "&nbsp;", "Ver/Lu"))


def test_real_tables_templates_and_formulas(real_pages):
    status = real_pages["Status Effect"]
    assert "Heat | PT_IMMOLATION | Ignite" in status
    assert "Proc Type Chance = Damage ÷ Total Damage" in status                # {{MathText}}, {{eql}}, {{div}}
    assert "Proc Type Chance | 18.18% | 4.55% | 9.09% | 22.73% | 45.45%" in status
    assert "Prior to Update 25.7" in status                                    # {{ver|25.7}}
    disruption = real_pages["Disruption"]
    assert "Kuva Fortress | Kuva x 50 | 100%" in disruption                  # {{Resource|Kuva}}
    assert "4+ | B | B | C | C" in disruption


def test_real_galleries_and_tabs_become_lists(real_pages):
    status = real_pages["Status Effect"]
    assert "Rifle=\n\n- Catalyzer Link\n- Galvanized Aptitude" in status       # {{#tag:tabber}} + <gallery>
    assert "- Carnis Carapace" in status and "- Ancient Healer" in status       # <tabber> puis galeries
