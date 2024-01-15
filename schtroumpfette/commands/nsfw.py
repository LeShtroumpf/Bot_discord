from utils.call_url import CallUrl

class Nsfw:
    def __int__(self):
        pass

    def get_gif(self):
        url = 'https://nekobot.xyz/api/image'
        params = {'type': 'pgif'}
        response = CallUrl.send_request(url, "GET", params=params)
        response = response.json()
        return response['message']


Nsfw = Nsfw()
