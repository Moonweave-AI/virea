from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


def main() -> None:
    pid_path = Path(sys.argv[1])
    child = subprocess.Popen(
        (
            "python3",
            "-c",
            "import sys, time; "
            "print('guest child inherited output', flush=True); "
            "print('guest child inherited error', file=sys.stderr, flush=True); "
            "time.sleep(120)",
        ),
        stdin=subprocess.DEVNULL,
        shell=False,
    )
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(f"{os.getpid()}\n{child.pid}\n", encoding="ascii")
    print("guest parent output", flush=True)
    while True:
        time.sleep(0.1)


if __name__ == "__main__":
    main()
