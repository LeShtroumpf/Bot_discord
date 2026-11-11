"""Boucle d'outils avec Claude : une question, des appels d'outils, une réponse.

La boucle est écrite à la main pour tenir le plafond de tours, cumuler l'usage et s'arrêter net sur une panne.
"""
import asyncio
from dataclasses import dataclass, field

from cephalon import tools
from cephalon.config import MAX_TOOL_ROUNDS, Config
from cephalon.persona import SYSTEM_PROMPT
from cephalon.warframe_api import WarframeApi

# Outils puis prompt système forment un préfixe identique d'une question à l'autre : ce marqueur le met en cache
# 5 minutes. Seule la première question d'un pic paie l'écriture, les suivantes le relisent à prix réduit.
SYSTEM = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]

OK, ROUNDS, REFUSAL = "ok", "rounds", "refusal"


@dataclass
class Usage:
    input: int = 0        # tokens d'entrée hors cache
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0

    def add(self, usage) -> None:
        self.input += getattr(usage, "input_tokens", 0) or 0
        self.output += getattr(usage, "output_tokens", 0) or 0
        self.cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.cache_write += getattr(usage, "cache_creation_input_tokens", 0) or 0


@dataclass
class Answer:
    status: str                      # OK : text est la réponse ; ROUNDS / REFUSAL : pas de réponse
    text: str = ""
    sources: list[tuple[str, str]] = field(default_factory=list)  # (nom, page du wiki), sans doublon
    usage: Usage = field(default_factory=Usage)
    rounds: int = 0


def text_of(response) -> str:
    return "\n".join(block.text for block in response.content if block.type == "text").strip()


def add_sources(known: list[tuple[str, str]], new: list[tuple[str, str]]) -> None:
    urls = {url for _, url in known}
    for name, url in new:
        if url not in urls:
            urls.add(url)
            known.append((name, url))


async def ask(client, api: WarframeApi, question: str, config: Config) -> Answer:
    """Pose la question à Claude. Les erreurs de l'API Anthropic et les pannes de warframestat remontent."""
    answer = Answer(status=ROUNDS)
    messages = [{"role": "user", "content": question}]
    for _ in range(MAX_TOOL_ROUNDS):
        response = await client.messages.create(
            model=config.model,
            max_tokens=config.max_tokens,
            system=SYSTEM,
            tools=tools.TOOLS,
            messages=messages,
            output_config={"effort": config.effort},
        )
        answer.rounds += 1
        answer.usage.add(response.usage)
        if response.stop_reason == "refusal":
            answer.status = REFUSAL
            return answer
        if response.stop_reason != "tool_use":
            text = text_of(response)
            if response.stop_reason == "max_tokens" and text:
                text += "…"
            answer.status, answer.text = (OK, text) if text else (ROUNDS, "")
            return answer
        calls = [block for block in response.content if block.type == "tool_use"]
        outcomes = await asyncio.gather(*(tools.execute(api, call.name, call.input) for call in calls))
        for outcome in outcomes:
            add_sources(answer.sources, outcome.sources)
        # Le contenu de l'assistant repart tel quel (blocs de réflexion compris), tous les résultats dans un seul message.
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": call.id, "content": outcome.content, "is_error": outcome.is_error}
            for call, outcome in zip(calls, outcomes)]})
    return answer
