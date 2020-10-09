import discord
from discord.ext import commands
import asyncio
import youtube_dl

TOKEN = 'NzUxMzM1MDI4ODM4ODkxNjAw.X1HlRg.qRR7nanlnUvxyihmhbneTN8X8Ok'

description = '''Bot discord python by Le Shtroumpf#6750'''
bot = commands.Bot(command_prefix='$', description=description)
GUILD = "Les Champions du dimanche"


@bot.event
async def on_ready():
    channel = bot.get_channel(752057616041246740)
    for guild in bot.guilds:
        if guild.name == GUILD:
            break
    print(f'{bot.user} has connected to the following guild:\n'
          f'{guild.name}(id: {guild.id})')
    activity = discord.Game(name="La vie ressemble à une longue course "
                                 "d'obstacles, mais le principale obstacle, c'est soi-même.")
    await bot.change_presence(status=discord.Status.idle, activity=activity)
    await channel.purge(limit=1)
    await channel.send(f"Réagis pour avoir ton rôle.")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.errors.CheckFailure):
        await ctx.send(f"Tu n'as pas le droit d'utiliser cette commande petit chenapan! :wink:")


@bot.event
async def on_member_join(member):
    channel = bot.get_channel(442710531271426058)
    await member.send(f"Bonjour {member.mention} et bienvenue sur le discord: __**{GUILD}**__.\n"
                      f" Nous sommes une communauté de joueurs sur divers jeux mais sur une seule platforme: PC.\n"
                      f"Tu peux aller dans la section 'rôles' pour choisir le jeu sur lequel tu es et si jamais "
                      f"tu souhaites ajouter un jeu, n'hésites pas à demander.")
    await channel.send(f'{member.mention} vient de rejoindre le serveur.')


@bot.event
async def on_reaction_add(reaction, user):
    channel = 752057616041246740
    if reaction.message.channel.id != channel:
        return
    else:
        if reaction.emoji.name == 'sot':
            role = discord.utils.get(user.guild.roles, id=529584341055963137)
            await user.add_roles(role)
        if reaction.emoji.name == 'Monsterhunter':
            role = discord.utils.get(user.guild.roles, id=723262020203446373)
            await user.add_roles(role)
        if reaction.emoji.name =='ksp':
            role = discord.utils.get(user.guild.roles, id=727152365505085532)
            await user.add_roles(role)
        if reaction.emoji.name == 'satisfactory':
            role = discord.utils.get(user.guild.roles, id=726916741577572394)
            await user.add_roles(role)
        if reaction.emoji.name == 'empyrion':
            role = discord.utils.get(user.guild.roles, id=743765801009545236)
            await user.add_roles(role)
        if reaction.emoji.name == 'fs20':
            role = discord.utils.get(user.guild.roles, id=751843044768350328)
            await user.add_roles(role)
        if reaction.emoji.name == 'warframe':
            role = discord.utils.get(user.guild.roles, id=752060513143488542)
            await user.add_roles(role)
        if reaction.emoji.name =='division2':
            role = discord.utils.get(user.guild.roles, id=682178457261965374)
            await user.add_roles(role)


@bot.event
async def on_reaction_remove(reaction, user):
    channel = 752057616041246740
    if reaction.message.channel.id != channel:
        print(f"Pas le bon channel!")
        return
    else:
        if reaction.emoji.name == 'sot':
            role = discord.utils.get(user.guild.roles, id=529584341055963137)
            await user.remove_roles(role)
        if reaction.emoji.name == 'Monsterhunter':
            role = discord.utils.get(user.guild.roles, id=723262020203446373)
            await user.remove_roles(role)
        if reaction.emoji.name =='ksp':
            role = discord.utils.get(user.guild.roles, id=727152365505085532)
            await user.remove_roles(role)
        if reaction.emoji.name == 'satisfactory':
            role = discord.utils.get(user.guild.roles, id=726916741577572394)
            await user.remove_roles(role)
        if reaction.emoji.name == 'empyrion':
            role = discord.utils.get(user.guild.roles, id=743765801009545236)
            await user.remove_roles(role)
        if reaction.emoji.name == 'fs20':
            role = discord.utils.get(user.guild.roles, id=751843044768350328)
            await user.remove_roles(role)
        if reaction.emoji.name == 'warframe':
            role = discord.utils.get(user.guild.roles, id=752060513143488542)
            await user.remove_roles(role)
        if reaction.emoji.name =='division2':
            role = discord.utils.get(user.guild.roles, id=682178457261965374)
            await user.remove_roles(role)


class Modo(commands.Cog):
    """Outils de modération."""

    @commands.command()
    async def test(self, ctx, arg):
        await ctx.send(arg)

    @commands.command(name="clear", help="Supprime le nombre de message voulu dans le channel.")
    @commands.has_role("Les Champions du Dimanche" or "Les colombus")
    async def clear(self, ctx, amount=2):
        await ctx.channel.purge(limit=amount+1)


# Suppress noise about console usage from errors
youtube_dl.utils.bug_reports_message = lambda: ''


ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': False,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '78.229.135.231' # bind to ipv4 since ipv6 addresses cause issues sometimes
}

ffmpeg_options = {
    'options': '-vn'
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)


class YTDLSource(discord.PCMVolumeTransformer):

    def __init__(self, source, *, data, volume=50):
        super().__init__(source, volume)

        self.data = data

        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if 'entries' in data:
            # take first item from a playlist
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def join(self, ctx, *, channel: discord.VoiceChannel):
        """Joins a voice channel"""

        if ctx.voice_client is not None:
            return await ctx.voice_client.move_to(channel)

        await channel.connect()

    @commands.command()
    async def play(self, ctx, *, query):
        """Plays a file from the local filesystem"""

        source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(query))
        ctx.voice_client.play(source, after=lambda e: print('Player error: %s' % e) if e else None)

        await ctx.send('En lecture: {}'.format(query))

    @commands.command()
    async def yt(self, ctx, *, url):
        """Plays from a url (almost anything youtube_dl supports)"""

        async with ctx.typing():
            player = await YTDLSource.from_url(url, loop=self.bot.loop)
            ctx.voice_client.play(player, after=lambda e: print('Player error: %s' % e) if e else None)

        await ctx.send('En lecture: {}'.format(player.title))

    @commands.command()
    async def stream(self, ctx, *, url):
        """Streams from a url (same as yt, but doesn't predownload)"""

        async with ctx.typing():
            player = await YTDLSource.from_url(url, loop=self.bot.loop, stream=True)
            ctx.voice_client.play(player, after=lambda e: print('Player error: %s' % e) if e else None)

        await ctx.send('En lecture: {}'.format(player.title))

    @commands.command()
    async def volume(self, ctx, volume: int):
        """Changes the player's volume"""

        if ctx.voice_client is None:
            return await ctx.send("Not connected to a voice channel.")

        ctx.voice_client.source.volume = volume / 100
        await ctx.send("Volume passé à: {}%".format(volume))

    @commands.command()
    async def stop(self, ctx):
        """Stops and disconnects the bot from voice"""

        await ctx.voice_client.disconnect()

    @play.before_invoke
    @yt.before_invoke
    @stream.before_invoke
    async def ensure_voice(self, ctx):
        if ctx.voice_client is None:
            if ctx.author.voice:
                await ctx.author.voice.channel.connect()
            else:
                await ctx.send("Tu n'es pas en vocal.")
                raise commands.CommandError("Author not connected to a voice channel.")
        elif ctx.voice_client.is_playing():
            ctx.voice_client.stop()


bot.add_cog(Music(bot))
bot.add_cog(Modo())
bot.run(TOKEN)
