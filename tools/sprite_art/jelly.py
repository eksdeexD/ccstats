# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# JELLY — the 32x32 squishy slime/blob. Sprite-art data module consumed by
# tools/build-avatar-frames.py (one file per sprite; see that tool's
# docstring for the format contract).
#
# All layers ported 1:1 from the OLD view/screens.js SPRITES.jelly entry
# (label JELLY, vb:32): a rounded blob dome that flares out to a wide wobbly
# base, a 2-step left shine (hi), a 3D right-edge shade plus a base shade row,
# small notched eyes, and a wide grinning happy mouth. The eyes fragment is
# split by its rect class: class="w" -> eyes_white (kept as solid rects so the
# firmware's blink can squash them), class="p" -> eyes_pupil. happy holds the
# closed "smiling" eyes plus a grin for the done flourish. jelly has no mouth
# layer and no dark layer.

SPRITE = {
    "name": "jelly",
    "label": "JELLY",
    "roster_index": 7,  # AV_SPRITES order in screens.js (GLOOM 0, DIMPLE 1, VOLT 2, MISO 3, NOODLE 4, BLIP 5, SPARKLY 6, JELLY 7)
    "grid_cells": 32,   # the SVG viewBox (32 -> 3.5 px cells in the 112px box)
    # top-left of the 12x16 sweat bead, DEVICE px in the neutral 112px box,
    # sitting on the blob's upper-right slope (rides the squash transform at
    # draw). A blob has no distinct head, so the dome crown is treated as the
    # head top: the fill's ink top is cell y=9 -> round(9*3.5)=32 px. In the
    # body's upper third the right slope runs out to cell x=23 (at y=14) ->
    # round(23*3.5)=80 px. bead left = 80 - 8 = 72; bead top = 32 + 2 = 34.
    # (The old web AV_SWEAT jelly:[21,10] floats off the body; this sits the
    # bead ON the upper-right slope per the GLOOM/DIMPLE/NOODLE precedent.)
    "sweat_anchor": (72, 34),
    "layers": {
        "fill": ((14, 9, 4, 1), (13, 10, 6, 1), (12, 11, 8, 1), (11, 12, 10, 1),
                 (10, 13, 12, 1), (9, 14, 14, 1), (8, 15, 16, 1), (8, 16, 16, 1),
                 (7, 17, 18, 1), (6, 18, 20, 7), (7, 25, 18, 1)),
        "shade": ((24, 16, 2, 9), (7, 24, 18, 1)),
        "hi": ((12, 11, 3, 2), (10, 13, 2, 2)),
        "eyes_white": ((11, 17, 3, 4), (18, 17, 3, 4)),
        "eyes_pupil": ((12, 18, 2, 2), (19, 18, 2, 2)),
        "happy": ((11, 18, 1, 1), (12, 17, 1, 1), (13, 18, 1, 1),
                  (18, 18, 1, 1), (19, 17, 1, 1), (20, 18, 1, 1),
                  (13, 21, 1, 1), (14, 22, 4, 1), (18, 21, 1, 1)),
    },
}
