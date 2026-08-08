from __future__ import annotations

from functools import lru_cache
import hashlib
import logging
import mimetypes
import os
from pathlib import Path
import re
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from virea.data.registry import DatasetRegistry
from virea.data.annotations import resolve_cached_sidecar, sidecar_cache_health
from virea.data.profiles import profile_for_sample
from virea.paths import AVAILABLE_DATA_SOURCES, ProjectPaths, repo_root
from virea.pipelines.batch import BatchPipeline, default_worker_count
from virea.pipelines.catalog import CatalogPipeline
from virea.pipelines.preview_reader import PreviewReader
from virea.pipelines.processed_preview import ProcessedPreviewPipeline
from virea.pipelines.processing import ProcessingPipeline
from virea.pipelines.raw_preview import RawPreviewPipeline
from virea.server.binary_codec import pack_positions_binary


LOGGER = logging.getLogger(__name__)
MAX_EXPLICIT_PREVIEW_FRAMES = 1_000_000


class ProcessRequest(BaseModel):
    data_source: str | None = None
    dataset: str
    sample_id: str
    max_frames: int | None = None
    persist: bool = True
    skip_existing: bool = False


class BatchRequest(BaseModel):
    data_source: str | None = None
    datasets: list[str] = Field(default_factory=list)
    query: str = ""
    limit_per_dataset: int = 0
    max_frames: int | None = None
    workers: int = 0
    continue_on_error: bool = True
    skip_existing: bool = True
    force: bool = False


def _default_data_source() -> str:
    return ProjectPaths().data_source


def _resolve_data_source(data_source: str | None) -> str:
    return (data_source or _default_data_source()).strip().lower()


def _mount_static_if_exists(app: FastAPI, route: str, directory: str | Path) -> None:
    path = Path(directory).expanduser()
    if not path.is_absolute():
        path = repo_root() / path
    if path.exists():
        app.mount(route, StaticFiles(directory=str(path)), name=route.strip("/").replace("/", "_"))


def _mount_static_first_existing(app: FastAPI, route: str, candidates: list[str | Path]) -> bool:
    for directory in candidates:
        path = Path(directory).expanduser()
        if not path.is_absolute():
            path = repo_root() / path
        if path.exists():
            app.mount(route, StaticFiles(directory=str(path)), name=route.strip("/").replace("/", "_"))
            return True
    return False


def _mount_static_from_env(app: FastAPI, route: str, env_name: str, project_relative_fallbacks: list[str]) -> bool:
    candidates: list[str | Path] = []
    env_value = os.getenv(env_name)
    if env_value:
        candidates.append(env_value)
    candidates.extend(project_relative_fallbacks)
    return _mount_static_first_existing(app, route, candidates)


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _require_write_api() -> None:
    if not _truthy_env("VIREA_ENABLE_WRITE_API"):
        raise HTTPException(
            status_code=403,
            detail="write API disabled; set VIREA_ENABLE_WRITE_API=1 for an explicitly local trusted session",
        )


def _public_http_error(exc: Exception, status_code: int = 400) -> HTTPException:
    LOGGER.warning("VIREA API request failed: %s", type(exc).__name__, exc_info=exc)
    if isinstance(exc, FileNotFoundError):
        detail = "requested sample or artifact was not found"
    elif isinstance(exc, KeyError):
        detail = "unknown dataset or sample identifier"
    elif isinstance(exc, PermissionError) and "VIREA_ALLOW_TRUSTED_RAW_PICKLE=1" in str(exc):
        detail = (
            "legacy GRAB/SuSu NumPy object data is disabled because it can execute code; "
            "for a locally verified dataset only, set VIREA_ALLOW_TRUSTED_RAW_PICKLE=1 "
            "and restart the service"
        )
    else:
        detail = f"request failed ({type(exc).__name__})"
    return HTTPException(status_code=status_code, detail=detail)


def _public_path(value: str | Path, registry: DatasetRegistry) -> str:
    path = Path(value)
    if not path.is_absolute():
        return path.as_posix()
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    roots = (
        ("raw", registry.paths.raw_root.resolve()),
        ("processed", registry.paths.processed_root.resolve()),
    )
    for label, root in roots:
        try:
            return f"{label}/{resolved.relative_to(root).as_posix()}"
        except ValueError:
            continue
    return f"<redacted-local-path>/{resolved.name}"


