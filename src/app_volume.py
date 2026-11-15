# DualCPY Split - per-app volume
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

# src/app_volume.py
"""
scrcpy has no volume option, so the stream's PC volume is set on its Windows
audio session (the same slider as in the Windows Volume Mixer).
"""

import logging

logger = logging.getLogger(__name__)

try:
    import comtypes
    from pycaw.pycaw import AudioUtilities
    _available = True
except Exception as e:  # pycaw missing -> volume slider is a no-op
    logger.warning(f"Per-app volume unavailable (install pycaw): {e}")
    _available = False


def set_process_volume(pids, level):
    """
    Set the volume (0.0-1.0) of the audio sessions owned by `pids`.
    Returns True if at least one session was found (it only exists once the
    process has started playing audio).
    """
    if not _available:
        return True  # nothing we can do; don't retry forever
    try:
        comtypes.CoInitialize()
    except Exception:
        pass
    found = False
    try:
        for session in AudioUtilities.GetAllSessions():
            proc = session.Process
            if proc is not None and proc.pid in pids:
                session.SimpleAudioVolume.SetMasterVolume(float(level), None)
                found = True
    except Exception as e:
        logger.debug(f"set_process_volume failed: {e}")
    if found:
        logger.info(f"Stream volume set to {int(level * 100)}%")
    return found
