# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# The drawing surface — MicroPython implementation of viewscreens/pico.js.
#
# screens draw EXCLUSIVELY through these primitives at absolute integer pixel
# coordinates (320x240, origin top-left), exactly like the browser canvas
# backend, so screens.js code ports ~1:1. Text sizes are either a type-scale
# ROLE name (resolved via the active font preset) or a raw pixel size; pixel
# fonts must be drawn at their native px or an integer multiple to stay crisp.

import badgeware  # noqa: F401 -- injects screen/shape/image/color/font globals

import design_fonts
from font_metrics import FONT_METRICS

# Hand-tuned per-glyph layout overrides: font_key -> character ->
# (ink_shift, advance), both in DESIGN pixels (scaled by px/native at draw).
# 5x7 MT Pixel centres '1' in its wide monospace cell (3-design-px left
# bearing, 6-px advance), which reads as a hole around every '1' at hero
# size — re-seat it as a proportional glyph: ink shifted to a 1-px bearing,
# advance 1+2+1 (user call 2026-06-12).
GLYPH_LAYOUT_OVERRIDES = {
    "5x7_mt_pixel": {"1": (-2, 4)},
}


class PicoDraw:
    def __init__(self, palette, type_scale):
        self.palette = palette  # a theme.Theme instance
        self.scale = type_scale  # role name -> (font_key, pixel_size)
        self.clock_text = "--:--"  # footer clock; the feed's generated_at HH:MM
        self.title_override = None  # replaces any chrome title (palette preview flow)
        self.connection_online = True  # footer status dot: palette status pen / black
        self.battery_cells = 4  # footer fuel gauge state (navigation sets these)
        self.battery_critical = False
        self.battery_static_empty = False
        self.battery_charging = False
        self._cap_top_cache = {}  # (font_key, px) -> rows between draw-y and the cap top
        self._advance_cache = {}  # (font_key, px) -> {character: real advance}

    # ---- primitives (1:1 with pico.js) ----

    def clear(self, pen):
        screen.pen = pen
        screen.clear()

    def rect(self, x, y, width, height, pen):
        screen.pen = pen
        screen.shape(shape.rectangle(int(x), int(y), int(width), int(height)))

    def border(self, x, y, width, height, pen, thickness=1):
        self.rect(x, y, width, thickness, pen)
        self.rect(x, y + height - thickness, width, thickness, pen)
        self.rect(x, y, thickness, height, pen)
        self.rect(x + width - thickness, y, thickness, height, pen)

    def hline(self, x, y, width, pen):
        self.rect(x, y, width, 1, pen)

    def pixel(self, x, y, pen):
        self.rect(x, y, 1, 1, pen)

    def dash(self, x, y, width, pen, on_length=4, off_length=4):
        cursor = 0
        while cursor < width:
            self.rect(x + cursor, y, min(on_length, width - cursor), 1, pen)
            cursor += on_length + off_length

    def tri(self, x, y, pointing, pen):
        # 4x7 pixel-staircase triangle; (x, y) is the top-left of the box.
        column_heights = (7, 5, 3, 1)
        for index in range(4):
            height = column_heights[index]
            column_y = y + ((7 - height) >> 1)
            column_x = x + index if pointing == "r" else x + (3 - index)
            self.rect(column_x, column_y, 1, height, pen)

    # ---- text ----

    def char_width(self, pixel_size):
        # layout-planning advance (the spec's arithmetic metric)
        return round(pixel_size * 0.6)

    def text_width(self, message, pixel_size, letter_spacing=0):
        length = len(str(message))
        if length == 0:
            return 0
        return length * self.char_width(pixel_size) + (length - 1) * letter_spacing

    def exact_text_width(self, message, size, font_key=None, letter_spacing=0):
        """True rendered width from the font's real per-character advances
        (text_width is the spec's arithmetic estimate; this is what text()
        actually draws). size: a type-scale role name or a raw px."""
        message = str(message)
        resolved_font_key, pixel_size = self._resolve_size(size, font_key)
        width = sum(
            self._character_advance(resolved_font_key, pixel_size, character)
            for character in message
        )
        if letter_spacing and message:
            width += (len(message) - 1) * letter_spacing
        return width

    def _resolve_size(self, size, font_key):
        if isinstance(size, str):  # a type-scale role
            role_font_key, pixel_size = self.scale[size]
            return role_font_key, pixel_size
        return font_key or "silk", size

    def _character_advance(self, font_key, pixel_size, character):
        # real per-character advance (the fonts are not strictly monospace:
        # 'i'/'.'/space run narrower), measured once and cached. Measured at
        # the grid-exact effective size, so advances are integer pixels.
        per_font_cache = self._advance_cache.setdefault((font_key, pixel_size), {})
        if character not in per_font_cache:
            override = GLYPH_LAYOUT_OVERRIDES.get(font_key, {}).get(character)
            if override:
                design_pixel = pixel_size / FONT_METRICS[font_key][0]
                per_font_cache[character] = round(override[1] * design_pixel)
                return per_font_cache[character]
            screen.font = design_fonts.FONT_REGISTRY[font_key]
            effective_size = design_fonts.effective_text_size(font_key, pixel_size)
            width, _ = screen.measure_text(character, effective_size)
            if width <= 0 and character == " ":
                width = self.char_width(pixel_size)
            if abs(width - round(width)) < 0.01:  # advances are integers by design
                width = round(width)
            per_font_cache[character] = width
        return per_font_cache[character]

    def _character_ink_shift(self, font_key, pixel_size, character):
        override = GLYPH_LAYOUT_OVERRIDES.get(font_key, {}).get(character)
        if not override:
            return 0
        return round(override[0] * pixel_size / FONT_METRICS[font_key][0])

    def _cap_top(self, font_key, pixel_size):
        # rows between the draw-y and the top of a capital glyph, so every
        # font's cap seats exactly at the draw-y (fonts stay swappable without
        # vertical drift) — the on-device equivalent of pico.js _capTop().
        cache_key = (font_key, pixel_size)
        if cache_key in self._cap_top_cache:
            return self._cap_top_cache[cache_key]
        gap = 0
        try:
            probe_size = max(8, int(pixel_size * 2))
            probe_image = image(probe_size, probe_size)
            # color objects have no equality operator; compare the packed
            # pixel value (.p) instead. A fresh image is all zeroes.
            blank_value = probe_image.get(probe_size - 1, probe_size - 1).p
            probe_image.font = design_fonts.FONT_REGISTRY[font_key]
            probe_image.antialias = image.OFF
            probe_image.pen = color.white
            probe_image.text(
                "W", 0, 0, design_fonts.effective_text_size(font_key, pixel_size)
            )
            found = False
            for row in range(probe_size):
                for column in range(probe_size):
                    if probe_image.get(column, row).p != blank_value:
                        gap = row
                        found = True
                        break
                if found:
                    break
        except Exception as error:  # never let a probe failure break drawing
            print("cap_top probe failed for", font_key, pixel_size, "->", error)
            gap = 0
        self._cap_top_cache[cache_key] = gap
        return gap

    def text(self, message, x, y, pen, size, font_key=None, letter_spacing=0, shadow=None, align="l"):
        """Draw text; returns its rendered width.

        size: a type-scale role name or a raw px. shadow: (dx, dy, pen).
        align: 'l' (x = left edge), 'r' (x = right edge), 'c' (x = centre).
        """
        message = str(message)
        resolved_font_key, pixel_size = self._resolve_size(size, font_key)
        screen.font = design_fonts.FONT_REGISTRY[resolved_font_key]

        # The .af advances are fractional (em-grid quantization), so glyphs are
        # ALWAYS placed individually at integer pixel columns: drawing a whole
        # string lets fractional advances accumulate and each glyph lands at a
        # different sub-pixel offset — with antialiasing off, 1px strokes then
        # vanish unpredictably (the classic broken-small-pixel-font look).
        advances = [
            self._character_advance(resolved_font_key, pixel_size, character)
            for character in message
        ]
        ink_shifts = [
            self._character_ink_shift(resolved_font_key, pixel_size, character)
            for character in message
        ]
        width = sum(advances)
        if letter_spacing and message:
            width += (len(message) - 1) * letter_spacing

        if align == "r":
            x = x - width
        elif align == "c":
            x = x - width / 2
        y = round(y) - self._cap_top(resolved_font_key, pixel_size)

        effective_size = design_fonts.effective_text_size(resolved_font_key, pixel_size)

        def draw_pass(pass_x, pass_y, pass_pen):
            # +0.25: stroke edges are exact integers, but float epsilon can
            # put an edge a hair below a pixel boundary; a quarter-pixel bias
            # keeps every edge strictly inside pixel cells (covers the same
            # pixels, immune to the boundary flip).
            screen.pen = pass_pen
            cursor_x = pass_x
            for index, character in enumerate(message):
                if character != " ":
                    screen.text(character, round(cursor_x + ink_shifts[index]) + 0.25,
                                pass_y + 0.25, effective_size)
                cursor_x += advances[index] + letter_spacing

        if shadow:
            shadow_dx, shadow_dy, shadow_pen = shadow
            draw_pass(x + shadow_dx, y + shadow_dy, shadow_pen)
        draw_pass(x, y, pen)
        return width
