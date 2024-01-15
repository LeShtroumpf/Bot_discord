import requests as rq


class CallUrl:
    def __init__(self):
        pass

    def send_request(self, url:str, method:str, headers:dict=None, params:dict=None) -> rq.Response:  # noqa
        print(url, method, headers, params)
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


CallUrl = CallUrl()
