# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# The design's actual typefaces (the same families /view uses), converted from
# TTF to Alright Fonts with Pimoroni's afinate (gadgetoid/alright-fonts,
# feature/icon-and-font-merge — the format this firmware's picovector reads).
# Both are OFL-licensed Google Fonts: see fonts/OFL.txt.
#
# Fonts are always loaded from device flash by absolute path: reading binary
# files through the `mpremote mount` VFS bridge crashes the host-side server,
# so the mount dev loop must NOT touch .af files. The installed app ships them
# under its own directory; for mount-based dev runs copy them once to /fonts:
#   mpremote mkdir :/fonts + cp firmware/fonts/*.af :/fonts/

import badgeware  # noqa: F401 -- injects the `font` global used below

_FONT_DIRECTORIES = ("/system/apps/ccstats/fonts/", "/fonts/")


def _load(file_name):
    for directory in _FONT_DIRECTORIES:
        try:
            return font.load(directory + file_name)
        except OSError:
            continue
    raise OSError(
        "font not found: %s (run tools/install-app.py, or cp firmware/fonts/*.af to /fonts/)"
        % file_name
    )


from font_metrics import FONT_METRICS

# The /viewscreens font library, keyed exactly like pico.js FONTS / the type scale.
# Files are built grid-exact by tools/build-fonts.py; each font is crisp at
# its native px and integer multiples only.
FONT_REGISTRY = {
    "pico": _load("pico.af"),  # Press Start 2P (native 8)
    "silk": _load("silk.af"),  # Silkscreen (native 8)
    "silk_bold": _load("silk_bold.af"),  # Silkscreen Bold (native 8)
    "visitor_tt1": _load("visitor_tt1.af"),  # Visitor TT1 (native 10)
    "aurora_24": _load("aurora_24.af"),  # Aurora 24 (native 9)
    "deer_diary": _load("deer_diary.af"),  # Deer Diary (native 11)
    "5x7_mt_pixel": _load("5x7_mt_pixel.af"),  # 5x7 MT Pixel (native 7)
    "5x5_mt_pixel": _load("5x5_mt_pixel.af"),  # 5x5 MT Pixel (native 5)
    "3x5_mt_pixel": _load("3x5_mt_pixel.af"),  # 3x5 MT Pixel (native 5)
}


def effective_text_size(font_key, requested_pixel_size):
    """The size to pass to the renderer so the font's design grid lands
    EXACTLY on requested_pixel_size/native screen pixels per design pixel.

    The .af files quantize one design pixel to an integer number of units
    (font_metrics.py) and the renderer scales glyphs by size/128 — so this
    makes every stroke, bearing and advance an exact integer at native sizes
    and integer multiples. See tools/build-fonts.py.
    """
    native_pixel_size, units_per_design_pixel = FONT_METRICS[font_key]
    return 128 * requested_pixel_size / (units_per_design_pixel * native_pixel_size)


# direct aliases for the boot screen (drawn before any type scale exists)
PRESS_START_2P = FONT_REGISTRY["pico"]
SILKSCREEN = FONT_REGISTRY["silk"]
