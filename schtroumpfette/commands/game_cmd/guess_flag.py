from datetime import datetime
import asyncio
import random as rd

# from utils.call_url import CallUrl

from discord.ui import Button
import discord.integrations

from utils.call_url import CallUrl


class FlagButton(discord.ui.View):
    def __init__(self):
        self.user_answer = []
        super().__init__()
        self.message = None
        self.button1 = Button(
            label="{}".format(choose_country[0]),
            style=discord.ButtonStyle.primary,
            custom_id="{}".format(choose_country[0])
        )
        self.button1.callback = self.on_button_click
        self.button2 = Button(
            label="{}".format(choose_country[1]),
            style=discord.ButtonStyle.primary,
            custom_id="{}".format(choose_country[1])
        )
        self.button2.callback = self.on_button_click
        self.button3 = Button(
            label="{}".format(choose_country[2]),
            style=discord.ButtonStyle.primary,
            custom_id="{}".format(choose_country[2])
        )
        self.button3.callback = self.on_button_click
        self.button4 = Button(
            label="{}".format(choose_country[3]),
            style=discord.ButtonStyle.primary,
            custom_id="{}".format(choose_country[3])
        )
        self.button4.callback = self.on_button_click

        self.add_item(self.button1)
        self.add_item(self.button2)
        self.add_item(self.button3)
        self.add_item(self.button4)

    async def on_button_click(self, interaction: discord.Interaction):
        global global_user_answer
        await interaction.response.defer(ephemeral=True)

        user = interaction.user.name
        self.message = interaction.message
        if (user not in self.user_answer and
                interaction.data["custom_id"] == good_answer_reply):
            self.user_answer.append(user)
        if (user in self.user_answer and
                interaction.data["custom_id"] != good_answer_reply):
            self.user_answer.remove(user)
        global_user_answer = self.user_answer

    async def disable(self, message):
        for child in self.children:
            child.disabled = True
            if child.label == good_answer_reply:
                child.style = discord.ButtonStyle.success
        await message.edit(view=self)


class GuessFlag:

    def __init__(self):
        self.guess_flag = dict()
        self.country_choose = list()

    async def guessing_flag(self, ctx):

        global global_user_answer
        global_user_answer = []

        self.guess_flag.clear()

        response = CallUrl.send_request(
            url="https://flagcdn.com/fr/codes.json",
            method="GET"
        ).json()

        self.country_choose = rd.sample(list(response), 4)
        for country in self.country_choose:
            self.guess_flag[country] = response[country]
        choose_flag = rd.randint(0, 3)
        flag_url = (f"https://flagcdn.com/h240/"
                    f"{self.country_choose[choose_flag]}.png")
        good_answer = self.guess_flag[self.country_choose[choose_flag]]

        embed_flag = discord.Embed(
            title="Quel est ce pays?",
            description="",
            colour=0x6312b4,
            timestamp=datetime.now())
        embed_flag.set_author(name="La Schtroumpfette")
        embed_flag.set_image(url=flag_url)
        embed_flag.set_footer(text="Schtroumpfette inc")

        global good_answer_reply
        global choose_country
        good_answer_reply = good_answer
        choose_country = self.code_to_country(self.guess_flag)

        message = await ctx.channel.send(embed=embed_flag, view=FlagButton())

        task = asyncio.create_task(FlagButton().wait())
        loop = asyncio.get_event_loop()
        loop.call_later(10, lambda: task.cancel())
        try:
            await task
        except asyncio.CancelledError:
            pass
        await self.give_answer(ctx)
        await FlagButton().disable(message)

    async def give_answer(self, ctx):
        if not global_user_answer:
            await ctx.channel.send(
                "Dommage, la bonne réponse était {}".format(
                    good_answer_reply
                ))
        if len(global_user_answer) == 1:
            await ctx.channel.send(
                "Bravo a {} pour la bonne réponse qui était {}".format(
                    global_user_answer[0],
                    good_answer_reply
                ))
        if 1 < len(global_user_answer) < 5:
            message = "Bravo a "
            for user in global_user_answer:
                message += " {} , ".format(user)
            message += "pour avoir trouver la bonne réponse qui est {}".format(
                good_answer_reply
            )
            await ctx.channel.send(message)

    def code_to_country(self, guess_flag: dict):
        """renvoie les pays dans un liste en fonction des codes dans guess_flag"""  # noqa
        country_list = []
        for value in guess_flag.values():
            country_list.append(value)
        return country_list

GuessFlag = GuessFlag()
