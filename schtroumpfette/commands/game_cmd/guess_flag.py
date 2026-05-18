from datetime import datetime
import asyncio
import random as rd

from discord.ui import Button
import discord

from utils.call_url import CallUrl


class FlagButton(discord.ui.View):
    def __init__(self, countries: list, good_answer: str):
        super().__init__()
        self.user_answer = []
        self.good_answer = good_answer

        for country in countries:
            button = Button(
                label=country,
                style=discord.ButtonStyle.primary,
                custom_id=country
            )
            button.callback = self.on_button_click
            self.add_item(button)

    async def on_button_click(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user = interaction.user.name

        if interaction.data["custom_id"] == self.good_answer:
            if user not in self.user_answer:
                self.user_answer.append(user)
        else:
            if user in self.user_answer:
                self.user_answer.remove(user)

    async def disable(self, message):
        for child in self.children:
            child.disabled = True
            if child.label == self.good_answer:
                child.style = discord.ButtonStyle.success
        await message.edit(view=self)


class GuessFlag:

    def __init__(self):
        self.guess_flag = dict()
        self.country_choose = list()

    async def guessing_flag(self, interaction: discord.Interaction):
        try:
            self.guess_flag.clear()

            response = CallUrl.send_request(
                url="https://flagcdn.com/fr/codes.json",
                method="GET"
            ).json()

            self.country_choose = rd.sample(list(response), 4)
            for country in self.country_choose:
                self.guess_flag[country] = response[country]

            choose_flag = rd.randint(0, 3)
            flag_url = f"https://flagcdn.com/h240/{self.country_choose[choose_flag]}.png"
            good_answer = self.guess_flag[self.country_choose[choose_flag]]
            countries = list(self.guess_flag.values())

            embed_flag = discord.Embed(
                title="Quel est ce pays?",
                description="",
                colour=0x6312b4,
                timestamp=datetime.now()
            )
            embed_flag.set_author(name="La Schtroumpfette")
            embed_flag.set_image(url=flag_url)
            embed_flag.set_footer(text="Schtroumpfette inc")

            # Une seule instance de FlagButton
            view = FlagButton(countries=countries, good_answer=good_answer)
            await interaction.response.send_message(embed=embed_flag, view=view)
            message = await interaction.original_response()

            # Timer 10 secondes
            await asyncio.sleep(10)

            # Désactiver les boutons
            await view.disable(message)

            # Annoncer le résultat
            await self.give_answer(interaction, view.user_answer, good_answer)

        except Exception as e:
            print(f"Erreur guessing_flag : {e}")
            try:
                await interaction.followup.send("Une erreur est survenue !")
            except Exception:
                pass

    async def give_answer(self, interaction: discord.Interaction, user_answer: list, good_answer: str):
        try:
            if not user_answer:
                msg = f"Dommage, la bonne réponse était **{good_answer}**"
            elif len(user_answer) == 1:
                msg = f"Bravo à **{user_answer[0]}** pour la bonne réponse qui était **{good_answer}** !"
            else:
                winners = ", ".join(f"**{u}**" for u in user_answer)
                msg = f"Bravo à {winners} pour avoir trouvé la bonne réponse qui est **{good_answer}** !"

            await interaction.followup.send(msg)

        except Exception as e:
            print(f"Erreur give_answer : {e}")

    def code_to_country(self, guess_flag: dict):
        return list(guess_flag.values())


GuessFlag = GuessFlag()