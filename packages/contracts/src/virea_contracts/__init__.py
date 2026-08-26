"""Stable, model-runtime-neutral VIREA contracts.

The package intentionally does not import NumPy, Torch, CUDA, model code, or
the legacy :mod:`virea` package.  It is safe to install in both the control
plane and isolated workers.
"""

from .accelerator import canonical_nvidia_uuid, nvidia_uuid_equal
from .evidence import (
    ManagedApiLifecycle,
    ProductionBrowserObservation,
    ProductionE2EEvidence,
)
from .execution import (
    ExecutionDomainKind,
    ExecutionTargetSelection,
    execution_domain_id,
)
from .installation import TERMINAL_INSTALLATION_STATES, InstallationState
from .job import TERMINAL_JOB_STATES, JobRequest, JobState
from .machine import AcceleratorReport, ExecutionDomainReport, MachineReport
from .model import (
    ModelDefinition,
    ModelIdentity,
    ModelSupportStatus,
    ProductionAcceptanceExpectation,
    ProductionArtifactKind,
    ProductionE2EAcceptance,
    ProductionE2EAcceptanceSuite,
    ProductionE2EStage,
)
from .motion_ir import MotionIRDescriptor
from .representation import RepresentationProfile
from .result import ArtifactRef, ModelResult, NativeMotionDescriptor
from .runtime import (
    AcceleratorSpec,
    MemoryStrategy,
    ResourceProfile,
    RuntimeBackend,
    RuntimeSpec,
)
from .runtime_identity import RUNTIME_CORE_EPOCH
from .skeleton import SkeletonProfile
from .vrm import ActorExportIdentity, ExportRecord, ResultIdentity, VrmMotionResult
from .worker import (
    RuntimeCoreIdentity,
    WorkerError,
    WorkerInferRequest,
    WorkerMetadata,
    WorkerStartupFailure,
)

__all__ = [
    "TERMINAL_INSTALLATION_STATES",
    "TERMINAL_JOB_STATES",
    "AcceleratorReport",
    "AcceleratorSpec",
    "ArtifactRef",
    "ActorExportIdentity",
    "ExecutionDomainKind",
    "ExecutionDomainReport",
    "ExecutionTargetSelection",
    "ExportRecord",
    "InstallationState",
    "JobRequest",
    "JobState",
    "MachineReport",
    "ManagedApiLifecycle",
    "MemoryStrategy",
    "ModelDefinition",
    "ModelIdentity",
    "ModelResult",
    "ModelSupportStatus",
    "MotionIRDescriptor",
    "NativeMotionDescriptor",
    "ProductionAcceptanceExpectation",
    "ProductionBrowserObservation",
    "ProductionE2EEvidence",
    "ProductionArtifactKind",
    "ProductionE2EAcceptance",
    "ProductionE2EAcceptanceSuite",
    "ProductionE2EStage",
    "RepresentationProfile",
    "ResultIdentity",
    "ResourceProfile",
    "RuntimeBackend",
    "RuntimeCoreIdentity",
    "RuntimeSpec",
    "SkeletonProfile",
    "VrmMotionResult",
    "WorkerError",
    "WorkerInferRequest",
    "WorkerMetadata",
    "WorkerStartupFailure",
    "RUNTIME_CORE_EPOCH",
    "canonical_nvidia_uuid",
    "execution_domain_id",
    "nvidia_uuid_equal",
]

__version__ = "0.4.0"
