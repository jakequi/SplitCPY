# SplitCPY - dual-screen scrcpy launcher for the AYN Thor and other handhelds
# Copyright (C) 2026 the_swest (original DualCPY) and SplitCPY contributors
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

# main.py

__version__ = "1.0.0"
__app_name__ = "SplitCPY"
__author__ = "jakequi (fork of DualCPY by the_swest)"
__description__ = "Dual-screen scrcpy launcher for the AYN Thor and other handhelds"

import os
import sys
import time
import ctypes
import logging
import tkinter as tk
from ctypes import wintypes
from tkinter import messagebox
from src.launcher import Launcher

REQUIRED_FOLDERS = ["bin", "config", "logs"] # List of required folders that must exist in order to function
WIN11_LOWEST_BUILD = 22000 # Lowest build number of Windows 11
LOG_MULT = 60 # Amount of = to put in the logs as seperators
MB_ICONERROR = 0x10 # Windows error messagebox flag

def setup_logging():
    """
    Configure logging
    """
    log_dir = os.path.join(
        os.path.dirname(sys.executable if hasattr(sys, "_MEIPASS") else __file__),
        "logs",
    )
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, f"splitcpy_{time.strftime('%Y%m%d')}.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler()],
    )


def check_windows_version():
    """
    Check if running on Windows 10 and show a warning.
    Windows 11 has build number 22000 or higher.
    Shows a warning message if running on Windows 10 but allows launch.
    """
    logger = logging.getLogger(__name__)

    try:
        version = sys.getwindowsversion()
        build = version.build

        # Windows 11 is build 22000+, Windows 10 is builds 10240-19045
        if build < WIN11_LOWEST_BUILD:
            logger.warning(f"Windows 10 detected (Build {build}) - showing warning message")
            # Show warning
            try:
                root = tk.Tk()
                root.withdraw()
                messagebox.showwarning(
                    "Windows 10 Detected - Known Issues",
                    f"WARNING: You are running Windows 10 (Build {build})\n\n"
                    f"SplitCPY has been reported to have stability issues on Windows 10.\n"
                    f"Restarting SplitCPY can sometimes fix small issues.\n"
                    f"For the best experience, please use Windows 11.\n\n"
                    f"Continue anyway?",
                )
                root.destroy()
            except Exception as tkErr:
                # Fallback to console message if the messagebox doesn't work
                logger.error(f"GUI warning message failed: {tkErr}")
                print("=" * LOG_MULT)
                print("WARNING: Windows 10 Detected - Unstable Build with Known Issues")
                print("=" * LOG_MULT)
                print(f"You are running Windows 10 (Build {build})")
                print("")
                print("SplitCPY has known stability issues on Windows 10.")
                print("")
                print("Restarting SplitCPY can sometimes fix small issues")
                print("")
                print("For the best experience, please use Windows 11.")
                print("=" * LOG_MULT)
                print(f"(GUI warning failed: {tkErr})")
                input("\nPress Enter to continue anyway...")
        else:
            logger.info(f"Windows 11 detected (Build {build})")
            print(f"Windows 11 detected (Build {build})")

    except Exception as WinDetectionError:
        logger.error(f"Could not verify Windows version: {WinDetectionError}")
        print(f"Warning: Could not verify Windows version: {WinDetectionError}")


def show_fatal_error(title: str, message: str):
    """Show a fatal error dialog."""
    ctypes.windll.user32.MessageBoxW(
        None,
        message,
        title,
        MB_ICONERROR
    )


def check_runtime_structure():
    """
    Checks that all required folders exist in the application directory.
    Is used when running from python files and with a pyinstaller exe.
    """
    logger = logging.getLogger(__name__)

    is_frozen = hasattr(sys, "_MEIPASS")
    if is_frozen:
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))

    # When frozen, transparently create the writable folders next to
    # the executable and skip the bin/ check (it lives in _MEIPASS).
    if is_frozen:
        for folder in ("config", "logs"):
            try:
                os.makedirs(os.path.join(base, folder), exist_ok=True)
            except Exception as MkdirError:
                logger.warning(
                    f"Could not create runtime folder '{folder}': {MkdirError}"
                )
        logger.debug(
            f"Frozen runtime: bin/ resolves from _MEIPASS={sys._MEIPASS}; "
            f"config/ and logs/ ensured next to {sys.executable}"
        )
        return

    # From-source path: hard fail if anything is missing.
    missing = [f for f in REQUIRED_FOLDERS if not os.path.isdir(os.path.join(base, f))]

    if missing:
        msg = (
            f"{__app_name__} failed to start.\n\n"
            f"Missing required folders:\n"
            f"{', '.join(missing)}\n\n"
            f"{__app_name__} must be installed with:\n"
            f"bin/, config/, logs/\n\n"
            f"Please reinstall or extract the full build."
        )

        # Log error and show fatal error, also print to console
        logger.critical(msg)
        print(msg)
        show_fatal_error(f"{__app_name__} Startup Error", msg)
        sys.exit(1)


_instance_mutex = None
SINGLE_INSTANCE_MUTEX = "Local\\SplitCPY.SingleInstance"


