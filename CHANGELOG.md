# Changelog

## SplitCPY 1.2.0 - 17-11-2026

### Added
- **Themes** (dropdown at the top right of the control panel, opposite the title):
  - **DS (PictoChat)** - PictoChat's pixel lettering throughout (the "Pictochat" font by Kirby3, CC BY-SA 3.0), square boxes with dark 2 px pixel outlines, section titles as solid blue name tags on a dark rule, PictoChat greys
  - **3DS (HOME menu)** - white rounded buttons with thin light outlines; the selected and main buttons keep a white face with a glowing cyan border and cyan text, as on the 3DS; cyan-underlined titles; M PLUS Rounded 1c (OFL), or FOT-Rodin (the 3DS system font) if a licensed copy is installed
  - Switch instantly without restarting the streams; the title bar, the Wireless window and the loading screen follow the theme

### Fixed
- **Audio output "Both" only played on the handheld** (since 1.1.0 / scrcpy 5.0): scrcpy 5 asks Android to capture every kind of audio including voice calls, which Android 13 (e.g. the AYN Thor) refuses for adb (`registerAudioPolicy() returned -1`), so PC audio was switched off. The bundled `scrcpy-server` is now rebuilt with a fallback: if refused, it retries without voice-call audio, then media only. Patch and build script in `native/scrcpy_server_patch`

### Known issues
- Audio output "Both": the PC's sound lags the handheld's (capture, encoding, Wi-Fi and the audio buffer); lower Latency narrows the gap
- JamesDSP (root build) once stopped working after a session until restarted; not confirmed to be SplitCPY (see README > Known issues)

## SplitCPY 1.1.0 - 16-11-2026

### Changed
- **scrcpy 5.0.1** (from 4.0): the PC now decodes the video on the graphics card (D3D11VA) - scrcpy reports ~10x less CPU - including H.265 (fixed for Windows in 5.0.1), plus improved video buffering. Hardware decoding needs the Direct3D 11 renderer, which is now the default for new setups (a renderer you already chose is kept). A **Hardware decoding** switch (Display) turns it off if a graphics driver misbehaves

### Added
- **Stats overlay** (Misc Settings, off by default): live FPS of each screen, codec, bitrate and the connection (USB, or Wi-Fi with its round-trip time) in the corner of the stream; toggle with **Ctrl+Alt+I**. Click-through, never takes focus, and isn't recorded by OBS Window Capture
- **Scaling** (Display): Smooth (as before) or Sharp (nearest-neighbour, hard pixel edges). scrcpy has no option for this, so SplitCPY ships a small pass-through `SDL3.dll` (source in `native/sdl_scale_proxy`) that sets the filter on scrcpy's video texture; the real SDL is `bin/SDL3_real.dll`
- **Video codec: H.265 (experimental)** (Stream): more detail than H.264 at the same bitrate. Tested on the AYN Thor's hardware HEVC encoder at 1080p 60 FPS
- **VSync: Auto / On / Off** (Display): Auto keeps 1.0.1's behaviour (on for 100 Hz+ monitors); On / Off force it
- **Video buffer: Off / 50 ms / 100 ms** (Display): holds frames briefly and plays them out evenly, hiding short Wi-Fi hitches for that much extra delay (sound is delayed to match). For slower games; keep Off for precision platformers
- **Collapsible control panel**: click a section title to fold it away; SplitCPY remembers which are folded. The picture options (Scaling, VSync, Renderer, Hardware decoding) have their own **Display (this PC)** section and Settings is now **Misc Settings**
- **Opens centred, without jumping**: the stream and the control panel open side by side, centred on the monitor as a pair. The stream window is created in its final spot and the panel stays invisible until it's sized and placed, instead of both appearing elsewhere and moving a few seconds later
- **Faster start-up, one loading screen**: the loading screen now stays up (with the current step: looking for the device, starting streams, opening) until SplitCPY is actually on screen, and searches for the handheld while it's showing instead of waiting a fixed 2 s first. The pause before starting scrcpy is 0.2 s instead of 1 s, and the Wi-Fi lock is set up in the background
- **Enter confirms in the Wireless window**: Enter in the address / port boxes presses Connect Now, and in the pairing boxes presses Pair Device

### Fixed
- **Stopping a stream no longer kills other apps' background helpers on the handheld**: the cleanup ran `pkill -f app_process`, which also ended e.g. the Cocoon launcher's `AynGameObserver`; it now only ends scrcpy's server
- **Wi-Fi lock can't get stuck on**: SplitCPY sends the helper a heartbeat every 3 s and the helper quits by itself after 15 s without one, so a connection that dies silently (PC loses power, router drops) no longer leaves the handheld's Wi-Fi power save off. Any leftover helper is also ended when a new stream starts, not only when one stops

