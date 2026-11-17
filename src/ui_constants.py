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

# src/ui_constants.py

import os
import sys
import logging
import tkinter as tk
import customtkinter as ctk
from ctypes import windll
from PIL import Image, ImageTk

logger = logging.getLogger(__name__)

# Colours
BG_COLOUR      = "#121418"
PANEL_COLOUR   = "#1e2128"
BORDER_COLOUR  = "#2d3139"
TEXT_COLOUR    = "#c8cdd8"
ACCENT_COLOUR  = "#4000D4"
ACCENT2_COLOUR = "#6A4BF4"
TOP_COLOUR     = "#A241ED"
BOTTOM_COLOUR  = "#936aad"
SUCCESS_COLOUR = "#2ecc71"
DANGER_COLOUR  = "#e74c3c"
WARNING_COLOUR = "#f39c12"
MUTED_COLOUR   = "#7d8494"   # hints / secondary text
ON_ACCENT      = "#ffffff"   # text on accent-coloured buttons
OUTLINE_COLOUR = "#2d3139"   # outline of outlined buttons
SELECT_STYLE   = "fill"      # selected / main buttons: "fill" or "glow" (accent border)
SELECT_BORDER  = 2
# Shape (set per theme): corner radius, outline width on outlined widgets,
# section title style ("plain", "band" = tinted strip, "underline")
CORNER         = 6
OUTLINE        = 1
HEADER_STYLE   = "plain"
HEADER_TINT    = "#1e2128"

# ----------------------------------------------------------------------
# Themes
# ----------------------------------------------------------------------
# Colour palettes for the control panel and dialogs. The DS / 3DS themes
# are inspired by those consoles' menus (colours and feel only - no
# Nintendo artwork, fonts or logos). "mode" is customtkinter's appearance
# mode, which also sets the colours of scrollbars, switch tracks etc.
THEME_KEYS = ("BG_COLOUR", "PANEL_COLOUR", "BORDER_COLOUR", "TEXT_COLOUR", "ACCENT_COLOUR",
              "ACCENT2_COLOUR", "SUCCESS_COLOUR", "DANGER_COLOUR", "WARNING_COLOUR",
              "MUTED_COLOUR", "ON_ACCENT", "CORNER", "OUTLINE", "OUTLINE_COLOUR",
              "HEADER_STYLE", "HEADER_TINT", "SELECT_STYLE", "SELECT_BORDER")
_DEFAULT_STYLE = {"CORNER": 6, "OUTLINE": 1, "OUTLINE_COLOUR": None, "HEADER_STYLE": "plain",
                  "HEADER_TINT": "#1e2128", "SELECT_STYLE": "fill", "SELECT_BORDER": 2}
