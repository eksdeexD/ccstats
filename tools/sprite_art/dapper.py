# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# DAPPER — the 32x32 penguin. Sprite-art data module consumed by
# tools/build-avatar-frames.py (one file per sprite; see that tool's
# docstring for the format contract).
#
# All layers ported 1:1 from view/screens.js SPRITES.dapper entry (label
# DAPPER, vb:32): a dark rounded body with two stubby side flippers, a light
# belly (the hi layer, per the designer's comment), a small beak and two feet
# (the mouth layer — drawn with the dark background pen, matching the web's
# .av-mouth rect{ fill:var(--ink) } which has NO data-avatar="dapper" special),
# a right-edge 3D shade, round eyes, and a happy "^ ^" for the done flourish.
# The eyes fragment is split by its rect class: class="w" -> eyes_white (kept
# as solid rects so the firmware's blink can squash them), class="p" ->
# eyes_pupil. dapper has no dark layer.

SPRITE = {
    "name": "dapper",
    "label": "DAPPER",
    "roster_index": 8,  # AV_SPRITES order in screens.js (GLOOM 0, DIMPLE 1, VOLT 2, MISO 3, NOODLE 4, BLIP 5, ..., DAPPER 8)
    "grid_cells": 32,   # the SVG viewBox (32 -> 3.5 px cells in the 112px box)
    # top-left of the 12x16 sweat bead, DEVICE px in the neutral 112px box,
    # sitting on the head/body's right slope in the upper third (rides the
    # squash transform at draw). The web AV_SWEAT dapper:[22,3] floats off the
    # head; this sits the bead ON it, per the GLOOM/DIMPLE/NOODLE rule. The
    # fill's upper-third rounded row is cell (9,6,14,4): right edge cell x=23 ->
    # round(23*3.5)=80 px, bead left = 80 - 8 = 72; head-ink top is cell y=4 ->
    # round(4*3.5)=14 px, bead top = 14 + 2 = 16.
    "sweat_anchor": (72, 16),
    "layers": {
        "fill": ((12, 4, 8, 1), (10, 5, 12, 1), (9, 6, 14, 4), (8, 10, 16, 14),
                 (9, 24, 14, 2), (5, 13, 2, 9), (25, 13, 2, 9)),
        "shade": ((22, 10, 2, 14), (9, 25, 14, 1)),
        "hi": ((12, 13, 8, 11), (11, 15, 1, 7), (20, 15, 1, 7)),
        "mouth": ((15, 10, 2, 1), (16, 11, 1, 1), (10, 26, 4, 2), (18, 26, 4, 2)),
        "eyes_white": ((11, 7, 3, 3), (18, 7, 3, 3)),
        "eyes_pupil": ((12, 8, 2, 2), (19, 8, 2, 2)),
        "happy": ((11, 8, 1, 1), (12, 7, 1, 1), (13, 8, 1, 1),
                  (18, 8, 1, 1), (19, 7, 1, 1), (20, 8, 1, 1)),
    },
}
