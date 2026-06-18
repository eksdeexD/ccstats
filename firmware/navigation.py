# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# Two-axis navigation over the screen registry: UP/DOWN moves between
# categories (wraps; entering a category resets to its first screen), A/C
# cycles the screens inside the category (wraps). B is reserved (future
# screen-collapsing toggles). Only ported screens are navigable — no
# placeholders. Small pixel arrows over the footer mirror the A/C buttons.

import time

import badgeware  # noqa: F401 -- drawing + badge/button globals

import avatar_animation
import avatar_frames
import battery_gauge
import content_pack
import feeds
import screen_registry
import screens_options
import screens_tokens
import settings
import wifi_signal
from pico_draw import PicoDraw
import screen_shared
from screen_shared import BATTERY_BLINK_MILLISECONDS, FOOTER_Y, SCREEN_WIDTH
from type_scale import get_active_scale

# Feed refreshes run on feeds.FeedScheduler's warm keep-alive connection: a
# steady-state GET is ~75-215 ms — shorter than most button presses — so it
# only waits for a tiny input-quiet gap. A reconnect (~1.8 s TLS handshake,
# after a server idle-close or a network error) is the one fetch that would
# still eat presses, so it waits for a long quiet window instead.
WARM_FETCH_QUIET_MILLISECONDS = 300
HANDSHAKE_QUIET_MILLISECONDS = 1200
# the protective low-battery cutoff shows its notice for this long before it
# powers off, so the warning is seen and USB can still abort it (user call)
POWER_OFF_NOTICE_SECONDS = 30


def feed_clock_text(stats_payload):
    # the footer clock is the feed's generated_at HH:MM (server-local time)
    generated_at = (stats_payload.get("meta") or {}).get("generated_at", "")
    return generated_at[11:16] if len(generated_at) >= 16 else "--:--"


