#!/usr/bin/env python3
# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

"""Generate the avatar frame modules — pre-squashed sprite frames, one set
per sprite-art module in tools/sprite_art/.

OUTPUT LAYOUT (lazy loading): firmware/avatar_frames.py is a small registry
(constants, SPRITE_ORDER, per-sprite metadata, and sprite() which imports a
sprite's frames on first use); the heavy frame data lives in one generated
firmware/avatar_sprite_<name>.py per sprite (~35 KB each). A single combined
module at 7 sprites (~240 KB) HANGS MicroPython's on-device compiler — keep
the per-sprite split.

The web avatar (view/screens.css) animates with CSS transforms over the whole
112 px sprite box with image-rendering:pixelated — i.e. a nearest-neighbour
non-uniform scale anchored at bottom-centre. This tool replicates that at the
device-pixel level: every cell-rect's edges are mapped through the exact
keyframe scale factors and rounded, so squashed frames keep crisp pixel edges
(cells come out a pixel taller/shorter here and there — exactly like the
browser renders the squash). 16-cell sprites get 7 px cells, 32-cell sprites
3.5 px cells (alternating 3/4 px after rounding), matching the browser.

SPRITE-ART MODULE CONTRACT (tools/sprite_art/<name>.py) — each defines:
  SPRITE = {
    "name": "gloom",            # firmware key (snake_case)
    "label": "GLOOM",           # roster label (AV_SPRITES in screens.js)
    "roster_index": 0,          # position in AV_SPRITES (display order)
    "grid_cells": 16,           # the source SVG viewBox (16 or 32)
    "sweat_anchor": (63, 16),   # 12x16 bead top-left, DEVICE px in the
                                # neutral 112px box, ON the head's right slope
    "stress_marker": "ember",   # OPTIONAL: stress drop art — "sweat" (default
                                # blue bead) | "ember" (SPARKLY's amber spark)
    "sparkle_pen": "avatar_light",  # OPTIONAL: theme pen for the done
                                # twinkles (default "status" green)
    "happy_pen": "text",        # OPTIONAL: theme pen for the happy layer
                                # (default "background" cut-out; BLIP's cream)
    "eyes_white_on_top": True,  # OPTIONAL: draw eyes_white AFTER eyes_pupil
                                # (ZIGGY: cream glints over dark almonds)
    "layers": { ... },          # cell rects (x, y, w, h) per layer; only the
                                # layers the sprite has — others default empty
  }
The OPTIONAL keys carry the web's per-avatar CSS overrides (screens.css
data-avatar rules); set them only when they differ from the default, so the
generated output for plain sprites stays byte-identical.
Layers (draw order, theme pen in parentheses): fill (avatar), shade
(avatar_dark), hi (avatar_light), dark (avatar_dark), mouth (background),
eyes_white (text), eyes_pupil (background), happy (background — replaces both
eye layers during the done flourish). Blink squashes eyes_white rows, so keep
eye whites as solid rects.

Keyframes ported verbatim from screens.css:
  avFloat (2 s, ease-in-out per segment):
    0%/100%  translateY(+3px) scaleX(1.05) scaleY(0.95)   (resting, squashed)
    50%      translateY(-9px) scaleX(0.96) scaleY(1.05)   (apex, stretched)
  avHop (1.15 s, ease-out per segment):
    0% (0,1,1) 20% (-13,.90,1.12) 40% (0,1.10,.88) 58% (-5,.98,1.03)
    74% (0,1.03,.98) 100% (0,1,1)

Run from the repo root:  python3 tools/build-avatar-frames.py
"""

import glob
import math
import os

# GPLv2 header prepended to every generated module, matching the per-file
# header carried by the hand-written sources (public-release packaging).
LICENSE_HEADER = """# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

"""

SPRITE_BOX = 112           # the CSS transform box (.av-svg is 112x112)
ANCHOR_X = SPRITE_BOX / 2  # transform-origin: bottom center
ANCHOR_Y = SPRITE_BOX

FLOAT_FRAME_COUNT = 32
HOP_FRAME_COUNT = 24

LAYER_ORDER = ("fill", "shade", "hi", "dark", "mouth",
               "eyes_white", "eyes_pupil", "happy")

FLOAT_REST = (3.0, 1.05, 0.95)   # (translate_y px, scale_x, scale_y)
FLOAT_APEX = (-9.0, 0.96, 1.05)

HOP_KEYFRAMES = (  # (cycle position, translate_y, scale_x, scale_y)
    (0.00, 0.0, 1.00, 1.00),
    (0.20, -13.0, 0.90, 1.12),
    (0.40, 0.0, 1.10, 0.88),
    (0.58, -5.0, 0.98, 1.03),
    (0.74, 0.0, 1.03, 0.98),
    (1.00, 0.0, 1.00, 1.00),
)


