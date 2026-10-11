"""Bounded, read-only diagnostics for the selected local client's online session.

Only diagnostic states leave this module; log lines, account IDs and credentials
are never included in API responses. OSC readiness is a separate contract.
"""

import json
import os
import re
import sys
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .room_invites import PREFIX, api_invitation_receipt, invitation_event

API_RECOVERED = (
    "VIREA API verified by a newer invitation delivered to the other account"
)


@dataclass
class _LogCursor:
    offset: int = 0
    modified: int = 0
    sequence: int = 0
    account: str = ""
    skipping: bool = False
    events: dict = field(default_factory=dict)
    api_error_at: float | None = None
    api_receipts: dict = field(default_factory=dict)

    def accept(self, line):
        self.sequence += 1
        authenticated = re.search(
            r"User Authenticated: .*\((usr_[0-9a-f-]{36})\)", line
        )
        if authenticated:
            self.account = authenticated[1]
            self.api_error_at = None
            self.api_receipts.clear()
            self.events.pop("authentication", None)
            self.events.pop("room", None)
            self.events.pop("arrival", None)
            for key in list(self.events):
                if key.startswith("invite:"):
                    self.events.pop(key)
            self.events["identity"] = (
                self.sequence,
                f"User Authenticated: ({self.account})",
            )
        if '"Missing Credentials"' in line or '"Logged out"' in line:
            marker = (
                '"Logged out"' if '"Logged out"' in line else '"Missing Credentials"'
            )
            self.events["authentication"] = (self.sequence, marker)
            self.api_error_at = None
            if marker == '"Missing Credentials"':
                try:
                    self.api_error_at = datetime.strptime(
                        line[:19], "%Y.%m.%d %H:%M:%S"
                    ).timestamp()
                except ValueError:
                    pass  # Undated failures cannot safely be superseded.
            else:
                self.api_receipts.clear()
            for key in list(self.events):
                if key.startswith("invite:"):
                    self.events.pop(key)
        receipt = api_invitation_receipt(line)
        if (
            receipt
            and receipt["recipient"] == self.account
            and receipt["sender"] != self.account
        ):
            sender = receipt["sender"]
            if receipt["created"] > self.api_receipts.get(sender, {}).get("created", 0):
                self.api_receipts[sender] = receipt
            while len(self.api_receipts) > 32:
                self.api_receipts.pop(next(iter(self.api_receipts)))
        invite = invitation_event(line)
        if invite and invite["recipient"] == self.account:
            key = "invite:" + invite.pop("id")
            if invite.pop("removed"):
                self.events.pop(key, None)
            else:
                self.events[key] = (self.sequence, PREFIX + json.dumps(invite))
                invitations = [key for key in self.events if key.startswith("invite:")]
                for old in invitations[:-32]:
                    self.events.pop(old)
        if "You are in offline testing mode" in line:
            self.events["connection"] = (
                self.sequence,
                "You are in offline testing mode",
            )
        elif "Connected to master in " in line:
            self.events["connection"] = (self.sequence, "Connected to master in online")
        elif "OnDisconnected:" in line:
            previous = self.events.get("connection", (0, ""))[1]
            if "offline testing mode" not in previous:
                self.events["connection"] = (self.sequence, "OnDisconnected:")
        joined = re.search(r"\[Behaviour\] Joining (wrld_[^\s]+)", line)
        if joined:
            self.events["room"] = (self.sequence, f"[Behaviour] Joining {joined[1]}")
            self.events.pop("arrival", None)
        if self.account and "OnPlayerJoined " in line and f"({self.account})" in line:
            self.events["arrival"] = (self.sequence, f"OnPlayerJoined ({self.account})")
        if "OnLeftRoom" in line or "OnDisconnected:" in line or '"Logged out"' in line:
            self.events.pop("room", None)
            self.events.pop("arrival", None)


_LOG_CURSORS = OrderedDict()
_LOG_LOCK = threading.Lock()


def _session_log_text(path):
    """Incrementally retain session evidence, not an ever-growing raw log tail."""
    with _LOG_LOCK:
        stat = path.stat()
        cursor = _LOG_CURSORS.pop(path, None)
        if (
            cursor is None
            or stat.st_size < cursor.offset
            or (stat.st_size == cursor.offset and stat.st_mtime_ns != cursor.modified)
        ):
            cursor = _LogCursor()
        _LOG_CURSORS[path] = cursor
        while len(_LOG_CURSORS) > 16:
            _LOG_CURSORS.popitem(last=False)
        cursor.modified = stat.st_mtime_ns
        budget = 4 * 1024 * 1024
        with path.open("rb") as stream:
            stream.seek(cursor.offset)
            while budget > 0:
                start = stream.tell()
                raw = stream.readline(min(16384, budget))
                if not raw:
                    break
                budget -= len(raw)
                if not raw.endswith(b"\n"):
                    if len(raw) < 16384 and budget > 0:
                        # Do not promote partially written events; retry after append.
                        cursor.offset = start
                        return ""
                    cursor.skipping = True
                elif cursor.skipping:
                    cursor.skipping = False
                else:
                    cursor.accept(raw.decode("utf-8", errors="replace"))
                cursor.offset = stream.tell()
        if cursor.offset < path.stat().st_size:
            return ""  # Initial catch-up is still incomplete.
        # A native successful write, corroborated by the other account, can
        # recover a historical 401 without forcing logout. Silence, Photon,
        # OSC, a public-world response, and receiving a message cannot do so.
        if cursor.account and cursor.api_error_at is not None:
            for peer in _LOG_CURSORS.values():
                receipt = peer.api_receipts.get(cursor.account)
                if (
                    peer is not cursor
                    and peer.account != cursor.account
                    and receipt
                    and receipt["recipient"] == peer.account
                    and receipt["created"] > cursor.api_error_at + 10
                    and receipt["received"] > cursor.api_error_at + 10
                ):
                    cursor.events["authentication"] = (cursor.sequence, API_RECOVERED)
                    cursor.api_error_at = None
                    break
        return "\n".join(line for _, line in sorted(cursor.events.values()))


