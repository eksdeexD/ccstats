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

"""
Durable HUMAN BOTTLENECK accumulator.

Records, per local clock-hour, the cumulative wall-clock seconds during which AT LEAST ONE live
Claude Code session on this box was blocked waiting on the human (an unanswered `AskUserQuestion`).
That is the "HUMAN BOTTLENECK" time the competition feed compares over 24h / 7d / 30d / all-time.

This is deliberately INDEPENDENT of the live-activity monitor (live-monitor.py): the competition
needs a stat that persists on its own, decoupled from that monitor. It does ONE thing —
detect "is anyone waiting right now" and bank the elapsed seconds — and writes a tiny SQLite DB
(`bottleneck.db`, table `bottleneck(datehour, seconds)`) that `extract.py --mode competitor` reads.

Waiting is inferred exactly like the live monitor: the final `assistant` turn of a session's
transcript has an `AskUserQuestion` tool_use with no matching `tool_result` after it. Live sessions
are found via ~/.claude/sessions/<pid>.json with a procStart liveness guard against PID reuse.

A single unanswered question is banked for at most ABANDON_CAP_SEC (30 min): a session walked away
from mid-question stops counting past that, so an abandoned window can't accumulate forever. A
new/changed question resets the budget, so a session that's actively being answered is never capped.

Runs as root (needs to read other users' 0600 transcripts) from a systemd service. Stdlib only.
"""
import argparse
import glob
import json
import os
import sqlite3
import time
from datetime import datetime
from zoneinfo import ZoneInfo

# Timezone is read per-machine from config.json (default UTC) so hour buckets line up with the
# rest of the pipeline (default UTC if config.json is absent).
_CONFIG_PATH = os.environ.get("CCSTATS_CONFIG", "/opt/claude-stats/config.json")


def _tz():
    try:
        with open(_CONFIG_PATH) as fh:
            name = (json.load(fh).get("timezone") or "UTC").strip() or "UTC"
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("UTC")


TZ = _tz()
WAIT_TOOL = "AskUserQuestion"
SESSIONS_GLOB = "/home/*/.claude/sessions/*.json"
SAMPLE_INTERVAL = 10          # seconds between waiting checks (human-scale; 10s is plenty)
ABANDON_CAP_SEC = 1800        # cap continuous wait on ONE unanswered question (30 min): a session
                              # walked away from mid-question stops banking past this; a new/changed
                              # question resets the budget, so an actively-answered session never trips it
DB_PATH = "/opt/claude-stats/bottleneck.db"


