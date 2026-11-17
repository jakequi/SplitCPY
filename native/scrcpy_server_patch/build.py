"""
Build bin/scrcpy-server from scrcpy's source with SplitCPY's audio patch.

    python native/scrcpy_server_patch/build.py            # version of bin/scrcpy.exe
    python native/scrcpy_server_patch/build.py 5.0.1

Why: scrcpy 5.0 made playback capture (SplitCPY's "Both" audio) ask for all
audio usages including voice calls, plus voice-call capture permission.
Android 13 (e.g. the AYN Thor) refuses that request for the adb shell
("registerAudioPolicy() returned -1") and scrcpy then disables PC audio.
The patch keeps 5.0's request first and, if Android refuses it, retries
without the voice-call usages, then with media only (scrcpy 4.x behaviour).

Needs a JDK (javac) and the Android SDK (platforms/android-*, build-tools/*
with aidl and d8). The SDK is found via ANDROID_HOME / ANDROID_SDK_ROOT,
else %LOCALAPPDATA%\\Android\\Sdk.
"""
import glob
import io
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(ROOT, "bin", "scrcpy-server")
BUILD = os.path.join(HERE, "build")
APC = "com/genymobile/scrcpy/audio/AudioPlaybackCapture.java"
NEWER_VERSION_CODES = {"VANILLA_ICE_CREAM": 35, "BAKLAVA": 36}


def sdk_dir():
    for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(env):
            return os.environ[env]
    return os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk")


def latest(pattern):
    found = sorted(glob.glob(pattern), key=lambda p: [int(x) for x in re.findall(r"\d+", p)])
    if not found:
        sys.exit(f"Not found: {pattern}")
    return found[-1]


def bundled_version():
    out = subprocess.run([os.path.join(ROOT, "bin", "scrcpy.exe"), "--version"],
                         capture_output=True, text=True).stdout
    m = re.search(r"scrcpy (\d+\.\d+(?:\.\d+)?)", out)
    if not m:
        sys.exit("Couldn't read the bundled scrcpy version")
    return m.group(1)


def patch_playback_capture(path):
    src = open(path, encoding="utf-8").read()
    if "SplitCPY" in src:
        return
    # 1) the builder takes a level: 0 = all usages + voice capture (upstream),
    #    1 = all but voice-call usages, 2 = media only
    old_sig = "    private AudioRecord createAudioRecord() throws AudioCaptureException {"
    assert old_sig in src, "createAudioRecord() not found - re-check the patch for this version"
    src = src.replace(old_sig, (
        "    private AudioRecord createAudioRecord() throws AudioCaptureException {\n"
        "        // SplitCPY patch: Android 13 refuses the full request below for the adb\n"
        "        // shell (registerAudioPolicy() returns -1), so fall back step by step\n"
        "        Exception last = null;\n"
        "        for (int level = 0; level <= 2; level++) {\n"
        "            try {\n"
        "                AudioRecord recorder = createAudioRecord(level);\n"
        "                if (level > 0) {\n"
        "                    Ln.i(\"Audio playback capture: using fallback level \" + level);\n"
        "                }\n"
        "                return recorder;\n"
        "            } catch (Exception e) {\n"
        "                last = e;\n"
        "                Ln.w(\"Audio playback capture level \" + level + \" refused: \" + e);\n"
        "            }\n"
        "        }\n"
        "        Ln.e(\"Could not capture audio playback\", last);\n"
        "        throw new AudioCaptureException();\n"
        "    }\n\n"
        "    @TargetApi(AndroidVersions.API_26_ANDROID_8_0)\n"
        "    @SuppressLint(\"PrivateApi\")\n"
        "    private AudioRecord createAudioRecord(int level) throws Exception {"))
    # 2) usages per level
    m = re.search(r"            int\[\] usages = \{.*?\};\n", src, re.S)
    assert m, "usages list not found"
    full = m.group(0)
    no_voice = re.sub(r"\s*AudioAttributes\.USAGE_VOICE_COMMUNICATION(_SIGNALLING)?,", "", full)
    no_voice = no_voice.replace("int[] usages = {", "int[] usagesNoVoice = {")
    src = src.replace(full, full + no_voice + (
        "            int[] usagesMedia = {AudioAttributes.USAGE_MEDIA};\n"
        "            if (level == 1) {\n"
        "                usages = usagesNoVoice;\n"
        "            } else if (level == 2) {\n"
        "                usages = usagesMedia;\n"
        "            }\n"))
    # 3) voice-call capture permission only at level 0
    old_voice = "            voiceCommunicationCaptureAllowedMethod.invoke(audioMixingRuleBuilder, true);"
    assert old_voice in src, "voiceCommunicationCaptureAllowed call not found"
    src = src.replace(old_voice, "            if (level == 0) {\n    " + old_voice + "\n            }")
    # 4) the inner method now throws; the wrapper above logs and gives up
    old_catch = ("        } catch (Exception e) {\n"
                 "            Ln.e(\"Could not capture audio playback\", e);\n"
                 "            throw new AudioCaptureException();\n"
                 "        }\n    }")
    assert old_catch in src, "catch block not found"
    src = src.replace(old_catch, "        } finally {\n            // errors go to the caller\n        }\n    }")
    open(path, "w", encoding="utf-8").write(src)


