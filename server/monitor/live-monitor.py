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
Claude Code LIVE ACTIVITY MONITOR  —  TEST / VALIDATION ONLY.

Per Linux user, reports one of three states, written to /var/www/stats/live-status.json
every cycle (fast cadence — the badge polls this ~every 2 s; usage stats live in the separate,
slow claude-stats.json):

  • working  — a session shows NETWORK activity to the API, OR the transcript shows the model still
               owes a response (turn in progress) — see below
  • idle     — Claude is running but BOTH state signals have been quiet for IDLE_DEBOUNCE seconds
  • waiting  — a session is blocked on an unanswered AskUserQuestion ("HUMAN BOTTLENECK").
               This OVERRIDES idle, because a blocked session is itself CPU-idle.

ACTIVITY is decided by TWO state signals (working if EITHER fires):
  1. NETWORK — bytes/sec (sent+received) on the user's Claude processes' REMOTE TCP sockets, read from
               `ss -tinp` (tcp_info bytes_sent/bytes_received), summed per user. An idle Claude does
               ~0 B/s of remote socket traffic (observed max ~172); a live turn streams hundreds–100k
               B/s, set by token streaming NOT CPU speed — so one threshold travels across machines.
               Detects the START of work and active streaming.
  2. OWES-RESPONSE — the session transcript shows the turn is still in progress: the last record is a
               user prompt or a tool_result (the model owes output), or an assistant tool_use with a
               non-AskUserQuestion tool still running. This is the fix for FALSE-IDLES: during a long
               turn the model can think server-side for 15-25 s+ with NOTHING streaming, so NET (and
               io/mtime) all go quiet even though the turn isn't done; the transcript is ground truth
               that it is. Held at most TURN_CAP s past the last NET activity, so a dead/hung turn
               still decays. Detects the SILENT middle of a turn that NET alone mis-reads as idle.
DIAGNOSTIC-only (measured + shown in `signals`, but NOT in the state decision): I/O rchar+wchar bytes/s
(too noisy — idle disk blips cross any sane threshold → false-working) and transcript-mtime (never
fired uniquely). CPU% was removed earlier (idle/active CPU overlap caused false-working). Every
threshold is overridable PER MACHINE via the "live_monitor" block in config.json. To flip
idle→working a state signal must hold for ACTIVE_DEBOUNCE seconds (a 1-sample confirm); to decay
working→idle BOTH state signals must be quiet for IDLE_DEBOUNCE seconds — which is now snappy (the
owes-response signal, not a big debounce, is what covers long API latency).

"waiting" is inferred from the session transcript: a session is blocked when the last
`assistant` turn has an `AskUserQuestion` tool_use with no matching `tool_result` after it.

