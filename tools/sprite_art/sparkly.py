# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# SPARKLY — the faceless Claude spark. Sprite-art data module consumed by
# tools/build-avatar-frames.py (one file per sprite; see that tool's
# docstring for the format contract).
#
# Ported 1:1 from view/screens.js SPRITES.spark (label 'SPARKLY', vb:32):
# a big four-armed spark (stacked widening rects around the centre) with
# four tiny child-sparkle dots, a right/lower shade and a 2-step shine.
# Deliberately NO face — the source's eyes and happy fragments are empty,
# so those layers are omitted (the animator guards empty eye groups: no
# blink, no happy swap).
#
# Per-sprite specials (the web's data-avatar="spark" CSS overrides):
# stress sheds an amber EMBER instead of the blue sweat bead (.swt-ember),
# and the done twinkles are amber (avatar_light) instead of the default
# green (.av-spark i{background:var(--avatar-l)}).

SPRITE = {
    "name": "sparkly",
    "label": "FLICK",
    "roster_index": 10,  # AV_SPRITES order in screens.js (SPARKLY is last)
    "grid_cells": 32,    # the SVG viewBox (32 -> 3.5 px cells in the 112px box)
    # top-left of the 12x16 ember, DEVICE px in the neutral 112px box, ON the
    # spark's upper-right arm (rides the squash transform at draw). The web
    # AV_SWEAT spark:[22,3] anchors to the stage and floats off the ink; per
    # the GLOOM rule the ember sits on ink instead: the upper ink at ember
    # height is the top arm (right edge cell 17 -> 59.5 ~ 60 px), so ember
    # left = 60 - 8 = 52, and top = arm top (cell 4 -> 14 px) + 2 = 16.
    "sweat_anchor": (52, 16),
    # stress drop art: amber ember instead of the blue bead (web .swt-ember)
    "stress_marker": "ember",
    # done twinkles in amber instead of the default green (web --avatar-l)
    "sparkle_pen": "avatar_light",
    "layers": {
        # the four-armed spark: vertical + horizontal bars, the widening
        # diamond body, then the four child-sparkle dots
        "fill": ((15, 4, 2, 24), (4, 15, 24, 2), (15, 6, 2, 20), (14, 8, 4, 16),
                 (13, 11, 6, 10), (6, 15, 20, 2), (8, 14, 16, 4), (11, 13, 10, 6),
                 (20, 6, 1, 1), (11, 6, 1, 1), (6, 22, 1, 1), (25, 9, 1, 1)),
        "shade": ((16, 17, 2, 9), (17, 16, 9, 1), (16, 13, 2, 3)),
        "hi": ((13, 11, 3, 2), (11, 13, 2, 2)),
    },
}
