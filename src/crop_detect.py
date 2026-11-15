# DualCPY Split - game area detection
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

# src/crop_detect.py
"""Find the game picture inside black bars, from a screenshot of a viewport."""

import numpy as np

FULL_CROP = (0.0, 0.0, 1.0, 1.0)

# Pixels brighter than this count as "picture" (bars are pure/near black)
BLACK_THRESHOLD = 24
# A row/column is part of the picture if this fraction of it is non-black
MIN_LINE_FILL = 0.01
# Treat anything this close to the full frame as "no bars"
FULL_TOLERANCE = 0.97
# Reject results smaller than this fraction of the frame area
MIN_AREA = 0.08
# Pixels at the capture edge to ignore (window border / rounded corners)
EDGE_MARGIN = 2


def detect_content(img, full_aspect):
    """
    `img` is a capture of a viewport currently showing the FULL frame (scrcpy
    letterboxes it to fit). Returns the picture's crop as
    (left, top, right, bottom) fractions of the full frame, FULL_CROP if
    there are no bars, or None if nothing usable was found (e.g. a black
    screen).
    """
    w, h = img.size
    if w < 8 or h < 8:
        return None

    # Where scrcpy drew the full frame inside the viewport
    if w / h > full_aspect:
        fh, fw = h, h * full_aspect
    else:
        fw, fh = w, w / full_aspect
    ox, oy = (w - fw) / 2, (h - fh) / 2

    gray = np.asarray(img.convert("L"), dtype=np.uint8)
    mask = gray > BLACK_THRESHOLD
    # Ignore the outermost pixels: Windows 11 draws the window border and
    # rounded corners there, which would otherwise count as "picture"
    m = EDGE_MARGIN
    mask[:m, :] = False
    mask[-m:, :] = False
    mask[:, :m] = False
    mask[:, -m:] = False
    cols = np.flatnonzero(mask.mean(axis=0) > MIN_LINE_FILL)
    rows = np.flatnonzero(mask.mean(axis=1) > MIN_LINE_FILL)
    if cols.size == 0 or rows.size == 0:
        return None

    x0, x1 = cols[0], cols[-1] + 1
    y0, y1 = rows[0], rows[-1] + 1

    def clamp(v):
        return min(1.0, max(0.0, v))

    # Step in by one display pixel so a soft scaled edge doesn't leave a dark line
    left = clamp((x0 - ox + 1) / fw)
    right = clamp((x1 - ox - 1) / fw)
    top = clamp((y0 - oy + 1) / fh)
    bottom = clamp((y1 - oy - 1) / fh)

    if right - left <= 0 or bottom - top <= 0:
        return None
    if (right - left) * (bottom - top) < MIN_AREA:
        return None
    if right - left >= FULL_TOLERANCE and bottom - top >= FULL_TOLERANCE:
        return FULL_CROP
    return (left, top, right, bottom)
