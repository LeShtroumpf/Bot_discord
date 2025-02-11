import json

from discord.ext import commands

from client.twitch import twitch


class ModoTwitch(commands.Cog):
    """Outils de gestion twitch."""
    def __init__(self, bot):
        self.bot = bot

    @commands.command(
        name="add_streamer",
        help="Ajouter le suivi des streams d'un streamer twitch"
    )
    @commands.has_role("Les Champions du Dimanche" or "Les colombus")
    async def add_streamer(self, ctx, streamer_url: str):
        try:
            with open('settings.json', 'r') as f:
                data = json.load(f)
        except FileNotFoundError:
            print('Erreur : Le fichier settings.json n\'a pas été trouvé.')
            return

            # Vérifier si l'élément existe déjà
        if streamer_url not in data['streamer_followed']:
            data['streamer_followed'].append(streamer_url)
        else:
            ctx.send('Streamer déjà présent dans la liste des streamers.')

        with open('settings.json', 'w') as f:
            json.dump(data, f, indent=4)

        twitch.reload_streamer_followed()

    @commands.command(
        name="remove_streamer",
        help="Supprime le suivi des streams d'un streamer twitch"
    )
    @commands.has_role("Les Champions du Dimanche" or "Les colombus")
    async def remove_streamer(self, ctx, streamer_url: str):
        try:
            with open('settings.json', 'r') as f:
                data = json.load(f)
        except FileNotFoundError:
            print('Erreur : Le fichier settings.json n\'a pas été trouvé.')
            return

        if streamer_url in data['streamer_followed']:
            data['streamer_followed'].remove(streamer_url)
        else:
            ctx.send('Le streamer n\'est pas présent dans la liste des streamers.')

        with open('settings.json', 'w') as f:
            json.dump(data, f, indent=4)

        twitch.reload_streamer_followed(url=streamer_url)

    @commands.command(
        name="get_streamer",
        help="Afficvhe les streamers dans la liste des streamers"
    )
    @commands.has_role("Les Champions du Dimanche" or "Les colombus")
    async def get_streamer(self, ctx):
        try:
            with open('settings.json', 'r') as f:
                data = json.load(f)
        except FileNotFoundError:
            print('Erreur : Le fichier settings.json n\'a pas été trouvé.')
            return
        streamer_name = []
        for steamer in data['streamer_followed']:
            streamer_name.append(steamer.split('/')[-1])
        await ctx.send("Streamer suivi: {}".format(streamer_name))


async def setup(bot):  # pragma: no cover
    await bot.add_cog(ModoTwitch(bot))
