"""Client-image geometry shared by capture and direct viewport controls."""


def client_crop_bounds(frame_size, client, candidates):
    """Match WGC's physical-pixel bounds, excluding title bar and resize border.

    During resize, an old frame and new window bounds can disagree. Reject that
    frame instead of stretching it or sending clicks with obsolete geometry.
    """
    width, height = frame_size
    for left, top, right, bottom in candidates:
        if (right - left, bottom - top) != (width, height):
            continue
        x0, y0, x1, y1 = (
            client[0] - left,
            client[1] - top,
            client[2] - left,
            client[3] - top,
        )
        if 0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height:
            return x0, y0, x1, y1
    raise ValueError("waiting for client geometry to match the frame")


def window_client_crop(hwnd, width, height):
    import ctypes
    from ctypes import wintypes

    user = ctypes.WinDLL("user32", use_last_error=True)
    dwm = ctypes.WinDLL("dwmapi")
    user.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    dwm.DwmGetWindowAttribute.argtypes = [
        wintypes.HWND,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    previous = user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    try:
        client, window, extended = wintypes.RECT(), wintypes.RECT(), wintypes.RECT()
        point = wintypes.POINT(0, 0)
        if not (
            user.GetClientRect(hwnd, ctypes.byref(client))
            and user.ClientToScreen(hwnd, ctypes.byref(point))
            and user.GetWindowRect(hwnd, ctypes.byref(window))
        ):
            raise ValueError("window geometry unavailable")
        bounds = [(window.left, window.top, window.right, window.bottom)]
        if (
            dwm.DwmGetWindowAttribute(
                hwnd, 9, ctypes.byref(extended), ctypes.sizeof(extended)
            )
            == 0
        ):
            bounds.insert(
                0, (extended.left, extended.top, extended.right, extended.bottom)
            )
        absolute_client = (
            point.x,
            point.y,
            point.x + client.right,
            point.y + client.bottom,
        )
        # Some capture backends already return the client area.
        bounds.append(absolute_client)
        return client_crop_bounds((width, height), absolute_client, bounds)
    finally:
        if previous:
            user.SetThreadDpiAwarenessContext(previous)
