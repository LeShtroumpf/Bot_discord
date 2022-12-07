import requests as rq


class Nsfw:
    def __int__(self):
        pass

    def get_gif(self):
        url = 'https://nekobot.xyz/api/image'
        params = {'type': 'pgif'}
        response = rq.get(url=url, params=params)
        response = response.json()
        return response['message']


Nsfw = Nsfw()
