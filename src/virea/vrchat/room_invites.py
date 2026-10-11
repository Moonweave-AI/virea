"""Read only current-client invitation metadata, never authentication cookies."""

import json
import re
import time
from datetime import datetime, timezone

PREFIX = "VIREA room invitation: "
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


def api_invitation_receipt(line):
    """A delivered native invite/request proves the *sender's* API write.

    Receiving a pipeline message does not prove the recipient's REST session.
    This is authentication evidence only, never a private-room access grant.
    """
    match = re.match(
        rf"^(\d{{4}}\.\d{{2}}\.\d{{2}} \d{{2}}:\d{{2}}:\d{{2}}) Debug\s+-\s+"
        rf"Received Notification: <Notification from username:[^\r\n]*?, "
        rf"sender user id:(usr_{UUID}) to (usr_{UUID}) of type: (invite|requestInvite), "
        rf"id: not_{UUID}, created at: ([0-9/ :]+) UTC, details: ",
        line,
    )
    if not match:
        return None
    try:
        received = datetime.strptime(match[1], "%Y.%m.%d %H:%M:%S").timestamp()
        created = (
            datetime.strptime(match[5], "%m/%d/%Y %H:%M:%S")
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )
    except ValueError:
        return None
    # Reject old notifications replayed on login and implausible clock offsets.
    if not -10 <= received - created <= 600:
        return None
    return {
        "sender": match[2],
        "recipient": match[3],
        "created": created,
        "received": received,
    }


def invitation_event(line):
    # A chat message/username containing an invite-shaped string is not an
    # invitation. Require the exact game diagnostic record, type and IDs.
    prefix = re.match(
        r"^\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2} Debug\s+-\s+"
        r"(Received Notification: |Remove notification from (?:AllTime|Recent) notifications:)"
        r"<Notification from username:",
        line,
    )
    if not prefix:
        return None
    match = re.search(
        rf", sender user id:(usr_{UUID}) to (usr_{UUID}) of type: invite, "
        rf"id: (not_{UUID}), created at: ([0-9/ :]+) UTC, details: \{{\{{worldId="
        r"(wrld_[A-Za-z0-9_~().:+-]{1,1500})(?:,|\})",
        line[prefix.end() :],
    )
    if not match:
        return None
    try:
        created = (
            datetime.strptime(match[4], "%m/%d/%Y %H:%M:%S")
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )
    except ValueError:
        return None
    return {
        "sender": match[1],
        "recipient": match[2],
        "id": match[3],
        "created": created,
        "location": match[5],
        "removed": prefix[1].startswith("Remove"),
    }


def matching_invitation(text, host, guest, location, *, now=None):
    now = time.time() if now is None else now
    for line in text.splitlines():
        if not line.startswith(PREFIX):
            continue
        try:
            item = json.loads(line[len(PREFIX) :])
            age = now - item["created"]
            if (item["sender"], item["recipient"], item["location"]) == (
                host,
                guest,
                location,
            ) and 0 <= age <= 600:
                return {"worldId": location}
        except (ValueError, KeyError, TypeError):
            continue
    return None


def received_invitation(guest, host):
    import psutil

    from .client_status import _client_log_text, authentication_status, room_evidence

    try:
        process = psutil.Process(guest.pid)
        if (
            process.name().lower() != "vrchat.exe"
            or process.create_time() != guest.started
        ):
            return None
        text = _client_log_text(process)
        if authentication_status(text) != "authenticated_in_log" or room_evidence(
            text
        ) != (guest.account, guest.room):
            return None
        return matching_invitation(text, host.account, guest.account, host.room)
    except (OSError, ValueError, KeyError, psutil.Error):
        return None
