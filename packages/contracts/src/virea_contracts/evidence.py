from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from urllib.parse import quote, urlsplit

from pydantic import Field, field_validator, model_validator

from .base import ContractModel
from .execution import ExecutionDomainKind
from .job import JobRequest
from .model import ProductionE2EStage
from .runtime import MemoryStrategy
from .worker import RuntimeCoreIdentity


def _relative_locator(value: str) -> str:
    normalized = value.replace("\\", "/")
    parts = normalized.split("/")
    if (
        not normalized
        or normalized.startswith("/")
        or ":" in parts[0]
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ValueError("evidence locators must be clean relative paths")
    return normalized


def result_artifact_url_path(result_id: str, locator: str) -> str:
    """Mirror Web ``artifactUrl``/JavaScript ``encodeURIComponent`` exactly."""

    artifact_name = locator.replace("\\", "/").split("/")[-1]
    javascript_safe = "!'()*-._~"
    return (
        f"/api/v1/results/{quote(result_id, safe=javascript_safe)}"
        f"/artifacts/{quote(artifact_name, safe=javascript_safe)}"
    )


class BrowserEvidenceProducer(ContractModel):
    id: Literal["virea.production_browser_e2e_runner"] = (
        "virea.production_browser_e2e_runner"
    )
    version: Literal["1.0.0"] = "1.0.0"
    capture_mode: Literal["out_of_process_browser_automation"] = (
        "out_of_process_browser_automation"
    )
    client_self_report_accepted: Literal[False] = False


class BrowserApplicationJavascriptHttpGetObservation(ContractModel):
    url_path: str
    method: Literal["GET"]
    status: Literal[200]
    body_byte_length: int = Field(gt=0)
    content_length: int | None = Field(gt=0)
    unique_request_count: Literal[1]
    unique_response_count: Literal[1]

    @field_validator("url_path")
    @classmethod
    def hashed_local_javascript_path(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme
            or parsed.netloc
            or parsed.query
            or parsed.fragment
            or parsed.path != value
            or re.fullmatch(r"/app/assets/index-[A-Za-z0-9_-]+\.js", value) is None
        ):
            raise ValueError(
                "application JavaScript observation must identify one hashed local asset"
            )
        return value

    @model_validator(mode="after")
    def content_length_matches_body(
        self,
    ) -> "BrowserApplicationJavascriptHttpGetObservation":
        if (
            self.content_length is not None
            and self.content_length != self.body_byte_length
        ):
            raise ValueError(
                "application JavaScript Content-Length differs from response body"
            )
        return self


class BrowserApplicationObservation(ContractModel):
    application_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    visible_version_label: str
    javascript: BrowserApplicationJavascriptHttpGetObservation

    @model_validator(mode="after")
    def version_is_visibly_rendered(self) -> "BrowserApplicationObservation":
        if self.visible_version_label != f"Motion Studio {self.application_version}":
            raise ValueError(
                "visible Motion Studio version differs from application version"
            )
        return self


class BrowserModelBinding(ContractModel):
    id: str
    plugin_version: str
    upstream_revision: str
    runtime_id: str


class BrowserJobBinding(ContractModel):
    id: str
    state: Literal["SUCCEEDED"]


class BrowserVrmaHttpGetObservation(ContractModel):
    url_path: str
    method: Literal["GET"]
    status: Literal[200]
    body_byte_length: int = Field(gt=0)
    content_length: int | None = Field(gt=0)
    unique_request_count: Literal[1]
    unique_response_count: Literal[1]

    @field_validator("url_path")
    @classmethod
    def local_result_artifact_path(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme
            or parsed.netloc
            or parsed.query
            or parsed.fragment
            or parsed.path != value
            or not value.startswith("/api/v1/results/")
        ):
            raise ValueError("VRMA HTTP observation must record one local URL path")
        return value

    @model_validator(mode="after")
    def content_length_matches_body(self) -> "BrowserVrmaHttpGetObservation":
        if (
            self.content_length is not None
            and self.content_length != self.body_byte_length
        ):
            raise ValueError("VRMA HTTP Content-Length differs from response body")
        return self


class BrowserVrmaBinding(ContractModel):
    actor_id: str
    locator: str
    byte_length: int = Field(gt=0)
    http_get: BrowserVrmaHttpGetObservation

    _clean_locator = field_validator("locator")(_relative_locator)


class BrowserResultBinding(ContractModel):
    result_id: str
    job_id: str
    model_id: str
    model_version: str
    runtime_variant_id: str
    checkpoint_revision: str
    native_representation_id: str
    native_skeleton_id: str
    target_representation_id: str
    target_skeleton_id: str
    resource_profile_id: str
    memory_strategy: MemoryStrategy
    device: str
    frame_count: int = Field(gt=0)
    vrma: BrowserVrmaBinding


class BrowserViewport(ContractModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    device_scale_factor: float = Field(gt=0)


class BrowserWebGLObservation(ContractModel):
    context: Literal["webgl", "webgl2"]
    vendor: str
    renderer: str
    version: str
    shading_language_version: str
    context_lost: Literal[False] = False


class BrowserRuntimeObservation(ContractModel):
    name: str
    version: str
    user_agent: str
    headless: bool
    viewport: BrowserViewport
    webgl: BrowserWebGLObservation


class AvatarEvidence(ContractModel):
    filename: str
    usage_basis: str
    redistributed: Literal[False] = False

    @field_validator("filename")
    @classmethod
    def basename_only(cls, value: str) -> str:
        if not value or "/" in value or "\\" in value:
            raise ValueError("avatar evidence records only the basename")
        if not value.lower().endswith((".vrm", ".glb")):
            raise ValueError("avatar evidence must identify a VRM/GLB file")
        return value


class ProjectedAvatarBounds(ContractModel):
    min_x: float = Field(ge=-1, le=1)
    min_y: float = Field(ge=-1, le=1)
    min_z: float = Field(ge=-1, le=1)
    max_x: float = Field(ge=-1, le=1)
    max_y: float = Field(ge=-1, le=1)
    max_z: float = Field(ge=-1, le=1)

    @model_validator(mode="after")
    def ordered(self) -> "ProjectedAvatarBounds":
        if not (
            self.min_x <= self.max_x
            and self.min_y <= self.max_y
            and self.min_z <= self.max_z
        ):
            raise ValueError("projected avatar bounds are not ordered")
        return self


class CanvasPlaybackObservation(ContractModel):
    css_width: float = Field(gt=0)
    css_height: float = Field(gt=0)
    backing_width: int = Field(gt=0)
    backing_height: int = Field(gt=0)
    render_frame_count: int = Field(ge=2)
    render_calls: int = Field(ge=1)
    render_triangles: int = Field(ge=1)
    fully_visible: Literal[True]
    projected_bounds: ProjectedAvatarBounds


class PlaybackObservation(ContractModel):
    viewer_telemetry_version: Literal["virea.viewer_telemetry.v1.0.0"]
    state: Literal["playing"]
    duration_seconds: float = Field(gt=0)
    mixer_time_before_seconds: float = Field(ge=0)
    mixer_time_after_seconds: float = Field(gt=0)
    observed_interval_ms: int = Field(ge=250)
    canvas: CanvasPlaybackObservation

    @model_validator(mode="after")
    def mixer_advanced(self) -> "PlaybackObservation":
        if self.mixer_time_after_seconds <= self.mixer_time_before_seconds:
            raise ValueError("AnimationMixer time did not advance")
        return self


class BrowserConsoleObservation(ContractModel):
    errors: tuple[str, ...] = Field(max_length=0)
    warnings: tuple[str, ...] = Field(max_length=0)
    page_errors: tuple[str, ...] = Field(max_length=0)
    request_failures: tuple[str, ...] = Field(max_length=0)


class EvidenceScreenshot(ContractModel):
    kind: Literal["job_result", "viewer", "canvas"]
    locator: str
    byte_length: int = Field(gt=0)

    _clean_locator = field_validator("locator")(_relative_locator)


class ProductionBrowserObservation(ContractModel):
    """Raw out-of-process browser observation.

    It intentionally has no promotion flag.  Only the independent
    ``ProductionE2EEvidence`` validator output can be recorded by the evidence
    registry.
    """

    schema_version: Literal["virea.production_browser_observation.v1.0.0"] = (
        "virea.production_browser_observation.v1.0.0"
    )
    kind: Literal["production_browser_observation"] = "production_browser_observation"
    run_id: str
    started_at: str
    completed_at: str
    generation_mode: Literal["fresh_web_job", "persisted_result_replay"]
    producer: BrowserEvidenceProducer
    base_url: str
    application: BrowserApplicationObservation
    model: BrowserModelBinding
    request: JobRequest
    job: BrowserJobBinding
    result: BrowserResultBinding
    browser: BrowserRuntimeObservation
    avatar: AvatarEvidence
    playback: PlaybackObservation
    console: BrowserConsoleObservation
    screenshots: tuple[EvidenceScreenshot, ...]

    @field_validator("base_url")
    @classmethod
    def loopback_control_plane(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("browser evidence must target a loopback control plane")
        return value.rstrip("/")

    @field_validator("started_at", "completed_at")
    @classmethod
    def timezone_aware_timestamp(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("evidence timestamps must include a timezone")
        return value

    @field_validator("screenshots")
    @classmethod
    def complete_screenshot_set(
        cls, value: tuple[EvidenceScreenshot, ...]
    ) -> tuple[EvidenceScreenshot, ...]:
        kinds = [item.kind for item in value]
        if len(value) != 3 or set(kinds) != {"job_result", "viewer", "canvas"}:
            raise ValueError("browser evidence requires job-result, viewer and canvas")
        return value

    @model_validator(mode="after")
    def coherent_bindings(self) -> "ProductionBrowserObservation":
        started = datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))
        completed = datetime.fromisoformat(self.completed_at.replace("Z", "+00:00"))
        if completed < started:
            raise ValueError("browser evidence completed before it started")
        if self.request.model_id != self.model.id:
            raise ValueError("browser request model differs from model binding")
        if self.result.job_id != self.job.id:
            raise ValueError("browser result job differs from job binding")
        if self.result.model_id != self.model.id:
            raise ValueError("browser result model differs from model binding")
        if self.result.model_version != self.model.plugin_version:
            raise ValueError("browser result plugin version differs")
        if self.result.runtime_variant_id != self.model.runtime_id:
            raise ValueError("browser result runtime differs")
        if self.result.checkpoint_revision != self.model.upstream_revision:
            raise ValueError("browser result checkpoint differs")
        expected_vrma_path = result_artifact_url_path(
            self.result.result_id, self.result.vrma.locator
        )
        if self.result.vrma.http_get.url_path != expected_vrma_path:
            raise ValueError(
                "browser VRMA GET URL differs from current result artifact"
            )
        if self.result.vrma.http_get.body_byte_length != self.result.vrma.byte_length:
            raise ValueError("browser VRMA response body differs from result artifact")
        return self


class RuntimeCoreEvidenceBinding(ContractModel):
    runtime_id: str
    project_package: str
    project_version: str
    runtime_core_epoch: str
    observed: RuntimeCoreIdentity

    @model_validator(mode="after")
    def observed_components_match_expected_epoch(self) -> "RuntimeCoreEvidenceBinding":
        if (
            self.observed.contracts_epoch != self.runtime_core_epoch
            or self.observed.model_sdk_epoch != self.runtime_core_epoch
        ):
            raise ValueError(
                "observed runtime core identity differs from expected epoch"
            )
        return self


class ManagedApiLifecycle(ContractModel):
    schema_version: Literal["virea.managed_api_lifecycle.v1.0.0"] = (
        "virea.managed_api_lifecycle.v1.0.0"
    )
    managed: Literal[True]
    process_spawned: Literal[True]
    started_at: str
    stopped_at: str
    pid: int = Field(gt=0)
    loopback_port: int = Field(gt=0, le=65535)
    stdin_eof_requested: Literal[True]
    graceful: Literal[True]
    forced: Literal[False]
    exit_code: Literal[0]
    exit_signal: None
    port_closed: Literal[True]
    port_close_method: Literal["connection_refused", "exclusive_bind_available"]

    @field_validator("started_at", "stopped_at")
    @classmethod
    def timezone_aware_timestamp(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("managed API lifecycle timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def ordered_lifecycle(self) -> "ManagedApiLifecycle":
        started = datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))
        stopped = datetime.fromisoformat(self.stopped_at.replace("Z", "+00:00"))
        if stopped < started:
            raise ValueError("managed API lifecycle timestamps are not ordered")
        return self


class BackendEvidenceBinding(ContractModel):
    validator_id: Literal["virea.production_e2e_evidence_validator.v1.1.0"] = (
        "virea.production_e2e_evidence_validator.v1.1.0"
    )
    status: Literal["passed"] = "passed"
    acceptance_schema_version: Literal["virea.real_e2e_acceptance.v1.0.0"]
    doctor_report_id: str
    doctor_recorded_at: str
    installation_id: str
    installation_created_at: str
    installation_ready_at: str
    acceptance_job_id: str
    acceptance_job_created_at: str
    acceptance_result_id: str
    acceptance_result_created_at: str
    acceptance_runtime_selection_at: str
    acceptance_worker_instance_id: str
    acceptance_worker_started_at: str
    acceptance_worker_stopped_at: str
    acceptance_runtime_core: RuntimeCoreEvidenceBinding
    license_acceptance_required: bool
    license_explicitly_accepted: bool
    license_acceptance_satisfied: Literal[True]
    license_source_urls: tuple[str, ...]
    worker_instance_id: str
    worker_process_identity_verifiable: Literal[True]
    execution_domain_id: str
    execution_domain_kind: ExecutionDomainKind
    execution_platform: str
    execution_architecture: str
    model_id: str
    runtime_id: str
    resource_profile_id: str
    memory_strategy: MemoryStrategy
    device: str
    job_id: str
    job_created_at: str
    runtime_selection_at: str
    generation_runtime_core: RuntimeCoreEvidenceBinding
    worker_started_at: str
    worker_stopped_at: str
    result_id: str
    result_created_at: str
    native_frame_count: int = Field(gt=0)
    vrma_locator: str
    vrma_byte_length: int = Field(gt=0)
    observation_locator: str
    backend_report_locator: str
    managed_api_lifecycle_schema_version: Literal["virea.managed_api_lifecycle.v1.0.0"]
    managed_api_lifecycle_locator: str
    managed_api_process_spawned: Literal[True]
    managed_api_started_at: str
    managed_api_stopped_at: str
    managed_api_pid: int = Field(gt=0)
    managed_api_loopback_port: int = Field(gt=0, le=65535)
    managed_api_stdin_eof_requested: Literal[True]
    managed_api_graceful: Literal[True]
    managed_api_forced: Literal[False]
    managed_api_exit_code: Literal[0]
    managed_api_exit_signal: None
    managed_api_port_closed: Literal[True]
    managed_api_port_close_method: Literal[
        "connection_refused", "exclusive_bind_available"
    ]
    backend_observed_port_close_method: Literal[
        "connection_refused", "exclusive_bind_available"
    ]
    control_plane_owner_lock_count: Literal[0]
    resource_lock_count: Literal[0]
    client_self_report_accepted: Literal[False] = False

    _clean_locators = field_validator(
        "vrma_locator",
        "observation_locator",
        "backend_report_locator",
        "managed_api_lifecycle_locator",
    )(_relative_locator)

    @field_validator(
        "doctor_recorded_at",
        "installation_created_at",
        "installation_ready_at",
        "acceptance_job_created_at",
        "acceptance_result_created_at",
        "acceptance_runtime_selection_at",
        "acceptance_worker_started_at",
        "acceptance_worker_stopped_at",
        "job_created_at",
        "runtime_selection_at",
        "worker_started_at",
        "worker_stopped_at",
        "result_created_at",
        "managed_api_started_at",
        "managed_api_stopped_at",
    )
    @classmethod
    def timezone_aware_chain_timestamp(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("backend evidence timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def ordered_production_chain(self) -> "BackendEvidenceBinding":
        def parsed(value: str) -> datetime:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))

        doctor = parsed(self.doctor_recorded_at)
        installation_created = parsed(self.installation_created_at)
        acceptance_job = parsed(self.acceptance_job_created_at)
        acceptance_selection = parsed(self.acceptance_runtime_selection_at)
        acceptance_worker_started = parsed(self.acceptance_worker_started_at)
        acceptance_result = parsed(self.acceptance_result_created_at)
        acceptance_worker_stopped = parsed(self.acceptance_worker_stopped_at)
        installation_ready = parsed(self.installation_ready_at)
        job = parsed(self.job_created_at)
        runtime_selection = parsed(self.runtime_selection_at)
        worker_started = parsed(self.worker_started_at)
        result = parsed(self.result_created_at)
        worker_stopped = parsed(self.worker_stopped_at)
        managed_api_started = parsed(self.managed_api_started_at)
        managed_api_stopped = parsed(self.managed_api_stopped_at)
        if not (
            doctor
            <= installation_created
            <= acceptance_job
            <= acceptance_selection
            <= acceptance_worker_started
            <= acceptance_result
            <= acceptance_worker_stopped
            <= job
            <= runtime_selection
            <= worker_started
            <= result
            <= worker_stopped
        ):
            raise ValueError("backend production evidence timeline is not ordered")
        if acceptance_result > installation_ready or installation_ready > job:
            raise ValueError(
                "READY installation is outside the fresh evidence timeline"
            )
        if managed_api_started > job or managed_api_stopped < worker_stopped:
            raise ValueError(
                "managed API lifecycle does not contain the fresh generation chain"
            )
        if self.acceptance_job_id == self.job_id:
            raise ValueError(
                "fresh browser job must differ from installation acceptance job"
            )
        if self.acceptance_result_id == self.result_id:
            raise ValueError(
                "fresh browser result must differ from installation acceptance result"
            )
        if self.acceptance_runtime_core != self.generation_runtime_core:
            raise ValueError(
                "acceptance and generation runtime core evidence must be identical"
            )
        if self.generation_runtime_core.runtime_id != self.runtime_id:
            raise ValueError("runtime core evidence differs from backend runtime id")
        if self.license_acceptance_required and not self.license_explicitly_accepted:
            raise ValueError(
                "required model license lacks explicit acceptance evidence"
            )
        return self


class EvidencePromotionDecision(ContractModel):
    eligible: Literal[True]
    maximum_model_status: Literal["integrated_experimental"]
    completed_stages: tuple[ProductionE2EStage, ...]
    ordinary_client_report_eligible: Literal[False] = False

    @field_validator("completed_stages")
    @classmethod
    def every_stage_once(
        cls, value: tuple[ProductionE2EStage, ...]
    ) -> tuple[ProductionE2EStage, ...]:
        if len(value) != len(ProductionE2EStage) or set(value) != set(
            ProductionE2EStage
        ):
            raise ValueError("validated evidence must complete every production stage")
        return value


class ProductionE2EEvidence(ContractModel):
    schema_version: Literal["virea.production_e2e_evidence.v1.1.0"] = (
        "virea.production_e2e_evidence.v1.1.0"
    )
    kind: Literal["validated_production_e2e"] = "validated_production_e2e"
    evidence_id: str
    recorded_at: str
    outcome: Literal["passed"] = "passed"
    observation: ProductionBrowserObservation
    backend: BackendEvidenceBinding
    promotion: EvidencePromotionDecision

    @field_validator("recorded_at")
    @classmethod
    def timezone_aware_recorded_at(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("evidence timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def browser_and_backend_are_same_chain(self) -> "ProductionE2EEvidence":
        observation = self.observation
        backend = self.backend
        if observation.generation_mode != "fresh_web_job":
            raise ValueError(
                "persisted-result browser replay is diagnostic-only and cannot promote"
            )
        matches = {
            "model": backend.model_id == observation.model.id,
            "runtime": backend.runtime_id == observation.model.runtime_id,
            "job": backend.job_id == observation.job.id,
            "result": backend.result_id == observation.result.result_id,
            "resource profile": (
                backend.resource_profile_id == observation.result.resource_profile_id
            ),
            "memory strategy": (
                backend.memory_strategy == observation.result.memory_strategy
            ),
            "device": backend.device == observation.result.device,
            "native frame count": (
                backend.native_frame_count == observation.result.frame_count
            ),
            "VRMA locator": backend.vrma_locator == observation.result.vrma.locator,
            "VRMA bytes": (
                backend.vrma_byte_length == observation.result.vrma.byte_length
            ),
        }
        differences = [name for name, matched in matches.items() if not matched]
        if differences:
            raise ValueError(
                "browser/backend evidence chain differs: " + ", ".join(differences)
            )
        observation_completed = datetime.fromisoformat(
            observation.completed_at.replace("Z", "+00:00")
        )
        managed_api_started = datetime.fromisoformat(
            backend.managed_api_started_at.replace("Z", "+00:00")
        )
        managed_api_stopped = datetime.fromisoformat(
            backend.managed_api_stopped_at.replace("Z", "+00:00")
        )
        recorded = datetime.fromisoformat(self.recorded_at.replace("Z", "+00:00"))
        if not (
            managed_api_started
            <= observation_completed
            <= managed_api_stopped
            <= recorded
        ):
            raise ValueError(
                "managed API lifecycle is outside the validated browser evidence window"
            )
        return self
