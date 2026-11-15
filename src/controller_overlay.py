# SplitCPY - live controller overlay (experimental)
# Copyright (C) 2026 SplitCPY contributors
#
# The input-event approach (adb `getevent -lq`, Thor key/axis maps, AYN
# button = KEY_F24 on a separate gpio-keys node) and the overlay idea and
# layout come from scrcpy-thor-ui by tommywaaf
# (https://github.com/tommywaaf/scrcpy-thor-ui, GPL-3.0). Rendering was
# rewritten with Pillow for SplitCPY's stage layout.
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

# src/controller_overlay.py
"""
Draws the handheld's controls (sticks, D-pad, face buttons, shoulder
triggers, Select/Start/Home/Back/AYN) in strips either side of the bottom
screen, lighting up live as they're pressed on the device.
"""

import logging
import subprocess
import threading

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x08000000

# ---------------------------------------------------------------------------
# Input listener
# ---------------------------------------------------------------------------
KEY_MAP = {
    "BTN_SOUTH": "btn_a", "BTN_GAMEPAD": "btn_a", "BTN_A": "btn_a",
    "BTN_EAST": "btn_b", "BTN_B": "btn_b",
    "BTN_NORTH": "btn_x", "BTN_X": "btn_x",
    "BTN_WEST": "btn_y", "BTN_Y": "btn_y",
    "BTN_TL": "l1", "BTN_TR": "r1", "BTN_TL2": "l2", "BTN_TR2": "r2",
    "BTN_SELECT": "select", "BTN_START": "start",
    "BTN_MODE": "home", "KEY_HOME": "home", "KEY_HOMEPAGE": "home",
    "KEY_BACK": "back",
    "KEY_APPSELECT": "ayn", "KEY_F24": "ayn",
    "BTN_THUMBL": "l3", "BTN_THUMBR": "r3",
    "BTN_DPAD_UP": "dpad_up", "BTN_DPAD_DOWN": "dpad_down",
    "BTN_DPAD_LEFT": "dpad_left", "BTN_DPAD_RIGHT": "dpad_right",
}
# code -> (state key, min, max, deadzone)
AXIS_MAP = {
    "ABS_X": ("lstick_x", -32767, 32767, 0.08),
    "ABS_Y": ("lstick_y", -32767, 32767, 0.08),
    "ABS_Z": ("rstick_x", -32767, 32767, 0.08),
    "ABS_RZ": ("rstick_y", -32767, 32767, 0.08),
    "ABS_GAS": ("trigger_r", 0, 32767, 0.02),
    "ABS_BRAKE": ("trigger_l", 0, 32767, 0.02),
}


