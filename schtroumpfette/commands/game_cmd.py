import random as rd
from settings import dict_map, dict_url, dict_defi
from ressource.embed import GeoGuessrChallenge


class GeoGuessr:

    async def challenge(self, channel):
        rand_num = rd.randint(1, len(dict_map))
        map = dict_map[rand_num]
        url = dict_url[rand_num]
        challenge_geo = dict_defi[rd.randint(1, len(dict_defi))]
        if rand_num == 3:
            department = rd.randint(1, 95)
            await GeoGuessrChallenge.challenge1(
                channel,
                map,
                challenge_geo,
                department
            )

        elif rand_num == 6:
            await GeoGuessrChallenge.challenge2(channel, url)

        elif rand_num != 3 or rand_num != 6:
            await GeoGuessrChallenge.challenge3(
                channel,
                map,
                url,
                challenge_geo
            )


GeoGuessr = GeoGuessr()
