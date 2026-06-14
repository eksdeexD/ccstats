# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# MISO — the cat. Sprite-art data module consumed by
# tools/build-avatar-frames.py (one file per sprite; see that tool's
# docstring for the format contract).
#
# Ported 1:1 from the OLD web registry view/screens.js SPRITES.cat
# (label 'MISO'): two triangular ears + a round-ish head, two tall eyes
# with pupils, a 3D right-edge shade, a forehead highlight, and the closed
# happy eyes / little "v" nose shown during the done flourish. The eyes
# fragment is split by its rect class: class="w" -> eyes_white (kept as
# solid rects so the firmware's blink can squash them), class="p" ->
# eyes_pupil. 16-cell grid (no vb:), so cell -> px = 7 in the 112px box.

SPRITE = {
    "name": "miso",
    "label": "MISO",
    "roster_index": 3,  # AV_SPRITES order in screens.js (GLOOM 0, DIMPLE 1, VOLT 2, MISO 3, ...)
    "grid_cells": 16,   # the SVG viewBox (16 -> 7 px cells in the 112px box)
    # top-left of the 12x16 sweat bead, DEVICE px in the neutral 112px box,
    # sitting on the head's right slope (rides the squash transform at draw).
    # A cat has ears, so the head top is the skull/forehead BETWEEN the ears,
    # not the ear tips: the forehead's top row is cell y=2 -> 14 px, and its
    # right edge there is cell x=4+8=12 -> 84 px. Bead left = 84 - 8 = 76,
    # bead top = forehead top (14 px) + 2 = 16, so the bead overlaps the
    # head's right slope at forehead height (same correction as GLOOM's
    # [12,1] -> (63,16); the old web AV_SWEAT cat:[12,3] floated off the head).
    "sweat_anchor": (76, 16),
    "layers": {
        # two ears (base + tip) + forehead taper + head body + chin taper
        "fill": ((3, 1, 2, 2), (11, 1, 2, 2), (3, 0, 1, 1), (12, 0, 1, 1),
                 (4, 2, 8, 1), (3, 3, 10, 1), (2, 4, 12, 8), (3, 12, 10, 1), (4, 13, 8, 1)),
        "shade": ((13, 4, 1, 8), (4, 12, 9, 1)),
        "hi": ((3, 1, 1, 2), (2, 4, 10, 1)),
        "eyes_white": ((4, 6, 2, 3), (9, 6, 2, 3)),
        "eyes_pupil": ((5, 7, 1, 2), (9, 7, 1, 2)),
        "happy": ((6, 9, 1, 1), (7, 10, 2, 1), (9, 9, 1, 1), (7, 8, 2, 1)),
    },
}
