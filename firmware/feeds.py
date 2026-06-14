# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# Feed fetching — every JSON feed the badge consumes, over one persistent
# verified-HTTPS connection (http_client.PersistentConnection: the ~1.8 s TLS
# handshake happens once; each poll is then a ~75-215 ms keep-alive GET).
# claude-stats.json is required (schema-guarded); the rest attach to the
# payload under their key, best-effort like the web client.
#
# Steady-state refresh is FeedScheduler: per-feed cadences (power-aware — on
# battery everything slows down and the live channel is off by default), at
# most ONE fetch per call so the caller's input loop stays responsive, and a
# doubling backoff after network errors so a dead network is not hammered
# with 1.8 s handshake attempts every pass. Boot/smoke use fetch_everything().

import gc
import json
import time

import http_client
import secrets  # device /secrets.py or the mounted firmware/secrets.py (gitignored)

EXPECTED_SCHEMA_VERSION = 1

# (payload key, feed file, USB cadence ms, battery cadence ms).
# live_status on battery is OFF by default (None) — the briefing's power
# model; the B-on-AVATAR toggle (M4b) flips live_status_on_battery instead.
# Battery numbers are first guesses pending real runtime measurements
# (battery HTTPS-vs-HTTP comparison).
FEED_TABLE = (
    ("stats", "claude-stats.json", 5 * 60 * 1000, 15 * 60 * 1000),
    ("limits", "claude-limits.json", 60 * 1000, 5 * 60 * 1000),
    ("competition", "competition.json", 2 * 60 * 1000, 10 * 60 * 1000),
    ("live_status", "live-status.json", 2 * 1000, None),
    # avatar message banks — optional server endpoint (SERVER-PROMPT-M4B.md);
    # 404/403 just keeps the baked defaults in content_pack.py
    ("content_pack", "content-pack.json", 24 * 3600 * 1000, 24 * 3600 * 1000),
)

OPTIONAL_FEED_KEYS = tuple(key for key, _, _, _ in FEED_TABLE if key != "stats")

ERROR_BACKOFF_START_MILLISECONDS = 5 * 1000
ERROR_BACKOFF_MAXIMUM_MILLISECONDS = 60 * 1000

# the one connection to the stats server, shared by boot fetch + scheduler
connection = http_client.PersistentConnection(secrets.STATS_BASE_URL)


def _feed_path(feed_name):
    return "/" + feed_name + "?token=" + secrets.STATS_TOKEN


def _guard_schema(stats_payload):
    schema_version = stats_payload["meta"]["schema_version"]
    if schema_version != EXPECTED_SCHEMA_VERSION:
        raise http_client.HttpError(
            "feed schema v%s, firmware expects v%d" % (schema_version, EXPECTED_SCHEMA_VERSION)
        )


def fetch_primary_stats():
    """claude-stats.json — required, schema-guarded. Raises on any failure."""
    gc.collect()
    status_code, stats_payload, _ = connection.get_json(_feed_path("claude-stats.json"))
    if status_code != 200:
        raise http_client.HttpError("feed returned HTTP %d (check token/server)" % status_code)
    _guard_schema(stats_payload)
    return stats_payload


def fetch_optional_feed(feed_name):
    """One optional feed; returns its payload or None (never raises)."""
    try:
        gc.collect()
        status_code, payload, _ = connection.get_json(_feed_path(feed_name))
        if status_code == 200:
            return payload
        print(feed_name, "returned HTTP", status_code, "- skipping")
    except (OSError, ValueError, http_client.HttpError) as error:
        print(feed_name, "unavailable:", error)
    return None


def fetch_everything():
    """All feeds in one blocking pass (boot + the dev smoke test) — one
    handshake + four keep-alive GETs on the shared connection."""
    stats_payload = fetch_primary_stats()
    for feed_key, feed_name, _, _ in FEED_TABLE:
        if feed_key == "stats":
            continue
        optional_payload = fetch_optional_feed(feed_name)
        if optional_payload is not None:
            stats_payload[feed_key] = optional_payload
    return stats_payload