THEMES = {
    "default": {
        "label": "Default (dark)", "mode": "dark",
        "BG_COLOUR": "#121418", "PANEL_COLOUR": "#1e2128", "BORDER_COLOUR": "#2d3139",
        "TEXT_COLOUR": "#c8cdd8", "ACCENT_COLOUR": "#4000D4", "ACCENT2_COLOUR": "#6A4BF4",
        "SUCCESS_COLOUR": "#2ecc71", "DANGER_COLOUR": "#e74c3c", "WARNING_COLOUR": "#f39c12",
        "MUTED_COLOUR": "#7d8494", "ON_ACCENT": "#ffffff",
        "font": ("Cal Sans", "assets/fonts/CalSans-Regular.ttf", 1.0),
        "heading_font": ("Cal Sans", "assets/fonts/CalSans-Regular.ttf", 1.0),
    },
    # DS / PictoChat: PictoChat's pixel lettering everywhere, square boxes with
    # dark-grey 2 px pixel outlines, section titles as solid blue name tags on
    # a dark rule (like the name tags in a PictoChat log), light grey frame
    # around white boxes
    "ds": {
        "label": "DS (PictoChat)", "mode": "light",
        "CORNER": 0, "OUTLINE": 2, "OUTLINE_COLOUR": "#4a4a4a",
        "HEADER_STYLE": "tag", "HEADER_TINT": "#3a6fd8",
        # "Pictochat" by Kirby3 (FontStruct, CC BY-SA 3.0). Its letters are
        # short for their size, so it's scaled up: 13 px labels -> 20 px and
        # 14 px headings -> 24 px, sizes where it's pixel-crisp. Normal weight
        # only (faked bold smears a pixel font).
        "font": ("Pictochat", "assets/fonts/pictochat/pictochat.ttf", 20 / 13),
        "heading_font": ("Pictochat", "assets/fonts/pictochat/pictochat.ttf", 24 / 14),
        "heading_weight": "normal", "body_weight": "normal",
        "BG_COLOUR": "#e3e3e3", "PANEL_COLOUR": "#ffffff", "BORDER_COLOUR": "#9a9a9a",
        "TEXT_COLOUR": "#2a2a2a", "ACCENT_COLOUR": "#3a6fd8", "ACCENT2_COLOUR": "#5c8ce6",
        "SUCCESS_COLOUR": "#2a8f4a", "DANGER_COLOUR": "#c8382f", "WARNING_COLOUR": "#c47a00",
        "MUTED_COLOUR": "#6a6a6a", "ON_ACCENT": "#ffffff",
    },
    # 3DS HOME menu / System Settings: light grey, white rounded buttons with
    # a thin light outline; the selected / main button keeps its white face and
    # gets the 3DS's glowing cyan border and cyan text; cyan-underlined titles
    "3ds": {
        "label": "3DS (HOME menu)", "mode": "light",
        "CORNER": 10, "OUTLINE": 1, "OUTLINE_COLOUR": "#c9cfd6",
        "HEADER_STYLE": "underline", "HEADER_TINT": "#14a0d6",
        "SELECT_STYLE": "glow", "SELECT_BORDER": 3,
        # The 3DS system font is Fontworks' FOT-Rodin (commercial): used if a
        # licensed copy is installed on this PC, else M PLUS Rounded 1c (OFL)
        "prefer_installed": ("FOT-RodinNTLG Pro DB", "FOT-RodinProN DB", "FOT-Rodin Pro DB",
                             "FOT-RodinNTLG Pro B", "FOT-RodinProN B", "FOT-Rodin Pro B"),
        "font": ("Rounded Mplus 1c", "assets/fonts/MPLUSRounded1c-Regular.ttf", 1.1),
        "heading_font": ("Rounded Mplus 1c", "assets/fonts/MPLUSRounded1c-Bold.ttf", 1.1),
        "BG_COLOUR": "#e8eaed", "PANEL_COLOUR": "#ffffff", "BORDER_COLOUR": "#b9c0c8",
        "TEXT_COLOUR": "#3a3f45", "ACCENT_COLOUR": "#12a3dc", "ACCENT2_COLOUR": "#7fd0f0",
        "SUCCESS_COLOUR": "#2e9e55", "DANGER_COLOUR": "#d0403a", "WARNING_COLOUR": "#d98a10",
        "MUTED_COLOUR": "#7f8892", "ON_ACCENT": "#ffffff",
    },
}
for _t in THEMES.values():
    for _k, _v in _DEFAULT_STYLE.items():
        _t.setdefault(_k, _v)
    if not _t["OUTLINE_COLOUR"]:
        _t["OUTLINE_COLOUR"] = _t["BORDER_COLOUR"]


def _installed_font(families):
    """(family, file path) of the first of these fonts installed in Windows, else None"""
    try:
        import winreg
    except ImportError:
        return None
    windir = os.environ.get("WINDIR", r"C:\Windows")
    locations = ((winreg.HKEY_LOCAL_MACHINE, os.path.join(windir, "Fonts")),
                 (winreg.HKEY_CURRENT_USER, os.path.join(os.environ.get("LOCALAPPDATA", ""),
                                                         "Microsoft", "Windows", "Fonts")))
    for family in families:
        for hive, folder in locations:
            try:
                key = winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")
            except OSError:
                continue
            with key:
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, i)
                    except OSError:
                        break
                    i += 1
                    if name.lower().startswith(family.lower()):
                        path = value if os.path.isabs(value) else os.path.join(folder, value)
                        if os.path.isfile(path):
                            return family, path
    return None


