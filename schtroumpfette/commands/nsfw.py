from utils.call_url import CallUrl


class Nsfw:

    def get_gif(self) -> str:
        url = 'https://nekobot.xyz/api/image'
        params = {'type': 'pgif'}
        response = CallUrl.send_request(url=url, method="GET", params=params)
        response = response.json()
        return response['message']


nsfw = Nsfw()