class FeedScheduler:
    """Per-feed cadence refresh on the shared persistent connection.

    fetch_due() runs at most ONE fetch per call and never raises; the caller
    polls it from the input loop. needs_handshake() tells the caller when the
    next fetch would pay the ~1.8 s reconnect, so it can defer that to an
    input-quiet window (a warm GET is shorter than a button press and needs
    no such care).
    """

    def __init__(self, feed_connection):
        self.connection = feed_connection
        self.on_battery = False  # caller refreshes from badge.usb_connected()
        self.live_status_on_battery = False  # B-on-AVATAR toggle lands with M4b
        self._last_attempt_ticks = {}
        self._last_body = {}
        self._consecutive_errors = 0
        self._backoff_started_ticks = None

    @property
    def is_offline(self):
        """True while fetches are failing (cleared by the next success) —
        the footer dot and the avatar's OFFLINE word read this."""
        return self._consecutive_errors > 0

    def start_cadences_now(self):
        """Call right after a boot fetch_everything(): every cadence counts
        from now instead of refetching everything immediately."""
        now = time.ticks_ms()
        for feed_key, _, _, _ in FEED_TABLE:
            self._last_attempt_ticks[feed_key] = now

    def _cadence_milliseconds(self, feed_key, usb_cadence, battery_cadence):
        if not self.on_battery:
            return usb_cadence
        if feed_key == "live_status":
            return usb_cadence if self.live_status_on_battery else None
        return battery_cadence

    def _in_error_backoff(self, now):
        if self._backoff_started_ticks is None:
            return False
        backoff = min(
            ERROR_BACKOFF_START_MILLISECONDS * (2 ** (self._consecutive_errors - 1)),
            ERROR_BACKOFF_MAXIMUM_MILLISECONDS,
        )
        return time.ticks_diff(now, self._backoff_started_ticks) < backoff

    def due_feed(self):
        """(feed_key, feed_name) of the next due feed, or None."""
        now = time.ticks_ms()
        if self._in_error_backoff(now):
            return None
        for feed_key, feed_name, usb_cadence, battery_cadence in FEED_TABLE:
            cadence = self._cadence_milliseconds(feed_key, usb_cadence, battery_cadence)
            if cadence is None:
                continue
            last_attempt = self._last_attempt_ticks.get(feed_key)
            if last_attempt is None or time.ticks_diff(now, last_attempt) >= cadence:
                return feed_key, feed_name
        return None

    def needs_handshake(self):
        return not self.connection.is_connected

    def fetch_due(self, stats_payload):
        """Fetch the next due feed, at most one. Never raises.

        Returns (stats_payload, changed_feed_key) — changed_feed_key is None
        when nothing was due, nothing changed (byte-identical body), or the
        fetch failed (previous data stays on screen).
        """
        due = self.due_feed()
        if due is None:
            return stats_payload, None
        feed_key, feed_name = due
        self._last_attempt_ticks[feed_key] = time.ticks_ms()

        try:
            gc.collect()
            status_code, body = self.connection.get(_feed_path(feed_name))
        except (OSError, http_client.HttpError) as error:
            self._consecutive_errors += 1
            self._backoff_started_ticks = time.ticks_ms()
            print(feed_key, "refresh failed (backoff #%d):" % self._consecutive_errors, error)
            return stats_payload, None
        self._consecutive_errors = 0
        self._backoff_started_ticks = None

        if status_code != 200:
            print(feed_key, "returned HTTP", status_code, "- keeping previous")
            return stats_payload, None
        if body == self._last_body.get(feed_key):
            return stats_payload, None  # unchanged — skip the parse and redraw
        try:
            payload = json.loads(body)
            if feed_key == "stats":
                _guard_schema(payload)
        except (ValueError, KeyError, http_client.HttpError) as error:
            print(feed_key, "rejected:", error)
            return stats_payload, None
        self._last_body[feed_key] = body

        if feed_key == "stats":
            # carry the optional feeds over until their fresh copies land
            for optional_key in OPTIONAL_FEED_KEYS:
                if optional_key in stats_payload:
                    payload[optional_key] = stats_payload[optional_key]
            return payload, "stats"
        stats_payload[feed_key] = payload
        return stats_payload, feed_key
