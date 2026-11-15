# DualCPY Split - viewport windows
# Copyright (C) 2026 the_swest and DualCPY Split contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

# src/viewport.py
"""
Each scrcpy window lives inside a "viewport" window that we own.

The scrcpy window always shows the FULL device screen; the viewport only
shows part of it (the crop). Cropping is therefore instant - no stream
restart - and can match exactly what a game draws (e.g. a 4:3 game with
integer-scaling bars on every side).

Combined mode: viewports are children of the container window.
Split mode:    viewports become normal top-level windows (title bar,
               move/resize, individually capturable) - the scrcpy window
               stays inside, so the crop keeps working.
"""

import ctypes
import logging
from ctypes import wintypes

from src.win32_dock import apply_docked_style, frame_insets, set_client_rect
from src.win32_darkmode import enable_dark_titlebar

logger = logging.getLogger(__name__)

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

LRESULT = ctypes.c_longlong
WPARAM = ctypes.c_ulonglong
LPARAM = ctypes.c_longlong
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM)

user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
user32.SetParent.restype = wintypes.HWND

GWL_STYLE = -16
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_CLIPCHILDREN = 0x02000000
WS_CLIPSIBLINGS = 0x04000000
WS_OVERLAPPEDWINDOW = 0x00CF0000

WM_SIZE = 0x0005
WM_CLOSE = 0x0010
WM_SIZING = 0x0214
WM_PARENTNOTIFY = 0x0210
WM_MOUSEACTIVATE = 0x0021
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
MA_ACTIVATE = 1

WMSZ_LEFT, WMSZ_RIGHT, WMSZ_TOP = 1, 2, 3
WMSZ_TOPLEFT, WMSZ_TOPRIGHT, WMSZ_BOTTOM = 4, 5, 6
WMSZ_BOTTOMLEFT, WMSZ_BOTTOMRIGHT = 7, 8

SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_FRAMECHANGED = 0x0020
BLACK_BRUSH = 4

FULL_CROP = (0.0, 0.0, 1.0, 1.0)
CLASS_NAME = "DualCPYViewport"


class _WNDCLASSEX(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HANDLE),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HANDLE),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HANDLE),
    ]


class Viewport:
    def __init__(self, key):
        self.key = key
        self.hwnd = None
        self.child = None          # the scrcpy window inside
        self.crop = FULL_CROP      # (left, top, right, bottom) fractions of the full frame
        self.full_aspect = 16 / 9  # width / height of the full device screen
        self.title = key
        self._last_inner = None
        self._last_outer = None


