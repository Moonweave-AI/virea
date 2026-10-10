import asyncio
import os
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from virea_api.routes.vrchat_views import router

from virea.vrchat.views import (
    CapturedFrame,
    IsolatedWindowCapture,
    ViewUnavailable,
    WindowTarget,
    WindowViews,
    select_target,
)


def crashing_capture_worker(_target, connection):
    connection.recv()
    os._exit(23)


def working_capture_worker(_target, connection):
    while connection.recv() == "frame":
        connection.send((None, CapturedFrame(b"jpeg", time.monotonic(), 1, 960, 540)))
    connection.close()


def test_native_process_exit_does_not_kill_host_and_new_capture_can_start():
    def read(capture):
        deadline = time.monotonic() + 20
        while True:
            try:
                return capture.read()
            except ViewUnavailable as exc:
                if exc.code != "waiting_for_frame" or time.monotonic() > deadline:
                    raise
                time.sleep(0.02)

    target = WindowTarget(22, 2, 220)
    failed = IsolatedWindowCapture(target, worker=crashing_capture_worker)
    with pytest.raises(ViewUnavailable, match="capture_failed"):
        read(failed)
    assert failed.closed
    recovered = IsolatedWindowCapture(target, worker=working_capture_worker)
    try:
        assert read(recovered).jpeg == b"jpeg"
        assert read(recovered).width == 960
    finally:
        recovered.close()
    assert recovered.closed


def test_roles_follow_ports_not_window_order_and_never_share_a_process():
    observer = WindowTarget(11, 1, 110)
    ai = WindowTarget(22, 2, 220)
    inventory = {19000: [ai], 9000: [observer]}
    assert select_target(inventory, "observer", 19000) == observer
    assert select_target(inventory, "ai", 19000) == ai
    for invalid in (
        {9000: [ai], 19000: [ai]},
        {9000: [observer], 19000: [ai, observer]},
    ):
        with pytest.raises(ViewUnavailable, match="ambiguous_window"):
            select_target(invalid, "ai", 19000)
    with pytest.raises(ViewUnavailable, match="window_not_found"):
        select_target({9000: [observer]}, "ai", 19000)
    with pytest.raises(ViewUnavailable, match="window_minimized"):
        select_target({19000: [WindowTarget(22, 2, 220, True)]}, "ai", 19000)


def test_capture_is_lazy_expires_and_rebinds_after_pid_reuse():
    now = [10.0]
    target = [WindowTarget(22, 2, 220)]
    created = []

    class Capture:
        def __init__(self, target):
            self.target = target
            self.closed = False
            created.append(self)

        def read(self):
            return CapturedFrame(b"jpeg", now[0], 1, 960, 540)

        def close(self):
            self.closed = True

    views = WindowViews(
        inventory=lambda: {19000: target}, factory=Capture, clock=lambda: now[0]
    )
    assert not created
    views.frame("ai", 19000)
    now[0] += 1
    views.frame("ai", 19000)
    assert len(created) == 1
    now[0] += 1
    target[0] = WindowTarget(22, 3, 220)
    views.frame("ai", 19000)
    assert len(created) == 2 and created[0].closed
    now[0] += 2.1
    views.reap_idle()
    assert not views.channels and created[1].closed
    views.frame("ai", 19000)
    asyncio.run(views.close())
    assert all(capture.closed for capture in created)
    with pytest.raises(ViewUnavailable, match="capture_closed"):
        views.frame("ai", 19000)


def test_window_disappearance_discards_frame_instead_of_serving_old_view():
    now = [0.0]
    inventory = {19000: [WindowTarget(22, 2, 220)]}
    capture = SimpleNamespace(
        target=inventory[19000][0], read=lambda: b"frame", close=lambda: None
    )
    views = WindowViews(
        inventory=lambda: inventory, factory=lambda _: capture, clock=lambda: now[0]
    )
    views.frame("ai", 19000)
    inventory.clear()
    now[0] += 1
    with pytest.raises(ViewUnavailable, match="window_not_found"):
        views.frame("ai", 19000)
    assert not views.channels


