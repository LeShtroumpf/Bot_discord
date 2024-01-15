import os
import string

import time

from utils.embed import TwitchMessage
from utils.call_url import CallUrl


class Twitch:
    def __init__(self):
        self.token = str()
        self.client_id = os.environ['CLIENT_ID']
        self.favorite_streamer = ['streamer url']

    def gettoken(self):
        """get app access token"""
        client_secret = os.environ['CLIENT_SECRET']
        gettoken = CallUrl.send_request(
            "https://id.twitch.tv/oauth2/token",
            "POST",
            params={
                'client_id': self.client_id,
                'client_secret': client_secret,
                'grant_type': 'client_credentials'
            })
        access_token = gettoken.json()
        self.token = f'Bearer {access_token["access_token"]}'

    async def is_online_streamer(self, channel):
        """Check if a streamer is online and get the streamer id"""
        already_post = list()

        if not self.token:
            self.gettoken()

        for streamer_url in self.favorite_streamer:
            name = self.get_streamer_name(streamer_url)
            get_online_stream = CallUrl.send_request(
                f'{streamer_url}',
                "GET"
            ).content.decode('utf-8')
            if 'isLiveBroadcast' in get_online_stream and\
                    name not in already_post:
                findstreamer = CallUrl.send_request(
                    'https://api.twitch.tv/helix/users',
                    "GET",
                    headers={
                        'Authorization': self.token,
                        'Client-Id': self.client_id
                    },
                    params={
                        'login': name,
                    }
                )

                if findstreamer.status_code != 200:
                    self.gettoken()
                else:
                    streamer = findstreamer.json()
                    streamer_id = streamer['data'][0]['id']
                    profile_img = streamer['data'][0]['profile_image_url']
                    await self.get_data_stream(
                        streamer_id,
                        streamer_url,
                        channel,
                        profile_img
                    )
                    already_post.append(name)
                    time.sleep(5)
            else:
                already_post.remove(name)

    async def get_data_stream(
            self,
            streamer_id,
            streamer_url,
            channel,
            profil_img
    ):
        """Get data of an online streamer"""
        data = CallUrl.send_request(
            'https://api.twitch.tv/helix/streams',
            "GET",
            headers={
                'Authorization': self.token,
                'Client-Id': self.client_id
            },
            params={
                'user_id': streamer_id
            }
        )
        data_to_analyse = data.json()
        await TwitchMessage.online(
            data_to_analyse,
            streamer_url,
            channel,
            profil_img
        )

    def get_streamer_name(self, url: string):
        """Get the name login of a streamer"""
        name = url.split('/')
        return name[-1]


twitch = Twitch()
