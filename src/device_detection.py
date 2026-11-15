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

# src/device_detection.py

import re
import os
import sys
import shutil
import logging
import subprocess

logger = logging.getLogger(__name__)

ADB_INFO_TIMEOUT = 5
ADB_DISPLAY_TIMEOUT = 10

ADB_SERVER_TIMEOUT = 30

CREATE_NO_WINDOW = 0x08000000

# Map key names to Android prop keys
DEVICE_PROPS = {
    "model":        "ro.product.model",
    "manufacturer": "ro.product.manufacturer",
    "android":      "ro.build.version.release",
    "api_level":    "ro.build.version.sdk",
    "cpu_abi":      "ro.product.cpu.abi",
    "device":       "ro.product.device",
}


def resolve_adb(name):
    """
    Locate a bundled binary (scrcpy / adb)

    Search order:
      1. PyInstaller bundle (sys._MEIPASS/bin/) when running as a frozen exe
      2. ./bin next to the running script or exe
      3. The current working directory's bin/
      4. System PATH
    """
    logger.debug(f"Resolving binary: {name}")

    candidates = []

    # PyInstaller _MEIPASS unpacked bundle
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, "bin", f"{name}.exe"))

    # ./bin next to the script/exe
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
    else:
        exe_dir = os.path.dirname(os.path.abspath(__file__))
        # src/ -> project root
        exe_dir = os.path.dirname(exe_dir)
    candidates.append(os.path.join(exe_dir, "bin", f"{name}.exe"))

    # cwd
    candidates.append(os.path.join(os.getcwd(), "bin", f"{name}.exe"))

    for path in candidates:
        if os.path.exists(path):
            logger.info(f"Found {name} at: {path}")
            return path

    # System PATH
    found = shutil.which(name)
    if found:
        logger.info(f"Found {name} in system PATH: {found}")
        return found

    logger.warning(f"Binary '{name}' not found (checked: {candidates})")
    return None

