# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# PIP — the 32x32 round-eared critter (owl/dog — deliberately ambiguous).
# Sprite-art data module consumed by tools/build-avatar-frames.py (one file
# per sprite; see that tool's docstring for the format contract).
#
# All layers ported 1:1 from the OLD view/screens.js SPRITES.pip entry
# (label PIP, vb:32): two round ears, a rounded head tapering to a chin, a
# 3D right-edge shade (the right ear reads as shaded too), a left highlight
# edge, a small nose/mouth, big round eyes, and the happy "smiling" eyes for
# the done flourish. The eyes fragment is split by its rect class:
# class="w" -> eyes_white (kept as solid rects so the firmware's blink can
# squash the whole group), class="p" -> eyes_pupil.

SPRITE = {
    "name": "pip",
    "label": "PIP",
    "roster_index": 6,  # AV_SPRITES order in screens.js (GLOOM 0, DIMPLE 1, VOLT 2, MISO 3, NOODLE 4, BLIP 5, PIP 6)
    "grid_cells": 32,   # the SVG viewBox (32 -> 3.5 px cells in the 112px box)
    # top-left of the 12x16 sweat bead, DEVICE px in the neutral 112px box,
    # sitting on the head's right slope at forehead height (rides the squash
    # transform at draw). PIP has round EARS, so the head "top" is the skull
    # between the ears, not the ear tips (the cat rule): the fill's first
    # continuous brow block is cell y=9, right edge cell x=25. bead left =
    # round(25*3.5) - 8 = 88 - 8 = 80; bead top = round(9*3.5) + 2 = 32 + 2 =
    # 34. (The old web AV_SWEAT pip:[23,5] floats off the head; this sits the
    # bead ON it.)
    "sweat_anchor": (80, 34),
    "layers": {
        "fill": ((9, 5, 3, 3), (20, 5, 3, 3), (10, 7, 12, 1), (8, 8, 16, 1),
                 (7, 9, 18, 14), (8, 23, 16, 1), (10, 24, 12, 1)),
        "shade": ((23, 10, 2, 13), (9, 23, 15, 1), (20, 5, 3, 3)),
        "hi": ((9, 5, 1, 3), (8, 9, 14, 1)),
        "mouth": ((15, 17, 2, 2), (14, 19, 1, 1), (17, 19, 1, 1)),
        "eyes_white": ((8, 10, 7, 7), (17, 10, 7, 7)),
        "eyes_pupil": ((10, 12, 3, 3), (19, 12, 3, 3)),
        "happy": ((8, 14, 2, 1), (10, 13, 2, 1), (12, 14, 2, 1),
                  (17, 14, 2, 1), (19, 13, 2, 1), (21, 14, 2, 1)),
    },
}
