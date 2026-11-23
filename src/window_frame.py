"""Native sizing for a window whose colored title bar reaches the top edge."""

import ctypes as ct
from ctypes import wintypes as win


WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084
WM_NCDESTROY = 0x0082
HTTOP, HTTOPLEFT, HTTOPRIGHT = 12, 13, 14
GWL_STYLE = -16
WS_THICKFRAME = 0x00040000

SUBCLASS_PROC = ct.WINFUNCTYPE(ct.c_ssize_t, win.HWND, win.UINT, win.WPARAM, win.LPARAM,
                              ct.c_size_t, ct.c_size_t)


class WindowFrame:
    def __init__(self, hwnd: int):
        self._top_band = self._side_band = 0
        self._callback = SUBCLASS_PROC(self._dispatch)
        self._user = ct.WinDLL('user32', use_last_error=True)
        self._controls = ct.WinDLL('comctl32', use_last_error=True)

        self._user.GetWindowLongW.argtypes = (win.HWND, ct.c_int)
        self._user.GetWindowLongW.restype = win.LONG
        self._user.SetWindowLongW.argtypes = (win.HWND, ct.c_int, win.LONG)
        self._user.SetWindowLongW.restype = win.LONG
        self._user.SetWindowPos.argtypes = (win.HWND, win.HWND, ct.c_int, ct.c_int, ct.c_int, ct.c_int, win.UINT)
        self._user.SetWindowPos.restype = win.BOOL
        self._user.GetWindowRect.argtypes = (win.HWND, ct.POINTER(win.RECT))
        self._user.GetWindowRect.restype = win.BOOL
        self._user.IsZoomed.argtypes = (win.HWND,)
        self._user.IsZoomed.restype = win.BOOL
        self._controls.SetWindowSubclass.argtypes = (win.HWND, SUBCLASS_PROC, ct.c_size_t, ct.c_size_t)
        self._controls.SetWindowSubclass.restype = win.BOOL
        self._controls.RemoveWindowSubclass.argtypes = (win.HWND, SUBCLASS_PROC, ct.c_size_t)
        self._controls.RemoveWindowSubclass.restype = win.BOOL
        self._controls.DefSubclassProc.argtypes = (win.HWND, win.UINT, win.WPARAM, win.LPARAM)
        self._controls.DefSubclassProc.restype = ct.c_ssize_t

        if not self._controls.SetWindowSubclass(hwnd, self._callback, 1, 0):
            raise ct.WinError(ct.get_last_error())
        try:
            style = self._user.GetWindowLongW(hwnd, GWL_STYLE)
            ct.set_last_error(0)
            if not self._user.SetWindowLongW(hwnd, GWL_STYLE, style | WS_THICKFRAME) and ct.get_last_error():
                raise ct.WinError(ct.get_last_error())
            # Recalculate the frame without moving, sizing, or activating the window.
            frame_changed = 0x0020
            preserve_window = 0x0001 | 0x0002 | 0x0004 | 0x0010
            if not self._user.SetWindowPos(hwnd, None, 0, 0, 0, 0, frame_changed | preserve_window):
                raise ct.WinError(ct.get_last_error())
        except OSError:
            self._controls.RemoveWindowSubclass(hwnd, self._callback, 1)
            raise

    def _dispatch(self, hwnd, message, wparam, lparam, subclass_id, _data):
        forward = self._controls.DefSubclassProc
        if message == WM_NCCALCSIZE and lparam and not self._user.IsZoomed(hwnd):
            # Both forms of WM_NCCALCSIZE start with the proposed window rectangle.
            rect = ct.cast(lparam, ct.POINTER(win.RECT)).contents
            outer_left, outer_top = rect.left, rect.top
            forward(hwnd, message, wparam, lparam)
            self._top_band = max(0, rect.top - outer_top)
            self._side_band = max(0, rect.left - outer_left)
            rect.top = outer_top
            return 0
        if message == WM_NCHITTEST and self._top_band and not self._user.IsZoomed(hwnd):
            hit = self._top_hit(hwnd, lparam)
            if hit is not None:
                return hit
        if message == WM_NCDESTROY:
            self._controls.RemoveWindowSubclass(hwnd, self._callback, subclass_id)
        return forward(hwnd, message, wparam, lparam)

    def _top_hit(self, hwnd, lparam):
        bounds = win.RECT()
        if not self._user.GetWindowRect(hwnd, ct.byref(bounds)):
            return None
        x = ct.c_short(lparam & 0xffff).value
        y = ct.c_short((lparam >> 16) & 0xffff).value
        if not (bounds.top <= y < bounds.top + self._top_band and bounds.left <= x < bounds.right):
            return None
        if x < bounds.left + self._side_band:
            return HTTOPLEFT
        if x >= bounds.right - self._side_band:
            return HTTOPRIGHT
        return HTTOP
