import datetime as dt
import os
import re

import aiohttp
from dotenv import load_dotenv

from utils.embed import TwitchMessage
from utils.file_management import settings_file_management

load_dotenv()

HELIX_URL = "https://api.twitch.tv/helix"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"
TIMEOUT = aiohttp.ClientTimeout(total=10)
MAX_LOGINS = 100  # limite de Twitch par requête
OFFLINE_GRACE = dt.timedelta(minutes=10)  # hors ligne depuis ce délai : le prochain live sera annoncé
USERS_CHECK_INTERVAL = dt.timedelta(hours=1)
MENTIONED_LOGIN = "le_shtroumpf"
STREAMER_INPUT = re.compile(r"(?:(?:https?://)?(?:www\.|m\.)?twitch\.tv/)?([a-z0-9_]{1,25})")


class TwitchError(Exception):
    """Erreur du suivi Twitch. Son texte part dans le salon de logs : jamais de secret ni de token."""


def login_from_url(url: str) -> str:
    return url.rstrip('/').split('/')[-1].lower()


def streamer_url(login: str) -> str:
    return f"https://www.twitch.tv/{login}"


def parse_streamer(text: str) -> str | None:
    """Pseudo d'un streamer à partir d'un pseudo ou d'un lien Twitch. None si ce n'est ni l'un ni l'autre."""
    match = STREAMER_INPUT.fullmatch(text.strip().lower().rstrip('/'))
    return match[1] if match else None


class TwitchApi:
    """Appels à l'API Helix avec un token d'application, renouvelé quand il expire."""

    def __init__(self, client_id: str | None, client_secret: str | None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token = None

    async def authenticate(self, session: aiohttp.ClientSession):
        credentials = {"client_id": self.client_id, "client_secret": self.client_secret, "grant_type": "client_credentials"}
        async with session.post(TOKEN_URL, data=credentials, timeout=TIMEOUT) as response:  # dans le corps : jamais dans l'URL
            if response.status != 200:
                raise TwitchError(f"token refusé (HTTP {response.status})")
            self.token = (await response.json())["access_token"]

    async def get(self, session: aiohttp.ClientSession, path: str, params: list[tuple[str, str]]) -> list[dict]:
        if not self.token:
            await self.authenticate(session)
        for retry in (True, False):
            headers = {"Authorization": f"Bearer {self.token}", "Client-Id": self.client_id}
            async with session.get(f"{HELIX_URL}/{path}", headers=headers, params=params, timeout=TIMEOUT) as response:
                if response.status == 401 and retry:
                    await self.authenticate(session)
                    continue
                if response.status != 200:
                    raise TwitchError(f"/{path} : HTTP {response.status}")
                return (await response.json())["data"]

    async def by_login(self, session: aiohttp.ClientSession, path: str, param: str, key: str, logins: list[str]) -> dict[str, dict]:
        found = {}
        for start in range(0, len(logins), MAX_LOGINS):
            params = [(param, login) for login in logins[start:start + MAX_LOGINS]]
            found |= {entry[key].lower(): entry for entry in await self.get(session, path, params)}
        return found

    async def streams(self, session: aiohttp.ClientSession, logins: list[str]) -> dict[str, dict]:
        """Lives en cours, par pseudo."""
        return await self.by_login(session, "streams", "user_login", "user_login", logins)

    async def users(self, session: aiohttp.ClientSession, logins: list[str]) -> dict[str, dict]:
        """Comptes existants, par pseudo."""
        return await self.by_login(session, "users", "login", "login", logins)


class Twitch:
    """Suivi des streamers de streamer_followed (URL -> live déjà annoncé)."""

    def __init__(self):
        self.api = TwitchApi(os.getenv('TWITCH_CLIENT_ID'), os.getenv('TWITCH_CLIENT_SECRET'))
        self.last_seen: dict[str, dt.datetime] = {}  # dernière présence en live, en mémoire
        self.missing: set[str] = set()               # pseudos introuvables, déjà signalés
        self.users_checked_at: dt.datetime | None = None
        self.users_checked_for: set[str] = set()

    async def check(self, channel):
        """Un tour de suivi. Une panne de l'API arrête le tour sans rien modifier ;
        les erreurs propres à un streamer n'empêchent pas de traiter les autres et remontent à la fin."""
        if channel is None:
            raise TwitchError("salon des lives introuvable")
        followed = settings_file_management.get_entry('streamer_followed')
        if not followed:
            return
        urls = {login_from_url(url): url for url in followed}
        now = dt.datetime.now(dt.UTC)
        async with aiohttp.ClientSession() as session:
            streams = await self.api.streams(session, list(urls))
            errors = await self.report_missing(session, set(urls), now)
            for login, url in urls.items():
                try:
                    await self.update_streamer(session, login, url, followed[url], streams.get(login), channel, now)
                except Exception as error:
                    errors.append(f"{login} : {type(error).__name__}: {error}")
        if errors:
            raise TwitchError(" | ".join(errors))

    async def report_missing(self, session: aiohttp.ClientSession, logins: set[str], now: dt.datetime) -> list[str]:
        """Streamers renommés ou bannis : /streams ne les signale pas, seul /users le fait. Un seul message par disparition."""
        due = self.users_checked_at is None or now - self.users_checked_at >= USERS_CHECK_INTERVAL
        if not due and logins == self.users_checked_for:
            return []
        missing = logins - set(await self.api.users(session, sorted(logins)))
        new = missing - self.missing
        self.users_checked_at, self.users_checked_for, self.missing = now, logins, missing
        return [f"{login} : introuvable sur Twitch (renommé ou banni ?)" for login in sorted(new)]

    async def update_streamer(self, session: aiohttp.ClientSession, login: str, url: str, announced: bool,
                              stream: dict | None, channel, now: dt.datetime):
        if stream:
            self.last_seen[login] = now
            if not announced:
                user = (await self.api.users(session, [login])).get(login, {})
                await TwitchMessage.message_online(stream, url, channel, user.get('profile_image_url'), login == MENTIONED_LOGIN)
                self.mark(url, True)  # après l'envoi : une annonce en échec sera retentée au tour suivant
        elif announced and now - self.last_seen.setdefault(login, now) >= OFFLINE_GRACE:
            self.mark(url, False)
            del self.last_seen[login]

    def mark(self, url: str, announced: bool):
        settings_file_management.update_entry(main_key='streamer_followed', new_data={url: announced})


twitch = Twitch()
