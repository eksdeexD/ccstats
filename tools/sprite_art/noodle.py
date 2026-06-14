# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# NOODLE — the 32x32 cat. Sprite-art data module consumed by
# tools/build-avatar-frames.py (one file per sprite; see that tool's
# docstring for the format contract).
#
# All layers ported 1:1 from the OLD view/screens.js SPRITES.cat3 entry
# (label NOODLE, vb:32): two pointed ears with shaded right edges and a
# 3-step ear highlight, a rounded head tapering to a chin, a lit muzzle
# (hi) with a dark nose/mouth (dark), big round eyes, and 3D right-edge
# shade plus cheek/whisker shade rows. The eyes fragment is split by its
# rect class: class="w" -> eyes_white (kept as solid rects so the
# firmware's blink can squash them), class="p" -> eyes_pupil. happy holds
# the closed "smiling" eyes for the done flourish. cat3 has no mouth layer.

SPRITE = {
    "name": "noodle",
    "label": "NOODLE",
    "roster_index": 4,  # AV_SPRITES order in screens.js (GLOOM 0, DIMPLE 1, VOLT 2, MISO 3, NOODLE 4, BLIP 5, ...)
    "grid_cells": 32,   # the SVG viewBox (32 -> 3.5 px cells in the 112px box)
    # top-left of the 12x16 sweat bead, DEVICE px in the neutral 112px box,
    # sitting on the head's right slope at forehead height (rides the squash
    # transform at draw). A cat has ears, so the head "top" is the skull
    # between the ears, not the ear tips: the fill's first continuous brow
    # row is cell y=9, right edge cell x=27. bead left = round(27*3.5) - 8 =
    # 95 - 8 = 87; bead top = round(9*3.5) + 2 = 32 + 2 = 34. (The old web
    # AV_SWEAT cat3:[24,9] floats off the head; this sits the bead ON it.)
    "sweat_anchor": (87, 34),
    "layers": {
        "fill": ((7, 2, 2, 1), (6, 3, 4, 1), (6, 4, 5, 1), (5, 5, 7, 1), (5, 6, 8, 1),
                 (5, 7, 9, 1), (5, 8, 10, 1),
                 (23, 2, 2, 1), (22, 3, 4, 1), (21, 4, 5, 1), (20, 5, 7, 1), (19, 6, 8, 1),
                 (18, 7, 9, 1), (17, 8, 10, 1),
                 (5, 9, 22, 1), (4, 10, 24, 14), (5, 24, 22, 1), (7, 25, 18, 1), (9, 26, 14, 1),
                 (12, 27, 8, 1), (14, 28, 4, 1)),
        "shade": ((7, 2, 1, 1), (6, 3, 1, 1), (6, 4, 1, 1), (5, 5, 1, 1), (5, 6, 1, 1),
                  (5, 7, 1, 1), (5, 8, 1, 1),
                  (24, 2, 1, 1), (25, 3, 1, 1), (25, 4, 1, 1), (26, 5, 1, 1), (26, 6, 1, 1),
                  (26, 7, 1, 1), (26, 8, 1, 1),
                  (11, 12, 1, 3), (14, 11, 1, 4), (17, 11, 1, 4), (20, 12, 1, 3),
                  (4, 20, 5, 1), (4, 22, 5, 1), (4, 24, 5, 1),
                  (23, 20, 5, 1), (23, 22, 5, 1), (23, 24, 5, 1),
                  (25, 11, 2, 13), (7, 25, 18, 1), (16, 27, 3, 1)),
        "hi": ((7, 4, 2, 1), (7, 5, 3, 1), (6, 6, 5, 1), (6, 7, 5, 1),
               (23, 4, 2, 1), (22, 5, 3, 1), (21, 6, 5, 1), (21, 7, 5, 1),
               (12, 20, 8, 1), (10, 21, 12, 1), (10, 22, 12, 1), (11, 23, 10, 1), (13, 24, 6, 1)),
        "dark": ((14, 20, 4, 1), (15, 21, 2, 1), (15, 22, 2, 1), (14, 23, 1, 1), (17, 23, 1, 1),
                 (12, 24, 2, 1), (18, 24, 2, 1)),
        "eyes_white": ((10, 15, 3, 1), (9, 16, 5, 4), (10, 20, 3, 1),
                       (19, 15, 3, 1), (18, 16, 5, 4), (19, 20, 3, 1)),
        "eyes_pupil": ((10, 17, 3, 3), (19, 17, 3, 3)),
        "happy": ((9, 17, 2, 1), (11, 16, 2, 1), (13, 17, 2, 1),
                  (17, 17, 2, 1), (19, 16, 2, 1), (21, 17, 2, 1)),
    },
}
