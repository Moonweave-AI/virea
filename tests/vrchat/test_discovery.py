import json
import urllib.request

import pytest

from virea.vrchat.discovery import OSCQuery


def test_oscquery_host_info_advertises_actual_receive_port_and_avatar_tree():
    pytest.importorskip("zeroconf")
    query = OSCQuery(19401)
    query.open()
    try:
        url = f"http://127.0.0.1:{query.http.server_port}"
        with urllib.request.urlopen(url + "/?HOST_INFO", timeout=3) as response:
            info = json.load(response)
        assert (
            info["OSC_IP"] == "127.0.0.1"
            and info["OSC_PORT"] == 19401
            and info["OSC_TRANSPORT"] == "UDP"
        )
        with urllib.request.urlopen(url, timeout=3) as response:
            tree = json.load(response)
        assert tree["CONTENTS"]["avatar"]["CONTENTS"]["change"]["TYPE"] == "s"
        assert len(query.services) == 2
    finally:
        query.close()
