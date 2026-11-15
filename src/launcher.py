# DualCPY Split - dual-screen scrcpy launcher for the AYN Thor and other handhelds
# Copyright (C) 2026 the_swest (original DualCPY) and DualCPY Split contributors
# Fork of https://github.com/theswest/DualCPY
# Issues: https://github.com/jakequi/DualCPY-Split/issues
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

# src/launcher.py

import os
import sys
import time
import ctypes
import logging
import queue
import threading
import subprocess
import customtkinter as _ctk
from ctypes import wintypes
from tkinter import messagebox
from dataclasses import replace as dc_replace

from src.presets import PresetStore
from src.config import ConfigManager
from src.scrcpy_manager import ScrcpyManager
from src.device_profile import BUILTIN_PROFILES
from src.win32_darkmode import enable_dark_titlebar
from src.wireless_dialog import show_wireless_dialog, wait_for_device
from src.device_selector import show_device_selector
from src.custom_profile_store import CustomProfileStore
from src.control_panel import show_loading_screen, CTkUI
from src.device_profile_editor import DeviceProfileEditorDialog
from src.win32_dock import (
    Win32Dock, monitor_work_area, monitor_rect, frame_insets, apply_docked_style,
)
from src.viewport import ViewportManager, FULL_CROP
from src.scrcpy_manager import valid_crop, ASPECT_PRESETS, ASPECT_ALIASES, FULL_SCREEN_LABEL
from src import app_volume
from src.controller_overlay import InputListener, StripRenderer
from src import process_guard
from src.device_detection import (
    detect_device, resolve_adb, get_device_info, get_display_list, auto_connect_wireless,
)
from src.ui_constants import resource_path

logger = logging.getLogger(__name__)

# Win32 window message constants
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002

# Win32 window style constants
WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_VISIBLE = 0x10000000
WS_CLIPCHILDREN = 0x02000000
WS_CLIPSIBLINGS = 0x04000000
WS_EX_CONTROLPARENT = 0x00010000

WM_MOUSEACTIVATE = 0x0021
MA_ACTIVATE = 1

# Window show/hide constants
SW_HIDE = 0
SW_SHOW = 5

# GDI constants
BLACK_BRUSH = 4

# Process creation flags
CREATE_NO_WINDOW = 0x08000000

# Allowed scrcpy FPS values exposed in the control panel
ALLOWED_FPS_VALUES = (30, 60, 90, 120)
DEFAULT_MAX_FPS = 60

# Container window initial position
DEFAULT_CONTAINER_X = 100
DEFAULT_CONTAINER_Y = 100

# Timing constants
SCRCPY_POLL_INTERVAL = 0.1
DOCKING_MONITOR_TIME_DELAY = 0.5

# Math constants
HALF = 0.5

# Stage (combined window) view modes
VIEW_MODES = ("both", "top", "bottom")
MAX_SCREEN_GAP = 200

# Global hotkeys (work while gaming / from OBS): Ctrl+Alt+<key>
WM_SIZE = 0x0005
WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0001, 0x0002, 0x4000
HOTKEYS = {
    1: (ord("1"), "both"),
    2: (ord("2"), "top"),
    3: (ord("3"), "bottom"),
    4: (ord("S"), "cycle"),
    5: (ord("F"), "fullscreen"),
    6: (ord("M"), "menu"),
    7: (ord("O"), "screens"),
}
WS_POPUP = 0x80000000
# Controller overlay: width of each side strip relative to the bottom screen's height
OVERLAY_STRIP = 0.42
WM_PAINT = 0x000F
WM_APP_TOGGLE_FULLSCREEN = 0x8000 + 1   # WM_APP + 1, posted by the F11 hook
WS_MAXIMIZEBOX = 0x00010000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_CHILD = 0x40000000
# No maximise box: the window always takes the exact shape of the game area
CONTAINER_STYLE = (WS_OVERLAPPEDWINDOW & ~WS_MAXIMIZEBOX) | WS_VISIBLE | WS_CLIPCHILDREN | WS_CLIPSIBLINGS
WM_ACTIVATE = 0x0006
WM_SIZING = 0x0214
WM_EXITSIZEMOVE = 0x0232
WMSZ_TOP, WMSZ_BOTTOM = 3, 6
WMSZ_TOPLEFT, WMSZ_TOPRIGHT = 4, 5


