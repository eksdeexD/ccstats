# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# Theme module — the 6 user colour slots and the ~20 derived shades, ported
# verbatim from applyTheme() / the colour helpers in the spec's screens.js.
# All derivation happens here once per theme change; screens only ever read
# named pens off the Theme object.

import badgeware  # noqa: F401 -- guarantees the drawing globals (color, ...) exist


def parse_hex(hex_string):
    # "#ff6422" -> (255, 100, 34)
    digits = hex_string.replace("#", "")
    packed_rgb = int(digits, 16)
    return ((packed_rgb >> 16) & 255, (packed_rgb >> 8) & 255, packed_rgb & 255)


def clamp_byte(value):
    return max(0, min(255, round(value)))


def scale(rgb, factor):
    # darken/lighten towards black/white by multiplying each channel
    red, green, blue = rgb
    return (clamp_byte(red * factor), clamp_byte(green * factor), clamp_byte(blue * factor))


def tint(rgb, factor):
    # blend each channel towards white by `factor`
    red, green, blue = rgb
    return (
        clamp_byte(red + (255 - red) * factor),
        clamp_byte(green + (255 - green) * factor),
        clamp_byte(blue + (255 - blue) * factor),
    )


def rgb_to_hsv(rgb):
    red, green, blue = (channel / 255 for channel in rgb)
    max_channel = max(red, green, blue)
    min_channel = min(red, green, blue)
    channel_range = max_channel - min_channel
    hue = 0.0
    if channel_range:
        if max_channel == red:
            hue = ((green - blue) / channel_range) % 6
        elif max_channel == green:
            hue = (blue - red) / channel_range + 2
        else:
            hue = (red - green) / channel_range + 4
        hue *= 60
        if hue < 0:
            hue += 360
    saturation = 0 if max_channel == 0 else channel_range / max_channel
    return hue, saturation, max_channel


def hsv_to_rgb(hue, saturation, value):
    saturation = max(0.0, min(1.0, saturation))
    value = max(0.0, min(1.0, value))
    chroma = value * saturation
    second_component = chroma * (1 - abs((hue / 60) % 2 - 1))
    lightness_match = value - chroma
    if hue < 60:
        red, green, blue = chroma, second_component, 0
    elif hue < 120:
        red, green, blue = second_component, chroma, 0
    elif hue < 180:
        red, green, blue = 0, chroma, second_component
    elif hue < 240:
        red, green, blue = 0, second_component, chroma
    elif hue < 300:
        red, green, blue = second_component, 0, chroma
    else:
        red, green, blue = chroma, 0, second_component
    return (
        clamp_byte((red + lightness_match) * 255),
        clamp_byte((green + lightness_match) * 255),
        clamp_byte((blue + lightness_match) * 255),
    )


# The 6 slots of the DEFAULT theme (THEME_DEFAULTS in screens.js).
DEFAULT_THEME_SLOTS = {
    "background": "#292929",
    "accent_primary": "#ff6422",  # the spec's "amber" / ACCENT 1
    "accent_secondary": "#2cdd17",  # the spec's "teal" / ACCENT 2
    "text": "#d3d3d3",
    "status": "#00ea06",
    "avatar_color": "#ff6422",
}

# Preset palettes (PALETTES in screens.js) — on-device theming is preset-only.
PALETTE_PRESETS = (
    ("DEFAULT", "#292929", "#ff6422", "#2cdd17", "#d3d3d3", "#00ea06", "#ff6422"),
    ("NEON", "#020c22", "#b1ff14", "#14d8ff", "#d0ecf1", "#c3f859", "#b1ff14"),
    ("MONOCHROME", "#787878", "#434343", "#e0e0e0", "#fafafa", "#292929", "#c6c6c6"),
    ("SPRING", "#9cf09c", "#19db3b", "#4a9eff", "#f1a2eb", "#434343", "#f3e84c"),
    ("AUTUMN", "#f1dc9e", "#7a5c00", "#f78a4b", "#f46a34", "#434343", "#f8d059"),
    ("BLOOD", "#2c0303", "#a40000", "#f85b00", "#ff3c3c", "#5e5e5e", "#ec7e7e"),
    ("BLURANGE", "#191919", "#ff640a", "#14d8ff", "#bababa", "#14d8ff", "#14d8ff"),
    ("ACIDIC WATERMELON", "#191028", "#69eb00", "#ff08eb", "#97b8f1", "#8aea00", "#ff6422"),
    ("COMFY", "#1d1b1b", "#ff3f0c", "#fe8234", "#ffb45f", "#8aea00", "#ff6422"),
    ("PURDEE", "#1d1b1b", "#33a9ff", "#b50cff", "#4bc0ff", "#ff2598", "#e045a8"),
    ("MILLENIUM", "#1b1f22", "#33a9ff", "#ff620c", "#4bc0ff", "#91e900", "#ff620c"),
    ("DJINKZED", "#192024", "#ff33fd", "#ff620c", "#4cbffe", "#91e900", "#ff33fd"),
    ("BLUEFEELS", "#191c1f", "#33a1ff", "#0c42ff", "#5fc1ff", "#00eac1", "#228aff"),
    ("SANDEE", "#2c2626", "#ffb622", "#de7216", "#a3a3a3", "#fe8847", "#ff7822"),
    ("GRRLY", "#1d1b1b", "#ea54ce", "#f06b6b", "#ff705f", "#8aea00", "#ff3692"),
    ("PASTELLICIOUS", "#171515", "#63e955", "#f26969", "#ff705f", "#8aea00", "#77bbbe"),
    ("RETRO DULLNESS", "#a69e9e", "#2629ff", "#d01212", "#000000", "#19b30f", "#004fa7"),
)

