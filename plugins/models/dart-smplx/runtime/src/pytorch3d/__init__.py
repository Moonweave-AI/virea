"""Pure-PyTorch subset of :mod:`pytorch3d` required by pinned DART.

The public API intentionally contains only ``transforms``. It avoids compiled
PyTorch3D platform wheels while preserving the official rotation conventions.
"""

from . import transforms

__all__ = ["transforms"]
