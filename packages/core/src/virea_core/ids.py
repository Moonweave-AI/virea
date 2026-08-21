from __future__ import annotations

import os
import time

_CROCKFORD32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode_crockford(value: int, length: int) -> str:
    output = ["0"] * length
    for index in range(length - 1, -1, -1):
        output[index] = _CROCKFORD32[value & 31]
        value >>= 5
    if value:
        raise ValueError("value does not fit requested Crockford base32 length")
    return "".join(output)


def new_ulid(timestamp_ms: int | None = None) -> str:
    """Create a sortable ULID without using content digests.

    ULIDs identify local jobs and records; they are not used as integrity or
    authorization codes.
    """

    now_ms = int(time.time_ns() // 1_000_000) if timestamp_ms is None else timestamp_ms
    if now_ms < 0 or now_ms >= 2**48:
        raise ValueError("timestamp_ms must fit 48 bits")
    randomness = int.from_bytes(os.urandom(10), byteorder="big")
    return _encode_crockford(now_ms, 10) + _encode_crockford(randomness, 16)
