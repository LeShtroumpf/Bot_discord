import os
import asyncio

import discord
import client

command_prefix = "$"
description = '''Bot discord by Le Shtroumpf#6750'''
intents = discord.Intents.all()
token = os.environ['TOKEN']
bot = client.event.EventListener(
    command_prefix=command_prefix,
    description=description,
    intents=intents,
)
cogs = ['commands.everyone', 'commands.modo']


async def main():
    async with bot:
        await load_extension()
        await bot.start(token)


async def load_extension():
    for cog in cogs:
        await bot.load_extension(cog)

if __name__ == "__main__":
    asyncio.run(main())
