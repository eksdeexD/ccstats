# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# OPTIONS screens + the B edit-mode flows.
#
# Layouts port drawOptDisplay / drawOptScreens / drawOptPalettes /
# drawOptAvatar / drawOptWifi from screens.js, with the device divergences
# by design: PALETTES and AVATAR are message-plus-preview
# screens (the web's static lists are replaced by live B-preview flows), and
# WIFI shows the real joined network instead of the web's placeholder list.
#
# Edit-mode contract (navigation.py drives it): B on a screen with an entry
# in B_FLOWS constructs the flow; while it is active, navigation routes every
# button to flow.handle_buttons() and draws via flow.draw(). The flow sets
# .finished on the confirming B press; an optional .on_finish() runs before
# navigation drops it. Footer bezel: B_HINTS labels B in normal mode, the
# flow's .footer_label replaces it while editing. Every value change writes
# straight through to flash (settings.update) — confirming just exits.

import random

import badgeware  # noqa: F401 -- drawing + badge/button globals
import network

import avatar_animation
import avatar_bubbles
import avatar_frames
import content_pack
import screens_tokens
import screens_trophies
import settings
import theme
from pico_draw import PicoDraw
from screen_shared import SECTION_LABEL_Y, draw_chrome, draw_section_label

OPTION_BOX_X = 4
OPTION_BOX_WIDTH = 312
OPTION_LABEL_X = 10
OPTION_VALUE_RIGHT_X = 308

ANIMATION_SPEED_STEPS = (0.5, 1.0, 1.5, 2.0)
BRIGHTNESS_STEP = 0.05  # UI percent over the USABLE range (main.apply_brightness)


def _draw_option_box(P, y, height, selected=False):
    # the spec's optBox; a selected row swaps the edge border for accent 1
    C = P.palette
    P.rect(OPTION_BOX_X, y, OPTION_BOX_WIDTH, height, C.panel)
    P.border(OPTION_BOX_X, y, OPTION_BOX_WIDTH, height, C.accent_primary if selected else C.edge, 1)
    if selected:
        P.rect(OPTION_BOX_X + 3, y + 3, 2, height - 6, C.accent_primary)  # active marker


def _data_screen_ids():
    # every hideable / boot-eligible screen: the ported data screens. OPTIONS
    # screens stay out so the editor can never hide its own way back in.
    import screen_registry

    return [screen_id for screen_id, category, _ in screen_registry.PORTED_SCREENS
            if category != "OPTIONS"]


def _screen_title(screen_id):
    import screen_registry

    return screen_registry.SCREEN_TITLES.get(screen_id, screen_id.upper())


# ---- DISPLAY: the preferences list -----------------------------------------

DISPLAY_LIST_Y = 44
DISPLAY_ROW_PITCH = 18  # web is 23 for 7 rows; the longer device list needs 18
DISPLAY_BOX_HEIGHT = 16
DISPLAY_VISIBLE_ROWS = 10  # the list scrolls beyond this (like SCREENS)


def _display_rows(navigation):
    """[(label, value_text_function, step_function(direction)), ...] —
    step functions write through to settings (and apply live effects)."""

    def token_text():
        return "ALL TOKENS" if settings.get("token_mode") == "all" else "WITHOUT CACHE"

    def token_step(direction):
        settings.update("token_mode", "all" if settings.get("token_mode") == "nocache" else "nocache")

    def boot_text():
        return _screen_title(settings.get("boot_screen"))

    def boot_step(direction):
        choices = _data_screen_ids()
        current = settings.get("boot_screen")
        index = choices.index(current) if current in choices else 0
        settings.update("boot_screen", choices[(index + direction) % len(choices)])

    def font_text():
        return settings.get("font_preset").upper()

    def font_step(direction):
        # opens the live preview (user spec 2026-06-13) — same concept as
        # the palette preview; the row itself never cycles blind
        navigation.edit_flow = FontPreviewFlow(navigation)

    def speed_text():
        return "%.1fX" % settings.get("animation_speed")

    def speed_step(direction):
        # opens the live preview (user spec 2026-06-13): adjust the speed
        # while WATCHING the avatar, instead of editing a blind number
        navigation.edit_flow = AnimationSpeedPreviewFlow(navigation)

    def brightness_text():
        return "%d%%" % round(settings.get("brightness") * 100)

    def brightness_step(direction):
        import main

        value = settings.get("brightness") + direction * BRIGHTNESS_STEP
        value = max(0.0, min(1.0, round(value * 100) / 100))
        settings.update("brightness", value)
        # live and UNDIMMED so the arrows show the real level even on
        # battery; navigation re-applies the battery dim after the editor
        main.apply_brightness(value)

    def toggle_text(key, inverted=False):
        def text():
            enabled = settings.get(key)
            if inverted:
                enabled = not enabled
            return "ON" if enabled else "OFF"
        return text

    def toggle_step(key):
        def step(direction):
            settings.update(key, not settings.get(key))
        return step

    def reset_step(direction):
        _reset_defaults(navigation)

    def demo_step(direction):
        # replaces the DISPLAY editor as the active flow; any button exits it
        navigation.edit_flow = DemoFlow(navigation)

    def about_step(direction):
        # replaces the DISPLAY editor as the active flow; any button exits it
        navigation.edit_flow = AboutFlow(navigation)

    def avatar_line_text(slot):
        import options

        def text():
            return options.AVATAR_LINE_LABELS[settings.get("avatar_line_%d" % slot)]
        return text

    def avatar_line_step(slot):
        import options

        def step(direction):
            key = "avatar_line_%d" % slot
            modes = options.AVATAR_LINE_MODES
            current = settings.get(key)
            index = modes.index(current) if current in modes else 0
            settings.update(key, modes[(index + direction) % len(modes)])
        return step

    return (
        ("TOKENS DEFAULT", token_text, token_step),
        ("BOOT SCREEN", boot_text, boot_step),
        ("FONT PRESET", font_text, font_step),
        ("ANIMATION SPEED", speed_text, speed_step),
        ("BRIGHTNESS", brightness_text, brightness_step),
        ("DIM ON BATTERY", toggle_text("dim_on_battery"), toggle_step("dim_on_battery")),
        ("AVATAR LINE 1", avatar_line_text(1), avatar_line_step(1)),
        ("AVATAR LINE 2", avatar_line_text(2), avatar_line_step(2)),
        # the stored key is the OFF-switch; the row reads as the saver itself
        ("BATTERY SAVER", toggle_text("battery_saver_off", inverted=True), toggle_step("battery_saver_off")),
        ("AUTO BOOT", toggle_text("auto_boot"), toggle_step("auto_boot")),
        ("DEMO MODE", lambda: ">", demo_step),
        ("RESET DEFAULTS", lambda: ">", reset_step),
        ("ABOUT", lambda: ">", about_step),
    )


