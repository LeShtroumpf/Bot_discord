import os

import discord
from client.event import EventListener

command_prefix = "$"
description = '''Bot discord by Le Shtroumpf#6750'''
intents = discord.Intents.all()
token = os.environ['TOKEN']
bot = EventListener(
    command_prefix=command_prefix,
    description=description,
    intents=intents,
)
cogs = ['commands.everyone', 'commands.modo', 'commands.roleplay']

if __name__ == "__main__":
    for cog in cogs:
        bot.load_extension(cog)
    bot.run(token)
