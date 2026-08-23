from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from virea_contracts.vrm import VrmMotionResult

from ..dependencies import control_plane
from ..service import ControlPlane

router = APIRouter(prefix="/results", tags=["results"])


@router.get("/{result_id}", response_model=VrmMotionResult)
def result(
    result_id: str, control: ControlPlane = Depends(control_plane)
) -> VrmMotionResult:
    row = control.store.get_result(result_id)
    if row is None:
        raise HTTPException(status_code=404, detail="result not found")
    return VrmMotionResult.model_validate_json(row["payload_json"])


@router.get("/{result_id}/source-skeleton")
def source_skeleton(
    result_id: str,
    control: ControlPlane = Depends(control_plane),
) -> dict:
    """Return model-space skeleton animation before VRM retargeting."""

    try:
        return control.source_skeleton_preview(result_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="result not found") from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SOURCE_SKELETON_UNAVAILABLE",
                "message": str(exc),
            },
        ) from exc


@router.get("/{result_id}/artifacts/{name}")
def artifact(
    result_id: str,
    name: str,
    control: ControlPlane = Depends(control_plane),
) -> FileResponse:
    row = control.store.get_result(result_id)
    if row is None:
        raise HTTPException(status_code=404, detail="result not found")
    payload = VrmMotionResult.model_validate_json(row["payload_json"])
    locators: dict[str, tuple[str, str]] = {
        Path(export.locator).name: (export.locator, export.media_type)
        for export in payload.exports
    }
    for locator in payload.tracks.values():
        if locator is not None:
            locators[Path(locator).name] = (locator, _media_type(locator))
    if name not in locators:
        raise HTTPException(status_code=404, detail="artifact not found")
    locator, media_type = locators[name]
    path = control.paths.resolve_locator(locator)
    result_root = control.paths.result_directory(result_id).resolve(strict=False)
    try:
        path.resolve(strict=False).relative_to(result_root)
    except ValueError as exc:
        raise HTTPException(
            status_code=403, detail="artifact locator is outside result"
        ) from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="artifact file is missing")
    return FileResponse(path, media_type=media_type, filename=path.name)


def _media_type(locator: str) -> str:
    return {
        ".json": "application/json",
        ".npz": "application/x-npz",
        ".npy": "application/x-npy",
        ".vrma": "model/gltf-binary",
    }.get(Path(locator).suffix.lower(), "application/octet-stream")