def _reset_defaults(navigation):
    import main
    import screen_registry
    from type_scale import get_active_scale

    for key, default_value in settings.DEFAULTS.items():
        # mutables get a copy — settings.update keeps a reference to what it is given
        if isinstance(default_value, list):
            default_value = list(default_value)
        settings.update(key, default_value)
    main.apply_brightness(settings.get("brightness"))
    navigation.painter.palette.apply(theme.preset_slots(settings.get("palette")))
    navigation.painter.scale = get_active_scale()
    avatar_animation.animator.sprite_name = settings.get("sprite_name")
    navigation.categories = screen_registry.categories_with_screens()


def draw_options_display(P, stats_payload, selected_row=None, window_start=0):
    C = P.palette
    draw_chrome(P, "DISPLAY", "OPTIONS")
    draw_section_label(P, "PREFERENCES", SECTION_LABEL_Y)
    rows = _display_rows(None)
    if len(rows) > DISPLAY_VISIBLE_ROWS:
        P.text("%d-%d / %d" % (window_start + 1,
                               min(window_start + DISPLAY_VISIBLE_ROWS, len(rows)), len(rows)),
               314, SECTION_LABEL_Y, C.text_dark, "caption", letter_spacing=1, align="r")
    for visible_index, (label, value_text, _) in enumerate(
            rows[window_start:window_start + DISPLAY_VISIBLE_ROWS]):
        row_index = window_start + visible_index
        y = DISPLAY_LIST_Y + visible_index * DISPLAY_ROW_PITCH
        _draw_option_box(P, y, DISPLAY_BOX_HEIGHT, selected=row_index == selected_row)
        P.text(label, OPTION_LABEL_X, y + 4, C.text, "row_label", letter_spacing=1)
        P.text(value_text(), OPTION_VALUE_RIGHT_X, y + 4, C.accent_primary, "row_label", align="r")


class DisplayEditFlow:
    footer_label = "CONFIRM"

    def __init__(self, navigation):
        self.navigation = navigation
        self.rows = _display_rows(navigation)
        self.row_index = 0
        self.window_start = 0
        self.finished = False

    def handle_buttons(self):
        changed = False
        if badge.pressed(BUTTON_UP):
            self.row_index = (self.row_index - 1) % len(self.rows)
            changed = True
        if badge.pressed(BUTTON_DOWN):
            self.row_index = (self.row_index + 1) % len(self.rows)
            changed = True
        if badge.pressed(BUTTON_A):
            self.rows[self.row_index][2](-1)
            changed = True
        if badge.pressed(BUTTON_C):
            self.rows[self.row_index][2](1)
            changed = True
        if badge.pressed(BUTTON_B):
            self.finished = True
            changed = True
        # keep the selection inside the visible window
        if self.row_index < self.window_start:
            self.window_start = self.row_index
        elif self.row_index >= self.window_start + DISPLAY_VISIBLE_ROWS:
            self.window_start = self.row_index - DISPLAY_VISIBLE_ROWS + 1
        return changed

    def draw(self, P, stats_payload):
        draw_options_display(P, stats_payload,
                             selected_row=self.row_index, window_start=self.window_start)


# ---- SCREENS: per-screen show/hide ------------------------------------------

SCREENS_LIST_Y = 44
SCREENS_ROW_PITCH = 21
SCREENS_BOX_HEIGHT = 18
SCREENS_VISIBLE_ROWS = 8


