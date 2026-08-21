from __future__ import annotations

from fastapi import Request

from .service import ControlPlane


def control_plane(request: Request) -> ControlPlane:
    return request.app.state.control_plane