def ease_in_out(t):
    return (1 - math.cos(math.pi * t)) / 2


def ease_out(t):
    return 1 - (1 - t) ** 2


def lerp(a, b, t):
    return a + (b - a) * t


def load_sprites():
    art_directory = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sprite_art")
    sprites = []
    for path in sorted(glob.glob(os.path.join(art_directory, "*.py"))):
        namespace = {}
        with open(path) as art_file:
            exec(art_file.read(), namespace)  # noqa: S102 -- our own data modules
        sprite = namespace["SPRITE"]
        for required in ("name", "label", "roster_index", "grid_cells", "sweat_anchor", "layers"):
            if required not in sprite:
                raise SystemExit("%s: SPRITE is missing %r" % (path, required))
        unknown = set(sprite["layers"]) - set(LAYER_ORDER)
        if unknown:
            raise SystemExit("%s: unknown layers %s" % (path, sorted(unknown)))
        if sprite.get("stress_marker", "sweat") not in ("sweat", "ember"):
            raise SystemExit("%s: unknown stress_marker %r" % (path, sprite["stress_marker"]))
        sprites.append(sprite)
    sprites.sort(key=lambda sprite: sprite["roster_index"])
    return sprites


def transform_layer(cell_rects, cell_pixels, scale_x, scale_y):
    """Map cell rects to device-pixel rects through the bottom-centre scale.
    Edges are transformed and rounded individually, so rects that share an
    edge stay seamless (no gaps, no overlaps) in the squashed frame."""
    out = []
    for cell_x, cell_y, cell_w, cell_h in cell_rects:
        x0 = cell_x * cell_pixels
        x1 = (cell_x + cell_w) * cell_pixels
        y0 = cell_y * cell_pixels
        y1 = (cell_y + cell_h) * cell_pixels
        tx0 = round(ANCHOR_X + (x0 - ANCHOR_X) * scale_x)
        tx1 = round(ANCHOR_X + (x1 - ANCHOR_X) * scale_x)
        ty0 = round(ANCHOR_Y + (y0 - ANCHOR_Y) * scale_y)
        ty1 = round(ANCHOR_Y + (y1 - ANCHOR_Y) * scale_y)
        if tx1 > tx0 and ty1 > ty0:
            out.append((tx0, ty0, tx1 - tx0, ty1 - ty0))
    return tuple(out)


def make_frame(sprite, translate_y, scale_x, scale_y):
    # scale factors ride along (per-mille ints) so the firmware can glue
    # accessories (the sweat bead) to the head through the SAME transform —
    # the squash moves the head top by up to ~10 px (anchored at the feet)
    cell_pixels = SPRITE_BOX / sprite["grid_cells"]
    layers = tuple(
        transform_layer(sprite["layers"].get(name, ()), cell_pixels, scale_x, scale_y)
        for name in LAYER_ORDER
    )
    return (round(translate_y), round(scale_x * 1000), round(scale_y * 1000)) + layers


def float_frames(sprite):
    frames = []
    for index in range(FLOAT_FRAME_COUNT):
        position = index / FLOAT_FRAME_COUNT
        if position < 0.5:
            t = ease_in_out(position / 0.5)
        else:
            t = 1 - ease_in_out((position - 0.5) / 0.5)
        frames.append(make_frame(
            sprite,
            lerp(FLOAT_REST[0], FLOAT_APEX[0], t),
            lerp(FLOAT_REST[1], FLOAT_APEX[1], t),
            lerp(FLOAT_REST[2], FLOAT_APEX[2], t),
        ))
    return frames


def hop_frames(sprite):
    frames = []
    for index in range(HOP_FRAME_COUNT):
        position = index / HOP_FRAME_COUNT
        for k in range(len(HOP_KEYFRAMES) - 1):
            p0, ty0, sx0, sy0 = HOP_KEYFRAMES[k]
            p1, ty1, sx1, sy1 = HOP_KEYFRAMES[k + 1]
            if p0 <= position <= p1:
                t = ease_out((position - p0) / (p1 - p0)) if p1 > p0 else 0
                frames.append(make_frame(
                    sprite, lerp(ty0, ty1, t), lerp(sx0, sx1, t), lerp(sy0, sy1, t)))
                break
    return frames


def emit_frames(frames):
    lines = []
    for frame in frames:
        (ty, sx_milli, sy_milli), layer_tuples = frame[:3], frame[3:]
        layer_text = ", ".join(
            "(" + ", ".join(str(r) for r in layer) + ("," if len(layer) == 1 else "") + ")"
            if layer else "()"
            for layer in layer_tuples
        )
        lines.append("        (%d, %d, %d, %s)," % (ty, sx_milli, sy_milli, layer_text))
    return "\n".join(lines)


