# DualCPY Split - child process guard
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

# src/process_guard.py
"""
Ties scrcpy / adb to DualCPY's lifetime with a Windows Job Object
(JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE). When DualCPY exits for ANY reason -
normal close, crash, or being killed from Task Manager - Windows closes
the job handle and terminates every process in it. No more scrcpy audio
playing in the background or adb.exe left connected.
"""

import ctypes
import logging
from ctypes import wintypes

logger = logging.getLogger(__name__)

kernel32 = ctypes.windll.kernel32

JobObjectExtendedLimitInformation = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x00000800
CREATE_BREAKAWAY_FROM_JOB = 0x01000000

PROCESS_SET_QUOTA = 0x0100
PROCESS_TERMINATE = 0x0001


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _BASIC_LIMIT(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _EXTENDED_LIMIT(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BASIC_LIMIT),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


kernel32.CreateJobObjectW.restype = wintypes.HANDLE
kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
kernel32.GetCurrentProcess.restype = wintypes.HANDLE

_job = None
_self_in_job = False


def init():
    """
    Create the job and put DualCPY itself in it, so every process it starts
    (scrcpy, adb, and the adb server adb spawns) inherits the job.
    Safe to call more than once.
    """
    global _job, _self_in_job
    if _job:
        return
    try:
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise OSError(ctypes.get_last_error())
        info = _EXTENDED_LIMIT()
        info.BasicLimitInformation.LimitFlags = (
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_BREAKAWAY_OK
        )
        if not kernel32.SetInformationJobObject(
                job, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError(ctypes.get_last_error())
        _job = job  # intentionally never closed: closing it is what kills the children
        _self_in_job = bool(kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess()))
        logger.info(f"Process guard active (self in job: {_self_in_job})")
    except Exception as e:
        logger.warning(f"Process guard unavailable: {e}")


def adopt(popen):
    """Add a child process to the job (only needed if DualCPY itself isn't in it)."""
    if not _job or _self_in_job:
        return
    try:
        handle = getattr(popen, "_handle", None)
        if handle:
            kernel32.AssignProcessToJobObject(_job, wintypes.HANDLE(int(handle)))
    except Exception as e:
        logger.debug(f"Could not add PID {getattr(popen, 'pid', '?')} to job: {e}")


def breakaway_flags():
    """Creation flags for a process that must outlive DualCPY (e.g. app restart)."""
    return CREATE_BREAKAWAY_FROM_JOB if _self_in_job else 0