def draw_options_screens(P, stats_payload, selected_row=None, window_start=0):
    C = P.palette
    draw_chrome(P, "SCREENS", "OPTIONS")
    draw_section_label(P, "SHOW / HIDE SCREENS", SECTION_LABEL_Y)
    screen_ids = _data_screen_ids()
    hidden_screens = settings.get("hidden_screens")
    P.text("%d-%d / %d" % (window_start + 1,
                           min(window_start + SCREENS_VISIBLE_ROWS, len(screen_ids)),
                           len(screen_ids)),
           314, SECTION_LABEL_Y, C.text_dark, "caption", letter_spacing=1, align="r")
    for visible_index, screen_id in enumerate(
            screen_ids[window_start:window_start + SCREENS_VISIBLE_ROWS]):
        row_index = window_start + visible_index
        y = SCREENS_LIST_Y + visible_index * SCREENS_ROW_PITCH
        _draw_option_box(P, y, SCREENS_BOX_HEIGHT, selected=row_index == selected_row)
        P.text(_screen_title(screen_id), OPTION_LABEL_X, y + 5, C.text, "row_label", letter_spacing=1)
        is_shown = screen_id not in hidden_screens
        P.text("ON" if is_shown else "OFF", OPTION_VALUE_RIGHT_X, y + 5,
               C.status if is_shown else C.text_dark, "row_label", align="r")


class ScreensEditFlow:
    footer_label = "CONFIRM"

    def __init__(self, navigation):
        self.navigation = navigation
        self.screen_ids = _data_screen_ids()
        self.row_index = 0
        self.window_start = 0
        self.finished = False

    def _toggle(self):
        screen_id = self.screen_ids[self.row_index]
        hidden_screens = list(settings.get("hidden_screens"))
        if screen_id in hidden_screens:
            hidden_screens.remove(screen_id)
        else:
            hidden_screens.append(screen_id)
        settings.update("hidden_screens", hidden_screens)

    def handle_buttons(self):
        changed = False
        if badge.pressed(BUTTON_UP):
            self.row_index = (self.row_index - 1) % len(self.screen_ids)
            changed = True
        if badge.pressed(BUTTON_DOWN):
            self.row_index = (self.row_index + 1) % len(self.screen_ids)
            changed = True
        if badge.pressed(BUTTON_A) or badge.pressed(BUTTON_C):
            self._toggle()
            changed = True
        if badge.pressed(BUTTON_B):
            self.finished = True
            changed = True
        # keep the selection inside the visible window
        if self.row_index < self.window_start:
            self.window_start = self.row_index
        elif self.row_index >= self.window_start + SCREENS_VISIBLE_ROWS:
            self.window_start = self.row_index - SCREENS_VISIBLE_ROWS + 1
        return changed

    def on_finish(self):
        # the hidden list changed — rebuild navigation over the survivors
        import screen_registry

        self.navigation.categories = screen_registry.categories_with_screens()
        self.navigation._show_screen("options_screens")

    def draw(self, P, stats_payload):
        draw_options_screens(P, stats_payload,
                             selected_row=self.row_index, window_start=self.window_start)


# ---- PALETTES: active preset + the B live-preview entry message -------------

PALETTE_SWATCH_SIZE = 10
PALETTE_SWATCH_GAP = 1


def _draw_palette_row(P, y, preset, selected=False):
    # one palette row (web active-row style): marker, name, 6-swatch strip
    C = P.palette
    _draw_option_box(P, y, 16, selected=selected)
    P.text(preset[0], 13, y + 4, C.text, "row_label", letter_spacing=1)
    swatch_x = OPTION_VALUE_RIGHT_X - (6 * (PALETTE_SWATCH_SIZE + PALETTE_SWATCH_GAP) - PALETTE_SWATCH_GAP)
    for slot_hex in preset[1:]:
        P.rect(swatch_x, y + 3, PALETTE_SWATCH_SIZE, PALETTE_SWATCH_SIZE,
               color.rgb(*theme.parse_hex(slot_hex)))
        P.border(swatch_x, y + 3, PALETTE_SWATCH_SIZE, PALETTE_SWATCH_SIZE, C.edge, 1)
        swatch_x += PALETTE_SWATCH_SIZE + PALETTE_SWATCH_GAP


def _active_palette_preset():
    active_name = settings.get("palette")
    for preset in theme.PALETTE_PRESETS:
        if preset[0] == active_name:
            return preset
    return theme.PALETTE_PRESETS[0]


def draw_options_palettes(P, stats_payload):
    # the device flow: no list — the active preset plus
    # the B-preview instructions; B opens the live TOKEN USAGE preview
    C = P.palette
    draw_chrome(P, "PALETTES", "OPTIONS")
    draw_section_label(P, "COLOR THEMES", SECTION_LABEL_Y)
    _draw_palette_row(P, 44, _active_palette_preset(), selected=True)
    P.text("ACTIVE", OPTION_LABEL_X + 3, 66, C.status, "caption", letter_spacing=1)
    P.text("PRESS B TO PREVIEW PALETTES", 160, 120, C.text, "caption", letter_spacing=1, align="c")
    P.text("PRESS B AGAIN TO CONFIRM", 160, 134, C.text_dark, "caption", letter_spacing=1, align="c")


