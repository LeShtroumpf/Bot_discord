import os
import asyncio
from dotenv import load_dotenv
import discord

import client

load_dotenv()

command_prefix = "/"
description = '''Bot discord by Le Shtroumpf#6750'''
intents = discord.Intents.default()
intents.message_content = True  # Pour lire les messages
intents.members = True  # Pour les events membres (limité)
intents.guilds = True
intents.voice_states = True  # Pour les vocaux
intents.reactions = True  # Pour les réactions
intents.presences = False  # Ne track pas les statuts
intents.typing = False  # Ne track pas "en train d'écrire"

token = os.getenv('TOKEN')
bot = client.event.EventListener(
    command_prefix=command_prefix,
    description=description,
    intents=intents
)
cogs = ['commands.everyone', 'commands.moderation.modo', 'commands.moderation.twitch_cmd']


async def main():
    async with bot:
        await load_extension()
        await bot.start(token)


async def load_extension():
    for cog in cogs:
        await bot.load_extension(cog)

if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
