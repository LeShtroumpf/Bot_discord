import os
from dotenv import load_dotenv

from utils.call_url import CallUrl
from utils.embed import TwitchMessage
from utils.file_management import settings_file_management

load_dotenv()


class Twitch:
    def __init__(self):
        self.token = None
        self.client_id = os.getenv('TWITCH_CLIENT_ID')
        self.already_post = []

    async def is_online_streamer(self, channel):
        """Check if a streamer is online and get the streamer id"""
        favorite_streamer = self._load_streamer_followed()

        if not self.token:
            self._gettoken()

        for streamer_url in favorite_streamer.keys():
            name = self._get_streamer_name(streamer_url)
            try:
                get_streamer_status = CallUrl.send_request(
                    url='https://api.twitch.tv/helix/streams',
                    method='GET',
                    headers={
                        'Authorization': self.token,
                        'Client-Id': self.client_id
                    },
                    params={
                        'user_login': name
                    }
                )
            except Exception as e:
                print("error get_streamer_status", e)
            if get_streamer_status.status_code != 200:
                self._gettoken()
            try:
                streamer_data_request = CallUrl.send_request(
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
            except Exception as e:
                print("error streamer_data_request: ", e)
            streamer_status = get_streamer_status.json()
            streamer_data = streamer_data_request.json()
            profile_img = streamer_data['data'][0]['profile_image_url']
            if streamer_status['data'] != [] and favorite_streamer[streamer_url] is False:
                viewer_tag = False
                if streamer_url == "https://www.twitch.tv/le_shtroumpf":
                    viewer_tag = True
                settings_file_management.update_entry(
                    main_key='streamer_followed',
                    new_data={streamer_url: True},
                )
                await TwitchMessage.message_online(
                    streamer_status,
                    streamer_url,
                    channel,
                    profile_img, viewer_tag
                )
            elif streamer_status['data'] == [] and favorite_streamer[streamer_url] is True:
                settings_file_management.update_entry(
                    main_key='streamer_followed',
                    new_data={streamer_url: False},
                )

    def _get_streamer_name(self, url: str) -> str:
        """Get the name login of a streamer"""
        name = url.split('/')
        return name[-1]

    def _gettoken(self) -> str:
        """get app access token"""
        client_secret = os.getenv('TWITCH_CLIENT_SECRET')
        try:
            gettoken = CallUrl.send_request(
                "https://id.twitch.tv/oauth2/token",
                "POST",
                params={
                    'client_id': self.client_id,
                    'client_secret': client_secret,
                    'grant_type': 'client_credentials'
                })
        except Exception as e:
            print("error gettoken", e)
        if gettoken.status_code == 200:
            access_token = gettoken.json()
            self.token = f'Bearer {access_token["access_token"]}'
            return self.token
        else:
            raise ValueError(f"Invalid token: {gettoken.json()}")

    def _load_streamer_followed(self):
        favorite_streamer = settings_file_management.get_entry('streamer_followed')
        return favorite_streamer


twitch = Twitch()