def authentication_status(text):
    """Report log evidence, not current room connectivity or a re-login requirement."""
    state = "unknown"
    for line in text.splitlines():
        if "User Authenticated:" in line or line == API_RECOVERED:
            state = "authenticated_in_log"
        elif '"Logged out"' in line:
            state = "signed_out_in_log"
        elif '"Missing Credentials"' in line:
            state = "api_auth_error_in_log"
    return state


def connection_status(text):
    """Classify explicit session evidence without mistaking login or EAC for a room."""
    state = "unknown"
    for line in text.splitlines():
        if "You are in offline testing mode" in line:
            state = "offline_testing"
        elif "Connected to master in " in line:
            state = "online_session_in_log"
        elif "OnDisconnected:" in line and state != "offline_testing":
            state = "disconnected_in_log"
    return state


def room_evidence(text):
    """Keep identities local; a join request alone is not evidence of arrival."""
    account = room = None
    members = set()
    for line in text.splitlines():
        authenticated = re.search(
            r"User Authenticated: .*\((usr_[0-9a-f-]{36})\)", line
        )
        if authenticated:
            account = authenticated[1]
            room = None
            members.clear()
        joined = re.search(r"\[Behaviour\] Joining (wrld_[^\s]+)", line)
        if joined:
            room = joined[1]
            members.clear()
        player = re.search(r"OnPlayerJoined .*\((usr_[0-9a-f-]{36})\)", line)
        if player:
            members.add(player[1])
        if "OnLeftRoom" in line or "OnDisconnected:" in line or '"Logged out"' in line:
            room = None
            members.clear()
    return (account, room) if account and room and account in members else None


def _client_log_text(process):
    started = process.create_time()
    root = Path(os.environ["USERPROFILE"]) / "AppData/LocalLow/VRChat/VRChat"
    candidates = []
    ports = None
    for path in root.glob("output_log_*.txt"):
        stamp = re.fullmatch(
            r"output_log_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})\.txt", path.name
        )
        if not stamp:
            continue
        when = datetime.strptime(stamp[1], "%Y-%m-%d_%H-%M-%S").timestamp()
        if abs(when - started) < 10:
            candidates.append(path)
        elif 0 <= when - started <= 120:
            # Protected-client startup can take longer than ten seconds. A
            # wider time window alone could attach the observer's log, so only
            # admit delayed logs whose launch OSC port belongs to this PID.
            if ports is None:
                import psutil

                ports = {
                    item.laddr.port
                    for item in psutil.net_connections(kind="udp4")
                    if item.pid == process.pid
                }
            with path.open("rb") as stream:
                header = stream.read(16384).decode("utf-8", errors="replace")
            osc = re.search(r"Arg: --osc=(\d+):", header)
            if osc and int(osc[1]) in ports:
                candidates.append(path)
    if len(candidates) != 1:
        return ""
    return _session_log_text(candidates[0])


def selected_client_status(pid):
    result = {
        "authentication": "unknown",
        "connection": "unknown",
        "same_instance": "unverified",
    }
    if sys.platform != "win32":
        return result
    try:
        import psutil
    except ImportError:
        return result
    try:
        process = psutil.Process(pid)
        if process.name().lower() != "vrchat.exe":
            return result
        text = _client_log_text(process)
        result["authentication"] = authentication_status(text)
        result["connection"] = connection_status(text)
        current_room = room_evidence(text)
        if current_room:
            for peer in psutil.process_iter(["pid", "name"]):
                if peer.pid == pid or (peer.info["name"] or "").lower() != "vrchat.exe":
                    continue
                try:
                    peer_room = room_evidence(_client_log_text(peer))
                    if (
                        peer_room
                        and peer_room[0] != current_room[0]
                        and peer_room[1] == current_room[1]
                    ):
                        result["same_instance"] = "matched_in_live_client_logs"
                        break
                except (OSError, ValueError, KeyError, psutil.Error):
                    continue
        return result
    except (OSError, ValueError, KeyError, psutil.Error):
        return result
