"""Embeds de la Cephalon (fonctions pures)."""
import discord

from cephalon.persona import NAME

ANSWER_COLOR = discord.Color.blue()
FALLBACK_COLOR = discord.Color.light_grey()
DESCRIPTION_LIMIT = 4096  # limite Discord d'une description d'embed
FIELD_LIMIT = 1024        # limite Discord d'une valeur de champ
MAX_SOURCES = 5
FOOTER = "Données : warframestat.us"


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


def answer(question: str, text: str, sources: list[tuple[str, str]]) -> discord.Embed:
    embed = discord.Embed(description=body(question, text), color=ANSWER_COLOR)
    embed.set_author(name=NAME)
    links = sources_field(sources)
    if links:
        embed.add_field(name="Sources", value=links, inline=False)
        embed.set_footer(text=FOOTER)
    return embed


def fallback(question: str, message: str) -> discord.Embed:
    embed = discord.Embed(description=body(question, message), color=FALLBACK_COLOR)
    embed.set_author(name=NAME)
    return embed
