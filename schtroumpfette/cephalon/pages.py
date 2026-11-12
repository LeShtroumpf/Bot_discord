"""Pages choisies du wiki : exports déposés à la main dans `cephalon/state/pages/`, traités par /cephalon_pages.

Séparé de l'index warframestat : la reconstruction quotidienne de l'index ne touche pas aux pages, et le traitement
des pages ne télécharge rien. Lecture, traitement et écriture sont bloquants : à lancer dans un thread.
"""
import difflib
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from cephalon.config import MAX_PAGES, PAGE_MAX_BYTES, SECTION_LIMIT
from cephalon.index import normalize
from cephalon.wikitext import INTRODUCTION, WIKI_HOST, ExportError, clean, page_url, parse_export, split_sections

PAGES_FILE = "pages.json"
VERSION = 1           # format du fichier : un fichier d'une autre version est ignoré (relancer /cephalon_pages)
CLOSE = 0.75          # ressemblance minimale d'un titre approchant (0 à 1)
SURE = 0.85           # au-dessus, un titre approchant est pris pour le bon (lecture d'une section)
MIN_WORD = 3          # mots plus courts ignorés par la recherche dans le texte
STOP_WORDS = {"the", "and", "for", "with", "how", "what", "where", "les", "des", "une", "pour", "avec", "dans",
              "comment", "quoi", "est", "sur", "par", "que", "qui", "farm", "farmer"}
TRUNCATED = "\n(suite tronquée)"


class PagesError(Exception):
    """Fichier des pages illisible."""


