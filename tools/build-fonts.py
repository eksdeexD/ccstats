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

"""Build the firmware's .af fonts with pixel-grid-EXACT quantization.

Why this exists: the stock afinate conversion picks an arbitrary scale, so a
pixel font's design grid lands on fractional .af units; with the renderer's
fixed size/128 scaling, strokes then sit at fractional screen positions and
1px strokes drop columns unpredictably (glyphs missing vertical lines).

The fix: quantize each font so one DESIGN PIXEL is exactly U integer .af
units (U = the largest value that still fits the int8 coordinate range), and
record (native_px, U) in firmware/font_metrics.py. The firmware then draws at
size = 128 * requested_px / (U * native_px), which makes the renderer's
size/128 scale resolve every design pixel to exactly requested_px/native_px
screen pixels — strokes, bearings and advances all integer. No sub-pixel
phase, nothing to calibrate.

Prereqs you provide: the patched afinate converter clone at ~/alright-fonts-gadgetoid
(adds --scale-factor + round-not-truncate) and a font venv at ~/.venvs/fonts (fontTools).
Sources: the in-repo web font library at viewscreens/fonts/ (per-font TTF/OTF); the two
Google fonts (Press Start 2P, Silkscreen) are downloaded once into ~/.cache.

Usage: tools/build-fonts.py
"""

import os
import subprocess
import sys
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIRECTORY = os.path.join(REPO_ROOT, "firmware", "fonts")
METRICS_PATH = os.path.join(REPO_ROOT, "firmware", "font_metrics.py")
AFINATE_DIRECTORY = os.path.expanduser("~/alright-fonts-gadgetoid")
VENV_PYTHON = os.path.expanduser("~/.venvs/fonts/bin/python3")
LIBRARY_DIRECTORY = os.path.join(REPO_ROOT, "viewscreens", "fonts")
GOOGLE_CACHE = os.path.expanduser("~/.cache/ccstats-google-fonts")
GOOGLE_RAW = "https://raw.githubusercontent.com/google/fonts/main/ofl/"

# extra glyphs beyond basic latin (afinate corpus format: name codepoint-hex)
CORPUS_LINES = "middot b7\nbullet 2022\ndegree b0\nmultiply d7\nrightarrow 2192\n"

# font_key -> (source, path, native_px). source: "google" or "library".
FONTS = {
    "pico": ("google", "pressstart2p/PressStart2P-Regular.ttf", 8),
    "silk": ("google", "silkscreen/Silkscreen-Regular.ttf", 8),
    "silk_bold": ("google", "silkscreen/Silkscreen-Bold.ttf", 8),
    "visitor_tt1": ("library", "visitor_tt1/visitor1.ttf", 10),
    "aurora_24": ("library", "aurora_24/aurora-24.ttf", 9),
    "deer_diary": ("library", "deer_diary/deer-diary.ttf", 11),
    "5x7_mt_pixel": ("library", "5x7_mt_pixel/5x7 MT Pixel.ttf", 7),
    "5x5_mt_pixel": ("library", "5x5_mt_pixel/5x5 MT Pixel.ttf", 5),
    "3x5_mt_pixel": ("library", "3x5_mt_pixel/3x5 MT Pixel.ttf", 5),
}


def source_path(source, relative_path):
    if source == "library":
        return os.path.join(LIBRARY_DIRECTORY, relative_path)
    cached = os.path.join(GOOGLE_CACHE, os.path.basename(relative_path))
    if not os.path.exists(cached):
        os.makedirs(GOOGLE_CACHE, exist_ok=True)
        url = GOOGLE_RAW + relative_path.replace(" ", "%20")
        print("downloading", url)
        urllib.request.urlretrieve(url, cached)
    return cached


def corpus_codepoints():
    codepoints = list(range(0x20, 0x7F))  # afinate's basic_latin
    for line in CORPUS_LINES.strip().splitlines():
        codepoints.append(int(line.split()[1], 16))
    return codepoints


