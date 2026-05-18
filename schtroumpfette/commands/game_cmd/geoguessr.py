import json
import random as rd

from utils.embed import GeoGuessrChallenge


class GeoGuessr:

    def __init__(self):
        self.dict_map = dict()
        self.dict_url = dict()
        self.dict_defi = dict()
        self.build()

    def build(self):
        """Get all local data from settings.json"""
        with open('settings.json', mode='r') as file:
            data = json.load(file)
        self.dict_defi = data['dict_defi']
        self.dict_url = data['dict_url']
        self.dict_map = data['dict_map']

    async def challenge(self, interaction):
        try:
            rand_num = str(rd.randint(1, len(self.dict_map)))
            map_name = self.dict_map[rand_num]
            url = self.dict_url[rand_num]
            defi_key = str(rd.randint(1, len(self.dict_defi)))
            challenge_geo = self.dict_defi[defi_key]

            if rand_num == '3':
                department = rd.randint(1, 95)
                await GeoGuessrChallenge.challenge1(interaction, map_name, challenge_geo, department)
            elif rand_num == '6':
                await GeoGuessrChallenge.challenge2(interaction, url)
            else:
                await GeoGuessrChallenge.challenge3(interaction, map_name, url, challenge_geo)

        except Exception as e:
            print(f"Erreur challenge : {e}")
            await interaction.followup.send("Une erreur est survenue !")