CURRENT_THEME = "default"


def apply_theme(name):
    """
    Switch the colour palette everywhere. Every SplitCPY module did
    `from src.ui_constants import BG_COLOUR, ...`, so the new values are
    written into each loaded module too; widgets built afterwards use them.
    Returns the theme dict.
    """
    global CURRENT_THEME
    theme = THEMES.get(name) or THEMES["default"]
    CURRENT_THEME = name if name in THEMES else "default"
    # Font: family for Tk widgets, file for Pillow (the splash), size factor
    global FONT_FAMILY, FONT_PATH, FONT_SCALE, HEADING_FAMILY, HEADING_SCALE
    global HEADING_WEIGHT, BODY_WEIGHT
    FONT_FAMILY, _, FONT_SCALE = theme["font"]
    HEADING_FAMILY, heading_file, HEADING_SCALE = theme["heading_font"]
    HEADING_WEIGHT = theme.get("heading_weight", "bold")
    BODY_WEIGHT = theme.get("body_weight")          # None = as each widget asks
    # The splash is all title / status text, so it uses the heading font
    FONT_PATH = resource_path(heading_file)
    installed = _installed_font(theme.get("prefer_installed", ()))
    if installed:
        FONT_FAMILY = HEADING_FAMILY = installed[0]
        FONT_PATH = installed[1]
        logger.info(f"Theme font: using installed {installed[0]}")
    for mod_name, mod in list(sys.modules.items()):
        if not (mod_name == __name__ or mod_name.startswith("src.")) or mod is None:
            continue
        for key in THEME_KEYS:
            if hasattr(mod, key):
                setattr(mod, key, theme[key])
        if mod_name != __name__ and hasattr(mod, "FONT_PATH"):
            mod.FONT_PATH = FONT_PATH
    try:
        ctk.set_appearance_mode(theme["mode"])
        # Default corner radius for widgets built from now on
        tm = ctk.ThemeManager.theme
        for widget in ("CTkButton", "CTkOptionMenu", "CTkEntry", "CTkFrame", "CTkComboBox",
                       "CTkSegmentedButton", "CTkTextbox", "CTkScrollableFrame"):
            if widget in tm and "corner_radius" in tm[widget]:
                tm[widget]["corner_radius"] = theme["CORNER"]
    except Exception:
        pass
    logger.info(f"Theme: {CURRENT_THEME}")
    return theme


def theme_is_dark():
    return THEMES.get(CURRENT_THEME, THEMES["default"])["mode"] == "dark"

# Font / asset helpers
CALSANS_FAMILY = "Cal Sans"

# Tracks whether CalSans was successfully registered with Win32
_calsans_loaded = False


def resource_path(rel):
    """Resolve a resource path for both dev and PyInstaller contexts"""
    try:
        if hasattr(sys, "_MEIPASS"):
            path = os.path.join(sys._MEIPASS, rel)
            logger.debug(f"Resource path (PyInstaller): {path}")
            return path
        path = os.path.join(os.path.abspath("."), rel)
        logger.debug(f"Resource path (dev): {path}")
        return path
    except Exception as e:
        logger.error(f"Failed to resolve resource path for '{rel}': {e}")
        return rel


ICON_PATH = resource_path("assets/icon.png")
ICO_PATH  = resource_path("assets/icon.ico")
ICONS_DIR = resource_path("assets/icons")
FONT_PATH = resource_path("assets/fonts/CalSans-Regular.ttf")

# Cache loaded icons so identical (name, size, kind) requests reuse one object.
# This also keeps Tk PhotoImage references alive for the lifetime of the app,
# which Treeview rows and Labels require (Tk garbage-collects unreferenced
# images, blanking the widget).
_icon_cache = {}


