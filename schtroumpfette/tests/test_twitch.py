import datetime as dt
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from client import twitch as twitch_module
from client.event import EventListener
from client.twitch import OFFLINE_GRACE, USERS_CHECK_INTERVAL, Twitch, TwitchApi, TwitchError, login_from_url, parse_streamer

STREAMER = "https://www.twitch.tv/toto"
SHTROUMPF = "https://www.twitch.tv/le_shtroumpf"
NOW = dt.datetime(2026, 11, 5, 12, 0, tzinfo=dt.UTC)


def stream(login="toto", game="Warframe", title="Un live") -> dict:
    return {"user_login": login, "game_name": game, "title": title, "thumbnail_url": "https://img/{width}x{height}.jpg"}


def set_followed(settings_file, followed: dict):
    data = json.loads(settings_file.read_text(encoding="utf-8"))
    data["streamer_followed"] = followed
    settings_file.write_text(json.dumps(data), encoding="utf-8")


def followed(settings_file) -> dict:
    return json.loads(settings_file.read_text(encoding="utf-8"))["streamer_followed"]


def tracker(streams=None, users=None) -> Twitch:
    """Suivi sans réseau : users par défaut = tous les comptes demandés existent."""
    track = Twitch()
    track.api = MagicMock()
    track.api.streams = AsyncMock(return_value=streams or {})
    track.api.users = AsyncMock(side_effect=users or (lambda session, logins: {login: {"login": login} for login in logins}))
    return track


def channel():
    return MagicMock(send=AsyncMock())


@pytest.mark.parametrize("text, expected", [
    ("toto", "toto"),
    ("Toto_42", "toto_42"),
    ("twitch.tv/toto", "toto"),
    ("https://www.twitch.tv/Toto/", "toto"),
    ("https://m.twitch.tv/toto", "toto"),
    ("  http://twitch.tv/toto  ", "toto"),
    ("https://youtube.com/toto", None),
    ("https://www.twitch.tv/videos/123", None),
    ("pas un pseudo", None),
    ("", None),
])
def test_parse_streamer(text, expected):
    assert parse_streamer(text) == expected


def test_login_from_url():
    assert login_from_url("https://www.twitch.tv/Toto/") == "toto"


@pytest.mark.asyncio
async def test_live_is_announced_then_marked(settings_file):
    set_followed(settings_file, {STREAMER: False})
    salon = channel()
    await tracker({"toto": stream()}).check(salon)
    assert salon.send.await_count == 1
    assert followed(settings_file) == {STREAMER: True}


@pytest.mark.asyncio
async def test_announced_live_is_not_posted_twice(settings_file):
    set_followed(settings_file, {STREAMER: True})
    salon = channel()
    await tracker({"toto": stream()}).check(salon)
    salon.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_announcement_is_retried_and_others_continue(settings_file):
    other = "https://www.twitch.tv/tata"
    set_followed(settings_file, {STREAMER: False, other: False})
    salon = channel()
    salon.send.side_effect = [RuntimeError("refusé"), None]
    track = tracker({"toto": stream(), "tata": stream("tata")})
    with pytest.raises(TwitchError, match="toto : RuntimeError: refusé"):
        await track.check(salon)
    assert followed(settings_file) == {STREAMER: False, other: True}


@pytest.mark.asyncio
async def test_short_outage_does_not_rearm(settings_file):
    set_followed(settings_file, {STREAMER: True})
    track = tracker()
    track.last_seen["toto"] = dt.datetime.now(dt.UTC) - OFFLINE_GRACE + dt.timedelta(minutes=1)
    await track.check(channel())
    assert followed(settings_file) == {STREAMER: True}


@pytest.mark.asyncio
async def test_long_offline_rearms(settings_file):
    set_followed(settings_file, {STREAMER: True})
    track = tracker()
    track.last_seen["toto"] = dt.datetime.now(dt.UTC) - OFFLINE_GRACE
    await track.check(channel())
    assert followed(settings_file) == {STREAMER: False}
    assert "toto" not in track.last_seen


@pytest.mark.asyncio
async def test_after_a_restart_offline_waits_for_the_grace_period(settings_file):
    set_followed(settings_file, {STREAMER: True})
    await tracker().check(channel())
    assert followed(settings_file) == {STREAMER: True}


@pytest.mark.asyncio
async def test_api_failure_changes_nothing(settings_file):
    set_followed(settings_file, {STREAMER: True})
    track = tracker()
    track.last_seen["toto"] = dt.datetime.now(dt.UTC) - OFFLINE_GRACE * 2
    track.api.streams.side_effect = TwitchError("/streams : HTTP 500")
    with pytest.raises(TwitchError):
        await track.check(channel())
    assert followed(settings_file) == {STREAMER: True}


@pytest.mark.asyncio
async def test_missing_channel_is_an_error():
    with pytest.raises(TwitchError, match="salon des lives introuvable"):
        await tracker().check(None)


@pytest.mark.asyncio
async def test_no_streamer_makes_no_request(settings_file):
    set_followed(settings_file, {})
    track = tracker()
    await track.check(channel())
    track.api.streams.assert_not_awaited()


