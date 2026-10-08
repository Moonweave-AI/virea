"""Same-origin live views of the two explicitly separated VRChat clients."""

import asyncio
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from virea.vrchat.views import ViewUnavailable

from .vrchat import local_request

router = APIRouter(
    prefix="/vrchat/views", tags=["vrchat"], dependencies=[Depends(local_request)]
)


@router.get("/{role}/frame")
async def window_frame(role: Literal["observer", "ai"], request: Request):
    # Requiring a custom header prevents cross-site <img> requests from opening
    # capture sessions. This API has no permissive CORS preflight handler.
    if request.headers.get("x-virea-capture") != "1" or request.headers.get(
        "sec-fetch-site"
    ) in {"cross-site", "same-site"}:
        raise HTTPException(403, "Window capture requires a same-origin VIREA request")
    service = request.app.state.vrchat
    ai_port = service.config.send_port if service.config else 19010
    try:
        target, frame = await asyncio.to_thread(
            request.app.state.vrchat_views.frame, role, ai_port
        )
    except ViewUnavailable as exc:
        raise HTTPException(409, {"code": exc.code}) from exc
    return Response(
        frame.jpeg,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store, private, max-age=0",
            "Cross-Origin-Resource-Policy": "same-origin",
            "X-Content-Type-Options": "nosniff",
            "X-Capture-Pid": str(target.pid),
            "X-Capture-Sequence": str(frame.sequence),
            "X-Capture-Age-Ms": str(
                round((time.monotonic() - frame.captured_at) * 1000)
            ),
            "X-Capture-Width": str(frame.width),
            "X-Capture-Height": str(frame.height),
        },
    )
