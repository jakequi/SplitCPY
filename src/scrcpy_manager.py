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

# src/scrcpy_manager.py

import os
import re
import time
import ctypes
import logging
import subprocess
from src.device_detection import resolve_adb
from src import process_guard

# Setup logger for this module
logger = logging.getLogger(__name__)

# Process creation flags and prevent console window from appearing
CREATE_NO_WINDOW = 0x08000000
# HIGH_PRIORITY_CLASS keeps scrcpy from being descheduled under load.
# Important for sustained smoothness when the host CPU has other work.
HIGH_PRIORITY_CLASS = 0x00000080
SCRCPY_CREATION_FLAGS = CREATE_NO_WINDOW | HIGH_PRIORITY_CLASS

# Scrcpy startup retry config
SCRCPY_RETRY_COUNT = 2
SCRCPY_START_DELAY = 1.0

# ADB command timeouts
ADB_CAPTURE_OUTPUT = True
ADB_SERVER_TIMEOUT = 30
ADB_TASKKILL_TIMEOUT = 5
ADB_TCPIP_TIMEOUT = 10
ADB_CONNECT_TIMEOUT = 10
ADB_SERVER_START_RETRIES = 2

# Logging constants
LOG_MULT = 60
LOGFILE_ENCODING = "utf-8"

# Scrcpy default parameters
DEFAULT_MAX_FPS = "60"
DEFAULT_RENDER_DRIVER = "direct3d"
DEFAULT_VIDEO_CODEC = "h264"

# Video bitrate calculation constants
# Bitrate is derived from the *stream* resolution (not the window size),
# in Mbps per megapixel. Wireless gets a much lower budget: the old values
# pushed ~48 Mbps over Wi-Fi, which congests the link and makes scrcpy's
# audio regulator speed up / slow down playback (audible pitch warping).
BITRATE_MBPS_PER_MP_USB = 10
BITRATE_MBPS_PER_MP_WIRELESS = 6
BITRATE_MIN_USB = 8
BITRATE_MIN_WIRELESS = 3
# Legacy names kept for callers that still pass them to default_args()
TOP_BITRATE_MINIMUM = BITRATE_MIN_USB
TOP_BITRATE_SCALE = BITRATE_MBPS_PER_MP_USB
BOTTOM_BITRATE_MINIMUM = BITRATE_MIN_USB
BOTTOM_BITRATE_SCALE = BITRATE_MBPS_PER_MP_USB

# Stream resolution caps (longest edge, px). USB streams at native
# resolution so the window can be resized live without losing sharpness;
# wireless is capped to keep bandwidth (and audio) stable.
WIRELESS_MAX_SIZE_TOP = 1280
WIRELESS_MAX_SIZE_BOTTOM = 960

# Audio
AUDIO_MODES = ("pc", "device", "both")
AUDIO_MODE_LABELS = {"pc": "PC", "device": "Device", "both": "Both"}
# "Latency" profile: audio buffering + Wi-Fi stream size/bitrate together.
# Low is the default - right for USB and strong Wi-Fi. If audio warps or
# crackles, Balanced / Stable trade a little delay for smoothness.
AUDIO_LATENCY_MODES = ("low", "auto", "stable")
AUDIO_LATENCY_LABELS = {"low": "Low", "auto": "Balanced", "stable": "Stable"}
AUDIO_BUFFER_MS = {
    # (usb, wireless)
    # Wi-Fi delivers data in bursts; below ~80 ms scrcpy keeps resampling
    # to stay in sync, which is heard as warping / speeding up / slowing down
    "low": (30, 80),
    "auto": (60, 120),
    "stable": (120, 250),
}
AUDIO_OUTPUT_BUFFER_MS = {"low": 10, "auto": 10, "stable": 15}
# Wi-Fi stream caps per latency profile: (top max size, bottom max size, Mbps per megapixel)
# None = native resolution
WIRELESS_PROFILE = {
    "low": (None, None, 8),
    "auto": (1280, 960, 6),
    "stable": (1024, 800, 4),
}
AUDIO_BIT_RATE = "128K"

# Picture quality = video bitrate multiplier. More bits = sharper fast motion
# and dark scenes (less blocking), but more bandwidth. Max is only worth it
# on USB or very fast Wi-Fi.
QUALITY_MODES = ("standard", "high", "very_high", "max")
QUALITY_LABELS = {"standard": "Standard", "high": "High", "very_high": "Very High", "max": "Max"}
QUALITY_MULTIPLIER = {"standard": 0.7, "high": 1.0, "very_high": 1.4, "max": 2.0}

FULL_CROP = (0.0, 0.0, 1.0, 1.0)


def valid_crop(crop):
    try:
        l, t, r, b = (float(c) for c in crop)
        return 0 <= l < r <= 1 and 0 <= t < b <= 1 and (r - l) > 0.05 and (b - t) > 0.05
    except Exception:
        return False


# Aspect-ratio crop presets, one per ratio: "4:3 (DS, NES, ...)" -> width/height.
# Sorted numerically by ratio; consoles alphabetical inside the brackets.
# The crop is centred and applied on the PC side (instant, no restart).
FULL_SCREEN_LABEL = "Full Screen (no crop)"