## SplitCPY 1.0.1 - 15-11-2026

### Fixed
- **Stutter with the Thor at 120 Hz**: while a stream at 60 FPS or less runs, the handheld's screens are switched to 60 Hz and your setting is put back on exit (or on the next connect after a crash). At 120 Hz games hand frames to the encoder unevenly and the 60 FPS cap discarded real frames - 47-56 FPS over USB vs a steady 58-60 at 60 Hz. Turn off with `"stream_at_60hz": false` in config.json
- **Tearing in fullscreen**: vsync is now on when the PC monitor runs at 100 Hz or more (costs at most one refresh, ~5 ms at 195 Hz); still off on 60 Hz monitors
- **Lag when the stream isn't focused**: SplitCPY and scrcpy opt out of Windows 11's background power throttling (EcoQoS / ignored timer resolution)
- **Wi-Fi stutter and audio dropouts**: over Wi-Fi the handheld's Wi-Fi power save is now switched off while streaming, via a tiny helper (`bin/splitcpy-wifilock.dex`, source in `android/wifilock`) that holds Android's high-performance Wi-Fi lock. Power save was batching packets, which showed up as sudden FPS collapses (e.g. 30 → 4 fps) with the audio cutting out. No root needed; the lock is released when the stream stops, and Android drops it automatically if SplitCPY crashes

## SplitCPY 1.0.0 - 15-11-2026

