from .avatars import router as avatars_router
from .jobs import router as jobs_router
from .models import router as models_router
from .results import router as results_router
from .system import router as system_router

__all__ = [
    "avatars_router",
    "jobs_router",
    "models_router",
    "results_router",
    "system_router",
]
