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
    """
    Add a child process to the job explicitly. Even when DualCPY itself is in
    the job, some Pythons (e.g. the Microsoft Store build) let children escape
    it, so never rely on inheritance alone.
    """
    if not _job:
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


# ----------------------------------------------------------------------
# Leftovers from earlier sessions
# ----------------------------------------------------------------------
class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260),
    ]


def kill_stale(exe_path):
    """
    Close any process running `exe_path` (our bundled scrcpy.exe) left over
    from an earlier DualCPY session - e.g. after a crash or Ctrl+C under a
    Python that lets children escape the job. Returns how many were closed.
    """
    import os
    if not exe_path:
        return 0
    target = os.path.normcase(os.path.abspath(exe_path))
    name = os.path.basename(target)
    TH32CS_SNAPPROCESS = 0x2
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.OpenProcess.restype = wintypes.HANDLE
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == wintypes.HANDLE(-1).value:
        return 0
    killed = 0
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == name:
                h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_TERMINATE,
                                         False, entry.th32ProcessID)
                if h:
                    try:
                        buf = ctypes.create_unicode_buffer(1024)
                        size = wintypes.DWORD(1024)
                        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                            if os.path.normcase(buf.value) == target:
                                if kernel32.TerminateProcess(h, 1):
                                    killed += 1
                                    logger.info(f"Closed leftover {name} (PID {entry.th32ProcessID})")
                    finally:
                        kernel32.CloseHandle(h)
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return killed