class InputListener:
    """Streams `adb shell getevent -lq` (all input nodes) into a state dict."""

    def __init__(self, adb_bin, serial, on_change=None):
        self.adb_bin, self.serial, self.on_change = adb_bin, serial, on_change
        self._proc = None
        self._stop = threading.Event()
        self._state = {}
        self._lock = threading.Lock()

    def start(self):
        if not (self.adb_bin and self.serial):
            return False
        threading.Thread(target=self._run, daemon=True, name="ControllerInput").start()
        return True

    def stop(self):
        self._stop.set()
        if self._proc:
            try:
                self._proc.kill()
            except Exception:
                pass

    def snapshot(self):
        with self._lock:
            return dict(self._state)

    def _run(self):
        try:
            from src import process_guard
            self._proc = subprocess.Popen(
                [self.adb_bin, "-s", self.serial, "shell", "getevent -lq"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                text=True, bufsize=1, creationflags=CREATE_NO_WINDOW,
            )
            process_guard.adopt(self._proc)
            logger.info("Controller input listener started")
            for line in iter(self._proc.stdout.readline, ""):
                if self._stop.is_set():
                    break
                if self._parse(line.strip()) and self.on_change:
                    self.on_change()
        except Exception as e:
            logger.error(f"Controller input listener failed: {e}")
        finally:
            if self._proc:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            logger.info("Controller input listener stopped")

    @staticmethod
    def _hex(value):
        try:
            v = int(value, 16)
            return v - (1 << 32) if v & 0x80000000 else v
        except ValueError:
            return None

    def _set(self, key, value):
        if self._state.get(key) != value:
            self._state[key] = value
            return True
        return False

    def _parse(self, line):
        """Returns True if the visible state changed"""
        if not line or "SYN_" in line:
            return False
        parts = line.split()
        if parts and parts[0].endswith(":"):  # "/dev/input/eventN:" prefix
            parts = parts[1:]
        if len(parts) < 3:
            return False
        ev_type, code, value = parts[0], parts[1], parts[2]
        with self._lock:
            if ev_type == "EV_KEY" and code in KEY_MAP:
                return self._set(KEY_MAP[code], value == "DOWN" or value == "REPEAT")
            if ev_type != "EV_ABS":
                return False
            raw = self._hex(value)
            if raw is None:
                return False
            if code == "ABS_HAT0X":
                return self._set("dpad_left", raw < 0) | self._set("dpad_right", raw > 0)
            if code == "ABS_HAT0Y":
                return self._set("dpad_up", raw < 0) | self._set("dpad_down", raw > 0)
            if code in AXIS_MAP:
                key, vmin, vmax, dz = AXIS_MAP[code]
                if vmin < 0:
                    norm = max(-1.0, min(1.0, raw / max(abs(vmin), abs(vmax))))
                else:
                    norm = max(0.0, min(1.0, (raw - vmin) / ((vmax - vmin) or 1)))
                if abs(norm) < dz:
                    norm = 0.0
                norm = round(norm * 20) / 20  # quantise: ignore stick rest noise
                return self._set(key, norm)
        return False


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------
BG = (0, 0, 0)
GREY = (62, 62, 68)
GREY_PRESSED = (120, 120, 132)
HILITE = (96, 96, 104)
PILL = (54, 54, 60)
PILL_PRESSED = (150, 150, 160)
RIM = (24, 24, 28)
LABEL = (220, 220, 224)
LABEL_DIM = (150, 150, 156)
WELL = (40, 40, 46)
LED_OFF = (60, 18, 22)
LED_ON = (240, 56, 56)
FACE = {"btn_x": (62, 134, 232), "btn_a": (216, 70, 76), "btn_b": (242, 192, 76), "btn_y": (108, 192, 102)}
SUPERSAMPLE = 2

_font_cache = {}


def _font(size):
    size = max(6, int(size))
    if size not in _font_cache:
        for name in ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
            try:
                _font_cache[size] = ImageFont.truetype(name, size)
                break
            except OSError:
                continue
        else:
            _font_cache[size] = ImageFont.load_default()
    return _font_cache[size]


def _lighten(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c)


class StripRenderer:
    """Renders one side strip (left or right) for a given size and state."""

    def render(self, side, w, h, st):
        if w < 20 or h < 40:
            return Image.new("RGB", (max(1, w), max(1, h)), BG)
        S = SUPERSAMPLE
        img = Image.new("RGB", (w * S, h * S), BG)
        d = ImageDraw.Draw(img)
        W, H = w * S, h * S
        cx = W // 2
        a = min(W / 3.3, H / 6.4)  # base unit: widest cluster ~3.1a

        y_led, y_pill, y_main, y_second, y_bottom = (H * f for f in (0.06, 0.15, 0.36, 0.66, 0.91))
        if side == "left":
            self._leds(d, cx, y_led, a, ("L1", st.get("l1")), ("L2", st.get("l2") or st.get("trigger_l", 0) > 0.3))
            self._pill(d, cx, y_pill, a, "SELECT", st.get("select"))
            self._stick(d, cx, y_main, a, st.get("lstick_x", 0.0), st.get("lstick_y", 0.0), st.get("l3"))
            self._dpad(d, cx, y_second, a, st)
            self._pill(d, cx, y_bottom, a, "HOME", st.get("home"))
        else:
            self._leds(d, cx, y_led, a, ("R1", st.get("r1")), ("R2", st.get("r2") or st.get("trigger_r", 0) > 0.3))
            self._pill(d, cx, y_pill, a, "START", st.get("start"))
            self._abxy(d, cx, y_main, a, st)
            self._stick(d, cx, y_second, a, st.get("rstick_x", 0.0), st.get("rstick_y", 0.0), st.get("r3"))
            self._pill(d, cx - a * 0.55, y_bottom, a * 0.75, "AYN", st.get("ayn"))
            self._pill(d, cx + a * 0.75, y_bottom, a * 0.75, "BACK", st.get("back"))
        return img.resize((w, h), Image.LANCZOS)

    # -- primitives ---------------------------------------------------------
    @staticmethod
    def _circle(d, x, y, r, fill, outline=None, width=1):
        d.ellipse((x - r, y - r, x + r, y + r), fill=fill, outline=outline, width=width)

    def _leds(self, d, cx, cy, a, left, right):
        r = a * 0.16
        for px, (label, on) in ((cx - a * 1.0, left), (cx + a * 1.0, right)):
            self._circle(d, px, cy, r + a * 0.04, RIM)
            self._circle(d, px, cy, r, LED_ON if on else LED_OFF)
            f = _font(a * 0.22)
            d.text((px, cy + r + a * 0.18), label, fill=LABEL_DIM, font=f, anchor="mm")

    def _pill(self, d, cx, cy, a, label, pressed):
        w, h = a * 1.35, a * 0.38
        box = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
        d.rounded_rectangle((box[0] - 2, box[1] - 1, box[2] + 2, box[3] + 3), radius=h / 2, fill=RIM)
        d.rounded_rectangle(box, radius=h / 2, fill=PILL_PRESSED if pressed else PILL)
        d.text((cx, cy), label, fill=(20, 20, 24) if pressed else LABEL, font=_font(h * 0.5), anchor="mm")

    def _stick(self, d, cx, cy, a, x, y, pressed):
        outer, inner = a * 0.95, a * 0.6
        self._circle(d, cx, cy, outer, WELL, outline=RIM, width=max(2, int(a * 0.05)))
        off = outer - inner - a * 0.04
        px, py = cx + max(-1, min(1, x)) * off, cy + max(-1, min(1, y)) * off
        self._circle(d, px + a * 0.04, py + a * 0.06, inner, RIM)
        self._circle(d, px, py, inner, GREY_PRESSED if pressed else GREY)
        self._circle(d, px - inner * 0.28, py - inner * 0.32, inner * 0.18, HILITE)

    def _dpad(self, d, cx, cy, a, st):
        aw, al = a * 0.5, a * 0.8
        r = a * 0.1
        for box in ((cx - aw / 2, cy - al, cx + aw / 2, cy + al), (cx - al, cy - aw / 2, cx + al, cy + aw / 2)):
            d.rounded_rectangle((box[0] - 2, box[1], box[2] + 2, box[3] + 3), radius=r, fill=RIM)
            d.rounded_rectangle(box, radius=r, fill=GREY)
        arms = {
            "dpad_up": (cx - aw / 2, cy - al, cx + aw / 2, cy - aw / 2),
            "dpad_down": (cx - aw / 2, cy + aw / 2, cx + aw / 2, cy + al),
            "dpad_left": (cx - al, cy - aw / 2, cx - aw / 2, cy + aw / 2),
            "dpad_right": (cx + aw / 2, cy - aw / 2, cx + al, cy + aw / 2),
        }
        for key, box in arms.items():
            if st.get(key):
                d.rounded_rectangle(box, radius=r, fill=GREY_PRESSED)
        self._circle(d, cx, cy, aw * 0.18, _lighten(GREY, 0.8))

    def _abxy(self, d, cx, cy, a, st):
        r = a * 0.42
        g = r * 1.6
        pos = {"btn_x": (cx, cy - g, "X"), "btn_a": (cx + g, cy, "A"),
               "btn_b": (cx, cy + g, "B"), "btn_y": (cx - g, cy, "Y")}
        f = _font(r * 0.95)
        for key, (px, py, label) in pos.items():
            pressed = bool(st.get(key))
            col = FACE[key]
            face = _lighten(col, 1.35) if pressed else _lighten(col, 0.72)
            self._circle(d, px + a * 0.03, py + a * 0.06, r + a * 0.02, RIM)
            self._circle(d, px, py, r, face)
            if pressed:
                self._circle(d, px, py, r, None, outline=(255, 255, 255), width=max(2, int(a * 0.05)))
            d.text((px, py), label, fill=(255, 255, 255), font=f, anchor="mm")
