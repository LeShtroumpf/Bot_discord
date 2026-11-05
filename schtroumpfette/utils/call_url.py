import requests as rq

TIMEOUT = 10  # secondes


class CallUrl:

    @classmethod
    def send_request(cls, url: str, method: str, headers: dict = None, params: dict = None) -> rq.Response:
        if method not in ["GET", "POST"]:
            raise ValueError("wrong method called")
        return rq.request(method, url, headers=headers, params=params, timeout=TIMEOUT)


if __name__ == "__main__":  # pragma: no cover
    CallUrl = CallUrl()
