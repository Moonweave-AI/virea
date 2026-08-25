from .catalog import CatalogError, ModelCatalog
from .installation import InvalidInstallationTransition, next_installation_states
from .manifest import ModelPluginManifest
from .pool import InstallOutcome, ModelPool, ModelVerificationCancelled

__all__ = [
    "CatalogError",
    "InstallOutcome",
    "InvalidInstallationTransition",
    "ModelCatalog",
    "ModelPluginManifest",
    "ModelPool",
    "ModelVerificationCancelled",
    "next_installation_states",
]

__version__ = "0.4.0"