class PalettePreviewFlow:
    """The live preview: B opens the TOKEN USAGE
    screen really rendered in the candidate palette, the title shows the
    palette's name, CONFIRM sits over B; A/C (or UP/DOWN) cycle the presets;
    B confirms whatever is on screen. The flow draws through its OWN painter
    so the real theme object is never touched until the confirming B."""

    footer_label = "CONFIRM"

    def __init__(self, navigation):
        self.navigation = navigation
        active_name = settings.get("palette")
        preset_names = [preset[0] for preset in theme.PALETTE_PRESETS]
        self.preset_index = preset_names.index(active_name) if active_name in preset_names else 0
        self.preview_theme = theme.Theme(theme.preset_slots(active_name))
        self.painter = PicoDraw(self.preview_theme, navigation.painter.scale)
        self.finished = False
        self._apply_preview()

    def _preset_name(self):
        return theme.PALETTE_PRESETS[self.preset_index][0]

    def _apply_preview(self):
        self.preview_theme.apply(theme.preset_slots(self._preset_name()))
        self.painter.title_override = self._preset_name()

    def _cycle(self, direction):
        self.preset_index = (self.preset_index + direction) % len(theme.PALETTE_PRESETS)
        self._apply_preview()

    def handle_buttons(self):
        changed = False
        if badge.pressed(BUTTON_A) or badge.pressed(BUTTON_UP):
            self._cycle(-1)
            changed = True
        if badge.pressed(BUTTON_C) or badge.pressed(BUTTON_DOWN):
            self._cycle(1)
            changed = True
        if badge.pressed(BUTTON_B):
            self.finished = True
            changed = True
        return changed

    def on_finish(self):
        preset_name = self._preset_name()
        settings.update("palette", preset_name)
        # the shared theme object every screen draws with follows the pick
        self.navigation.painter.palette.apply(theme.preset_slots(preset_name))

    def draw(self, P, stats_payload):
        screens_tokens.draw_tokens(P, stats_payload)


class FontPreviewFlow:
    """Font preset selection exactly like the palette preview (user spec
    2026-06-13): TOKEN USAGE truly rendered in the candidate type scale,
    the title shows the preset's name, CONFIRM over B; A/C (or UP/DOWN)
    cycle, B confirms. Draws through its own painter so the live scale is
    untouched until the confirming B."""

    footer_label = "CONFIRM"

    def __init__(self, navigation):
        from type_scale import FONT_PRESETS

        self.navigation = navigation
        self.preset_keys = sorted(FONT_PRESETS)
        active_key = settings.get("font_preset")
        self.preset_index = (self.preset_keys.index(active_key)
                             if active_key in self.preset_keys else 0)
        self.painter = PicoDraw(navigation.painter.palette,
                                FONT_PRESETS[self.preset_keys[self.preset_index]])
        self.finished = False
        self._apply_preview()

    def _preset_key(self):
        return self.preset_keys[self.preset_index]

    def _apply_preview(self):
        from type_scale import FONT_PRESETS

        self.painter.scale = FONT_PRESETS[self._preset_key()]
        self.painter.title_override = self._preset_key().upper()

    def _cycle(self, direction):
        self.preset_index = (self.preset_index + direction) % len(self.preset_keys)
        self._apply_preview()

    def handle_buttons(self):
        changed = False
        if badge.pressed(BUTTON_A) or badge.pressed(BUTTON_UP):
            self._cycle(-1)
            changed = True
        if badge.pressed(BUTTON_C) or badge.pressed(BUTTON_DOWN):
            self._cycle(1)
            changed = True
        if badge.pressed(BUTTON_B):
            self.finished = True
            changed = True
        return changed

    def on_finish(self):
        from type_scale import get_active_scale

        settings.update("font_preset", self._preset_key())
        self.navigation.painter.scale = get_active_scale()

    def draw(self, P, stats_payload):
        screens_tokens.draw_tokens(P, stats_payload)


class AnimationSpeedPreviewFlow:
    """The animation-speed editor (user spec 2026-06-13): a CLAUDE
    CODE-style screen with NOTHING but the avatar — title ANIMATION SPEED,
    A/C adjust the speed while the avatar visibly bobs at it (writes
    through live; the animator reads the setting every frame), B confirms.
    The word band shows ANIMATION SPEED over the current value. Runs a
    private working-state animator (most motion to judge by)."""

    footer_label = "CONFIRM"

    def __init__(self, navigation):
        self.navigation = navigation
        self.animator = _PreviewAnimator()
        self.animator.bubble_director = _PinnedBubbleDirector()
        self.animator.sprite_name = avatar_animation.animator.sprite_name
        self.animator._set_visual_state("working")
        self.finished = False

    def _step(self, direction):
        steps = ANIMATION_SPEED_STEPS
        current = settings.get("animation_speed")
        nearest = min(range(len(steps)), key=lambda i: abs(steps[i] - current))
        settings.update("animation_speed", steps[(nearest + direction) % len(steps)])

    def handle_buttons(self):
        changed = False
        if badge.pressed(BUTTON_A):
            self._step(-1)
            changed = True
        if badge.pressed(BUTTON_C):
            self._step(1)
            changed = True
        if badge.pressed(BUTTON_B):
            self.finished = True
            changed = True
        return changed

    def draw(self, P, stats_payload):
        C = P.palette
        draw_chrome(P, "ANIMATION SPEED", "PREVIEW")
        self.animator.draw_stage(P)
        P.text("ANIMATION SPEED", 160, 208, C.text, "caption", letter_spacing=1, align="c")
        P.text("%.1fX" % settings.get("animation_speed"), 160, 217,
               C.accent_primary, "caption", letter_spacing=1, align="c")

    def animate(self, P):
        return self.animator.update(P)