def find_javac():
    """scrcpy builds with JDK 17; much newer javac output crashes older d8"""
    exe = "javac.exe" if os.name == "nt" else "javac"
    for env in ("SPLITCPY_JDK", "JAVA17_HOME"):
        if os.environ.get(env):
            return os.path.join(os.environ[env], "bin", exe)
    for pattern in (r"C:\Program Files\Java\jdk-17*", r"C:\Program Files\Eclipse Adoptium\jdk-17*",
                    r"C:\Program Files\Microsoft\jdk-17*"):
        found = sorted(glob.glob(pattern))
        if found and os.path.isfile(os.path.join(found[-1], "bin", exe)):
            return os.path.join(found[-1], "bin", exe)
    return shutil.which("javac") or sys.exit("javac not found (JDK 17 recommended)")


def run(cmd):
    if subprocess.run(cmd).returncode != 0:
        sys.exit(f"Build step failed: {os.path.basename(cmd[0])}")


def main():
    version = sys.argv[1] if len(sys.argv) > 1 else bundled_version()
    sdk = sdk_dir()
    platform_dir = latest(os.path.join(sdk, "platforms", "android-*"))
    tools = latest(os.path.join(sdk, "build-tools", "*"))
    exe = ".exe" if os.name == "nt" else ""
    javac = find_javac()

    shutil.rmtree(BUILD, ignore_errors=True)
    os.makedirs(BUILD)
    url = f"https://github.com/Genymobile/scrcpy/archive/refs/tags/v{version}.zip"
    print(f"Downloading scrcpy {version} source...")
    zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(url, timeout=120).read())).extractall(BUILD)
    server = os.path.join(BUILD, f"scrcpy-{version}", "server", "src", "main")
    patch_playback_capture(os.path.join(server, "java", APC))
    # Building against an older SDK than scrcpy's: newer version-code names are
    # just their numbers (identical compiled result)
    for rel in glob.glob(os.path.join(server, "java", "**", "*.java"), recursive=True):
        code = open(rel, encoding="utf-8").read()
        new = code
        for name, number in NEWER_VERSION_CODES.items():
            new = new.replace(f"Build.VERSION_CODES.{name}", str(number))
        if new != code:
            open(rel, "w", encoding="utf-8").write(new)

    gen, classes = os.path.join(BUILD, "gen"), os.path.join(BUILD, "classes")
    os.makedirs(os.path.join(gen, "com", "genymobile", "scrcpy"))
    os.makedirs(classes)
    with open(os.path.join(gen, "com", "genymobile", "scrcpy", "BuildConfig.java"), "w") as f:
        f.write("package com.genymobile.scrcpy;\npublic final class BuildConfig {\n"
                "  public static final boolean DEBUG = false;\n"
                f"  public static final String VERSION_NAME = \"{version}\";\n}}\n")

    aidl_dir = os.path.join(server, "aidl")
    aidl = os.path.join(tools, "aidl" + exe)
    for rel in glob.glob(os.path.join(aidl_dir, "**", "*.aidl"), recursive=True):
        cmd = [aidl, "-o" + gen, "-I" + aidl_dir]
        if "IDisplayWindowListener" in rel:
            cmd += ["-p", os.path.join(platform_dir, "framework.aidl")]
        subprocess.check_call(cmd + [os.path.relpath(rel, aidl_dir)], cwd=aidl_dir)

    java_dir = os.path.join(server, "java")
    sources = glob.glob(os.path.join(java_dir, "**", "*.java"), recursive=True)
    sources += glob.glob(os.path.join(gen, "**", "*.java"), recursive=True)
    print(f"Compiling {len(sources)} sources against {os.path.basename(platform_dir)}...")
    run([javac, "-encoding", "UTF-8", "-nowarn", "-Xlint:-options",
                           "-bootclasspath", os.path.join(platform_dir, "android.jar"),
                           "-cp", os.path.join(tools, "core-lambda-stubs.jar") + os.pathsep + gen,
                           "-d", classes, "-source", "1.8", "-target", "1.8", *sources])
    # One jar instead of hundreds of .class paths (Windows' command line limit)
    classes_jar = os.path.join(BUILD, "classes.jar")
    with zipfile.ZipFile(classes_jar, "w") as z:
        for path in glob.glob(os.path.join(classes, "**", "*.class"), recursive=True):
            z.write(path, os.path.relpath(path, classes).replace(os.sep, "/"))
    class_files = [classes_jar]
    d8 = os.path.join(tools, "d8.bat" if os.name == "nt" else "d8")
    print("Dexing...")
    run([d8, "--release", "--min-api", "21",
                           "--lib", os.path.join(platform_dir, "android.jar"),
                           "--output", BUILD, *class_files])
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(BUILD, "classes.dex"), "classes.dex")
    print(f"Wrote {OUT} (scrcpy {version} server, SplitCPY audio patch)")


if __name__ == "__main__":
    main()
