# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# Avatar speech-bubble behaviours (M4b steps 2+3) — ports the "delight"
# layer of view/screens.js: HUMAN BOTTLENECK quips (escalating tiers + book
# brags), near-limit lines, streak-danger nags and the rare idle quote,
# arbitrated by priority (web pickBubble order). Message banks live in
# content_pack (server-syncable); the badge picks which line locally.
#
# Streak danger runs CLIENT-SIDE like the web, but on the SERVER's local
# clock: meta.generated_at in claude-stats.json carries the server-local
# date+hour (at most one stats cadence stale), so no on-device timezone
# tables are needed — same condition, same data, no extra server field.

import random
import time

import content_pack
from screens_breakdown import BOOKS

# --- HUMAN BOTTLENECK: tier timing (banks in content_pack) ---
BOOK_TAUNT_CHANCE_PERCENT = 40
BOTTLENECK_ROTATE_MILLISECONDS = 20000
BOTTLENECK_TIER_1_MILLISECONDS = 3 * 60 * 1000
BOTTLENECK_TIER_2_MILLISECONDS = 6 * 60 * 1000

# book titles sized to the tier: gentle = short book, dramatic = epic
BOOKS_BY_TIER = (
    tuple(title for title, _, words in BOOKS if words < 70000),
    tuple(title for title, _, words in BOOKS if 70000 <= words < 150000),
    tuple(title for title, _, words in BOOKS if words >= 150000),
)

# --- near-limit thresholds + cadence ---
LIMIT_SESSION_PERCENT = 80   # = the full-sweat threshold (web STRESS_FULL)
LIMIT_WEEKLY_PERCENT = 90
LIMIT_ON_MILLISECONDS = 12000
LIMIT_OFF_MILLISECONDS = 108000  # ~12 s shown every ~2 min while a limit is near

# --- streak danger: nag while today's activity would break the streak ---
STREAK_ON_MILLISECONDS = 10000
STREAK_OFF_EARLY_MILLISECONDS = 285000  # 16:00-20:00 — roughly every 5 min
STREAK_OFF_LATE_MILLISECONDS = 105000   # 20:00-midnight — tighter, every ~2 min
STREAK_EARLY_HOUR = 16
STREAK_LATE_HOUR = 20

# --- idle quote: a rare flavour line, idle-only, lowest priority ---
QUOTE_MINIMUM_MILLISECONDS = 2 * 3600 * 1000
QUOTE_MAXIMUM_MILLISECONDS = 5 * 3600 * 1000
QUOTE_SHOW_MILLISECONDS = 30000


def _pick_no_repeat(bank, last_index):
    if len(bank) < 2:
        return 0
    index = random.randrange(len(bank))
    while index == last_index:
        index = random.randrange(len(bank))
    return index


def _quote_interval():
    return QUOTE_MINIMUM_MILLISECONDS + random.randrange(
        QUOTE_MAXIMUM_MILLISECONDS - QUOTE_MINIMUM_MILLISECONDS)


def _server_local_clock(stats_payload):
    """(date 'YYYY-MM-DD', hour int) from the stats feed's generated_at —
    the server's local wall clock, at most one stats cadence stale."""
    generated_at = ((stats_payload or {}).get("meta") or {}).get("generated_at", "")
    if len(generated_at) < 13:
        return None, None
    try:
        return generated_at[:10], int(generated_at[11:13])
    except ValueError:
        return None, None


