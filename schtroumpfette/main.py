import os
import asyncio
from dotenv import load_dotenv
import discord

import client

load_dotenv()

command_prefix = "$"
description = '''Bot discord by Le Shtroumpf#6750'''
intents = discord.Intents.all()
token = os.getenv('TOKEN')
bot = client.event.EventListener(
    command_prefix=command_prefix,
    description=description,
    intents=intents,
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