class Launcher:
    """
    Main window controller for DualCPY
    Manages scrcpy instances, docking and undocking behabiour,
    UI rendering and event handling and configuration persistance

    The launcher makes a container window that holds 2 scrcpy instances and controls positioning
    """

    def __init__(self):
        """
        Sets up the launcher with default layouts and configurations
        Sets up scrcpy instance with saved scale
        forces the default layout on boot
        Manages windows docking
        Sorts out Win32 API function signatures
        """
        logger.info("Initializing Launcher with Forced Default Layout")
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32

        # Load config managers
        self.store = PresetStore("config/layout.json")
        self.config = ConfigManager("config/config.json")
        self.custom_profiles = CustomProfileStore("config/custom_profiles.json")
        # Saved setups ("profiles"): view, aspect, gap, audio, latency, FPS...
        self.setups = PresetStore("config/profiles.json")
        self.default_setup = self.config.get("default_profile", None)
        # Device profiles (per-handheld screen definitions) can be switched off:
        # then the built-in AYN Thor profile is always used, no selector
        self.device_profiles_enabled = bool(self.config.get("device_profiles_enabled", True))

        # Load scale from config if saved, otherwise let ScrcpyManager fall back to profile
        saved_scale = self.config.get("global_scale", None)
        self.launch_scale = saved_scale

        # Load max FPS from config
        try:
            cfg_fps = int(self.config.get("max_fps", DEFAULT_MAX_FPS))
        except (TypeError, ValueError):
            cfg_fps = DEFAULT_MAX_FPS
        self.max_fps = cfg_fps if cfg_fps in ALLOWED_FPS_VALUES else DEFAULT_MAX_FPS

        # Stream options (applied by restarting the streams)
        self.audio_mode = self.config.get("audio_mode", "pc")
        self.audio_latency = self.config.get("audio_latency", "low")
        self.quality = self.config.get("quality", "high")
        self.thor_screens_off = bool(self.config.get("thor_screens_off", False))
        self.render_driver = self.config.get("render_driver", "direct3d")
        # Live controller overlay beside the bottom screen (experimental)
        self.controller_overlay = bool(self.config.get("controller_overlay", False))
        self.overlay_strips = None          # {"left": (x,y,w,h), "right": ...} client coords
        self._overlay_listener = None
        self._overlay_renderer = StripRenderer()
        self._overlay_bitmaps = {}          # side -> (x, y, w, h, BGRX bytes)
        self._overlay_lock = threading.Lock()
        self._overlay_dirty = threading.Event()
        self._overlay_thread = None
        self.bottom_fps = int(self.config.get("bottom_fps", 0) or 0)
        # Visible region of each screen (PC-side crop, no restart needed)
        self.top_aspect = self._normalise_aspect(self.config.get("top_aspect", FULL_SCREEN_LABEL))
        self.bottom_aspect = self._normalise_aspect(self.config.get("bottom_aspect", FULL_SCREEN_LABEL))
        self.crops = {}
        for key in ("top", "bottom"):
            crop = self.config.get(f"{key}_crop", None)
            if crop and valid_crop(crop):
                self.crops[key] = tuple(crop)
            else:
                # Older config: aspect name without a crop region -> start full
                self.crops[key] = FULL_CROP
                setattr(self, f"{key}_aspect", FULL_SCREEN_LABEL)

        # Stream restart / auto-reconnect state
        self._restarting = False
        self._reconnect_attempts = 0
        self._last_reconnect = 0.0

        # Stage: which screen(s) the combined window shows, gap between them
        self.view_mode = self.config.get("view_mode", "both")
        if self.view_mode not in VIEW_MODES:
            self.view_mode = "both"
        try:
            self.screen_gap = max(0, min(MAX_SCREEN_GAP, int(self.config.get("screen_gap", 0))))
        except (TypeError, ValueError):
            self.screen_gap = 0
        self.view_rects = {}            # key -> (x, y, w, h) in container client coords
        self.fullscreen = False
        self._normal_placement = None   # (style, rect) to restore after fullscreen
        self.hwnd_backdrop = None       # black window behind the stage in fullscreen
        self._backdrop_proc = None
        # Height of the windowed stage; the width follows the view's shape, so
        # switching Both / Top / Bottom keeps the same height in OBS
        try:
            self.stage_height = int(self.config.get("stage_height", 0)) or None
        except (TypeError, ValueError):
            self.stage_height = None

        # PC volume of the stream (0-100), applied to scrcpy's audio session
        try:
            self.volume = max(0, min(100, int(self.config.get("volume", 100))))
        except (TypeError, ValueError):
            self.volume = 100
        self._volume_applied_pid = None

        # Set from the viewport thread when a split window is closed
        self._request_dock = False

        # Tk is not thread-safe: other threads queue UI callbacks here and the
        # control panel runs them on the Tk thread (see CTkUI._update_loop)
        self.ui_calls = queue.Queue()

        # Layout attributes
        self.scrcpy = None
        self.tx = None
        self.ty = None
        self.bx = None
        self.by = None
        self.global_scale = None

        # ADB model name of the connected device
        self.device_model = None

        self._tk_root = None

        # Initialise window management
        self.dock = Win32Dock()
        self.viewports = ViewportManager(
            on_focus=lambda hwnd: self.dock.force_focus(hwnd),
            on_close_request=self._on_split_window_closed,
        )
        self.running = False
        self.docked = True
        self.hwnd_container = None
        self._wndproc = None
        self.dock_lock = threading.Lock()

        # Define Win32 API signatures for type safety
        self.LRESULT = ctypes.c_longlong
        self.WPARAM = ctypes.c_ulonglong
        self.LPARAM = ctypes.c_longlong

        try:
            self.user32.DefWindowProcW.argtypes = [
                wintypes.HWND,
                wintypes.UINT,
                self.WPARAM,
                self.LPARAM,
            ]
            self.user32.DefWindowProcW.restype = self.LRESULT
        except Exception as e:
            logger.error(f"Error when defining window argtypes: {e}")
            pass

        # Make sure GDI signatures are wide enough for 64-bit handles
        try:
            self._setup_gdi_signatures()
        except Exception as e:
            logger.error(f"Error when defining GDI argtypes: {e}")

    def _save_device_profile(self, serial: str, profile_key: str, scale: float = None):
        """
        Persist a serial and storage_key (and optionally scale) mapping so that
        the next boot for this device loads the exact profile and scale chosen
        If scale is None the existing saved scale for this serial is left alone
        """
        try:
            cfg = self.config.load()
            device_profiles = cfg.get("device_profiles", {})
            device_profiles[serial] = profile_key
            cfg["device_profiles"] = device_profiles

            if scale is not None:
                device_scales = cfg.get("device_scales", {})
                device_scales[serial] = scale
                cfg["device_scales"] = device_scales

            self.config.save(cfg)

            logger.info(f"Saved device profile mapping: {serial} -> key '{profile_key}'" +
                        (f", scale {scale}" if scale is not None else ""))

        except Exception as e:
            logger.error(f"Failed to save device profile mapping: {e}")

    def _save_device_scale(self, serial: str, scale: float):
        """Keep only the scale for a specific device serial"""
        try:
            cfg = self.config.load()
            device_scales = cfg.get("device_scales", {})
            device_scales[serial] = scale
            cfg["device_scales"] = device_scales
            self.config.save(cfg)
        except Exception as e:
            logger.error(f"Failed to save device scale: {e}")

    @staticmethod
    def _normalise_aspect(name):
        name = ASPECT_ALIASES.get(name, name)
        return name if name in ASPECT_PRESETS else FULL_SCREEN_LABEL

    def _make_manager(self, profile, scale):
        """Create a ScrcpyManager with all current stream options applied"""
        return ScrcpyManager(
            profile=profile,
            scale=scale,
            max_fps=self.max_fps,
            audio_mode=self.audio_mode,
            audio_latency=self.audio_latency,
            crops=self.crops,
            quality=self.quality,
            render_driver=self.render_driver,
            bottom_fps=self.bottom_fps,
        )

    def _apply_default_layout(self):
        layout = self.get_default_layout()
        self.tx, self.ty, self.bx, self.by = layout["tx"], layout["ty"], layout["bx"], layout["by"]

    def _container_client_size(self):
        """Initial client size: the current view's game area at the saved height"""
        s = self.scrcpy
        if not self.stage_height:
            self.stage_height = max(160, s.f_h1 + s.f_h2 + self.screen_gap)
        w, h = self._content_size_for_height(self.stage_height)
        work = monitor_work_area(None)
        if work:
            il, it, ir, ib = frame_insets(CONTAINER_STYLE, WS_EX_CONTROLPARENT)
            max_w = work[2] - work[0] - il - ir
            max_h = work[3] - work[1] - it - ib
            if w > max_w or h > max_h:
                w, h = self._content_fit(min(w, max_w), min(h, max_h))
        return max(1, int(round(w))), max(1, int(round(h)))

    def get_default_layout(self):
        """
        Return the centred default layout dictionary for the current profile/scale
        """
        w1, h1 = self.scrcpy.f_w1, self.scrcpy.f_h1
        w2, h2 = self.scrcpy.f_w2, self.scrcpy.f_h2
        ty = 0
        by = int(h1)

        if w1 >= w2:
            tx = 0
            bx = int((w1 - w2) * HALF)
        else:
            bx = 0
            tx = int((w2 - w1) * HALF)
        return {"tx": tx, "ty": ty, "bx": bx, "by": by}

    def save_layout(self):
        """
        Saves current state and scale to config file
        """
        try:
            cfg = self.config.load()
            cfg["tx"] = self.tx
            cfg["ty"] = self.ty
            cfg["bx"] = self.bx
            cfg["by"] = self.by
            cfg["global_scale"] = self.global_scale
            cfg["view_mode"] = self.view_mode
            cfg["screen_gap"] = self.screen_gap
            placement = self._container_placement()
            if placement:
                cfg["container_pos"], cfg["container_client"] = placement
            if self.stage_height:
                cfg["stage_height"] = int(self.stage_height)

            if self.scrcpy and getattr(self.scrcpy, "profile", None):
                cfg["last_profile"] = self.scrcpy.profile.name

            # Persist scale per-device so each device remembers its own scale
            if self.scrcpy and self.global_scale is not None:
                serial = getattr(self.scrcpy, "serial", None)

                if serial:
                    device_scales = cfg.get("device_scales", {})
                    device_scales[serial] = self.global_scale
                    cfg["device_scales"] = device_scales

            self.config.save(cfg)
            logger.info(f"Saved configuration (Scale: {self.global_scale})")

        except Exception as e:
            logger.error(f"Failed to save configuration: {e}")

    def save_scale(self):
        """Save only the global scale to config in a single write"""
        try:
            cfg = self.config.load()
            cfg["global_scale"] = self.global_scale

            if self.scrcpy and self.global_scale is not None:
                serial = getattr(self.scrcpy, "serial", None)

                if serial:
                    device_scales = cfg.get("device_scales", {})
                    device_scales[serial] = self.global_scale
                    cfg["device_scales"] = device_scales

            self.config.save(cfg)

        except Exception as e:
            logger.error(f"Failed to save scale: {e}")

    def _create_wnd_proc(self):
        WM_LBUTTONDOWN = 0x0201
        WM_PARENTNOTIFY = 0x0210

        WNDPROC = ctypes.WINFUNCTYPE(
            self.LRESULT, wintypes.HWND, wintypes.UINT, self.WPARAM, self.LPARAM
        )

        def py_wndproc(hwnd, msg, wp, lp):
            if msg in (WM_CLOSE, WM_DESTROY):
                self.stop()
                return 0

            try:
                if msg == WM_SIZE:
                    # The stage always fills the window: re-layout on every resize
                    self.layout_windows()

                elif msg == WM_SIZING and self.docked and not self.fullscreen:
                    # Keep the window exactly the shape of the game area while dragging
                    self._keep_stage_shape(int(wp), lp)
                    return 1

                elif msg == WM_EXITSIZEMOVE and self.docked and not self.fullscreen:
                    rc = wintypes.RECT()
                    self.user32.GetClientRect(hwnd, ctypes.byref(rc))
                    if rc.bottom > 50:
                        self.stage_height = rc.bottom

                elif msg == WM_ACTIVATE and self.fullscreen:
                    self._place_backdrop()

                elif msg == WM_APP_TOGGLE_FULLSCREEN:
                    self.toggle_fullscreen()
                    return 0

                elif msg == WM_PAINT and self.overlay_strips:
                    self._paint_overlay(hwnd)
                    return 0

                elif msg == WM_HOTKEY:
                    self._on_hotkey(int(wp))
                    return 0

                elif msg == WM_MOUSEACTIVATE and self.scrcpy is not None:
                    # Focus whichever screen is under the cursor
                    pt = wintypes.POINT()
                    self.user32.GetCursorPos(ctypes.byref(pt))
                    self.user32.ScreenToClient(hwnd, ctypes.byref(pt))
                    for key, rect in self.view_rects.items():
                        x, y, w, h = rect
                        if x <= pt.x < x + w and y <= pt.y < y + h:
                            child = self.dock.hwnd_top if key == "top" else self.dock.hwnd_bottom
                            self.dock.force_focus(child)
                            break
                    return MA_ACTIVATE
            except Exception as e:
                logger.error(f"Container wndproc error: {e}")

            return self.user32.DefWindowProcW(hwnd, msg, wp, lp)

        return WNDPROC(py_wndproc)

    def _setup_gdi_signatures(self):
        """
        Tell ctypes the proper signatures for the GDI functions we invoke
        """
        gdi32 = ctypes.windll.gdi32
        gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        gdi32.SelectObject.restype = wintypes.HGDIOBJ
        gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        gdi32.CreateCompatibleDC.restype = wintypes.HDC
        gdi32.DeleteDC.argtypes = [wintypes.HDC]
        gdi32.DeleteDC.restype = wintypes.BOOL
        gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        gdi32.DeleteObject.restype = wintypes.BOOL
        gdi32.BitBlt.argtypes = [
            wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD,
        ]
        gdi32.BitBlt.restype = wintypes.BOOL
        gdi32.GetStockObject.argtypes = [ctypes.c_int]
        gdi32.GetStockObject.restype = wintypes.HGDIOBJ

        self.user32.FillRect.argtypes = [
            wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH,
        ]

        self.user32.FillRect.restype = ctypes.c_int
        self.user32.UpdateWindow.argtypes = [wintypes.HWND]
        self.user32.UpdateWindow.restype = wintypes.BOOL

    def cycle_max_fps(self):
        """
        Cycle through the allowed FPS presets (30 -> 60 -> 120 -> 30)
        Persists to config. Takes effect on the next scrcpy restart;
        the user is expected to click RESTART afterwards.
        """
        try:
            idx = ALLOWED_FPS_VALUES.index(self.max_fps)
        except ValueError:
            idx = ALLOWED_FPS_VALUES.index(DEFAULT_MAX_FPS)
        new_fps = ALLOWED_FPS_VALUES[(idx + 1) % len(ALLOWED_FPS_VALUES)]
        self.set_max_fps(new_fps)
        return new_fps

    def set_max_fps(self, fps):
        """Set the FPS cap and persist; restart required to take effect"""
        if fps not in ALLOWED_FPS_VALUES:
            logger.warning(f"Ignoring out-of-range FPS request: {fps}")
            return
        logger.info(f"FPS preference changed: {self.max_fps} -> {fps}")
        self.max_fps = fps
        try:
            self.config.set("max_fps", fps)
        except Exception as e:
            logger.warning(f"Failed to persist max_fps: {e}")
        # Update the live ScrcpyManager so a restart picks it up
        if hasattr(self, "scrcpy"):
            self.scrcpy.max_fps = fps

    def restart_app(self):
        """
        Restart the entire application. Spawns a fresh main.py (or
        the bundled exe under PyInstaller) and exits this process.
        Used by the control panel after global-scale or FPS changes.
        """
        try:
            if getattr(sys, "frozen", False):
                project_root = os.path.dirname(sys.executable)
                cmd = [sys.executable]
            else:
                project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                main_script = os.path.join(project_root, "main.py")
                cmd = [sys.executable, main_script]

            child_env = os.environ.copy()
            for key in (
                "_MEIPASS2",
                "_PYI_APPLICATION_HOME_DIR",
                "_PYI_PARENT_PROCESS_LEVEL",
                "_PYI_SPLASH_IPC",
            ):
                child_env.pop(key, None)

            logger.info(f"Restarting application: {' '.join(cmd)}")
            subprocess.Popen(cmd, cwd=project_root, env=child_env,
                             creationflags=process_guard.breakaway_flags())

        except Exception as e:
            logger.error(f"Failed to spawn restart process: {e}", exc_info=True)
            return

        self.stop()

    def _create_container_window(self):
        """
        Creates the main container window in a background thread
        Handles both scrcpy windows as children
        Waits for scrcpy dimensions to be available before creating window
        """

        def loop():
            # Wait for the window dimensions
            while self.scrcpy.f_w1 == 0:
                time.sleep(SCRCPY_POLL_INTERVAL)
                if not self.running:
                    return

            # Define window class structure
            class WNDCLASSEX(ctypes.Structure):
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

            # Register the class
            wc = WNDCLASSEX()
            wc.cbSize = ctypes.sizeof(WNDCLASSEX)
            wc.lpfnWndProc = ctypes.cast(self._wndproc, ctypes.c_void_p).value
            wc.lpszClassName = "DualCPYBridge"
            hinst = self.kernel32.GetModuleHandleW(None)
            wc.hInstance = hinst
            wc.hbrBackground = ctypes.windll.gdi32.GetStockObject(BLACK_BRUSH)

            # Load the application icon.
            # We build a list of candidate paths to try in order, because the
            # working directory differs between PyCharm, terminal, and PyInstaller.
            hicon = None
            IMAGE_ICON      = 1
            LR_LOADFROMFILE = 0x00000010
            LR_DEFAULTSIZE  = 0x00000040

            if getattr(sys, "frozen", False):
                # Frozen: try the PyInstaller _MEIPASS bundle, then extract from exe
                icon_candidates = [resource_path("assets/icon.ico")]
            else:
                # Dev: try cwd, the project root (one level above src/), and the
                # directory containing this file - covers all PyCharm run configs
                _this_dir    = os.path.dirname(os.path.abspath(__file__))
                _project_root = os.path.dirname(_this_dir)
                icon_candidates = [
                    os.path.join(os.path.abspath("."), "assets", "icon.ico"),
                    os.path.join(_project_root, "assets", "icon.ico"),
                    os.path.join(_this_dir,     "assets", "icon.ico"),
                ]

            for _path in icon_candidates:
                if not os.path.exists(_path):
                    continue
                try:
                    hicon = self.user32.LoadImageW(
                        None, _path, IMAGE_ICON, 0, 0,
                        LR_LOADFROMFILE | LR_DEFAULTSIZE,
                    )
                    if hicon:
                        logger.debug(f"Container icon loaded from: {_path}")
                        break
                except Exception as e:
                    logger.debug(f"LoadImageW failed for {_path}: {e}")

            # Final fallback for frozen builds: extract icon embedded in the exe
            if not hicon and getattr(sys, "frozen", False):
                try:
                    large_icons = (wintypes.HICON * 1)()
                    small_icons = (wintypes.HICON * 1)()
                    n = ctypes.windll.shell32.ExtractIconExW(
                        sys.executable, 0, large_icons, small_icons, 1,
                    )
                    if n > 0:
                        hicon = large_icons[0]
                        logger.debug("Container icon extracted from exe resources")
                    else:
                        logger.warning("ExtractIconExW returned 0 - container will have blank icon")
                except Exception as e:
                    logger.warning(f"ExtractIconExW failed: {e}")

            if hicon:
                wc.hIcon   = hicon
                wc.hIconSm = hicon

            self.user32.RegisterClassExW(ctypes.byref(wc))

            # Calculate container size to fit both stacked windows
            client_w, client_h = self._container_client_size()

            # Adjustments for window decorations
            rect = wintypes.RECT(0, 0, int(client_w), int(client_h))
            style = CONTAINER_STYLE
            self.user32.AdjustWindowRectEx(
                ctypes.byref(rect), style, False, WS_EX_CONTROLPARENT
            )

            # Build window title with device name if available
            device_label = getattr(self, "device_model", None) or "Unknown Device"
            window_title = f"DualCPY Split | {device_label}"

            # Create the container window
            hwnd = self.user32.CreateWindowExW(
                WS_EX_CONTROLPARENT,
                "DualCPYBridge",
                window_title,
                style,
                *self._initial_container_pos(),
                rect.right - rect.left,
                rect.bottom - rect.top,
                None,
                0,
                ctypes.c_void_p(hinst),
                None,
            )

            if hwnd:
                self.hwnd_container = hwnd
                self.dock.hwnd_container = hwnd
                self.user32.ShowWindow(hwnd, SW_SHOW)

                # Enable the dark titlebar
                enable_dark_titlebar(hwnd)

                # Viewport windows that hold (and crop) the two scrcpy windows.
                # Created on this thread so this message loop services them.
                try:
                    self.viewports.create(hwnd, hinst, hicon)
                    self._update_viewport_meta()
                    self.layout_windows(force=True)
                except Exception as e:
                    logger.error(f"Failed to create viewports: {e}", exc_info=True)

                try:
                    self._create_backdrop(hinst)
                except Exception as e:
                    logger.error(f"Failed to create fullscreen backdrop: {e}", exc_info=True)

                # F11 = fullscreen while a DualCPY window is in front
                try:
                    self._install_f11_hook()
                except Exception as e:
                    logger.warning(f"F11 hook unavailable: {e}")

                # Global hotkeys must be registered on the thread that owns hwnd
                for hk_id, (vk, action) in HOTKEYS.items():
                    if not self.user32.RegisterHotKey(hwnd, hk_id, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, vk):
                        logger.warning(f"Hotkey Ctrl+Alt+{chr(vk)} ({action}) is in use by another app")

            # Run the message loop for the container window
            msg = wintypes.MSG()
            while self.running and self.user32.GetMessageW(
                    ctypes.byref(msg), None, 0, 0
            ):
                self.user32.TranslateMessage(ctypes.byref(msg))
                self.user32.DispatchMessageW(ctypes.byref(msg))

        threading.Thread(target=loop, daemon=True).start()

    @property
    def _window_titles(self):
        return self.scrcpy._window_titles()

    def _docking_monitor(self):
        """
        Background thread: finds new scrcpy windows (they appear as top-level
        windows) and moves them into their viewport. Once adopted they are
        child windows, so FindWindowW no longer sees them - only fresh ones
        after a (re)start are picked up.
        """
        while self.running:
            try:
                if self.hwnd_container and self.viewports.ready():
                    top_title, bottom_title = self._window_titles
                    with self.dock_lock:
                        top = self.user32.FindWindowW(None, top_title)
                        if top:
                            self.viewports.adopt("top", top)
                            self.dock.hwnd_top = top
                            self.scrcpy.top_ready.set()
                        bottom = self.user32.FindWindowW(None, bottom_title)
                        if bottom:
                            self.viewports.adopt("bottom", bottom)
                            self.dock.hwnd_bottom = bottom
                self._enforce_child_styles()
                self._check_stream_health()
                if self.audio_mode != "device" and not self._restarting:
                    self._apply_volume()
            except Exception as e:
                logger.error(f"Docking monitor error: {e}", exc_info=True)
            # Poll quickly while a stream window is still to be adopted
            waiting = not (self.viewports.views["top"].child and self.viewports.views["bottom"].child)
            time.sleep(0.1 if waiting else DOCKING_MONITOR_TIME_DELAY)

    # ------------------------------------------------------------------
    # Viewport layout
    # ------------------------------------------------------------------
    def _update_viewport_meta(self):
        """Push crop + titles for the current profile into the viewports"""
        if not self.scrcpy:
            return
        for key in ("top", "bottom"):
            self.viewports.set_crop(key, self.crops[key], self.scrcpy.full_aspect(key))
        device = getattr(self, "device_model", None) or self.scrcpy.profile.name
        self.viewports.set_titles(f"{device} | Top Screen", f"{device} | Bottom Screen")

    # ------------------------------------------------------------------
    # Stage layout (combined window)
    # ------------------------------------------------------------------
    def stage_layout(self, cw, ch):
        """
        Where each screen goes in a cw x ch window for the current view mode.
        Screens keep their aspect and are as large as possible, centred
        (so a single screen fills the height with natural side bars).
        Returns {"top": (x, y, w, h) or None, "bottom": ...}.
        """
        s = self.scrcpy
        w1, h1, w2, h2 = s.content_sizes(1.0)
        g = self.screen_gap if self.view_mode == "both" else 0
        rects = {"top": None, "bottom": None}
        if cw <= 0 or ch <= 0:
            return rects
        strips = 2 * OVERLAY_STRIP * h2 if self._overlay_active() else 0
        if self.view_mode == "both":
            k = max(0.01, min(cw / max(w1, w2 + strips), (ch - g) / (h1 + h2)))
            tw, th, bw, bh = w1 * k, h1 * k, w2 * k, h2 * k
            y0 = (ch - (th + bh + g)) / 2
            rects["top"] = ((cw - tw) / 2, y0, tw, th)
            rects["bottom"] = ((cw - bw) / 2, y0 + th + g, bw, bh)
        else:
            w, h = (w1, h1) if self.view_mode == "top" else (w2, h2)
            uw = w + (strips if self.view_mode == "bottom" else 0)
            k = min(cw / uw, ch / h)
            rects[self.view_mode] = ((cw - w * k) / 2, (ch - h * k) / 2, w * k, h * k)
        out = {key: (list(int(round(v)) for v in r) if r else None) for key, r in rects.items()}
        if self.view_mode == "both":
            # Absorb rounding so the stack exactly fills a window sized to it
            # (otherwise OBS captures a 1px black line)
            top, bot = out["top"], out["bottom"]
            spare = ch - (top[3] + bot[3] + g)
            if 0 < abs(spare) <= 2:
                top[1] = 0
                bot[1] = top[3] + g
                bot[3] += spare
        return {key: (tuple(r) if r else None) for key, r in out.items()}

    def layout_windows(self, force=False):
        """Lay out the viewports inside the container for the current view"""
        if not self.scrcpy or not self.viewports.ready() or not self.hwnd_container:
            return
        if not self.docked:
            if force:
                self.viewports.layout_inner("top", force=True)
                self.viewports.layout_inner("bottom", force=True)
            return
        rc = wintypes.RECT()
        self.user32.GetClientRect(self.hwnd_container, ctypes.byref(rc))
        rects = self.stage_layout(rc.right, rc.bottom)
        visible = {}
        for key, rect in rects.items():
            if rect:
                self.viewports.set_visible(key, True)
                self.viewports.place_docked(key, *rect, force=force)
                visible[key] = rect
            else:
                self.viewports.set_visible(key, False)
        self.view_rects = visible
        self._update_overlay_strips()

    def set_view_mode(self, mode):
        """Show both screens stacked, or just the top / bottom (filling the window)"""
        if mode == "cycle":
            mode = VIEW_MODES[(VIEW_MODES.index(self.view_mode) + 1) % len(VIEW_MODES)]
        if mode not in VIEW_MODES:
            return
        self.view_mode = mode
        logger.info(f"View mode -> {mode}")
        self.fit_container_to_content()
        try:
            self.config.set("view_mode", mode)
        except Exception:
            pass
        ui = getattr(self, "ui", None)
        if ui:
            try:
                self.ui_calls.put(ui._refresh_view_buttons)
            except Exception:
                pass

    def set_screen_gap(self, gap):
        self.screen_gap = max(0, min(MAX_SCREEN_GAP, int(gap)))
        self.fit_container_to_content()

    def _on_hotkey(self, hk_id):
        action = HOTKEYS.get(hk_id, (None, None))[1]
        if action == "screens":
            self.set_thor_screens_off(not self.thor_screens_off)
            ui = getattr(self, "ui", None)
            if ui:
                self.ui_calls.put(ui._sync_sliders_from_launcher)
            return
        if action == "menu":
            ui = getattr(self, "ui", None)
            if ui:
                self.ui_calls.put(ui.toggle_panel)
        elif action == "fullscreen":
            self.toggle_fullscreen()
        elif action:
            if not self.docked:
                return
            self.set_view_mode(action)

    # ------------------------------------------------------------------
    # Stage shape: the window is always exactly the game area (no black
    # bars for OBS to capture)
    # ------------------------------------------------------------------
    def _stage_units(self):
        """Unscaled sizes for the current view: (w, h, gap) with h excluding gap"""
        w1, h1, w2, h2 = self.scrcpy.content_sizes(1.0)
        strips = 2 * OVERLAY_STRIP * h2 if self._overlay_active() else 0
        if self.view_mode == "both":
            return max(w1, w2 + strips), h1 + h2, self.screen_gap
        if self.view_mode == "top":
            return w1, h1, 0
        return w2 + strips, h2, 0

    def _content_size_for_height(self, height):
        w, h, g = self._stage_units()
        k = max(0.01, (height - g) / h)
        return w * k, h * k + g

    def _content_size_for_width(self, width):
        w, h, g = self._stage_units()
        k = width / w
        return width, h * k + g

    def _content_fit(self, box_w, box_h):
        """Largest game-area size that fits in box_w x box_h"""
        w, h, g = self._stage_units()
        k = max(0.01, min(box_w / w, (box_h - g) / h))
        return w * k, h * k + g

    def _keep_stage_shape(self, edge, lp):
        rect = ctypes.cast(lp, ctypes.POINTER(wintypes.RECT)).contents
        il, it, ir, ib = frame_insets(CONTAINER_STYLE, WS_EX_CONTROLPARENT)
        cw = (rect.right - rect.left) - il - ir
        ch = (rect.bottom - rect.top) - it - ib
        if edge in (WMSZ_TOP, WMSZ_BOTTOM):
            cw, _ = self._content_size_for_height(ch)
            rect.right = rect.left + int(round(cw)) + il + ir
        else:
            _, ch = self._content_size_for_width(cw)
            ch = int(round(ch))
            if edge in (WMSZ_TOPLEFT, WMSZ_TOPRIGHT):
                rect.top = rect.bottom - ch - it - ib
            else:
                rect.bottom = rect.top + ch + it + ib

    def fit_container_to_content(self, center=False):
        """
        Resize the combined window to exactly the game area of the current
        view. Windowed: keeps the stage height (width follows the view's
        shape), stays on the monitor. Fullscreen: largest size that fits the
        monitor, centred over the black backdrop.
        """
        hwnd = self.hwnd_container
        if not hwnd or not self.scrcpy or not self.docked:
            self.layout_windows(force=True)
            return
        flags = 0x0004 | 0x0010  # NOZORDER | NOACTIVATE
        if self.fullscreen:
            mon = monitor_rect(hwnd)
            if mon:
                l, t, r, b = mon
                w, h = (int(round(v)) for v in self._content_fit(r - l, b - t))
                self.user32.SetWindowPos(hwnd, 0, l + (r - l - w) // 2, t + (b - t - h) // 2, w, h, flags)
                self._place_backdrop()
        else:
            work = monitor_work_area(hwnd)
            il, it, ir, ib = frame_insets(CONTAINER_STYLE, WS_EX_CONTROLPARENT)
            w, h = self._content_size_for_height(self.stage_height or 600)
            if work:
                max_w = work[2] - work[0] - il - ir
                max_h = work[3] - work[1] - it - ib
                if w > max_w or h > max_h:
                    w, h = self._content_fit(min(w, max_w), min(h, max_h))
            w, h = int(round(w)), int(round(h))
            ow, oh = w + il + ir, h + it + ib
            cur = wintypes.RECT()
            self.user32.GetWindowRect(hwnd, ctypes.byref(cur))
            if center and work:
                x = work[0] + (work[2] - work[0] - ow) // 2
                y = work[1] + (work[3] - work[1] - oh) // 2
            else:
                # Keep the window's horizontal centre and top edge
                x = (cur.left + cur.right) // 2 - ow // 2
                y = cur.top
            if work:
                x = max(work[0] - il, min(x, work[2] - ow + ir))
                y = max(work[1], min(y, work[3] - oh + ib))
            self.user32.SetWindowPos(hwnd, 0, x, y, ow, oh, flags)
        self.layout_windows(force=True)

    # ------------------------------------------------------------------
    # Fullscreen: stage window = game area, black backdrop behind it
    # ------------------------------------------------------------------
    def _create_backdrop(self, hinst):
        """A plain black popup covering the monitor behind the stage in fullscreen.
        It's a separate window, so OBS's Window Capture of the stage never sees it."""
        WNDPROC = ctypes.WINFUNCTYPE(self.LRESULT, wintypes.HWND, wintypes.UINT, self.WPARAM, self.LPARAM)

        def proc(hwnd, msg, wp, lp):
            if msg == WM_CLOSE:
                return 0
            if msg == WM_MOUSEACTIVATE:
                # Clicking the black area gives focus back to the game
                if self.hwnd_container:
                    self.user32.SetForegroundWindow(self.hwnd_container)
                return 3  # MA_NOACTIVATE
            return self.user32.DefWindowProcW(hwnd, msg, wp, lp)

        self._backdrop_proc = WNDPROC(proc)

        class WNDCLASSEX(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT), ("style", wintypes.UINT),
                ("lpfnWndProc", ctypes.c_void_p), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HANDLE), ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HANDLE), ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HANDLE),
            ]

        wc = WNDCLASSEX()
        wc.cbSize = ctypes.sizeof(WNDCLASSEX)
        wc.lpfnWndProc = ctypes.cast(self._backdrop_proc, ctypes.c_void_p).value
        wc.lpszClassName = "DualCPYBackdrop"
        wc.hInstance = hinst
        wc.hbrBackground = ctypes.windll.gdi32.GetStockObject(BLACK_BRUSH)
        self.user32.RegisterClassExW(ctypes.byref(wc))
        WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x00000080, 0x08000000
        self.user32.CreateWindowExW.restype = wintypes.HWND
        self.hwnd_backdrop = self.user32.CreateWindowExW(
            WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, "DualCPYBackdrop", "DualCPY Backdrop",
            WS_POPUP, 0, 0, 10, 10, None, None, ctypes.c_void_p(hinst), None,
        )

    def _place_backdrop(self):
        """Cover the monitor with the backdrop, directly beneath the stage"""
        if not (self.hwnd_backdrop and self.fullscreen):
            return
        mon = monitor_rect(self.hwnd_container)
        if not mon:
            return
        l, t, r, b = mon
        SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x0010, 0x0040
        self.user32.SetWindowPos(self.hwnd_backdrop, self.hwnd_container, l, t, r - l, b - t,
                                 SWP_NOACTIVATE | SWP_SHOWWINDOW)

    def toggle_fullscreen(self):
        """
        Fullscreen for OBS: the stage window becomes borderless and exactly the
        game area, as large as the monitor allows and centred; a separate black
        window fills the rest of the monitor. Window Capture of the stage
        therefore only ever contains the game.
        """
        if not self.hwnd_container:
            return
        if not self.docked:
            self.toggle_dock()
        GWL_STYLE = -16
        hwnd = self.hwnd_container
        if not self.fullscreen:
            rect = wintypes.RECT()
            self.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            self._normal_placement = (rect.left, rect.top, rect.right, rect.bottom)
            self.user32.SetWindowLongW(hwnd, GWL_STYLE,
                                       WS_POPUP | WS_VISIBLE | WS_CLIPCHILDREN | WS_CLIPSIBLINGS)
            self.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                                     0x0001 | 0x0002 | 0x0004 | 0x0020)  # NOSIZE|NOMOVE|NOZORDER|FRAMECHANGED
            self.fullscreen = True
            self.fit_container_to_content()
            self.user32.SetForegroundWindow(hwnd)
        else:
            if self.hwnd_backdrop:
                self.user32.ShowWindow(self.hwnd_backdrop, SW_HIDE)
            self.user32.SetWindowLongW(hwnd, GWL_STYLE, CONTAINER_STYLE)
            l, t, r, b = self._normal_placement or (100, 100, 1000, 900)
            self.user32.SetWindowPos(hwnd, 0, l, t, r - l, b - t, 0x0004 | 0x0020 | 0x0040)
            self.fullscreen = False
            enable_dark_titlebar(hwnd)
            self.fit_container_to_content()
        # SDL can re-add a frame to the scrcpy windows after big resizes
        self._enforce_child_styles()
        threading.Timer(0.4, self._enforce_child_styles).start()
        logger.info(f"Fullscreen -> {self.fullscreen}")
        ui = getattr(self, "ui", None)
        if ui:
            try:
                self.ui_calls.put(ui._refresh_view_buttons)
            except Exception:
                pass

    def _enforce_child_styles(self):
        """
        Make sure the scrcpy windows stay borderless child windows. SDL can
        restore its own title bar/frame after large resizes (e.g. leaving
        fullscreen), which showed up as window borders around the screens.
        """
        for key, v in self.viewports.views.items():
            child = v.child
            if not child or not self.user32.IsWindow(child):
                continue
            style = self.user32.GetWindowLongW(child, -16) & 0xFFFFFFFF
            if style & (WS_CAPTION | WS_THICKFRAME) or not style & WS_CHILD:
                logger.info(f"scrcpy {key} window regained a frame (0x{style:08x}) - removing it")
                apply_docked_style(child)
                self.viewports.layout_inner(key, force=True)

    def _dualcpy_in_front(self):
        """Is the foreground window one of ours (stage, split window, panel, backdrop)?"""
        fg = self.user32.GetForegroundWindow()
        if not fg:
            return False
        self.user32.GetAncestor.restype = wintypes.HWND
        root = self.user32.GetAncestor(fg, 2) or fg  # GA_ROOT
        ours = {self.hwnd_container, self.hwnd_backdrop}
        ours.update(v.hwnd for v in self.viewports.views.values())
        ui = getattr(self, "ui", None)
        if ui:
            try:
                ours.add(self.user32.GetParent(ui.window.winfo_id()) or ui.window.winfo_id())
            except Exception:
                pass
        return root in {h for h in ours if h}

    def _install_f11_hook(self):
        """
        Low-level keyboard hook for F11. Unlike a global hotkey it only acts
        (and swallows the key) while DualCPY is in front, so F11 keeps working
        normally in browsers and everything else.
        """
        WH_KEYBOARD_LL, WM_KEYDOWN, WM_SYSKEYDOWN, VK_F11 = 13, 0x0100, 0x0104, 0x7A

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                        ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.c_size_t)]

        HOOKPROC = ctypes.WINFUNCTYPE(self.LRESULT, ctypes.c_int, self.WPARAM, self.LPARAM)
        self.user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, self.WPARAM, self.LPARAM]
        self.user32.CallNextHookEx.restype = self.LRESULT

        def proc(n_code, w_param, l_param):
            try:
                if n_code == 0 and w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    kb = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                    if kb.vkCode == VK_F11 and self._dualcpy_in_front():
                        self.user32.PostMessageW(self.hwnd_container, WM_APP_TOGGLE_FULLSCREEN, 0, 0)
                        return 1  # swallow: don't also send F11 to the game
            except Exception:
                pass
            return self.user32.CallNextHookEx(None, n_code, w_param, l_param)

        self._f11_proc = HOOKPROC(proc)  # keep a reference
        self.user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
        self.user32.SetWindowsHookExW.restype = wintypes.HHOOK
        self.kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        self._f11_hook = self.user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._f11_proc, self.kernel32.GetModuleHandleW(None), 0)
        logger.info(f"F11 fullscreen hook installed: {bool(self._f11_hook)}")

    def _container_placement(self):
        """((x, y), (client_w, client_h)) of the normal (non-fullscreen) container"""
        if not self.hwnd_container or not self.user32.IsWindow(self.hwnd_container):
            return None
        if self.fullscreen and self._normal_placement:
            l, t, r, b = self._normal_placement
            il, it, ir, ib = frame_insets(CONTAINER_STYLE, WS_EX_CONTROLPARENT)
            return [l, t], [r - l - il - ir, b - t - it - ib]
        if self.user32.IsIconic(self.hwnd_container) or self.user32.IsZoomed(self.hwnd_container):
            return None
        rect = wintypes.RECT()
        self.user32.GetWindowRect(self.hwnd_container, ctypes.byref(rect))
        rc = wintypes.RECT()
        self.user32.GetClientRect(self.hwnd_container, ctypes.byref(rc))
        if rc.right < 50 or rc.bottom < 50:
            return None
        return [rect.left, rect.top], [rc.right, rc.bottom]

    def _initial_container_pos(self):
        pos = self.config.get("container_pos", None)
        try:
            x, y = int(pos[0]), int(pos[1])
            # Only reuse it if it's still on a monitor
            MONITOR_DEFAULTTONULL = 0
            pt = wintypes.POINT(x + 50, y + 20)
            self.user32.MonitorFromPoint.restype = wintypes.HANDLE
            if self.user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONULL):
                return x, y
        except (TypeError, ValueError, IndexError):
            pass
        return DEFAULT_CONTAINER_X, DEFAULT_CONTAINER_Y

    # ------------------------------------------------------------------
    # Profiles (saved setups)
    # ------------------------------------------------------------------
    def capture_setup(self):
        """Everything a profile restores"""
        return {
            "view_mode": self.view_mode,
            "screen_gap": self.screen_gap,
            "top_aspect": self.top_aspect,
            "bottom_aspect": self.bottom_aspect,
            "top_crop": list(self.crops["top"]),
            "bottom_crop": list(self.crops["bottom"]),
            "volume": self.volume,
            "audio_mode": self.audio_mode,
            "audio_latency": self.audio_latency,
            "quality": self.quality,
            "thor_screens_off": self.thor_screens_off,
            "bottom_fps": self.bottom_fps,
            "controller_overlay": self.controller_overlay,
            "max_fps": self.max_fps,
            "stage_height": self.stage_height,
            "split": not self.docked,
        }

    def apply_setup(self, data):
        """Apply a saved profile. Only restarts the streams if audio/latency/FPS differ."""
        if not data or not self.scrcpy:
            return
        restart = False
        if "controller_overlay" in data and bool(data["controller_overlay"]) != self.controller_overlay:
            self.set_controller_overlay(bool(data["controller_overlay"]))
        if "thor_screens_off" in data and bool(data["thor_screens_off"]) != self.thor_screens_off:
            self.set_thor_screens_off(bool(data["thor_screens_off"]))
        for key in ("audio_mode", "audio_latency", "quality", "bottom_fps"):
            if key in data and data[key] != getattr(self, key):
                setattr(self, key, data[key])
                self.config.set(key, data[key])
                restart = True
        if "max_fps" in data and int(data["max_fps"]) != self.max_fps:
            self.set_max_fps(int(data["max_fps"]))
            restart = True

        for key in ("top", "bottom"):
            name = self._normalise_aspect(data.get(f"{key}_aspect", getattr(self, f"{key}_aspect")))
            crop = data.get(f"{key}_crop")
            if not (crop and valid_crop(crop)):
                crop = self.scrcpy.preset_crop(key, name)
            if tuple(crop) != tuple(self.crops[key]) or name != getattr(self, f"{key}_aspect"):
                self.set_crop(key, crop, name)

        if data.get("stage_height"):
            self.stage_height = int(data["stage_height"])
        if "screen_gap" in data:
            self.screen_gap = max(0, min(MAX_SCREEN_GAP, int(data["screen_gap"])))
        if data.get("view_mode") in VIEW_MODES:
            self.view_mode = data["view_mode"]
        if "volume" in data:
            self.set_volume(int(data["volume"]))
            self.save_volume()

        want_split = bool(data.get("split", False))
        if want_split != (not self.docked):
            self.toggle_dock()
        else:
            self.fit_container_to_content()

        self.save_layout()
        if restart:
            self.request_restart()

    def run_link_test(self):
        """
        Measure the handheld <-> PC link in the background and hand the
        recommendation to the control panel (which applies it).
        """
        if getattr(self, "_link_test_running", False) or not self.scrcpy:
            return
        adb_bin, serial = self.scrcpy.adb_bin, self.scrcpy.serial
        if not adb_bin or not serial:
            self._notify("No device connected", "error")
            return
        self._link_test_running = True

        def worker():
            from src import link_test
            ui = getattr(self, "ui", None)
            try:
                wireless = self.scrcpy.is_wireless
                if wireless:
                    result = link_test.measure(
                        adb_bin, serial,
                        progress=lambda m: self._notify(m, "info"))
                else:
                    result = None
                key, reason = link_test.recommend(result or {}, wireless, self.max_fps)
                quality = link_test.recommend_quality(result or {}, wireless, self.max_fps, key)
                if ui:
                    self.ui_calls.put(lambda: ui.on_link_test_result(result, key, reason, quality))
            except Exception as e:
                logger.error(f"Link test failed: {e}", exc_info=True)
                self._notify(f"Connection test failed: {e}", "error")
            finally:
                self._link_test_running = False

        threading.Thread(target=worker, daemon=True).start()

    def set_default_setup(self, name):
        self.default_setup = name
        self.config.set("default_profile", name)

    def set_device_profiles_enabled(self, enabled):
        self.device_profiles_enabled = bool(enabled)
        self.config.set("device_profiles_enabled", self.device_profiles_enabled)

    # ------------------------------------------------------------------
    # Controller overlay (experimental)
    # ------------------------------------------------------------------
    def _overlay_active(self):
        return self.controller_overlay and self.docked and self.view_mode in ("both", "bottom")

    def set_controller_overlay(self, on):
        self.controller_overlay = bool(on)
        try:
            self.config.set("controller_overlay", self.controller_overlay)
        except Exception:
            pass
        if self.controller_overlay:
            self._start_overlay_listener()
        elif self._overlay_listener:
            self._overlay_listener.stop()
            self._overlay_listener = None
        self.fit_container_to_content()

    def _start_overlay_listener(self):
        if self._overlay_listener:
            self._overlay_listener.stop()
        adb_bin = getattr(self.scrcpy, "adb_bin", None)
        serial = getattr(self.scrcpy, "serial", None)
        self._overlay_listener = InputListener(adb_bin, serial, on_change=self._overlay_dirty.set)
        self._overlay_listener.start()
        if not self._overlay_thread:
            self._overlay_thread = threading.Thread(target=self._overlay_loop, daemon=True,
                                                    name="ControllerOverlay")
            self._overlay_thread.start()
        self._overlay_dirty.set()

    def _update_overlay_strips(self):
        """Side strips flank the bottom screen (only in Both / Bottom, combined)"""
        strips = None
        bottom = self.view_rects.get("bottom")
        if self._overlay_active() and bottom:
            bx, by, bw, bh = bottom
            sw = int(round(OVERLAY_STRIP * bh))
            strips = {"left": (bx - sw, by, sw, bh), "right": (bx + bw, by, sw, bh)}
        if strips != self.overlay_strips:
            self.overlay_strips = strips
            with self._overlay_lock:
                self._overlay_bitmaps = {}
            # Repaint the whole stage background so strips that are no longer
            # wanted (overlay switched off, view changed) are wiped to black -
            # previously they lingered until something else forced a repaint
            if self.hwnd_container:
                self.user32.InvalidateRect(self.hwnd_container, None, True)
            self._overlay_dirty.set()

    def _overlay_loop(self):
        """Re-render the strips when input or size changes (max ~30 fps)"""
        last = None
        while self.running:
            self._overlay_dirty.wait(0.5)
            self._overlay_dirty.clear()
            strips = self.overlay_strips
            if not strips or not self.hwnd_container:
                continue
            state = self._overlay_listener.snapshot() if self._overlay_listener else {}
            key = (tuple(sorted(strips.items())), tuple(sorted(state.items())))
            if key == last:
                continue
            last = key
            try:
                bitmaps = {}
                for side, (x, y, w, h) in strips.items():
                    img = self._overlay_renderer.render(side, w, h, state)
                    bitmaps[side] = (x, y, w, h, img.tobytes("raw", "BGRX"))
                with self._overlay_lock:
                    self._overlay_bitmaps = bitmaps
                for side, (x, y, w, h) in strips.items():
                    rc = wintypes.RECT(x, y, x + w, y + h)
                    self.user32.InvalidateRect(self.hwnd_container, ctypes.byref(rc), False)
            except Exception as e:
                logger.error(f"Overlay render failed: {e}", exc_info=True)
            time.sleep(1 / 30)

    def _paint_overlay(self, hwnd):
        class PAINTSTRUCT(ctypes.Structure):
            _fields_ = [("hdc", wintypes.HDC), ("fErase", wintypes.BOOL), ("rcPaint", wintypes.RECT),
                        ("fRestore", wintypes.BOOL), ("fIncUpdate", wintypes.BOOL),
                        ("rgbReserved", ctypes.c_byte * 32)]

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                        ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                        ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

        ps = PAINTSTRUCT()
        self.user32.BeginPaint.restype = wintypes.HDC
        hdc = self.user32.BeginPaint(hwnd, ctypes.byref(ps))
        try:
            with self._overlay_lock:
                bitmaps = dict(self._overlay_bitmaps)
            gdi32 = ctypes.windll.gdi32
            gdi32.StretchDIBits.argtypes = [
                wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT, wintypes.DWORD]
            for x, y, w, h, data in bitmaps.values():
                bmi = BITMAPINFOHEADER()
                bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
                bmi.biWidth, bmi.biHeight = w, -h  # top-down
                bmi.biPlanes, bmi.biBitCount = 1, 32
                buf = ctypes.create_string_buffer(data, len(data))
                gdi32.StretchDIBits(hdc, x, y, w, h, 0, 0, w, h, buf, ctypes.byref(bmi), 0, 0x00CC0020)
        finally:
            self.user32.EndPaint(hwnd, ctypes.byref(ps))

    # ------------------------------------------------------------------
    # Volume
    # ------------------------------------------------------------------
    def set_volume(self, volume):
        """PC volume of the stream, 0-100 (Windows per-app volume of scrcpy)"""
        self.volume = max(0, min(100, int(volume)))
        self._volume_applied_pid = None
        threading.Thread(target=self._apply_volume, daemon=True).start()

    def save_volume(self):
        try:
            self.config.set("volume", self.volume)
        except Exception:
            pass

    def _apply_volume(self):
        """Apply the volume to the top scrcpy's audio session if it exists yet"""
        procs = list(getattr(self.scrcpy, "processes", []) or [])
        if not procs:
            return
        pid = procs[0].pid
        if self._volume_applied_pid == pid:
            return
        if app_volume.set_process_volume([p.pid for p in procs], self.volume / 100.0):
            self._volume_applied_pid = pid

    def _resize_split_windows(self):
        s = self.scrcpy
        self.viewports.resize_split("top", s.f_w1, s.f_h1)
        self.viewports.resize_split("bottom", s.f_w2, s.f_h2)

    def _on_split_window_closed(self):
        # Called on the viewport thread; the UI loop performs the re-dock
        self._request_dock = True

    # ------------------------------------------------------------------
    # Crop (aspect) - instant, never restarts the stream
    # ------------------------------------------------------------------
    def set_crop(self, key, crop, aspect_name):
        """Show only `crop` (fractions of the full frame) of one screen. Instant."""
        if not self.scrcpy or not valid_crop(crop):
            return False
        crop = tuple(round(float(c), 4) for c in crop)
        self.crops[key] = crop
        setattr(self, f"{key}_aspect", aspect_name)
        self.scrcpy.crops[key] = crop
        self.viewports.set_crop(key, crop, self.scrcpy.full_aspect(key))
        self.scrcpy.set_scale(self.scrcpy.scale)
        try:
            cfg = self.config.load()
            cfg[f"{key}_crop"] = list(crop)
            cfg[f"{key}_aspect"] = aspect_name
            self.config.save(cfg)
        except Exception as e:
            logger.warning(f"Failed to persist crop: {e}")
        logger.info(f"Crop {key} -> {aspect_name} {crop}")

        if self.docked:
            self.fit_container_to_content()
        else:
            # Keep the split window's width, adjust its height to the new shape
            w, _ = self.viewports.client_size(key)
            l, t, r, b = crop
            aspect = self.scrcpy.full_aspect(key) * (r - l) / (b - t)
            if w > 0:
                self.viewports.resize_split(key, w, int(round(w / aspect)))
        return True

    def capture_rect(self, key=None):
        """Screen rect to capture: the container (combined) or one viewport"""
        if key is None:
            # Bounding box of the visible screens (no surrounding black)
            if not self.hwnd_container or not self.view_rects:
                return None
            pt = wintypes.POINT(0, 0)
            self.user32.ClientToScreen(self.hwnd_container, ctypes.byref(pt))
            xs = [r[0] for r in self.view_rects.values()]
            ys = [r[1] for r in self.view_rects.values()]
            xe = [r[0] + r[2] for r in self.view_rects.values()]
            ye = [r[1] + r[3] for r in self.view_rects.values()]
            return pt.x + min(xs), pt.y + min(ys), pt.x + max(xe), pt.y + max(ye)
        return self.viewports.client_screen_rect(key)

    def bring_to_front(self, key=None):
        """Raise the window being captured so nothing covers it"""
        hwnd = self.hwnd_container if (self.docked or key is None) else self.viewports.views[key].hwnd
        if not hwnd:
            return
        HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
        flags = 0x0001 | 0x0002 | 0x0010  # NOSIZE | NOMOVE | NOACTIVATE
        self.user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)
        self.user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, flags)

    # ------------------------------------------------------------------
    # Stream health / restart
    # ------------------------------------------------------------------
    def _notify(self, msg, kind="info"):
        """Show a status message in the control panel from any thread"""
        ui = getattr(self, "ui", None)
        if ui and ui.window:
            try:
                self.ui_calls.put(lambda: ui.show_status(msg, kind, duration=4.0))
            except Exception:
                pass

    def _check_stream_health(self):
        """
        Auto-reconnect: if a scrcpy process dies (Wi-Fi blip, device sleep),
        restart the streams. Backs off after a few failed attempts.
        """
        if self._restarting or not self.scrcpy or not self.scrcpy.processes:
            return
        dead = self.scrcpy._check_process_alive()
        if dead is None:
            if time.time() - self._last_reconnect > 60:
                self._reconnect_attempts = 0
            return
        if self._reconnect_attempts >= 3:
            return
        if time.time() - self._last_reconnect < 5:
            return
        self._reconnect_attempts += 1
        self._last_reconnect = time.time()
        logger.warning(f"A stream stopped - auto-reconnecting (attempt {self._reconnect_attempts}/3)")
        self._notify(f"Stream dropped - reconnecting ({self._reconnect_attempts}/3)...", "warning")
        self.restart_streams()

    def request_restart(self, delay=1.0):
        """
        Restart the streams shortly after the last settings change, so clicking
        through several options restarts once instead of every time (each
        restart briefly drops audio). Retries if a restart is already running.
        """
        timer = getattr(self, "_restart_timer", None)
        if timer:
            timer.cancel()

        def fire():
            if self._restarting:
                self.request_restart(0.5)
            else:
                self.restart_streams()

        self._restart_timer = threading.Timer(delay, fire)
        self._restart_timer.daemon = True
        self._restart_timer.start()

    def restart_streams(self):
        """
        Restart both scrcpy streams in-process with the current settings
        (FPS, audio). Keeps the container, viewports (and so split-window
        positions), crop and control panel. Runs in a background thread.
        Only one restart can run at a time - a second request while one is
        in progress is ignored (overlapping restarts used to orphan a pair
        of scrcpy processes that kept playing audio).
        """
        if self._restarting or not self.scrcpy:
            return
        serial = self.scrcpy.serial
        if not serial:
            logger.error("restart_streams: no serial")
            return
        self._restarting = True

        def worker():
            try:
                old = self.scrcpy
                try:
                    old.stop()
                except Exception as e:
                    logger.warning(f"Error stopping streams: {e}")

                with self.dock_lock:
                    self.dock.hwnd_top = None
                    self.dock.hwnd_bottom = None
                    self.viewports.release_children()

                new = self._make_manager(old.profile, self.global_scale or old.scale)
                new.serial = serial
                new.connection_mode = old.connection_mode
                new.adb_bin = old.adb_bin or new.adb_bin
                self.scrcpy = new

                new.start_scrcpy(serial=serial)
                self._volume_applied_pid = None
                if self.controller_overlay:
                    self._start_overlay_listener()
                self._notify("Streams restarted", "success")
            except Exception as e:
                logger.error(f"Stream restart failed: {e}", exc_info=True)
                self._notify("Stream restart failed - see logs", "error")
            finally:
                self._last_reconnect = max(self._last_reconnect, time.time())
                self._restarting = False

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    # Dim the handheld's screens while streaming
    # ------------------------------------------------------------------
    # Tested on the Thor (Android 13):
    #  - powering a panel off is no good: --turn-screen-off blacks out the
    #    mirror, and runtime Alt+O makes Android compose the top screen at
    #    ~6 fps; the bottom panel ignores power-off requests entirely
    #  - so both panels are set to minimum brightness (~2 nits) through
    #    DisplayManager.setBrightness(displayId) - what AYN's own slider does
    # The previous brightness of each panel is saved first and restored when
    # switched off, on exit, or - after a crash - the next time DualCPY connects.

    def _adb_shell(self, command, timeout=6):
        adb_bin = getattr(self.scrcpy, "adb_bin", None)
        serial = getattr(self.scrcpy, "serial", None)
        if not adb_bin or not serial:
            return None
        try:
            r = subprocess.run([adb_bin, "-s", serial, "shell", command], capture_output=True,
                               text=True, timeout=timeout, creationflags=CREATE_NO_WINDOW)
            return r.stdout if r.returncode == 0 else None
        except Exception as e:
            logger.warning(f"adb shell failed ({command[:40]}...): {e}")
            return None

    # IDisplayManager binder transactions (read from the Thor's Android 13
    # framework): setBrightness(int displayId, float) / getBrightness(int).
    # The adb shell holds CONTROL_DISPLAY_BRIGHTNESS, so it may call them -
    # this is exactly what AYN's own brightness slider does for display 4.
    TX_SET_BRIGHTNESS = 35
    TX_GET_BRIGHTNESS = 36

    @staticmethod
    def _parse_parcel_float(out):
        """'Result: Parcel(00000000 3eb332b3 ...)' -> 0.35 (None if not a float reply)"""
        import re, struct
        m = re.search(r"Parcel\(\s*([0-9a-f]{8})\s+([0-9a-f]{8})", out or "")
        if not m or m.group(1) != "00000000":
            return None
        value = struct.unpack("<f", struct.pack("<I", int(m.group(2), 16)))[0]
        return value if 0.0 <= value <= 1.0 else None

    def _bottom_display_id(self):
        try:
            return int(self.scrcpy.profile.bottom_display_id)
        except Exception:
            return 4

    def _panel_ids(self):
        ids = []
        for attr in ("top_display_id", "bottom_display_id"):
            try:
                ids.append(int(getattr(self.scrcpy.profile, attr)))
            except Exception:
                pass
        return ids or [0, 4]

    def _dim_thor(self):
        """
        Both panels to minimum brightness. (Powering the top panel off with
        scrcpy's Alt+O was tried first, but Android then only composes that
        screen ~6 times a second, so the mirror stuttered - measured in the
        scrcpy logs. Brightness doesn't affect composition.)
        """
        backup = self.config.get("thor_brightness_backup", None) or {}
        panels = dict(backup.get("panels", {}))
        for disp in self._panel_ids():
            if str(disp) in panels:
                continue
            current = self._parse_parcel_float(
                self._adb_shell(f"service call display {self.TX_GET_BRIGHTNESS} i32 {disp}"))
            if current is None:
                logger.warning(f"Couldn't read display {disp}'s brightness - leaving it alone")
                continue
            panels[str(disp)] = current
        if not panels:
            return False
        backup["panels"] = panels
        self.config.set("thor_brightness_backup", backup)
        logger.info(f"Saved Thor brightness: {backup}")
        cmds = [f"service call display {self.TX_SET_BRIGHTNESS} i32 {d} f 0.0" for d in panels]
        ok = self._adb_shell("; ".join(cmds)) is not None
        logger.info(f"Thor screens dimmed: {ok}")
        return ok

    def _restore_thor_brightness(self):
        backup = self.config.get("thor_brightness_backup", None)
        if not backup:
            return True
        cmds = [f"service call display {self.TX_SET_BRIGHTNESS} i32 {int(d)} f {float(v):.6f}"
                for d, v in backup.get("panels", {}).items()]
        if "bottom_brightness" in backup:  # previous build: bottom only
            cmds.append(f"service call display {self.TX_SET_BRIGHTNESS} i32 "
                        f"{int(backup.get('display', 4))} f {float(backup['bottom_brightness']):.6f}")
        # Older DualCPY Split builds saved settings values instead
        legacy = ("screen_brightness_mode", "screen_brightness", "dual_screen_brightness_level")
        cmds += [f"settings put system {k} {v}" for k, v in backup.items() if k in legacy]
        ok = not cmds or self._adb_shell("; ".join(cmds)) is not None
        if ok:
            cfg = self.config.load()
            cfg.pop("thor_brightness_backup", None)
            self.config.save(cfg)
            logger.info(f"Thor brightness restored: {backup}")
        return ok

    def set_thor_screens_off(self, off):
        """Dim (off=True) or restore the handheld's screens. Instant, no restart."""
        self.thor_screens_off = bool(off)
        try:
            self.config.set("thor_screens_off", self.thor_screens_off)
        except Exception:
            pass

        def worker():
            ok = self._dim_thor() if off else self._restore_thor_brightness()
            if ok:
                self._notify("Thor screens " + ("dimmed" if off else "restored"), "success")
            else:
                self._notify("Couldn't reach the Thor - is it connected?", "error")

        threading.Thread(target=worker, daemon=True).start()

    def _apply_thor_screens_on_connect(self):
        """After connecting: undo a dim left over from a crash, then re-dim if wanted"""
        def worker():
            if self.config.get("thor_brightness_backup", None) and not self.thor_screens_off:
                self._restore_thor_brightness()
            if self.thor_screens_off:
                self._dim_thor()
        threading.Thread(target=worker, daemon=True).start()

    def set_stream_options(self, options):
        """Set several stream options at once with a single stream restart"""
        changed = False
        for key, value in options.items():
            if getattr(self, key, None) != value:
                setattr(self, key, value)
                try:
                    self.config.set(key, value)
                except Exception as e:
                    logger.warning(f"Failed to persist {key}: {e}")
                changed = True
        if changed:
            logger.info(f"Stream options {options}; restarting streams")
            self.request_restart()
        return changed

    def set_stream_option(self, key, value):
        """Persist an audio option (audio_mode, audio_latency) and restart the
        streams so it takes effect."""
        if getattr(self, key, None) == value:
            return
        setattr(self, key, value)
        try:
            self.config.set(key, value)
        except Exception as e:
            logger.warning(f"Failed to persist {key}: {e}")
        logger.info(f"Stream option {key} -> {value}; restarting streams")
        self.request_restart()

    # ------------------------------------------------------------------
    # Live scaling / fit to monitor
    # ------------------------------------------------------------------
    def fit_to_monitor(self):
        """
        Combined: maximise the window (the stage scales the screens to fill it).
        Split: stack the two windows, as large as possible, centred on the monitor.
        """
        if not self.scrcpy:
            return None
        if self.docked:
            if self.fullscreen:
                self.toggle_fullscreen()
            self.stage_height = 100000   # capped to the monitor by fit_container_to_content
            self.fit_container_to_content(center=True)
            rc = wintypes.RECT()
            self.user32.GetClientRect(self.hwnd_container, ctypes.byref(rc))
            self.stage_height = rc.bottom
            return True

        work = monitor_work_area(self.viewports.views["top"].hwnd)
        if not work:
            return None
        wl, wt, wr, wb = work
        avail_w, avail_h = wr - wl, wb - wt
        w1, h1, w2, h2 = self.scrcpy.content_sizes(1.0)
        il, it, ir, ib = frame_insets(WS_OVERLAPPEDWINDOW, 0)
        k = min((avail_w - il - ir) / max(w1, w2), (avail_h - 2 * (it + ib)) / (h1 + h2))
        tw, th, bw, bh = (int(v * k) for v in (w1, h1, w2, h2))
        top_y = wt + (avail_h - (th + bh + 2 * (it + ib))) // 2 + it
        bottom_y = top_y + th + ib + it
        cx = wl + avail_w // 2
        self.viewports.resize_split("top", tw, th, cx - tw // 2, top_y)
        self.viewports.resize_split("bottom", bw, bh, cx - bw // 2, bottom_y)
        logger.info(f"Split windows fitted to monitor {work}")
        return True

    def toggle_dock(self):
        """
        Switch between combined (one window) and split (two windows).
        The scrcpy windows never move between parents here - only their
        viewports do - so the streams and crop are untouched.
        """
        if not self.viewports.ready():
            logger.warning("Cannot toggle dock: viewports not ready")
            return

        with self.dock_lock:
            if self.docked:
                logger.info("Splitting windows")
                if self.fullscreen:
                    self.toggle_fullscreen()
                # Lay both screens out first so both split windows get a sensible size
                saved_mode = self.view_mode
                self.view_mode = "both"
                self.layout_windows(force=True)
                self.view_mode = saved_mode
                self.docked = False
                self.viewports.to_split()
                self.user32.ShowWindow(self.hwnd_container, SW_HIDE)
                self.layout_windows(force=True)
                logger.info("Windows split")
            else:
                logger.info("Combining windows")
                self.user32.ShowWindow(self.hwnd_container, SW_SHOW)
                self.viewports.to_docked(self.hwnd_container)
                self.docked = True
                self.fit_container_to_content()
                logger.info("Windows combined")
        self._request_dock = False

    def show_connection_dialog(self):
        """
        Shows the wireless connection dialog.
        Hides the scrcpy container window first so it doesn't conflict with
        the dialog grab, then restores it when the dialog closes.
        """
        logger.info("Opening wireless connection dialog - hiding scrcpy container")

        # Hide scrcpy container
        if self.hwnd_container:
            self.user32.ShowWindow(self.hwnd_container, SW_HIDE)

        try:
            result = show_wireless_dialog(self._tk_root, self.scrcpy, config=self.config)

            if result == 'connected':
                logger.info("Wireless connection established via dialog")
                return 'connected'
            elif result == 'disconnected':
                logger.info("Device disconnected via dialog")
                return 'disconnected'
            else:
                logger.info("Dialog closed without action")
                return None

        except Exception as e:
            logger.error(f"Error showing wireless dialog: {e}")
            messagebox.showerror(
                "Dialog Error", f"Failed to show wireless connection dialog")
            return None

        finally:
            logger.info("Wireless dialog closed - restoring scrcpy container")
            if self.hwnd_container:
                self.user32.ShowWindow(self.hwnd_container, SW_SHOW)

    def _launch_recovery_editor(self):
        """
        Open the profile editor as a recovery path when scrcpy fails to start.
        """
        if not getattr(self, "_hidden_ctk_root", None):
            self._hidden_ctk_root = _ctk.CTk()
            self._hidden_ctk_root.withdraw()

        DeviceProfileEditorDialog(
            parent=self._hidden_ctk_root,
            custom_store=self.custom_profiles,
            launcher=self,
        ).run()

        self.stop()

    def launch(self):
        self.running = True
        self._wndproc = self._create_wnd_proc()
        show_loading_screen()

        adb_bin = resolve_adb("adb")
        serial = detect_device(adb_bin)

        # No USB device: quietly reconnect a paired handheld over Wi-Fi first
        # (finds its current port via the network, or uses the last address)
        if not serial:
            logger.info("No USB device - trying wireless auto-connect")
            serial, target = auto_connect_wireless(
                adb_bin,
                saved_ip=self.config.get("wireless_connect_ip", None),
                saved_port=self.config.get("wireless_connect_port", None),
                timeout=2.5,
            )
            if serial and target:
                ip, port = target.rsplit(":", 1)
                try:
                    cfg = self.config.load()
                    cfg["wireless_connect_ip"], cfg["wireless_connect_port"] = ip, port
                    self.config.save(cfg)
                except Exception as e:
                    logger.warning(f"Could not save wireless address: {e}")
            if serial:
                logger.info(f"Wireless auto-connect succeeded: {serial}")

        # Still nothing: wait for it (connects by itself the moment the Thor's
        # Wireless debugging comes on); pairing/manual connect from there
        if not serial:
            logger.info("No device found on boot - waiting for one")
            default_boot_profile = BUILTIN_PROFILES.get("ayn_thor") or list(BUILTIN_PROFILES.values())[0]
            self.scrcpy = ScrcpyManager(profile=default_boot_profile, scale=self.launch_scale, max_fps=self.max_fps)
            serial = wait_for_device(self.scrcpy, config=self.config)
            if not serial:
                logger.info("No device - user quit")
                self.stop()
                return
            logger.info(f"Device ready: {serial}")

        if self._tk_root is None:
            _hidden = _ctk.CTk()
            _hidden.withdraw()
            self._tk_root = _hidden
            self._hidden_ctk_root = _hidden

        # Resolve device model name
        _dev_info = get_device_info(adb_bin, serial)
        self.device_model = (_dev_info or {}).get("model", "Unknown Device")

        # Check config for a previously saved profile for this serial
        device_profiles_map = self.config.get("device_profiles", {})
        remembered_key = device_profiles_map.get(serial)
        chosen_profile = None

        device_scales_map = self.config.get("device_scales", {})
        remembered_scale = device_scales_map.get(serial)

        if remembered_key:
            logger.info(f"Remembered profile key for {serial}: '{remembered_key}'")
            # Look up by storage key in custom store first
            all_custom = self.custom_profiles.load_all()

            if remembered_key in all_custom:
                chosen_profile = all_custom[remembered_key]
                logger.info(f"Resolved custom profile: '{chosen_profile.nickname or chosen_profile.name}'")
            # Fall back to builtin key lookup
            elif remembered_key in BUILTIN_PROFILES:
                chosen_profile = BUILTIN_PROFILES[remembered_key]
                logger.info(f"Resolved builtin profile: '{chosen_profile.name}'")
            else:
                logger.warning(
                    f"Remembered key '{remembered_key}' no longer exists - "
                    f"falling back to auto-detection"
                )

        if not self.device_profiles_enabled:
            chosen_profile = BUILTIN_PROFILES.get("ayn_thor") or list(BUILTIN_PROFILES.values())[0]
            logger.info("Device profiles are off - using the built-in AYN Thor profile")

        if chosen_profile is not None:
            # Apply live display specs (same logic as device_selector)
            display_list = get_display_list(adb_bin, serial)

            if display_list and len(display_list) >= 2:
                flipped = chosen_profile.flipped_screens
                top_display    = display_list[1] if flipped else display_list[0]
                bottom_display = display_list[0] if flipped else display_list[1]

                chosen_profile = dc_replace(
                    chosen_profile,
                    top_display_id=str(top_display["id"]),
                    bottom_display_id=str(bottom_display["id"]),
                    top_screen_width=int(top_display["width"]),
                    top_screen_height=int(top_display["height"]),
                    bottom_screen_width=int(bottom_display["width"]),
                    bottom_screen_height=int(bottom_display["height"]),
                )

            logger.info(f"Using remembered profile: '{chosen_profile.name}'")
        else:
            chosen_profile = show_device_selector(
                BUILTIN_PROFILES,
                adb_bin,
                serial,
                custom_store=self.custom_profiles,
                parent_window=self._tk_root,
            )
            # Clear any stale per-device scale
            if chosen_profile is not None:
                try:
                    cfg = self.config.load()
                    device_scales = cfg.get("device_scales", {})

                    if serial in device_scales:
                        device_scales.pop(serial)
                        cfg["device_scales"] = device_scales
                        self.config.save(cfg)
                        logger.info(
                            f"Cleared stale device scale for {serial} "
                            f"so new profile default ({chosen_profile.default_ui_scale}) takes effect"
                        )

                except Exception as e:
                    logger.warning(f"Could not clear stale device scale: {e}")

                remembered_scale = None

        if chosen_profile is None:
            logger.info("No profile selected, exiting")
            self.stop()
            return

        # Keep this serial
        _custom_all = self.custom_profiles.load_all()
        _profile_key = next(
            (k for k, v in _custom_all.items() if v.name == chosen_profile.name
             and v.nickname == chosen_profile.nickname),
            next(
                (k for k, v in BUILTIN_PROFILES.items() if v.name == chosen_profile.name),
                chosen_profile.name,
            ),
        )

        if remembered_scale is not None:
            self.launch_scale = remembered_scale
            logger.info(f"Using remembered scale for {serial}: {remembered_scale}")
        else:
            self.launch_scale = chosen_profile.default_ui_scale
            logger.info(f"Using profile default scale: {chosen_profile.default_ui_scale}")

        self._save_device_profile(serial, _profile_key)

        # Re-instantiate ScrcpyManager with the actual proper profile
        prev_connection_mode = getattr(self.scrcpy, "connection_mode", None) if self.scrcpy else None
        self.scrcpy = self._make_manager(chosen_profile, self.launch_scale)
        self.scrcpy.serial = serial
        self.scrcpy.connection_mode = prev_connection_mode or (
            "wireless" if self.scrcpy.is_wireless else "usb")

        # Compute layout now that profile dimensions are known
        self.global_scale = self.scrcpy.scale
        self.launch_scale = self.scrcpy.scale

        # Stacked + centred default layout
        self._apply_default_layout()
        self._update_viewport_meta()

        logger.info(
            f"Layout set: Top({self.tx}, {self.ty}), Bottom({self.bx}, {self.by}) "
            f"at scale {self.global_scale} for profile '{chosen_profile.name}'"
        )

        # Start scrcpy
        if serial:
            logger.info(f"Starting scrcpy with device: {serial} (mode: {self.scrcpy.connection_mode})")
            try:
                self.scrcpy.start_scrcpy(serial=serial)
            except RuntimeError as e:
                messagebox.showerror(
                    "Scrcpy Failed to Start",
                    str(e) + "\n\nThe profile editor will open so you can fix the extra args.",
                )
                self._launch_recovery_editor()
                return
        else:
            logger.error("No device available to start scrcpy")
            self.stop()
            return

        self._apply_thor_screens_on_connect()
        if self.controller_overlay:
            self._start_overlay_listener()

        # Start background threads
        self._create_container_window()
        threading.Thread(target=self._docking_monitor, daemon=True).start()

        # If we created a hidden bootstrap root for the profile dialog, destroy it
        if hasattr(self, "_hidden_ctk_root") and self._hidden_ctk_root:
            try:
                self._hidden_ctk_root.destroy()
            except Exception:
                pass
            self._hidden_ctk_root = None
            self._tk_root = None

        # Create control panel
        self.ui = CTkUI(self)
        self._tk_root = self.ui.window

        # Apply the default profile once the stage window exists, and put the
        # panel beside the stage rather than on top of it
        self.ui.window.after(1200, self.ui.load_default_profile)
        self.ui.window.after(250, self.ui.fit_height)
        self.ui.window.after(400, self.ui.place_beside_stage)
        self.ui.window.after(1600, self.ui.place_beside_stage)

        self.ui.run()

    def _resize_container_window(self):
        """
        Resize the existing container window to fit the current scrcpy dimensions.
        """
        if not self.hwnd_container:
            logger.warning("_resize_container_window: no container hwnd yet")
            return

        client_w, client_h = self._container_client_size()

        style = WS_OVERLAPPEDWINDOW | WS_VISIBLE | WS_CLIPCHILDREN | WS_CLIPSIBLINGS
        rect  = wintypes.RECT(0, 0, int(client_w), int(client_h))
        self.user32.AdjustWindowRectEx(
            ctypes.byref(rect), style, False, WS_EX_CONTROLPARENT
        )

        new_w = rect.right - rect.left
        new_h = rect.bottom - rect.top

        SWP_NOMOVE = 0x0002
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        SWP_FRAMECHANGED = 0x0020

        self.user32.SetWindowPos(
            self.hwnd_container, 0,
            0, 0, new_w, new_h,
            SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )

        logger.info(f"Container resized to {new_w}x{new_h} (client {int(client_w)}x{int(client_h)})")

    def switch_profile(self, profile):
        """
        Switch the active device profile
        """
        logger.info(f"Switching profile to '{profile.name}'")

        serial = self.scrcpy.serial if self.scrcpy else None
        if not serial:
            logger.error("switch_profile: no active serial - cannot restart scrcpy")
            return

        # Stop current scrcpy
        try:
            self.scrcpy.stop()
        except Exception as e:
            logger.warning(f"Error stopping scrcpy during profile switch: {e}")

        # Clear stale handles - docking monitor will adopt the new windows
        with self.dock_lock:
            self.dock.hwnd_top = None
            self.dock.hwnd_bottom = None
            self.viewports.release_children()

        # make a new ScrcpyManager with the new profile's default scale
        self.launch_scale = profile.default_ui_scale
        self.global_scale = profile.default_ui_scale
        old_mode = getattr(self.scrcpy, "connection_mode", None)
        self.scrcpy = self._make_manager(profile, self.launch_scale)
        self.scrcpy.serial = serial
        self.scrcpy.connection_mode = old_mode

        # setup default centred layout
        self._apply_default_layout()
        self._update_viewport_meta()

        logger.info(
            f"Profile switch layout: Top({self.tx},{self.ty}) "
            f"Bottom({self.bx},{self.by}) scale={self.global_scale}"
        )

        # Start scrcpy
        try:
            try:
                self.scrcpy.start_scrcpy(serial=serial)
            except RuntimeError as e:
                messagebox.showerror(
                    "Scrcpy Failed to Start",
                    str(e) + "\n\nThe profile editor will open so you can fix the extra args.",
                )
                self._launch_recovery_editor()
                return
        except Exception as e:
            logger.error(f"Failed to restart scrcpy after profile switch: {e}")
            return

        self.save_layout()
        self.layout_windows(force=True)

        # Sync UI
        if hasattr(self, "ui") and self.ui:
            def _sync():
                try:
                    self.ui._sync_sliders_from_launcher()
                    self.ui.show_status(f"Profile loaded: {profile.name}", "success")
                except Exception as e:
                    logger.warning(f"UI sync after profile switch failed: {e}")

            self.ui_calls.put(_sync)

    def stop(self):
        """
        Shuts down the application
        1) Saves current layout config
        2) Stops all scrcpy processes
        3) Closes the CTK control panel (stops mainloop)
        4) Closes the container window
        5) Force-exits
        """
        if not self.running:
            return
        self.running = False
        self.save_layout()

        # Stop only OUR scrcpy processes (not any other scrcpy the user runs)
        for proc in list(getattr(self.scrcpy, "processes", []) or []):
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                    creationflags=CREATE_NO_WINDOW,
                    timeout=5,
                )
            except Exception:
                pass

        if self._overlay_listener:
            self._overlay_listener.stop()

        # Give the Thor its screens back before disconnecting
        try:
            if self.config.get("thor_brightness_backup", None):
                self._restore_thor_brightness()
        except Exception as e:
            logger.warning(f"Brightness restore on exit failed: {e}")

        # Shut down the bundled adb server so adb.exe doesn't linger in the
        # background and pile up across launches (upstream issue #11)
        try:
            adb_bin = getattr(self.scrcpy, "adb_bin", None) or resolve_adb("adb")
            serial = getattr(self.scrcpy, "serial", None)
            if adb_bin:
                if serial and getattr(self.scrcpy, "is_wireless", False):
                    subprocess.run([adb_bin, "disconnect", serial], capture_output=True,
                                   creationflags=CREATE_NO_WINDOW, timeout=5)
                subprocess.run([adb_bin, "kill-server"], capture_output=True,
                               creationflags=CREATE_NO_WINDOW, timeout=5)
                logger.info("adb disconnected and server stopped")
        except Exception as e:
            logger.warning(f"adb shutdown failed: {e}")
        # Anything still running in our job (scrcpy, adb) is killed by
        # Windows when this process exits (see process_guard)

        # Stop the CTK main loop
        try:
            if hasattr(self, "ui") and self.ui and self.ui.window:
                self.ui.window.quit()
        except Exception:
            pass

        if self.hwnd_container:
            self.user32.PostMessageW(self.hwnd_container, WM_CLOSE, 0, 0)
        os._exit(0)