# ---- AVATAR: active sprite + the B live-preview flow ------------------------

# the web's CYCLE tile intervals (CYCLE_MINS in view/screens.js)
CYCLE_INTERVAL_MINUTES = (5, 15, 30, 60, 180, 360, 720, 1440)

CYCLE_ENTRY = "cycle"  # the pseudo-entry after the sprite roster

PREVIEW_STATES = ("idle", "working", "done", "bubble")


def _interval_label(minutes):
    if minutes < 60:
        return "%d MINUTES" % minutes
    hours = minutes // 60
    return "1 HOUR" if hours == 1 else "%d HOURS" % hours


def _random_book_reference():
    # a preview bubble like the bottleneck book taunts: random taunt template
    # x random book from any non-empty tier
    taunts = content_pack.bank("book_taunts")
    tiers = [books for books in avatar_bubbles.BOOKS_BY_TIER if books]
    books = tiers[random.randrange(len(tiers))]
    return (taunts[random.randrange(len(taunts))]
            .replace("{book}", books[random.randrange(len(books))]))


class _PinnedBubbleDirector:
    """Stands in for the preview animator's BubbleDirector: shows exactly the
    pick the flow pinned (or nothing) instead of arbitrating live feeds."""

    def __init__(self):
        self.pick = None

    def update(self, visual_state, stats_payload):
        return self.pick


class _PreviewAnimator(avatar_animation.AvatarAnimator):
    # the preview owns the word band (instruction text) — the ticker word and
    # the breathing spark must not draw over it
    def draw_word(self, P):
        pass

    def _draw_star(self, P, clear=False):
        pass


class AvatarPreviewFlow:
    """The live preview: a CLAUDE CODE-style screen
    titled with the sprite's name; A/C cycle the roster (+ the CYCLE AVATARS
    pseudo-entry), UP/DOWN cycle states (idle / working / done / book-quote
    bubble) — or, on the pseudo-entry, the auto-cycle interval. No session
    bar / stats line / status text: the word band holds the key help. B
    confirms: a sprite pick also turns auto-cycle OFF (like the web, where
    'cycle' is itself the style); confirming CYCLE AVATARS sets the interval.

    Runs a private animator instance so the live one's state machine and
    timers are never touched."""

    footer_label = "CONFIRM"

    def __init__(self, navigation):
        self.navigation = navigation
        self.entries = list(avatar_frames.SPRITE_ORDER) + [CYCLE_ENTRY]
        active_sprite = avatar_animation.animator.sprite_name
        if settings.get("avatar_cycle_minutes"):
            # auto-cycle IS the active pick — open the preview on its entry
            self.entry_index = len(self.entries) - 1
        else:
            self.entry_index = (self.entries.index(active_sprite)
                                if active_sprite in self.entries else 0)
        self.state_index = 0  # idle, per the spec's default
        saved_interval = settings.get("avatar_cycle_minutes")
        self.interval_index = (CYCLE_INTERVAL_MINUTES.index(saved_interval)
                               if saved_interval in CYCLE_INTERVAL_MINUTES else 1)  # 15 min
        self.bubble_sequence = 0
        self.animator = _PreviewAnimator()
        self.animator.bubble_director = _PinnedBubbleDirector()
        self.finished = False
        self._apply_entry()

    def _is_cycle_entry(self):
        return self.entries[self.entry_index] == CYCLE_ENTRY

    def _apply_entry(self):
        if self._is_cycle_entry():
            return
        self.animator.sprite_name = self.entries[self.entry_index]
        self._apply_state()

    def _apply_state(self):
        state = PREVIEW_STATES[self.state_index]
        director = self.animator.bubble_director
        if state == "bubble":
            self.animator.visual_state = "idle"
            self.bubble_sequence += 1  # fresh key -> fresh random book line
            director.pick = ("speak", _random_book_reference(),
                             "preview:%d" % self.bubble_sequence)
        else:
            self.animator.visual_state = state
            director.pick = None

    def handle_buttons(self):
        changed = False
        if badge.pressed(BUTTON_A):
            self.entry_index = (self.entry_index - 1) % len(self.entries)
            self._apply_entry()
            changed = True
        if badge.pressed(BUTTON_C):
            self.entry_index = (self.entry_index + 1) % len(self.entries)
            self._apply_entry()
            changed = True
        if badge.pressed(BUTTON_UP):
            if self._is_cycle_entry():
                self.interval_index = (self.interval_index - 1) % len(CYCLE_INTERVAL_MINUTES)
            else:
                self.state_index = (self.state_index - 1) % len(PREVIEW_STATES)
                self._apply_state()
            changed = True
        if badge.pressed(BUTTON_DOWN):
            if self._is_cycle_entry():
                self.interval_index = (self.interval_index + 1) % len(CYCLE_INTERVAL_MINUTES)
            else:
                self.state_index = (self.state_index + 1) % len(PREVIEW_STATES)
                self._apply_state()
            changed = True
        if badge.pressed(BUTTON_B):
            self.finished = True
            changed = True
        return changed

    def on_finish(self):
        if self._is_cycle_entry():
            settings.update("avatar_cycle_minutes", CYCLE_INTERVAL_MINUTES[self.interval_index])
            self.navigation.last_sprite_cycle_ticks = badge.ticks  # interval starts now
        else:
            sprite_name = self.entries[self.entry_index]
            settings.update("sprite_name", sprite_name)
            avatar_animation.animator.sprite_name = sprite_name
            settings.update("avatar_cycle_minutes", 0)  # an explicit pick ends auto-cycling

    def draw(self, P, stats_payload):
        C = P.palette
        if self._is_cycle_entry():
            draw_chrome(P, "CYCLE AVATARS", "OPTIONS")
            P.text("?", 160, 96, C.avatar_color, 42, "5x7_mt_pixel", align="c")
            P.text(_interval_label(CYCLE_INTERVAL_MINUTES[self.interval_index]),
                   160, 208, C.text, "caption", letter_spacing=1, align="c")
            P.text("UP+DOWN SET CYCLE TIME", 160, 217, C.text_dark, "caption",
                   letter_spacing=1, align="c")
            return
        sprite_label = avatar_frames.SPRITE_INFO.get(
            self.animator.sprite_name, {}).get("label", self.animator.sprite_name.upper())
        draw_chrome(P, sprite_label, PREVIEW_STATES[self.state_index].upper())
        self.animator.draw_stage(P)
        P.text("LEFT+RIGHT CYCLE AVATARS", 160, 208, C.text, "caption",
               letter_spacing=1, align="c")
        P.text("UP+DOWN CYCLE STATES", 160, 217, C.text_dark, "caption",
               letter_spacing=1, align="c")

    def animate(self, P):
        # partial-region frames between full redraws (navigation loop hook)
        if self._is_cycle_entry():
            return False
        return self.animator.update(P)