class ViewportManager:
    """
    Owns the two viewport windows. create() must be called on the thread
    that runs the container's message loop (viewport messages are handled
    there). Everything else is safe to call from any thread.
    """

    def __init__(self, on_focus, on_close_request):
        self.on_focus = on_focus                  # callable(scrcpy_hwnd)
        self.on_close_request = on_close_request  # callable(): user closed a split window
        self.views = {"top": Viewport("top"), "bottom": Viewport("bottom")}
        self.split = False
        self._proc = WNDPROC(self._wndproc)       # keep a reference (no GC)
        self._by_hwnd = {}

    # ------------------------------------------------------------ creation
    def create(self, container, hinst, hicon=None):
        wc = _WNDCLASSEX()
        wc.cbSize = ctypes.sizeof(_WNDCLASSEX)
        wc.lpfnWndProc = ctypes.cast(self._proc, ctypes.c_void_p).value
        wc.lpszClassName = CLASS_NAME
        wc.hInstance = hinst
        wc.hbrBackground = gdi32.GetStockObject(BLACK_BRUSH)
        wc.hCursor = user32.LoadCursorW(None, ctypes.c_void_p(32512))  # IDC_ARROW
        if hicon:
            wc.hIcon = hicon
            wc.hIconSm = hicon
        user32.RegisterClassExW(ctypes.byref(wc))

        for v in self.views.values():
            v.hwnd = user32.CreateWindowExW(
                0, CLASS_NAME, v.title,
                WS_CHILD | WS_VISIBLE | WS_CLIPCHILDREN | WS_CLIPSIBLINGS,
                0, 0, 10, 10, container, None, hinst, None,
            )
            self._by_hwnd[v.hwnd] = v
            logger.info(f"Viewport '{v.key}' created (hwnd {v.hwnd})")

    def ready(self):
        return all(v.hwnd for v in self.views.values())

    def set_titles(self, top_title, bottom_title):
        self.views["top"].title = top_title
        self.views["bottom"].title = bottom_title
        for v in self.views.values():
            if v.hwnd:
                user32.SetWindowTextW(v.hwnd, v.title)

    # ------------------------------------------------------------ children
    def adopt(self, key, scrcpy_hwnd):
        """Put a (new) scrcpy window inside its viewport"""
        v = self.views[key]
        if not v.hwnd:
            return False
        user32.SetParent(scrcpy_hwnd, v.hwnd)
        apply_docked_style(scrcpy_hwnd)
        v.child = scrcpy_hwnd
        v._last_inner = None
        self.layout_inner(key)
        logger.info(f"scrcpy window {scrcpy_hwnd} adopted into viewport '{key}'")
        return True

    def release_children(self):
        for v in self.views.values():
            v.child = None
            v._last_inner = None

    # ------------------------------------------------------------ geometry
    def set_crop(self, key, crop, full_aspect=None):
        v = self.views[key]
        v.crop = tuple(crop)
        if full_aspect:
            v.full_aspect = full_aspect
        v._last_inner = None

    def client_size(self, key):
        v = self.views[key]
        rc = wintypes.RECT()
        if v.hwnd and user32.GetClientRect(v.hwnd, ctypes.byref(rc)):
            return rc.right, rc.bottom
        return 0, 0

    def client_screen_rect(self, key):
        """(left, top, right, bottom) of the viewport's client area on screen"""
        v = self.views[key]
        if not v.hwnd:
            return None
        w, h = self.client_size(key)
        pt = wintypes.POINT(0, 0)
        user32.ClientToScreen(v.hwnd, ctypes.byref(pt))
        return pt.x, pt.y, pt.x + w, pt.y + h

    def layout_inner(self, key, crop=None, force=False):
        """
        Size/position the scrcpy window inside the viewport so that only the
        crop region is visible. `crop` overrides the stored crop (used by
        detection to show the full frame temporarily).
        """
        v = self.views[key]
        if not (v.hwnd and v.child and user32.IsWindow(v.child)):
            return
        cw, ch = self.client_size(key)
        if cw <= 0 or ch <= 0:
            return
        l, t, r, b = crop or v.crop
        iw = cw / max(1e-3, r - l)
        ih = ch / max(1e-3, b - t)
        geom = (int(round(-l * iw)), int(round(-t * ih)), int(round(iw)), int(round(ih)))
        if force or geom != v._last_inner:
            user32.SetWindowPos(v.child, 0, *geom, SWP_NOZORDER | SWP_NOACTIVATE)
            v._last_inner = geom

    def place_docked(self, key, x, y, w, h, force=False):
        """Position a viewport inside the container (combined mode)"""
        v = self.views[key]
        if not v.hwnd or self.split:
            return
        geom = (int(x), int(y), int(w), int(h))
        if force or geom != v._last_outer:
            user32.SetWindowPos(v.hwnd, 0, *geom, SWP_NOZORDER | SWP_NOACTIVATE)
            v._last_outer = geom
        self.layout_inner(key, force=force)

    def resize_split(self, key, w, h, x=None, y=None):
        """Resize a split-mode window's client area, keeping its top-left"""
        v = self.views[key]
        if not v.hwnd:
            return
        if x is None or y is None:
            rect = self.client_screen_rect(key)
            x, y = rect[0], rect[1]
        set_client_rect(v.hwnd, x, y, w, h)
        self.layout_inner(key, force=True)

    # ------------------------------------------------------------ modes
    def to_split(self):
        """Turn both viewports into independent top-level windows"""
        for v in self.views.values():
            if not v.hwnd:
                continue
            x, y, r, b = self.client_screen_rect(v.key)
            user32.SetWindowLongW(v.hwnd, GWL_STYLE, WS_OVERLAPPEDWINDOW | WS_VISIBLE | WS_CLIPCHILDREN)
            user32.SetParent(v.hwnd, None)
            user32.SetWindowTextW(v.hwnd, v.title)
            set_client_rect(v.hwnd, x, y, r - x, b - y)
            try:
                enable_dark_titlebar(v.hwnd)
            except Exception:
                pass
            v._last_outer = None
        self.split = True

    def to_docked(self, container):
        """Put both viewports back inside the container"""
        for v in self.views.values():
            if not v.hwnd:
                continue
            user32.SetWindowLongW(v.hwnd, GWL_STYLE, WS_CHILD | WS_VISIBLE | WS_CLIPCHILDREN | WS_CLIPSIBLINGS)
            user32.SetParent(v.hwnd, container)
            user32.SetWindowPos(v.hwnd, 0, 0, 0, 0, 0,
                                SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOMOVE | SWP_NOSIZE | SWP_FRAMECHANGED)
            v._last_outer = None
        self.split = False

    # ------------------------------------------------------------ window proc
    def _crop_aspect(self, v):
        l, t, r, b = v.crop
        return v.full_aspect * (r - l) / max(1e-3, b - t)

    def _wndproc(self, hwnd, msg, wp, lp):
        v = self._by_hwnd.get(hwnd)
        try:
            if v is not None:
                if msg == WM_SIZE:
                    self.layout_inner(v.key)

                elif msg == WM_CLOSE:
                    # Closing a split window puts the screens back together
                    # instead of killing the stream
                    self.on_close_request()
                    return 0

                elif msg == WM_SIZING and self.split:
                    self._keep_aspect(v, wp, lp)
                    return 1

                elif msg == WM_PARENTNOTIFY and (wp & 0xFFFF) in (WM_LBUTTONDOWN, WM_RBUTTONDOWN):
                    if v.child:
                        self.on_focus(v.child)

                elif msg == WM_MOUSEACTIVATE and self.split:
                    if v.child:
                        self.on_focus(v.child)
                    return MA_ACTIVATE
        except Exception as e:
            logger.error(f"Viewport wndproc error: {e}")
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    def _keep_aspect(self, v, edge, lp):
        """Keep the split window's client area at the crop's aspect while dragging"""
        rect = ctypes.cast(lp, ctypes.POINTER(wintypes.RECT)).contents
        style = user32.GetWindowLongW(v.hwnd, GWL_STYLE)
        il, it, ir, ib = frame_insets(style, 0)
        cw = (rect.right - rect.left) - il - ir
        ch = (rect.bottom - rect.top) - it - ib
        aspect = self._crop_aspect(v)
        if edge in (WMSZ_TOP, WMSZ_BOTTOM):
            cw = int(round(ch * aspect))
            rect.right = rect.left + cw + il + ir
        else:
            ch = int(round(cw / aspect))
            if edge in (WMSZ_TOPLEFT, WMSZ_TOPRIGHT):
                rect.top = rect.bottom - ch - it - ib
            else:
                rect.bottom = rect.top + ch + it + ib
