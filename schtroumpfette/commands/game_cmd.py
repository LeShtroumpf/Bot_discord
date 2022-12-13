import json

import random as rd
from ressource.embed import GeoGuessrChallenge


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
        return self.dict_map, self.dict_url, self.dict_defi

    async def challenge(self, channel):
        rand_num = str(rd.randint(1, len(self.dict_map)))
        map = self.dict_map[rand_num]
        url = self.dict_url[rand_num]
        defi_key = str(rd.randint(1, len(self.dict_defi)))
        challenge_geo = self.dict_defi[defi_key]
        if rand_num == '3':
            department = rd.randint(1, 95)
            await GeoGuessrChallenge.challenge1(
                channel,
                map,
                challenge_geo,
                department
            )

        elif rand_num == '6':
            await GeoGuessrChallenge.challenge2(channel, url)

        elif rand_num != '3' or rand_num != '6':
            await GeoGuessrChallenge.challenge3(
                channel,
                map,
                url,
                challenge_geo
            )


GeoGuessr = GeoGuessr()
