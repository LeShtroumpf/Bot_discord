import requests as rq


class CallUrl:

    @classmethod
    def send_request(self, url:str, method:str, headers:dict=None, params:dict=None) -> rq.Response:  # noqa
        if method not in ["GET", "POST"]:
            raise ValueError("wrong method called")
        if method == "GET":
            try:
                response = rq.get(url, headers=headers, params=params)
            except Exception as e:
                print(f"GET request error: {e}")
        if method == "POST":
            try:
                response = rq.post(url, headers=headers, params=params)
            except Exception as e:
                print(f"POST request error: {e}")
        return response


if __name__ == "__main__":  # pragma: no cover
    CallUrl = CallUrl()