def load_icon(name, size=16, kind="tk"):
    """Load ``assets/icons/<name>.png`` as a square icon of the given size.

    kind="tk"  -> ImageTk.PhotoImage    (for tk.Label / ttk.Treeview rows)
    kind="ctk" -> customtkinter.CTkImage (for CTkButton / CTkLabel)

    Returns ``None`` when the file is missing or fails to load, so callers can
    fall back to a plain text label until the asset is dropped in.
    """
    key = (name, size, kind)
    if key in _icon_cache:
        return _icon_cache[key]

    path = os.path.join(ICONS_DIR, f"{name}.png")
    if not os.path.exists(path):
        return None

    try:
        img = Image.open(path).convert("RGBA")
        if kind == "ctk":
            obj = ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
        else:
            obj = ImageTk.PhotoImage(img.resize((size, size), Image.LANCZOS))
        _icon_cache[key] = obj
        return obj
    except Exception as e:
        logger.warning(f"Failed to load icon '{name}' from {path}: {e}")
        return None


# Theme font in use (apply_theme sets these)
FONT_FAMILY = CALSANS_FAMILY
FONT_SCALE = 1.0
HEADING_FAMILY = CALSANS_FAMILY
HEADING_SCALE = 1.0
HEADING_WEIGHT = "bold"
BODY_WEIGHT = None
# Bundled fonts registered with Windows (privately, for this process only)
UI_FONT_FILES = ("assets/fonts/CalSans-Regular.ttf", "assets/fonts/pictochat/pictochat.ttf",
                 "assets/fonts/MPLUSRounded1c-Regular.ttf", "assets/fonts/MPLUSRounded1c-Bold.ttf")
_fonts_loaded = set()


def load_calsans():
    """Register the bundled UI fonts (Cal Sans and the theme fonts) with Win32"""
    global _calsans_loaded
    FR_PRIVATE = 0x10
    for rel in UI_FONT_FILES:
        if rel in _fonts_loaded:
            continue
        path = resource_path(rel)
        try:
            if os.path.isfile(path) and windll.gdi32.AddFontResourceExW(path, FR_PRIVATE, 0) > 0:
                _fonts_loaded.add(rel)
                logger.info(f"Font loaded: {path}")
            else:
                logger.warning(f"Font not loaded: {path}")
        except Exception as e:
            logger.warning(f"Font load failed for {path}: {e}")
    _calsans_loaded = "assets/fonts/CalSans-Regular.ttf" in _fonts_loaded
    return _calsans_loaded


def make_font(size, weight="normal"):
    """A CTkFont in the current theme's font (Cal Sans by default); CTk default if not loaded"""
    size = max(8, int(round(size * FONT_SCALE)))
    weight = BODY_WEIGHT or weight
    if _fonts_loaded:
        return ctk.CTkFont(family=FONT_FAMILY, size=size, weight=weight)
    return ctk.CTkFont(size=size, weight=weight)


def make_heading_font(size, weight=None):
    """Font for titles and section headings (the theme's heading font and weight)"""
    weight = weight or HEADING_WEIGHT
    size = max(8, int(round(size * HEADING_SCALE)))
    if _fonts_loaded:
        return ctk.CTkFont(family=HEADING_FAMILY, size=size, weight=weight)
    return ctk.CTkFont(size=size, weight=weight)


def apply_window_icon(window):
    """Apply the SplitCPY icon to any CTk window or Toplevel.

    On Windows the titlebar icon is driven by ``wm_iconbitmap`` with an .ico
    file (``iconphoto`` alone is unreliable for the titlebar there). The catch
    is that CustomTkinter schedules its own default-icon override ~200 ms after
    a window is created - and for CTkToplevel it does so *unconditionally* - so
    any icon we set during construction gets clobbered. We therefore set the
    icon now and re-assert it once that override has fired.
    """
    def _apply():
        try:
            if sys.platform.startswith("win") and os.path.exists(ICO_PATH):
                window.iconbitmap(ICO_PATH)
        except Exception:
            pass
        try:
            img = tk.PhotoImage(file=ICON_PATH)
            window.iconphoto(True, img)
            window._icon_image = img  # keep a ref so Tk doesn't GC it
        except Exception:
            pass

    _apply()
    # Re-assert after CustomTkinter's ~200 ms default-icon override fires.
    try:
        window.after(260, _apply)
    except Exception:
        pass