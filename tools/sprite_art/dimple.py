# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# DIMPLE — the 32x32 dome ghost. Sprite-art data module consumed by
# tools/build-avatar-frames.py (one file per sprite; see that tool's
# docstring for the format contract).
#
# All layers ported 1:1 from the OLD view/screens.js SPRITES.ghost2 entry
# (label DIMPLE, vb:32): a rounded dome with a 3-step shine, a right nub,
# big notched eyes, a black smile, a 3D right-edge shade, and a spiky skirt.
# The eyes fragment is split by its rect class: class="w" -> eyes_white
# (kept as solid rects so the firmware's blink can squash them), class="p"
# -> eyes_pupil. happy holds the closed "smiling" eyes for the done flourish.

SPRITE = {
    "name": "dimple",
    "label": "DIMPLE",
    "roster_index": 1,  # AV_SPRITES order in screens.js (GLOOM 0, DIMPLE 1, VOLT 2, ...)
    "grid_cells": 32,   # the SVG viewBox (32 -> 3.5 px cells in the 112px box)
    # top-left of the 12x16 sweat bead, DEVICE px in the neutral 112px box,
    # sitting on the dome's right slope at forehead height (rides the squash
    # transform at draw). Derived from the fill silhouette: the dome's right
    # edge near the top is cell x=24 -> 84 px; bead left = 84 - 8 = 76, and
    # bead top = dome top (cell y=3 -> 10.5 px) + ~2 -> 12.
    "sweat_anchor": (76, 12),
    "layers": {
        "fill": ((11, 3, 10, 1), (9, 4, 14, 1), (8, 5, 16, 1), (7, 6, 18, 1), (6, 7, 20, 1),
                 (5, 8, 22, 1), (5, 9, 22, 1), (4, 10, 24, 14), (22, 2, 2, 5),
                 (4, 24, 3, 2), (8, 24, 4, 2), (14, 24, 4, 2), (20, 24, 4, 2), (25, 24, 3, 2),
                 (5, 26, 1, 1), (9, 26, 2, 1), (15, 26, 2, 1), (21, 26, 2, 1), (26, 26, 1, 1)),
        "shade": ((26, 8, 1, 2), (27, 10, 1, 14), (26, 24, 2, 2), (26, 26, 1, 1), (23, 24, 1, 2)),
        "hi": ((12, 4, 2, 2), (10, 6, 2, 2), (8, 8, 2, 2)),
        "mouth": ((11, 19, 2, 1), (19, 19, 2, 1), (12, 20, 2, 1), (18, 20, 2, 1), (13, 21, 6, 1)),
        "eyes_white": ((11, 10, 2, 1), (9, 11, 6, 5), (10, 16, 4, 1),
                       (19, 10, 2, 1), (17, 11, 6, 5), (18, 16, 4, 1)),
        "eyes_pupil": ((10, 13, 3, 3), (19, 13, 3, 3)),
        "happy": ((9, 15, 2, 1), (13, 15, 2, 1), (10, 14, 2, 1), (12, 14, 2, 1), (11, 13, 2, 1),
                  (17, 15, 2, 1), (21, 15, 2, 1), (18, 14, 2, 1), (20, 14, 2, 1), (19, 13, 2, 1)),
    },
}