def test_slow_first_frame_is_not_reaped_before_its_startup_deadline():
    now = [0.0]
    target = WindowTarget(22, 2, 220)
    capture = SimpleNamespace(target=target, pending=True, received=False, closed=False)

    def make(_):
        now[0] += 3  # A slow Windows spawn must not count as idle time.
        return capture

    def read():
        raise ViewUnavailable("waiting_for_frame")

    capture.read = read
    capture.close = lambda: setattr(capture, "closed", True)
    views = WindowViews(
        inventory=lambda: {19000: [target]}, factory=make, clock=lambda: now[0]
    )
    with pytest.raises(ViewUnavailable, match="waiting_for_frame"):
        views.frame("ai", 19000)
    now[0] += 2.1
    views.reap_idle()
    assert not capture.closed
    now[0] += 18
    views.reap_idle()
    assert capture.closed and not views.channels


def test_frame_route_rejects_cross_site_capture_and_returns_noncacheable_jpeg():
    requested = []

    def frame(role, port):
        requested.append((role, port))
        return WindowTarget(22, 2, 220), CapturedFrame(
            b"jpeg", time.monotonic(), 4, 960, 540
        )

    app = FastAPI()
    app.state.vrchat = SimpleNamespace(config=SimpleNamespace(send_port=19000))
    app.state.vrchat_views = SimpleNamespace(frame=frame)
    app.include_router(router, prefix="/api/v1")
    with TestClient(
        app, base_url="http://127.0.0.1", client=("127.0.0.1", 4321)
    ) as client:
        path = "/api/v1/vrchat/views/ai/frame"
        headers = {"X-Virea-Capture": "1"}
        assert client.get(path).status_code == 403
        assert (
            client.get(
                path, headers={**headers, "Sec-Fetch-Site": "cross-site"}
            ).status_code
            == 403
        )
        assert (
            client.get(
                path, headers={**headers, "Origin": "http://evil.example"}
            ).status_code
            == 403
        )
        assert (
            client.get(path, headers={**headers, "Host": "evil.example"}).status_code
            == 403
        )
        assert not requested
        response = client.get(path, headers=headers)
        assert response.content == b"jpeg"
        assert response.headers["content-type"] == "image/jpeg"
        assert "no-store" in response.headers["cache-control"]
        assert response.headers["x-capture-pid"] == "22"
        assert requested == [("ai", 19000)]
        assert (
            client.get(
                "/api/v1/vrchat/views/desktop/frame", headers=headers
            ).status_code
            == 422
        )


def test_unavailable_capture_returns_explicit_state():
    def unavailable(*_):
        raise ViewUnavailable("window_minimized")

    app = FastAPI()
    app.state.vrchat = SimpleNamespace(config=None)
    app.state.vrchat_views = SimpleNamespace(frame=unavailable)
    app.include_router(router, prefix="/api/v1")
    with TestClient(
        app, base_url="http://127.0.0.1", client=("127.0.0.1", 4321)
    ) as client:
        response = client.get(
            "/api/v1/vrchat/views/observer/frame", headers={"X-Virea-Capture": "1"}
        )
        assert response.status_code == 409
        assert response.json() == {"detail": {"code": "window_minimized"}}


def test_capture_failure_is_released_and_a_later_request_can_recover():
    target = WindowTarget(22, 2, 220)
    closed = []
    created = []

    def make_capture(_):
        fails = not created

        def read():
            if fails:
                raise ViewUnavailable("capture_failed")
            return b"recovered"

        capture = SimpleNamespace(
            target=target, read=read, close=lambda: closed.append(True)
        )
        created.append(capture)
        return capture

    views = WindowViews(inventory=lambda: {19000: [target]}, factory=make_capture)
    with pytest.raises(ViewUnavailable, match="capture_failed"):
        views.frame("ai", 19000)
    assert closed == [True]
    assert views.frame("ai", 19000)[1] == b"recovered"
    asyncio.run(views.close())
    assert len(closed) == 2
