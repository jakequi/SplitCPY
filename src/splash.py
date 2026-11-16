# SplitCPY - dual-screen scrcpy launcher for the AYN Thor and other handhelds
# Copyright (C) 2026 the_swest (original DualCPY) and SplitCPY contributors
# Fork of https://github.com/theswest/DualCPY
# Issues: https://github.com/jakequi/SplitCPY/issues
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

# src/splash.py
"""
Start-up splash: the SplitCPY logo and "Split CPY / Starting up..." shown
from launch until the program itself is on screen.

It's a plain Win32 layered window drawn with Pillow and run on its own thread
with its own message loop, so it stays up and responsive while the main thread
is busy (finding the device, starting the streams, building the control
panel) - a Tk splash can't, because it shares Tk's single thread.

    splash.show()
    splash.set_status("Starting streams...")
    splash.close()        # safe to call any number of times, from any thread
"""

import ctypes
import logging
import threading
from ctypes import wintypes

from PIL import Image, ImageDraw, ImageFont

from src.ui_constants import (BG_COLOUR, TEXT_COLOUR, ACCENT_COLOUR, ACCENT2_COLOUR,
                              ICON_PATH, FONT_PATH)

logger = logging.getLogger(__name__)

# Private copies: ctypes.windll.user32 is shared, and other modules declare
# argtypes on its functions (e.g. CreateWindowExW) that don't fit this code
user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
# Handles are 64-bit: declare every call so none is truncated to an int
_H = wintypes.HANDLE
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.c_void_p, ctypes.c_void_p,
                                       wintypes.HDC, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                                       wintypes.DWORD]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.PeekMessageW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.TranslateMessage.argtypes = [ctypes.c_void_p]
user32.DispatchMessageW.argtypes = [ctypes.c_void_p]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.SelectObject.restype = _H
gdi32.SelectObject.argtypes = [wintypes.HDC, _H]
gdi32.DeleteObject.argtypes = [_H]
gdi32.DeleteDC.argtypes = [wintypes.HDC]

WIDTH, HEIGHT = 480, 190          # logical px, same as the old Tk splash
SAFETY_CLOSE_S = 60               # never outlive a stuck start-up

WS_POPUP = 0x80000000
WS_EX_LAYERED, WS_EX_TOOLWINDOW, WS_EX_TOPMOST = 0x00080000, 0x00000080, 0x00000008
WS_EX_NOACTIVATE = 0x08000000
ULW_ALPHA, AC_SRC_OVER, AC_SRC_ALPHA = 0x2, 0x0, 0x1
SW_SHOWNOACTIVATE = 4
PM_REMOVE = 1


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


_lock = threading.Lock()
_thread = None
_stop = threading.Event()
_status = {"text": "Starting up...", "dirty": False}


def _scale():
    try:
        return user32.GetDpiForSystem() / 96
    except Exception:
        return 1.0


def _font(size):
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        return ImageFont.load_default()


def _render(status):
    """The splash as a premultiplied BGRA image (same layout as the old Tk one)"""
    s = _scale()
    w, h = int(WIDTH * s), int(HEIGHT * s)
    radius = int(14 * s)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=BG_COLOUR,
                        outline="#2a2e38", width=max(1, int(s)))

    logo_size = int(96 * s)
    title_font, status_font = _font(int(45 * s)), _font(int(22 * s))
    split_w = d.textlength("Split", font=title_font)
    text_w = max(split_w + d.textlength("CPY", font=title_font), d.textlength(status, font=status_font))
    gap = int(22 * s)
    x = int((w - (logo_size + gap + text_w)) / 2)
    try:
        logo = Image.open(ICON_PATH).convert("RGBA").resize((logo_size, logo_size), Image.LANCZOS)
        img.alpha_composite(logo, (x, (h - logo_size) // 2))
    except Exception as e:
        logger.debug(f"Splash logo failed: {e}")
    tx = x + logo_size + gap
    title_h = int(52 * s)
    status_h = int(30 * s)
    ty = (h - title_h - status_h) // 2
    d.text((tx, ty), "Split", font=title_font, fill=ACCENT_COLOUR)
    d.text((tx + split_w, ty), "CPY", font=title_font, fill=ACCENT2_COLOUR)
    d.text((tx, ty + title_h), status, font=status_font, fill=TEXT_COLOUR)

    # UpdateLayeredWindow wants premultiplied alpha, in B, G, R, A byte order
    r, g, b, a = img.convert("RGBa").split()
    bgra = Image.merge("RGBA", (b, g, r, a)).tobytes()
    return w, h, bgra


def _blit(hwnd, w, h, bgra):
    """Push a BGRA image to the layered window"""
    screen = user32.GetDC(None)
    mem = gdi32.CreateCompatibleDC(screen)
    bmi = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    bits = ctypes.c_void_p()
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                       ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
    bmp = gdi32.CreateDIBSection(mem, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    ctypes.memmove(bits, bgra, len(bgra))
    old = gdi32.SelectObject(mem, bmp)
    size = wintypes.SIZE(w, h)
    src = wintypes.POINT(0, 0)
    blend = _BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
    user32.UpdateLayeredWindow(hwnd, screen, None, ctypes.byref(size), mem, ctypes.byref(src),
                               0, ctypes.byref(blend), ULW_ALPHA)
    gdi32.SelectObject(mem, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(None, screen)


def _run():
    try:
        w, h, bgra = _render(_status["text"])
        sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                           ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                           wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        hwnd = user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_NOACTIVATE,
            "Static", "SplitCPY - Loading...", WS_POPUP,
            (sw - w) // 2, int((sh - h) / 2.5), w, h, None, None, None, None)
        if not hwnd:
            return
        _blit(hwnd, w, h, bgra)
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        msg = wintypes.MSG()
        while not _stop.wait(0.03):
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            if _status["dirty"]:
                _status["dirty"] = False
                w, h, bgra = _render(_status["text"])
                _blit(hwnd, w, h, bgra)
        user32.DestroyWindow(hwnd)
    except Exception as e:
        logger.warning(f"Splash failed: {e}")
    finally:
        logger.info("Loading screen closed")


_generation = [0]


def show(status=None):
    """Show the splash (again, e.g. after the Wireless screen or device picker)"""
    global _thread
    with _lock:
        if status:
            _status["text"] = status
        if _thread and _thread.is_alive():
            if not _stop.is_set():
                _status["dirty"] = True
                return              # already showing
            _thread.join(1.0)       # still closing from an earlier close()
        _stop.clear()
        _status["dirty"] = False
        _generation[0] += 1
        logger.info("Showing loading screen")
        _thread = threading.Thread(target=_run, name="splash", daemon=True)
        _thread.start()
        # Only closes this showing, not one started after it
        gen = _generation[0]
        timer = threading.Timer(SAFETY_CLOSE_S, lambda: _generation[0] == gen and close())
        timer.daemon = True     # must never keep SplitCPY alive on exit
        timer.start()


def set_status(text):
    _status["text"] = text
    _status["dirty"] = True


def close():
    _stop.set()
