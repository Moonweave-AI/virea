"""Use stdlib deadlines, with the upstream backport on Python 3.10."""

import sys

if sys.version_info >= (3, 11):
    from asyncio import timeout as timeout
else:
    from async_timeout import timeout as timeout
