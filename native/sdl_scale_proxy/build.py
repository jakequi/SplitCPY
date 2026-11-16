"""
Build the SDL3 scale-mode proxy (see sdl_scale_proxy.c).

    python native/sdl_scale_proxy/build.py [bin folder]

Needs Visual Studio's C++ tools (x64). The first run renames the real
bin/SDL3.dll to bin/SDL3_real.dll; the proxy is then written to bin/SDL3.dll.
When updating scrcpy, put its new SDL3.dll in bin/ as SDL3_real.dll and rerun.
"""
import glob
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
BIN = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(ROOT, "bin")
REAL = os.path.join(BIN, "SDL3_real.dll")
PROXY = os.path.join(BIN, "SDL3.dll")
WRAPPED = {"SDL_CreateTextureWithProperties", "SDL_CreateTexture"}
# The real SDL3 is ~2 MB; the proxy is a few KB
REAL_MIN_SIZE = 500_000


def vcvars():
    vswhere = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                           "Microsoft Visual Studio", "Installer", "vswhere.exe")
    if os.path.isfile(vswhere):
        path = subprocess.run([vswhere, "-latest", "-products", "*", "-property", "installationPath"],
                              capture_output=True, text=True).stdout.strip()
        candidate = os.path.join(path, "VC", "Auxiliary", "Build", "vcvars64.bat")
        if os.path.isfile(candidate):
            return candidate
    found = sorted(glob.glob(r"C:\Program Files*\Microsoft Visual Studio\*\*\VC\Auxiliary\Build\vcvars64.bat"))
    if not found:
        sys.exit("Visual Studio C++ tools (vcvars64.bat) not found")
    return found[-1]


def in_vs(vc, command):
    return subprocess.run(f'cmd /c ""{vc}" >nul && {command}"', shell=True,
                          capture_output=True, text=True, cwd=HERE)


def main():
    if not os.path.isfile(REAL):
        if not os.path.isfile(PROXY) or os.path.getsize(PROXY) < REAL_MIN_SIZE:
            sys.exit("bin/SDL3.dll is not the real SDL3 and bin/SDL3_real.dll is missing")
        shutil.copyfile(PROXY, REAL)
        print("Saved the real SDL3 as bin/SDL3_real.dll")

    vc = vcvars()
    out = in_vs(vc, f'dumpbin /nologo /exports "{REAL}"')
    if out.returncode != 0:
        sys.exit(out.stdout + out.stderr)
    names = re.findall(r"^\s+\d+\s+[0-9A-F]+\s+[0-9A-F]{8}\s+(\S+)", out.stdout, re.M)
    if len(names) < 500:
        sys.exit(f"Only {len(names)} exports found - dumpbin output changed?")

    build = os.path.join(HERE, "build")
    shutil.rmtree(build, ignore_errors=True)
    os.makedirs(build)
    # Forwarders as linker pragmas (a .def "name=SDL3_real.name" entry is
    # rejected as an unresolved symbol by current MSVC linkers)
    with open(os.path.join(build, "forwards.h"), "w") as f:
        for name in names:
            if name not in WRAPPED:
                f.write(f'#pragma comment(linker, "/export:{name}=SDL3_real.{name}")\n')

    r = in_vs(vc, r"cl /nologo /O2 /LD /MT /Ibuild /FIforwards.h sdl_scale_proxy.c "
                  r"/Fobuild\ /Febuild\SDL3.dll /link kernel32.lib")
    if r.returncode != 0:
        sys.exit(r.stdout + r.stderr)
    shutil.copyfile(os.path.join(build, "SDL3.dll"), PROXY)
    print(f"Wrote {PROXY} ({len(names)} exports, {len(WRAPPED)} wrapped)")


if __name__ == "__main__":
    main()