def grid_parameters(ttf_path, native_px):
    """(units_per_design_px U, afinate scale factor) for pixel-grid exactness."""
    import freetype  # provided by the font venv (we re-exec into it below)

    face = freetype.Face(ttf_path)
    units_per_em = face.units_per_EM
    max_extent = max(abs(face.bbox.xMin), abs(face.bbox.yMin),
                     abs(face.bbox.xMax), abs(face.bbox.yMax))
    # .af packs ADVANCES as int8 like the coordinates — and an advance can
    # exceed every outline extent (deer_diary 'W': advance 154 units wrapped
    # to -102, the cursor stepped BACKWARDS and the next glyph overdrew it —
    # while every coordinate fit fine, so afinate raised no error). Constrain
    # the grid by the widest corpus advance as well.
    for codepoint in corpus_codepoints():
        if face.get_char_index(codepoint) == 0:
            continue
        face.load_char(chr(codepoint), freetype.FT_LOAD_NO_SCALE)
        max_extent = max(max_extent, abs(face.glyph.advance.x))
    design_px_units = units_per_em / native_px  # font units per design pixel
    units_per_design_px = int(127 * design_px_units // max_extent)
    if units_per_design_px < 1:
        raise SystemExit("font grid does not fit int8 coords: " + ttf_path)
    scale_factor = design_px_units / units_per_design_px
    return units_per_design_px, scale_factor


def main():
    os.makedirs(OUTPUT_DIRECTORY, exist_ok=True)
    corpus_path = "/tmp/ccstats-font-corpus.txt"
    with open(corpus_path, "w") as corpus_file:
        corpus_file.write(CORPUS_LINES)

    metrics = {}
    for font_key, (source, relative_path, native_px) in FONTS.items():
        ttf_path = source_path(source, relative_path)
        units_per_design_px, _ = grid_parameters(ttf_path, native_px)
        output_path = os.path.join(OUTPUT_DIRECTORY, font_key + ".af")
        # some fonts have outlines beyond the face-declared bbox; if int8
        # coordinates overflow, step U down — exactness needs U integer, not
        # maximal resolution.
        while units_per_design_px >= 1:
            import freetype

            face = freetype.Face(ttf_path)
            scale_factor = (face.units_per_EM / native_px) / units_per_design_px
            completed = subprocess.run(
                [VENV_PYTHON, "afinate", "--quiet", "--font", ttf_path,
                 "--quality", "high", "--characters", "basic_latin",
                 "--corpus", corpus_path, "--scale-factor", str(scale_factor),
                 "--out", output_path],
                cwd=AFINATE_DIRECTORY,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
            if completed.returncode == 0:
                break
            if b"requires -128 <= number <= 127" not in completed.stderr:
                sys.stderr.write(completed.stderr.decode())
                raise SystemExit("afinate failed for " + font_key)
            units_per_design_px -= 1
        else:
            raise SystemExit("could not fit " + font_key + " into int8 coords")
        metrics[font_key] = (native_px, units_per_design_px)
        print("built %-14s native %2dpx, %2d units/design-px, %5d bytes"
              % (font_key, native_px, units_per_design_px, os.path.getsize(output_path)))

    with open(METRICS_PATH, "w") as metrics_file:
        metrics_file.write(
            "# GENERATED by tools/build-fonts.py — do not edit by hand.\n"
            "#\n"
            "# font_key -> (native_px, units_per_design_pixel). The .af files are\n"
            "# quantized so one design pixel is exactly units_per_design_pixel .af\n"
            "# units; the renderer scales glyphs by size/128, so drawing at\n"
            "#   size = 128 * requested_px / (units * native_px)\n"
            "# makes every design pixel exactly requested_px/native_px screen pixels\n"
            "# (integer strokes, bearings and advances — no sub-pixel phase).\n"
            "FONT_METRICS = {\n"
        )
        for font_key in FONTS:
            native_px, units = metrics[font_key]
            metrics_file.write("    %r: (%d, %d),\n" % (font_key, native_px, units))
        metrics_file.write("}\n")
    print("wrote", METRICS_PATH)


if __name__ == "__main__":
    try:
        import freetype  # noqa: F401
    except ImportError:  # re-exec under the font venv, which has freetype-py
        os.execv(VENV_PYTHON, [VENV_PYTHON, os.path.abspath(__file__)] + sys.argv[1:])
    main()