def detect_device(adb_bin):
    logger.info("Starting device detection with ADB")

    if not adb_bin:
        logger.error("Cannot detect device: ADB binary not found")
        return None

    # Start ADB server
    try:
        subprocess.run(
            [adb_bin, "start-server"],
            capture_output=True,
            text=True,
            timeout=ADB_SERVER_TIMEOUT,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception as e:
        logger.error(f"Failed to start ADB server: {e}")
        return None

    # Try to get devices
    try:
        result = subprocess.run(
            [adb_bin, "devices"],
            capture_output=True,
            text=True,
            timeout=ADB_SERVER_TIMEOUT,
            creationflags=CREATE_NO_WINDOW,
        )

        if result.returncode != 0:
            logger.error(f"'adb devices' failed with code {result.returncode}")
            return None

        lines = result.stdout.strip().splitlines()

        for line in lines[1:]:
            parts = line.split()

            if len(parts) < 2:
                continue

            serial = parts[0]
            status = parts[1]

            if status == "device":
                logger.info(f"Device detected: {serial}")
                return serial

            if status == "unauthorized":
                logger.warning(
                    f"Unauthorized device: {serial} "
                    f"(check device for authorization prompt)"
                )

        logger.warning("No authorized devices found")
        return None

    except subprocess.TimeoutExpired:
        logger.error("'adb devices' timed out")
        return None

    except Exception as e:
        logger.error(f"Device detection failed: {e}")
        return None

def get_device_info(adb_bin, serial):
    """
    Get device properties with adb shell and getprop
    """
    info = {}

    for key, prop in DEVICE_PROPS.items():
        try:
            result = subprocess.run(
                [adb_bin, "-s", serial, "shell", "getprop", prop],
                capture_output=True,
                text=True,
                timeout=ADB_INFO_TIMEOUT,
                creationflags=CREATE_NO_WINDOW,
            )
            if result.returncode == 0:
                info[key] = result.stdout.strip()
            else:
                logger.warning(f"getprop {prop} returned code {result.returncode}")
                info[key] = None
        except subprocess.TimeoutExpired:
            logger.warning(f"Timeout fetching {prop}")
            info[key] = None
        except Exception as e:
            logger.error(f"Error fetching {prop}: {e}")
            info[key] = None

    logger.debug(f"Device info: {info}")
    return info

def get_display_list(adb_bin, serial):
    """
    Gets display IDs and resolutions from the mViewports line in dumpsys display
    """
    try:
        result = subprocess.run(
            [adb_bin, "-s", serial, "shell",
             "dumpsys display | grep mViewports"],
            capture_output=True,
            text=True,
            timeout=ADB_DISPLAY_TIMEOUT,
            creationflags=CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        logger.warning("Timeout fetching display list")
        return []
    except Exception as e:
        logger.error(f"Error fetching display list: {e}")
        return []

    displays = []

    # Each display appears as: displayId=N, ..., deviceWidth=W, deviceHeight=H
    matches = re.findall(r'displayId=(\d+).*?deviceWidth=(\d+),\s*deviceHeight=(\d+)', result.stdout)

    for display_id, width, height in matches:
        displays.append({
            "id": display_id,
            "width": int(width),
            "height": int(height),
        })

    logger.info(f"Displays found: {displays}")
    return displays

# ----------------------------------------------------------------------
# Wireless quick-connect helpers (SplitCPY)
# ----------------------------------------------------------------------
def list_ready_devices(adb_bin):
    """Serials of devices in the 'device' state (authorised and online)"""
    try:
        result = subprocess.run(
            [adb_bin, "devices"], capture_output=True, text=True,
            timeout=ADB_INFO_TIMEOUT, creationflags=CREATE_NO_WINDOW,
        )
    except Exception as e:
        logger.debug(f"adb devices failed: {e}")
        return []
    serials = []
    for line in (result.stdout or "").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def adb_connect(adb_bin, target, timeout=6):
    """`adb connect ip:port`; True if connected (or already connected)"""
    try:
        result = subprocess.run(
            [adb_bin, "connect", target], capture_output=True, text=True,
            timeout=timeout, creationflags=CREATE_NO_WINDOW,
        )
        out = (result.stdout or "").lower()
        ok = "connected to" in out and "cannot" not in out and "failed" not in out
        logger.info(f"adb connect {target}: {out.strip()}")
        return ok
    except Exception as e:
        logger.info(f"adb connect {target} failed: {e}")
        return False


def mdns_connect_targets(adb_bin):
    """
    ip:port of paired devices advertising wireless debugging on the network.
    Android picks a new port whenever Wireless debugging is re-enabled, so this
    is how we find the current one without the user typing it in.
    """
    try:
        result = subprocess.run(
            [adb_bin, "mdns", "services"], capture_output=True, text=True,
            timeout=ADB_INFO_TIMEOUT, creationflags=CREATE_NO_WINDOW,
        )
    except Exception as e:
        logger.debug(f"adb mdns services failed: {e}")
        return []
    return re.findall(r"_adb-tls-connect\._tcp\.?\s+(\d+\.\d+\.\d+\.\d+:\d+)", result.stdout or "")


def auto_connect_wireless(adb_bin, saved_ip=None, saved_port=None, timeout=6.0, progress=None):
    """
    Get a paired handheld connected over Wi-Fi without any dialog:
      1. adb often auto-connects paired devices it discovers - just wait for it
      2. connect to any device advertising wireless debugging (current port)
      3. connect to the last address used
    Returns (serial, "ip:port" or None) or (None, None).
    """
    import time as _time
    if not adb_bin:
        return None, None
    deadline = _time.time() + timeout
    tried = set()
    saved = f"{saved_ip}:{saved_port}" if saved_ip and saved_port else None
    while _time.time() < deadline:
        ready = list_ready_devices(adb_bin)
        if ready:
            logger.info(f"Auto-connect: device ready: {ready[0]}")
            return ready[0], None

        targets = mdns_connect_targets(adb_bin)
        # Prefer the device we used last time
        if saved_ip:
            targets.sort(key=lambda t: 0 if t.startswith(saved_ip + ":") else 1)
        if saved and saved not in targets:
            targets.append(saved)
        for target in targets:
            if target in tried:
                continue
            tried.add(target)
            if progress:
                progress(f"Connecting to {target}...")
            if adb_connect(adb_bin, target):
                for _ in range(10):
                    ready = list_ready_devices(adb_bin)
                    if ready:
                        return (target if target in ready else ready[0]), target
                    _time.sleep(0.2)
        _time.sleep(0.4)
    logger.info("Auto-connect: no wireless device found")
    return None, None


def mdns_pairing_services(adb_bin):
    """[(instance_name, "ip:port")] of devices currently offering QR/code pairing"""
    try:
        result = subprocess.run(
            [adb_bin, "mdns", "services"], capture_output=True, text=True,
            timeout=ADB_INFO_TIMEOUT, creationflags=CREATE_NO_WINDOW,
        )
    except Exception as e:
        logger.debug(f"adb mdns services failed: {e}")
        return []
    return re.findall(r"^(\S+)\s+_adb-tls-pairing\._tcp\.?\s+(\d+\.\d+\.\d+\.\d+:\d+)",
                      result.stdout or "", flags=re.MULTILINE)


def adb_pair(adb_bin, target, code, timeout=20):
    """`adb pair ip:port code`; True on success"""
    try:
        result = subprocess.run(
            [adb_bin, "pair", target, code], capture_output=True, text=True,
            timeout=timeout, creationflags=CREATE_NO_WINDOW,
        )
        out = ((result.stdout or "") + (result.stderr or "")).strip()
        logger.info(f"adb pair {target}: {out}")
        return result.returncode == 0 and "success" in out.lower()
    except Exception as e:
        logger.info(f"adb pair {target} failed: {e}")
        return False
