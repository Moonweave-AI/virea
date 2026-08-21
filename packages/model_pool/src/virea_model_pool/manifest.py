from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from virea_contracts.base import ContractModel
from virea_contracts.model import ModelSupportStatus, ProductionE2EAcceptance
from virea_contracts.runtime import RuntimeSpec


class UpstreamSpec(ContractModel):
    repository: str
    revision: str
    release: str | None = None


class ModelSection(ContractModel):
    id: str
    display_name: str
    plugin_version: str
    upstream: UpstreamSpec
    tasks: tuple[str, ...]
    adapter_family: str
    status: ModelSupportStatus

    @field_validator("tasks")
    @classmethod
    def unique_tasks(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(value) != len(set(value)):
            raise ValueError("tasks must be non-empty and unique")
        return value


class OutputSpec(ContractModel):
    envelope: Literal["virea.model_result.v1.0.0"] = "virea.model_result.v1.0.0"
    representation_id: str
    skeleton_id: str
    fps: float | None = None
    coordinate_system: str
    units: str
    root_translation_semantics: str
    root_rotation_semantics: str
    face_representation_ids: tuple[str, ...] = ()


class ArchiveExtractionSpec(ContractModel):
    path: str
    format: Literal["zip", "tar"]
    destination: str = "."
    strip_components: int = Field(default=0, ge=0, le=16)
    remove_archive: bool = True

    @field_validator("path", "destination")
    @classmethod
    def relative_archive_path(cls, value: str) -> str:
        parts = urlsplit(value)
        normalized = value.replace("\\", "/")
        path_parts = tuple(
            part for part in normalized.split("/") if part not in {"", "."}
        )
        if (
            not value.strip()
            or parts.scheme
            or normalized.startswith("/")
            or ".." in path_parts
        ):
            raise ValueError("archive paths must be safe relative paths")
        return value


class ArtifactSource(ContractModel):
    id: str
    kind: Literal["huggingface", "https", "local", "manual"]
    repository: str | None = None
    revision: str | None = None
    url: str | None = None
    local_path: str | None = None
    allow_patterns: tuple[str, ...] = ()
    expected_files: tuple[str, ...] = ()
    expected_total_bytes: int | None = None
    unpack: tuple[ArchiveExtractionSpec, ...] = ()

    @model_validator(mode="after")
    def source_is_complete(self) -> ArtifactSource:
        if self.kind == "huggingface" and not (self.repository and self.revision):
            raise ValueError("Hugging Face sources require repository and revision")
        if self.kind == "https":
            parts = urlsplit(self.url or "")
            if parts.scheme.lower() != "https" or not parts.hostname:
                raise ValueError("HTTPS sources require an absolute https URL")
            if parts.username is not None or parts.password is not None:
                raise ValueError("HTTPS source URLs must not contain credentials")
        if self.kind == "local" and not self.local_path:
            raise ValueError("local sources require local_path")
        unpack_paths = tuple(item.path for item in self.unpack)
        if len(unpack_paths) != len(set(unpack_paths)):
            raise ValueError("archive extraction paths must be unique")
        return self


class LicenseFacts(ContractModel):
    code: str | None = None
    weights: str | None = None
    dataset_lineage: tuple[str, ...] = ()
    body_model: tuple[str, ...] = ()
    commercial_allowed: bool | None = None
    redistribution_allowed: bool | None = None
    requires_acceptance: bool = False
    source_urls: tuple[str, ...] = ()


class TestFixtureSpec(ContractModel):
    request_fixture: str
    min_frames: int = 1
    expected_representation_id: str
    timeout_seconds: float = 120.0


class ModelPluginManifest(ContractModel):
    schema_version: Literal["virea.model_plugin.v1.0.0"] = "virea.model_plugin.v1.0.0"
    model: ModelSection
    inputs: tuple[dict[str, Any], ...]
    output: OutputSpec
    runtime_variants: tuple[RuntimeSpec, ...] = ()
    artifacts: tuple[ArtifactSource, ...] = ()
    licenses: LicenseFacts
    resources: dict[str, Any] = Field(default_factory=dict)
    production_acceptance: ProductionE2EAcceptance | None = None
    test_only: bool = False
    test_fixture: TestFixtureSpec | None = None
    notes: tuple[str, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_fixture_key(cls, value: Any) -> Any:
        """Read v1 manifests without preserving their old release semantics."""

        if not isinstance(value, dict) or "smoke_test" not in value:
            return value
        if "test_fixture" in value:
            raise ValueError(
                "manifest cannot declare both legacy and current test fixture keys"
            )
        migrated = dict(value)
        migrated["test_fixture"] = migrated.pop("smoke_test")
        return migrated

    @model_validator(mode="after")
    def validate_support_and_acceptance_claims(self) -> ModelPluginManifest:
        production_status = self.model.status in {
            ModelSupportStatus.INTEGRATED_EXPERIMENTAL,
            ModelSupportStatus.SUPPORTED,
        }
        if self.test_fixture is not None and not self.test_only:
            raise ValueError("test fixtures must be explicitly marked test-only")
        if self.test_only:
            if production_status:
                raise ValueError("test-only models cannot claim production support")
            if self.production_acceptance is not None:
                raise ValueError(
                    "test-only models cannot declare production acceptance"
                )
        if production_status and (
            not self.runtime_variants or self.production_acceptance is None
        ):
            raise ValueError(
                "integrated models require a runtime and production E2E acceptance"
            )
        if self.production_acceptance is not None:
            unversioned_runtimes = [
                runtime.id
                for runtime in self.runtime_variants
                if not runtime.project_package
                or not runtime.project_version
                or not runtime.runtime_core_epoch
            ]
            if unversioned_runtimes:
                raise ValueError(
                    "production runtime variants require project_package, "
                    "project_version, and runtime_core_epoch: "
                    + ", ".join(unversioned_runtimes)
                )
            request = self.production_acceptance.request
            expected = self.production_acceptance.expected
            if request.model_id != self.model.id:
                raise ValueError(
                    "production acceptance request model must match model id"
                )
            if request.task not in self.model.tasks:
                raise ValueError("production acceptance task must be declared by model")
            if expected.representation_id != self.output.representation_id:
                raise ValueError(
                    "production acceptance representation must match model output"
                )
            if expected.skeleton_id != self.output.skeleton_id:
                raise ValueError(
                    "production acceptance skeleton must match model output"
                )
        return self