def draw_options_avatar(P, stats_payload):
    # device flow: the active pick plus the B-preview
    # instructions; B opens the live preview screen. With auto-cycle ON the
    # pick IS the cycle (user fix 2026-06-13) — show the "?" and the
    # interval, not whichever sprite happens to be on stage right now.
    C = P.palette
    draw_chrome(P, "AVATAR", "OPTIONS")
    draw_section_label(P, "AVATAR STYLE", SECTION_LABEL_Y)
    cycle_minutes = settings.get("avatar_cycle_minutes")
    if cycle_minutes:
        P.text("CYCLE AVATARS EVERY " + _interval_label(cycle_minutes),
               160, 44, C.text, "caption", letter_spacing=1, align="c")
        P.text("?", 160, 96, C.avatar_color, 42, "5x7_mt_pixel", align="c")
    else:
        animator = avatar_animation.animator
        sprite_label = avatar_frames.SPRITE_INFO.get(
            animator.sprite_name, {}).get("label", animator.sprite_name.upper())
        P.text(sprite_label + " • ACTIVE", 160, 44, C.text, "caption", letter_spacing=1, align="c")
        animator.draw_stage(P, static=True)
    P.text("PRESS B TO PREVIEW AVATARS", 160, 208, C.text, "caption", letter_spacing=1, align="c")
    P.text("PRESS B AGAIN TO CONFIRM", 160, 217, C.text_dark, "caption", letter_spacing=1, align="c")


# ---- WIFI: the real joined network (the web list is a placeholder) ----------

def _signal_bar_count(rssi):
    if rssi is None:
        return 0
    if rssi >= -55:
        return 4
    if rssi >= -65:
        return 3
    if rssi >= -75:
        return 2
    return 1


