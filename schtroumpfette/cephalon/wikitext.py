"""Exports `Special:Export` du wiki : lecture du XML, nettoyage du wikitexte, découpage en sections (fonctions pures).

Le bot ne télécharge jamais rien sur le wiki : les fichiers sont exportés et déposés à la main.
"""
import html
import re
from dataclasses import dataclass, field
from urllib.parse import quote, urlsplit
from xml.etree import ElementTree

WIKI_HOST = "wiki.warframe.com"
ARTICLE_URL = f"https://{WIKI_HOST}/w/"
INTRODUCTION = "Introduction"

# Modèles en ligne qui portent du texte : remplacés par leur premier argument. Les autres modèles sont retirés.
INLINE_TEMPLATES = {"d", "dt", "proc", "m", "wf", "weapon", "res", "resource", "tooltip", "icon", "abilities", "a",
                    "enemy", "e", "planet", "mission", "node", "item", "i", "pol", "polarity", "faction", "f", "arcane",
                    "focus", "mathtext", "math"}
LAST_ARGUMENT_TEMPLATES = {"text"}  # {{Text|red|texte}} : le texte est le dernier argument
SYMBOLS = {"eql": "=", "mul": "×", "div": "÷", "min": "−", "plus": "+", "minus": "−", "times": "×", "!": "|"}
# Modèles courts à retirer même s'ils n'ont qu'un argument (bandeaux, renvois).
DROPPED_TEMPLATES = {"main", "see also", "seealso", "further", "stub", "cite", "citation", "anchor", "clear",
                     "construction", "update", "spoiler", "quote", "noinclude", "displaytitle", "defaultsort",
                     "transclude", "updateme", "tocright", "toc", "clr", "youtube", "videogallery", "reflist", "top"}
SHORT_TEMPLATE = 60  # un modèle inconnu, sans argument nommé, d'au plus 2 arguments et aussi court, est gardé

MAX_HEADING = 4      # niveaux de titres découpés en sections (== à ====)

INNER_LINK = re.compile(r"\[\[([^\[\]]*)\]\]")
EXTERNAL_LINK = re.compile(r"\[(?:https?:)?//[^\s\]]+(?:\s+([^\]]*))?\]")
COMMENT = re.compile(r"<!--.*?-->", re.S)
REF = re.compile(r"<ref\b[^>/]*/>|<ref\b[^>]*>.*?</ref\s*>", re.S | re.I)
GALLERY = re.compile(r"<gallery\b[^>]*>(.*?)</gallery\s*>", re.S | re.I)
DROPPED_BLOCKS = re.compile(r"<(nowiki|math|score|templatedata|includeonly|syntaxhighlight)\b[^>]*>.*?</\1\s*>",
                            re.S | re.I)
BREAK = re.compile(r"<br\s*/?>", re.I)
TAG = re.compile(r"</?[a-zA-Z][^>]*>")
SWITCH = re.compile(r"__[A-Z]+__")
EMPHASIS = re.compile(r"'{2,5}")
HEADING = re.compile(r"^(={1,6})\s*(.+?)\s*\1\s*$")
CELL_ATTRIBUTES = re.compile(r"^\s*[a-zA-Z-]+\s*=")
INTERLANGUAGE = re.compile(r"^[a-z]{2,3}(-[a-z]+)?:")
LINK_NAMESPACES = ("file:", "image:", "media:", "category:")


class ExportError(Exception):
    """Fichier qui n'est pas un export lisible du wiki."""


@dataclass
class RawPage:
    title: str
    text: str
    redirect: bool = False


@dataclass
class Export:
    base: str
    pages: list[RawPage] = field(default_factory=list)

    @property
    def host(self) -> str:
        return urlsplit(self.base).hostname or ""


@dataclass
class Section:
    title: str
    level: int   # 1 pour l'introduction, 2 à 4 pour les titres == à ====
    text: str


# --- Lecture de l'export ----------------------------------------------------------------------------------

def local(tag: str) -> str:
    """Nom d'une balise sans son espace de noms XML (il change avec la version de MediaWiki)."""
    return tag.rsplit("}", 1)[-1]


def child(element, name: str):
    return next((item for item in element if local(item.tag) == name), None)


