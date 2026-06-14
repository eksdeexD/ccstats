# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# BLIP — the CRT terminal. Sprite-art data module consumed by
# tools/build-avatar-frames.py (one file per sprite; see that tool's
# docstring for the format contract).
#
# All layers ported 1:1 from the OLD view/screens.js SPRITES.blip entry
# (label BLIP, vb:32): a boxy CRT casing with a beveled top/left highlight,
# a 3D right/bottom-edge shade, a recessed dark screen, two pixel eyes on
# the screen, and a little stand. The eyes fragment is split by its rect
# class: class="w" -> eyes_white (kept as solid rects so the firmware's
# blink can squash the whole group), class="p" -> eyes_pupil.
#
# happy holds the lit-up smiley shown during the done flourish. On the web,
# BLIP's smiley glows CREAM instead of ink
# (.avatar-screen[data-avatar="blip"] .av-happy rect{fill:var(--cream)} in
# view/screens.css) — the face lights up on the CRT screen rather than being
# drawn in ink. "happy_pen": "text" below tells the generator to pen the
# happy layer in the cream/text colour for this sprite (see note in report).

SPRITE = {
    "name": "blip",
    "label": "BLIP",
    "roster_index": 5,  # AV_SPRITES order in screens.js (GLOOM 0, DIMPLE 1, VOLT 2, MISO 3, NOODLE 4, BLIP 5, ...)
    "grid_cells": 32,   # the SVG viewBox (32 -> 3.5 px cells in the 112px box)
    # top-left of the 12x16 sweat bead, DEVICE px in the neutral 112px box,
    # sitting on the casing's right slope near the top (rides the squash
    # transform at draw). Derived from the fill silhouette: the casing is the
    # single rect (4,4,24,18); its right edge in the upper third is cell
    # x=4+24=28 -> 28*3.5 = 98 px, so bead left = 98 - 8 = 90; bead top =
    # casing-ink top (cell y=4 -> 14 px) + 2 -> 16.
    "sweat_anchor": (90, 16),
    # BLIP's done-smiley GLOWS: the web lights the happy layer in CREAM
    # (--cream) instead of ink, so the face appears to light up on the CRT
    # screen. The badge pens it eye_white — the fixed cream that does not
    # follow a palette's text slot (M5 eye-white decision; a dark-text
    # palette must not unlight the smiley).
    "happy_pen": "eye_white",
    "layers": {
        "fill": ((4, 4, 24, 18), (14, 22, 4, 2), (9, 24, 14, 3)),
        "shade": ((26, 5, 2, 17), (9, 26, 14, 1), (21, 24, 2, 2)),
        "hi": ((4, 4, 24, 1), (4, 5, 1, 16)),
        "dark": ((7, 7, 18, 12),),
        "eyes_white": ((10, 10, 3, 4), (19, 10, 3, 4)),
        "eyes_pupil": ((11, 11, 2, 2), (20, 11, 2, 2)),
        "happy": ((11, 9, 2, 3), (19, 9, 2, 3), (11, 15, 1, 1), (20, 15, 1, 1), (12, 16, 8, 1)),
    },
}