class Navigation:
    def __init__(self, theme, stats_payload):
        self.painter = PicoDraw(theme, get_active_scale())
        self.categories = screen_registry.categories_with_screens()
        self.category_index = 0
        self.screen_index = 0
        self.stats_payload = stats_payload
        self.scheduler = feeds.FeedScheduler(feeds.connection)
        self.scheduler.start_cadences_now()  # boot just fetched everything
        if "content_pack" in stats_payload:  # boot fetch found a server pack
            content_pack.apply(stats_payload["content_pack"])
        self.last_tick_ticks = badge.ticks
        self.last_button_ticks = 0
        self.last_sprite_cycle_ticks = badge.ticks  # avatar auto-cycle timer
        self.edit_flow = None  # active contextual-B flow (screens_options.B_FLOWS)
        self.backlight_dimmed = None  # None forces the first update_backlight apply
        self._last_battery_blink_phase = None  # tracks the 1 Hz critical-blink frame
        # last footer values actually painted — so the change-gated footer refresh
        # repaints the WiFi/battery glyphs when they move without a full redraw
        self._footer_wifi_drawn = None
        self._footer_battery_drawn = None
        self._footer_charging_drawn = False
        self.painter.clock_text = feed_clock_text(stats_payload)
        saved_sprite = settings.get("sprite_name")
        if saved_sprite in avatar_frames.SPRITE_ORDER:  # stale names fall back to the default
            avatar_animation.animator.sprite_name = saved_sprite
        self._show_screen(settings.get("boot_screen"))  # no-op for unknown/hidden ids

    def current_screens(self):
        _, screens_in_category = self.categories[self.category_index]
        return screens_in_category

    def current_screen_id(self):
        screen_id, _ = self.current_screens()[self.screen_index]
        return screen_id

    def _projects_more_available(self):
        # PROJECTS B = MORE only when there is a second page to show.
        return (
            self.current_screen_id() == "projects"
            and len(self.stats_payload.get("projects") or [])
            > screens_tokens.PROJECTS_PER_PAGE
        )

    def tick_if_due(self):
        """Run the current screen's periodic behaviour (e.g. the WORDS book
        rotation); returns True when it fired and the screen needs a redraw."""
        tick_entry = screen_registry.SCREEN_TICKS.get(self.current_screen_id())
        if not tick_entry:
            return False
        interval_milliseconds, tick_function = tick_entry
        if badge.ticks - self.last_tick_ticks < interval_milliseconds:
            return False
        self.last_tick_ticks = badge.ticks
        if tick_function:  # None = pure repaint (e.g. ticking countdowns)
            tick_function()
        return True

    def handle_buttons(self):
        """Apply pending button presses; returns True if navigation changed."""
        if self.edit_flow:
            # an edit/preview flow owns every button until its confirming B
            changed = self.edit_flow.handle_buttons()
            if self.edit_flow.finished:
                on_finish = getattr(self.edit_flow, "on_finish", None)
                if on_finish:
                    on_finish()
                self.edit_flow = None
                self.backlight_dimmed = None  # editors preview undimmed — re-evaluate
                changed = True
            if changed:
                self.last_button_ticks = badge.ticks
            return changed
        changed = False
        category_count = len(self.categories)
        if badge.pressed(BUTTON_UP):
            self.category_index = (self.category_index - 1) % category_count
            self.screen_index = 0  # entering a category resets to its first screen
            screens_tokens.set_projects_page(0)  # leaving PROJECTS rewinds its window
            changed = True
        if badge.pressed(BUTTON_DOWN):
            self.category_index = (self.category_index + 1) % category_count
            self.screen_index = 0
            screens_tokens.set_projects_page(0)
            changed = True
        screen_count = len(self.current_screens())
        if badge.pressed(BUTTON_A):
            self.screen_index = (self.screen_index - 1) % screen_count
            screens_tokens.set_projects_page(0)
            changed = True
        if badge.pressed(BUTTON_C):
            self.screen_index = (self.screen_index + 1) % screen_count
            screens_tokens.set_projects_page(0)
            changed = True
        if badge.pressed(BUTTON_B):
            if self.current_screen_id() == "avatar" and self.scheduler.on_battery:
                # the M4 battery design: live channel off on battery, B here
                # flips it (and the avatar animates again while it is on)
                self.scheduler.live_status_on_battery = (
                    not self.scheduler.live_status_on_battery
                )
                changed = True
            elif self._projects_more_available():
                # PROJECTS: B = MORE — slide the 4-up window, last page flush to
                # the end, then wrap to the start (old /view gridB paging).
                count = len(self.stats_payload.get("projects") or [])
                max_start = max(0, count - screens_tokens.PROJECTS_PER_PAGE)
                page = screens_tokens.projects_page()
                if page >= max_start:
                    page = 0
                else:
                    page = min(page + screens_tokens.PROJECTS_PER_PAGE, max_start)
                screens_tokens.set_projects_page(page)
                changed = True
            else:
                flow_class = screens_options.B_FLOWS.get(self.current_screen_id())
                if flow_class:
                    self.edit_flow = flow_class(self)
                    changed = True
        if changed:
            self.last_button_ticks = badge.ticks
        return changed

    def refresh_feeds_if_due(self):
        """At most one feed fetch per call (feeds.FeedScheduler cadences);
        returns True when the VISIBLE screen draws the changed feed.

        Warm keep-alive GETs run behind a tiny input-quiet gap; a reconnect
        handshake waits for a long quiet window so it never lands
        mid-navigation. Failures keep the previous payload on screen.
        """
        self.scheduler.on_battery = (
            not badge.usb_connected()
            and not settings.get("battery_saver_off")
        )
        if self.scheduler.due_feed() is None:
            return False
        required_quiet = (
            HANDSHAKE_QUIET_MILLISECONDS
            if self.scheduler.needs_handshake()
            else WARM_FETCH_QUIET_MILLISECONDS
        )
        if badge.ticks - self.last_button_ticks < required_quiet:
            return False  # user is navigating — defer the fetch
        self.stats_payload, changed_feed_key = self.scheduler.fetch_due(self.stats_payload)
        if changed_feed_key is None:
            return False
        if changed_feed_key == "content_pack":
            content_pack.apply(self.stats_payload["content_pack"])
        if changed_feed_key == "stats":
            self.painter.clock_text = feed_clock_text(self.stats_payload)
            return True  # the primary payload feeds every screen
        dependent_screens = screen_registry.FEED_SCREEN_DEPENDENCIES.get(changed_feed_key, ())
        return self.current_screen_id() in dependent_screens

    def update_backlight(self):
        """Battery dimming (DIM ON BATTERY, default on): battery drops the
        panel to the dimmest usable level, USB restores the user setting.
        Applied on STATE CHANGES only, so the brightness editor's live
        preview is never fought mid-edit."""
        dimmed = settings.get("dim_on_battery") and not badge.usb_connected()
        if dimmed == self.backlight_dimmed:
            return
        self.backlight_dimmed = dimmed
        import main

        main.apply_brightness(settings.get("brightness"), dimmed=dimmed)

    def auto_cycle_sprite_if_due(self):
        """Advance the avatar sequentially through the roster every
        avatar_cycle_minutes (0 = off; set by the CYCLE AVATARS preview
        entry). The advanced sprite IS persisted (user call 2026-06-12:
        a reboot resumes from whichever avatar was last on stage) — at the
        5-minute minimum interval that is ~300 small writes/day, well within
        what the wear-levelled flash shrugs off."""
        interval_minutes = settings.get("avatar_cycle_minutes")
        if not interval_minutes:
            return False
        if badge.ticks - self.last_sprite_cycle_ticks < interval_minutes * 60000:
            return False
        self.last_sprite_cycle_ticks = badge.ticks
        animator = avatar_animation.animator
        order = avatar_frames.SPRITE_ORDER
        index = order.index(animator.sprite_name) if animator.sprite_name in order else -1
        animator.sprite_name = order[(index + 1) % len(order)]
        settings.update("sprite_name", animator.sprite_name)
        return self.current_screen_id() == "avatar" and self.edit_flow is None

    def update_avatar(self):
        """Run the avatar's live state machine (every pass, even off-screen,
        so working-spell timing stays truthful); returns True when a state
        edge needs the visible AVATAR screen fully repainted (chrome label)."""
        animator = avatar_animation.animator
        # static frame only while the battery live channel is off — the B
        # toggle revives both the data and the animation together
        animator.on_battery = (
            self.scheduler.on_battery and not self.scheduler.live_status_on_battery
        )
        animator.connection_online = not self.scheduler.is_offline
        animator.update_state(self.stats_payload)
        if animator.jump_to_avatar:
            # a celebration fired — auto-show the AVATAR screen (web parity:
            # "if not on the avatar screen when it fires we auto-jump there")
            animator.jump_to_avatar = False
            animator.needs_full_redraw = False
            self._show_screen("avatar")
            return True
        if animator.needs_full_redraw:
            animator.needs_full_redraw = False
            return self.current_screen_id() == "avatar"
        return False

    def _show_screen(self, target_screen_id):
        self.edit_flow = None  # leaving the screen abandons its flow
        screens_tokens.set_projects_page(0)  # arrive on any screen at page 0
        for category_index, (_, screens_in_category) in enumerate(self.categories):
            for screen_index, (screen_id, _) in enumerate(screens_in_category):
                if screen_id == target_screen_id:
                    self.category_index = category_index
                    self.screen_index = screen_index
                    return

    def draw(self):
        screen.antialias = image.OFF  # hard pixel edges, like the binarized canvas
        # a preview flow draws through its OWN painter (candidate theme) —
        # the bezel overlays below must use the same one or their pens clash
        painter = self.painter
        self.painter.connection_online = not self.scheduler.is_offline
        self._set_battery_painter(self.painter)
        if self.edit_flow:
            painter = getattr(self.edit_flow, "painter", None) or self.painter
            painter.clock_text = self.painter.clock_text
            painter.connection_online = self.painter.connection_online
            self._set_battery_painter(painter)
            self.edit_flow.draw(painter, self.stats_payload)
        else:
            _, draw_function = self.current_screens()[self.screen_index]
            draw_function(painter, self.stats_payload)
        # footer bezel: A/C pixel arrows + the contextual-B label (the flow's
        # while one is active, otherwise the screen's hint that B does something).
        # A full-bleed flow (the ABOUT photo) draws edge to edge — no chrome over
        # the picture; any button exits it back to the DISPLAY list.
        if self.edit_flow and getattr(self.edit_flow, "suppress_footer", False):
            return
        arrow_y = FOOTER_Y + 3
        painter.tri(round(SCREEN_WIDTH * 0.189) - 2, arrow_y, "l", painter.palette.text)
        painter.tri(round(SCREEN_WIDTH * 0.809) - 2, arrow_y, "r", painter.palette.text)
        if self.edit_flow:
            b_label = self.edit_flow.footer_label
        elif self.current_screen_id() == "avatar" and self.scheduler.on_battery:
            b_label = "LIVE:ON" if self.scheduler.live_status_on_battery else "LIVE:OFF"
        elif self._projects_more_available():
            b_label = "MORE"
        else:
            b_label = screens_options.B_HINTS.get(self.current_screen_id())
        if b_label:
            painter.text(b_label, 160, 231, painter.palette.text, "tag",
                         letter_spacing=1, align="c")
        self._last_battery_blink_phase = badge.ticks // BATTERY_BLINK_MILLISECONDS

    def _charging_active(self):
        """Whether the charging sweep should show: genuinely charging AND not
        yet full. The charger keeps reporting "charging" even at a full 4.22 V
        cell (is_charging() never clears for us), so we drop the sweep once the
        smoothed voltage says full and let the static level bars stand in."""
        return badge.is_charging() and not battery_gauge.charged_full()

    def _set_battery_painter(self, painter):
        painter.wifi_bars = wifi_signal.bars()
        painter.wifi_indicator_on = settings.get("wifi_indicator")
        painter.battery_cells = battery_gauge.cells()
        painter.battery_critical = battery_gauge.critical()
        painter.battery_charging = self._charging_active()

    def _footer_wifi_value(self):
        # None when the indicator is off, so its (still-sampling) RSSI can't drive
        # a pointless footer repaint while nothing is shown
        return wifi_signal.bars() if settings.get("wifi_indicator") else None

    def note_footer_painted(self):
        """Record the WiFi/battery values a full redraw just rendered, so the
        change-gated footer refresh below doesn't immediately re-fire."""
        self._footer_wifi_drawn = self._footer_wifi_value()
        self._footer_battery_drawn = battery_gauge.cells()
        self._footer_charging_drawn = self._charging_active()

    def refresh_footer_if_changed(self):
        """Repaint just the footer WiFi + battery icons the moment their cached
        values change. Both sample on a ~15 s cadence, so this repaints at most
        about once / 15 s and ONLY when a value actually moved — a stationary
        badge still sits still. It fills the gap left by the rare full redraw on
        a save-mode static screen, where the footer would otherwise lag the live
        signal / level by a whole feed-poll interval (~15 min on battery).
        Returns True when it drew (the caller then runs display.update())."""
        if self.edit_flow:
            return False  # a flow owns the whole screen; its own animate() repaints
        if (self._footer_wifi_value() == self._footer_wifi_drawn
                and battery_gauge.cells() == self._footer_battery_drawn
                and self._charging_active() == self._footer_charging_drawn):
            return False
        self._set_battery_painter(self.painter)
        screen_shared.draw_wifi_icon(self.painter)
        screen_shared.draw_battery_icon(self.painter)
        self.note_footer_painted()
        return True

    def animate_battery_if_due(self):
        """Repaint just the footer battery rect at 1 Hz when it needs to
        animate: the charging fill sweep (1->2->3->4->1), or the critical
        single-bar blink. The blink runs on battery EVEN with the saver on
        (user call 2026-06-17) — a near-empty cell is exactly when the warning
        matters most, so the extra repaints are worth it. Full-bleed flows never
        animate. Returns True when it drew (the caller then runs display.update())."""
        if self.edit_flow:
            return False  # a flow owns the screen; its own animate() repaints
        animate = self._charging_active() or battery_gauge.critical()
        if not animate:
            return False
        phase = badge.ticks // BATTERY_BLINK_MILLISECONDS
        if phase == self._last_battery_blink_phase:
            return False  # still inside the current animation second
        self._last_battery_blink_phase = phase
        self._set_battery_painter(self.painter)
        screen_shared.draw_battery_icon(self.painter)
        return True

    def power_off_low_battery(self):
        """Protective cutoff: at the cutoff voltage on battery, show a notice
        with a 30 s countdown, then power the badge OFF (badge.sleep ->
        powman_off) so the Li-ion cell is never drained toward its damage zone.
        Plugging in USB during the countdown aborts the power-off (the cell is
        charging again). Once off it wakes on a button press, and charges while
        off (user call 2026-06-14)."""
        C = self.painter.palette
        for remaining in range(POWER_OFF_NOTICE_SECONDS, 0, -1):
            if badge.usb_connected():
                return  # plugged in mid-countdown — abort, let it charge
            self.painter.clear(C.background)
            self.painter.text("LOW BATTERY", 160, 92, C.accent_primary,
                              "screen_title", align="c")
            self.painter.text("POWERING OFF IN %ds" % remaining, 160, 132, C.text,
                              "tag", letter_spacing=1, align="c")
            display.update()
            time.sleep(1)
        badge.sleep()  # powman_off(); wakes on a button press, charges while off

