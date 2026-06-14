# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# The living GLOOM mascot (M4b step 1) — ports the avatar behaviour of
# view/screens.js to the badge: the live state machine with the synthesized
# "done" flourish, the float/squash bob (pre-squashed frames from
# tools/build-avatar-frames.py), blink, thinking dots, the hop, the sweat
# bead, and the working word ticker with the text-scramble sweep.
#
# Drawing is PARTIAL-REGION: the stage band (sprite + shadow + dots + sweat)
# and the word band redraw independently at animation cadence (~50 ms and
# ~18 ms incl. display.update on device), so the input loop stays responsive
# and the rest of the screen is never repainted per frame. Full-screen
# redraws (chrome status changes) go through navigation as usual.

import math
import random
import time

import badgeware  # noqa: F401 -- drawing globals

import avatar_bubbles
import avatar_frames
import content_pack
from screens_trophies import draw_glyph

# ---- the avatar screen's fixed geometry ----
# User-tuned 2026-06-12 (diverges from screens.js drawAvatar on purpose):
# sprite sits 15 px lower for breathing room under the today-line, and the
# word line sits ~5 px above the footer band (footer starts at y=227).
SPRITE_X = 104  # round((320 - 112) / 2)
SPRITE_Y = 86  # nudged +5 (was 81) to free room for the two AVATAR info lines
# the today-line's ink ends at ~y=52; the band starts just under it so the
# thinking dots (and VOLT's antenna at the hop peak, ink up to y=55) fit
STAGE_TOP = 53
STAGE_BOTTOM = 204  # exclusive; the word band is further down
WORD_TOP = 208
WORD_BOTTOM = 226  # the footer band starts at 227
WORD_BASELINE_Y = 214
WORD_LEFT_X = 24  # working ticker text, LEFT-aligned after the spark icon

SHADOW_CENTER_X = 160
SHADOW_Y = 190  # nudged +5 with SPRITE_Y so the sprite keeps its ground shadow
SHADOW_BASE_WIDTH = 74

# the battery-sleep "zZz" — (x, y, size) for three glyphs ascending up-right,
# placed beside the head (user-tuned 2026-06-13). Drawn once (static), so no
# per-frame cost.
SLEEP_Z_GLYPHS = ((186, 110, 7), (201, 97, 10), (219, 84, 13))

# ---- speech bubble (pixel panel top-right; the avatar slides left and
# slightly down to free the stage for it — av-stage.has-bubble) ----
# Left-anchored to the slid-aside avatar (user feedback 2026-06-12): the slid
# sprite's ink right edge sits at ~x=103, the bubble starts ~10 px after it
# and uses everything up to the right margin — wider than the web's 150.
BUBBLE_RIGHT_X = 312
BUBBLE_WIDTH = 198
BUBBLE_TOP_Y = 64
BUBBLE_PADDING_X = 9
# Settled 2026-06-12: Silkscreen 8. Aurora 9 + Deer Diary 11 stay legit
# candidates for the M5 font-preset system (bubble font joins the presets).
BUBBLE_FONT = ("silk", 8)
BUBBLE_FONT_CYCLE_MILLISECONDS = 5000  # debug: cycle candidate fonts for review
SLIDE_MILLISECONDS = 1100
SLIDE_OFFSET_X = -94  # web: margin-left -56 -> -150
SLIDE_OFFSET_Y = 8    # web slides 28 down; our lower sprite only has room for 8

# the breathing spark icon left of the working word (av-word-star: 4-point
# sparkle, scale 0.25-1.0 over 1.6 s; cross bars in avatar colour, corner
# dots + centre in avatar-light). Cell art on a 16-grid, drawn in a 14 px box.
STAR_CENTER_X = 13
STAR_CENTER_Y = 217
STAR_BOX = 14
STAR_CYCLE_MILLISECONDS = 1600
STAR_BARS = ((7, 0, 2, 16), (0, 7, 16, 2))
STAR_LIGHTS = ((3, 3, 2, 2), (11, 3, 2, 2), (3, 11, 2, 2), (11, 11, 2, 2), (6, 6, 4, 4))

# ~14.3 fps stage redraw. The fps math: a stage frame costs ~47 ms on-device
# (draw ~30 + display.update ~17), so ~16-17 fps is the ceiling before the
# loop has no headroom left for button polls; the generated frame data gives
# a new unique pose every 62.5 ms (32 frames / 2 s float cycle), so cadences
# below ~60 ms would just repeat poses. 70 ms keeps ~2 polls between frames.
STAGE_FRAME_MILLISECONDS = 70

# ---- state machine (applyLive in view/screens.js) ----
MIN_WORK_MILLISECONDS = 6000   # a working spell shorter than this is a blip, not a task
DONE_MILLISECONDS = 7000       # the celebrate-then-settle flourish window

# ---- blink (avBlink: 4.2 s cycle, shut for a moment near the end) ----
BLINK_CYCLE_MILLISECONDS = 4200
BLINK_SHUT_MILLISECONDS = 200

