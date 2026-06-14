# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# Type scale — ELEMENT-TYPE ROLES, each mapped to (font_key, pixel_size).
# Screens reference a ROLE (what the text IS — a row label, a hero value, an
# axis tick), never a raw size, so a font preset can re-map every role without
# touching screen code (port of the /viewscreens type-scale system).
#
# pixel_size must be the font's NATIVE px or an integer multiple — pixel fonts
# rendered off their native grid lose strokes. font_key resolves via
# design_fonts.FONT_REGISTRY.

ROLES = (
    "screen_title",
    "section_label",
    "row_label",
    "row_value",
    "hero_value",
    "caption",
    "axis_tick",
    "legend_label",
    "tag",
    "compare_value",
    "model_share_label",
    "model_turn_label",
    "speech_bubble",
)

# Complete role -> (font_key, px) maps (FONT_PRESETS in screens.js).
FONT_PRESETS = {
    "preset1": {  # the /viewscreens default scale
        "screen_title": ("visitor_tt1", 20),  # Visitor TT1 (native 10) x2
        "section_label": ("silk", 8),  # Silkscreen (native 8)
        "row_label": ("aurora_24", 9),  # Aurora 24 (native 9)
        "row_value": ("silk", 16),  # Silkscreen (native 8) x2
        "hero_value": ("5x7_mt_pixel", 21),  # 5x7 MT Pixel (native 7) x3
        "caption": ("silk", 8),  # Silkscreen (native 8)
        "axis_tick": ("5x5_mt_pixel", 5),  # 5x5 MT Pixel (native 5)
        "legend_label": ("5x5_mt_pixel", 5),
        "tag": ("5x5_mt_pixel", 5),
        "compare_value": ("aurora_24", 9),
        "model_share_label": ("3x5_mt_pixel", 5),  # 3x5 MT Pixel (native 5)
        "model_turn_label": ("visitor_tt1", 10),  # Visitor TT1 (native 10)
        "speech_bubble": ("silk", 8),  # avatar bubbles (settled 2026-06-12;
        # deer_diary 11 / aurora_24 9 are the A/B-tested candidates for new presets)
    },
    "preset2": {  # user-authored alternative set (2026-06-11)
        "screen_title": ("visitor_tt1", 20),
        "section_label": ("visitor_tt1", 10),
        "row_label": ("pico", 8),  # Press Start 2P (native 8)
        "row_value": ("silk", 16),
        "hero_value": ("visitor_tt1", 50),  # Visitor TT1 (native 10) x5
        "caption": ("visitor_tt1", 10),
        "axis_tick": ("5x5_mt_pixel", 5),
        "legend_label": ("5x5_mt_pixel", 5),
        "tag": ("visitor_tt1", 10),
        "compare_value": ("pico", 8),
        "model_share_label": ("3x5_mt_pixel", 5),
        "model_turn_label": ("visitor_tt1", 10),
        "speech_bubble": ("silk", 8),
    },
}

def get_active_scale():
    # the persisted preset; a stale saved key falls back to the default scale
    import settings

    return FONT_PRESETS.get(settings.get("font_preset")) or FONT_PRESETS["preset1"]
