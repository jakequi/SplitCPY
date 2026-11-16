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

# src/stats_overlay.py
"""
Stream stats overlay: a small translucent box in the corner of the stream
showing FPS per screen, codec, bitrate and the connection (USB, or Wi-Fi with
its round-trip time).

It is a separate, click-through window owned by the stage window, so it sits
just above the stream (not above other apps), never takes focus or clicks,
and isn't recorded by OBS Window Capture of the stream.

All Tk calls happen on the control panel's Tk thread (via after()); the
Wi-Fi round-trip time is measured on a background thread.
"""

import os
import re
import time
import ctypes
import socket
import logging
import threading
import subprocess
import tkinter as tk
from ctypes import wintypes

logger = logging.getLogger(__name__)

user32 = ctypes.windll.user32
user32.GetAncestor.restype = wintypes.HWND
user32.GetParent.restype = wintypes.HWND
user32.SetWindowLongPtrW.restype = ctypes.c_void_p
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
user32.GetWindowLongW.restype = ctypes.c_long

GWL_EXSTYLE = -20
GWLP_HWNDPARENT = -8
GA_ROOT = 2
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
CREATE_NO_WINDOW = 0x08000000

TICK_MS = 1000
RTT_INTERVAL_S = 2.0
MARGIN = 8
FPS_RE = re.compile(rb"(\d+) fps")
CODEC_NAMES = {"h264": "H.264", "h265": "H.265", "av1": "AV1"}


