"""Embeds de la Cephalon (fonctions pures)."""
import discord

from cephalon.persona import NAME

ANSWER_COLOR = discord.Color.blue()
FALLBACK_COLOR = discord.Color.light_grey()
DESCRIPTION_LIMIT = 4096  # limite Discord d'une description d'embed
FIELD_LIMIT = 1024        # limite Discord d'une valeur de champ
MAX_SOURCES = 5
FOOTER = "Données : warframestat.us"
WIKI_FOOTER = "Données : warframestat.us, wiki.warframe.com (CC BY-NC-SA)"
REPORT_LINES = 15         # pages listées par champ du rapport de /cephalon_pages, au plus


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def quote(question: str) -> str:
    """La question du joueur en citation, sur une ou plusieurs lignes."""
    return "\n".join(f"> {line}" for line in question.strip().splitlines() or [""])


def body(question: str, text: str) -> str:
    return truncate(f"{quote(question)}\n\n{text.strip()}", DESCRIPTION_LIMIT)


def sources_field(sources: list[tuple[str, str]]) -> str:
    """Liens vers les pages du wiki, tant qu'ils tiennent dans un champ."""
    lines = []
    for name, url in sources[:MAX_SOURCES]:
        line = f"[{name}]({url})"
        if len("\n".join(lines + [line])) > FIELD_LIMIT:
            break
        lines.append(line)
    return "\n".join(lines)


def remaining_text(remaining: int) -> str:
    """Questions que le joueur peut encore poser aujourd'hui."""
    if remaining <= 0:
        return "Dernière question du jour"
    return "1 question restante aujourd'hui" if remaining == 1 else f"{remaining} questions restantes aujourd'hui"


def answer(question: str, text: str, sources: list[tuple[str, str]], remaining: int | None = None,
           wiki: bool = False) -> discord.Embed:
    embed = discord.Embed(description=body(question, text), color=ANSWER_COLOR)
    embed.set_author(name=NAME)
    footer = []
    links = sources_field(sources)
    if links:
        embed.add_field(name="Sources", value=links, inline=False)
        footer.append(WIKI_FOOTER if wiki else FOOTER)
    if remaining is not None:
        footer.append(remaining_text(remaining))
    if footer:
        embed.set_footer(text=" · ".join(footer))
    return embed


def fallback(question: str, message: str) -> discord.Embed:
    embed = discord.Embed(description=body(question, message), color=FALLBACK_COLOR)
    embed.set_author(name=NAME)
    return embed


def page_lines(entries: list[tuple[str, int]]) -> str:
    """Une ligne par page, « … et N autres » si le champ déborde."""
    lines = [f"{title} ({count} section{'s' if count > 1 else ''})" for title, count in entries]
    shown = lines[:REPORT_LINES]
    while shown and len("\n".join(shown)) > FIELD_LIMIT - 30:
        shown.pop()
    if len(shown) < len(lines):
        shown.append(f"… et {len(lines) - len(shown)} autres")
    return "\n".join(shown)


def problem_lines(problems: list[str]) -> str:
    shown = []
    for problem in problems:
        line = truncate(problem, 200)
        if len("\n".join(shown + [line])) > FIELD_LIMIT - 30:
            shown.append(f"… et {len(problems) - len(shown)} autres")
            break
        shown.append(line)
    return "\n".join(shown)


def pages_report(report, moderator: str) -> discord.Embed:
    """Résultat de /cephalon_pages (réponse éphémère et salon de logs) : vert, orange (problèmes) ou rouge (échec)."""
    if report.fatal:
        return discord.Embed(title="📚 Pages du wiki non rechargées", color=discord.Color.red(),
                             description=f"par {moderator}\nRien n'a changé : {report.fatal}")
    color = discord.Color.orange() if report.problems else discord.Color.green()
    embed = discord.Embed(title="📚 Pages du wiki rechargées", description=f"par {moderator}", color=color)
    for name, entries in (("Ajoutées", report.added), ("Modifiées", report.modified), ("Retirées", report.removed)):
        if entries:
            embed.add_field(name=name, value=page_lines(entries), inline=False)
    if report.problems:
        embed.add_field(name="Problèmes", value=problem_lines(report.problems), inline=False)
    if not (report.added or report.modified or report.removed or report.problems):
        embed.add_field(name="Aucun changement", value="Les pages sont les mêmes qu'avant.", inline=False)
    pages = f"{report.pages} page{'s' if report.pages > 1 else ''}"
    sections = f"{report.sections} section{'s' if report.sections > 1 else ''}"
    embed.set_footer(text=f"{pages}, {sections} dans les archives")
    return embed
