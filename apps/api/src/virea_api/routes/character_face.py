from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from virea_motion_ir import load_motion_ir

from virea.character.face import vrm_face_track

from ..dependencies import control_plane
from ..service import ControlPlane

router = APIRouter(prefix="/characters/results", tags=["characters"])


@router.get("/{result_id}/face")
def character_face(
    result_id: str, control: ControlPlane = Depends(control_plane)
) -> dict:
    row = control.store.get_result(result_id)
    if row is None:
        raise HTTPException(404, "result not found")
    result = json.loads(row["payload_json"])
    locator = result["tracks"].get("motion_ir")
    if not locator:
        raise HTTPException(409, "result has no native Motion IR")
    path = control.paths.resolve_locator(locator).resolve()
    if not path.is_relative_to(control.paths.result_directory(result_id).resolve()):
        raise HTTPException(403, "Motion IR outside result directory")
    motion = load_motion_ir(path)
    for track in motion.face_tracks:
        if track.get("representation_id") == "arkit.blendshape51.v1":
            return vrm_face_track(track["values"], motion.fps)
    raise HTTPException(409, "result has no SentiAvatar face track")