@pytest.mark.asyncio
async def test_mention_depends_on_the_login(settings_file):
    set_followed(settings_file, {"https://twitch.tv/Le_Shtroumpf": False, STREAMER: False})
    salon = channel()
    await tracker({"le_shtroumpf": stream("le_shtroumpf"), "toto": stream()}).check(salon)
    messages = [call.args[0] for call in salon.send.await_args_list]
    assert "<@&" in messages[0] and messages[1] == ""


@pytest.mark.asyncio
async def test_missing_streamer_is_reported_once():
    track = tracker(users=lambda session, logins: {})
    assert (await track.report_missing(None, {"toto"}, NOW)) == ["toto : introuvable sur Twitch (renommé ou banni ?)"]
    assert (await track.report_missing(None, {"toto"}, NOW + USERS_CHECK_INTERVAL)) == []


@pytest.mark.asyncio
async def test_missing_streamer_can_be_reported_again_after_coming_back():
    track = tracker()
    track.missing = {"toto"}
    assert (await track.report_missing(None, {"toto"}, NOW)) == []
    assert track.missing == set()


@pytest.mark.asyncio
async def test_users_are_checked_every_hour_or_when_the_list_changes():
    track = tracker()
    await track.report_missing(None, {"toto"}, NOW)
    await track.report_missing(None, {"toto"}, NOW + USERS_CHECK_INTERVAL - dt.timedelta(minutes=1))
    assert track.api.users.await_count == 1
    await track.report_missing(None, {"toto"}, NOW + USERS_CHECK_INTERVAL)
    assert track.api.users.await_count == 2
    await track.report_missing(None, {"toto", "tata"}, NOW + USERS_CHECK_INTERVAL)
    assert track.api.users.await_count == 3


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status = status
        self.payload = payload

    async def json(self):
        return self.payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def session(*gets, token_status=200):
    fake = MagicMock()
    fake.get.side_effect = list(gets)
    fake.post.side_effect = lambda *args, **kwargs: FakeResponse(token_status, {"access_token": "jeton"})
    return fake


@pytest.mark.asyncio
async def test_secret_stays_out_of_the_url():
    fake = session()
    await TwitchApi("id", "secret").authenticate(fake)
    assert "secret" not in str(fake.post.call_args.args)
    assert fake.post.call_args.kwargs["data"]["client_secret"] == "secret"
    assert "params" not in fake.post.call_args.kwargs


@pytest.mark.asyncio
async def test_refused_token_does_not_leak_the_secret():
    with pytest.raises(TwitchError) as error:
        await TwitchApi("id", "secret").authenticate(session(token_status=403))
    assert "secret" not in str(error.value)


@pytest.mark.asyncio
async def test_expired_token_is_renewed_then_the_request_replayed():
    fake = session(FakeResponse(401), FakeResponse(200, {"data": [{"user_login": "Toto"}]}))
    api = TwitchApi("id", "secret")
    api.token = "vieux"
    assert await api.streams(fake, ["toto"]) == {"toto": {"user_login": "Toto"}}
    assert fake.get.call_args.kwargs["headers"]["Authorization"] == "Bearer jeton"


@pytest.mark.asyncio
async def test_repeated_401_is_an_error():
    api = TwitchApi("id", "secret")
    api.token = "vieux"
    with pytest.raises(TwitchError, match="HTTP 401"):
        await api.streams(session(FakeResponse(401), FakeResponse(401)), ["toto"])


@pytest.mark.asyncio
async def test_http_error_is_raised():
    api = TwitchApi("id", "secret")
    api.token = "jeton"
    with pytest.raises(TwitchError, match="/streams : HTTP 500"):
        await api.streams(session(FakeResponse(500)), ["toto"])


@pytest.mark.asyncio
async def test_logins_are_sent_by_batches():
    api = TwitchApi("id", "secret")
    api.token = "jeton"
    fake = session(FakeResponse(200, {"data": []}), FakeResponse(200, {"data": []}))
    await api.streams(fake, [f"s{i}" for i in range(150)])
    assert [len(call.kwargs["params"]) for call in fake.get.call_args_list] == [100, 50]


@pytest.mark.asyncio
@pytest.mark.parametrize("game, title, expected", [
    ("", "Un live", ("Un live", "Non renseigné")),
    ("Warframe", "", ("Sans titre", "Warframe")),
])
async def test_empty_stream_fields(game, title, expected):
    salon = channel()
    await twitch_module.TwitchMessage.message_online(stream(game=game, title=title), STREAMER, salon, None, False)
    embed = salon.send.await_args.kwargs["embed"]
    assert (embed.fields[0].value, embed.fields[1].value) == expected


@pytest.mark.asyncio
async def test_task_starts_once_in_setup_hook():
    listener = MagicMock()
    await EventListener.setup_hook(listener)
    listener.on_post_online_stream.start.assert_called_once()


@pytest.mark.asyncio
async def test_on_ready_does_not_start_the_task():
    listener = MagicMock()
    listener.tree.sync = AsyncMock(return_value=[])
    listener.event_actions.on_ready = AsyncMock()
    await EventListener.on_ready(listener)
    listener.on_post_online_stream.start.assert_not_called()


@pytest.mark.asyncio
async def test_task_passes_the_stream_channel():
    listener = MagicMock(stream_channel="1")
    with patch.object(twitch_module.twitch, "check", new=AsyncMock()) as check:
        await EventListener.on_post_online_stream.coro(listener)
    check.assert_awaited_once_with(listener.get_channel.return_value)