def _public_payload(value, registry: DatasetRegistry):
    """Remove machine-local absolute paths from every HTTP JSON response."""
    if isinstance(value, dict):
        return {str(key): _public_payload(item, registry) for key, item in value.items()}
    if isinstance(value, list):
        return [_public_payload(item, registry) for item in value]
    if isinstance(value, tuple):
        return [_public_payload(item, registry) for item in value]
    if isinstance(value, Path):
        return _public_path(value, registry)
    if isinstance(value, str) and Path(value).is_absolute():
        return _public_path(value, registry)
    return value


def _public_sample_payload(sample, registry: DatasetRegistry) -> dict:
    """Return a catalog sample plus the profile FPS used only for preview sizing."""
    payload = sample.to_dict()
    explicit_profile = str(sample.metadata.get("dataset_profile") or "") or None
    try:
        profile = profile_for_sample(sample.dataset, sample.sample_id, explicit_profile)
    except KeyError:
        profile = None
    if profile is not None:
        payload["preview_fps_fallback"] = float(profile.fps_fallback)
        payload["preview_fps_provenance"] = f"dataset_profile:{profile.key}"
    return _public_payload(payload, registry)


def _public_data_sources() -> dict[str, dict]:
    output: dict[str, dict] = {}
    for key, item in ProjectPaths.available_sources().items():
        output[key] = {
            "label": item.get("label", key),
            "description": item.get("description", ""),
            "exists": bool(item.get("exists")),
            "location": "configured" if item.get("exists") else "missing",
        }
    return output


def _sidecar_media_type(path: Path) -> str:
    explicit = {
        ".json": "application/json",
        ".npy": "application/x-npy",
        ".npz": "application/x-npz",
        ".wav": "audio/wav",
    }
    return explicit.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_sidecar_file(digest: str, data_source: str | None = None) -> Path:
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise FileNotFoundError("invalid sidecar content identifier")
    sources = (_resolve_data_source(data_source),) if data_source else AVAILABLE_DATA_SOURCES
    for source in sources:
        root = (_registry_for(source).paths.processed_root / "sidecars").resolve()
        if not root.is_dir():
            continue
        for candidate in root.iterdir():
            if not candidate.is_file() or not (candidate.name == digest or candidate.name.startswith(f"{digest}.")):
                continue
            resolved = candidate.resolve()
            if not resolved.is_relative_to(root):
                continue
            if _sha256_file(resolved) == digest:
                return resolved
    cached = resolve_cached_sidecar(digest)
    if cached is not None:
        return cached
    raise FileNotFoundError("sidecar content was not found")


@lru_cache(maxsize=4)
def _registry_for(data_source: str) -> DatasetRegistry:
    if data_source not in AVAILABLE_DATA_SOURCES:
        raise KeyError(f"unsupported data source: {data_source}")
    return DatasetRegistry.default(data_source=data_source)


def _preview_query_params(
    data_source: str | None,
    dataset: str,
    sample_id: str,
    max_frames: int | None,
    from_artifacts: bool,
) -> tuple[DatasetRegistry, str, str, str, int | None, bool]:
    resolved = _resolve_data_source(data_source)
    registry = _registry_for(resolved)
    effective_max_frames = max_frames if max_frames is not None else registry.paths.preview_max_frames
    return registry, resolved, dataset, sample_id, effective_max_frames, from_artifacts


