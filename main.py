import os

import discord
from discord.ext import commands
from commande.commands import (
    everyone,
    game_cmd,
    modo,
)
from commande.client.event import EventListener


def main():
    command_prefix = "$"
    description = '''Bot discord by Le Shtroumpf#6750'''
    intents = discord.Intents.all()
    token = os.environ['TOKEN']
    bot = EventListener(
        command_prefix=command_prefix,
        description=description,
        intents=intents,
    )
    cogs = ['commande.commands.everyone', 'commande.commands.game_cmd', 'commande.commands.modo']
    for cog in cogs:
        bot.load_extension(cog)
    bot.run(token)


if __name__ == "__main__":
    main()