First release of SplitCPY, a fork of [DualCPY](https://github.com/theswest/DualCPY) 1.0.0 by the_swest.

### Added
- **View: Both / Top / Bottom** - the combined window is always exactly the game area (no black bars for OBS to capture): Both stacks the screens, Top / Bottom show one screen. Switching keeps the window height; dragging the edges keeps the shape
- **Fullscreen**: the game area is centred on the monitor at the largest size, over a separate black backdrop window that OBS's Window Capture never sees
- **Gap** slider between stacked screens
- **Global hotkeys** (work in-game): Ctrl+Alt+1 Both, Ctrl+Alt+2 Top, Ctrl+Alt+3 Bottom, Ctrl+Alt+S cycle, Ctrl+Alt+F fullscreen
- **Aspect presets by ratio** - the button shows the ratio (1:1, 3:2, 4:3 ... 80:51, sorted numerically) and a strip beside it lists the consoles using it ("3DS-B, Arcade, DC, DS, GC, MD, N64, ..."), scrollable sideways with the mouse wheel or by dragging. Cropping is done on the PC side, so it's instant and never restarts the stream
- **Profiles**: save the whole setup (view, aspect, gap, volume, audio, latency, FPS, split/combined); star one as default to load on start-up
- **Device profiles toggle** (Settings): off = always use the built-in AYN Thor profile, no device selector
- **Ctrl+Alt+M** shows/hides the control panel, even over fullscreen
- **120 FPS (experimental)** - bitrate scales with frame rate so 120 FPS frames stay sharp
- **Test Connection & Auto-Set**: measures the handheld-to-PC Wi-Fi (response time, jitter, throughput) and picks the lowest Latency setting that keeps audio clean
- **Waiting screen instead of a setup dialog**: with no device connected, DualCPY keeps looking and continues by itself the moment the Thor's Wireless debugging comes on (tip: add the Wireless debugging Quick Settings tile) - works after Thor or PC restarts with nothing to type
- **Easier pairing**: open "Pair device with pairing code" on the Thor and DualCPY fills in the address - just type the 6-digit code
- **Dim Thor screens** (switch or Ctrl+Alt+O): both handheld screens go to minimum brightness while you play on the monitor, through Android's per-display brightness (what AYN's own slider uses). Instant, no restart; each screen's brightness is restored when switched off, on exit, or after a crash on the next connect. (Powering panels off was tested and rejected: it blacks out or throttles the mirror to ~6 FPS, and the bottom panel ignores it)
- **(i) buttons**: explanations in the control panel are hidden by default and shown per section
- **Controller overlay (experimental)**: the Thor's controls drawn beside the bottom screen, lighting up live as you press them (read from the device over adb - nothing to install). Part of the stage window, so OBS captures it; the window widens just enough to fit. Idea, input handling and layout from [scrcpy-thor-ui](https://github.com/tommywaaf/scrcpy-thor-ui) by tommywaaf, rendering rewritten for SplitCPY
- **Renderer** setting: Direct3D 9 (default) or Direct3D 11 (can be smoother on Windows 11)
- **Bottom FPS** setting: same as top, or 30 to free the Thor's GPU for the top screen
- **F11** toggles fullscreen while DualCPY is in front (doesn't affect other apps)
- **Instant wireless connect**: on start-up a paired handheld is reconnected automatically (finds its current wireless-debugging port on the network, or uses the last address) - no dialog. Quick Connect and Pair now go straight into the streams instead of waiting for you to close the window; if the port changed, the new one is found automatically
- **Volume slider** (sets the stream's volume in the Windows mixer)
- **Audio output** setting: PC, Device (keep sound on the handheld) or Both (Android 13+)
- **Latency** setting: Low (default; 60 ms audio buffer on USB, 80 ms on Wi-Fi), Balanced, Stable
- **Quality** setting (Standard / High / Very High / Max) - video bitrate; the connection test picks the highest your link carries
- **Split Windows**: two independent windows you can move, resize (aspect-locked) and capture separately; closing one recombines them
- **Fit to Monitor**: maximise the window, or stack split windows as large as possible
- Auto-reconnect when a stream drops (up to 3 attempts)
- Split-mode screenshots (both windows stacked into one image)

### Changed
- New SplitCPY icon (app, taskbar, title bars, splash, README)
- Balanced latency now streams at full resolution and bitrate like Low - only the audio buffer is larger. Only Stable (for weak Wi-Fi) lowers resolution
- Reorganised control panel (View / Aspect / Audio & Stream / Tools / Profiles / Settings); manual position sliders, size slider and layout presets replaced by the self-fitting stage and Profiles
- Mouse wheel no longer changes slider values (it moved the volume while scrolling the panel)
- Window size and position are remembered between launches
- Changing FPS / audio / quality restarts just the streams, not the whole app - once, shortly after the last change
- Wi-Fi bitrate is tied to the Latency setting (Balanced/Stable use less bandwidth if audio warps)
- On exit the wireless connection is dropped and the bundled adb server is shut down (no more piled-up adb.exe)
- scrcpy and adb are tied to DualCPY with a Windows job object, so they always close with it - even after a crash

### Bugfixes
- Bottom screen took ~15 s to appear after a stream restart (e.g. after changing a setting or Test Connection): the top window was adopted before the start-up check could see it, so the check waited for its full timeout
- Blocky / soft picture after Test Connection picked Balanced on Wi-Fi (it also cut the stream to 1280x720 and 960x836)
- Black screens when a second copy of SplitCPY (or DualCPY) was already running: both copies found scrcpy windows by the same title, so the running copy took over the new copy's streams. Window titles are now unique per copy
- Only one SplitCPY runs at a time - opening it again brings the running one to the front (an app restart still works)
- Start-up: scrcpy windows open off-screen and are adopted within ~0.1 s (no flashing/jumping), and the control panel opens beside the stage instead of on top of it
- Ctrl+Alt+M could hide the panel instead of showing it while fullscreen
- Fullscreen / Split buttons are highlighted only while active
- Control panel opens flush against the stage (measures the visible frame, not Windows' invisible borders)
- Tidier control panel: one row of mode buttons; separate Stream (Quality, Top FPS, Bottom FPS, test/restart) and Audio (output, latency, volume) sections; experimental options (controller overlay, renderer) in Settings
- Switching the controller overlay off now clears the strips immediately (they lingered until the view changed)
- Control panel opens tall enough to show every option (90% of the screen on small monitors), with a tighter title area
- USB audio buffer raised to 60 ms + 15 ms output (30 ms clicked on dense music - measured by scrcpy-thor-ui)
- Screenshot button could crash the app (replaced dxcam with Windows screen capture; works on any monitor)
- Overlapping stream restarts could orphan scrcpy processes that kept playing audio in the background
- UI updates from background threads could crash Tk (now queued to the UI thread)
- Window borders appeared around the screens after leaving fullscreen (scrcpy/SDL re-adding its frame is now detected and removed)
- Status messages disappeared after the first one
- Running from source crashed on an incorrect `ui_constants` import
- Wireless-debugging (mDNS) serials weren't recognised as wireless

## 1.0.0 - 01-06-2026

> Note: **ThorCPY is now known as DualCPY.**

### Added
- Rebranded the project from ThorCPY to DualCPY, including a brand-new logo
- Complete UI port to customtkinter and redesign with a nicer design language in-mind
- Multi-device support:
  - Automatic device detection over ADB
  - Built-in device profiles for:
    - AYN Thor (Tested),
    - RG DS (Tested),
    - Pocket DS (Tested),
    - Odin 3 + RDS (Tested),
    - Odin 2 + RDS,
    - Odin 2 Portal + RDS,
    - Odin 2 Mini + RDS,
    - Retroid Pocket 6 + RDS,
    - Retroid Pocket G2 + RDS,
    - Retroid Pocket 5 + RDS,
    - Retroid Pocket 4 Pro + RDS
  - Custom user-defined device profiles
  - Device selector on launch with smart selection of the detected device
  - "Last used profile" is remembered in the config and auto-booted per-device
- Profile editor:
  - Ability to add custom profiles with different screen sizes
  - Support for devices with internal monitors on top/bottom
  - Per-profile custom scrcpy launch commands
- Per-device screen ratios are now calculated on boot to allow for any screen ratio
- Gamepad passthrough to the device (`--gamepad=uhid` on the top screen; disabled on the bottom)
  - You may have to reconnect your controller whilst DualCPY is running, this is due to a limitation with android
- FPS selector in the control panel (@tommywaaf)
- Restart button in the control panel (@tommywaaf)
- Added File Transfer window (@DrSkyfaR and @theswest):
  - Ability to transfer files from Windows -> DualCPY and vice versa via adb
  - Delete, rename, and create folders on the device
  - Windows quick-nav shortcuts: Home, Desktop, Downloads, Documents, Pictures
  - Device quick-nav shortcuts: Internal, Download, DCIM, Pictures, Music, Documents
  - Automatic SD card detection with quick-nav pills
  - Inline image previews with file metadata
- Redesigned splash screen with the new DualCPY logo
- App icon is now used as the window favicon across every window
- Additional default scrcpy launch flags: `--no-mipmaps`, `--no-power-on`, `--no-cleanup`
- Configurable screen-launch delay to support lower-powered devices
- Updated the bundled scrcpy version to scrcpy v4.0

### Changed
- Replaced the old Pygame menu with a fully reworked CustomTkinter control panel
- Backend improvements to heavily increase performance and decrease latency
- Undocked windows now have title bars, allowing resizing, reshaping and easier movement (@tommywaaf)
- Rebuilt the wireless connection dialog in CustomTkinter (previously tkinter)
- Added dedicated icon assets for the file browser
- Docked window title now reads "DualCPY | {device name}"
- Undocked window titles now read "{device name} - Top/Bottom Screen - DualCPY"
- Build is now bundled as onedir instead of onefile, improving launch speed on subsequent runs (@tommywaaf)
- Increased process priority for smoother mirroring (@tommywaaf)
- Major backend rework for clarity and conciseness:
  - Moved shared UI constants into their own module to prevent circular imports
  - Removed Thor-specific hardcoded constants from scrcpy_manager to allow for profiles
  - Relocated launch behaviour to be more accessible
- Improved launch codec and parameters (@tommywaaf)
- Improved video codec options (@tommywaaf)
- Improved scrcpy window launch commands (@tommywaaf)
- Improved bundled binary location handling (@tommywaaf)
- More resistant ADB server retry logic (@tommywaaf)
- Screens now only redraw when changes occur (@tommywaaf)
- Windows are now only re-docked when necessary (@tommywaaf)

### Bugfixes
- Fixed many display and rendering issues
- Fixed screenshots not working on built executables
- Undocked windows can now be resized and moved via their title bars (@tommywaaf)
- Fixed title-bar rendering scale when undocking, so windows no longer show borders after undocking (@tommywaaf)
- Fixed rendering size and scale for undocked windows

### Known Issues
- Restarting doesn't work when running from source 


## 0.3.0 - 15-02-2026
### Added
- Added Wireless Support
### Bugfixes
- Fixed issue where bottom screen displays incorrectly, causing non-transparency with screenshots
- Improved window handling to improve stability

## 0.2.0 - 31-01-2026
### Added
- Added ability to change Scrcpy Scale
- Better logging and error handling
### Bugfixes
- Fixed issue with Control Panel crashing on Windows 10 and improved Windows 10 Compatibility
- Updated codebase to become more refined
- Improved window management safeguards for Windows 10


## 0.1.1 - 28-01-2026
### Added
- Added incompatibility warning for Windows 10
- Add thread safety to window focus handling
- Improved dark mode support
### Bugfixes
- Fixed spacing on "DOCK WINDOWS" text 
- Debounce and throttle sync() calls


## 0.1.0 - 26-01-2026
### Added
- Dual-screen scrcpy docking
- Layout presets
- Screenshot capture
- Logging system
- PyInstaller build support
