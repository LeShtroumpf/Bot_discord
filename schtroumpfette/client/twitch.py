import os
from dotenv import load_dotenv

from utils.call_url import CallUrl
from utils.embed import TwitchMessage
from utils.file_management import settings_file_management

load_dotenv()

SHTROUMPF_URL = "https://www.twitch.tv/le_shtroumpf"


class Twitch:
    def __init__(self):
        self.token = None
        self.client_id = os.getenv('TWITCH_CLIENT_ID')

    async def is_online_streamer(self, channel):
        """Check if a streamer is online and post if so."""
        favorite_streamer = self._load_streamer_followed()

        if not self.token:
            self._gettoken()

        for streamer_url, is_posted in favorite_streamer.items():
            try:
                name = self._get_streamer_name(streamer_url)

                streamer_status = self._get_streamer_status(name)
                streamer_data = self._get_streamer_data(name)

                if streamer_status is None or streamer_data is None:
                    continue

                profile_img = streamer_data['data'][0]['profile_image_url']
                is_live = streamer_status['data'] != []

                if is_live and not is_posted:
                    viewer_tag = streamer_url == SHTROUMPF_URL
                    settings_file_management.update_entry(
                        main_key='streamer_followed',
                        new_data={streamer_url: True},
                    )
                    await TwitchMessage.message_online(
                        streamer_status,
                        streamer_url,
                        channel,
                        profile_img,
                        viewer_tag
                    )
                elif not is_live and is_posted:
                    settings_file_management.update_entry(
                        main_key='streamer_followed',
                        new_data={streamer_url: False},
                    )

            except Exception as e:
                print(f"Erreur is_online_streamer pour {streamer_url}: {e}")
                continue

    def _get_streamer_status(self, name: str) -> dict | None:
        """Get stream status for a streamer."""
        try:
            response = CallUrl.send_request(
                url='https://api.twitch.tv/helix/streams',
                method='GET',
                headers={'Authorization': self.token, 'Client-Id': self.client_id},
                params={'user_login': name}
            )
            if response.status_code == 401:
                self._gettoken()
                response = CallUrl.send_request(
                    url='https://api.twitch.tv/helix/streams',
                    method='GET',
                    headers={'Authorization': self.token, 'Client-Id': self.client_id},
                    params={'user_login': name}
                )
            return response.json()
        except Exception as e:
            print(f"Erreur _get_streamer_status ({name}): {e}")
            return None

    def _get_streamer_data(self, name: str) -> dict | None:
        """Get streamer profile data."""
        try:
            response = CallUrl.send_request(
                url='https://api.twitch.tv/helix/users',
                method='GET',
                headers={'Authorization': self.token, 'Client-Id': self.client_id},
                params={'login': name}
            )
            return response.json()
        except Exception as e:
            print(f"Erreur _get_streamer_data ({name}): {e}")
            return None

    def _get_streamer_name(self, url: str) -> str:
        """Extract streamer login name from URL."""
        return url.rstrip('/').split('/')[-1]

    def _gettoken(self) -> str:
        """Get Twitch app access token."""
        client_secret = os.getenv('TWITCH_CLIENT_SECRET')
        try:
            response = CallUrl.send_request(
                url="https://id.twitch.tv/oauth2/token",
                method="POST",
                params={
                    'client_id': self.client_id,
                    'client_secret': client_secret,
                    'grant_type': 'client_credentials'
                }
            )
            if response.status_code == 200:
                self.token = f'Bearer {response.json()["access_token"]}'
                return self.token
            else:
                raise ValueError(f"Token invalide: {response.json()}")
        except Exception as e:
            print(f"Erreur _gettoken: {e}")
            raise

    def _load_streamer_followed(self) -> dict:
        return settings_file_management.get_entry('streamer_followed')


twitch = Twitch()