class StatsOverlay:
    def __init__(self, launcher, tk_root):
        self.l = launcher
        self.root = tk_root
        self.enabled = False
        self.win = None
        self.label = None
        self._owner = None
        self._rtt_ms = None
        self._rtt_thread = None
        self._ip_for = (None, None)    # (serial, ip)
        self.root.after(TICK_MS, self._tick)

    # ------------------------------------------------------------ public
    def set_enabled(self, on):
        self.enabled = bool(on)
        if self.enabled and not (self._rtt_thread and self._rtt_thread.is_alive()):
            self._rtt_thread = threading.Thread(target=self._rtt_loop, name="stats-rtt", daemon=True)
            self._rtt_thread.start()
        if not self.enabled and self.win:
            self.win.withdraw()

    # ------------------------------------------------------------ window
    def _ensure_window(self):
        if self.win:
            return
        self.win = tk.Toplevel(self.root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.configure(bg="#101014")
        try:
            self.win.attributes("-alpha", 0.82)
        except tk.TclError:
            pass
        self.label = tk.Label(self.win, text="", justify="left", anchor="w",
                              bg="#101014", fg="#e8e8ee", font=("Consolas", 10),
                              padx=8, pady=5)
        self.label.pack()
        self.win.update_idletasks()
        hwnd = self._hwnd()
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT
                              | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)

    def _hwnd(self):
        return user32.GetParent(self.win.winfo_id()) or self.win.winfo_id()

    def _set_owner(self, owner):
        """Owned windows stay just above their owner and follow it"""
        if owner != self._owner:
            user32.SetWindowLongPtrW(self._hwnd(), GWLP_HWNDPARENT, owner)
            self._owner = owner

    def _anchor(self):
        """(screen x, y, owner hwnd) of the first visible screen, or None"""
        rects = getattr(self.l, "view_rects", None) or {}
        views = getattr(getattr(self.l, "viewports", None), "views", {})
        for key in ("top", "bottom"):
            if key not in rects or key not in views:
                continue
            hwnd = views[key].hwnd
            if not hwnd or not user32.IsWindowVisible(hwnd):
                continue
            root = user32.GetAncestor(hwnd, GA_ROOT) or hwnd
            if user32.IsIconic(root):
                return None
            pt = wintypes.POINT(MARGIN, MARGIN)
            user32.ClientToScreen(hwnd, ctypes.byref(pt))
            return pt.x, pt.y, root
        return None

    # ------------------------------------------------------------ stats
    @staticmethod
    def _last_fps(path):
        try:
            with open(path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 400))
                hits = FPS_RE.findall(f.read())
            if hits and time.time() - os.path.getmtime(path) < 3:
                return int(hits[-1])
        except OSError:
            pass
        return None

    def _text(self):
        mgr = getattr(self.l, "scrcpy", None)
        info = getattr(mgr, "stream_info", None) or {}
        if not info:
            return None
        rects = getattr(self.l, "view_rects", None) or {}
        parts = []
        for key in ("top", "bottom"):
            if key in info and key in rects:
                fps = self._last_fps(info[key]["log"])
                parts.append(f"{key.title()} {fps if fps is not None else '--'} fps")
        lines = ["  ".join(parts) or "--"]

        first = info.get("top") or next(iter(info.values()))
        codec = CODEC_NAMES.get(first.get("codec"), first.get("codec") or "?")
        rates = [info[k]["mbps"] for k in ("top", "bottom") if k in info and info[k].get("mbps")]
        rate = " + ".join(f"{r:g}" for r in rates)
        lines.append(f"{codec}  {rate} Mbps" if rate else codec)

        if getattr(mgr, "is_wireless", False):
            lines.append(f"Wi-Fi  {self._rtt_ms:.0f} ms" if self._rtt_ms is not None else "Wi-Fi  -- ms")
        else:
            lines.append("USB")
        return "\n".join(lines)

    def _tick(self):
        try:
            if self.enabled:
                anchor = self._anchor()
                text = self._text() if anchor else None
                if anchor and text:
                    self._ensure_window()
                    x, y, owner = anchor
                    self._set_owner(owner)
                    self.label.configure(text=text)
                    self.win.geometry(f"+{x}+{y}")
                    if self.win.state() == "withdrawn":
                        self.win.deiconify()
                elif self.win:
                    self.win.withdraw()
        except Exception as e:
            logger.debug(f"Stats overlay tick failed: {e}")
        self.root.after(TICK_MS, self._tick)

    # ------------------------------------------------------------ Wi-Fi RTT
    def _device_addr(self, mgr):
        """(ip, port) of the device's open adb port. Closed ports on Android
        drop the handshake instead of refusing it, so it has to be this one."""
        serial = getattr(mgr, "serial", None)
        if self._ip_for[0] == serial:
            return self._ip_for[1]
        addr = None
        m = re.match(r"^(\d+\.\d+\.\d+\.\d+):(\d+)$", serial or "")
        if m:
            addr = (m.group(1), int(m.group(2)))
        elif serial and getattr(mgr, "adb_bin", None):
            # Wireless-debugging name (adb-XXXX._adb-tls-connect._tcp)
            try:
                out = subprocess.run([mgr.adb_bin, "mdns", "services"], capture_output=True,
                                     text=True, timeout=5, creationflags=CREATE_NO_WINDOW).stdout
                name = serial.split(".", 1)[0]
                for line in out.splitlines():
                    parts = line.split()
                    if len(parts) >= 3 and parts[0] == name and parts[1] in serial:
                        ip, _, port = parts[-1].rpartition(":")
                        if ip and port.isdigit():
                            addr = (ip, int(port))
                            break
            except Exception:
                pass
        self._ip_for = (serial, addr)
        return addr

    def _rtt_loop(self):
        """One TCP handshake (or refusal) to the device = one network round trip"""
        while self.enabled:
            mgr = getattr(self.l, "scrcpy", None)
            rtt = None
            if mgr is not None and getattr(mgr, "is_wireless", False):
                addr = self._device_addr(mgr)
                if addr:
                    t0 = time.perf_counter()
                    try:
                        with socket.create_connection(addr, timeout=1.0):
                            pass
                        rtt = (time.perf_counter() - t0) * 1000
                    except OSError:
                        rtt = None
                        self._ip_for = (None, None)  # port may have changed; look again
            # Light smoothing so the number doesn't flicker
            if rtt is not None and self._rtt_ms is not None:
                rtt = self._rtt_ms * 0.5 + rtt * 0.5
            self._rtt_ms = rtt
            time.sleep(RTT_INTERVAL_S)
