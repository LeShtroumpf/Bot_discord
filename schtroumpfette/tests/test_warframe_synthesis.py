from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from warframe import synthesis
from warframe.render import SYNTHESIS_CREDIT, render_synthesis
from warframe.synthesis import SynthesisError, find, label, normalize, parse, search, suggest
from warframe.translations import Translator


def lua(*entries: str) -> str:
    return "local synthesisData = {\n" + "".join(entries) + "}\n"


def entry(name: str, places: str = '"Ara"', extra: str = "") -> str:
    return f'\t["{name}"] = {{\n\t\t_IgnoreEntry = false,\n\t\tLocations = {{ {places} }},\n{extra}\t}},\n'


def full_module() -> str:
    return lua(*[entry(f"Target {index}") for index in range(synthesis.MIN_TARGETS)])


def session_returning(text: str = "", error: Exception | None = None) -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock(side_effect=error)
    response.text = AsyncMock(return_value=text)
    session = MagicMock()
    session.get.return_value.__aenter__ = AsyncMock(return_value=response)
    session.get.return_value.__aexit__ = AsyncMock(return_value=False)
    return session


# --- Parsing -------------------------------------------------------------------------------------------------

def test_parse_real_module(targets):
    assert targets["Hellion"] == ("Ara", "Lex", "Rusalka")
    assert set(targets["Lancer"]) >= {"Cambria", "Caloris", "Elion"}


def test_parse_strips_spaces_and_comments():
    text = lua(entry("Boiler", '"Isos ", "Horend", -- "Ancienne"\n"Tikal"'))
    assert parse(text, minimum=1) == {"Boiler": ("Isos", "Horend", "Tikal")}


def test_parse_skips_ignored_entries():
    ignored = '\t["Old"] = {\n\t\t_IgnoreEntry = true,\n\t\tLocations = { "Ara" },\n\t},\n'
    assert parse(lua(ignored, entry("New")), minimum=1) == {"New": ("Ara",)}


@pytest.mark.parametrize("text", ["", "<html>Erreur</html>", lua(entry("Seule cible"))])
def test_parse_rejects_unexpected_format(text):
    with pytest.raises(SynthesisError):
        parse(text)


# --- Cache et téléchargement ---------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_download_writes_cache(tmp_path):
    targets = await synthesis.download(session_returning(full_module()), tmp_path)
    assert len(targets) == synthesis.MIN_TARGETS
    cached, _ = synthesis.read_cache(tmp_path)
    assert cached == targets


@pytest.mark.asyncio
async def test_download_keeps_cache_on_bad_format(tmp_path):
    await synthesis.download(session_returning(full_module()), tmp_path)
    with pytest.raises(SynthesisError):
        await synthesis.download(session_returning("<html>Maintenance</html>"), tmp_path)
    assert len(synthesis.read_cache(tmp_path)[0]) == synthesis.MIN_TARGETS


@pytest.mark.asyncio
async def test_download_http_error(tmp_path):
    error = aiohttp.ClientResponseError(MagicMock(), (), status=503, message="Service Unavailable")
    with pytest.raises(SynthesisError):
        await synthesis.download(session_returning(error=error), tmp_path)


def test_read_cache_absent_or_invalid(tmp_path):
    assert synthesis.read_cache(tmp_path) is None
    (tmp_path / synthesis.CACHE_FILE).write_text("illisible", encoding="utf-8")
    assert synthesis.read_cache(tmp_path) is None


# --- Recherche -----------------------------------------------------------------------------------------------

def test_normalize():
    assert normalize("Homme d\u2019Équipage") == normalize("homme d'equipage") == "homme d equipage"


def test_label(bilingual):
    assert label(bilingual, "Lancer") == "Lancier (Lancer)"
    assert label(bilingual, "Hellion") == "Hellion"  # même nom dans les deux langues
    assert label(Translator(), "Lancer") == "Lancer"  # traductions pas encore chargées


@pytest.mark.parametrize("query", ["lancer", "lancier", "LANCIER", "lanc"])
def test_search_same_results_in_both_languages(targets, bilingual, query):
    assert set(search(targets, bilingual, query)) == {"Lancer", "Shield Lancer", "Corrupted Lancer"}


@pytest.mark.parametrize("query", ["lancer", "lancier"])
def test_search_exact_name_comes_first(targets, bilingual, query):
    assert search(targets, bilingual, query)[0] == "Lancer"


def test_search_limit(bilingual):
    targets = {f"Target {index}": ("Ara",) for index in range(40)}
    assert len(search(targets, bilingual, "")) == synthesis.MAX_CHOICES


@pytest.mark.parametrize("query, expected", [
    ("lancer", "Lancer"), ("Lancier", "Lancer"), ("eviscerateur", "Eviscerator"), ("Éviscérateur", "Eviscerator"),
    ("Lancier (Lancer)", "Lancer"), ("Shield Lancer", "Shield Lancer"),
])
def test_find_in_both_languages(targets, bilingual, query, expected):
    assert find(targets, bilingual, query) == expected


def test_find_needs_a_full_name(targets, bilingual):
    assert find(targets, bilingual, "lanc") is None


def test_suggest_close_names(targets, bilingual):
    assert "Lancier (Lancer)" in suggest(targets, bilingual, "lansier")
    assert len(suggest(targets, bilingual, "lanc")) <= synthesis.MAX_SUGGESTIONS
    assert suggest(targets, bilingual, "xyz") == []


# --- Rendu ---------------------------------------------------------------------------------------------------

def test_render_both_languages(bilingual):
    embed = render_synthesis(bilingual, "Lancer", ("Cambria",))
    assert embed.title == "Lancier (Lancer)"
    assert embed.description == "Cambria (Terre / Earth) · Espionnage · Grineer"
    assert embed.footer.text == SYNTHESIS_CREDIT


def test_render_sorted_by_planet_then_node(bilingual):
    lines = render_synthesis(bilingual, "Lancer", ("Cambria", "Elion", "Caloris", "Ara")).description.splitlines()
    assert [line.split(" (")[0] for line in lines] == ["Ara", "Caloris", "Elion", "Cambria"]


def test_render_french_node_name_differs(bilingual):
    assert render_synthesis(bilingual, "Lancer", ("Copernicus",)).description.startswith("Copernic (Lua) ·")


def test_render_same_planet_name_once(bilingual):
    assert render_synthesis(bilingual, "Lancer", ("Ara",)).description.startswith("Ara (Mars) ·")


def test_render_unknown_node(bilingual):
    assert render_synthesis(bilingual, "Lancer", ("Atlantide",)).description == "Atlantide"


def test_render_without_translations():
    embed = render_synthesis(Translator(), "Lancer", ("Cambria",))
    assert (embed.title, embed.description) == ("Lancer", "Cambria")


def test_every_real_target_fits_in_an_embed(targets, bilingual):
    for name, places in targets.items():
        assert len(render_synthesis(bilingual, name, places)) < 6000
