import os
import string

import time
import requests as rq

from ressource.embed import TwitchMessage


class Twitch:
    def __init__(self):
        self.token = str()
        self.client_id = os.environ['CLIENT_ID']
        self.favorite_streamer = ['twitch streamer url']

    def gettoken(self):
        """get app access token"""
        client_secret = os.environ['CLIENT_SECRET']

        gettoken = rq.post(
            'https://id.twitch.tv/oauth2/token',
            params={
                'client_id': self.client_id,
                'client_secret': client_secret,
                'grant_type': 'client_credentials'
            }
        )
        access_token = gettoken.json()
        self.token = f'Bearer {access_token["access_token"]}'

    async def is_online_streamer(self, channel):
        """Check if a streamer is online and get the streamer id"""
        already_post = list()

        if not self.token:
            self.gettoken()

        for streamer_url in self.favorite_streamer:
            name = self.get_streamer_name(streamer_url)
            get_online_stream = rq.get(
                f'{streamer_url}').content.decode('utf-8'
                                                  )
            if 'isLiveBroadcast' in get_online_stream and\
                    name not in already_post:
                findstreamer = rq.get(
                    'https://api.twitch.tv/helix/users',
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
        data = rq.get(
            'https://api.twitch.tv/helix/streams',
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