def parse_export(data: bytes) -> Export:
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as error:
        raise ExportError(f"XML illisible ({error})") from error
    if local(root.tag) != "mediawiki":
        raise ExportError("pas un export du wiki")
    siteinfo = child(root, "siteinfo")
    base = child(siteinfo, "base") if siteinfo is not None else None
    export = Export(base=(base.text or "").strip() if base is not None else "")
    for page in (item for item in root if local(item.tag) == "page"):
        title = child(page, "title")
        revisions = [item for item in page if local(item.tag) == "revision"]
        if title is None or not (title.text or "").strip() or not revisions:
            continue
        text = child(revisions[-1], "text")
        export.pages.append(RawPage(title=title.text.strip(), text=(text.text or "") if text is not None else "",
                                    redirect=child(page, "redirect") is not None))
    return export


def page_url(title: str, section: str | None = None) -> str:
    """Adresse de la page (et de la section) sur le wiki, comme MediaWiki la construit."""
    url = ARTICLE_URL + quote(title.replace(" ", "_"), safe="/:()',")
    if section:
        url += "#" + quote(section.replace(" ", "_"), safe="/:()',.")
    return url


# --- Nettoyage --------------------------------------------------------------------------------------------

def render_gallery(match: re.Match) -> str:
    """Galerie d'images : une ligne de liste par image, avec sa cible (link=) ou sa légende."""
    lines = []
    for line in match.group(1).split("\n"):
        _, bar, rest = line.strip().partition("|")
        if not bar:
            continue
        link = re.search(r"(?:^|\|)\s*link=([^|]*)", rest)
        caption = link.group(1) if link else re.sub(r"(?:^|\|)\s*[a-z]+=[^|]*", "", rest)
        if caption.strip():
            lines.append(f"* {caption.strip()}")
    return "\n" + "\n".join(lines) + "\n"


def render_link(match: re.Match) -> str:
    target, _, label = match.group(1).partition("|")
    target = target.strip()
    if target.startswith(":"):  # lien vers une catégorie ou un fichier, affiché comme un lien
        return label or target[1:]
    if target.lower().startswith(LINK_NAMESPACES) or INTERLANGUAGE.match(target):
        return ""
    return label if label else (target.split("#")[0] or target.lstrip("#")).replace("_", " ")


def closing(text: str, start: int) -> int:
    """Position juste après les }} qui ferment les {{ de `start` (accolades comptées), -1 s'il n'y en a pas."""
    depth, i = 0, start
    while i < len(text) - 1:
        if text.startswith("{{", i):
            depth, i = depth + 1, i + 2
        elif text.startswith("}}", i):
            depth, i = depth - 1, i + 2
            if not depth:
                return i
        else:
            i += 1
    return -1


def top_level_split(inner: str) -> list[str]:
    """Arguments d'un modèle : les | des modèles imbriqués ne coupent pas."""
    parts, depth, current, i = [], 0, [], 0
    while i < len(inner):
        if inner.startswith("{{", i) or inner.startswith("}}", i):
            depth += 1 if inner[i] == "{" else -1
            current.append(inner[i:i + 2])
            i += 2
            continue
        if inner[i] == "|" and not depth:
            parts.append("".join(current))
            current = []
        else:
            current.append(inner[i])
        i += 1
    parts.append("".join(current))
    return [part.strip() for part in parts]


def render_template(inner: str) -> str:
    """Un modèle en ligne connu, ou court et simple, devient son texte ; tout autre modèle disparaît, contenu compris."""
    parts = top_level_split(inner)
    name = parts[0].replace("_", " ").strip().lower()
    positional = [arg for arg in parts[1:] if not CELL_ATTRIBUTES.match(arg)]
    if name == "#tag:tabber":  # onglets : contenu gardé, un onglet par ligne
        return templates("|".join(parts[1:]))
    if name in DROPPED_TEMPLATES or name.startswith("#") or ":" in name:
        return ""
    if name in SYMBOLS and len(parts) == 1:
        return SYMBOLS[name]
    if name == "ver":
        return f"Update {positional[0]}" if positional else ""
    if name in LAST_ARGUMENT_TEMPLATES:
        return templates(positional[-1]) if positional else ""
    if name in INLINE_TEMPLATES:
        return templates(positional[0]) if positional else ""
    if (positional and "/" not in name and len(positional) == len(parts) - 1 <= 2 and len(inner) + 4 <= SHORT_TEMPLATE
            and "{{" not in inner and "\n" not in inner):
        return positional[0]
    return ""


def templates(text: str) -> str:
    """Modèles {{…}} lus de l'extérieur vers l'intérieur ; un modèle mal fermé emporte la fin du texte."""
    out, i = [], 0
    while True:
        start = text.find("{{", i)
        if start < 0:
            out.append(text[i:])
            return "".join(out)
        out.append(text[i:start])
        end = closing(text, start)
        if end < 0:
            return "".join(out)
        out.append(render_template(text[start + 2:end - 2]))
        i = end