def start(theme, stats_payload):
    # Input-first loop instead of badgeware's run(): that loop polls buttons
    # once per FRAME, and a full vector redraw takes long enough that quick
    # presses land between polls and vanish. Here buttons are polled every
    # ~10ms and the screen only redraws when navigation or data changed (the
    # screens are static in between — also the right shape for battery).
    navigation = Navigation(theme, stats_payload)
    battery_gauge.prime()  # seed the fuel gauge before the first paint
    wifi_signal.prime()  # seed the footer signal glyph too
    navigation.draw()
    display.update()
    navigation.note_footer_painted()  # seed the footer change-tracking
    while True:
        badge.poll()
        battery_gauge.sample_if_due()
        wifi_signal.sample_if_due()
        on_battery = not badge.usb_connected()
        battery_gauge.note_power(not on_battery)  # USB clears the critical latch
        if battery_gauge.should_power_off(on_battery):
            navigation.power_off_low_battery()  # draws a notice, then never returns
        navigation.update_backlight()
        navigation_changed = navigation.handle_buttons()
        data_changed = navigation.refresh_feeds_if_due()
        tick_fired = navigation.tick_if_due()
        avatar_changed = navigation.update_avatar()
        cycle_fired = navigation.auto_cycle_sprite_if_due()
        if navigation_changed or data_changed or tick_fired or avatar_changed or cycle_fired:
            navigation.draw()
            display.update()
            navigation.note_footer_painted()  # footer is fresh; reset the change-tracking
        elif navigation.edit_flow and getattr(navigation.edit_flow, "animate", None):
            # a live flow animates its own partial regions; "full" asks for a
            # whole-screen pass instead (demo mode changing its step)
            flow_drew = navigation.edit_flow.animate(navigation.painter)
            if flow_drew == "full":
                navigation.draw()
                display.update()
            elif flow_drew:
                display.update()
        elif navigation.current_screen_id() == "avatar":
            # partial-region animation frames (stage band / word band only)
            if avatar_animation.animator.update(navigation.painter):
                display.update()
        if navigation.animate_battery_if_due():
            # 1 Hz footer-only repaint: charging sweep or critical-battery blink
            display.update()
        elif navigation.refresh_footer_if_changed():
            # footer-only repaint when the WiFi bars / battery level move without
            # a full redraw (the common case on a static save-mode screen)
            display.update()
        time.sleep_ms(10)