# ---- thinking dots (avThink: 0.66 s bounce, 0.12 s stagger, working only) ----
DOT_CYCLE_MILLISECONDS = 660
DOT_STAGGER_MILLISECONDS = 120
DOT_SIZE = 6
DOT_GAP = 5
DOT_BASE_Y = 58  # just below the today-line; clears VOLT's antenna at the float apex
DOT_LIFT = 5

# ---- sweat bead (avSweat: 2.6 s sit-drip-vanish cycle; fixed blues) ----
# The bead is GLUED to the head: its anchor (neutral-box px, on the dome's
# right slope) is mapped through the SAME bottom-centre squash transform as
# the sprite frame, plus the frame's translate_y — so it rides the bob. The
# web version anchors to the stage instead and visibly detaches; deliberate
# improvement (user feedback 2026-06-12). The drip offset stays screen-space.
SWEAT_CYCLE_MILLISECONDS = 2600  # anchor is per-sprite (avatar_frames.SPRITES)
STRESS_MILD_PERCENT = 60  # session utilization thresholds (web STRESS_MILD/FULL)
# bead pixel art (6x8 grid at x2 = 12x16 px), colours fixed so it always
# reads as sweat regardless of palette (same as the web's inline fills)
SWEAT_OUTLINE = ((2, 0, 2, 1), (1, 1, 1, 2), (4, 1, 1, 2), (0, 3, 1, 3),
                 (5, 3, 1, 3), (1, 6, 1, 1), (4, 6, 1, 1), (2, 7, 2, 1))
SWEAT_BODY = ((2, 1, 2, 6), (1, 3, 4, 3))
SWEAT_SHINE = ((2, 2, 1, 2),)
# SPARKLY's amber EMBER (the web's .swt-ember swap, stress_marker "ember"):
# a tiny shed spark on the same 6x8 grid at x2, same drip cycle and anchor as
# the bead — pens from the palette (avatar_light + text), so it themes
EMBER_ARMS = ((2, 1, 2, 6), (0, 3, 6, 2))
EMBER_CORE = ((2, 3, 2, 2),)

# ---- done sparkles (avTwinkle: 1 s staggered green twinkles) ----
SPARKLE_CYCLE_MILLISECONDS = 1000
SPARKLE_OFFSETS = ((-16, 18), (122, 6), (-10, 72), (120, 60))  # relative to the sprite box

# ---- celebrations (the server's `celebrate` directive on live-status.json:
# {id, kind, label, detail, expires_at} — see SERVER-PROMPT-M4B.md). A
# celebration OWNS the stage + bubble (web priority 1): hop + happy eyes +
# confetti + the celebration bubble; sweat and the bubble arbiter pause.
# Each id celebrates ONCE (the server keeps the field present for the whole
# window and rotates ids every ~6 s when several fire). ----
CELEBRATION_FALLBACK_MILLISECONDS = 60 * 1000   # unparsable expires_at
CELEBRATION_MAXIMUM_MILLISECONDS = 3 * 60 * 1000  # the web's ~3 min window
CELEBRATED_IDS_REMEMBERED = 16
CONFETTI_PIECES = 14
CONFETTI_FALL_MILLISECONDS = (2200, 3800)  # per-piece random duration range
CONFETTI_COLOR_PENS = ("accent_primary", "accent_secondary", "status",
                       "avatar_color", "text")

# ---- word ticker (the working words + scramble sweep, view/screens.js) ----
TICKER_HOLD_MILLISECONDS = 2000
TICKER_STEP_MILLISECONDS = 60
TICKER_POST_MILLISECONDS = 200
TICKER_SUFFIX = "..."  # the words live in content_pack ("working_words")

STATIC_WORDS = {"idle": "STANDBY", "waiting": "HUMAN BOTTLENECK",
                "done": "DONE!", "standby": "STANDBY"}

_sweat_pens = None  # built lazily (color.rgb needs the badgeware globals live)


def _get_sweat_pens():
    global _sweat_pens
    if _sweat_pens is None:
        _sweat_pens = (color.rgb(0x15, 0x45, 0x5F), color.rgb(0xBF, 0xEA, 0xFF),
                       color.rgb(0xFF, 0xFF, 0xFF))
    return _sweat_pens


def _ease_in_out(t):
    return (1 - math.cos(math.pi * t)) / 2


def _speed_factor():
    # the ANIMATION SPEED setting scales every motion DURATION (the web's
    # --spd-num knob): 2.0X halves the float/hop/ticker/dot cycles
    import settings

    speed = settings.get("animation_speed")
    return speed if speed and speed > 0 else 1.0


def _scaled(duration_milliseconds):
    return max(1, round(duration_milliseconds / _speed_factor()))


def _pick_working_word(avoid_index=None):
    words = content_pack.bank("working_words")
    index = random.randrange(len(words))
    while index == avoid_index and len(words) > 1:
        index = random.randrange(len(words))
    return index


def _parse_utc_seconds(iso_text):
    """Epoch seconds (device epoch, RTC is UTC) from 'YYYY-MM-DDTHH:MM:SSZ';
    None when malformed."""
    try:
        return time.mktime((int(iso_text[0:4]), int(iso_text[5:7]), int(iso_text[8:10]),
                            int(iso_text[11:13]), int(iso_text[14:16]), int(iso_text[17:19]),
                            0, 0))
    except (ValueError, IndexError, TypeError, OverflowError):
        return None