def replace_innermost(pattern: re.Pattern, function, text: str) -> str:
    """Remplace de l'intérieur vers l'extérieur (liens imbriqués dans la légende d'une image)."""
    while True:
        text, count = pattern.subn(function, text)
        if not count:
            return text


def split_cells(line: str, separator: str) -> list[str]:
    cells = []
    for cell in line.split(separator):
        content, bar, rest = cell.partition("|")
        if bar and CELL_ATTRIBUTES.match(content):  # style="…" | contenu
            cell = rest
        cells.append(cell.strip())
    return cells


def flatten_tables(text: str) -> str:
    """Tableaux {| … |} : une ligne par rangée, cellules séparées par « | »."""
    out, row, depth = [], [], 0

    def close_row():
        if any(row):
            out.append(" | ".join(cell for cell in row))
        row.clear()

    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("{|"):
            close_row()
            depth += 1
        elif depth and stripped.startswith("|}"):
            close_row()
            depth -= 1
        elif depth and stripped.startswith("|+"):
            close_row()
            out.append(stripped[2:].strip())
        elif depth and stripped.startswith("|-"):
            close_row()
        elif depth and stripped.startswith("!"):
            row.extend(split_cells(stripped[1:], "!!"))
        elif depth and stripped.startswith("|"):
            row.extend(split_cells(stripped[1:], "||"))
        elif depth and row:
            row[-1] = f"{row[-1]} {stripped}".strip()  # suite d'une cellule sur plusieurs lignes
        else:
            out.append(line)
    close_row()
    return "\n".join(out)


def format_line(line: str) -> str:
    stripped = line.strip()
    match = re.match(r"^([*#:;]+)\s*(.*)$", stripped)
    if match and not HEADING.match(stripped):
        marks, content = match.groups()
        if marks[-1] in "*#":
            return "  " * (len(marks) - 1) + "- " + content
        return content
    return stripped


def clean(wikitext: str) -> str:
    """Texte lisible d'une page : titres gardés (== … ==), mise en forme du wiki retirée."""
    text = wikitext.replace("\r\n", "\n")
    text = COMMENT.sub("", text)
    text = REF.sub("", text)
    text = DROPPED_BLOCKS.sub("", text)
    text = GALLERY.sub(render_gallery, text)
    text = text.replace("{{!}}", "|").replace("{{=}}", "=")
    text = text.replace("|-|", "\n")  # séparateur d'onglets (<tabber>, {{#tag:tabber}})
    text = replace_innermost(INNER_LINK, render_link, text)
    text = templates(text)
    text = EXTERNAL_LINK.sub(lambda match: match.group(1) or "", text)
    text = flatten_tables(text)
    text = BREAK.sub("\n", text)
    text = TAG.sub("", text)
    text = SWITCH.sub("", text)
    text = EMPHASIS.sub("", text)
    text = html.unescape(text).replace("\xa0", " ")
    lines = [format_line(line) for line in text.split("\n")]
    text = "\n".join(re.sub(r"[ \t]{2,}", " ", line) if not line.startswith("  ") else line.rstrip() for line in lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# --- Découpage --------------------------------------------------------------------------------------------

def split_sections(text: str) -> list[Section]:
    """Introduction puis une section par titre (== à ====). Sections vides retirées, titres en double numérotés."""
    sections, title, level, lines = [], INTRODUCTION, 1, []

    def close():
        sections.append(Section(title=title, level=level, text="\n".join(lines).strip()))

    for line in text.split("\n"):
        match = HEADING.match(line.strip())
        if match and 2 <= len(match.group(1)) <= MAX_HEADING and match.group(2).strip():
            close()
            title, level, lines = match.group(2).strip(), len(match.group(1)), []
        elif match:
            lines.append(match.group(2).strip())  # titre plus profond : gardé comme une ligne de texte
        else:
            lines.append(line)
    close()
    # Une section vide n'est gardée que si elle a des sous-sections (elle se lit alors avec elles).
    sections = [section for i, section in enumerate(sections)
                if section.text or (i + 1 < len(sections) and sections[i + 1].level > section.level
                                    and section.level > 1)]
    seen: dict[str, int] = {}
    for section in sections:
        count = seen.get(section.title, 0) + 1
        seen[section.title] = count
        if count > 1:
            section.title = f"{section.title} ({count})"
    return sections