@dataclass
class Report:
    """Résultat d'un traitement de /cephalon_pages."""
    added: list[tuple[str, int]] = field(default_factory=list)      # (titre, nombre de sections)
    modified: list[tuple[str, int]] = field(default_factory=list)
    removed: list[tuple[str, int]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    fatal: str | None = None   # rien n'a changé
    pages: int = 0
    sections: int = 0


def digest(sections: list[dict]) -> str:
    return hashlib.sha1(json.dumps(sections, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def anchor(title: str) -> str:
    """Ancre MediaWiki d'une section : « Notes (2) » (titre en double, numéroté ici) devient Notes_2."""
    return re.sub(r" \((\d+)\)$", r"_\1", title)


def words_of(text: str) -> list[str]:
    return [word for word in normalize(text).split() if len(word) >= MIN_WORD and word not in STOP_WORDS]


class Pages:
    def __init__(self, pages: dict[str, dict]):
        self.pages = pages  # titre → {"title", "file", "url", "digest", "sections": [{"title", "level", "text"}]}
        self.titles = {normalize(title): title for title in pages}
        self.section_titles = {title: {normalize(section["title"]): section["title"] for section in page["sections"]}
                               for title, page in pages.items()}
        # Texte normalisé, entouré d'espaces : un mot cherché se trouve par « ␣mot » (préfixe d'un mot du texte).
        self.texts = {title: [" " + normalize(f"{section['title']} {section['text']}") + " "
                              for section in page["sections"]]
                      for title, page in pages.items()}

    def __len__(self) -> int:
        return len(self.pages)

    @property
    def section_count(self) -> int:
        return sum(len(page["sections"]) for page in self.pages.values())

    def summary(self) -> str:
        return f"{len(self)} pages, {self.section_count} sections"

    # --- Fichier ------------------------------------------------------------------------------------------

    @classmethod
    def read(cls, directory: Path) -> "Pages | None":
        """Les pages gardées sur disque, None s'il n'y en a pas. PagesError si le fichier est illisible."""
        try:
            saved = json.loads((Path(directory) / PAGES_FILE).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as error:
            raise PagesError(f"pages du wiki illisibles : {error}") from error
        try:
            if saved["version"] != VERSION:
                raise PagesError("pages du wiki d'une ancienne version : relance /cephalon_pages")
            return cls({page["title"]: page for page in saved["pages"]})
        except (KeyError, TypeError) as error:
            raise PagesError(f"pages du wiki d'une forme inattendue : {error or type(error).__name__}") from error

    def write(self, directory: Path) -> None:
        """Écriture atomique : un fichier temporaire, puis un renommage."""
        directory = Path(directory)
        tmp = directory / (PAGES_FILE + ".tmp")
        saved = {"version": VERSION, "pages": list(self.pages.values())}
        tmp.write_text(json.dumps(saved, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, directory / PAGES_FILE)

    # --- Traitement des exports ---------------------------------------------------------------------------

    @classmethod
    def reload(cls, directory: Path, previous: "Pages | None" = None) -> tuple["Pages | None", Report]:
        """Relit tous les exports du dossier. Rien de changé (None) si le dossier est introuvable.

        Un fichier en échec garde ses pages précédentes ; une page vide après nettoyage aussi."""
        report, directory = Report(), Path(directory)
        old = previous.pages if previous else {}
        if not directory.is_dir():
            report.fatal = f"dossier `{directory.name}` introuvable ({directory})"
            return None, report
        files = sorted((path for path in directory.iterdir() if path.is_file() and path.suffix.lower() == ".xml"),
                       key=lambda path: (path.stat().st_mtime, path.name))  # le plus récent en dernier : il l'emporte
        pages: dict[str, dict] = {}
        failed_files: set[str] = set()
        kept: set[str] = set()
        for path in files:
            try:
                export = cls.read_export(path)
            except ExportError as error:
                report.problems.append(f"{path.name} : {error}")
                failed_files.add(path.name)
                continue
            for raw in export.pages:
                if raw.redirect:
                    report.problems.append(f"{path.name} : redirection ignorée : {raw.title} (exporte plutôt la page cible)")
                    continue
                sections = [{"title": section.title, "level": section.level, "text": section.text}
                            for section in split_sections(clean(raw.text))]
                if not any(section["text"] for section in sections):
                    report.problems.append(f"{path.name} : page vide après nettoyage : {raw.title}")
                    kept.add(raw.title)
                    continue
                if raw.title in pages:
                    report.problems.append(f"{raw.title} présent dans {pages[raw.title]['file']} et {path.name}, "
                                           f"gardé : {path.name} (le plus récent)")
                pages[raw.title] = {"title": raw.title, "file": path.name, "url": page_url(raw.title),
                                    "digest": digest(sections), "sections": sections}
        for title, page in old.items():
            if title not in pages and (page["file"] in failed_files or title in kept):
                pages[title] = page
        for title, page in sorted(pages.items()):
            entry = (title, len(page["sections"]))
            if title not in old:
                report.added.append(entry)
            elif old[title]["digest"] != page["digest"]:
                report.modified.append(entry)
        report.removed = [(title, len(page["sections"])) for title, page in sorted(old.items()) if title not in pages]
        result = cls(pages)
        report.pages, report.sections = len(result), result.section_count
        return result, report

    @staticmethod
    def read_export(path: Path):
        if path.stat().st_size > PAGE_MAX_BYTES:
            raise ExportError(f"fichier trop gros (> {PAGE_MAX_BYTES // (1024 * 1024)} Mo)")
        export = parse_export(path.read_bytes())
        if export.host != WIKI_HOST:
            raise ExportError(f"domaine inattendu : {export.host or 'aucun'} (seul {WIKI_HOST} est accepté)")
        return export

    # --- Recherche ----------------------------------------------------------------------------------------

    def find_title(self, name: str, sure: bool = False) -> str | None:
        key = normalize(name)
        if key in self.titles:
            return self.titles[key]
        close = difflib.get_close_matches(key, self.titles, n=1, cutoff=SURE if sure else CLOSE)
        return self.titles[close[0]] if close else None

    def toc(self, title: str) -> list[dict]:
        """Sommaire : titre, niveau et longueur (sous-sections comprises) de chaque section."""
        sections = self.pages[title]["sections"]
        return [{"title": section["title"], "level": section["level"], "chars": len(self.section_text(title, i))}
                for i, section in enumerate(sections)]

    def search(self, query: str) -> list[dict]:
        """Pages par titre (tolérant aux fautes), puis par titre de section, puis par le texte des sections."""
        key, words = normalize(query), words_of(query)
        query_words = set(key.split())
        found: dict[str, dict] = {}

        def add(title: str, how: str, sections: list[str] | None = None):
            if title not in found and len(found) < MAX_PAGES:
                found[title] = {"page": title, "found_by": how, **({"matching_sections": sections} if sections else {}),
                                "sections": self.toc(title)}

        exact = self.find_title(query)
        if exact:
            add(exact, "title")
        for candidate in difflib.get_close_matches(key, self.titles, n=MAX_PAGES, cutoff=CLOSE):
            add(self.titles[candidate], "title")
        for normalized, title in sorted(self.titles.items(), key=lambda item: len(item[0])):
            title_words = set(normalized.split())
            if title_words and (title_words <= query_words or (query_words and query_words <= title_words)):
                add(title, "title")
        for title, sections in self.section_titles.items():
            matching = [display for normalized, display in sections.items()
                        if normalized and (normalized == key or set(normalized.split()) <= query_words
                                           or (query_words and query_words <= set(normalized.split())))]
            if matching:
                add(title, "section", matching)
        if not found and words:  # repli : le texte seulement si aucun titre ne correspond
            scored = []
            for title, texts in self.texts.items():
                counts = [sum(f" {word}" in text for word in words) for text in texts]
                best = max(counts, default=0)
                if best:
                    sections = self.pages[title]["sections"]
                    matching = [sections[i]["title"] for i, count in enumerate(counts) if count == best][:5]
                    scored.append((-best, title, matching))
            for _, title, matching in sorted(scored):
                add(title, "text", matching)
        return list(found.values())

    # --- Lecture ------------------------------------------------------------------------------------------

    def section_text(self, title: str, i: int) -> str:
        """Texte d'une section, suivi de ses sous-sections (avec leur titre)."""
        sections = self.pages[title]["sections"]
        parts = [sections[i]["text"]]
        for section in sections[i + 1:]:
            if section["level"] <= sections[i]["level"]:
                break
            parts.append(f"{'=' * section['level']} {section['title']} {'=' * section['level']}\n{section['text']}")
        return "\n\n".join(part for part in parts if part).strip()

    def read_section(self, page: str, section: str | None) -> tuple[dict, tuple[str, str] | None]:
        """(résultat pour Claude, source) ; source None si la page ou la section est introuvable."""
        title = self.find_title(page, sure=True)
        if title is None:
            return {"error": "Page introuvable : appelle d'abord search_pages pour obtenir le titre exact."}, None
        sections = self.pages[title]["sections"]
        wanted = normalize(section or INTRODUCTION)
        index = next((i for i, item in enumerate(sections) if normalize(item["title"]) == wanted), None)
        if index is None and section is None:
            index = 0
        if index is None:
            return {"error": "Section introuvable.", "page": title,
                    "sections": [item["title"] for item in sections]}, None
        name = sections[index]["title"]
        text = self.section_text(title, index)
        truncated = len(text) > SECTION_LIMIT
        if truncated:
            text = text[:SECTION_LIMIT].rstrip() + TRUNCATED
        is_intro = name == INTRODUCTION and sections[index]["level"] == 1
        source = (title if is_intro else f"{title} — {name}", page_url(title, None if is_intro else anchor(name)))
        return {"page": title, "section": name, "text": text, "truncated": truncated}, source
