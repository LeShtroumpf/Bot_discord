import json
from unittest.mock import patch

import pytest
import requests

from utils.call_url import TIMEOUT, CallUrl
from utils.file_management import settings_file_management


def test_update_entry_on_an_empty_section(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "settings.json").write_text(json.dumps({"section": {}}), encoding="utf-8")
    settings_file_management.update_entry(main_key="section", new_data={"cle": 1})
    assert json.loads((tmp_path / "settings.json").read_text(encoding="utf-8")) == {"section": {"cle": 1}}


def test_call_url_lets_the_real_error_through():
    with patch("utils.call_url.rq.request", side_effect=requests.ConnectionError("réseau")):
        with pytest.raises(requests.ConnectionError):
            CallUrl.send_request("http://x", "GET")


def test_call_url_has_a_timeout():
    with patch("utils.call_url.rq.request") as request:
        CallUrl.send_request("http://x", "POST", params={"a": 1})
    assert request.call_args.kwargs["timeout"] == TIMEOUT


def test_call_url_refuses_other_methods():
    with pytest.raises(ValueError):
        CallUrl.send_request("http://x", "PUT")
