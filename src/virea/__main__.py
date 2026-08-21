"""Allow running as `python -m virea`."""

import multiprocessing

from virea.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
