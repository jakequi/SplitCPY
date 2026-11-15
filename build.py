# DualCPY Split - dual-screen scrcpy launcher for the AYN Thor and other handhelds
# Copyright (C) 2026 the_swest (original DualCPY) and DualCPY Split contributors
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

# build.py

import PyInstaller.__main__

# NOTE: config/ and logs/ are deliberately NOT bundled - they hold the
# builder's personal settings (device IPs/serials) and session logs. The app
# creates both next to the exe on first run.

PyInstaller.__main__.run(
    [
        "main.py",
        "--onedir",
        "--noconsole",
        "--clean",
        "--name=DualCPY-Split",
        "--add-data=bin;bin",
        "--add-data=assets/fonts;assets/fonts",
        "--add-data=assets/icon.png;assets",
        "--add-data=assets/icon.ico;assets",
        "--add-data=assets/icons;assets/icons",
        "--icon=assets/icon.ico",
        "-y",
    ]
)