def draw_options_wifi(P, stats_payload):
    # Divergence from drawOptWifi's four fake networks: the device shows the
    # network it is actually on. The join/config flow is still to come (M5).
    C = P.palette
    draw_chrome(P, "WIFI", "OPTIONS")
    draw_section_label(P, "NETWORK", SECTION_LABEL_Y)
    wlan = network.WLAN(network.STA_IF)
    is_connected = wlan.isconnected()
    try:
        rssi = wlan.status("rssi") if is_connected else None
    except (OSError, ValueError):
        rssi = None
    try:
        joined_ssid = wlan.config("ssid") if is_connected else None
    except (OSError, ValueError):
        joined_ssid = None

    y = 46
    _draw_option_box(P, y, 20)
    P.text((joined_ssid or "NOT CONNECTED").upper(), OPTION_LABEL_X, y + 6,
           C.text, "row_label", letter_spacing=1)
    bar_width = 3
    bar_gap = 2
    bars_x = OPTION_VALUE_RIGHT_X - (4 * bar_width + 3 * bar_gap)
    lit_bars = _signal_bar_count(rssi)
    for bar in range(4):  # 4 rising signal bars, right-aligned in the box
        bar_height = 3 + bar * 2
        P.rect(bars_x + bar * (bar_width + bar_gap), y + 15 - bar_height,
               bar_width, bar_height, C.accent_secondary if bar < lit_bars else C.edge)

    P.text("STATUS", OPTION_LABEL_X, 78, C.text_dark, "caption", letter_spacing=1)
    P.text("CONNECTED" if is_connected else "DISCONNECTED", OPTION_VALUE_RIGHT_X, 78,
           C.status if is_connected else C.accent_primary, "caption", letter_spacing=1, align="r")
    P.text("IP", OPTION_LABEL_X, 92, C.text_dark, "caption", letter_spacing=1)
    P.text(wlan.ifconfig()[0] if is_connected else "-", OPTION_VALUE_RIGHT_X, 92,
           C.text, "caption", letter_spacing=1, align="r")
    if rssi is not None:
        P.text("SIGNAL", OPTION_LABEL_X, 106, C.text_dark, "caption", letter_spacing=1)
        P.text("%d DBM" % rssi, OPTION_VALUE_RIGHT_X, 106, C.text, "caption",
               letter_spacing=1, align="r")

    # which config source the join chain uses (settled 2026-06-13: networks
    # are edited in DISK MODE, no on-device editor)
    import main

    P.text("CONFIG: " + main.wifi_config_source(), OPTION_LABEL_X, 124,
           C.text_dark, "caption", letter_spacing=1)

    draw_section_label(P, "ADD NETWORKS IN DISK MODE", 146)
    P.text("1. DOUBLE-PRESS THE RESET BUTTON", OPTION_LABEL_X, 160, C.text, "caption",
           letter_spacing=1)
    P.text("2. CONNECT USB - THE BADGE IS A DISK", OPTION_LABEL_X, 172, C.text, "caption",
           letter_spacing=1)
    P.text("3. EDIT WIFI.TXT IN ITS ROOT", OPTION_LABEL_X, 184, C.text, "caption",
           letter_spacing=1)
    P.text("4. EJECT - THE BADGE REBOOTS", OPTION_LABEL_X, 196, C.text, "caption",
           letter_spacing=1)
    P.text("SSID LINE, PASSWORD LINE, REPEAT", OPTION_LABEL_X, 212, C.text_dark, "caption",
           letter_spacing=1)


# ---- ABOUT: Lord White Paws (full-bleed easter egg) -------------------------

# A tribute to the user's cat, reached from the DISPLAY list (the ABOUT row,
# under RESET DEFAULTS). Selecting it opens AboutFlow — like DEMO MODE, it
# replaces the DISPLAY editor as the active flow, and ANY
# button exits back to the list. The photo is exactly screen-sized (320x240
# RGB), drawn edge to edge with NO chrome (the flow sets suppress_footer so
# navigation.draw leaves the A/C arrows off the picture); any caption is baked
# into the image. Loaded from device FLASH only: image.load through the
# mpremote mount bridge crashes the host server (same pitfall as the splash and
# the fonts), so it reads the installed app copy or the dev-run root copy
# (mpremote cp firmware/lordwhitepaws.png :/lordwhitepaws.png, once). Decoded on
# first view (~300 KB RGBA) and cached — fine on the 8 MB-PSRAM board.
ABOUT_IMAGE_LOCATIONS = (
    "/system/apps/ccstats/lordwhitepaws.png",
    "/lordwhitepaws.png",
)
_about_image = None


class AboutFlow:
    """Full-bleed photo of Lord White Paws, opened from the DISPLAY ABOUT row.
    Pure tribute — nothing to adjust, so ANY button exits back to the list."""

    footer_label = None  # no B label
    suppress_footer = True  # and no A/C arrows over the photo

    def __init__(self, navigation):
        self.navigation = navigation
        self.finished = False

    def handle_buttons(self):
        if (badge.pressed(BUTTON_A) or badge.pressed(BUTTON_B) or badge.pressed(BUTTON_C)
                or badge.pressed(BUTTON_UP) or badge.pressed(BUTTON_DOWN)):
            self.finished = True
            return True
        return False

    def draw(self, P, stats_payload):
        global _about_image
        P.clear(P.palette.background)  # fallback fill if the photo can't be loaded
        if _about_image is None:
            for image_path in ABOUT_IMAGE_LOCATIONS:
                try:
                    _about_image = image.load(image_path)
                    break
                except OSError:
                    continue
        if _about_image is not None:
            screen.blit(_about_image, vec2(0, 0))


# ---- DEMO MODE: the hands-free screen tour for video recording --------------