def create_app() -> FastAPI:
    app = FastAPI(title="VIREA Preview Runtime", version="0.2.0")
    trusted_hosts = [
        item.strip()
        for item in os.getenv("VIREA_TRUSTED_HOSTS", "127.0.0.1,localhost,testserver").split(",")
        if item.strip()
    ]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_origin_regex=os.getenv(
            "VIREA_CORS_ORIGIN_REGEX",
            r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$",
        ),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    ui_root = repo_root() / "apps" / "viewer-web"
    if ui_root.exists():
        app.mount("/ui", StaticFiles(directory=str(ui_root)), name="ui")
    three_available = _mount_static_from_env(
        app, "/vendor/three", "VIREA_THREE_ROOT", ["node_modules/three", "vendor/three"]
    )
    vrm_available = _mount_static_from_env(
        app,
        "/vendor/three-vrm",
        "VIREA_THREE_VRM_ROOT",
        ["node_modules/@pixiv/three-vrm", "vendor/three-vrm"],
    )

    @app.get("/")
    def root() -> FileResponse:
        index = ui_root / "index.html"
        if not index.exists():
            raise HTTPException(status_code=404, detail="viewer UI is not available")
        return FileResponse(index)

    @app.get("/api/health")
    def health() -> dict:
        current_source = ProjectPaths().data_source
        registry = _registry_for(current_source)
        return {
            "ok": bool(ui_root.exists()),
            "default_data_source": registry.paths.data_source,
            "available_data_sources": _public_data_sources(),
            "dependencies": {
                "viewer_ui": ui_root.exists(),
                "three": three_available,
                "three_vrm": vrm_available,
            },
            "sidecar_cache": sidecar_cache_health(),
            "write_api_enabled": _truthy_env("VIREA_ENABLE_WRITE_API"),
            "trusted_raw_pickle_enabled": _truthy_env("VIREA_ALLOW_TRUSTED_RAW_PICKLE"),
            "datasets": registry.keys(),
        }

    @app.get("/api/catalog")
    def catalog(data_source: str | None = None) -> dict:
        registry = _registry_for(_resolve_data_source(data_source))
        return _public_payload(CatalogPipeline(registry).summary(), registry)

    @app.get("/api/artifacts/sidecars/{digest}")
    def artifact_sidecar(digest: str, data_source: str | None = None) -> FileResponse:
        """Read a content-addressed, integrity-checked sidecar from a processed root."""
        try:
            path = _resolve_sidecar_file(digest.lower(), data_source=data_source)
        except (FileNotFoundError, KeyError, ValueError) as exc:
            raise _public_http_error(exc, 404) from exc
        return FileResponse(
            path,
            media_type=_sidecar_media_type(path),
            headers={
                "Cache-Control": "private, max-age=31536000, immutable",
                "Content-Security-Policy": "default-src 'none'",
                "ETag": f'"sha256-{digest.lower()}"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.get("/api/datasets")
    def datasets(data_source: str | None = None) -> dict:
        registry = _registry_for(_resolve_data_source(data_source))
        return {
            "data_source": registry.paths.data_source,
            "processing_version": registry.paths.processing_version,
            "datasets": [record.to_dict() for record in registry.iter_records()],
        }

    @app.get("/api/samples")
    def samples(
        data_source: str | None = None,
        dataset: str = Query(...),
        q: str = "",
        limit: int = Query(50, ge=1, le=500),
    ) -> dict:
        try:
            resolved_source = _resolve_data_source(data_source)
            registry = _registry_for(resolved_source)
            items = registry.adapter(dataset).discover(limit=limit, query=q)
        except KeyError as exc:
            raise _public_http_error(exc, 404) from exc
        return {
            "data_source": resolved_source,
            "dataset": dataset,
            "items": [_public_sample_payload(item, registry) for item in items],
        }

    @app.get("/api/preview/source")
    def preview_source(
        data_source: str | None = None,
        dataset: str = Query(...),
        sample_id: str = Query(...),
        max_frames: int | None = Query(default=None, ge=1, le=MAX_EXPLICIT_PREVIEW_FRAMES),
        from_artifacts: bool = Query(default=True, alias="from_artifacts"),
    ) -> dict:
        try:
            registry, _source, _dataset, _sample, max_frames, _artifacts = _preview_query_params(
                data_source, dataset, sample_id, max_frames, from_artifacts
            )
            reader = PreviewReader(registry)
            if from_artifacts:
                try:
                    payload = reader.read_source_preview(dataset, sample_id, max_frames=max_frames).to_dict()
                    return _public_payload(payload, registry)
                except FileNotFoundError:
                    pass
            payload = RawPreviewPipeline(registry).preview(dataset, sample_id, max_frames=max_frames).to_dict()
            return _public_payload(payload, registry)
        except FileNotFoundError as exc:
            raise _public_http_error(exc, 404) from exc
        except Exception as exc:
            raise _public_http_error(exc) from exc

    @app.get("/api/preview/processed")
    def preview_processed(
        data_source: str | None = None,
        dataset: str = Query(...),
        sample_id: str = Query(...),
        max_frames: int | None = Query(default=None, ge=1, le=MAX_EXPLICIT_PREVIEW_FRAMES),
        from_artifacts: bool = Query(default=True, alias="from_artifacts"),
    ) -> dict:
        try:
            registry, _source, _dataset, _sample, max_frames, _artifacts = _preview_query_params(
                data_source, dataset, sample_id, max_frames, from_artifacts
            )
            reader = PreviewReader(registry)
            if from_artifacts:
                try:
                    payload = reader.read_processed_preview(dataset, sample_id, max_frames=max_frames).to_dict()
                    return _public_payload(payload, registry)
                except FileNotFoundError:
                    pass
            payload = ProcessedPreviewPipeline(registry).preview(
                dataset, sample_id, max_frames=max_frames, persist=False
            ).to_dict()
            return _public_payload(payload, registry)
        except FileNotFoundError as exc:
            raise _public_http_error(exc, 404) from exc
        except Exception as exc:
            raise _public_http_error(exc) from exc

    @app.get("/api/preview/motion")
    def preview_motion(
        data_source: str | None = None,
        dataset: str = Query(...),
        sample_id: str = Query(...),
        max_frames: int | None = Query(default=None, ge=1, le=MAX_EXPLICIT_PREVIEW_FRAMES),
        from_artifacts: bool = Query(default=True, alias="from_artifacts"),
    ) -> dict:
        try:
            registry, _source, _dataset, _sample, max_frames, _artifacts = _preview_query_params(
                data_source, dataset, sample_id, max_frames, from_artifacts
            )
            reader = PreviewReader(registry)
            if from_artifacts:
                try:
                    return reader.read_motion_payload(dataset, sample_id, max_frames=max_frames)
                except FileNotFoundError:
                    pass
            payload = ProcessedPreviewPipeline(registry).preview(
                dataset, sample_id, max_frames=max_frames, persist=False
            )
            if payload.motion is None:
                raise HTTPException(status_code=404, detail="motion payload missing")
            return payload.motion
        except HTTPException:
            raise
        except FileNotFoundError as exc:
            raise _public_http_error(exc, 404) from exc
        except Exception as exc:
            raise _public_http_error(exc) from exc

    @app.get("/api/preview/quality")
    def preview_quality_endpoint(
        data_source: str | None = None,
        dataset: str = Query(...),
        sample_id: str = Query(...),
    ) -> dict:
        try:
            registry = _registry_for(_resolve_data_source(data_source))
            return _public_payload(PreviewReader(registry).read_quality_report(dataset, sample_id), registry)
        except FileNotFoundError as exc:
            raise _public_http_error(exc, 404) from exc

    def _binary_positions(stage: Literal["source", "processed"], **kwargs) -> Response:
        registry, dataset, sample_id, max_frames, from_artifacts = (
            kwargs["registry"],
            kwargs["dataset"],
            kwargs["sample_id"],
            kwargs["max_frames"],
            kwargs["from_artifacts"],
        )
        reader = PreviewReader(registry)
        if stage == "source":
            if from_artifacts:
                try:
                    payload = reader.read_source_preview(dataset, sample_id, max_frames=max_frames)
                except FileNotFoundError:
                    payload = RawPreviewPipeline(registry).preview(dataset, sample_id, max_frames=max_frames)
            else:
                payload = RawPreviewPipeline(registry).preview(dataset, sample_id, max_frames=max_frames)
        else:
            if from_artifacts:
                try:
                    payload = reader.read_processed_preview(dataset, sample_id, max_frames=max_frames)
                except FileNotFoundError:
                    payload = ProcessedPreviewPipeline(registry).preview(
                        dataset, sample_id, max_frames=max_frames, persist=False
                    )
            else:
                payload = ProcessedPreviewPipeline(registry).preview(
                    dataset, sample_id, max_frames=max_frames, persist=False
                )
        positions = payload.positions
        frame_count = int(positions.shape[0])
        joint_count = int(positions.shape[1])
        body = pack_positions_binary(positions, frame_count, joint_count)
        return Response(content=body, media_type="application/octet-stream")

    @app.get("/api/preview/source/binary")
    def preview_source_binary(
        data_source: str | None = None,
        dataset: str = Query(...),
        sample_id: str = Query(...),
        max_frames: int | None = Query(default=None, ge=1, le=MAX_EXPLICIT_PREVIEW_FRAMES),
        from_artifacts: bool = Query(default=True, alias="from_artifacts"),
    ) -> Response:
        try:
            registry, _source, _dataset, _sample, max_frames, _artifacts = _preview_query_params(
                data_source, dataset, sample_id, max_frames, from_artifacts
            )
            return _binary_positions(
                "source",
                registry=registry,
                dataset=dataset,
                sample_id=sample_id,
                max_frames=max_frames,
                from_artifacts=from_artifacts,
            )
        except Exception as exc:
            raise _public_http_error(exc) from exc

    @app.get("/api/preview/processed/binary")
    def preview_processed_binary(
        data_source: str | None = None,
        dataset: str = Query(...),
        sample_id: str = Query(...),
        max_frames: int | None = Query(default=None, ge=1, le=MAX_EXPLICIT_PREVIEW_FRAMES),
        from_artifacts: bool = Query(default=True, alias="from_artifacts"),
    ) -> Response:
        try:
            registry, _source, _dataset, _sample, max_frames, _artifacts = _preview_query_params(
                data_source, dataset, sample_id, max_frames, from_artifacts
            )
            return _binary_positions(
                "processed",
                registry=registry,
                dataset=dataset,
                sample_id=sample_id,
                max_frames=max_frames,
                from_artifacts=from_artifacts,
            )
        except Exception as exc:
            raise _public_http_error(exc) from exc

    @app.get("/api/preview/on-demand")
    def preview_on_demand(
        data_source: str | None = None,
        dataset: str = Query(...),
        sample_id: str = Query(...),
        stage: Literal["raw", "processed"] = "processed",
        max_frames: int | None = Query(default=None, ge=1, le=MAX_EXPLICIT_PREVIEW_FRAMES),
        persist: bool = False,
    ) -> dict:
        """Compute preview in memory without requiring persisted artifacts."""
        try:
            registry = _registry_for(_resolve_data_source(data_source))
            max_frames = max_frames if max_frames is not None else registry.paths.preview_max_frames
            if stage == "raw":
                payload = RawPreviewPipeline(registry).preview(dataset, sample_id, max_frames=max_frames).to_dict()
                return _public_payload(payload, registry)
            if persist:
                _require_write_api()
            payload = ProcessedPreviewPipeline(registry).preview(
                dataset, sample_id, max_frames=max_frames, persist=persist
            ).to_dict()
            return _public_payload(payload, registry)
        except HTTPException:
            raise
        except Exception as exc:
            raise _public_http_error(exc) from exc

    @app.get("/api/preview")
    def preview_legacy(
        data_source: str | None = None,
        dataset: str = Query(...),
        sample_id: str = Query(...),
        stage: Literal["raw", "processed"] = "processed",
        max_frames: int | None = Query(default=None, ge=1, le=MAX_EXPLICIT_PREVIEW_FRAMES),
        persist: bool = False,
        from_artifacts: bool = Query(default=False, alias="from_artifacts"),
    ) -> dict:
        """Deprecated alias: prefer /api/preview/source or /api/preview/processed."""
        if stage == "raw":
            return preview_source(
                data_source=data_source,
                dataset=dataset,
                sample_id=sample_id,
                max_frames=max_frames,
                from_artifacts=from_artifacts or persist,
            )
        if persist:
            return preview_on_demand(
                data_source=data_source,
                dataset=dataset,
                sample_id=sample_id,
                stage="processed",
                max_frames=max_frames,
                persist=True,
            )
        return preview_processed(
            data_source=data_source,
            dataset=dataset,
            sample_id=sample_id,
            max_frames=max_frames,
            from_artifacts=from_artifacts,
        )

    @app.post("/api/process")
    def process(request: ProcessRequest) -> dict:
        try:
            _require_write_api()
            registry = _registry_for(_resolve_data_source(request.data_source))
            output = ProcessingPipeline(registry).run(
                request.dataset,
                request.sample_id,
                max_frames=request.max_frames,
                persist=request.persist,
                skip_existing=request.skip_existing,
            )
            builder_payload = ProcessedPreviewPipeline(registry)._builder.processed_payload(
                output.clip,
                output.canonical,
                source=output.source,
                files=output.paths,
            )
            return _public_payload(builder_payload.to_dict(), registry)
        except HTTPException:
            raise
        except Exception as exc:
            raise _public_http_error(exc) from exc

    @app.post("/api/batch")
    def batch_process(request: BatchRequest) -> dict:
        try:
            _require_write_api()
            registry = _registry_for(_resolve_data_source(request.data_source))
            pipeline = BatchPipeline(registry)
            limit = request.limit_per_dataset if request.limit_per_dataset > 0 else None
            tasks = pipeline.collect_tasks(
                datasets=request.datasets or None,
                query=request.query,
                limit_per_dataset=limit or 1_000_000_000,
            )
            workers = request.workers if request.workers > 0 else default_worker_count()
            report = pipeline.run(
                tasks,
                workers=workers,
                max_frames=request.max_frames,
                continue_on_error=request.continue_on_error,
                skip_existing=request.skip_existing,
                force=request.force,
            )
            return _public_payload(report.to_dict(), registry)
        except HTTPException:
            raise
        except Exception as exc:
            raise _public_http_error(exc) from exc

    return app


app = create_app()
