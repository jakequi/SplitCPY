# DualCPY Split - Thor <-> PC link test
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

# src/link_test.py
"""
Measures the connection between the handheld and this PC (not the internet -
the stream never goes there) and recommends a Latency profile.

- Response time / jitter: repeated tiny adb round trips. Jitter (how much the
  delay varies) is what makes audio warp: the audio buffer must absorb it.
- Throughput: push a test file to the device, then time pulling it back
  (device -> PC is the direction the video travels).
"""

import os
import re
import socket
import time
import logging
import statistics
import subprocess
import tempfile

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x08000000
PING_COUNT = 25
TEST_FILE_MB = 16
DEVICE_TEST_PATH = "/data/local/tmp/dualcpy_linktest.bin"

# Total video bitrate each profile needs over Wi-Fi at 60 FPS (Mbps, both screens),
# from scrcpy_manager's WIRELESS_PROFILE. 120 FPS needs ~1.5x.
PROFILE_NEED_MBPS = {"low": 28, "auto": 14, "stable": 7}
# Audio buffer (ms) each profile has on Wi-Fi - jitter has to fit inside it
PROFILE_AUDIO_BUFFER_MS = {"low": 50, "auto": 120, "stable": 250}
# Required headroom: measured throughput / needed bitrate
HEADROOM = 2.5


def _adb(adb_bin, serial, *args, timeout=30):
    return subprocess.run(
        [adb_bin, "-s", serial, *args],
        capture_output=True, text=True, timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
    )


def measure(adb_bin, serial, progress=None):
    """Run the test. Returns a dict of measurements (raises on adb failure)."""
    def step(msg):
        logger.info(f"Link test: {msg}")
        if progress:
            progress(msg)

    # 1) Round trips. With an ip:port serial, time TCP handshakes to the
    # device's adb port: that's the real Wi-Fi round trip. (Timing
    # `adb shell` instead mostly measures adb starting a shell, ~100 ms.)
    step("Measuring response time...")
    rtts = []
    m = re.match(r"^(\d+\.\d+\.\d+\.\d+):(\d+)$", serial or "")
    if m:
        addr = (m.group(1), int(m.group(2)))
        for _ in range(PING_COUNT):
            t0 = time.perf_counter()
            try:
                with socket.create_connection(addr, timeout=1.0):
                    rtts.append((time.perf_counter() - t0) * 1000)
            except OSError:
                pass
            time.sleep(0.03)
    if len(rtts) < PING_COUNT // 2:
        rtts = []
        for _ in range(PING_COUNT):
            t0 = time.perf_counter()
            r = _adb(adb_bin, serial, "shell", "echo", "ok", timeout=10)
            if r.returncode == 0:
                rtts.append((time.perf_counter() - t0) * 1000)
    if len(rtts) < PING_COUNT // 2:
        raise RuntimeError("The device didn't answer reliably")
    rtts.sort()
    median = statistics.median(rtts)
    p90 = rtts[int(len(rtts) * 0.9) - 1]
    jitter = max(0.0, p90 - median)

    # 2) Throughput (device -> PC)
    step("Measuring speed...")
    tmp_dir = tempfile.mkdtemp(prefix="dualcpy_")
    src = os.path.join(tmp_dir, "up.bin")
    back = os.path.join(tmp_dir, "down.bin")
    try:
        with open(src, "wb") as f:
            f.write(os.urandom(TEST_FILE_MB * 1024 * 1024))
        r = _adb(adb_bin, serial, "push", src, DEVICE_TEST_PATH, timeout=120)
        if r.returncode != 0:
            raise RuntimeError(f"Couldn't copy the test file: {(r.stderr or r.stdout).strip()}")
        t0 = time.perf_counter()
        r = _adb(adb_bin, serial, "pull", DEVICE_TEST_PATH, back, timeout=120)
        secs = time.perf_counter() - t0
        if r.returncode != 0:
            raise RuntimeError(f"Couldn't read the test file back: {(r.stderr or r.stdout).strip()}")
        mbps = TEST_FILE_MB * 8 * 1.048576 / max(secs, 1e-3)
    finally:
        try:
            _adb(adb_bin, serial, "shell", "rm", "-f", DEVICE_TEST_PATH, timeout=10)
        except Exception:
            pass
        for p in (src, back):
            try:
                os.remove(p)
            except OSError:
                pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass

    result = {"rtt_ms": round(median, 1), "jitter_ms": round(jitter, 1), "mbps": round(mbps, 1)}
    logger.info(f"Link test result: {result}")
    return result


def recommend(result, wireless, fps=60):
    """
    Pick the lowest-latency profile the link can carry with headroom and whose
    audio buffer comfortably absorbs the jitter. Returns (profile_key, reason).
    """
    if not wireless:
        return "low", "USB is fast and steady - lowest latency, full quality"
    fps_factor = max(1.0, (fps / 60.0) ** 0.6)
    for key in ("low", "auto", "stable"):
        need = PROFILE_NEED_MBPS[key] * fps_factor * HEADROOM
        # adb round trips include ~a few ms of adb overhead, so jitter here is a
        # slight over-estimate - keep it within half the audio buffer
        jitter_ok = result["jitter_ms"] <= PROFILE_AUDIO_BUFFER_MS[key] / 2
        if result["mbps"] >= need and jitter_ok:
            if key == "low":
                return key, "Strong, steady Wi-Fi - lowest latency, full quality"
            if key == "auto":
                return key, "Good Wi-Fi with some variation - a bit more audio buffer avoids warping"
            return key, "Busy or weak Wi-Fi - extra buffering keeps the audio clean"
    return "stable", "Weak or very unsteady Wi-Fi - Stable is the safest; USB would be much better"


def recommend_quality(result, wireless, fps=60, latency_key="low"):
    """Highest picture quality the link carries with headroom"""
    from src.scrcpy_manager import QUALITY_MULTIPLIER
    if not wireless:
        return "very_high"
    fps_factor = max(1.0, (fps / 60.0) ** 0.6)
    best = "standard"
    for q in ("standard", "high", "very_high", "max"):
        need = PROFILE_NEED_MBPS.get(latency_key, 28) * fps_factor * QUALITY_MULTIPLIER[q] * HEADROOM
        if result.get("mbps", 0) >= need:
            best = q
    return best