class BubbleDirector:
    """Advances the behaviour cadences and arbitrates which bubble (if any)
    shows. update() returns (variant, text, key) or None; a changed key is
    the caller's cue to repaint. Pure state — no drawing."""

    def __init__(self):
        now = time.ticks_ms()
        self.bottleneck_was_waiting = False
        self.bottleneck_entered_ticks = 0
        self.bottleneck_rotate_deadline = None
        self.bottleneck_text = ""
        self.bottleneck_key = None
        self.bottleneck_sequence = 0
        self.last_quip_index = [-1, -1, -1]
        self.last_taunt_index = -1
        self.last_book_index = [-1, -1, -1]
        self.limit_was_active = False
        self.limit_phase = "off"
        self.limit_deadline = None
        self.limit_text = ""
        self.limit_key = None
        self.limit_sequence = 0
        self.last_limit_index = -1
        self.streak_was_active = False
        self.streak_phase = "off"
        self.streak_deadline = None
        self.streak_text = ""
        self.streak_key = None
        self.streak_sequence = 0
        self.last_streak_index = -1
        self.quote_due_ticks = time.ticks_add(now, _quote_interval())
        self.quote_pending = False
        self.quote_until_ticks = None
        self.quote_text = ""
        self.quote_key = None
        self.quote_sequence = 0
        self.last_quote_index = -1

    # --- HUMAN BOTTLENECK cadence ---

    def _advance_bottleneck(self, now, is_waiting):
        if is_waiting and not self.bottleneck_was_waiting:
            self.bottleneck_entered_ticks = now  # just entered — quip promptly
            self.bottleneck_rotate_deadline = now
        self.bottleneck_was_waiting = is_waiting
        if not is_waiting:
            self.bottleneck_key = None
            return
        if time.ticks_diff(now, self.bottleneck_rotate_deadline) < 0:
            return
        elapsed = time.ticks_diff(now, self.bottleneck_entered_ticks)
        tier = (0 if elapsed < BOTTLENECK_TIER_1_MILLISECONDS
                else 1 if elapsed < BOTTLENECK_TIER_2_MILLISECONDS else 2)
        if random.randrange(100) < BOOK_TAUNT_CHANCE_PERCENT and BOOKS_BY_TIER[tier]:
            taunts = content_pack.bank("book_taunts")
            taunt_index = _pick_no_repeat(taunts, self.last_taunt_index)
            self.last_taunt_index = taunt_index
            book_index = _pick_no_repeat(BOOKS_BY_TIER[tier], self.last_book_index[tier])
            self.last_book_index[tier] = book_index
            self.bottleneck_text = taunts[taunt_index].replace(
                "{book}", BOOKS_BY_TIER[tier][book_index])
        else:
            tier_bank = content_pack.bank("bottleneck_tiers")[tier]
            quip_index = _pick_no_repeat(tier_bank, self.last_quip_index[tier])
            self.last_quip_index[tier] = quip_index
            self.bottleneck_text = tier_bank[quip_index]
        self.bottleneck_sequence += 1
        self.bottleneck_key = "bottle:%d" % self.bottleneck_sequence
        self.bottleneck_rotate_deadline = time.ticks_add(now, BOTTLENECK_ROTATE_MILLISECONDS)

    # --- near-limit cadence ---

    def _limit_alert(self, stats_payload):
        """{pct, window} worth warning about, or None — the louder one wins."""
        limits = (stats_payload or {}).get("limits") or {}
        session = (limits.get("session") or {}).get("utilization") or 0
        weekly = (limits.get("weekly") or {}).get("utilization") or 0
        session_hit = session >= LIMIT_SESSION_PERCENT
        weekly_hit = weekly >= LIMIT_WEEKLY_PERCENT
        if session_hit and weekly_hit:
            return (session, "session") if session >= weekly else (weekly, "weekly")
        if session_hit:
            return (session, "session")
        if weekly_hit:
            return (weekly, "weekly")
        return None

    def _advance_limit(self, now, stats_payload):
        alert = self._limit_alert(stats_payload)
        if alert and not self.limit_was_active:
            self.limit_phase = "off"  # just crossed the threshold — show promptly
            self.limit_deadline = now
        self.limit_was_active = bool(alert)
        if not alert:
            self.limit_phase = "off"
            return
        if time.ticks_diff(now, self.limit_deadline) < 0:
            return
        if self.limit_phase == "off":
            percent, window = alert
            lines = content_pack.bank("limit_lines")
            line_index = _pick_no_repeat(lines, self.last_limit_index)
            self.last_limit_index = line_index
            self.limit_text = (lines[line_index]
                               .replace("{pct}", str(round(percent)))
                               .replace("{window}", window))
            self.limit_sequence += 1
            self.limit_key = "limit:%d" % self.limit_sequence
            self.limit_phase = "on"
            self.limit_deadline = time.ticks_add(now, LIMIT_ON_MILLISECONDS)
        else:
            self.limit_phase = "off"
            self.limit_deadline = time.ticks_add(now, LIMIT_OFF_MILLISECONDS)

    # --- streak danger cadence ---

    def _streak_condition(self, stats_payload):
        """current_streak alive + no activity on the server-local 'today' +
        late enough in the (server-local) day to start nagging."""
        totals = (stats_payload or {}).get("totals") or {}
        if not (totals.get("current_streak") or 0) > 0:
            return False
        today, hour = _server_local_clock(stats_payload)
        if today is None or hour < STREAK_EARLY_HOUR:
            return False
        last_active_date = None
        for day in reversed((stats_payload or {}).get("daily_activity") or []):
            if (day.get("prompts") or 0) > 0:
                last_active_date = day.get("date")
                break
        return not (last_active_date and last_active_date >= today)

    def _advance_streak(self, now, stats_payload):
        active = self._streak_condition(stats_payload)
        if active and not self.streak_was_active:
            self.streak_phase = "off"  # just entered the window — nag promptly
            self.streak_deadline = now
        self.streak_was_active = active
        if not active:
            self.streak_phase = "off"
            return
        if time.ticks_diff(now, self.streak_deadline) < 0:
            return
        if self.streak_phase == "off":
            lines = content_pack.bank("streak_lines")
            line_index = _pick_no_repeat(lines, self.last_streak_index)
            self.last_streak_index = line_index
            self.streak_text = lines[line_index]
            self.streak_sequence += 1
            self.streak_key = "streak:%d" % self.streak_sequence
            self.streak_phase = "on"
            self.streak_deadline = time.ticks_add(now, STREAK_ON_MILLISECONDS)
        else:
            _, hour = _server_local_clock(stats_payload)
            off_milliseconds = (STREAK_OFF_LATE_MILLISECONDS
                                if (hour or 0) >= STREAK_LATE_HOUR
                                else STREAK_OFF_EARLY_MILLISECONDS)
            self.streak_phase = "off"
            self.streak_deadline = time.ticks_add(now, off_milliseconds)

    # --- idle quote ---

    def _advance_quote(self, now, visual_state):
        # only reached when no higher-priority bubble returned (web gate:
        # idle AND nothing else showing)
        if time.ticks_diff(now, self.quote_due_ticks) >= 0:
            self.quote_pending = True  # interval elapsed — wants to fire
        if self.quote_pending and visual_state == "idle":
            quotes = content_pack.bank("quotes")
            quote_index = _pick_no_repeat(quotes, self.last_quote_index)
            self.last_quote_index = quote_index
            self.quote_text = '"%s"' % quotes[quote_index].get("q", "")
            self.quote_sequence += 1
            self.quote_key = "quote:%d" % self.quote_sequence
            self.quote_until_ticks = time.ticks_add(now, QUOTE_SHOW_MILLISECONDS)
            self.quote_pending = False
            self.quote_due_ticks = time.ticks_add(now, _quote_interval())

    # --- the arbiter (web pickBubble priorities; celebrations land with the
    #     server's directive fields — see SERVER-PROMPT-M4B.md) ---

    def update(self, visual_state, stats_payload):
        now = time.ticks_ms()
        self._advance_bottleneck(now, visual_state == "waiting")
        self._advance_limit(now, stats_payload)
        self._advance_streak(now, stats_payload)
        if visual_state == "waiting" and self.bottleneck_key:
            return ("speak", self.bottleneck_text, self.bottleneck_key)
        if self.limit_phase == "on" and visual_state != "waiting":
            return ("speak", self.limit_text, self.limit_key)
        if self.streak_phase == "on" and visual_state == "idle":
            return ("think", self.streak_text, self.streak_key)
        self._advance_quote(now, visual_state)
        if (self.quote_until_ticks is not None
                and time.ticks_diff(now, self.quote_until_ticks) < 0
                and visual_state == "idle"):
            return ("speak", self.quote_text, self.quote_key)
        return None