Stdlib only. Runs as the `claude-live-monitor` systemd service (root — needed to read other
users' 0600 transcripts; reading /proc across users needs no privilege here, no hidepid).

Permanent feature (kept 2026-06-04). Drives the badge / `/viewscreens` working/idle/waiting avatar. See
the constants and comments below for the detection model and tuning knobs.
"""
import argparse
import glob
import grp
import json
import os
import pwd
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# ----------------------------- tunables -----------------------------
# A user is "active this sample" if NET is over threshold; only after idle_debounce_s seconds of NET
# quiet does it flip to idle. DEFAULTS below; ANY can be overridden PER MACHINE via the
# "live_monitor" block in config.json (so a remote on different hardware tunes itself without forking
# this file). Every effective value is mirrored into the JSON `thresholds` block for verification.
DEFAULTS = {
    "net_bytes_per_s":   300,    # THE state signal: remote-socket bytes/s (sent+received), busiest user.
                                 # idle floor is clean (observed max ~172 B/s); a streaming turn is hundreds–100k.
    "io_bytes_per_s":    256,    # DIAGNOSTIC ONLY — measured + shown, but NOT in `active` (too noisy: idle
                                 # disk blips routinely cross 256, p90 ~444 B/s, so it caused false-working).
    "transcript_signal": True,   # DIAGNOSTIC ONLY — measured + shown, but NOT in `active` (it never fired
                                 # uniquely; whenever it fired during net-quiet, io was firing too → no value).
    "turn_signal":       True,   # STATE signal #2: "model owes a response" (transcript turn-in-progress).
                                 # Holds working across silent API latency — measured in-turn net-silent
                                 # runs reach 15-25s+ while the model thinks server-side, so net alone
                                 # false-idles mid-turn. The transcript is ground truth that the turn isn't done.
    "turn_cap_s":        300,    # safety cap: the turn signal alone holds working at most this long past the
                                 # last net activity, so a dead/hung turn still decays (real turns blip well inside).
    "idle_debounce_s":   8,      # all state signals quiet this long before working->idle (snappy "done"; the
                                 # turn signal — not a big debounce — is what covers long API latency).
    "active_debounce_s": 2,      # a state signal up this long before idle->working. Net never false-fires,
                                 # so this is just a 1-sample confirm (was 4, back when io noise needed rejecting).
    "sample_interval_s": 2,      # seconds between samples / writes.
}
# NOTE: state = NETWORK ∨ "model-owes-a-response" (transcript). CPU% was removed long ago (idle/active
# CPU overlap). io and transcript-mtime were demoted to diagnostics on 2026-06-05 (idle disk blips
# caused false "active"; mtime never fired uniquely). Net cleanly separates idle from active for the
# START of work; the turn signal (added 2026-06-05) bridges the long net-silent gaps DURING a turn that
# net alone mis-reads as idle — together they avoid both false-working and false-idle.

# Timezone + per-machine live_monitor overrides from config.json (same file as extract.py).
_CONFIG_PATH = os.environ.get("CCSTATS_CONFIG", "/opt/claude-stats/config.json")
def _load_config():
    try:
        with open(_CONFIG_PATH) as fh:
            return json.load(fh)
    except Exception:
        return {}
_CONFIG = _load_config()
CONFIG_OVERRIDES = {k: v for k, v in (_CONFIG.get("live_monitor") or {}).items() if k in DEFAULTS}
def _tunable(key):
    return CONFIG_OVERRIDES.get(key, DEFAULTS[key])

NET_THRESHOLD     = float(_tunable("net_bytes_per_s"))
IO_THRESHOLD      = float(_tunable("io_bytes_per_s"))
TRANSCRIPT_SIGNAL = bool(_tunable("transcript_signal"))
TURN_SIGNAL       = bool(_tunable("turn_signal"))
TURN_CAP          = float(_tunable("turn_cap_s"))
IDLE_DEBOUNCE     = float(_tunable("idle_debounce_s"))
ACTIVE_DEBOUNCE   = float(_tunable("active_debounce_s"))
SAMPLE_INTERVAL   = float(_tunable("sample_interval_s"))

try:
    TZ = ZoneInfo((_CONFIG.get("timezone") or "UTC").strip() or "UTC")
except Exception:
    TZ = ZoneInfo("UTC")

# Claude Code process match (validated against live procs): cmdline contains an INCLUDE substring
# (or argv0 basename in INCLUDE_ARGV0), and NO EXCLUDE substring.
INCLUDE_SUBSTRINGS      = ["claude-code"]
INCLUDE_ARGV0_BASENAMES = ["claude"]
EXCLUDE_SUBSTRINGS      = ["claude-stats", "live-monitor", "shell-snapshots"]

WAIT_TOOL = "AskUserQuestion"          # blocked-on-user tool name
SESSIONS_GLOB = "/home/*/.claude/sessions/*.json"

DEFAULT_OUTPUT = "/var/www/stats/live-status.json"

# Celebration directives (M4b): extract.py --mode competitor detects record-breaks / trophy
# tier-ups (~2 min cadence) and queues short-lived events in this file; we fold ONE of them into
# every live-status.json write as a top-level `celebrate` key (additive — old clients ignore it).
# The badge celebrates each event id once and stops at expires_at; multiple simultaneous unlocks
# rotate every CELEB_ROTATE_S seconds. Missing file (remotes, or nothing to celebrate) → no key.
DEFAULT_CELEBRATIONS = "/opt/claude-stats/celebrations.json"
CELEB_ROTATE_S = 6.0
# ------------------------------------------------------------------------------------------------


def now_iso():
    return datetime.now(TZ).isoformat(timespec="seconds")


def log(msg):
    print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------- process / CPU sampling --------------------------------------
def read_cmdline(pid):
    with open(f"/proc/{pid}/cmdline", "rb") as f:
        return f.read().replace(b"\x00", b" ").decode("utf-8", "replace").strip()


def proc_user(pid):
    with open(f"/proc/{pid}/status") as f:
        for line in f:
            if line.startswith("Uid:"):
                uid = int(line.split()[1])
                try:
                    return pwd.getpwuid(uid).pw_name
                except KeyError:
                    return str(uid)
    return None


def _stat_fields(pid):
    """Fields of /proc/[pid]/stat AFTER '(comm)' — index 0 == field 3 (state)."""
    with open(f"/proc/{pid}/stat") as f:
        data = f.read()
    return data[data.rfind(")") + 2:].split()


def proc_starttime(pid):
    return _stat_fields(pid)[19]            # starttime (f22), as string — used for PID-reuse liveness


def proc_io(pid):
    """rchar+wchar from /proc/[pid]/io (total bytes through read()/write() incl. sockets).
    Mode 0400 — readable only as owner/root; the daemon is root. 0 if unreadable."""
    rchar = wchar = 0
    try:
        with open(f"/proc/{pid}/io") as f:
            for line in f:
                if line.startswith("rchar:"):
                    rchar = int(line.split()[1])
                elif line.startswith("wchar:"):
                    wchar = int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return 0
    return rchar + wchar


_SS_PID = re.compile(r'pid=(\d+)')
_SS_BS  = re.compile(r'bytes_sent:(\d+)')
_SS_BR  = re.compile(r'bytes_received:(\d+)')


def sample_net(pid_user):
    """Cumulative bytes (sent+received) per REMOTE TCP socket owned by a Claude process, from
    `ss -tinp`. Returns {(pid, local, peer): bytes_total}; the caller diffs across samples and sums
    positive deltas per user to get B/s. Remote = non-loopback peer (idle Claude does ~0 here; a
    live turn streams hundreds–100k B/s, set by token streaming → portable across hardware).
    `ss` lists a socket line then an indented tcp_info line. As root it sees every user's sockets;
    as a normal user only its own (enough for self-test). Best-effort — {} if `ss` is unavailable."""
    socks = {}
    try:
        res = subprocess.run(["ss", "-tinp"], capture_output=True, text=True, timeout=10)
    except Exception:
        return socks
    lines = res.stdout.splitlines()
    for i, line in enumerate(lines):
        if not line or line[0].isspace() or line.startswith("Recv-Q"):
            continue                                   # skip header + indented tcp_info lines
        m = _SS_PID.search(line)
        if not m or m.group(1) not in pid_user:
            continue                                   # not a Claude-owned socket
        cols = line.split()
        if len(cols) < 5:
            continue
        local, peer = cols[3], cols[4]
        if peer.startswith("127.") or peer.startswith("[::1]"):
            continue                                   # loopback (IDE/MCP) isn't API work
        info = lines[i + 1] if i + 1 < len(lines) and lines[i + 1][:1].isspace() else ""
        bs = _SS_BS.search(info)
        br = _SS_BR.search(info)
        socks[(m.group(1), local, peer)] = (int(bs.group(1)) if bs else 0) + (int(br.group(1)) if br else 0)
    return socks


def is_claude(cmdline):
    low = cmdline.lower()
    if any(x in low for x in EXCLUDE_SUBSTRINGS):
        return False
    if any(x in low for x in INCLUDE_SUBSTRINGS):
        return True
    return os.path.basename(cmdline.split(" ", 1)[0]) in INCLUDE_ARGV0_BASENAMES


def discover():
    """{pid(str): (user, io_bytes)} for current Claude Code processes."""
    out = {}
    for p in glob.glob("/proc/[0-9]*"):
        pid = os.path.basename(p)
        try:
            cl = read_cmdline(pid)
            if not cl or not is_claude(cl):
                continue
            user = proc_user(pid)
            io = proc_io(pid)
        except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError, IndexError):
            continue
        if user:
            out[pid] = (user, io)
    return out


# ---------------- transcript turn-state: waiting + "model owes a response" ----------------------
# One walk yields (1) the unanswered tool calls in the final assistant turn (for the AskUserQuestion
# "waiting" detection) and (2) the LAST meaningful record kind, which tells us whether the turn is
# still in progress. The latter is the ground truth that fixes false-idles during long API latency:
# while the model owes a response the network can be silent for 15-25 s+ (measured), so net/io/mtime
# all go quiet even though the turn isn't done. "owes a response" holds working across that silence.
# Defensive cap on UNTRUSTED transcript input (these .jsonl files are written by other local users):
# never read a multi-GB file into this 2-second monitor. ~30x the largest real transcript (~8 MB).
MAX_TRANSCRIPT_BYTES = 256 * 1024 * 1024
MAX_LINE_BYTES       = 16 * 1024 * 1024


def tail_state(path):
    """Return (pending_tools, last_kind). last_kind ∈ user_prompt | tool_result | assistant_tooluse
    | assistant_text | complete. user_prompt/tool_result ⇒ the model owes output; assistant_tooluse
    with a non-AskUserQuestion pending tool ⇒ a tool is running; assistant_text ⇒ turn complete."""
    tool_names, answered, last_ids, last_kind = {}, set(), [], "complete"
    try:
        if os.path.getsize(path) > MAX_TRANSCRIPT_BYTES:
            return [], "complete"   # absurdly large transcript — treat as idle rather than OOM the monitor
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
                continue                       # skip corrupt/truncated lines
            if o.get("isMeta") or o.get("isSidechain"):
                continue                       # system/subagent noise — not the main turn boundary
            t = o.get("type")
            if t == "assistant":
                ids, has_text = [], False
                for b in o.get("message", {}).get("content", []):
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_use":
                        tool_names[b["id"]] = b.get("name"); ids.append(b["id"])
                    elif b.get("type") == "text" and (b.get("text") or "").strip():
                        has_text = True
                if ids:
                    last_ids = ids; last_kind = "assistant_tooluse"
                elif has_text:
                    last_kind = "assistant_text"
            elif t == "user":
                c = o.get("message", {}).get("content", [])
                is_result = o.get("toolUseResult") is not None
                if isinstance(c, list):
                    for b in c:
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            answered.add(b.get("tool_use_id")); is_result = True
                if is_result:
                    last_kind = "tool_result"
                else:                          # a real human prompt? (text block not starting with '<')
                    txt = ""
                    if isinstance(c, list):
                        for b in c:
                            if isinstance(b, dict) and b.get("type") == "text":
                                txt = b.get("text") or ""; break
                    elif isinstance(c, str):
                        txt = c
                    if txt.strip() and not txt.lstrip().startswith("<"):
                        last_kind = "user_prompt"
    return [tool_names[i] for i in last_ids if i not in answered], last_kind


_state_cache = {}    # transcript path -> ((mtime_ns, size), (pending_list, last_kind))


def transcript_state(path):
    """tail_state(path), re-parsed only when the file changes (append-only → mtime/size bump)."""
    try:
        st = os.stat(path)
    except OSError:
        return [], "complete"
    key = (st.st_mtime_ns, st.st_size)
    cached = _state_cache.get(path)
    if cached and cached[0] == key:
        return cached[1]
    val = tail_state(path)
    _state_cache[path] = (key, val)
    return val


_transcript_mtime = {}    # transcript path -> last-seen mtime_ns (for the activity signal)


def scan_sessions():
    """Scan live sessions once, returning:
       waiting    = {user: [sessionId, ...]}  blocked on AskUserQuestion
       tx_active  = {user}                     a live transcript's mtime advanced since last sample
       owes       = {user}                     the model owes a response (turn in progress) — holds
                                               working across silent API latency. A tool actively
                                               running (non-AskUserQuestion pending) also counts.
    All three come from the same session-registry walk so we stat/parse each transcript once."""
    waiting, tx_active, owes = {}, set(), set()
    seen_paths = set()
    for reg in glob.glob(SESSIONS_GLOB):
        try:
            s = json.load(open(reg))
        except Exception:
            continue
        pid, sid, cwd = s.get("pid"), s.get("sessionId"), s.get("cwd") or ""
        if not (pid and sid and cwd):
            continue
        try:                                   # liveness: pid alive AND same process (procStart guards pid reuse)
            if proc_starttime(pid) != str(s.get("procStart")):
                continue
        except (OSError, IndexError):
            continue
        claude_dir = os.path.dirname(os.path.dirname(reg))      # /home/<user>/.claude
        user = reg.split("/")[2] if reg.startswith("/home/") else "?"
        tpath = f"{claude_dir}/projects/{cwd.replace('/', '-')}/{sid}.jsonl"
        seen_paths.add(tpath)

        # transcript-mtime activity signal: appended while a turn runs → mtime advances
        if TRANSCRIPT_SIGNAL:
            try:
                m = os.stat(tpath).st_mtime_ns
                prev = _transcript_mtime.get(tpath)
                if prev is not None and m != prev:
                    tx_active.add(user)
                _transcript_mtime[tpath] = m
            except OSError:
                pass

        try:
            pend, last_kind = transcript_state(tpath)
        except OSError:
            continue
        if WAIT_TOOL in pend:
            waiting.setdefault(user, []).append(sid)
        # model owes a response: last record is a prompt/tool_result, or a real tool is running
        if TURN_SIGNAL:
            if last_kind in ("user_prompt", "tool_result"):
                owes.add(user)
            elif last_kind == "assistant_tooluse" and any(t != WAIT_TOOL for t in pend):
                owes.add(user)

    for dead in set(_transcript_mtime) - seen_paths:            # forget transcripts of ended sessions
        del _transcript_mtime[dead]
    return waiting, tx_active, owes


def write_json(obj, path, chown_www=True):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, separators=(",", ":"))
    os.replace(tmp, path)
    if chown_www:
        try:
            os.chown(path, pwd.getpwnam("www-data").pw_uid, grp.getgrnam("www-data").gr_gid)
        except (KeyError, PermissionError):
            pass
    os.chmod(path, 0o644)


# ------------------------------ multi-server merge (main only) ----------------------------------
def load_remote_live(merge_dir, stale_s):
    """Fold per-server live files shipped by remotes (merge_dir/<label>.json) into one user map.
    A file older than stale_s (remote stopped shipping / tunnel dropped) can't claim 'working' —
    its users are forced to idle and flagged stale, so the global status never sticks on 'working'.
    Returns ({ "server:user": entry }, [(server, stale, age_s), ...])."""
    out, info = {}, []
    for ff in sorted(glob.glob(os.path.join(merge_dir, "*.json"))):
        try:
            d = json.load(open(ff))
        except Exception:
            continue
        srv = d.get("server") or os.path.splitext(os.path.basename(ff))[0]
        age = None
        ts = d.get("updated_at")
        if ts:
            try:
                age = (datetime.now(TZ) - datetime.fromisoformat(ts)).total_seconds()
            except Exception:
                age = None
        if age is None:
            try:
                age = time.time() - os.stat(ff).st_mtime
            except OSError:
                age = 1e9
        stale = age is None or age > stale_s
        for ukey, e in (d.get("users") or {}).items():
            e = dict(e)
            e["server"] = e.get("server", srv)
            if stale:
                if e.get("status") == "working":
                    e["status"] = "idle"
                e["stale"] = True
            out[f"{srv}:{e.get('user', ukey.split(':')[-1])}"] = e
        info.append((srv, stale, round(age, 1) if age is not None else None))
    return out, info


# --------------------------- celebration directive (badge avatar) -------------------------------
_celeb_cache = {"key": None, "events": []}


def current_celebration(path):
    """The single active celebrate directive (or None): load the queue file (re-parsed only when
    it changes), drop expired events, rotate through the survivors every CELEB_ROTATE_S seconds.
    The id stays stable across rotations of the same event, so the badge's celebrate-once-per-id
    dedup works while the field persists for the whole window."""
    try:
        st = os.stat(path)
    except OSError:
        return None                                  # no queue (remotes / nothing detected yet)
    key = (st.st_mtime_ns, st.st_size)
    if _celeb_cache["key"] != key:
        try:
            with open(path) as fh:
                events = json.load(fh).get("events") or []
        except Exception:
            events = []
        _celeb_cache["key"] = key
        _celeb_cache["events"] = events
    now_utc = datetime.now(timezone.utc)
    live = []
    for event in _celeb_cache["events"]:
        try:
            expires = datetime.fromisoformat(str(event.get("expires_at", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if expires > now_utc:
            live.append(event)
    if not live:
        return None
    return live[int(time.time() // CELEB_ROTATE_S) % len(live)]


# ----------------------------- ship local status to main (remotes) ------------------------------
def shipper(args):
    """Daemon thread: push OUTPUT to main while a session has been live within the grace window,
    over a multiplexed (ControlMaster) SSH connection that stays warm between 2 s pushes and is
    allowed to drop once we stop pushing after `ship_grace` s of no live session. sftp put→rename
    so main never reads a half-written file. Failures are logged, never fatal."""
    try:
        os.makedirs(os.path.dirname(args.ship_control), exist_ok=True)
    except OSError:
        pass
    rdir = args.ship_remote_path.rstrip("/")
    remote_tmp, remote_dst = f"{rdir}/.{args.server}.json.tmp", f"{rdir}/{args.server}.json"
    base = ["sftp", "-q", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ControlMaster=auto", "-o", f"ControlPath={args.ship_control}",
            "-o", f"ControlPersist={args.ship_persist}", "-i", args.ship_key, "-b", "-", args.ship_dest]
    batch = f"put {args.output} {remote_tmp}\nrename {remote_tmp} {remote_dst}\n"
    last_present = 0.0
    warm = False
    log(f"shipper start | dest={args.ship_dest} grace={args.ship_grace}s persist={args.ship_persist}s")
    while True:
        try:
            present = json.load(open(args.output)).get("status") != "no_processes"
        except Exception:
            present = False
        now = time.monotonic()
        if present:
            last_present = now
        if now - last_present <= args.ship_grace:
            try:
                r = subprocess.run(base, input=batch, text=True, timeout=15,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                if r.returncode != 0:
                    log(f"shipper: push rc={r.returncode} {(r.stderr or '').strip()[:120]}")
                warm = True
            except Exception as e:
                log(f"shipper: push failed ({e})")
        elif warm:
            log("shipper: idle past grace — pausing uploads (tunnel will drop)")
            warm = False
        time.sleep(args.ship_interval)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true", help="log raw CPU + waiting each sample")
    ap.add_argument("--output", default=DEFAULT_OUTPUT, help="where to write the status JSON")
    ap.add_argument("--server", default="main", help="label tagged on this machine's users")
    ap.add_argument("--no-chown", action="store_true", help="don't chown output to www-data (remotes)")
    # main only: fold per-server files shipped by remotes into the served aggregate
    ap.add_argument("--merge-dir", default=None, help="dir of remote-shipped <label>.json to merge in")
    ap.add_argument("--celebrations-file", default=DEFAULT_CELEBRATIONS,
                    help="celebrate-directive queue written by extract.py --mode competitor")
    ap.add_argument("--stale-seconds", type=float, default=10.0,
                    help="a remote file older than this can't report 'working' (forced idle)")
    # remotes only: ship OUTPUT up to main over a multiplexed, activity-gated SSH connection
    ap.add_argument("--ship-dest", default=None, help="statsuser@main-domain — enables shipping")
    ap.add_argument("--ship-key", default="/root/.ssh/ccstats_frag", help="ssh identity for shipping")
    ap.add_argument("--ship-remote-path", default="/var/www/stats/live-remote",
                    help="dir on main to upload <server>.json into")
    ap.add_argument("--ship-grace", type=float, default=1800.0,
                    help="keep shipping (tunnel warm) this long after the last live session")
    ap.add_argument("--ship-interval", type=float, default=2.0, help="seconds between uploads")
    ap.add_argument("--ship-persist", type=int, default=30, help="ssh ControlPersist seconds")
    ap.add_argument("--ship-control", default="/run/ccstats/cm-live", help="ssh ControlPath socket")
    args = ap.parse_args()

    if args.ship_dest:
        threading.Thread(target=shipper, args=(args,), daemon=True).start()

    users = {}            # user -> {act_status, status, since_iso, idle_since, active_since, _wait, _sig}
    known = set()

    base = discover()
    prev_io = {pid: io for pid, (u, io) in base.items()}
    prev_net = sample_net({pid: u for pid, (u, io) in base.items()})   # (pid,local,peer) -> bytes
    for _, (u, _io) in base.items():
        known.add(u)
    prev_mono = time.monotonic()
    log(f"monitor start | config={_CONFIG_PATH} overrides={CONFIG_OVERRIDES or '(none)'} "
        f"| state: net>={NET_THRESHOLD:.0f}B/s ∨ owes-response({'on' if TURN_SIGNAL else 'off'},cap={TURN_CAP:.0f}s) "
        f"| diag: io>={IO_THRESHOLD:.0f}B/s transcript={'on' if TRANSCRIPT_SIGNAL else 'off'} "
        f"| idle_debounce={IDLE_DEBOUNCE}s active_debounce={ACTIVE_DEBOUNCE}s interval={SAMPLE_INTERVAL}s "
        f"| waiting=unanswered {WAIT_TOOL}")
    time.sleep(SAMPLE_INTERVAL)

    while True:
        cur = discover()
        now_mono = time.monotonic()
        elapsed = max(1e-6, now_mono - prev_mono)

        # I/O (secondary): busiest single process per user (max matches top, stops idle helpers summing).
        uio, upids = {}, {}
        for pid, (u, io) in cur.items():
            known.add(u)
            io_bps = max(0, io - prev_io.get(pid, io)) / elapsed              # bytes/sec (rchar+wchar)
            uio[u] = max(uio.get(u, 0.0), io_bps)
            upids.setdefault(u, []).append(int(pid))

        # NETWORK (primary): bytes/s on each user's remote sockets, summed over positive per-socket
        # deltas. A socket that closed (or a new one) contributes 0, never a spurious negative/spike.
        pid_user = {pid: u for pid, (u, io) in cur.items()}
        cur_net = sample_net(pid_user)
        unet = {}
        for key, tot in cur_net.items():
            d = tot - prev_net.get(key, tot)
            if d > 0:
                u = pid_user.get(key[0])
                if u:
                    unet[u] = unet.get(u, 0.0) + d / elapsed
        prev_net = cur_net

        waiting_users, tx_active, owes_users = scan_sessions()
        known.update(waiting_users)
        known.update(tx_active)
        known.update(owes_users)

        for u in known:
            io_bps  = uio.get(u, 0.0)
            net_bps = unet.get(u, 0.0)
            # per-sample raw signals. Two STATE signals drive `active`:
            #  • NET  — net traffic now (a turn opens with API traffic; idle net floor is clean <300 B/s).
            #  • OWES — the transcript says the model owes a response (turn in progress). This holds
            #           working across the long net-silent gaps DURING a turn (model thinking server-side,
            #           15-25s+ with nothing streaming) that net alone mis-reads as idle. Capped at
            #           TURN_CAP past the last net activity so a dead/hung turn still decays.
            # io and transcript-mtime are measured for the diagnostic signals string only — NOT in `active`.
            sig_net = net_bps >= NET_THRESHOLD
            sig_io  = io_bps  >= IO_THRESHOLD     # diagnostic only (noisy) — not in `active`
            sig_tx  = u in tx_active              # diagnostic only — not in `active`

            st = users.get(u)
            if st is None:
                st = {"act_status": "idle", "status": "idle", "since_iso": now_iso(),
                      "idle_since": now_mono, "active_since": None, "_wait": [], "_sig": "",
                      "last_net_mono": now_mono}
                users[u] = st
            if sig_net:
                st["last_net_mono"] = now_mono
            sig_owes = TURN_SIGNAL and (u in owes_users) and (now_mono - st["last_net_mono"] <= TURN_CAP)
            active = sig_net or sig_owes

            st["_sig"] = (("N" if sig_net else "-") + ("I" if sig_io else "-")
                          + ("T" if sig_tx else "-") + ("R" if sig_owes else "-"))   # N I T R(owes)

            # combined-signal debounce → underlying act_status
            if active:
                st["idle_since"] = None
                if st["act_status"] != "working":
                    if st["active_since"] is None:
                        st["active_since"] = now_mono
                    if now_mono - st["active_since"] >= ACTIVE_DEBOUNCE:
                        st["act_status"] = "working"
            else:
                st["active_since"] = None
                if st["act_status"] == "working":
                    if st["idle_since"] is None:
                        st["idle_since"] = now_mono
                    if now_mono - st["idle_since"] >= IDLE_DEBOUNCE:
                        st["act_status"] = "idle"

            # waiting overrides idle/working → effective status
            wsids = waiting_users.get(u, [])
            st["_wait"] = wsids
            effective = "waiting" if wsids else st["act_status"]
            if effective != st["status"]:
                why = ("blocked on AskUserQuestion" if effective == "waiting"
                       else f"net {net_bps:.0f}B/s owes={'y' if sig_owes else 'n'} "
                            f"io {io_bps:.0f}B/s sig[{st['_sig']}]")
                log(f"{u}: {st['status']} → {effective} ({why})")
                st["status"] = effective
                st["since_iso"] = now_iso()

        any_pids = len(cur) > 0
        # this machine's users, keyed server:user (unique across servers once merged)
        combined = {f"{args.server}:{u}": {
            "server": args.server,
            "user": u,
            "status": users[u]["status"],
            "act_status": users[u]["act_status"],     # activity status pre-waiting (net ∨ owes-response)
            "net_bps": round(unet.get(u, 0.0)),       # state signal: remote-socket bytes/s
            "owes_response": u in owes_users,         # state signal: transcript says turn in progress
            "io_bps": round(uio.get(u, 0.0)),
            "signals": users[u]["_sig"],              # this-sample raw fires N/I/T/R, e.g. "N--R", "---R"
            "waiting": bool(users[u]["_wait"]),
            "waiting_sessions": users[u]["_wait"],
            "pids": sorted(upids.get(u, [])),
            "since": users[u]["since_iso"],
        } for u in sorted(known)}

        # main: fold in remote-shipped per-server files (stale ones can't claim 'working')
        remote_info = []
        if args.merge_dir and os.path.isdir(args.merge_dir):
            remote_users, remote_info = load_remote_live(args.merge_dir, args.stale_seconds)
            combined.update(remote_users)

        statuses = [e.get("status") for e in combined.values()]
        any_waiting = any(s == "waiting" for s in statuses)
        any_working = any(s == "working" for s in statuses)
        present = any_pids or any(s in ("working", "idle", "waiting") for s in statuses)
        top = ("waiting" if any_waiting else "working" if any_working
               else "idle" if present else "no_processes")

        payload = {
            "status": top,
            "server": args.server,
            "servers": sorted({e["server"] for e in combined.values()}) or [args.server],
            "users": combined,
            "thresholds": {
                "net_bytes_per_s": NET_THRESHOLD, "io_bytes_per_s": IO_THRESHOLD,
                "transcript_signal": TRANSCRIPT_SIGNAL,
                "turn_signal": TURN_SIGNAL, "turn_cap_s": TURN_CAP,
                "idle_debounce_s": IDLE_DEBOUNCE, "active_debounce_s": ACTIVE_DEBOUNCE,
                "sample_interval_s": SAMPLE_INTERVAL,
                "net_basis": "remote-socket bytes/s (sent+received), busiest user, via ss -tinp",
                "config_overrides": CONFIG_OVERRIDES or None,
                "active_rule": "working when NET over threshold OR the transcript shows the model owes "
                               "a response (turn in progress, capped at turn_cap_s past last net) for "
                               "active_debounce s; idle when both quiet for idle_debounce s. io and "
                               "transcript-mtime are diagnostic-only, not state signals.",
                "wait_tool": WAIT_TOOL,
            },
            "updated_at": now_iso(),
        }
        celebrate = current_celebration(args.celebrations_file)
        if celebrate:
            payload["celebrate"] = celebrate
        write_json(payload, args.output, chown_www=not args.no_chown)

        if args.verbose:
            detail = "  ".join(
                f"{u}=net{unet.get(u,0):.0f}B/s io=max{uio.get(u,0):.0f}B/s"
                f"[{ 'Q' if users[u]['status']=='waiting' else users[u]['act_status'][0] }:{users[u]['_sig']}]"
                for u in sorted(known)
            ) or "(no claude procs)"
            log(f"sample dt={elapsed:.2f}s  {detail}")

        prev_io = {pid: io for pid, (u, io) in cur.items()}
        prev_mono = now_mono
        time.sleep(SAMPLE_INTERVAL)


if __name__ == "__main__":
    main()
