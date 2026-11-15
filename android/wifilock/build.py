"""
Build bin/splitcpy-wifilock.dex from src/WifiLock.java.

Needs a JDK (javac) and the Android SDK (build-tools d8 + platforms/android-*).
The SDK is found via ANDROID_HOME / ANDROID_SDK_ROOT, else %LOCALAPPDATA%\\Android\\Sdk.

    python android/wifilock/build.py
"""
import glob
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(ROOT, "bin", "splitcpy-wifilock.dex")


def sdk_dir():
    for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(env):
            return os.environ[env]
    return os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk")


def latest(pattern):
    found = sorted(glob.glob(pattern))
    if not found:
        sys.exit(f"Not found: {pattern}")
    return found[-1]


def main():
    sdk = sdk_dir()
    android_jar = latest(os.path.join(sdk, "platforms", "android-*", "android.jar"))
    d8 = latest(os.path.join(sdk, "build-tools", "*", "d8.bat" if os.name == "nt" else "d8"))
    javac = shutil.which("javac") or sys.exit("javac not found on PATH")

    build = os.path.join(HERE, "build")
    classes = os.path.join(build, "classes")
    shutil.rmtree(build, ignore_errors=True)
    os.makedirs(classes)

    subprocess.check_call([javac, "--release", "8", "-Xlint:-options", "-cp", android_jar,
                           "-d", classes, os.path.join(HERE, "src", "WifiLock.java")])
    subprocess.check_call([d8, "--min-api", "24", "--lib", android_jar, "--output", build,
                           *glob.glob(os.path.join(classes, "*.class"))])
    shutil.copyfile(os.path.join(build, "classes.dex"), OUT)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