# ratio -> consoles / uses that display at that ratio
_RATIO_CONSOLES = {
    (1, 1): ["Square"],
    (3, 2): ["GBA"],
    (4, 3): ["3DS-B", "Arcade", "DC", "DS", "GC", "MD", "N64", "NES", "PS1", "PS2",
             "SNES", "SS", "TG16"],
    (5, 3): ["3DS-T"],
    (8, 7): ["NES/SNES pixel"],
    (10, 9): ["GB", "GBC", "GG"],
    (12, 7): ["VB"],
    (14, 9): ["WS"],
    (16, 9): ["PSP", "Switch", "Vita", "Wide"],
    (16, 10): ["Wide"],
    (20, 19): ["NGP"],
    (31, 27): ["Thor-B"],
    (80, 51): ["Lynx"],
}

# Full names for the acronyms (shown in the panel hint)
CONSOLE_ACRONYMS = (
    "3DS-T/B 3DS top/bottom, DC Dreamcast, GB/GBC/GBA Game Boy/Color/Advance, GC GameCube, "
    "GG Game Gear, MD Mega Drive/Genesis, N64 Nintendo 64, NGP Neo Geo Pocket, "
    "PS1/PS2 PlayStation, SS Sega Saturn, TG16 TurboGrafx-16/PC Engine, Thor-B Thor bottom, "
    "VB Virtual Boy, WS WonderSwan"
)


def _ratio_label(w, h):
    names = sorted(_RATIO_CONSOLES[(w, h)], key=str.lower)
    return f"{w}:{h} ({', '.join(names)})"


# Labels used by the previous version (full console names) -> ratio
_PREVIOUS_NAMES = {
    (1, 1): ["Square"],
    (3, 2): ["Game Boy Advance"],
    (4, 3): ["3DS Bottom", "Arcade", "Dreamcast", "DS", "GameCube", "Genesis / Mega Drive",
             "NES", "Nintendo 64", "PC Engine / TurboGrafx-16", "PlayStation", "PlayStation 2",
             "Saturn", "SNES"],
    (5, 3): ["3DS Top"],
    (8, 7): ["NES / SNES Pixel-Perfect", "NES Pixel-Perfect", "SNES Pixel-Perfect"],
    (10, 9): ["Game Boy", "Game Boy Color", "Game Gear"],
    (12, 7): ["Virtual Boy"],
    (14, 9): ["WonderSwan"],
    (16, 9): ["PS Vita", "PSP", "Switch", "Widescreen"],
    (16, 10): ["Widescreen"],
    (20, 19): ["Neo Geo Pocket"],
    (31, 27): ["Thor Bottom Screen"],
    (80, 51): ["Atari Lynx"],
}


def _previous_label(w, h):
    names = sorted(_PREVIOUS_NAMES[(w, h)], key=str.lower)
    return f"{w}:{h} ({', '.join(names)})"


ASPECT_PRESETS = {FULL_SCREEN_LABEL: None}
for _w, _h in sorted(_RATIO_CONSOLES):
    ASPECT_PRESETS[_ratio_label(_w, _h)] = _w / _h

# Names saved in configs/profiles by earlier versions -> current label
ASPECT_ALIASES = {
    "Full": FULL_SCREEN_LABEL,
    "Full screen": FULL_SCREEN_LABEL,
    "Detected": FULL_SCREEN_LABEL,
}
for (_w, _h), _names in _PREVIOUS_NAMES.items():
    _label = _ratio_label(_w, _h)
    ASPECT_ALIASES[f"{_w}:{_h}"] = _label
    ASPECT_ALIASES[_previous_label(_w, _h)] = _label          # "4:3 (3DS Bottom, ...)"
    for _n in _names:
        ASPECT_ALIASES[f"{_n} ({_w}:{_h})"] = _label           # "DS (4:3)" style
ASPECT_ALIASES.update({
    "4:3 (3DS-B, Arcade, DC, DS, GC, GEN/MD, N64, NES, PCE/TG16, PS1, PS2, SAT, SNES)": _ratio_label(4, 3),
    # first-generation long labels
    "16:9  Switch / PSP / Vita / modern": _ratio_label(16, 9),
    "5:3  3DS top": _ratio_label(5, 3),
    "3:2  GBA": _ratio_label(3, 2),
    "31:27  Thor bottom (native)": _ratio_label(31, 27),
    "4:3  DS / 3DS bottom / NES / SNES / N64 / PS1 / PS2 / GC / Genesis": _ratio_label(4, 3),
    "8:7  NES / SNES (pixel-perfect)": _ratio_label(8, 7),
    "10:9  Game Boy / GBC / Game Gear": _ratio_label(10, 9),
    "20:19  Neo Geo Pocket": _ratio_label(20, 19),
    "12:7  Virtual Boy": _ratio_label(12, 7),
})


def aspect_short(label):
    """'4:3 (DS, NES, ...)' -> '4:3' for status messages"""
    return label if label == FULL_SCREEN_LABEL else label.split(" (")[0]


# Timing delays for process management
DISPLAY_INIT_DELAY = 1.2  # Wait for first display to initialize
SCRCPY_CREATION_DELAY = 0.3  # Check if process survives startup
SCRCPY_RETRY_DELAY = 0.7  # Wait between retry attempts

# Process termination timeouts
PROCESS_TERMINATE_TIMEOUT = 2
SCRCPY_TERMINATE_TIMEOUT = 3

# Wireless connection defaults
DEFAULT_WIRELESS_PORT = 5555

