# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# GLOOM — the default ghost. Sprite-art data module consumed by
# tools/build-avatar-frames.py (one file per sprite; see that tool's
# docstring for the format contract).
#
# fill/shade/hi/eyes ported from viewscreens/screens.js drawSprite(); the happy
# eyes (two pixel "∪" arcs, shown during the done flourish) from the OLD
# view/screens.js SPRITES.ghost.

SPRITE = {
    "name": "gloom",
    "label": "GLOOM",
    "roster_index": 0,  # AV_SPRITES order in screens.js
    "grid_cells": 16,   # the SVG viewBox (16 -> 7 px cells in the 112px box)
    # top-left of the 12x16 sweat bead, DEVICE px in the neutral 112px box,
    # sitting on the head's right slope (rides the squash transform at draw)
    "sweat_anchor": (63, 16),
    "layers": {
        "fill": ((5, 2, 5, 1), (4, 3, 7, 1), (3, 4, 9, 1), (2, 5, 11, 1), (2, 6, 11, 1),
                 (2, 7, 11, 1), (2, 8, 11, 1), (2, 9, 11, 1), (2, 10, 11, 1), (2, 11, 11, 1),
                 (2, 12, 2, 2), (5, 12, 2, 2), (8, 12, 2, 2), (11, 12, 2, 2)),
        "shade": ((12, 5, 1, 7), (11, 12, 2, 2)),
        "hi": ((4, 3, 2, 1), (3, 4, 1, 2)),
        "eyes_white": ((4, 5, 2, 3), (9, 5, 2, 3)),
        "eyes_pupil": ((5, 6, 1, 2), (9, 6, 1, 2)),
        "happy": ((4, 6, 1, 1), (5, 5, 1, 1), (6, 6, 1, 1), (8, 6, 1, 1), (9, 5, 1, 1), (10, 6, 1, 1)),
    },
}
