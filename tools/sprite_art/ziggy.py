# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# ZIGGY — the 32x32 alien. Sprite-art data module consumed by
# tools/build-avatar-frames.py (one file per sprite; see that tool's
# docstring for the format contract).
#
# All layers ported 1:1 from the OLD view/screens.js SPRITES.ziggy entry
# (label ZIGGY, vb:32): a wide bulb head tapering to a narrow neck, a slim
# body with two stick arms and two legs, a 3D right-edge shade on head and
# body, a 2-step left highlight, and big almond eyes. The eyes fragment is
# split by its rect class: in screens.css `.av-eyes rect.w{fill:cream}` and
# `.av-eyes rect.p{fill:ink}`, so for this alien the big almond eyes are the
# DARK class="p" rects (-> eyes_pupil) and the only class="w" rects are two
# tiny 1x1 cream glints (-> eyes_white, kept solid so the blink can squash
# the whole eye group). happy holds the closed "smiling" eyes for the done
# flourish. ziggy has no dark or mouth layer.

SPRITE = {
    "name": "ziggy",
    "label": "ZIGGY",
    "roster_index": 9,  # AV_SPRITES order in screens.js
    "grid_cells": 32,   # the SVG viewBox (32 -> 3.5 px cells in the 112px box)
    # top-left of the 12x16 sweat bead, DEVICE px in the neutral 112px box,
    # sitting on the bulb head's right slope at forehead height (rides the
    # squash transform at draw). Derived from the fill silhouette: the bulb's
    # right edge in the upper third is cell x=24 (row y=7 -> 8+16) -> 24*3.5 =
    # 84 px; bead left = 84 - 8 = 76. Head-ink top is cell y=4 -> 4*3.5 = 14
    # px; bead top = 14 + 2 = 16. (The old web AV_SWEAT ziggy:[23,5] floats
    # off the head; this sits the bead ON the bulb's right slope.)
    "sweat_anchor": (76, 16),
    # the source paints the dark almonds (class p) FIRST and the two cream
    # glints (class w) on top — the inverse of every other sprite's
    # sclera-under-pupil order. Draw eyes_white last so the glints survive.
    "eyes_white_on_top": True,
    "layers": {
        "fill": ((12, 4, 8, 1), (10, 5, 12, 1), (9, 6, 14, 1), (8, 7, 16, 1), (7, 8, 18, 4),
                 (8, 12, 16, 1), (9, 13, 14, 1), (11, 14, 10, 1), (14, 15, 4, 1),
                 (12, 16, 8, 6), (9, 17, 3, 4), (20, 17, 3, 4), (12, 22, 2, 4), (18, 22, 2, 4)),
        "shade": ((23, 8, 2, 4), (18, 16, 2, 6)),
        "hi": ((12, 4, 6, 1), (9, 6, 1, 2)),
        "eyes_white": ((10, 8, 1, 1), (21, 8, 1, 1)),
        "eyes_pupil": ((9, 8, 5, 2), (10, 10, 4, 1), (18, 8, 5, 2), (18, 10, 4, 1)),
        "happy": ((9, 10, 1, 1), (10, 9, 3, 1), (13, 10, 1, 1), (18, 10, 1, 1), (19, 9, 3, 1),
                  (22, 10, 1, 1), (15, 13, 2, 1)),
    },
}
