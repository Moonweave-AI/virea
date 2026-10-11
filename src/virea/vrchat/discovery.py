"""Advertise the bridge's receive port via the official OSCQuery handshake."""

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4


class OSCQuery:
    def __init__(self, osc_port):
        self.osc_port = osc_port
        self.name = f"VIREA-{uuid4().hex[:8]}"
        self.http = None
        self.thread = None
        self.zeroconf = None
        self.services = []

    def open(self):
        from zeroconf import IPVersion, ServiceInfo, Zeroconf

        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/?HOST_INFO":
                    payload = {
                        "NAME": owner.name,
                        "OSC_IP": "127.0.0.1",
                        "OSC_PORT": owner.osc_port,
                        "OSC_TRANSPORT": "UDP",
                        "EXTENSIONS": {"ACCESS": True, "VALUE": False},
                    }
                elif self.path in ("/", "/avatar"):
                    avatar = {
                        "FULL_PATH": "/avatar",
                        "ACCESS": 2,
                        "CONTENTS": {
                            "change": {
                                "FULL_PATH": "/avatar/change",
                                "ACCESS": 2,
                                "TYPE": "s",
                            },
                            "parameters": {
                                "FULL_PATH": "/avatar/parameters",
                                "ACCESS": 2,
                            },
                        },
                    }
                    payload = (
                        avatar
                        if self.path == "/avatar"
                        else {"FULL_PATH": "/", "CONTENTS": {"avatar": avatar}}
                    )
                else:
                    self.send_error(404)
                    return
                data = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_):
                pass

        try:
            self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
            self.thread.start()
            self.zeroconf = Zeroconf(
                interfaces=["127.0.0.1"], ip_version=IPVersion.V4Only
            )
            for kind, port in (
                ("_osc._udp.local.", self.osc_port),
                ("_oscjson._tcp.local.", self.http.server_port),
            ):
                service = ServiceInfo(
                    kind,
                    f"{self.name}.{kind}",
                    addresses=[socket.inet_aton("127.0.0.1")],
                    port=port,
                    server=f"{self.name}.local.",
                )
                self.zeroconf.register_service(service)
                self.services.append(service)
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.zeroconf:
            for service in self.services:
                self.zeroconf.unregister_service(service)
            self.zeroconf.close()
            self.zeroconf = None
            self.services.clear()
        if self.http:
            self.http.shutdown()
            self.http.server_close()
            self.thread.join(timeout=2)
            self.http = None