class AvatarAnimator:
    def __init__(self):
        now = time.ticks_ms()
        self.on_battery = False
        self._was_on_battery = False    # battery-edge detector (force a clean repaint)
        self.connection_online = True   # navigation mirrors the scheduler's error state
        self._was_online = True
        self.stress_override = None     # debug hook (web Tweaks parity): None=auto, 0=off, 1=forced
        self.sprite_name = "gloom"      # the M5 OPTIONS picker writes this
        self.visual_state = "standby"   # working | idle | waiting | done | standby
        self.previous_feed_status = None
        self.work_started_ticks = now
        self.done_until_ticks = None
        self.needs_full_redraw = False  # navigation consumes this (chrome changed)
        self.stats_payload = None       # latest payload, kept by update_state
        self.blink_anchor_ticks = now
        self.last_stage_ticks = 0
        # celebrations (server directive; owns the stage + bubble while active)
        self.celebration = None         # {"id","kind","text","until_ticks","started_ticks"}
        self.celebrated_identifiers = []
        self.confetti = ()              # per-piece (x, duration, delay, pen_name, size)
        self.jump_to_avatar = False     # navigation consumes: auto-show the AVATAR screen
        # speech bubble + the slide-aside choreography
        self.bubble_director = avatar_bubbles.BubbleDirector()
        self.bubble = None          # (variant, text, key) currently shown
        self.bubble_font = None  # debug override; None = the preset's speech_bubble role
        self.bubble_font_cycle = None  # debug: ((font_key, px), ...) cycled 5 s each
        self.slide_progress = 0.0   # 0 = centred, 1 = slid aside for a bubble
        self.last_slide_ticks = now
        # ticker
        self.word_index = 0
        self.ticker_phase = "hold"      # hold | scramble | post
        self.ticker_deadline = now
        self.scramble_from = ""
        self.scramble_to = ""
        self.scramble_cursor = 0

    # ---- state machine: runs EVERY navigation pass (cheap), even off-screen ----

    def update_state(self, stats_payload):
        self.stats_payload = stats_payload
        now = time.ticks_ms()
        self._update_celebration(now)
        status = ((stats_payload or {}).get("live_status") or {}).get("status")
        if status == "no_processes":
            status = "idle"
        if status not in ("working", "idle", "waiting"):
            status = None
        if self.on_battery:
            status = None  # live channel is off on battery — the data is stale
        if not self.connection_online:
            status = None  # fetches are failing — whatever we hold is stale
        if self.connection_online != self._was_online:
            # the OFFLINE word + chrome label flip even without a state edge
            self._was_online = self.connection_online
            self.needs_full_redraw = True
        if self.on_battery != self._was_on_battery:
            # battery edge: force a clean repaint so the avatar settles into its
            # neutral resting frame at once (not frozen mid-float), and so waking
            # on USB / LIVE:ON repaints immediately (user request 2026-06-13)
            self._was_on_battery = self.on_battery
            self.needs_full_redraw = True
            if self.on_battery:
                self.visual_state = "standby"  # neutral; chrome label reads STANDBY
                self.previous_feed_status = None
                self.done_until_ticks = None
                self.celebration = None        # end any in-flight flourish cleanly

        # a pending "done" flourish settles to idle when its window ends
        if self.done_until_ticks is not None and time.ticks_diff(now, self.done_until_ticks) >= 0:
            self.done_until_ticks = None
            if self.visual_state == "done":
                self._set_visual_state("idle" if status == "idle" else (status or "standby"))

        if status == self.previous_feed_status:
            return
        previous = self.previous_feed_status
        self.previous_feed_status = status
        self.done_until_ticks = None  # any new transition cancels a pending done
        if status == "working":
            self.work_started_ticks = now
        if (previous == "working" and status == "idle"
                and time.ticks_diff(now, self.work_started_ticks) >= MIN_WORK_MILLISECONDS):
            self._set_visual_state("done")  # genuine completion — celebrate, then settle
            self.done_until_ticks = time.ticks_add(now, DONE_MILLISECONDS)
        else:
            self._set_visual_state(status or "standby")

    def _set_visual_state(self, new_state):
        if new_state == self.visual_state:
            return
        if new_state == "working":
            self.word_index = _pick_working_word()
            self.ticker_phase = "hold"
            self.ticker_deadline = time.ticks_add(time.ticks_ms(), _scaled(TICKER_HOLD_MILLISECONDS))
        self.visual_state = new_state
        self.needs_full_redraw = True  # the chrome status label changed too

    def chrome_label(self):
        if not self.connection_online:
            return "OFFLINE"
        return self.visual_state.upper()

    # ---- celebrations (server directive consumer) ----

    def _update_celebration(self, now):
        if self.celebration and time.ticks_diff(now, self.celebration["until_ticks"]) >= 0:
            self.celebration = None  # window over — back to normal life
            self.needs_full_redraw = True
        directive = ((self.stats_payload or {}).get("live_status") or {}).get("celebrate")
        if not directive:
            return
        identifier = directive.get("id")
        if not identifier or identifier in self.celebrated_identifiers:
            return
        # remember the id even when it turns out expired — celebrate ONCE
        self.celebrated_identifiers.append(identifier)
        if len(self.celebrated_identifiers) > CELEBRATED_IDS_REMEMBERED:
            self.celebrated_identifiers.pop(0)
        window = CELEBRATION_FALLBACK_MILLISECONDS
        expires_seconds = _parse_utc_seconds(directive.get("expires_at") or "")
        if expires_seconds is not None:
            remaining = (expires_seconds - time.time()) * 1000
            if remaining <= 0:
                return  # arrived already expired (boot into a stale window)
            window = min(remaining, CELEBRATION_MAXIMUM_MILLISECONDS)
        lines = content_pack.bank(
            "trophy_lines" if directive.get("kind") == "trophy" else "record_lines")
        text = lines[random.randrange(len(lines))]
        label = directive.get("label") or ""
        detail = directive.get("detail") or ""
        if label or detail:
            text += "\n" + (label + " " + detail).strip()
        self.celebration = {
            "id": identifier,
            "kind": directive.get("kind") or "record",
            "text": text,
            "until_ticks": time.ticks_add(now, round(window)),
            "started_ticks": now,
        }
        self.confetti = tuple(
            (8 + random.randrange(304),
             CONFETTI_FALL_MILLISECONDS[0] + random.randrange(
                 CONFETTI_FALL_MILLISECONDS[1] - CONFETTI_FALL_MILLISECONDS[0]),
             random.randrange(2600),
             CONFETTI_COLOR_PENS[random.randrange(len(CONFETTI_COLOR_PENS))],
             3 + random.randrange(2))
            for _ in range(CONFETTI_PIECES)
        )
        self.jump_to_avatar = True  # never miss a celebration (web parity)
        self.needs_full_redraw = True

    def word_pen(self, C):
        state = self.visual_state
        if state == "working":
            return C.avatar_color
        if state == "waiting":
            return C.accent_secondary  # the web's gold
        if state == "done":
            return C.status            # the web's green
        return C.text_dark             # idle / standby (cream-d)

    # ---- per-pass animation update; navigation calls this when AVATAR is visible ----

    def update(self, P):
        """Advance + draw due animation regions. Returns True if it drew
        (navigation then runs one display.update())."""
        if self.on_battery:
            return False  # static frame on battery — full draw already painted it
        now = time.ticks_ms()
        drew = False
        if self._advance_ticker(now):
            self.draw_word(P)
            drew = True
        if time.ticks_diff(now, self.last_stage_ticks) >= STAGE_FRAME_MILLISECONDS:
            self.last_stage_ticks = now
            self._advance_bubble(now)
            self.draw_stage(P)
            if self.visual_state == "working" and not drew:
                self._draw_star(P, clear=True)  # breathe the spark on stage cadence
            drew = True
        return drew

    # ---- speech bubble arbitration + the slide-aside ----

    def _advance_bubble(self, now):
        if self.celebration:
            # priority 1: a celebration owns the bubble; the arbiter pauses
            pick = ("speak", self.celebration["text"], "celebrate:" + self.celebration["id"])
        else:
            pick = self.bubble_director.update(self.visual_state, self.stats_payload)
        new_key = pick[2] if pick else None
        current_key = self.bubble[2] if self.bubble else None
        if new_key != current_key:
            self.bubble = pick
        # the slide eases toward its target on every stage frame
        elapsed = time.ticks_diff(now, self.last_slide_ticks)
        self.last_slide_ticks = now
        step = min(elapsed, 4 * STAGE_FRAME_MILLISECONDS) / SLIDE_MILLISECONDS
        if self.bubble:
            self.slide_progress = min(1.0, self.slide_progress + step)
        else:
            self.slide_progress = max(0.0, self.slide_progress - step)

    def _slide_offsets(self):
        eased = 1 - (1 - self.slide_progress) ** 2  # ~ the web's ease-out slide
        return round(SLIDE_OFFSET_X * eased), round(SLIDE_OFFSET_Y * eased)

    # ---- the word ticker ----

    def _ticker_word(self):
        words = content_pack.bank("working_words")
        return words[self.word_index % len(words)] + TICKER_SUFFIX

    def _advance_ticker(self, now):
        """Scramble state machine; returns True when the word band changed."""
        if self.visual_state != "working":
            return False
        if time.ticks_diff(now, self.ticker_deadline) < 0:
            return False
        if self.ticker_phase == "hold":
            self.scramble_from = self._ticker_word()
            self.word_index = _pick_working_word(avoid_index=self.word_index)
            self.scramble_to = self._ticker_word()
            self.scramble_cursor = 1
            self.ticker_phase = "scramble"
            self.ticker_deadline = time.ticks_add(now, _scaled(TICKER_STEP_MILLISECONDS))
            return True
        if self.ticker_phase == "scramble":
            self.scramble_cursor += 1
            # the sweep ends the INSTANT the new word is complete — the web
            # keeps the cursor on to eat a longer old word's tail, which reads
            # as a lingering cursor (user call 2026-06-12: snap it away)
            if self.scramble_cursor >= len(self.scramble_to):
                self.ticker_phase = "post"
                self.ticker_deadline = time.ticks_add(now, _scaled(TICKER_POST_MILLISECONDS))
            else:
                self.ticker_deadline = time.ticks_add(now, _scaled(TICKER_STEP_MILLISECONDS))
            return True
        # post-hold over — settle on the new word and start the next hold
        self.ticker_phase = "hold"
        self.ticker_deadline = time.ticks_add(now, _scaled(TICKER_HOLD_MILLISECONDS))
        return False

    def _draw_star(self, P, clear=False):
        """The breathing 4-point spark left of the working word — edges scaled
        around the centre like the squash frames (avStarPulse 0.25-1.0)."""
        C = P.palette
        if clear:
            P.rect(STAR_CENTER_X - STAR_BOX // 2 - 1, WORD_TOP,
                   STAR_BOX + 2, WORD_BOTTOM - WORD_TOP, C.background)
        t = (time.ticks_ms() % STAR_CYCLE_MILLISECONDS) / STAR_CYCLE_MILLISECONDS
        breath = _ease_in_out(t * 2) if t < 0.5 else _ease_in_out((1 - t) * 2)
        factor = (0.25 + 0.75 * breath) * STAR_BOX / 16  # cell grid -> px box
        for rects, pen in ((STAR_BARS, C.avatar_color), (STAR_LIGHTS, C.avatar_light)):
            for x, y, w, h in rects:
                x0 = round(STAR_CENTER_X + (x - 8) * factor)
                x1 = round(STAR_CENTER_X + (x + w - 8) * factor)
                y0 = round(STAR_CENTER_Y + (y - 8) * factor)
                y1 = round(STAR_CENTER_Y + (y + h - 8) * factor)
                if x1 > x0 and y1 > y0:
                    P.rect(x0, y0, x1 - x0, y1 - y0, pen)

    def draw_word(self, P):
        """The word band: the working ticker (spark icon + left-aligned word
        with the scramble sweep) or the centred static state word."""
        C = P.palette
        P.rect(0, WORD_TOP, 320, WORD_BOTTOM - WORD_TOP, C.background)
        if self.on_battery:
            # resting: the live channel and the animation are off on battery, so
            # say so plainly instead of a stale state word (user request
            # 2026-06-13); the sprite holds its neutral eyes-open frame
            P.text("AVATAR SLEEPS ON BATTERY", 160, WORD_BASELINE_Y, C.text_dark,
                   "row_label", letter_spacing=1, align="c")
            return
        if not self.connection_online:
            # fetches are failing — say so instead of a stale state word
            # (user idea 2026-06-13); accent 1 is the boot screen's alert pen
            P.text("OFFLINE", 160, WORD_BASELINE_Y, C.accent_primary,
                   "row_label", letter_spacing=2, align="c")
            return
        pen = self.word_pen(C)
        if self.visual_state != "working":
            P.text(STATIC_WORDS.get(self.visual_state, "STANDBY"), 160, WORD_BASELINE_Y,
                   pen, "row_label", letter_spacing=2, align="c")
            return
        self._draw_star(P)
        if self.ticker_phase == "scramble":
            # locked new word · '_' flicker · block cursor · the old word's tail
            cursor = self.scramble_cursor
            locked = self.scramble_to[:min(cursor, len(self.scramble_to))]
            flicker = "_" if cursor < len(self.scramble_to) else ""
            x = WORD_LEFT_X
            x += P.text(locked + flicker, x, WORD_BASELINE_Y, pen, "row_label", letter_spacing=2) + 2
            P.rect(x, WORD_BASELINE_Y, 7, 9, pen)  # the literal block cursor
            x += 9
            tail = self.scramble_from[cursor + 1:]
            if tail:
                P.text(tail, x, WORD_BASELINE_Y, pen, "row_label", letter_spacing=2)
        else:
            P.text(self._ticker_word(), WORD_LEFT_X, WORD_BASELINE_Y,
                   pen, "row_label", letter_spacing=2)

    # ---- the stage (sprite + shadow + dots + sweat + sparkles) ----

    def _sprite(self):
        try:
            return avatar_frames.sprite(self.sprite_name)
        except (KeyError, ImportError):
            return avatar_frames.sprite("gloom")

    def _current_frame(self, now):
        sprite = self._sprite()
        if self.visual_state == "done" or self.celebration:
            cycle = _scaled(avatar_frames.HOP_CYCLE_MILLISECONDS)
            frames = sprite["hop"]
        else:
            cycle = _scaled(avatar_frames.FLOAT_CYCLE_WORKING_MILLISECONDS
                            if self.visual_state == "working"
                            else avatar_frames.FLOAT_CYCLE_MILLISECONDS)
            frames = sprite["float"]
        phase = (now % cycle) / cycle
        return frames[int(phase * len(frames)) % len(frames)], phase

    def _blink_shut(self, now):
        if self.visual_state == "done" or self.celebration:
            return False  # happy eyes never blink
        position = (now - self.blink_anchor_ticks) % BLINK_CYCLE_MILLISECONDS
        return position >= BLINK_CYCLE_MILLISECONDS - BLINK_SHUT_MILLISECONDS

    def _stress_level(self):
        if self.stress_override is not None:
            return self.stress_override
        limits = ((self.stats_payload or {}).get("limits") or {})
        utilization = (limits.get("session") or {}).get("utilization")
        return 1 if (utilization is not None and utilization >= STRESS_MILD_PERCENT) else 0

    def _draw_eye_slits(self, P, frame, origin_x, origin_y):
        # squash the WHOLE eye group (whites + pupils together) toward its
        # vertical centre, like the web's scaleY(.12) on .av-eyes — shared by
        # the blink and the battery-sleep (closed eyes) states. Per-rect
        # squashing leaves multi-rect eyes (DIMPLE's notches) as stray lines,
        # and whites-only squashing loses ZIGGY's dark almonds.
        C = P.palette
        whites = frame[avatar_frames.LAYER_EYES_WHITE]
        pupils = frame[avatar_frames.LAYER_EYES_PUPIL]
        group = whites + pupils
        if not group:
            return
        group_top = min(y for x, y, w, h in group)
        group_bottom = max(y + h for x, y, w, h in group)
        group_center = (group_top + group_bottom) / 2

        def draw_slits(rects, pen):
            for x, y, w, h in rects:
                slit_top = round(group_center + (y - group_center) * 0.12)
                slit_bottom = round(group_center + (y + h - group_center) * 0.12)
                if slit_bottom > slit_top:
                    P.rect(origin_x + x, origin_y + slit_top, w, slit_bottom - slit_top, pen)

        if self._sprite().get("eyes_white_on_top"):
            draw_slits(pupils, C.background)
            draw_slits(whites, C.eye_white)
        else:
            draw_slits(whites, C.eye_white)
            draw_slits(pupils, C.background)

    def _draw_sleep_z(self, P, x, y, size, pen):
        # a cartoon "Z" from rects (like the dots/sparkles): two bars + a stepped
        # diagonal from the top-right corner down to the bottom-left
        thickness = max(1, size // 4)
        P.rect(x, y, size, thickness, pen)                      # top bar
        P.rect(x, y + size - thickness, size, thickness, pen)   # bottom bar
        span = max(1, size - 1)
        for row in range(size):
            diagonal_x = x + round((size - thickness) * (1 - row / span))
            P.rect(diagonal_x, y + row, thickness, 1, pen)      # the diagonal

    def draw_stage(self, P, static=False, sleeping=False):
        C = P.palette
        now = time.ticks_ms()
        static = static or sleeping  # the battery-sleep state never animates
        P.rect(0, STAGE_TOP, 320, STAGE_BOTTOM - STAGE_TOP, C.background)

        if static:
            frame, phase = self._sprite()["float"][0], 0.0
            slide_x = slide_y = 0
        else:
            frame, phase = self._current_frame(now)
            slide_x, slide_y = self._slide_offsets()  # aside while a bubble shows
        translate_y = frame[0]

        # ground shadow (avShadow: narrows as the sprite rises, same eased phase)
        eased = _ease_in_out(phase * 2) if phase < 0.5 else _ease_in_out((1 - phase) * 2)
        shadow_width = round(SHADOW_BASE_WIDTH * (1.15 + (0.72 - 1.15) * eased))
        inset = max(2, round(shadow_width * 0.14))
        shadow_center = SHADOW_CENTER_X + slide_x
        shadow_y = SHADOW_Y + slide_y
        P.rect(shadow_center - shadow_width // 2 + inset, shadow_y, shadow_width - 2 * inset, 1, C.edge)
        P.rect(shadow_center - shadow_width // 2, shadow_y + 1, shadow_width, 3, C.edge)
        P.rect(shadow_center - shadow_width // 2 + inset, shadow_y + 4, shadow_width - 2 * inset, 1, C.edge)

        # the sprite (pre-squashed frame; rects are already in device px)
        origin_x = SPRITE_X + slide_x
        origin_y = SPRITE_Y + translate_y + slide_y
        draw_glyph(P, frame[avatar_frames.LAYER_FILL], origin_x, origin_y, 1, C.avatar_color)
        draw_glyph(P, frame[avatar_frames.LAYER_SHADE], origin_x, origin_y, 1, C.avatar_dark)
        draw_glyph(P, frame[avatar_frames.LAYER_HI], origin_x, origin_y, 1, C.avatar_light)
        draw_glyph(P, frame[avatar_frames.LAYER_DARK], origin_x, origin_y, 1, C.avatar_dark)
        draw_glyph(P, frame[avatar_frames.LAYER_MOUTH], origin_x, origin_y, 1, C.background)
        if (self.visual_state == "done" or self.celebration) and not static:
            # default cuts the happy rects out of the fill; BLIP's happy_pen
            # lights its smiley cream instead (web .av-happy fill:var(--cream))
            happy_pen = getattr(C, self._sprite().get("happy_pen", "background"))
            draw_glyph(P, frame[avatar_frames.LAYER_HAPPY], origin_x, origin_y, 1, happy_pen)
        elif sleeping or (self._blink_shut(now) and not static):
            # closed eyes — shared by the blink and the battery-sleep state
            self._draw_eye_slits(P, frame, origin_x, origin_y)
        else:
            if self._sprite().get("eyes_white_on_top"):
                # ZIGGY: cream glints sit ON the dark almonds (source z-order)
                draw_glyph(P, frame[avatar_frames.LAYER_EYES_PUPIL], origin_x, origin_y, 1, C.background)
                draw_glyph(P, frame[avatar_frames.LAYER_EYES_WHITE], origin_x, origin_y, 1, C.eye_white)
            else:
                draw_glyph(P, frame[avatar_frames.LAYER_EYES_WHITE], origin_x, origin_y, 1, C.eye_white)
                draw_glyph(P, frame[avatar_frames.LAYER_EYES_PUPIL], origin_x, origin_y, 1, C.background)

        if sleeping:
            # the cartoon "zZz" drifting up-right of the head — three glyphs of
            # ascending size, drawn ONCE (static state, no per-frame cost)
            for z_x, z_y, z_size in SLEEP_Z_GLYPHS:
                self._draw_sleep_z(P, z_x, z_y, z_size, C.text)

        if static:
            return

        # thinking dots (working only): three staggered bouncing dots above the head
        if self.visual_state == "working":
            dot_cycle = _scaled(DOT_CYCLE_MILLISECONDS)
            for dot in range(3):
                t = ((now - dot * DOT_STAGGER_MILLISECONDS) % dot_cycle) / dot_cycle
                lift = _ease_in_out(t * 2) if t < 0.5 else _ease_in_out((1 - t) * 2)
                dot_x = 160 + slide_x - (3 * DOT_SIZE + 2 * DOT_GAP) // 2 + dot * (DOT_SIZE + DOT_GAP)
                pen = C.avatar_light if lift > 0.5 else C.avatar_dark
                P.rect(dot_x, DOT_BASE_Y + slide_y - round(DOT_LIFT * lift), DOT_SIZE, DOT_SIZE, pen)

        # twinkles while celebrating done (green by default; SPARKLY's
        # sparkle_pen makes them amber — web .av-spark i background override)
        if self.visual_state == "done":
            sparkle_pen = getattr(C, self._sprite().get("sparkle_pen", "status"))
            for index, (offset_x, offset_y) in enumerate(SPARKLE_OFFSETS):
                t = ((now - index * 250) % SPARKLE_CYCLE_MILLISECONDS) / SPARKLE_CYCLE_MILLISECONDS
                grow = _ease_in_out(t * 2) if t < 0.5 else _ease_in_out((1 - t) * 2)
                size = round(6 * grow)
                if size >= 2:
                    center_x = origin_x + offset_x + 3
                    center_y = SPRITE_Y + slide_y + offset_y + 3
                    P.rect(center_x - size // 2, center_y - 1, size, 2, sparkle_pen)
                    P.rect(center_x - 1, center_y - size // 2, 2, size, sparkle_pen)

        # confetti rains over the whole stage while celebrating (under the
        # bubble, over the sprite — web .av-confetti z-order)
        if self.celebration:
            elapsed = time.ticks_diff(now, self.celebration["started_ticks"])
            fall_span = SHADOW_Y + 8 - STAGE_TOP
            for piece_x, duration, delay, pen_name, size in self.confetti:
                t = ((elapsed - delay) % duration) / duration
                piece_y = STAGE_TOP - 6 + t * fall_span
                # "rotation": the piece flips proportions as it tumbles
                if int(t * 8) % 2:
                    width, height = size, max(2, size - 1)
                else:
                    width, height = max(2, size - 1), size
                # CLIP to the stage band (the web's overflow:hidden): pixels
                # above STAGE_TOP are never cleared by the per-frame redraw
                # and would linger as static ghosts under the today-line
                top = max(round(piece_y), STAGE_TOP)
                bottom = min(round(piece_y) + height, STAGE_BOTTOM)
                if bottom > top:
                    P.rect(round(piece_x), top, width, bottom - top, getattr(C, pen_name))

        # sweat bead by the head while the session limit looms (paused while
        # celebrating, like the web's applyStress)
        if self._stress_level() >= 1 and self.visual_state != "done" and not self.celebration:
            t = (now % SWEAT_CYCLE_MILLISECONDS) / SWEAT_CYCLE_MILLISECONDS
            if t < 0.58:
                drip = 0
            elif t < 0.78:
                drip = round(9 * (t - 0.58) / 0.20)
            elif t < 0.88:
                drip = 9 + round(2 * (t - 0.78) / 0.10)
            else:
                drip = None  # vanished, about to reappear
            if drip is not None:
                sprite = self._sprite()
                # per-sprite anchor mapped through the frame's squash + bob
                anchor_x, anchor_y = sprite["sweat_anchor"]
                scale_x = frame[avatar_frames.FRAME_SCALE_X] / 1000
                scale_y = frame[avatar_frames.FRAME_SCALE_Y] / 1000
                bead_x = origin_x + round(56 + (anchor_x - 56) * scale_x)
                bead_y = origin_y + round(112 + (anchor_y - 112) * scale_y) + drip
                if sprite.get("stress_marker", "sweat") == "ember":
                    # SPARKLY sheds an amber ember instead of the blue bead
                    draw_glyph(P, EMBER_ARMS, bead_x, bead_y, 2, C.avatar_light)
                    draw_glyph(P, EMBER_CORE, bead_x, bead_y, 2, C.text)
                else:
                    outline_pen, body_pen, shine_pen = _get_sweat_pens()
                    draw_glyph(P, SWEAT_BODY, bead_x, bead_y, 2, body_pen)
                    draw_glyph(P, SWEAT_OUTLINE, bead_x, bead_y, 2, outline_pen)
                    draw_glyph(P, SWEAT_SHINE, bead_x, bead_y, 2, shine_pen)

        # the speech bubble draws last — over everything on the stage
        if self.bubble:
            self._draw_bubble(P)

    def _bubble_font(self):
        if self.bubble_font_cycle:
            index = (time.ticks_ms() // BUBBLE_FONT_CYCLE_MILLISECONDS) % len(self.bubble_font_cycle)
            return self.bubble_font_cycle[index]
        if self.bubble_font:  # explicit debug override wins
            return self.bubble_font
        from type_scale import get_active_scale

        return get_active_scale().get("speech_bubble") or BUBBLE_FONT

    def _wrap_bubble_text(self, P, text, font_key, pixel_size):
        # explicit "\n" forces a break (the celebration bubble's humour line
        # over its label/detail line — the web's white-space:pre-line)
        maximum_width = BUBBLE_WIDTH - 2 * BUBBLE_PADDING_X
        lines = []
        for paragraph in text.split("\n"):
            current = ""
            for word in paragraph.split():
                candidate = (current + " " + word) if current else word
                if not current or P.exact_text_width(candidate, pixel_size, font_key=font_key) <= maximum_width:
                    current = candidate
                else:
                    lines.append(current)
                    current = word
            if current:
                lines.append(current)
        return lines

    def _draw_bubble(self, P):
        """The pixel-art bubble panel: a 2px staircase-cornered border (the
        web's 'rounded' clip — two 3px steps per corner) with a speak tail.
        Built from rect unions, so no clipping is needed."""
        C = P.palette
        variant, text, _ = self.bubble
        font_key, pixel_size = self._bubble_font()
        line_height = round(pixel_size * 1.5)  # the web's 1.5 line-height
        lines = self._wrap_bubble_text(P, text.upper(), font_key, pixel_size)  # lowercase 'i' is missing from the pixel fonts
        height = len(lines) * line_height + 16
        x = BUBBLE_RIGHT_X - BUBBLE_WIDTH
        y = BUBBLE_TOP_Y
        width = BUBBLE_WIDTH
        # border shape (edge), then the fill inset 2px with the same steps
        P.rect(x + 6, y, width - 12, height, C.edge)
        P.rect(x + 3, y + 3, width - 6, height - 6, C.edge)
        P.rect(x, y + 6, width, height - 12, C.edge)
        P.rect(x + 8, y + 2, width - 16, height - 4, C.title_bar)
        P.rect(x + 5, y + 5, width - 10, height - 10, C.title_bar)
        P.rect(x + 2, y + 8, width - 4, height - 16, C.title_bar)
        if variant == "think":
            # a trail of three shrinking puffs going down-left (thought cloud)
            for puff_x, puff_y, size in ((x + 16, y + height - 2, 8),
                                         (x + 9, y + height + 5, 5),
                                         (x + 4, y + height + 10, 3)):
                P.rect(puff_x, puff_y, size, size, C.edge)
                if size > 4:
                    P.rect(puff_x + 2, puff_y + 2, size - 4, size - 4, C.title_bar)
        else:
            # speak: one staircased pointy tail, two-tone, tip at bottom-left
            tail_x, tail_y = x + 12, y + height - 4
            for row, tail_width in enumerate((12, 9, 6, 3)):
                P.rect(tail_x, tail_y + row * 3, tail_width, 3, C.edge)
            for row_y, tail_width, row_height in ((tail_y - 2, 10, 3), (tail_y + 1, 7, 3),
                                                  (tail_y + 4, 4, 3), (tail_y + 7, 1, 1)):
                P.rect(tail_x + 2, row_y, tail_width, row_height, C.title_bar)
        # centre the text block vertically: the ink spans (lines-1) line-steps
        # plus one glyph height, not lines * line_height
        ink_height = (len(lines) - 1) * line_height + pixel_size
        text_y = y + round((height - ink_height) / 2)
        for line in lines:
            P.text(line, x + width // 2, text_y, C.text, pixel_size,
                   font_key=font_key, align="c")
            text_y += line_height


# the one animator — navigation drives it, screens_live draws through it
animator = AvatarAnimator()