PRESET_SLOT_ORDER = ("background", "accent_primary", "accent_secondary", "text", "status", "avatar_color")


def preset_slots(preset_name):
    """The 6-slot dict for a named preset. Unknown names fall back to DEFAULT —
    a persisted name that disappears in a preset rename must not break boot."""
    for preset in PALETTE_PRESETS:
        if preset[0] == preset_name:
            return dict(zip(PRESET_SLOT_ORDER, preset[1:]))
    return dict(DEFAULT_THEME_SLOTS)


class Theme:
    """The 6 primaries plus every derived shade, as ready-to-use pens."""

    def __init__(self, slots=None):
        self.apply(slots or DEFAULT_THEME_SLOTS)

    def apply(self, slots):
        def pen(rgb):
            return color.rgb(*rgb)

        background = parse_hex(slots["background"])
        accent_primary = parse_hex(slots["accent_primary"])
        accent_secondary = parse_hex(slots["accent_secondary"])
        text_color = parse_hex(slots["text"])
        status = parse_hex(slots["status"])
        avatar_color = parse_hex(slots["avatar_color"])

        # primaries
        self.background = pen(background)
        self.accent_primary = pen(accent_primary)
        self.accent_secondary = pen(accent_secondary)
        self.text = pen(text_color)
        self.status = pen(status)
        self.avatar_color = pen(avatar_color)

        # derived from background (applyTheme: titlebar/rim/line/screenborder/panel/track/edge)
        self.title_bar = pen(scale(background, 1.35))
        self.rim = pen(scale(background, 1.85))
        self.line = pen(scale(background, 1.72))
        self.screen_border = pen(scale(background, 1.27))
        self.panel = pen(scale(background, 0.74))
        self.track = pen(scale(background, 0.58))
        self.edge = pen(scale(background, 0.36))

        # derived from the accents
        # _dim: -15% saturation/value (HSV) — the MODELS share palette's 3rd/4th pens
        hue_1, saturation_1, value_1 = rgb_to_hsv(accent_primary)
        self.accent_primary_dim = pen(hsv_to_rgb(hue_1, saturation_1 - 0.15, value_1 - 0.15))
        hue_2, saturation_2, value_2 = rgb_to_hsv(accent_secondary)
        self.accent_secondary_dim = pen(hsv_to_rgb(hue_2, saturation_2 - 0.15, value_2 - 0.15))
        self.accent_primary_dark = pen(scale(accent_primary, 0.76))
        self.accent_primary_light = pen(tint(accent_primary, 0.30))
        self.accent_primary_shadow = pen(scale(accent_primary, 0.43))
        self.accent_secondary_dark = pen(scale(accent_secondary, 0.64))
        self.accent_secondary_light = pen(tint(accent_secondary, 0.34))
        self.accent_secondary_shadow = pen(scale(accent_secondary, 0.37))
        self.accent_secondary_zero = pen(scale(accent_secondary, 0.575))  # zero-day chart stubs
        self.text_dark = pen(scale(text_color, 0.74))
        self.status_dark = pen(scale(status, 0.34))

        # ACTIVITY heatmap ramp (pico.js buildPalette): index 0 = zero-activity
        # shade, 1..4 = -15% saturation/value steps off accent_primary, 5 = pure
        # accent_primary. Matrix levels 1..4 index heat_ramp[level + 1].
        hue, saturation, value = rgb_to_hsv(accent_primary)
        self.heat_zero = pen(scale(background, 0.5))
        self.heat_ramp = (self.heat_zero,) + tuple(
            pen(hsv_to_rgb(hue, saturation - 0.15 * step, value - 0.15 * step))
            for step in (4, 3, 2, 1)
        ) + (self.accent_primary,)

        # avatar shades (pico.js: avatarD/avatarL/avatarSh)
        self.avatar_dark = pen(scale(avatar_color, 0.76))
        self.avatar_light = pen(tint(avatar_color, 0.30))
        self.avatar_shadow = pen(scale(avatar_color, 0.43))

        # Avatar eye whites: FIXED at the DEFAULT palette's cream, NOT the
        # theme's text slot — a palette with dark/coloured text (RETRO
        # DULLNESS is #000000) must not tint every avatar's eyeballs.
        # Settled with the M5 palette work (TODO note 2026-06-12); the blink
        # slits and BLIP's glowing happy smiley share it. Deliberate
        # divergence from the web, which uses var(--cream) and has the bug.
        self.eye_white = pen((0xD3, 0xD3, 0xD3))

    def accent_pens(self, accent_number):
        # accentPen(): accent 1 or 2 -> (color, dark, light, shadow) pens.
        # Every accent-coloured element picks its set through this.
        if accent_number == 2:
            return (
                self.accent_secondary,
                self.accent_secondary_dark,
                self.accent_secondary_light,
                self.accent_secondary_shadow,
            )
        return (
            self.accent_primary,
            self.accent_primary_dark,
            self.accent_primary_light,
            self.accent_primary_shadow,
        )