def log(msg):
    print(f"[{datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def datehour():
    return datetime.now(TZ).strftime("%Y-%m-%dT%H")


# ---------------------------- AskUserQuestion (waiting) detection -------------------------------
# Defensive cap on UNTRUSTED transcript input (.jsonl written by other local users): never read a
# multi-GB file into this monitor. ~30x the largest real transcript (~8 MB).
MAX_TRANSCRIPT_BYTES = 256 * 1024 * 1024
MAX_LINE_BYTES       = 16 * 1024 * 1024


def pending_tools(path):
    """(id, name) pairs of unanswered tool calls in the final assistant turn of a transcript."""
    tool_names, answered, last_ids = {}, set(), []
    try:
        if os.path.getsize(path) > MAX_TRANSCRIPT_BYTES:
            return []   # absurdly large transcript — treat as no pending tools rather than OOM
    except OSError:
        pass
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if len(line) > MAX_LINE_BYTES:
                continue
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            t = o.get("type")
            if t == "assistant":
                ids = []
                for b in o.get("message", {}).get("content", []):
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        tool_names[b["id"]] = b["name"]
                        ids.append(b["id"])
                if ids:
                    last_ids = ids
            elif t == "user":
                c = o.get("message", {}).get("content", [])
                if isinstance(c, list):
                    for b in c:
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            answered.add(b.get("tool_use_id"))
    return [(i, tool_names[i]) for i in last_ids if i not in answered]


_pending_cache = {}    # transcript path -> ((mtime_ns, size), pending_list)


def transcript_pending(path):
    """pending_tools(path), re-parsed only when the (append-only) file changes."""
    try:
        st = os.stat(path)
    except OSError:
        return []
    key = (st.st_mtime_ns, st.st_size)
    cached = _pending_cache.get(path)
    if cached and cached[0] == key:
        return cached[1]
    pend = pending_tools(path)
    _pending_cache[path] = (key, pend)
    return pend


def proc_starttime(pid):
    with open(f"/proc/{pid}/stat") as f:
        data = f.read()
    return data[data.rfind(")") + 2:].split()[19]      # field 22 (starttime)


_wait_state = {}   # sid -> {"sig": askuser tool_use-id tuple, "start": mono, "abandoned": bool}
                   # one entry per session currently waiting; lets a single wait be capped (ABANDON_CAP_SEC)


def anyone_waiting(now_mono, cap):
    """Live sessions blocked on an unanswered AskUserQuestion, EXCLUDING any that has been waiting on
    the SAME question for more than `cap` seconds (treated as abandoned). A new/changed question
    resets the clock, so a session that's actively being answered is never capped. State persists in
    _wait_state across calls; sessions that clear or end are pruned so a later wait starts fresh."""
    active, pending_sids = [], set()
    for reg in glob.glob(SESSIONS_GLOB):
        try:
            s = json.load(open(reg))
        except Exception:
            continue
        pid, sid, cwd = s.get("pid"), s.get("sessionId"), s.get("cwd") or ""
        if not (pid and sid and cwd):
            continue
        try:                                            # liveness + PID-reuse guard
            if proc_starttime(pid) != str(s.get("procStart")):
                continue
        except (OSError, IndexError):
            continue
        claude_dir = os.path.dirname(os.path.dirname(reg))   # /home/<user>/.claude
        tpath = f"{claude_dir}/projects/{cwd.replace('/', '-')}/{sid}.jsonl"
        try:
            pend = transcript_pending(tpath)
        except OSError:
            continue
        sig = tuple(sorted(i for i, n in pend if n == WAIT_TOOL))
        if not sig:                                     # not blocked on a question
            continue
        pending_sids.add(sid)
        st = _wait_state.get(sid)
        if st is None or st["sig"] != sig:              # new / changed question → fresh budget
            st = _wait_state[sid] = {"sig": sig, "start": now_mono, "abandoned": False}
        if now_mono - st["start"] <= cap:
            active.append(sid)
        elif not st["abandoned"]:                       # just crossed the cap → log once
            st["abandoned"] = True
            log(f"session {sid[:8]} abandoned (>{cap:.0f}s on one question) — no longer counting")
    for sid in list(_wait_state):                       # forget sessions no longer waiting
        if sid not in pending_sids:
            del _wait_state[sid]
    return active


# ----------------------------------------- storage ----------------------------------------------
def open_db(path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE IF NOT EXISTS bottleneck(datehour TEXT PRIMARY KEY, seconds REAL)")
    con.commit()
    try:
        os.chmod(path, 0o600)  # internal accumulator (not web-served) — keep it root-only
    except OSError:
        pass
    return con


def add_seconds(con, dh, secs):
    con.execute(
        "INSERT INTO bottleneck(datehour, seconds) VALUES(?, ?) "
        "ON CONFLICT(datehour) DO UPDATE SET seconds = seconds + excluded.seconds",
        (dh, secs))
    con.commit()


def main():
    ap = argparse.ArgumentParser(description="Durable HUMAN BOTTLENECK time accumulator")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--interval", type=float, default=SAMPLE_INTERVAL)
    ap.add_argument("--abandon-cap", type=float, default=ABANDON_CAP_SEC,
                    help="cap continuous wait on one unanswered question, seconds (default 1800 = 30 min)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    con = open_db(args.db)
    log(f"bottleneck monitor start | db={args.db} interval={args.interval}s "
        f"abandon_cap={args.abandon_cap:.0f}s tz={TZ} | waiting = unanswered {WAIT_TOOL}")

    prev_mono = time.monotonic()
    was_waiting = False
    while True:
        time.sleep(args.interval)
        now_mono = time.monotonic()
        elapsed = now_mono - prev_mono
        prev_mono = now_mono

        sids = anyone_waiting(now_mono, args.abandon_cap)
        # Credit the interval just elapsed if the box was the human's bottleneck across it. Using the
        # state sampled at the END of the interval; over 10s samples the edge error is negligible.
        if sids:
            add_seconds(con, datehour(), elapsed)
        if args.verbose or bool(sids) != was_waiting:
            log(f"{'WAITING' if sids else 'clear  '} sessions={len(sids)} (+{elapsed:.0f}s)"
                if sids else f"clear (sessions=0)")
        was_waiting = bool(sids)


if __name__ == "__main__":
    main()