# (kind, ...) steps:
#   ("screen", screen_id, ms)               -> a data/options screen in the
#                                              user's ACTIVE palette + font;
#   ("screen", screen_id, palette_name, ms) -> the same, but FORCED into a named
#                                              palette (the palette showcase);
#   ("avatar", sprite, state, ms)           -> a sprite + state on the real
#                                              AVATAR screen.
# Avatar segments 4 s each (one sprite per state), screens 3 s, looping. The four
# avatar states are a fixed sprite tour (user-chosen); the three trailing screens
# show off distinct palettes right after the PALETTES options screen.
DEMO_SEQUENCE = (
    ("avatar", "gloom", "idle", 4000),
    ("avatar", "dimple", "working", 4000),
    ("avatar", "blip", "bubble", 4000),
    ("avatar", "pip", "done", 4000),
    ("screen", "usage", 3000),
    ("screen", "projects", 3000),
    ("screen", "calendar", 3000),
    ("screen", "trophies", 3000),
    ("screen", "options_display", 3000),
    ("screen", "options_palettes", 3000),
    ("screen", "words", "ACIDIC WATERMELON", 3000),
    ("screen", "versus_human", "GRRLY", 3000),
    ("screen", "models", "SANDEE", 3000),
)

# The demo bubble is a FIXED book taunt (book_taunts template 0 × "1984") so the
# filmed loop is deterministic, not the live random pick (_random_book_reference).
DEMO_BUBBLE_TEXT = 'Could\'ve written "1984" by now.'


class DemoFlow:
    """The demo mode: loops the curated tour above until ANY button
    is pressed — for filming the badge without touching it. Avatar segments
    drive a private animator through the REAL avatar screen drawing (the
    live animator is swapped in only for the draw call, never mutated), with
    a pinned book-taunt bubble in the 'bubble' step. Started from the
    DISPLAY editor's DEMO MODE row."""

    footer_label = None  # clean footer on camera

    def __init__(self, navigation):
        self.navigation = navigation
        self.step_index = 0
        self.step_started_ticks = badge.ticks
        self.bubble_sequence = 0
        self.animator = avatar_animation.AvatarAnimator()
        self.animator.bubble_director = _PinnedBubbleDirector()
        self.finished = False
        # the demo draws through its OWN painter (a clone of the active theme),
        # so palette-showcase steps can swap palette without touching the live
        # theme; navigation draws the footer chrome on this same painter, so the
        # footer follows each step's palette too. Discarded on exit -> the live
        # theme is never dirtied.
        self.active_palette = settings.get("palette")
        self.painter = PicoDraw(theme.Theme(theme.preset_slots(self.active_palette)),
                                navigation.painter.scale)
        # pre-import every sprite the tour visits NOW: a lazy import after a
        # mounted dev host detaches hard-wedges the badge (device-pitfalls)
        for step in DEMO_SEQUENCE:
            if step[0] == "avatar":
                avatar_frames.sprite(step[1])
        self._apply_step()

    def _step(self):
        return DEMO_SEQUENCE[self.step_index]

    def _apply_step(self):
        step = self._step()
        # palette: a named showcase palette on 4-tuple screen steps, else active
        palette_name = (step[2] if step[0] == "screen" and len(step) == 4
                        else self.active_palette)
        self.painter.palette.apply(theme.preset_slots(palette_name))
        if step[0] != "avatar":
            return
        _, sprite_name, state, _ = step
        self.animator.sprite_name = sprite_name
        director = self.animator.bubble_director
        if state == "bubble":
            self.animator._set_visual_state("idle")
            self.bubble_sequence += 1
            director.pick = ("speak", DEMO_BUBBLE_TEXT,
                             "demo:%d" % self.bubble_sequence)
        else:
            self.animator._set_visual_state(state)  # seeds the working ticker too
            director.pick = None

    def handle_buttons(self):
        if (badge.pressed(BUTTON_A) or badge.pressed(BUTTON_B) or badge.pressed(BUTTON_C)
                or badge.pressed(BUTTON_UP) or badge.pressed(BUTTON_DOWN)):
            self.finished = True
            return True
        return False

    def draw(self, P, stats_payload):
        import screen_registry
        import screens_live

        step = self._step()
        if step[0] == "screen":
            for screen_id, _, draw_function in screen_registry.PORTED_SCREENS:
                if screen_id == step[1]:
                    draw_function(P, stats_payload)
                    return
            return
        # the real AVATAR screen, drawn against the demo animator
        live_animator = avatar_animation.animator
        avatar_animation.animator = self.animator
        try:
            screens_live.draw_avatar(P, stats_payload)
        finally:
            avatar_animation.animator = live_animator

    def animate(self, P):
        if badge.ticks - self.step_started_ticks >= self._step()[-1]:
            self.step_index = (self.step_index + 1) % len(DEMO_SEQUENCE)
            self.step_started_ticks = badge.ticks
            self._apply_step()
            return "full"  # navigation redraws the whole screen (bezel included)
        if self._step()[0] == "avatar":
            return self.animator.update(P)
        return False


# ---- the contextual-B registry (navigation reads these) ---------------------

B_FLOWS = {
    "options_display": DisplayEditFlow,
    "options_screens": ScreensEditFlow,
    "options_palettes": PalettePreviewFlow,
    "options_avatar": AvatarPreviewFlow,
    "trophies": screens_trophies.TrophyExplainFlow,
}

# footer bezel label over the physical B button while NOT in a flow
B_HINTS = {
    "options_display": "EDIT",
    "options_screens": "EDIT",
    "options_palettes": "PREVIEW",
    "options_avatar": "PREVIEW",
    "trophies": "EXPLAIN",
}
