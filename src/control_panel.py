# DualCPY - Dual-screen scrcpy docking and control UI for Windows
# Copyright (C) 2026 the_swest
# Contact: Github issues
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

# src/control_panel.py

import os
import sys
import time
import ctypes
import logging
import win32clipboard
import tkinter as tk
import customtkinter as ctk
from PIL import Image, ImageGrab
from io import BytesIO
from ctypes import windll, wintypes

from src.win32_darkmode import enable_dark_titlebar
from src.file_transfer_dialog import FileTransferDialog
from src.ui_constants import (
    BG_COLOUR, PANEL_COLOUR, BORDER_COLOUR, TEXT_COLOUR,
    ACCENT_COLOUR, ACCENT2_COLOUR, TOP_COLOUR, BOTTOM_COLOUR,
    SUCCESS_COLOUR, DANGER_COLOUR, WARNING_COLOUR,
    CALSANS_FAMILY, ICON_PATH, FONT_PATH,
    resource_path, load_calsans, make_font, apply_window_icon,
)
from src.device_profile_editor import DeviceProfileEditorDialog

logger = logging.getLogger(__name__)

# Slider range constraints
# Slider range only; typed values are not clamped (upstream issue #19)
SCREEN_MIN_POS = -2000
SCREEN_MAX_POS = 4000
GLOBAL_SCALE_MIN = 0.1
GLOBAL_SCALE_MAX = 3.0

# Timing
STATUS_MESSAGE_DURATION = 2.0
ERROR_STATUS_DURATION = 3.0
PRESET_CACHE_TIME = 0.5
UPDATE_INTERVAL_MS = 16
LOADING_SCREEN_DURATION = 2000

# Misc
DEFAULT_PRESET_NAME = "NewPreset"
SCALE_CHANGE_THRESHOLD = 0.01

# Win32 SetWindowPos flags
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SW_SHOW = 5

# GDI clipboard/copy constants
CF_BITMAP = 2
SRCCOPY = 0x00CC0020

def fps_label(fps):
    """Frame-rate dropdown label (120 is marked experimental)"""
    return f"{fps} FPS (experimental)" if fps >= 120 else f"{fps} FPS"


# Loading screen
def show_loading_screen():
    """
    Shows a brief splash screen centered dynamically on the user's monitor.
    """
    logger.info("Showing loading screen")
    load_calsans()
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    splash = ctk.CTk()
    splash.iconbitmap()
    splash.title("DualCPY Loading...")

    window_width = 480
    window_height = 190
    screen_width = splash.winfo_screenwidth()
    screen_height = splash.winfo_screenheight()
    center_x = (screen_width - window_width) // 2
    center_y = (screen_height - window_height) // 2.5

    splash.geometry(f"{window_width}x{window_height}+{center_x}+{center_y}")

    splash.resizable(False, False)
    splash.configure(fg_color=BG_COLOUR)

    apply_window_icon(splash)

    # Horizontal layout: DualCPY logo on the left, text block to its right.
    content = ctk.CTkFrame(splash, fg_color="transparent")
    content.pack(expand=True, padx=28)

    try:
        logo_ctk = ctk.CTkImage(Image.open(ICON_PATH), size=(96, 96))
        logo_lbl = ctk.CTkLabel(content, image=logo_ctk, text="")
        logo_lbl._logo_ref = logo_ctk  # keep a reference so it isn't GC'd
        logo_lbl.pack(side="left", padx=(0, 22))
    except Exception as e:
        logger.warning(f"Splash logo failed to load: {e}")

    # Text block sits to the right of the logo, left-aligned within itself.
    text_block = ctk.CTkFrame(content, fg_color="transparent")
    text_block.pack(side="left")

    title_frame = ctk.CTkFrame(text_block, fg_color="transparent")
    title_frame.pack(anchor="w")

    ctk.CTkLabel(
        title_frame,
        text="Dual",
        font=make_font(45, "bold"),
        text_color=ACCENT_COLOUR,
    ).pack(side="left")

    ctk.CTkLabel(
        title_frame,
        text="CPY",
        font=make_font(45, "bold"),
        text_color=ACCENT2_COLOUR,
    ).pack(side="left")

    ctk.CTkLabel(
        text_block,
        text="Starting up...",
        font=make_font(22),
        text_color=TEXT_COLOUR,
    ).pack(anchor="w")

    def _after_idle():
        try:
            splash.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(splash.winfo_id())
            if not hwnd:
                hwnd = splash.winfo_id()
            enable_dark_titlebar(hwnd)
        except Exception:
            pass

        # Clean shutdown sequence
        def _close_safely():
            splash.quit()
            splash.destroy()

        splash.after(LOADING_SCREEN_DURATION, _close_safely)

    splash.after(50, _after_idle)
    splash.mainloop()
    logger.info("Loading screen closed")


