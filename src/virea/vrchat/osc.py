"""Small bounded OSC 1.0 codec; wire types are part of the VRChat contract."""

import math
import struct

MAX_PACKET = 65507


def _string(value):
    if "\0" in value:
        raise ValueError("OSC strings cannot contain NUL")
    raw = value.encode("utf-8") + b"\0"
    return raw + b"\0" * (-len(raw) % 4)


def message(address, *values):
    if not address.startswith("/") or len(address) > 512:
        raise ValueError("invalid OSC address")
    tags, payload = ",", b""
    for value in values:
        if isinstance(value, bool):
            tags += "T" if value else "F"
        elif isinstance(value, int):
            tags += "i"
            payload += struct.pack(">i", value)
        elif isinstance(value, float) and math.isfinite(value):
            tags += "f"
            payload += struct.pack(">f", value)
        elif isinstance(value, str):
            tags += "s"
            payload += _string(value)
        else:
            raise ValueError("unsupported or non-finite OSC argument")
    packet = _string(address) + _string(tags) + payload
    if len(packet) > MAX_PACKET:
        raise ValueError("OSC packet exceeds UDP limit")
    return packet


def bundle(messages):
    packet = b"#bundle\0" + struct.pack(">Q", 1)
    for item in messages:
        packet += struct.pack(">I", len(item)) + item
    if len(packet) > MAX_PACKET:
        raise ValueError("OSC bundle exceeds UDP limit")
    return packet


def decode(packet, depth=0):
    if not packet or len(packet) > MAX_PACKET or depth > 4:
        raise ValueError("invalid OSC packet size or nesting")
    if packet.startswith(b"#bundle\0"):
        if len(packet) < 16:
            raise ValueError("short OSC bundle")
        offset, result = 16, []
        while offset < len(packet):
            if offset + 4 > len(packet):
                raise ValueError("short bundle element")
            size = struct.unpack_from(">I", packet, offset)[0]
            offset += 4
            if not size or offset + size > len(packet):
                raise ValueError("invalid bundle element size")
            result.extend(decode(packet[offset : offset + size], depth + 1))
            offset += size
        return result

    def string(offset):
        end = packet.find(b"\0", offset)
        if end < 0:
            raise ValueError("unterminated OSC string")
        next_offset = (end + 4) & ~3
        if next_offset > len(packet) or any(packet[end:next_offset]):
            raise ValueError("invalid OSC padding")
        return packet[offset:end].decode("utf-8"), next_offset

    try:
        address, offset = string(0)
        tags, offset = string(offset)
        if not address.startswith("/") or not tags.startswith(","):
            raise ValueError("invalid OSC header")
        values = []
        for tag in tags[1:]:
            if tag in "TF":
                value = tag == "T"
            elif tag == "s":
                value, offset = string(offset)
            elif tag in "if":
                value = struct.unpack_from(">" + tag, packet, offset)[0]
                offset += 4
                if isinstance(value, float) and not math.isfinite(value):
                    raise ValueError("non-finite OSC input")
            else:
                raise ValueError("unsupported OSC type")
            values.append(value)
        if offset != len(packet):
            raise ValueError("trailing OSC bytes")
        return [(address, values)]
    except (struct.error, UnicodeError) as exc:
        raise ValueError("malformed OSC packet") from exc


def release_messages(voice=False):
    values = [
        message(f"/input/{axis}", 0.0)
        for axis in ("Vertical", "Horizontal", "LookHorizontal")
    ]
    # Current clients advertise buttons as OSC booleans in OSCQuery.
    values += [message(f"/input/{button}", False) for button in ("Run", "Jump")]
    if voice:
        values.append(message("/input/Voice", False))
    return values