# Main ScrcpyManager class
class ScrcpyManager:
    """
    Manages scrcpy instances for controlling and displaying the Thor's screens
    Handles device detection (USB and wireless), window launching, scaling,
    resolution and process management and shutdown
    """

    def __init__(self, profile, scale=None, scrcpy_bin=None,
                 adb_bin=None, enable_audio_top=True, max_fps=int(DEFAULT_MAX_FPS),
                 audio_mode="pc", audio_latency="low",
                 crops=None, quality="high", screens_off=False):
        """
        Initialize the scrcpy manager.
        """
        self.scale = scale if scale is not None else profile.default_ui_scale
        self.profile = profile
        self.processes = []
        self.serial = None
        self.enable_audio_top = enable_audio_top
        self.connection_mode = None
        # Configurable per-instance FPS cap (override the module default)
        self.max_fps = int(max_fps) if max_fps else int(DEFAULT_MAX_FPS)
        self._scrcpy_log_handles = []

        self.audio_mode = audio_mode if audio_mode in AUDIO_MODES else "pc"
        self.audio_latency = audio_latency if audio_latency in AUDIO_LATENCY_MODES else "low"
        self.quality = quality if quality in QUALITY_MODES else "high"
        # Turn the handheld's own screens off while mirroring (both screens on
        # Android 10-14). They come back on when the stream ends.
        self.screens_off = bool(screens_off)
        # Visible region of each screen as (left, top, right, bottom) fractions
        # of the full frame. Applied on the PC side (viewport), so changing it
        # never restarts the stream.
        self.crops = {"top": FULL_CROP, "bottom": FULL_CROP}
        for key, crop in (crops or {}).items():
            if key in self.crops and valid_crop(crop):
                self.crops[key] = tuple(float(c) for c in crop)

        logger.info(
            f"Initializing ScrcpyManager (scale={self.scale}, audio={self.audio_mode}/"
            f"{self.audio_latency}, fps={max_fps}, crops={self.crops})"
        )

        self.f_w1 = self.f_h1 = self.f_w2 = self.f_h2 = 0
        self.set_scale(self.scale)

        # Locate scrcpy and adb binaries
        self.scrcpy_bin = scrcpy_bin or resolve_adb("scrcpy")
        self.adb_bin = adb_bin or resolve_adb("adb")

        if self.scrcpy_bin:
            logger.info(f"scrcpy binary found: {self.scrcpy_bin}")
        else:
            logger.warning("scrcpy binary not found")

        if self.adb_bin:
            logger.info(f"adb binary found: {self.adb_bin}")
        else:
            logger.warning("adb binary not found")

        # Retry config
        self.scrcpy_retry_count = SCRCPY_RETRY_COUNT
        self.scrcpy_start_delay = SCRCPY_START_DELAY
        logger.debug(f"Retry count: {self.scrcpy_retry_count}, Start delay: {self.scrcpy_start_delay}s")

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------
    @staticmethod
    def _crop_size(width, height, aspect_name):
        """
        Return the (w, h) of the centred region of a width x height screen
        matching the aspect preset. "Full" -> the whole screen.
        """
        ratio = ASPECT_PRESETS.get(aspect_name)
        if not ratio or width <= 0 or height <= 0:
            return width, height
        if width / height > ratio:
            # Screen is wider than the target -> trim the sides
            return int(round(height * ratio)) // 2 * 2, height
        # Screen is taller than the target -> trim top/bottom
        return width, int(round(width / ratio)) // 2 * 2

    def content_sizes(self, scale=1.0):
        """
        Window content sizes (w1, h1, w2, h2) for a given scale, keeping the
        physical size ratio between the screens and applying any aspect crop.
        Sizes are linear in scale, so callers can solve for a scale that fits.
        """
        p = self.profile
        full_w1 = p.top_screen_width * scale
        full_w2 = full_w1 * p.get_screen_width_ratio()

        l1, t1, r1, b1 = self.crops["top"]
        l2, t2, r2, b2 = self.crops["bottom"]
        cw1, ch1 = p.top_screen_width * (r1 - l1), p.top_screen_height * (b1 - t1)
        cw2, ch2 = p.bottom_screen_width * (r2 - l2), p.bottom_screen_height * (b2 - t2)

        w1 = full_w1 * (r1 - l1)
        h1 = w1 * ch1 / cw1
        w2 = full_w2 * (r2 - l2)
        h2 = w2 * ch2 / cw2
        return w1, h1, w2, h2

    def full_aspect(self, key):
        p = self.profile
        if key == "top":
            return p.top_screen_width / p.top_screen_height
        return p.bottom_screen_width / p.bottom_screen_height

    def preset_crop(self, key, aspect_name):
        """Centred crop fractions for an aspect preset ("Full", "4:3", ...)"""
        p = self.profile
        w, h = ((p.top_screen_width, p.top_screen_height) if key == "top"
                else (p.bottom_screen_width, p.bottom_screen_height))
        aspect_name = ASPECT_ALIASES.get(aspect_name, aspect_name)
        cw, ch = self._crop_size(w, h, aspect_name)
        fx, fy = (1 - cw / w) / 2, (1 - ch / h) / 2
        return (fx, fy, 1 - fx, 1 - fy)

    def set_scale(self, scale):
        """Recompute window sizes for a new scale. Takes effect immediately."""
        self.scale = scale
        w1, h1, w2, h2 = self.content_sizes(scale)
        self.f_w1, self.f_h1 = int(w1), int(h1)
        self.f_w2, self.f_h2 = int(w2), int(h2)
        logger.debug(
            f"Window sizes at scale {scale}: top {self.f_w1}x{self.f_h1}, "
            f"bottom {self.f_w2}x{self.f_h2}"
        )

    @property
    def is_wireless(self):
        return bool(self._is_wireless_serial(self.serial))

    def _is_wireless_serial(self, serial):
        """
        Check if a serial is a wireless connection: IP:PORT, or an mDNS
        wireless-debugging name like adb-XXXX._adb-tls-connect._tcp
        """
        if not serial:
            return False
        if "_adb-tls-connect" in serial:
            return True
        return ':' in serial and re.match(r'\d+\.\d+\.\d+\.\d+:\d+', serial)

    def connect_wireless(self, ip_address, port=DEFAULT_WIRELESS_PORT):
        """
        Connect to a device wirelessly via ADB
        """
        if not self.adb_bin:
            logger.error("Cannot connect wirelessly: ADB binary not found")
            return False

        target = f"{ip_address}:{port}"
        logger.info(f"Attempting wireless connection to {target}")

        try:
            result = subprocess.run(
                [self.adb_bin, "connect", target],
                capture_output=ADB_CAPTURE_OUTPUT,
                text=True,
                timeout=ADB_CONNECT_TIMEOUT,
            )

            output = result.stdout.strip() if result.stdout else ""

            if result.returncode == 0 and "connected" in output.lower():
                logger.info(f"Successfully connected to {target}")
                self.serial = target
                self.connection_mode = 'wireless'
                return True
            else:
                # Provide helpful error information
                error_msg = output if output else "Unknown error"
                logger.error(f"Failed to connect to {target}: {error_msg}")

                # Detect if this might be a pairing issue
                if port != DEFAULT_WIRELESS_PORT or "refused" in error_msg.lower() or "failed" in error_msg.lower():
                    logger.warning("=" * LOG_MULT)
                    logger.warning("CONNECTION TROUBLESHOOTING:")
                    logger.warning("=" * LOG_MULT)

                    if port != DEFAULT_WIRELESS_PORT:
                        logger.warning(f"Non-standard port detected ({port})")
                        logger.warning("This may be Android 11+ Wireless Debugging mode.")
                        logger.warning("")
                        logger.warning("For Wireless Debugging (random port like 46303):")
                        logger.warning("  1. On device: Developer Options > Wireless Debugging")
                        logger.warning("  2. Tap 'Pair device with pairing code'")
                        logger.warning("  3. You must PAIR first using: adb pair IP:PAIRING_PORT")
                        logger.warning("  4. Enter the 6-digit pairing code shown on device")
                        logger.warning("  5. After pairing, THEN connect using adb connect")
                        logger.warning("")

                    logger.warning("For legacy TCP/IP mode (port 5555):")
                    logger.warning("  1. Connect device via USB first")
                    logger.warning("  2. Enable wireless mode (button in this app)")
                    logger.warning("  3. Disconnect USB cable")
                    logger.warning("  4. Connect using IP:5555")
                    logger.warning("")
                    logger.warning("Make sure:")
                    logger.warning("  - Device and PC are on the same WiFi network")
                    logger.warning("  - Wireless debugging/ADB over network is enabled on device")
                    logger.warning("  - No firewall is blocking the connection")
                    logger.warning("=" * LOG_MULT)

                return False

        except subprocess.TimeoutExpired:
            logger.error(f"Connection timeout for {target}")
            logger.warning("Connection timed out - device may be unreachable or not on the same network")
            return False
        except Exception as WirelessConnectError:
            logger.error(f"Error connecting wirelessly: {WirelessConnectError}")
            return False

    def pair_wireless(self, ip_address, pairing_port, pairing_code):
        """
        Pair with a device using Android 11+ Wireless Debugging pairing

        This is required for the new wireless debugging feature that uses
        random ports and requires initial pairing with a code
        """
        if not self.adb_bin:
            logger.error("Cannot pair wirelessly: ADB binary not found")
            return False

        target = f"{ip_address}:{pairing_port}"
        logger.info(f"Attempting to pair with {target} using pairing code")

        try:
            # The adb pair command expects the pairing code to be provided interactively
            # or we can pass it via stdin
            process = subprocess.Popen(
                [self.adb_bin, "pair", target],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            # Send the pairing code
            output, _ = process.communicate(input=f"{pairing_code}\n", timeout=ADB_CONNECT_TIMEOUT)

            if process.returncode == 0 and ("successfully paired" in output.lower() or "paired" in output.lower()):
                logger.info(f"Successfully paired with {target}")
                return True
            else:
                logger.error(f"Failed to pair with {target}: {output}")
                return False

        except subprocess.TimeoutExpired:
            logger.error(f"Pairing timeout for {target}")
            return False
        except Exception as PairingError:
            logger.error(f"Error during pairing: {PairingError}")
            return False

    def disconnect_wireless(self, target=None):
        """
        Disconnect a wireless ADB connection
        """
        if not self.adb_bin:
            logger.error("Cannot disconnect: ADB binary not found")
            return False

        disconnect_target = target or self.serial
        if not disconnect_target:
            logger.warning("No target specified for disconnection")
            return False

        logger.info(f"Disconnecting from {disconnect_target}")

        try:
            result = subprocess.run(
                [self.adb_bin, "disconnect", disconnect_target],
                capture_output=ADB_CAPTURE_OUTPUT,
                text=True,
                timeout=ADB_CONNECT_TIMEOUT,
            )

            if result.returncode == 0:
                logger.info(f"Disconnected from {disconnect_target}")
                if disconnect_target == self.serial:
                    self.serial = None
                    self.connection_mode = None
                return True
            else:
                logger.error(f"Failed to disconnect: {result.stdout}")
                return False

        except Exception as DisconnectError:
            logger.error(f"Error disconnecting: {DisconnectError}")
            return False

    def enable_wireless_mode(self, port=DEFAULT_WIRELESS_PORT):
        """
        Enable wireless ADB mode on a USB-connected device
        This switches the device to TCP/IP mode
        """
        if not self.adb_bin:
            logger.error("Cannot enable wireless mode: ADB binary not found")
            return False

        if not self.serial:
            logger.error("Cannot enable wireless mode: No device connected")
            return False

        if self._is_wireless_serial(self.serial):
            logger.warning("Device is already in wireless mode")
            return True

        logger.info(f"Enabling wireless mode on {self.serial} (port {port})")

        try:
            result = subprocess.run(
                [self.adb_bin, "-s", self.serial, "tcpip", str(port)],
                capture_output=ADB_CAPTURE_OUTPUT,
                text=True,
                timeout=ADB_TCPIP_TIMEOUT,
            )

            if result.returncode == 0:
                logger.info(f"Wireless mode enabled on port {port}")
                return True
            else:
                logger.error(f"Failed to enable wireless mode: {result.stdout}")
                return False

        except subprocess.TimeoutExpired:
            logger.error("Timeout enabling wireless mode")
            return False
        except Exception as WirelessEnableError:
            logger.error(f"Error enabling wireless mode: {WirelessEnableError}")
            return False

    def get_device_ip(self):
        """
        Get the IP address of the connected USB device
        """
        if not self.adb_bin or not self.serial:
            logger.error("Cannot get device IP: No device connected")
            return None

        if self._is_wireless_serial(self.serial):
            # Extract IP from wireless serial
            return self.serial.split(':')[0]

        logger.debug("Attempting to retrieve device IP address")

        try:
            # Try to get IP from wlan0 interface
            result = subprocess.run(
                [self.adb_bin, "-s", self.serial, "shell", "ip", "addr", "show", "wlan0"],
                capture_output=ADB_CAPTURE_OUTPUT,
                text=True,
                timeout=ADB_SERVER_TIMEOUT,
            )

            if result.returncode == 0:
                # Parse IP from output (format: "inet 192.168.1.100/24")
                for line in result.stdout.split('\n'):
                    if 'inet ' in line:
                        parts = line.strip().split()
                        for i, part in enumerate(parts):
                            if part == 'inet' and i + 1 < len(parts):
                                ip_with_mask = parts[i + 1]
                                ip = ip_with_mask.split('/')[0]
                                logger.info(f"Device IP address: {ip}")
                                return ip

            logger.warning("Could not find IP address in wlan0 output")
            return None

        except Exception as GetIPError:
            logger.error(f"Error getting device IP: {GetIPError}")
            return None

    @staticmethod
    def default_args(
        width: int,
        height: int,
        bitrate_min: int,
        bitrate_scale: int,
        enable_audio: bool,
    ) -> list[str]:
        """
        Returns the default editable scrcpy args for a single screen.
        Called by profile dialogs to pre-populate the args textboxes.
        Audio flags are NOT part of these: audio is controlled from the
        control panel (Audio output / latency) and added at launch.
        """
        pixels = width * height
        bitrate_mbps = max(bitrate_min, int(round(pixels / 1e6 * bitrate_scale)))

        codec_options = (
            "low-latency=1,"
            "priority=0,"
            "operating-rate=120,"
            "bitrate-mode=2,"
            "complexity=0,"
            "i-frame-interval=10,"
            "intra-refresh-period=60"
        )

        args = [
            f"--video-bit-rate={bitrate_mbps}M",
            f"--render-driver={DEFAULT_RENDER_DRIVER}",
            f"--video-codec={DEFAULT_VIDEO_CODEC}",
            f"--video-codec-options={codec_options}",
            "--no-mipmaps",
            "--no-power-on",
            "--no-cleanup",
            "--print-fps",
        ]
        return args

    def _screen_args(self, display_id, width, height, wireless_cap, custom_args):
        """
        Video args for one screen: the profile's custom args if set, otherwise
        defaults sized for the connection type. Returns (max_size, args).
        """
        cw, ch = width, height
        max_size = max(cw, ch)
        top_cap, bottom_cap, wifi_rate = WIRELESS_PROFILE.get(self.audio_latency, WIRELESS_PROFILE["auto"])
        if self.is_wireless:
            cap = top_cap if wireless_cap == WIRELESS_MAX_SIZE_TOP else bottom_cap
            if cap:
                max_size = min(max_size, cap)
        factor = max_size / max(cw, ch)
        stream_w, stream_h = int(cw * factor), int(ch * factor)

        # More frames per second need more bits to keep each frame as sharp
        # (sub-linear: consecutive frames at 120 FPS are very similar)
        fps_factor = max(1.0, (self.max_fps / 60.0) ** 0.6)
        fps_factor *= QUALITY_MULTIPLIER.get(self.quality, 1.0)

        if custom_args:
            # Audio is managed by the control panel; ignore audio flags here
            args = [a for a in custom_args if not self._is_audio_arg(a)]
        elif self.is_wireless:
            args = self.default_args(stream_w, stream_h, int(BITRATE_MIN_WIRELESS * fps_factor),
                                     wifi_rate * fps_factor, enable_audio=False)
        else:
            args = self.default_args(stream_w, stream_h, int(BITRATE_MIN_USB * fps_factor),
                                     BITRATE_MBPS_PER_MP_USB * fps_factor, enable_audio=False)

        return max_size, list(args)

    @staticmethod
    def _is_audio_arg(arg):
        return arg.startswith("--audio") or arg in ("--no-audio", "--no-audio-playback", "--require-audio")

    def audio_args(self):
        """scrcpy audio flags for the top-screen instance."""
        if self.audio_mode == "device" or not self.enable_audio_top:
            # Leave sound on the handheld only
            return ["--no-audio"]
        usb_ms, wifi_ms = AUDIO_BUFFER_MS.get(self.audio_latency, AUDIO_BUFFER_MS["auto"])
        buffer_ms = wifi_ms if self.is_wireless else usb_ms
        args = [
            f"--audio-bit-rate={AUDIO_BIT_RATE}",
            f"--audio-buffer={buffer_ms}",
            # Output buffer: tiny for Low; slightly larger avoids Windows audio
            # underruns, which scrcpy compensates for by resampling (warping).
            f"--audio-output-buffer={AUDIO_OUTPUT_BUFFER_MS.get(self.audio_latency, 10)}",
        ]
        if self.audio_mode == "both":
            # Android 13+: capture playback while still playing on the device
            args += ["--audio-source=playback", "--audio-dup"]
        return args

    def _window_titles(self):
        name = self.profile.name
        return f"{name} - Top Screen - DualCPY", f"{name} - Bottom Screen - DualCPY"

    def _read_last_log(self):
        """Pull the last few lines from the most recent scrcpy log file."""
        try:
            if not self._scrcpy_log_handles:
                return ""
            handle = self._scrcpy_log_handles[-1]
            handle.flush()
            path = handle.name
            with open(path, "r", errors="replace") as f:
                lines = f.readlines()
            return "".join(lines[-10:]).strip()
        except Exception:
            return ""

    def start_scrcpy(self, serial=None):
        """
        Start both scrcpy windows (top and bottom screen)
        Supports both USB and wireless connections
        """
        use_serial = serial or self.serial
        if not use_serial:
            raise RuntimeError("No device serial available")

        profile = self.profile

        top_title, bottom_title = self._window_titles()

        logger.info("=" * LOG_MULT)
        logger.info(f"Starting scrcpy for device: {use_serial}")
        logger.info(f"Connection mode: {self.connection_mode or 'unknown'}")
        logger.info("=" * LOG_MULT)

        if not self.scrcpy_bin:
            raise RuntimeError("scrcpy binary not found")

        time.sleep(self.scrcpy_start_delay)

        # Launch top screen
        logger.info("Starting top screen window")
        self.serial = use_serial
        top_size, top_args = self._screen_args(
            profile.top_display_id, profile.top_screen_width, profile.top_screen_height,
            WIRELESS_MAX_SIZE_TOP, profile.extra_scrcpy_args_top,
        )
        top_args = top_args + self.audio_args() + ["--gamepad=uhid"]
        if self.screens_off:
            # Without --no-cleanup, scrcpy's on-device cleanup turns the screens
            # back on however the stream ends (close, crash, Wi-Fi drop)
            top_args = [a for a in top_args if a not in ("--no-cleanup", "--turn-screen-off")]
            top_args.append("--turn-screen-off")
        self._start_window(
            use_serial,
            profile.top_display_id,
            top_title,
            top_size,
            extra_args=top_args,
            max_fps_override=self.max_fps,
        )

        # Wait for first display to stabilize
        logger.info("Waiting for top screen window to appear before starting bottom...")
        deadline = time.time() + 15.0
        while time.time() < deadline:
            hwnd = ctypes.windll.user32.FindWindowW(None, top_title)
            if hwnd:
                logger.info(f"Top screen window confirmed (HWND: {hwnd}), starting bottom screen")
                break
            time.sleep(0.25)
        else:
            logger.warning("Top screen window not detected within 15s, starting bottom screen anyway")

        logger.info(f"Waiting for server to stabilise...")
        time.sleep(profile.screen_launch_delay)
        logger.info("Server stabilisation delay finished.")

        # Launch bottom screen
        logger.info("Starting bottom screen window")
        bottom_size, bottom_args = self._screen_args(
            profile.bottom_display_id, profile.bottom_screen_width, profile.bottom_screen_height,
            WIRELESS_MAX_SIZE_BOTTOM, profile.extra_scrcpy_args_bottom,
        )
        bottom_args = bottom_args + ["--no-audio", "--gamepad=disabled"]
        self._start_window(
            use_serial,
            profile.bottom_display_id,
            bottom_title,
            bottom_size,
            extra_args=bottom_args,
        )

        logger.info("All scrcpy windows started successfully")
        logger.info("=" * LOG_MULT)

    def _start_window(
            self,
            serial,
            display_id,
            window_title,
            max_size,
            extra_args: list = None,
            max_fps_override=None,
    ):
        """
        Start a single scrcpy window with retry logic.
        extra_args are the fully editable per-screen scrcpy flags
        (bitrate, codec, audio, etc.). Locked args (serial, display-id,
        window-title, max-size, max-fps) are always applied separately.
        """
        label = f"'{window_title}'"
        logger.debug(f"Preparing to start {label} (display {display_id})")

        cmd = [
            self.scrcpy_bin,
            "--serial",       serial,
            "--display-id",   display_id,
            "--window-title", window_title,
            "--max-size",     f"{int(max_size)}",
            "--max-fps",      str(max_fps_override if max_fps_override is not None else self.max_fps),
            *(extra_args or []),
        ]

        logger.debug(f"Command: {' '.join(cmd)}")

        # Retry logic
        last_exc = None
        for attempt in range(1, self.scrcpy_retry_count + 1):
            try:
                logger.info(f"Starting {label} (attempt {attempt}/{self.scrcpy_retry_count})")

                # IMPORTANT: NEVER use subprocess.PIPE here without a
                # drain thread - scrcpy's stdout/stderr fill the OS
                # pipe buffer (~64 KB on Windows) within seconds, then
                # scrcpy blocks on its next write and the stream stalls.
                #
                # Instead we hand scrcpy a real file handle. The OS
                # writes lazily to disk so there is no buffer-fill
                # deadlock, and we get scrcpy's --print-fps output in
                # a per-instance log file we can tail live with
                # `Get-Content -Wait logs\scrcpy_<role>_*.log` to see
                # the actual on-screen FPS.
                role = "top" if "Top" in window_title else "bottom"
                ts = time.strftime("%Y%m%d_%H%M%S")
                log_dir = "logs"
                try:
                    os.makedirs(log_dir, exist_ok=True)
                except Exception:
                    pass
                log_path = os.path.join(log_dir, f"scrcpy_{role}_{ts}.log")
                try:
                    log_handle = open(log_path, "wb", buffering=0)
                    self._scrcpy_log_handles.append(log_handle)
                    stdout_target = log_handle
                    stderr_target = subprocess.STDOUT
                    logger.info(f"Scrcpy {role} output -> {log_path}")
                except Exception as ScrcpyLogOpenError:
                    logger.warning(
                        f"Could not open scrcpy log file '{log_path}': "
                        f"{ScrcpyLogOpenError} - falling back to DEVNULL"
                    )
                    stdout_target = subprocess.DEVNULL
                    stderr_target = subprocess.DEVNULL

                # Disable SDL2's vsync wait inside scrcpy. With vsync
                # ON, SDL_RenderPresent blocks until the next monitor
                # refresh - on high-refresh-rate monitors (e.g. 144 /
                # 165 / 240 Hz) the timing slots don't align with the
                # 60 Hz incoming frame stream, and scrcpy ends up
                # skipping frames. Setting SDL_RENDER_VSYNC=0 makes
                # the renderer present every decoded frame as soon as
                # it arrives - the small chance of tearing on a
                # 200+ Hz panel is essentially invisible.
                child_env = os.environ.copy()
                child_env["SDL_RENDER_VSYNC"] = "0"
                # Strip PyInstaller bootloader env vars so a frozen-
                # parent's _MEIPASS isn't inherited by scrcpy.
                for _k in (
                    "_MEIPASS2",
                    "_PYI_APPLICATION_HOME_DIR",
                    "_PYI_PARENT_PROCESS_LEVEL",
                    "_PYI_SPLASH_IPC",
                ):
                    child_env.pop(_k, None)

                proc = subprocess.Popen(
                    cmd,
                    creationflags=SCRCPY_CREATION_FLAGS,
                    stdout=stdout_target,
                    stderr=stderr_target,
                    env=child_env,
                )
                process_guard.adopt(proc)

                # Quick check if process survives startup
                time.sleep(SCRCPY_CREATION_DELAY)
                if proc.poll() is not None:
                    log_tail = self._read_last_log()
                    raise RuntimeError(
                        f"Scrcpy {label} process died immediately (exit code: {proc.poll()})"
                        + (f"\n\nScrcpy output:\n{log_tail}" if log_tail else "")
                    )

                # Start process hidden
                self.processes.append(proc)
                logger.info(
                    f"Scrcpy {label} window started successfully (PID: {proc.pid})"
                )
                return proc

            except Exception as ScrcpyStartError:
                last_exc = ScrcpyStartError
                logger.warning(f"Scrcpy {label} start attempt "
                               f"{attempt}/{self.scrcpy_retry_count} failed: {ScrcpyStartError}")
                if attempt < self.scrcpy_retry_count:
                    logger.debug(f"Waiting {SCRCPY_RETRY_DELAY}s before retry...")
                    time.sleep(SCRCPY_RETRY_DELAY)

        # All attempts failed
        logger.error(f"All {self.scrcpy_retry_count} attempts to start scrcpy {label} window failed")
        raise last_exc

    # Check if process is alive
    def _check_process_alive(self):
        """
        Check if any processes that were tracked have died

        Returns the first process that is no longer alive or None if all are running
        """
        for processName, process in enumerate(self.processes):
            try:
                if process.poll() is not None:
                    logger.warning(f"Process {processName} "
                                   f"(PID: {process.pid}) is no longer alive (exit code: {process.poll()})")
                    return process
            except Exception as ProcessCheckError:
                logger.error(f"Error checking process {processName} status: {ProcessCheckError}")
                return process
        return None

    # Stop Process
    def stop(self):
        """
        Stop and cleanup all scrcpy windows politely, then forcefully if needed.

        Shuts down in the following order:
        1) Gracefully terminate (SIGTERM)
        2) Wait for proceesses to exit
        3) Force kill if needed (taskkill)
        4) Device-side cleanup (kill scrcpy-server, app_process)
        5) Remove ADB port forwards

        Safe to call multiple times
        """
        logger.info("=" * LOG_MULT)
        logger.info("Stopping ScrcpyManager")
        logger.info("=" * LOG_MULT)

        if not self.processes:
            logger.info("No scrcpy processes to stop")
            return

        logger.info(f"Stopping {len(self.processes)} scrcpy process(es)")

        # Attempt graceful termination
        for processName, process in enumerate(list(self.processes)):
            try:
                if process.poll() is None:
                    logger.debug(f"Terminating process {processName} (PID: {process.pid})")
                    process.terminate()
                else:
                    logger.debug(f"Process {processName} (PID: {process.pid}) already stopped")
            except Exception as TerminationError:
                logger.warning(f"Error terminating process {processName}: {TerminationError}")

        # Wait for graceful exit, then force-kill remaining processes
        logger.debug("Waiting for processes to terminate gracefully...")
        for processName, process in enumerate(list(self.processes)):
            try:
                if process.poll() is None:
                    process.wait(timeout=PROCESS_TERMINATE_TIMEOUT)
                    logger.debug(f"Process {processName} (PID: {process.pid}) terminated gracefully")
            except subprocess.TimeoutExpired:
                logger.warning(
                    f"Process {processName} (PID: {process.pid}) did not terminate, forcing kill"
                )
                try:
                    process.kill()
                    logger.debug(f"Process {processName} killed with p.kill()")
                except Exception as ProcessKillError:
                    logger.error(f"Failed to kill process {processName}: {ProcessKillError}")
                    # Last resort -> taskkill
                    try:
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                            capture_output=ADB_CAPTURE_OUTPUT,
                            timeout=ADB_TASKKILL_TIMEOUT,
                        )
                        logger.debug(f"Process {processName} killed with taskkill")
                    except Exception as TaskKillError:
                        logger.error(f"Taskkill also failed for process {processName}: {TaskKillError}")
            except Exception as ProcessKillWaitingError:
                logger.error(f"Error waiting for process {processName}: {ProcessKillWaitingError}")

        # Clear process list
        process_count = len(self.processes)
        self.processes = []
        logger.info(f"Cleared {process_count} process(es) from tracking list")

        # Close any per-instance scrcpy log files we opened
        for handle in self._scrcpy_log_handles:
            try:
                handle.close()
            except Exception:
                pass
        self._scrcpy_log_handles = []

        # Device-side cleanup (scrcpy server and app_process)
        if self.serial and self.adb_bin:
            logger.info(f"Performing device-side cleanup for {self.serial}")

            # Kill scrcpy server
            try:
                logger.debug("Killing scrcpy-server on device")
                result = subprocess.run(
                    [
                        self.adb_bin,
                        "-s",
                        self.serial,
                        "shell",
                        "pkill",
                        "-f",
                        "scrcpy-server",
                    ],
                    capture_output=ADB_CAPTURE_OUTPUT,
                    timeout=SCRCPY_TERMINATE_TIMEOUT,
                )
                if result.returncode == 0:
                    logger.debug("scrcpy-server killed successfully")
                else:
                    logger.debug(f"pkill scrcpy-server returned {result.returncode} (may not have been running)")
            except subprocess.TimeoutExpired:
                logger.warning("Timeout killing scrcpy-server")
            except Exception as ScrcpyKillError:
                logger.warning(f"Error killing scrcpy-server: {ScrcpyKillError}")

            # Kill app_process
            try:
                logger.debug("Killing app_process on device")
                result = subprocess.run(
                    [
                        self.adb_bin,
                        "-s",
                        self.serial,
                        "shell",
                        "pkill",
                        "-f",
                        "app_process",
                    ],
                    capture_output=ADB_CAPTURE_OUTPUT,
                    timeout=SCRCPY_TERMINATE_TIMEOUT,
                )
                if result.returncode == 0:
                    logger.debug("app_process killed successfully")
                else:
                    logger.debug(f"pkill app_process returned {result.returncode} (may not have been running)")
            except subprocess.TimeoutExpired:
                logger.warning("Timeout killing app_process")
            except Exception as AppProcessKillError:
                logger.warning(f"Error killing app_process: {AppProcessKillError}")

            # Remove port forwards
            try:
                logger.debug("Removing ADB port forwards")
                subprocess.run(
                    [self.adb_bin, "-s", self.serial, "forward", "--remove-all"],
                    capture_output=ADB_CAPTURE_OUTPUT,
                    timeout=SCRCPY_TERMINATE_TIMEOUT,
                )
                logger.debug("Port forwards removed")
            except Exception as PortForwardsKillError:
                logger.warning(f"Error removing port forwards: {PortForwardsKillError}")

            # Remove all reverse forwards
            try:
                logger.debug("Removing ADB reverse forwards")
                subprocess.run(
                    [self.adb_bin, "-s", self.serial, "reverse", "--remove-all"],
                    capture_output=ADB_CAPTURE_OUTPUT,
                    timeout=SCRCPY_TERMINATE_TIMEOUT,
                )
                logger.debug("Reverse forwards removed")
            except Exception as ReverseForwardsKillError:
                logger.warning(f"Error removing reverse forwards: {ReverseForwardsKillError}")

            logger.info("Device-side cleanup complete")
        else:
            if not self.serial:
                logger.debug("Skipping device cleanup: no serial")
            if not self.adb_bin:
                logger.debug("Skipping device cleanup: no ADB binary")

        logger.info("ScrcpyManager stopped successfully")
        logger.info("=" * LOG_MULT)