def acquire_single_instance(wait_ms=4000):
    """
    True if this is the only running SplitCPY. Waits briefly so an app
    restart (old copy still shutting down) doesn't get turned away.
    The mutex is released by Windows when the process exits, however it exits.
    """
    global _instance_mutex
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _instance_mutex = kernel32.CreateMutexW(None, False, SINGLE_INSTANCE_MUTEX)
    if not _instance_mutex:
        return True  # can't tell - don't block start-up
    WAIT_OBJECT_0, WAIT_ABANDONED = 0x0, 0x80
    return kernel32.WaitForSingleObject(_instance_mutex, wait_ms) in (WAIT_OBJECT_0, WAIT_ABANDONED)


def focus_existing_instance():
    """Bring the running copy's control panel (and stage) to the front"""
    user32 = ctypes.windll.user32
    for title in ("SplitCPY Control Panel",):
        hwnd = user32.FindWindowW(None, title)
        if hwnd:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
            return True
    return False


def main():
    """
    SplitCPY's main entry point
    Sets up logging, checks windows version, runs folder checks, sets DPI awareness,
    creates the launcher instance and starts the UI.
    """
    print(f"Starting {__app_name__} v{__version__}")
    print("Checking system requirements...")

    # When packaged as a PyInstaller exe, the working directory may
    # be wherever the user double-clicked from (their Desktop, etc).
    # Anchor all relative paths (config/, logs/) to the exe's own
    # directory so the app behaves predictably regardless of how it
    # was launched.
    if getattr(sys, "frozen", False):
        try:
            os.chdir(os.path.dirname(sys.executable))
        except Exception:
            pass

    # Sets up logging before anything else
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info(f"Starting {__app_name__} v{__version__}")
    logger.info(f"System: Windows Build {sys.getwindowsversion().build}")

    # Check Windows version and show warning if Windows 10
    check_windows_version()

    # Run the folder check
    check_runtime_structure()

    # Set DPI awareness
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        logger.info("DPI Awareness set successfully")
    except Exception as DpiAwareErr:
        logger.error(f"Could not set DPI Awareness: {DpiAwareErr}")

    # Bump our own process priority to ABOVE_NORMAL_PRIORITY_CLASS.
    # The two scrcpy children run at HIGH (set in scrcpy_manager) so
    # we stay below them and don't risk starving the encoder/decoder,
    # but we sit ABOVE the swarm of NORMAL-priority background apps
    # (Discord, browsers, IDEs, game launchers) that would otherwise
    # share CPU with our message pump and chassis renderer. That
    # sharing is the source of the residual sub-frame audio hiccups.
    try:
        ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
        kernel32 = ctypes.windll.kernel32
        # 64-bit pseudo-handle from GetCurrentProcess() must NOT be
        # truncated to 32-bit int by ctypes' default signature.
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.SetPriorityClass.restype = wintypes.BOOL
        current = kernel32.GetCurrentProcess()
        if kernel32.SetPriorityClass(current, ABOVE_NORMAL_PRIORITY_CLASS):
            logger.info("Host process priority set")
        else:
            err = kernel32.GetLastError()
            logger.warning(f"SetPriorityClass(ABOVE_NORMAL) failed (GetLastError={err})")
    except Exception as PriorityErr:
        logger.warning(f"Could not raise host process priority: {PriorityErr}")

    # Only one SplitCPY at a time: two copies fight over the handheld,
    # the hotkeys and each other's scrcpy windows
    if not acquire_single_instance():
        logger.info("SplitCPY is already running - bringing it to the front")
        focus_existing_instance()
        return

    # Make sure scrcpy/adb always die with us, even after a crash
    from src import process_guard
    from src.device_detection import resolve_adb
    process_guard.init()

    # Close any scrcpy left running by an earlier session (crash, Ctrl+C...)
    try:
        stale = process_guard.kill_stale(resolve_adb("scrcpy"))
        if stale:
            logger.warning(f"Closed {stale} leftover scrcpy process(es) from a previous session")
    except Exception as StaleErr:
        logger.warning(f"Leftover check failed: {StaleErr}")

    # Create the main launcher object and start it
    logger.info("Initializing launcher")
    app = Launcher()

    # Closing the terminal window (or logging off) -> clean shutdown
    CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT = 2, 5, 6
    HandlerRoutine = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

    def _console_handler(event):
        if event in (CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT):
            logger.info(f"Console event {event} - shutting down")
            app.stop()
            return True
        return False  # Ctrl+C etc. -> KeyboardInterrupt, handled below

    app._console_handler = HandlerRoutine(_console_handler)  # keep a reference
    try:
        ctypes.windll.kernel32.SetConsoleCtrlHandler(app._console_handler, True)
    except Exception:
        pass

    try:
        app.launch()
    except KeyboardInterrupt:
        logger.info("Ctrl+C - shutting down")
    finally:
        # Ctrl+C or an unexpected error: still stop the streams, disconnect and
        # stop adb (stop() is a no-op if it already ran)
        app.stop()


if __name__ == "__main__":
    main()