from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from virea_core.atomic import atomic_write_bytes, atomic_write_json
from virea_core.ids import new_ulid
from virea_vrm import inspect_avatar

from ..dependencies import control_plane
from ..service import ControlPlane

router = APIRouter(prefix="/avatars", tags=["avatars"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_avatar(
    request: Request,
    filename: str = "avatar.vrm",
    control: ControlPlane = Depends(control_plane),
) -> dict:
    if Path(filename).suffix.lower() not in {".vrm", ".glb"}:
        raise HTTPException(
            status_code=422, detail="avatar filename must end in .vrm or .glb"
        )
    payload = await request.body()
    if not payload or len(payload) > 256 * 1024 * 1024:
        raise HTTPException(
            status_code=413, detail="avatar must be between 1 byte and 256 MiB"
        )
    avatar_id = new_ulid()
    extension = Path(filename).suffix.lower()
    avatar_path = control.paths.avatars / "blobs" / f"{avatar_id}{extension}"
    atomic_write_bytes(avatar_path, payload)
    try:
        descriptor = inspect_avatar(avatar_path)
    except Exception as exc:
        avatar_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"invalid VRM/GLB: {exc}") from exc
    record = {
        "schema_version": "virea.avatar.v1.0.0",
        "id": avatar_id,
        "display_name": Path(filename).name,
        "profile_id": descriptor["profile"],
        "locator": control.paths.relative_locator(avatar_path),
        "descriptor": descriptor,
    }
    descriptor_path = control.paths.avatars / "descriptors" / f"{avatar_id}.json"
    atomic_write_json(descriptor_path, record)
    with control.store.transaction() as connection:
        connection.execute(
            "INSERT INTO avatars(id, profile_id, locator, payload_json) VALUES (?, ?, ?, ?)",
            (
                avatar_id,
                record["profile_id"],
                record["locator"],
                json.dumps(record, ensure_ascii=False, separators=(",", ":")),
            ),
        )
    return record


@router.get("")
def avatars(control: ControlPlane = Depends(control_plane)) -> list[dict]:
    with control.store.connect() as connection:
        rows = connection.execute(
            "SELECT payload_json FROM avatars ORDER BY id"
        ).fetchall()
        return [json.loads(row[0]) for row in rows]


@router.get("/{avatar_id}")
def avatar(avatar_id: str, control: ControlPlane = Depends(control_plane)) -> dict:
    with control.store.connect() as connection:
        row = connection.execute(
            "SELECT payload_json FROM avatars WHERE id = ?", (avatar_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="avatar not found")
    return json.loads(row[0])
