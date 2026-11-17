<p align="center">
  <img src=".github/icon.png" alt="SplitCPY logo" height="96">
</p>

<h1 align="center">SplitCPY</h1>

<p align="center">
  <em>Mirror both screens of the AYN Thor (and other dual-screen handhelds) to your PC -
  built for streaming with OBS and for playing on your monitor with the handheld as a controller.</em>
</p>

> [!NOTE]
> SplitCPY is a fork of **[DualCPY](https://github.com/theswest/DualCPY)** by the_swest.
> It keeps DualCPY's foundations (scrcpy docking, device profiles, file transfer) and adds an
> OBS-friendly stage, instant connecting, console aspect presets, audio fixes and much more -
> see the [changelog](CHANGELOG.md).

**Windows 11 recommended** (Windows 10 1809+ should work).

---

## Download

Grab **`SplitCPY-v1.2.0-windows.zip`** from the
[latest release](https://github.com/jakequi/SplitCPY/releases/latest), unzip it anywhere
and run **`SplitCPY.exe`**. scrcpy and adb are included - nothing else to install.
`config/` and `logs/` are created next to the exe on first launch.

### Run from source
1. Install Python 3.10-3.13 (tick *"Add python.exe to PATH"*).
2. `git clone https://github.com/jakequi/SplitCPY.git` and `cd SplitCPY`
3. `pip install -r requirements.txt`
4. `python main.py`

### Build the exe yourself
`pip install pyinstaller`, then `python build.py` - the app is in `dist/SplitCPY/`.

---

## First-time setup

On the handheld:
1. **Enable Developer options:** Settings > About device > tap *Build number* 7 times.
2. **USB:** turn on *USB debugging*, plug in, tap **Allow**. Done.
3. **Wi-Fi:** turn on *Wireless debugging* and tick **"Always allow on this network"**.
   In SplitCPY choose *Pair / Connect Manually*, then on the handheld open
   *Wireless debugging > Pair device with pairing code* - SplitCPY fills in the address,
   you just type the 6-digit code. You only pair once.
4. **Tip:** Developer options > *Quick settings developer tiles* > **Wireless debugging** puts a
   one-tap toggle in your quick settings.

From then on, just open SplitCPY. It finds the handheld on USB or Wi-Fi by itself (even after
a restart, even though Android changes the port) and opens straight into the streams. If Wireless
debugging is off it waits and connects the moment you turn it on.

---

## Features

### For OBS / streaming
- **One window, exactly the game area** - no black bars for OBS to capture.
  **Both** stacks the screens, **Top** / **Bottom** show one screen. Switching keeps the height;
  dragging the edges keeps the shape.
- **Fullscreen** (F11) centres the game on a black backdrop that OBS doesn't see.
- **Split** turns the screens into two separate windows (resizable, individually capturable).
- **Controller overlay (experimental)** - the Thor's buttons and sticks drawn beside the bottom
  screen, lighting up live as you press them.
- **Aspect presets** by ratio with the consoles that use it ("4:3 (DS, NES, SNES, PS1, ...)",
  "3:2 (GBA)", "31:27 (Thor-B)", ...) - crops the black bars instantly, no stream restart.

### For playing on your monitor
- **Low-latency streaming** with Latency (Low / Balanced / Stable) and Quality
  (Standard / High / Very High / Max) presets.
- **Test Connection & Auto-Set** measures the Wi-Fi between handheld and PC and picks the best
  Latency and Quality for you.
- **Dim Thor screens** while you play on the monitor (restored afterwards).
- **Audio output** on the PC, the handheld, or both; per-stream **volume**.
- **Top / Bottom FPS** (up to 120, experimental) and an optional 30 FPS cap for the bottom screen.

### Everything else
- **Profiles** - save your whole setup; star one to load it on start-up.
- **Auto-reconnect** if a stream drops; nothing left running when you close (even after a crash).
- **File transfer**, **screenshots** (also in split mode), **device profiles** for other
  dual-screen handhelds (can be switched off).

### Hotkeys (work while gaming)
| Keys | Action |
|---|---|
| Ctrl+Alt+1 / 2 / 3 | View: Both / Top / Bottom |
| Ctrl+Alt+S | Cycle views |
| Ctrl+Alt+F, or F11 while SplitCPY is in front | Fullscreen |
| Ctrl+Alt+M | Show / hide the control panel (also over fullscreen) |
| Ctrl+Alt+O | Dim / restore the Thor's screens |
| Ctrl+Alt+I | Show / hide the stats overlay (FPS, codec, bitrate, connection) |

### OBS setup
Add a **Window Capture** of the `SplitCPY | <device>` window, then right-click it >
*Transform > Edit Transform* > **Bounding Box Type: Scale to inner bounds**, **Alignment: Center**.
Switching between Both / Top / Bottom is then seamless.

---

## Roadmap

Planned for future versions:
- **Fullscreen for split windows** - in Split mode, F11 makes the window you're in fullscreen on
  its own monitor over a true-black background (e.g. top screen on the TV, bottom on the laptop).
  Idea from [AndersonWood's DualCPY fork](https://github.com/AndersonWood/DualCPYerson).

Suggestions and bug reports: [issues](https://github.com/jakequi/SplitCPY/issues).

---

## Troubleshooting

- **Audio warps or crackles (Wi-Fi):** run *Test Connection & Auto-Set*, or set Latency to
  Balanced, then Stable. USB gives the cleanest audio.
- **Black or flickering screens:** Display (this PC) > Renderer > Direct3D 9 (this also turns off hardware decoding).
- **Handheld not found:** check USB debugging / Wireless debugging is on and both devices are on
  the same network; *Pair / Connect Manually* in the waiting window lets you pair again.
- **Logs:** `logs/splitcpy_<date>.log` and per-stream `logs/scrcpy_*.log` next to the app.

### Known issues

- **Audio output "Both": the PC and the handheld aren't in sync** - the PC's copy arrives later,
  because it is captured, encoded, sent and buffered (the Latency setting) before it plays. Lower
  Latency narrows the gap; it can't be removed entirely.
- **JamesDSP (root build) stopped working after a session** - once, fixed by restarting it.
  Not confirmed to be SplitCPY: while streaming with *Audio output: PC*, Android moves JamesDSP's
  effect to the capture output scrcpy records from, and it may not always move back to the
  speaker afterwards. If it happens, restart JamesDSP; *Audio output: Device* avoids the capture.

---

## Bundled software & licences

- SplitCPY is licensed under the **GNU GPL v3.0** - see [LICENSE](LICENSE). You are free to
  modify and redistribute it under the same terms.
- Includes **[scrcpy](https://github.com/Genymobile/scrcpy) v5.0.1** by Genymobile / Romain Vimont,
  under the Apache License 2.0 ([bin/LICENSE_scrcpy.txt](bin/LICENSE_scrcpy.txt)), with the
  libraries its Windows release ships (SDL, FFmpeg, adb, libusb) under their own licences. The
  Windows program is unmodified; the on-device `scrcpy-server` is rebuilt from scrcpy's source
  with one change: if Android refuses scrcpy 5's audio playback capture request (Android 13, used
  by *Audio output: Both*), it retries without voice-call audio, then with media only. The patch
  and build script are in [native/scrcpy_server_patch](native/scrcpy_server_patch).
- scrcpy's **[SDL](https://www.libsdl.org/)** library (zlib licence) is included as `bin/SDL3_real.dll`;
  `bin/SDL3.dll` is SplitCPY's own small pass-through that adds the Sharp scaling option
  (source in [native/sdl_scale_proxy](native/sdl_scale_proxy)).
- UI font **[Cal Sans](https://github.com/calcom/font)**, SIL Open Font License 1.1
  ([assets/fonts/OFL.txt](assets/fonts/OFL.txt)).
- Theme fonts: **[Pictochat](https://fontstruct.com/fontstructions/show/377692)** by Kirby3, Creative
  Commons Attribution-ShareAlike 3.0 ([assets/fonts/pictochat](assets/fonts/pictochat)), and
  **[M PLUS Rounded 1c](https://github.com/coz-m/MPLUS_FONTS)**, SIL Open Font License 1.1
  ([assets/fonts/OFL-MPLUSRounded1c.txt](assets/fonts/OFL-MPLUSRounded1c.txt)). The 3DS theme uses
  Fontworks' FOT-Rodin instead if a licensed copy is installed on the PC (it isn't bundled).

## Acknowledgements

- **[the_swest](https://github.com/theswest)** - creator of [DualCPY](https://github.com/theswest/DualCPY), which this fork is built on
  (support the original: https://ko-fi.com/theswest)
- **[tommywaaf](https://github.com/tommywaaf)** - performance work in DualCPY and
  [scrcpy-thor-ui](https://github.com/tommywaaf/scrcpy-thor-ui), source of the controller-overlay
  idea, the Direct3D 11 finding and the audio-buffer measurements
- **[DrSkyfaR](https://github.com/DrSkyfaR)** - file transfer and the Linux port of DualCPY
- **[AndersonWood](https://github.com/AndersonWood)** - split-window fullscreen idea (roadmap)
- **[eldermonkey](https://github.com/eldermonkey)** - the legacy logo
- **[scrcpy](https://github.com/Genymobile/scrcpy)** by Romain Vimont - the backend
- **[CustomTkinter](https://github.com/TomSchimansky/CustomTkinter)** - UI toolkit
