"""Read the selected VRChat process's OSCQuery tree without advertising a receiver.

Discovery cannot redirect either client's UDP destination. Only the owner of the
configured OSC input port can supply identity; no logs or cached avatar files are
treated as live feedback.
"""

import asyncio
import time

import httpx

from .contracts import FACE_PARAMETERS, HAND_PARAMETERS, valid_avatar_id
from .osc import message


def local_client_endpoints(osc_port):
    import psutil

    try:
        owners = {
            item.pid
            for item in psutil.net_connections(kind="udp4")
            if item.pid
            and item.laddr.port == osc_port
            and item.laddr.ip in {"127.0.0.1", "0.0.0.0"}
        }
        if len(owners) != 1:
            return []
        pid = owners.pop()
        process = psutil.Process(pid)
        if process.name().lower() not in {"vrchat.exe", "vrchat"}:
            return []
        return [
            (pid, connection.laddr.port)
            for connection in process.net_connections(kind="tcp4")
            if connection.status == psutil.CONN_LISTEN
            and connection.laddr.ip == "127.0.0.1"
        ]
    except psutil.Error:
        return []


class ClientQuery:
    def __init__(self, config, protocol):
        self.config = config
        self.protocol = protocol
        self.endpoint = None
        self.verified = False

    async def read(self, client, port):
        base = f"http://127.0.0.1:{port}"
        host = await client.get(base + "/?HOST_INFO")
        host.raise_for_status()
        info = host.json()
        if (
            info.get("OSC_PORT") != self.config.send_port
            or info.get("OSC_IP") != "127.0.0.1"
            or info.get("OSC_TRANSPORT") != "UDP"
            or not str(info.get("NAME", "")).startswith("VRChat-Client-")
        ):
            raise ValueError("OSCQuery endpoint does not match the dedicated AI port")
        response = await client.get(base + "/avatar")
        response.raise_for_status()
        return response.json()

    def apply(self, tree, pid, port):
        contents = tree.get("CONTENTS", {})
        identity = contents.get("change", {}).get("VALUE", [])
        avatar = identity[0] if len(identity) == 1 else None
        previous = self.protocol.values.get("avatar_id", (None,))[0]
        if avatar != previous or not valid_avatar_id(avatar):
            self.protocol.datagram_received(
                message("/avatar/change", avatar if isinstance(avatar, str) else ""),
                ("127.0.0.1", self.config.send_port),
            )
        if not valid_avatar_id(avatar):
            raise ValueError("AI avatar is loading or has no supported identity")
        nodes = contents.get("parameters", {}).get("CONTENTS", {})
        supported = {"AI_Active", *FACE_PARAMETERS, *HAND_PARAMETERS}
        parameters = sorted(supported.intersection(nodes))
        for name, node in nodes.items():
            value = node.get("VALUE", [])
            if len(value) == 1 and isinstance(value[0], (bool, int, float)):
                self.protocol.datagram_received(
                    message(f"/avatar/parameters/{name}", value[0]),
                    ("127.0.0.1", self.config.send_port),
                )
        # Initial auto-binding requires a verified process and the installed rig.
        # Later avatar switches retain the pin and close the output gate.
        if (
            self.config.auto_bind
            and not self.config.avatar_id
            and supported <= nodes.keys()
        ):
            self.config.avatar_id = avatar
        self.protocol.query_checked = time.monotonic()
        self.protocol.query_status = {
            "state": "verified",
            "pid": pid,
            "port": port,
            "parameters": parameters,
            "missing_parameters": sorted(supported - nodes.keys()),
            "local_avatar": avatar.startswith("local:sdk_"),
        }
        self.verified = True

    async def run(self):
        from .client_status import selected_client_status

        async with httpx.AsyncClient(timeout=1.5, trust_env=False) as client:
            while True:
                try:
                    # Re-check process ownership every cycle, including PID/port reuse.
                    endpoints = await asyncio.to_thread(
                        local_client_endpoints, self.config.send_port
                    )
                    matched = False
                    for pid, port in endpoints:
                        try:
                            tree = await self.read(client, port)
                            self.apply(tree, pid, port)
                            self.protocol.query_status[
                                "online"
                            ] = await asyncio.to_thread(selected_client_status, pid)
                            matched = True
                            break
                        except (httpx.HTTPError, ValueError, TypeError, KeyError):
                            continue
                    if not matched:
                        self.protocol.query_status = {
                            "state": "waiting",
                            "detail": "Waiting for the AI client's OSCQuery endpoint",
                        }
                except (ImportError, OSError, RuntimeError) as exc:
                    self.protocol.query_status = {
                        "state": "unavailable",
                        "detail": str(exc)[:200],
                    }
                await asyncio.sleep(1 if self.verified else 2)
