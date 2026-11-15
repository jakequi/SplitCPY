# Changelog

## DualCPY Split 1.0.0 - 15-11-2026

First release of DualCPY Split, a fork of [DualCPY](https://github.com/theswest/DualCPY) 1.0.0 by the_swest.

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
- **Controller overlay (experimental)**: the Thor's controls drawn beside the bottom screen, lighting up live as you press them (read from the device over adb - nothing to install). Part of the stage window, so OBS captures it; the window widens just enough to fit. Idea, input handling and layout from [scrcpy-thor-ui](https://github.com/tommywaaf/scrcpy-thor-ui) by tommywaaf, rendering rewritten for DualCPY Split
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
- Reorganised control panel (View / Aspect / Audio & Stream / Tools / Profiles / Settings); manual position sliders, size slider and layout presets replaced by the self-fitting stage and Profiles
- Mouse wheel no longer changes slider values (it moved the volume while scrolling the panel)
- Window size and position are remembered between launches
- Changing FPS / audio / quality restarts just the streams, not the whole app - once, shortly after the last change
- Wi-Fi bitrate is tied to the Latency setting (Balanced/Stable use less bandwidth if audio warps)
- On exit the wireless connection is dropped and the bundled adb server is shut down (no more piled-up adb.exe)
- scrcpy and adb are tied to DualCPY with a Windows job object, so they always close with it - even after a crash

### Bugfixes
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