def emit_metadata(sprite):
    # the optional per-sprite overrides (web data-avatar CSS specials) ride
    # through only when present, so plain sprites' output is unchanged
    overrides = "".join(
        '\n        "%s": %r,' % (key, sprite[key])
        for key in ("stress_marker", "sparkle_pen", "happy_pen", "eyes_white_on_top")
        if key in sprite
    )
    return ('    "%s": {\n        "label": "%s",\n        "sweat_anchor": (%d, %d),%s\n    },'
            % (sprite["name"], sprite["label"],
               sprite["sweat_anchor"][0], sprite["sweat_anchor"][1], overrides))


def write_sprite_module(repo_root, sprite):
    target = os.path.join(repo_root, "firmware", "avatar_sprite_%s.py" % sprite["name"])
    body = LICENSE_HEADER + """# GENERATED by tools/build-avatar-frames.py — DO NOT EDIT BY HAND.
#
# %s's pre-squashed frames; loaded LAZILY via avatar_frames.sprite() (a
# combined module hangs the on-device compiler — see the generator docstring).
# Frame format: see firmware/avatar_frames.py.

FLOAT_FRAMES = (
%s
)

HOP_FRAMES = (
%s
)
""" % (sprite["label"], emit_frames(float_frames(sprite)).replace("        (", "    ("),
       emit_frames(hop_frames(sprite)).replace("        (", "    ("))
    with open(target, "w") as handle:
        handle.write(body)
    return target


def main():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sprites = load_sprites()
    # sweep stale generated modules (a renamed/removed sprite must not linger)
    current_names = set(sprite["name"] for sprite in sprites)
    for stale in glob.glob(os.path.join(repo_root, "firmware", "avatar_sprite_*.py")):
        stale_name = os.path.basename(stale)[len("avatar_sprite_"):-len(".py")]
        if stale_name not in current_names:
            os.remove(stale)
            print("removed stale", stale)
    for sprite in sprites:
        write_sprite_module(repo_root, sprite)
    registry = os.path.join(repo_root, "firmware", "avatar_frames.py")
    body = LICENSE_HEADER + '''# GENERATED by tools/build-avatar-frames.py — DO NOT EDIT BY HAND.
#
# The sprite registry: metadata + lazy access to the per-sprite frame
# modules (avatar_sprite_<name>.py). Frames replicate the web avatar's CSS
# float/hop transforms (squash anchored at bottom-centre, nearest-neighbour
# at device pixels). Each frame is (translate_y, scale_x_milli,
# scale_y_milli, fill, shade, hi, dark, mouth, eyes_white, eyes_pupil,
# happy) with rects in device px relative to the 112 px sprite box origin —
# draw layer rects 1:1 (scale is baked in), offset by translate_y; the
# per-mille scale factors glue accessories (sweat bead) to the head through
# the same transform. Optional metadata keys (stress_marker / sparkle_pen /
# happy_pen) carry the web's per-avatar CSS specials; absent = default.

SPRITE_BOX = %d

FLOAT_CYCLE_MILLISECONDS = 2000           # avFloat duration (idle/waiting)
FLOAT_CYCLE_WORKING_MILLISECONDS = 950    # working speeds the float up
HOP_CYCLE_MILLISECONDS = 1150             # avHop duration (done flourish)

FRAME_SCALE_X = 1
FRAME_SCALE_Y = 2
LAYER_FILL = 3
LAYER_SHADE = 4
LAYER_HI = 5
LAYER_DARK = 6
LAYER_MOUTH = 7
LAYER_EYES_WHITE = 8
LAYER_EYES_PUPIL = 9
LAYER_HAPPY = 10

SPRITE_ORDER = (%s)

SPRITE_INFO = {
%s
}

_loaded_sprites = {}


def sprite(name):
    """Metadata + frames for one sprite; the frame module imports on first
    use and stays cached (only visited sprites occupy RAM)."""
    if name not in _loaded_sprites:
        frame_module = __import__("avatar_sprite_" + name)
        entry = dict(SPRITE_INFO[name])
        entry["float"] = frame_module.FLOAT_FRAMES
        entry["hop"] = frame_module.HOP_FRAMES
        _loaded_sprites[name] = entry
    return _loaded_sprites[name]
''' % (SPRITE_BOX,
       ", ".join('"%s"' % sprite["name"] for sprite in sprites)
       + ("," if len(sprites) == 1 else ""),
       "\n".join(emit_metadata(sprite) for sprite in sprites))
    with open(registry, "w") as handle:
        handle.write(body)
    print("wrote %d sprite modules + the registry (%d float + %d hop frames each)"
          % (len(sprites), FLOAT_FRAME_COUNT, HOP_FRAME_COUNT))


if __name__ == "__main__":
    main()
