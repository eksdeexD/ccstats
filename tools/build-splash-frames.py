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

"""Bake the hue-cycling splash frames from firmware/splash.png.

CURRENTLY UNUSED (2026-06-13): the splash is a static cropped logo on a
fixed background — the hue cycle was retired by user choice. Kept in case
it comes back; main.py would need its frame-blitting path restored (see
git history around commit 963a278).

Writes firmware/splash_frames/hue_XX.png + meta.json. The frames are CROPPED
to the hue-affected region (saturated pixels + margin): a full-screen frame
decodes to 300 KB RGBA on the badge, so 36 of them cannot live in PSRAM —
the cropped logo region (~100 KB) can, which is what makes the cycle SMOOTH
(blit from RAM at ~30 fps vs a 147 ms PNG decode per step). The badge blits
the static splash once, then the cropped frames over it at meta's x/y.

Needs Pillow. The dev seat keeps it in a venv (no system pip on this VM):

    ~/.venvs/badge-tools/bin/python tools/build-splash-frames.py

Re-run after replacing firmware/splash.png. The frames install with the app
(/system/apps/ccstats/splash_frames/); they are NOT copied to the device
root — root flash is small (~850 KB free), so dev runs before any install
fall back to the static splash.
"""

import json
import os

from PIL import Image

FRAME_COUNT = 36  # 10-degree hue steps; full wheel in FRAME_COUNT frames
CROP_MARGIN = 2
SATURATION_FLOOR = 30  # below this (or dark), a pixel does not visibly change hue
VALUE_FLOOR = 30

repository_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
splash_path = os.path.join(repository_root, "firmware", "splash.png")
frames_directory = os.path.join(repository_root, "firmware", "splash_frames")


def colored_region(hsv_image):
    """Bounding box of visibly-colored pixels (the only ones hue moves)."""
    saturation = list(hsv_image.split()[1].getdata())
    value = list(hsv_image.split()[2].getdata())
    width, height = hsv_image.size
    min_x, min_y, max_x, max_y = width, height, -1, -1
    for y in range(height):
        for x in range(width):
            index = y * width + x
            if saturation[index] > SATURATION_FLOOR and value[index] > VALUE_FLOOR:
                min_x, min_y = min(min_x, x), min(min_y, y)
                max_x, max_y = max(max_x, x), max(max_y, y)
    if max_x < 0:
        raise SystemExit("splash.png has no colored pixels to hue-cycle")
    return (max(0, min_x - CROP_MARGIN), max(0, min_y - CROP_MARGIN),
            min(width, max_x + 1 + CROP_MARGIN), min(height, max_y + 1 + CROP_MARGIN))


def main():
    base_rgb = Image.open(splash_path).convert("RGB")
    base_hsv = base_rgb.convert("HSV")
    crop = colored_region(base_hsv)
    crop_rgb = base_rgb.crop(crop)
    hue_channel, saturation_channel, value_channel = base_hsv.crop(crop).split()
    # rotate ONLY the visibly-colored pixels: the splash background is a
    # slightly blue-tinted dark (21,21,27), and rotating its hue makes the
    # crop rectangle visibly drift against the untouched base around it
    rotate_mask = Image.eval(
        Image.merge("RGB", (saturation_channel, value_channel, value_channel)).convert("L"),
        lambda value: 0,
    )
    mask_pixels = rotate_mask.load()
    saturation_pixels = saturation_channel.load()
    value_pixels = value_channel.load()
    for y in range(rotate_mask.size[1]):
        for x in range(rotate_mask.size[0]):
            if saturation_pixels[x, y] > SATURATION_FLOOR and value_pixels[x, y] > VALUE_FLOOR:
                mask_pixels[x, y] = 255
    os.makedirs(frames_directory, exist_ok=True)
    for stale_name in os.listdir(frames_directory):
        os.remove(os.path.join(frames_directory, stale_name))
    for frame_index in range(FRAME_COUNT):
        offset = round(frame_index * 256 / FRAME_COUNT)
        rotated_hue = hue_channel.point(lambda value, offset=offset: (value + offset) % 256)
        rotated = Image.merge("HSV", (rotated_hue, saturation_channel, value_channel)).convert("RGB")
        frame = crop_rgb.copy()
        frame.paste(rotated, mask=rotate_mask)  # background stays bit-identical
        frame.save(os.path.join(frames_directory, "hue_%02d.png" % frame_index), optimize=True)
    meta = {"count": FRAME_COUNT, "x": crop[0], "y": crop[1],
            "width": crop[2] - crop[0], "height": crop[3] - crop[1]}
    with open(os.path.join(frames_directory, "meta.json"), "w") as meta_file:
        json.dump(meta, meta_file)
    total_kb = sum(os.path.getsize(os.path.join(frames_directory, name))
                   for name in os.listdir(frames_directory)) // 1024
    print("wrote %d cropped frames (%dx%d at %d,%d), %d KB + meta.json"
          % (FRAME_COUNT, meta["width"], meta["height"], meta["x"], meta["y"], total_kb))


if __name__ == "__main__":
    main()
