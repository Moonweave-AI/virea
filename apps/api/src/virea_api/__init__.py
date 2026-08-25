from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .app import app as app
    from .app import create_app as create_app

__all__ = ["app", "create_app"]

__version__ = "0.4.0"


def __getattr__(name: str) -> Any:
    """Load the ASGI application only when the public app API is requested.

    Python executes a package's ``__init__`` before importing any child module.
    Keeping the application import lazy lets library users import modules such as
    ``virea_api.service`` without requiring the separately built Web distribution.
    The documented ``from virea_api import app, create_app`` and
    ``uvicorn virea_api:app`` surfaces still resolve to the original objects.
    """

    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from .app import app as application
    from .app import create_app as application_factory

    # Cache both exports together. Importlib temporarily assigns the ``app``
    # submodule to this package while loading it; replacing that attribute here
    # preserves the existing package-level FastAPI application contract.
    globals()["app"] = application
    globals()["create_app"] = application_factory
    return globals()[name]


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
