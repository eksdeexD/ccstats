# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# VOLT — the square-headed robot. Sprite-art data module consumed by
# tools/build-avatar-frames.py (one file per sprite; see that tool's
# docstring for the format contract).
#
# Ported 1:1 from the OLD web registry view/screens.js SPRITES.robot
# (label 'VOLT'): antenna + square head, two square eyes with pupils, and
# the closed happy eyes (two notched "∪" arcs) shown during the done
# flourish. 16-cell grid (no vb:), so cell -> px = 7 in the 112px box.

SPRITE = {
    "name": "volt",
    "label": "ZAP",
    "roster_index": 2,  # AV_SPRITES order in screens.js (GLOOM 0, DIMPLE 1, VOLT 2, ...)
    "grid_cells": 16,   # the SVG viewBox (16 -> 7 px cells in the 112px box)
    # top-left of the 12x16 sweat bead, DEVICE px in the neutral 112px box,
    # sitting on the head's right slope (rides the squash transform at draw).
    # Square head right edge is cell 14 -> 98 px; bead left = 98 - 8 = 90,
    # bead top = head top (cell 2 -> 14 px) + 2 = 16, so the bead overlaps
    # the dome's right edge at forehead height.
    "sweat_anchor": (90, 16),
    "layers": {
        # antenna (tip + stalk) + square head body + two chin tabs
        "fill": ((7, 0, 2, 2), (6, 1, 4, 1), (2, 2, 12, 11), (3, 13, 3, 1), (10, 13, 3, 1)),
        "shade": ((13, 3, 1, 10), (3, 12, 10, 1)),
        "hi": ((2, 2, 11, 1), (2, 3, 1, 2)),
        "eyes_white": ((4, 5, 3, 3), (9, 5, 3, 3)),
        "eyes_pupil": ((5, 6, 1, 1), (10, 6, 1, 1)),
        "happy": ((5, 10, 6, 1), (4, 9, 1, 1), (11, 9, 1, 1)),
    },
}