# Main UI
class CTkUI:
    """
    Main control panel
    """
    def __init__(self, launcher):
        logger.info("Initializing Control Panel UI")
        self.l = launcher

        # Making sure that calsans is loaded
        load_calsans()

        # Status bar
        self.status_msg = ""
        self.status_type = "info"
        self._status_after_id = None

        # Preset cache
        self._preset_cache = None
        self._preset_cache_time = 0.0

        # Scale-change tracking
        self._original_scale = self.l.global_scale or 0.6
        self._scale_changed = False
        self._slider_refs = {}

        # Main Window
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.window = ctk.CTk()
        self.window.iconbitmap()
        self.window.title("DualCPY Control Panel")
        self.window.configure(fg_color=BG_COLOUR)
        self.window.minsize(360, 640)

        # Panel positioning
        try:
            panel_width = 460
            panel_height = 920

            screen_width = self.window.winfo_screenwidth()
            screen_height = self.window.winfo_screenheight()

            # Divide screen into 3 columns
            one_third = screen_width // 3
            right_third_start = one_third * 2

            # Find the midpoint of the rightmost column, then center the panel in it
            pos_x = right_third_start + (one_third - panel_width) // 2

            # Center vertically, but bump up the height a bit
            pos_y = (screen_height - panel_height) // 3.5

            # Safety checks for smaller resolutions or high Windows DPI scaling
            if pos_x + panel_width > screen_width:
                pos_x = screen_width - panel_width - 20
            if pos_y < 20:
                pos_y = 20

            self.window.geometry(f"{panel_width}x{panel_height}+{pos_x}+{pos_y}")
            self.window.update_idletasks()

        except Exception as e:
            logger.warning(f"Failed auto control UI placement, using fallback: {e}")
            self.window.geometry("460x920")

        apply_window_icon(self.window)

        self.window.protocol("WM_DELETE_WINDOW", self._on_close)


        self._build_ui()


        # Making sure titlebar is dark
        try:
            self.window.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.window.winfo_id())
            if not hwnd:
                hwnd = self.window.winfo_id()
            enable_dark_titlebar(hwnd)
        except Exception as e:
            logger.warning(f"Dark titlebar failed: {e}")

        # Starting the syncing loop
        self.window.after(UPDATE_INTERVAL_MS, self._update_loop)

        logger.info("Control UI initialisation finished")

    # UI construction
    def _button(self, parent, text, command, accent=False, **kw):
        """Consistently styled button"""
        if accent:
            return ctk.CTkButton(
                parent, text=text, command=command,
                fg_color=ACCENT_COLOUR, hover_color=ACCENT2_COLOUR,
                text_color="#ffffff", font=make_font(13, "bold"), **kw,
            )
        return ctk.CTkButton(
            parent, text=text, command=command,
            fg_color=PANEL_COLOUR, hover_color=BORDER_COLOUR,
            border_color=BORDER_COLOUR, border_width=1,
            text_color=TEXT_COLOUR, font=make_font(13), **kw,
        )

    def _dropdown(self, parent, label, values, current, command):
        """Labelled option menu row; returns the StringVar"""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=3)
        row.columnconfigure(1, weight=1)
        ctk.CTkLabel(row, text=label, font=make_font(13), text_color=TEXT_COLOUR,
                     width=110, anchor="w").grid(row=0, column=0, sticky="w")
        var = tk.StringVar(value=current)
        ctk.CTkOptionMenu(
            row, variable=var, values=list(values), command=command,
            fg_color=PANEL_COLOUR, button_color=BORDER_COLOUR,
            button_hover_color=ACCENT_COLOUR, text_color=TEXT_COLOUR,
            dropdown_fg_color=PANEL_COLOUR, dropdown_hover_color=BORDER_COLOUR,
            dropdown_text_color=TEXT_COLOUR,
            font=make_font(13), dropdown_font=make_font(13),
            dynamic_resizing=False,
        ).grid(row=0, column=1, sticky="ew", padx=(10, 0))
        return var

    def _hint(self, text):
        lbl = ctk.CTkLabel(self._scroll, text=text, font=make_font(11),
                           text_color="#7d8494",
                           anchor="w", justify="left", wraplength=380)
        lbl.pack(anchor="w", padx=16, pady=(0, 4))
        return lbl

    def _build_ui(self):
        """Make all widgets inside a frame"""
        from src.launcher import ALLOWED_FPS_VALUES
        from src.scrcpy_manager import (
            ASPECT_PRESETS, AUDIO_MODES, AUDIO_MODE_LABELS,
            AUDIO_LATENCY_MODES, AUDIO_LATENCY_LABELS,
        )
        self._audio_label_to_key = {AUDIO_MODE_LABELS[k]: k for k in AUDIO_MODES}
        self._latency_label_to_key = {AUDIO_LATENCY_LABELS[k]: k for k in AUDIO_LATENCY_MODES}
        self._view_label_to_key = {"Both": "both", "Top": "top", "Bottom": "bottom"}
        self._volume_after = None
        self._volume_save_after = None

        # The scrollable frame fills the entire window and responds to resizing
        self._scroll = ctk.CTkScrollableFrame(
            self.window,
            fg_color=BG_COLOUR,
            scrollbar_button_color=BORDER_COLOUR,
            scrollbar_button_hover_color=ACCENT_COLOUR,
        )
        self._scroll.pack(fill="both", expand=True)
        self._scroll.columnconfigure(0, weight=1)

        # Title bar
        title_row = ctk.CTkFrame(self._scroll, fg_color="transparent")
        title_row.pack(fill="x", padx=16, pady=(18, 2))

        try:
            pil_img = Image.open(ICON_PATH).resize((36, 36))
            self._logo_ctk = ctk.CTkImage(pil_img, size=(36, 36))
            ctk.CTkLabel(title_row, image=self._logo_ctk, text="").pack(side="left")
        except Exception:
            self._logo_ctk = None

        ctk.CTkLabel(
            title_row,
            text="DualCPY Split",
            font=make_font(22, "bold"),
            text_color=TEXT_COLOUR,
        ).pack(side="left", padx=10)

        # Active profile + connection type
        self._current_profile_label = ctk.CTkLabel(
            self._scroll, text="", font=make_font(12),
            text_color=SUCCESS_COLOUR, anchor="w",
        )
        self._current_profile_label.pack(anchor="w", padx=16)
        self._refresh_profile_label()

        # Status line (always present so messages never get lost)
        self._status_label = ctk.CTkLabel(
            self._scroll, text=" ", font=make_font(12),
            text_color=TEXT_COLOUR, anchor="w",
        )
        self._status_label.pack(anchor="w", padx=16, pady=(2, 0))

        # -------------------------------------------------------- View
        self._separator()
        self._section("View")

        self._view_seg = ctk.CTkSegmentedButton(
            self._scroll, values=list(self._view_label_to_key.keys()),
            command=lambda label: self.l.set_view_mode(self._view_label_to_key[label]),
            font=make_font(14, "bold"), height=36,
            fg_color=PANEL_COLOUR, selected_color=ACCENT_COLOUR,
            selected_hover_color=ACCENT2_COLOUR, unselected_color=PANEL_COLOUR,
            unselected_hover_color=BORDER_COLOUR, text_color=TEXT_COLOUR,
        )
        self._view_seg.pack(fill="x", padx=16, pady=(4, 6))

        row = ctk.CTkFrame(self._scroll, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 4))
        row.columnconfigure(0, weight=1)
        row.columnconfigure(1, weight=1)
        self._fullscreen_btn_text = tk.StringVar(value="Fullscreen")
        ctk.CTkButton(
            row, textvariable=self._fullscreen_btn_text, command=self._on_fullscreen,
            fg_color=ACCENT_COLOUR, hover_color=ACCENT2_COLOUR,
            text_color="#ffffff", font=make_font(13, "bold"),
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self._dock_btn_text = tk.StringVar(value=self._dock_label())
        self._dock_btn = ctk.CTkButton(
            row, textvariable=self._dock_btn_text, command=self._on_dock_toggle,
            fg_color=PANEL_COLOUR, hover_color=BORDER_COLOUR,
            border_color=BORDER_COLOUR, border_width=1,
            text_color=TEXT_COLOUR, font=make_font(13),
        )
        self._dock_btn.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        self._button(self._scroll, "Fit to Monitor", self._on_fit_to_monitor) \
            .pack(fill="x", padx=16, pady=(4, 2))

        self._build_slider("screen_gap", "Gap", self.l.screen_gap, 0, 200,
                           color=ACCENT_COLOUR, is_float=False,
                           on_change=self._on_gap_change)

        self._hint("The DualCPY window is always exactly the game area (no black bars): Both stacks "
                   "the screens, Top / Bottom show one screen. Fullscreen centres it on a black "
                   "background that OBS doesn't capture.\n"
                   "Hotkeys (work in-game): Ctrl+Alt+1 Both, Ctrl+Alt+2 Top, Ctrl+Alt+3 Bottom, "
                   "Ctrl+Alt+S cycle, Ctrl+Alt+F fullscreen, Ctrl+Alt+M show/hide this menu.\n"
                   "OBS: Window Capture the \"DualCPY | ...\" window, then right-click it > Transform > "
                   "Edit Transform > Bounding Box Type: \"Scale to inner bounds\", Alignment: Center. "
                   "Switching views is then seamless.")

        # -------------------------------------------------------- Aspect
        self._separator()
        self._section("Aspect (crop black bars)")
        aspects = list(ASPECT_PRESETS.keys())
        self._top_aspect_var = self._dropdown(
            self._scroll, "Top", aspects, self.l.top_aspect,
            lambda v: self._on_aspect("top", v))
        self._bottom_aspect_var = self._dropdown(
            self._scroll, "Bottom", aspects, self.l.bottom_aspect,
            lambda v: self._on_aspect("bottom", v))
        self._hint("Pick the system you're playing to cut the black bars - the screen then takes the "
                   "game's shape. Instant, never restarts the stream.")

        # -------------------------------------------------------- Audio & Stream
        self._separator()
        self._section("Audio & Stream")
        self._build_slider("volume", "Volume", self.l.volume, 0, 100,
                           color=ACCENT_COLOUR, is_float=False,
                           on_change=self._on_volume_change)
        self._audio_var = self._dropdown(
            self._scroll, "Audio output", [AUDIO_MODE_LABELS[k] for k in AUDIO_MODES],
            AUDIO_MODE_LABELS.get(self.l.audio_mode, "PC"),
            lambda v: self._on_stream_option("audio_mode", self._audio_label_to_key[v]))
        self._latency_var = self._dropdown(
            self._scroll, "Latency", [AUDIO_LATENCY_LABELS[k] for k in AUDIO_LATENCY_MODES],
            AUDIO_LATENCY_LABELS.get(self.l.audio_latency, "Low"),
            lambda v: self._on_stream_option("audio_latency", self._latency_label_to_key[v]))
        self._fps_var = self._dropdown(
            self._scroll, "Frame rate", [fps_label(v) for v in ALLOWED_FPS_VALUES],
            fps_label(self.l.max_fps), self._on_fps_change)
        self._hint("Audio output - PC, Device (sound stays on the handheld) or Both (Android 13+).\n"
                   "Latency - Low: smallest delay, full quality (USB / strong Wi-Fi). If sound warps "
                   "or crackles, try Balanced, then Stable.\n"
                   "Frame rate - 120 FPS (experimental) needs a 120 Hz+ monitor and a game running at "
                   "120; it uses ~1.5x the bandwidth. OBS still records at its own rate (usually 60).\n"
                   "Changing these restarts the streams (a second or two).")
        self._button(self._scroll, "Restart Streams", self._on_restart) \
            .pack(fill="x", padx=16, pady=(4, 0))

        # -------------------------------------------------------- Tools
        self._separator()
        self._section("Tools")
        grid = ctk.CTkFrame(self._scroll, fg_color="transparent")
        grid.pack(fill="x", padx=16, pady=(4, 20))
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        self._button(grid, "Screenshot", self.take_screenshot) \
            .grid(row=0, column=0, sticky="ew", padx=(0, 4), pady=4)
        self._button(grid, "File Transfer", self._on_file_transfer) \
            .grid(row=0, column=1, sticky="ew", padx=(4, 0), pady=4)
        self._button(grid, "Wireless", self._on_wireless) \
            .grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=4)
        self._device_profiles_btn = self._button(grid, "Device Profiles", self._on_edit_profiles)
        self._device_profiles_btn.grid(row=1, column=1, sticky="ew", padx=(4, 0), pady=4)

        # -------------------------------------------------------- Profiles
        self._separator()
        self._section("Profiles")
        self._hint("Save your whole setup (view, aspect, gap, volume, audio, latency, FPS, "
                   "split/combined). The default profile (\u2605) loads automatically on start-up.")
        save_row = ctk.CTkFrame(self._scroll, fg_color="transparent")
        save_row.pack(fill="x", padx=16, pady=4)
        save_row.columnconfigure(0, weight=1)
        self._profile_name_var = tk.StringVar(value="")
        ctk.CTkEntry(
            save_row, textvariable=self._profile_name_var,
            placeholder_text="Profile name, e.g. DS streaming",
            fg_color=PANEL_COLOUR, border_color=BORDER_COLOUR,
            text_color=TEXT_COLOUR, font=make_font(13),
        ).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(
            save_row, text="Save", width=80, command=self._on_save_profile,
            fg_color=ACCENT_COLOUR, hover_color=ACCENT2_COLOUR, font=make_font(13),
        ).grid(row=0, column=1)
        self._profile_list = ctk.CTkFrame(self._scroll, fg_color=PANEL_COLOUR, corner_radius=8)
        self._profile_list.pack(fill="x", padx=16, pady=(6, 4))
        self._profile_list.columnconfigure(0, weight=1)
        self.refresh_profile_list()

        # -------------------------------------------------------- Settings
        self._separator()
        self._section("Settings")
        self._device_profiles_var = tk.BooleanVar(value=self.l.device_profiles_enabled)
        ctk.CTkSwitch(
            self._scroll, text="Device profiles (other handhelds / custom screen setups)",
            variable=self._device_profiles_var, command=self._on_device_profiles_toggle,
            progress_color=ACCENT_COLOUR, text_color=TEXT_COLOUR, font=make_font(13),
        ).pack(anchor="w", padx=16, pady=(4, 2))
        self._hint("Off: always uses the built-in AYN Thor profile and never asks which device "
                   "you have. Takes effect next launch.")
        ctk.CTkFrame(self._scroll, fg_color="transparent", height=16).pack()
        self._apply_device_profiles_state()

        self._refresh_view_buttons()

    def _dock_label(self):
        return "Split Windows" if self.l.docked else "Combine Windows"

    def _refresh_profile_label(self):
        try:
            prof = self.l.scrcpy.profile
            name = prof.nickname.strip() if getattr(prof, "nickname", "") else prof.name
            conn = "Wi-Fi" if self.l.scrcpy.is_wireless else "USB"
            self._current_profile_label.configure(text=f"{name}  \u2022  {conn}")
        except Exception:
            pass

    def _refresh_view_buttons(self):
        """Reflect view mode / fullscreen / split state in the panel"""
        try:
            label = {v: k for k, v in self._view_label_to_key.items()}[self.l.view_mode]
            self._view_seg.set(label)
            self._view_seg.configure(state="normal" if self.l.docked else "disabled")
            self._fullscreen_btn_text.set("Exit Fullscreen" if self.l.fullscreen else "Fullscreen")
            self._dock_btn_text.set(self._dock_label())
        except Exception as e:
            logger.debug(f"View button refresh failed: {e}")

    # Layout helpers
    def _separator(self):
        ctk.CTkFrame(
            self._scroll, height=1, fg_color=BORDER_COLOUR
        ).pack(fill="x", padx=16, pady=10)

    def _section(self, label):
        ctk.CTkLabel(
            self._scroll,
            text=label,
            font=make_font(14, "bold"),
            text_color=TEXT_COLOUR,
            anchor="w",
        ).pack(anchor="w", padx=16, pady=(4, 2))

    def _build_slider(
        self, attr, label, initial_val,
        min_val, max_val, *, color, is_float, on_change, clamp_entry=True
    ):
        """
        Build one labeled slider row (label | slider | entry) that is
        fully responsive: the slider expands to fill available width.

        The row registers itself in self._slider_refs so preset loads can
        push new values back without re-building widgets.
        """
        row = ctk.CTkFrame(self._scroll, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=3)
        row.columnconfigure(1, weight=1)   # slider column expands

        ctk.CTkLabel(
            row, text=label,
            font=make_font(13),
            text_color=TEXT_COLOUR,
            width=90, anchor="w",
        ).grid(row=0, column=0, sticky="w")

        # Variables
        def to_norm(v):
            return (v - min_val) / (max_val - min_val)

        def from_norm(n):
            return min_val + n * (max_val - min_val)

        if is_float:
            real_var  = tk.DoubleVar(value=round(float(initial_val), 2))
            entry_str = f"{float(initial_val):.2f}"
        else:
            real_var  = tk.IntVar(value=int(initial_val))
            entry_str = str(int(initial_val))

        norm_var  = tk.DoubleVar(value=max(0.0, min(1.0, to_norm(initial_val))))
        entry_var = tk.StringVar(value=entry_str)

        # Slider
        def _slider_moved(norm_val):
            if is_float:
                real = round(from_norm(norm_val), 2)
                real_var.set(real)
                entry_var.set(f"{real:.2f}")
            else:
                real = int(round(from_norm(norm_val)))
                real_var.set(real)
                entry_var.set(str(real))
            on_change()

        slider = ctk.CTkSlider(
            row, from_=0.0, to=1.0,
            variable=norm_var,
            command=_slider_moved,
            button_color=color,
            button_hover_color=color,
            progress_color=color,
            fg_color=BORDER_COLOUR,
        )
        slider.grid(row=0, column=1, sticky="ew", padx=10)
        # Don't let the scroll wheel change values (it fired while scrolling
        # the panel past the Volume slider); the wheel just scrolls the panel
        try:
            slider._canvas.unbind("<MouseWheel>")
        except Exception:
            pass

        # Entry box
        entry = ctk.CTkEntry(
            row, textvariable=entry_var,
            width=72,
            fg_color=PANEL_COLOUR,
            border_color=BORDER_COLOUR,
            text_color=TEXT_COLOUR,
            font=make_font(13),
        )
        entry.grid(row=0, column=2)

        def _entry_committed(event=None):
            try:
                raw = entry_var.get().strip()
                if is_float:
                    new_val = float(raw)
                    new_val = max(min_val, min(max_val, new_val))
                    real_var.set(round(new_val, 2))
                    entry_var.set(f"{new_val:.2f}")
                else:
                    new_val = int(float(raw))
                    if clamp_entry:
                        new_val = max(min_val, min(max_val, new_val))
                    real_var.set(new_val)
                    entry_var.set(str(new_val))
                norm_var.set(max(0.0, min(1.0, to_norm(new_val))))
                on_change()
            except ValueError:
                self.show_status("Invalid number", "error")
                # Restore last good value
                if is_float:
                    entry_var.set(f"{real_var.get():.2f}")
                else:
                    entry_var.set(str(int(real_var.get())))

        entry.bind("<Return>",   _entry_committed)
        entry.bind("<FocusOut>", _entry_committed)

        # Register so preset loads can sync back
        self._slider_refs[attr] = {
            "real": real_var,
            "norm": norm_var,
            "entry": entry_var,
            "to_norm": lambda v: max(0.0, min(1.0, to_norm(v))),
            "is_float": is_float,
        }

    # Slider / button callbacks
    def _on_gap_change(self):
        ref = self._slider_refs.get("screen_gap")
        if ref:
            self.l.set_screen_gap(int(ref["real"].get()))

    def _on_volume_change(self):
        ref = self._slider_refs.get("volume")
        if not ref:
            return
        vol = int(ref["real"].get())
        # Debounce: apply ~12x/sec while dragging, save once you let go
        if self._volume_after:
            self.window.after_cancel(self._volume_after)
        self._volume_after = self.window.after(80, lambda: self.l.set_volume(vol))
        if self._volume_save_after:
            self.window.after_cancel(self._volume_save_after)
        self._volume_save_after = self.window.after(600, self.l.save_volume)

    def _on_aspect(self, key, name):
        crop = self.l.scrcpy.preset_crop(key, name)
        if self.l.set_crop(key, crop, name):
            from src.scrcpy_manager import aspect_short
            self.show_status(f"{key.title()} screen: {aspect_short(name)}", "success")

    # ------------------------------------------------------------ profiles
    def refresh_profile_list(self):
        for w in self._profile_list.winfo_children():
            w.destroy()
        try:
            profiles = self.l.setups.load_all()
        except Exception as e:
            logger.error(f"Could not load profiles: {e}")
            profiles = {}
        if not profiles:
            ctk.CTkLabel(self._profile_list, text="No profiles yet - set things up, name it, Save.",
                         text_color="#7d8494", font=make_font(12)).pack(pady=10)
            return
        for name in sorted(profiles, key=str.lower):
            is_default = name == self.l.default_setup
            row = ctk.CTkFrame(self._profile_list, fg_color="transparent")
            row.pack(fill="x", padx=6, pady=3)
            row.columnconfigure(1, weight=1)
            ctk.CTkButton(
                row, text="\u2605" if is_default else "\u2606", width=30,
                fg_color="transparent", hover_color=BORDER_COLOUR,
                text_color=WARNING_COLOUR if is_default else "#7d8494",
                font=make_font(16),
                command=lambda n=name: self._on_default_profile(n),
            ).grid(row=0, column=0, padx=(0, 4))
            ctk.CTkLabel(row, text=name, anchor="w", text_color=TEXT_COLOUR,
                         font=make_font(13, "bold" if is_default else "normal")) \
                .grid(row=0, column=1, sticky="w")
            ctk.CTkButton(row, text="Load", width=56, fg_color=ACCENT_COLOUR,
                          hover_color=ACCENT2_COLOUR, font=make_font(12),
                          command=lambda n=name: self._on_load_profile(n)) \
                .grid(row=0, column=2, padx=(4, 4))
            ctk.CTkButton(row, text="Delete", width=60, fg_color="#8b2020",
                          hover_color="#c0392b", font=make_font(12),
                          command=lambda n=name: self._on_delete_profile(n)) \
                .grid(row=0, column=3)

    def _on_save_profile(self):
        name = self._profile_name_var.get().strip()
        if not name:
            self.show_status("Type a name for the profile first", "error")
            return
        try:
            self.l.setups.save_preset(name, self.l.capture_setup())
        except ValueError as e:
            self.show_status(str(e), "error")
            return
        except Exception as e:
            logger.error(f"Profile save failed: {e}", exc_info=True)
            self.show_status("Couldn't save the profile", "error")
            return
        self._profile_name_var.set("")
        self.refresh_profile_list()
        self.show_status(f"Saved profile: {name}", "success")

    def _on_load_profile(self, name):
        data = self.l.setups.get_preset(name)
        if not data:
            self.show_status(f"Profile '{name}' not found", "error")
            return
        self.l.apply_setup(data)
        self._sync_sliders_from_launcher()
        self.show_status(f"Loaded profile: {name}", "success")

    def _on_default_profile(self, name):
        if self.l.default_setup == name:
            self.l.set_default_setup(None)
            self.show_status("No default profile", "info")
        else:
            self.l.set_default_setup(name)
            self.show_status(f"'{name}' loads on start-up", "success")
        self.refresh_profile_list()

    def _on_delete_profile(self, name):
        if self.l.setups.delete_preset(name):
            if self.l.default_setup == name:
                self.l.set_default_setup(None)
            self.refresh_profile_list()
            self.show_status(f"Deleted profile: {name}", "info")

    def load_default_profile(self):
        """Called once at start-up"""
        name = self.l.default_setup
        if not name:
            return
        data = self.l.setups.get_preset(name)
        if data:
            self.l.apply_setup(data)
            self._sync_sliders_from_launcher()
            self.show_status(f"Loaded default profile: {name}", "success", duration=4.0)

    def _on_device_profiles_toggle(self):
        on = bool(self._device_profiles_var.get())
        self.l.set_device_profiles_enabled(on)
        self._apply_device_profiles_state()
        self.show_status("Device profiles " + ("on" if on else "off") + " - applies next launch", "info",
                         duration=4.0)

    def _apply_device_profiles_state(self):
        self._device_profiles_btn.configure(
            state="normal" if self.l.device_profiles_enabled else "disabled")

    def toggle_panel(self):
        """Ctrl+Alt+M: bring the menu up over the stream (even fullscreen), or hide it"""
        w = self.window
        try:
            visible = w.state() == "normal"
            focused = w.focus_displayof() is not None
        except Exception:
            visible, focused = False, False
        if visible and focused:
            w.iconify()
            return
        w.deiconify()
        w.lift()
        w.attributes("-topmost", True)
        w.after(300, lambda: w.attributes("-topmost", False))
        w.focus_force()

    def _on_fullscreen(self):
        self.l.toggle_fullscreen()
        self._refresh_view_buttons()
        if self.l.fullscreen:
            self.show_status("Fullscreen - Ctrl+Alt+F to exit", "success", duration=4.0)

    def _on_fit_to_monitor(self):
        if self.l.fit_to_monitor() is None:
            self.show_status("Could not read the monitor size", "error")
            return
        self._refresh_view_buttons()
        self.show_status("Fitted to monitor", "success")

    def _on_fps_change(self, value):
        try:
            fps = int(value.split()[0])
            if fps == self.l.max_fps:
                return
            self.l.set_max_fps(fps)
            self.show_status(f"Frame rate {fps} FPS - restarting streams...", "info")
            self.l.restart_streams()
        except Exception as e:
            logger.error(f"FPS change error: {e}")

    def _on_stream_option(self, key, value):
        if getattr(self.l, key, None) == value:
            return
        self.show_status("Applying - restarting streams...", "info")
        self.l.set_stream_option(key, value)

    def _on_restart(self):
        self.show_status("Restarting streams...", "info")
        self.l.restart_streams()

    def _on_dock_toggle(self):
        if hasattr(self.l, "toggle_dock"):
            self.l.toggle_dock()
            self._refresh_view_buttons()
            if not self.l.docked:
                self.show_status("Split: move/resize each window freely", "success")

    def _on_wireless(self):
        """Hide CTK window, open wireless dialog, restore window."""
        self.window.withdraw()
        try:
            result = self.l.show_connection_dialog()
            if result == "connected":
                self.show_status("Wireless connected", "success")
            elif result == "disconnected":
                self.show_status("Device disconnected", "info")
        finally:
            self.window.deiconify()
            self.window.lift()

    def _on_edit_profiles(self):
        """Open the custom device profile editor dialog"""
        self.window.withdraw()

        try:
            DeviceProfileEditorDialog(
                parent=self.window,
                custom_store=self.l.custom_profiles,
                launcher=self.l,
            ).run()

        finally:
            self.window.deiconify()
            self.window.lift()

    def _on_file_transfer(self):
        """Open the dual-pane file transfer dialog."""
        adb_bin = getattr(self.l.scrcpy, "adb_bin", None)
        serial = getattr(self.l.scrcpy, "serial", None)

        if not adb_bin or not serial:
            self.show_status("No device connected for file transfer", "error")
            return

        try:
            dlg = FileTransferDialog(
                parent=self.window,
                adb_bin=adb_bin,
                serial=serial,
            )
            dlg.show()
        except Exception as e:
            logger.error(f"Failed to open File Transfer dialog: {e}", exc_info=True)
            self.show_status("Could not open File Transfer", "error")

    def _on_close(self):
        self.l.stop()

    def show_status(
            self, msg,
            status_type="info",
            duration=STATUS_MESSAGE_DURATION,
    ):
        """Display a timed status message in the panel."""
        logger.debug(f"Status [{status_type}]: {msg}")
        self.status_msg = msg
        self.status_type = status_type

        colour_map = {
            "success": SUCCESS_COLOUR,
            "error": DANGER_COLOUR,
            "warning": WARNING_COLOUR,
            "info": TEXT_COLOUR,
        }
        self._status_label.configure(
            text=msg,
            text_color=colour_map.get(status_type, TEXT_COLOUR),
        )

        if self._status_after_id:
            try:
                self.window.after_cancel(self._status_after_id)
            except Exception:
                pass

        # Clear the text once the timer expires (keep the widget packed so the
        # next message is still visible - previously it was pack_forget()-ed
        # and every later status message silently disappeared)
        def _clear_status():
            self._status_label.configure(text=" ")

        self._status_after_id = self.window.after(
            int(duration * 1000),
            _clear_status,
        )

    def force_window_sync(self):
        """Immediately re-apply the combined-window layout"""
        try:
            self.l.layout_windows(force=True)
        except Exception as e:
            logger.error(f"Force window sync error: {e}", exc_info=True)

    def _grab_rect(self, rect):
        """Capture a screen rect (any monitor) as a PIL image, or None"""
        try:
            if not rect or rect[2] <= rect[0] or rect[3] <= rect[1]:
                return None
            return ImageGrab.grab(bbox=rect, all_screens=True).convert("RGB")
        except Exception as e:
            logger.warning(f"Screen capture failed: {e}")
            return None

    def take_screenshot(self):
        try:
            if self.l.docked:
                self.l.bring_to_front(None)
                self.window.update()
                img = self._grab_rect(self.l.capture_rect(None))
                if img is None:
                    self.show_status("Screenshot failed - is the window visible?", "error")
                    return
            else:
                # Split mode: capture each window and stack them like the
                # combined layout (top centred over bottom)
                shots = []
                for key in ("top", "bottom"):
                    self.l.bring_to_front(key)
                    self.window.update()
                    shot = self._grab_rect(self.l.capture_rect(key))
                    if shot is not None:
                        shots.append(shot)
                if not shots:
                    self.show_status("Screenshot failed - are the windows visible?", "error")
                    return
                width = max(im.width for im in shots)
                img = Image.new("RGB", (width, sum(im.height for im in shots)), (0, 0, 0))
                y = 0
                for im in shots:
                    img.paste(im, ((width - im.width) // 2, y))
                    y += im.height

            output = BytesIO()
            img.convert("RGB").save(output, "BMP")
            data = output.getvalue()[14:]
            output.close()
            win32clipboard.OpenClipboard()

            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(
                    win32clipboard.CF_DIB,
                    data
                )

            finally:
                win32clipboard.CloseClipboard()

            logger.info("Screenshot copied to clipboard")

            self.show_status(
                "Screenshot copied to clipboard",
                "success"
            )

        except Exception as e:
            logger.error(
                f"Screenshot failed: {e}",
                exc_info=True
            )

            self.show_status(
                "Screenshot failed",
                "error"
            )

    # Internal helpers
    def _sync_sliders_from_launcher(self, skip=()):
        """Push current launcher state back into the panel widgets"""
        if hasattr(self, "_current_profile_label") and self.l.scrcpy:
            self._refresh_profile_label()
        try:
            from src.scrcpy_manager import AUDIO_MODE_LABELS, AUDIO_LATENCY_LABELS
            self._top_aspect_var.set(self.l.top_aspect)
            self._bottom_aspect_var.set(self.l.bottom_aspect)
            self._fps_var.set(fps_label(self.l.max_fps))
            self._audio_var.set(AUDIO_MODE_LABELS.get(self.l.audio_mode, "PC"))
            self._latency_var.set(AUDIO_LATENCY_LABELS.get(self.l.audio_latency, "Low"))
            for key, val in (("volume", self.l.volume), ("screen_gap", self.l.screen_gap)):
                ref = self._slider_refs.get(key)
                if ref:
                    ref["real"].set(int(val))
                    ref["entry"].set(str(int(val)))
                    ref["norm"].set(ref["to_norm"](int(val)))
        except Exception as e:
            logger.debug(f"Panel sync failed: {e}")
        self._refresh_view_buttons()

    def _update_loop(self):
        try:
            if not self.l.running:
                return

            # Run UI callbacks queued by other threads (Tk isn't thread-safe)
            for _ in range(20):
                try:
                    fn = self.l.ui_calls.get_nowait()
                except Exception:
                    break
                try:
                    fn()
                except Exception as e:
                    logger.warning(f"Queued UI call failed: {e}")

            # A split window was closed -> put the screens back together
            if self.l._request_dock and not self.l.docked:
                self._on_dock_toggle()

            # Keep the combined layout applied (cached; cheap when unchanged)
            if self.l.docked:
                self.l.layout_windows()

            # Keep dock button label in sync with actual state
            expected = self._dock_label()
            if self._dock_btn_text.get() != expected:
                self._refresh_view_buttons()

        except Exception as e:
            logger.error(f"Update loop error: {e}", exc_info=True)
        finally:
            if self.l.running:
                self.window.after(UPDATE_INTERVAL_MS, self._update_loop)

    # Main loop
    def run(self):
        """Enter the CTK main loop, Blocks until the window is closed."""
        logger.info("Entering CTkUI main loop")
        self.window.mainloop()
        logger.info("CTkUI main loop exited")