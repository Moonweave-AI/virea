from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


def main() -> None:
    pid_path = Path(sys.argv[1])
    child = subprocess.Popen(
        (sys.executable, "-c", "import time; time.sleep(120)"),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
    )
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(f"{os.getpid()}\n{child.pid}\n", encoding="ascii")
    while True:
        time.sleep(0.1)


if __name__ == "__main__":
    main()
