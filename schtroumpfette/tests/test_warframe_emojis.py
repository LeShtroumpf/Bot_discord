from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from commands import warframe as cog_module
from commands.warframe import Warframe
from warframe import emojis
from warframe.emojis import EMOJI_DIR, FACTIONS, STEMS, TIERS, emoji_name, load_images, plan, sync_emojis

PNG = b"\x89PNG\r\n\x1a\n"


def fake_emoji(name: str, emoji_id: int):
    emoji = MagicMock()
    emoji.name, emoji.id = name, emoji_id
    emoji.__str__ = lambda self: f"<:{self.name}:{self.id}>"
    emoji.delete = AsyncMock()
    return emoji


def write_images(directory, **images):
    for tier, data in images.items():
        (directory / f"tier{tier}.png").write_bytes(data)


def test_repo_has_an_image_per_tier_and_faction():
    images = load_images(EMOJI_DIR)
    assert set(images) == set(STEMS)
    assert all(data.startswith(PNG) for data in images.values())


def test_name_contains_image_fingerprint():
    assert emoji_name("SP", b"a").startswith("tierSP_")
    assert emoji_name("S", b"a") != emoji_name("S", b"b")  # image remplacée -> nouveau nom
    assert len(emoji_name("SP", b"a")) <= 32


def test_load_images_rejects_too_big(tmp_path):
    write_images(tmp_path, S=PNG + b"0" * (256 * 1024))
    with pytest.raises(ValueError):
        load_images(tmp_path)


def test_plan_keeps_creates_and_deletes():
    images = {"S": b"s", "A": b"a2"}
    up_to_date = fake_emoji(emoji_name("S", b"s"), 1)
    stale = fake_emoji(emoji_name("A", b"a1"), 2)      # ancienne image de A
    orphan = fake_emoji(emoji_name("B", b"b"), 3)      # plus de fichier pour B
    foreign = fake_emoji("pepe_dance", 4)              # pas géré par le bot : jamais touché
    result = plan([up_to_date, stale, orphan, foreign], images)
    assert result.keep == {"S": up_to_date}
    assert list(result.create) == ["A"]
    assert result.delete == [stale, orphan]


@pytest.mark.asyncio
async def test_sync_creates_then_deletes(tmp_path):
    write_images(tmp_path, S=b"s", SP=b"sp")
    stale = fake_emoji(emoji_name("SP", b"old"), 9)
    client = MagicMock()
    client.fetch_application_emojis = AsyncMock(return_value=[fake_emoji(emoji_name("S", b"s"), 1), stale])
    created = []

    async def create(name, image):
        assert not stale.delete.await_count  # l'ancien n'est supprimé qu'après la création
        created.append(name)
        return fake_emoji(name, 2)

    client.create_application_emoji = AsyncMock(side_effect=create)
    result = await sync_emojis(client, tmp_path)
    assert result == {"S": f"<:{emoji_name('S', b's')}:1>", "SP": f"<:{emoji_name('SP', b'sp')}:2>"}
    assert created == [emoji_name("SP", b"sp")]
    stale.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_sync_without_images_does_nothing(tmp_path):
    client = MagicMock(fetch_application_emojis=AsyncMock())
    assert await sync_emojis(client, tmp_path) == {}
    client.fetch_application_emojis.assert_not_awaited()


@pytest.mark.asyncio
async def test_cog_uses_managed_emojis():
    cog = Warframe(MagicMock(logs_channel_id="1"))
    with patch.object(emojis, "sync_emojis", AsyncMock(return_value={"S": "<:tierS_aaaaaaaa:1>"})):
        await cog.sync_emojis()
    assert cog.tier_emojis["S"] == "<:tierS_aaaaaaaa:1>"
    assert cog.tier_emojis["A"] == "🟩"  # les autres tiers gardent leur emoji par défaut


def test_faction_emojis_are_managed():
    stale = fake_emoji("factionCorpus_00000000", 1)
    result = plan([stale], {"FC_CORPUS": b"new"})
    assert result.delete == [stale]
    assert result.create["FC_CORPUS"][0] == emoji_name("FC_CORPUS", b"new")
    assert all(len(emoji_name(key, b"a")) <= 32 for key in FACTIONS)


@pytest.mark.asyncio
async def test_cog_splits_tier_and_faction_emojis():
    cog = Warframe(MagicMock(logs_channel_id="1"))
    managed = {"S": "<:tierS_aaaaaaaa:1>", "FC_CORPUS": "<:factionCorpus_aaaaaaaa:2>"}
    with patch.object(emojis, "sync_emojis", AsyncMock(return_value=managed)):
        await cog.sync_emojis()
    assert cog.faction_emojis == {"FC_CORPUS": "<:factionCorpus_aaaaaaaa:2>"}
    assert "FC_CORPUS" not in cog.tier_emojis


@pytest.mark.asyncio
async def test_cog_keeps_defaults_when_sync_fails():
    cog = Warframe(MagicMock(logs_channel_id="1"))
    failing = AsyncMock(side_effect=OSError("disque"))
    with patch.object(emojis, "sync_emojis", failing), \
            patch.object(cog_module.event_logs, "on_error_log", new=AsyncMock()) as logs:
        await cog.sync_emojis()
    assert cog.tier_emojis["S"] == "🟦"
    assert "emojis injoignable" in logs.call_args.args[1]


def test_bar_color_matches_emoji_letter():
    """La barre de l'embed a la couleur de la lettre de l'emoji (couleur dominante du PNG)."""
    from collections import Counter
    from io import BytesIO

    PIL = pytest.importorskip("PIL.Image")
    from warframe.arbitrations import TIER_COLORS
    for tier, data in ((key, image) for key, image in load_images(EMOJI_DIR).items() if key in TIERS):
        pixels = [p[:3] for p in PIL.open(BytesIO(data)).convert("RGBA").getdata() if p[3] > 250]
        r, g, b = Counter(pixels).most_common(1)[0][0]
        assert TIER_COLORS[tier] == (r << 16) + (g << 8) + b, tier
