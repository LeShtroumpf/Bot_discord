"""Signalement des erreurs du bot dans le salon de logs, avec anti-spam.

Utilisé par tout le bot (events, tâches, slash commands, cogs) : indépendant du cog des logs d'activité.
"""
import datetime as dt
import functools
from dataclasses import dataclass

from discord.ext import commands

from utils.embed import error_message

ERROR_WINDOW = dt.timedelta(minutes=10)  # une même erreur n'est pas renvoyée dans le salon avant ce délai


@dataclass
class ErrorState:
    sent_at: dt.datetime
    repeats: int = 0  # occurrences non envoyées depuis sent_at


class ErrorReporter:
    def __init__(self):
        self.errors: dict[tuple[str, str], ErrorState] = {}

    def repeats(self, key: tuple[str, str], now: dt.datetime) -> int | None:
        """Occurrences à signaler avec cette erreur, ou None si elle a déjà été envoyée il y a moins de ERROR_WINDOW."""
        state = self.errors.get(key)
        if state and now - state.sent_at < ERROR_WINDOW:
            state.repeats += 1
            return None
        self.errors = {k: s for k, s in self.errors.items() if s.repeats or now - s.sent_at < ERROR_WINDOW}
        self.errors[key] = ErrorState(sent_at=now)
        return state.repeats if state else 0

    async def report(self, error, origine: str, channel=None):
        """Ne lève jamais d'exception : la console reçoit chaque erreur, le salon une seule par ERROR_WINDOW."""
        text = str(error) or type(error).__name__
        print(f"[{origine}] {text}", flush=True)
        repeats = self.repeats((origine, text), dt.datetime.now(dt.UTC))
        if channel is None or repeats is None:
            return
        try:
            await channel.send(embed=error_message.error(origine, text, repeats))
        except Exception as e:
            print(f"[{origine}] log impossible : {e}", flush=True)


error_reporter = ErrorReporter()


async def report_error(bot, error, origine: str):
    """Envoie l'erreur dans le salon de logs du bot (propriété `logs_channel`), ou en console s'il est introuvable."""
    channel = getattr(bot, "logs_channel", None)
    await error_reporter.report(error, origine, channel)


def log_errors(origine: str):
    """Une exception dans un event, un listener ou une tâche part dans le salon de logs, avec son origine.

    Marche sur une méthode du bot comme sur une méthode de cog (attribut `bot`).
    """
    def decorator(handler):
        @functools.wraps(handler)
        async def wrapper(self, *args, **kwargs):
            try:
                await handler(self, *args, **kwargs)
            except Exception as error:
                await report_error(self.bot if isinstance(self, commands.Cog) else self, error, origine)
        return wrapper
    return decorator
