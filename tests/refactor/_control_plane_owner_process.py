from __future__ import annotations

import sys
import time
from pathlib import Path

from virea_api.coordination import ControlPlaneOwnership, ControlPlaneOwnershipError
from virea_core.db import StateStore
from virea_core.paths import VireaPaths


def main() -> int:
    home = Path(sys.argv[1])
    signal = Path(sys.argv[2])
    hold = sys.argv[3] == "hold"
    store = StateStore(VireaPaths(home))
    try:
        ownership = ControlPlaneOwnership.acquire(store)
    except ControlPlaneOwnershipError:
        signal.write_text("blocked", encoding="ascii")
        return 3
    signal.write_text("acquired", encoding="ascii")
    try:
        if hold:
            deadline = time.monotonic() + 30.0
            while (
                time.monotonic() < deadline and not signal.with_suffix(".stop").exists()
            ):
                time.sleep(0.05)
    finally:
        ownership.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
