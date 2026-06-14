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
Claude Code usage stats extractor / aggregator — with a durable all-time ledger.

Modes:
  --mode full     : parse local /home/*/.claude/projects PER SESSION, upsert each session into
                    the SQLite ledger, fold in remote fragments, then aggregate the WHOLE ledger
                    (incl. sessions whose transcripts have since been deleted) into the badge JSON.
                    Result = genuinely ALL-TIME, even though Claude Code prunes old transcripts.
  --mode fragment : emit this server's per-session rows for a remote main server to ingest.
  --mode seed     : one-time — insert "archive" rows for usage pruned BEFORE the ledger existed
                    (best-effort, from observed pre-ledger peaks). Idempotent.

Ledger design:
  * One row per session (keyed by sessionId). Each run, re-parse the transcripts that still exist
    and upsert each session's latest metrics; sessions not seen this run are RETAINED (alive=0).
    Append-only transcripts only grow, so replacing with the latest value is correct & idempotent.
  * Cross-session de-duplication: a single API request (requestId) or user prompt (uuid) can be
    copied into more than one transcript (session resume). A persistent `record_owner` table pins
    each record id to the FIRST session that banked it, counted once there and retained even after
    that session is deleted — so a surviving copy never double-counts it.

Stdlib only.
"""

import argparse
import glob
import json
import os
import re
import shutil
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# Per-machine config (alias, peers, timezone) lives OUTSIDE the repo, in config.json (gitignored).
# The competition feature reads alias/peers from it; the rest of the pipeline works without it.
# See config.example.json.
_CONFIG_PATH = os.environ.get("CCSTATS_CONFIG", "/opt/claude-stats/config.json")


def load_config(path=None):
    try:
        with open(path or _CONFIG_PATH) as fh:
            return json.load(fh) or {}
    except Exception:
        return {}


def _resolve_tz(cfg):
    """(name, ZoneInfo) for the configured timezone; UTC if unset/invalid. All hour/day bucketing
       uses this — it comes from the per-machine config.json, never hardcoded."""
    name = (cfg.get("timezone") or "UTC").strip() or "UTC"
    try:
        return name, ZoneInfo(name)
    except Exception:
        return "UTC", ZoneInfo("UTC")


# Default from config.json at the standard path (UTC if absent); main() re-resolves from --config.
TZ_NAME, TZ = _resolve_tz(load_config())

URL_RE = re.compile(r"https?://\S+")
# For the "true typed" char count we additionally drop pasted code: fenced ```...``` blocks and
# `inline` spans. This CC build inlines pasted text with no [Pasted text #N] marker, so code fences
# are the best paste signal available. Strip fences BEFORE inline spans (order matters).
FENCE_RE = re.compile(r"```.*?```", re.S)
INLINE_CODE_RE = re.compile(r"`[^`]*`")
# Pasted-markdown drop: a prompt carrying >= MD_DROP_MIN structural markdown indicators (## .. ######
# header lines + **bold** spans) is treated as a pasted/generated markdown document the user wouldn't
# hand-type (not human input), and dropped whole from word/char/prompt counts. A lone header or a
# single bold span is kept (could be typed prose with one emphasis); the threshold means genuine
# prose is virtually never caught — only docs with several markers at once.
MD_HEADER_RE = re.compile(r"^[ \t]*#{2,6}[ \t]+\S", re.M)
MD_BOLD_RE = re.compile(r"\*\*[^*\n]+\*\*")
MD_DROP_MIN = 3
IGNORE_RE = re.compile(r"\bignore\b", re.IGNORECASE)
WORK_SESSION_GAP = timedelta(minutes=20)
SCHEMA_VERSION = 1
DAY = timedelta(days=1)
FALLBACK_MODEL = "claude-opus-4-7"
DEFAULT_LEDGER = "/opt/claude-stats/ledger.db"

SCALAR_KEYS = ("tokens_input", "tokens_output", "tokens_cache_read", "tokens_cache_create",
               "user_words", "user_chars", "user_chars_typed", "user_prompts", "sessions",
               "work_sessions", "total_active_min", "nightowl_active_min")

# Best-effort recovery of usage pruned BEFORE the ledger existed (--mode seed). Populate this with
# per-project aggregate figures if you need to backfill totals that were lost before this ledger
# was first built; the archived slice carries totals only (no per-day/heatmap detail). Empty by
# default — the ledger is authoritative from its own start.
# Format: { "<project>": {"username": "<user>", "tokens_total": int, "sessions": int,
#                          "user_words": int, "user_prompts": int, "work_sessions": int}, ... }
PRELEDGER_PEAK = {}

_warnings = set()


def warn(msg):
    if msg not in _warnings:
        _warnings.add(msg)
        print("WARN:", msg, file=sys.stderr)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def parse_ts(s):
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def local_date_str(dt):
    return dt.astimezone(TZ).date().isoformat()


def load_pricing(path):
    try:
        with open(path) as fh:
            data = json.load(fh)
        return data.get("models", {}), data.get("pricing_date", "unknown")
    except Exception as e:
        warn("could not load pricing %s (%s); costs will be 0" % (path, e))
        return {}, "unknown"


def cost_for_model_tokens(model, toks, pricing):
    rate = pricing.get(model)
    if rate is None:
        warn("model %r not in pricing table; using %s rates" % (model, FALLBACK_MODEL))
        rate = pricing.get(FALLBACK_MODEL, {})
    return {
        "input_usd": toks.get("input", 0) * rate.get("input", 0) / 1_000_000,
        "output_usd": toks.get("output", 0) * rate.get("output", 0) / 1_000_000,
        "cache_read_usd": toks.get("cache_read", 0) * rate.get("cache_read", 0) / 1_000_000,
        "cache_create_usd": toks.get("cache_create", 0) * rate.get("cache_create", 0) / 1_000_000,
    }


def cost_from_model_tokens(mtoks, pricing):
    acc = {"input_usd": 0.0, "output_usd": 0.0, "cache_read_usd": 0.0, "cache_create_usd": 0.0}
    for m, t in mtoks.items():
        c = cost_for_model_tokens(m, t, pricing)
        for k in acc:
            acc[k] += c[k]
    acc["total_usd"] = sum(acc.values())
    return acc


def discover_projects(home_glob):
    out = []
    for home in sorted(glob.glob(home_glob)):
        if not os.path.isdir(home):
            continue
        user = os.path.basename(home.rstrip("/"))
        projdir = os.path.join(home, ".claude", "projects")
        if not os.path.isdir(projdir):
            continue
        name = user
        namefile = os.path.join(home, "projectname.txt")
        if os.path.isfile(namefile):
            try:
                content = open(namefile, errors="replace").read().strip()
            except Exception:
                content = ""
            if IGNORE_RE.search(content):
                continue
            if content:
                name = content
        out.append((user, name, projdir))
    return out


def project_name(mode, configured_name, cwd):
    """Resolve a session's project name for the chosen granularity.
       'user' (default): the home/projectname.txt name — one project per Linux user (unchanged
         behaviour). 'directory': one project per Claude Code working directory, taken from the exact
         `cwd` recorded in the transcript (its basename), so several projects under ONE user each get
         their own row. Falls back to the user name if a transcript carries no cwd."""
    if mode == "directory" and cwd:
        base = os.path.basename(cwd.rstrip("/"))
        if base:
            return base
    return configured_name


# --------------------------------------------------------------------------- #
# Per-session parsing → raw records (so cross-session dedup can pick an owner)
# --------------------------------------------------------------------------- #
def group_files(projdir):
    """Yield (sessionId, [files], has_top): a session's transcript + its subagent files."""
    files = glob.glob(os.path.join(projdir, "**", "*.jsonl"), recursive=True)
    groups = defaultdict(list)
    has_top = {}
    for f in files:
        rel = os.path.relpath(f, projdir).split(os.sep)
        if len(rel) == 2:                       # <encoded>/<sessionId>.jsonl
            sid = rel[1][:-6] if rel[1].endswith(".jsonl") else rel[1]
            has_top[sid] = True
        else:                                   # <encoded>/<sessionId>/subagents/...
            sid = rel[1]
            has_top.setdefault(sid, False)
        groups[sid].append(f)
    for sid, fl in groups.items():
        yield sid, fl, has_top.get(sid, False)


# Defensive caps on UNTRUSTED transcript input (these .jsonl files are written by other local
# users). Largest real line observed ~0.4 MB and largest file ~8 MB, so these caps sit ~30-40x
# above reality — they never drop legitimate data, but bound a hostile multi-GB drop from OOM-ing
# the root cron that parses them.
MAX_TRANSCRIPT_BYTES = 256 * 1024 * 1024   # skip an entire transcript file larger than this
MAX_LINE_BYTES       = 16 * 1024 * 1024    # skip a single pathological line larger than this


def parse_session_records(files):
    """Parse a session's files into per-record contributions, deduped WITHIN the session.
       assistant keyed by requestId (keep max output_tokens); user prompts keyed by uuid."""
    asst = {}      # rid -> {in,out,cr,cc,model,tools,date}
    tool_ids = {}  # rid -> {block_id: tool_name} — unioned across the rid's streaming records
    users = {}     # uuid -> {words,chars,date,hour,weekday}
    events = []    # [datetime] for work-session timeline
    date_min = date_max = None
    cwd = None     # the session's working dir (from the transcript) — names projects in 'directory' mode

    for f in files:
        try:
            sz = os.path.getsize(f)
        except OSError:
            sz = 0
        if sz > MAX_TRANSCRIPT_BYTES:
            warn("skipping oversized transcript %s (%d bytes)" % (f, sz))
            continue
        try:
            fh = open(f, errors="replace")
        except OSError as e:
            warn("cannot open %s (%s)" % (f, e))
            continue
        with fh:
            for line in fh:
                if len(line) > MAX_LINE_BYTES:
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if cwd is None:
                    cwd = r.get("cwd") or None   # first cwd seen wins; used by 'directory' granularity
                dt = parse_ts(r.get("timestamp"))
                if dt is not None:
                    events.append(dt)
                    d = local_date_str(dt)
                    if date_min is None or d < date_min:
                        date_min = d
                    if date_max is None or d > date_max:
                        date_max = d
                rtype = r.get("type")
                if rtype == "assistant":
                    msg = r.get("message") or {}
                    model = msg.get("model")
                    if model == "<synthetic>":
                        continue
                    usage = msg.get("usage") or {}
                    out = int(usage.get("output_tokens") or 0)
                    rid = r.get("requestId") or r.get("uuid")
                    if rid is None:
                        continue
                    # Claude Code writes EACH tool_use block as its OWN streaming record: all the
                    # records of one requestId share the same cumulative output_tokens, and the
                    # tool_use blocks are spread one-per-record across them — no single record holds
                    # the complete set. So accumulate tool_use blocks across ALL of the requestId's
                    # records, deduped by block id, instead of reading them off one chosen record.
                    # Keeping only the max-output record (the old behaviour) silently undercounted
                    # tool_uses ~2x and parallel-launch tools (e.g. an Agent batch) ~3.5x. This is
                    # DECOUPLED from the token-field record choice below: in/out/cache still come
                    # from the max-output record (tied-max records can differ in cache split), tool
                    # blocks from the per-rid union folded on after the loop.
                    content = msg.get("content")
                    if isinstance(content, list):
                        rtools = tool_ids.setdefault(rid, {})
                        for b in content:
                            if isinstance(b, dict) and b.get("type") == "tool_use":
                                # dedup by block id (collapses any streaming-duplicate records);
                                # unique fallback key for the rare block with no id.
                                rtools.setdefault(b.get("id") or object(), b.get("name") or "unknown")
                    prev = asst.get(rid)
                    if prev is None or out > prev["out"]:
                        ldt = dt.astimezone(TZ) if dt else None
                        asst[rid] = {"in": int(usage.get("input_tokens") or 0), "out": out,
                                     "cr": int(usage.get("cache_read_input_tokens") or 0),
                                     "cc": int(usage.get("cache_creation_input_tokens") or 0),
                                     "model": model or "unknown",
                                     "date": ldt.date().isoformat() if ldt else None,
                                     "datehour": ldt.strftime("%Y-%m-%dT%H") if ldt else None}
                elif rtype == "user":
                    if r.get("isSidechain") is True or r.get("isMeta") is True:
                        continue
                    if "toolUseResult" in r or "sourceToolAssistantUUID" in r:
                        continue
                    # Compaction/continuation summaries are auto-generated by Claude Code (carry
                    # isCompactSummary=true), not human input — they start with prose so they don't
                    # trip the leading-"<" guard and would otherwise be counted as ~one giant "prompt"
                    # of typed words (the single biggest source of word-count inflation, ~8%).
                    if r.get("isCompactSummary") is True:
                        continue
                    uuid = r.get("uuid")
                    if not uuid or uuid in users:
                        continue
                    msg = r.get("message") or {}
                    content = msg.get("content")
                    if isinstance(content, str):
                        text = content
                    elif isinstance(content, list):
                        text = " ".join(b.get("text", "") for b in content
                                        if isinstance(b, dict) and b.get("type") == "text")
                    else:
                        text = ""
                    stripped = text.strip()
                    if not stripped or stripped.startswith("<"):
                        continue
                    # Drop pasted/generated markdown documents (>= MD_DROP_MIN ## headers + **bold**
                    # spans) — not hand-typed input. See MD_* definitions above.
                    if len(MD_HEADER_RE.findall(text)) + len(MD_BOLD_RE.findall(text)) >= MD_DROP_MIN:
                        continue
                    clean = URL_RE.sub("", text)
                    typed = INLINE_CODE_RE.sub("", FENCE_RE.sub("", clean))  # drop pasted code
                    ldt = dt.astimezone(TZ) if dt else None
                    users[uuid] = {"words": len(clean.split()), "chars": len(clean),
                                   "chars_typed": len(typed),
                                   "date": ldt.date().isoformat() if ldt else None,
                                   "datehour": ldt.strftime("%Y-%m-%dT%H") if ldt else None,
                                   "hour": ldt.hour if ldt else None,
                                   "weekday": ldt.weekday() if ldt else None}
    # Fold each requestId's unioned tool_use blocks onto its kept (max-output) record.
    for rid, rec in asst.items():
        rec["tools"] = list(tool_ids.get(rid, {}).values())
    return {"asst": asst, "users": users, "events": events,
            "date_min": date_min, "date_max": date_max, "cwd": cwd}


def metrics_from_records(asst, users, events, date_min, date_max):
    """Aggregate one session's OWNED records into the metrics dict (badge-row shape)."""
    tin = tout = tcr = tcc = 0
    tool_counts = Counter()
    model_counts = Counter()
    model_tokens = defaultdict(lambda: {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0, "turns": 0})
    daily_tokens = Counter()
    daily_io = Counter()   # per-day input+output (cache-free), so TODAY/AVATAR can honor the token mode
    daily_agents = Counter()  # per-day Agent (subagent) launches — banked for a future by-day UI
    # per-day per-model token split → lets main price each day for the all-time "most expensive day"
    # record (we bank TOKENS, not cost, so price changes apply retroactively — same as model_tokens).
    daily_model_tokens = defaultdict(lambda: defaultdict(
        lambda: {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0}))
    # Option-B per-hour series (local-tz "YYYY-MM-DDTHH") → {t:total, i:input, o:output, p:prompts, w:words}.
    # Enables exact rolling 24h/7d/30d windows for the head-to-head competition feed; the existing
    # day-granular daily_activity stays untouched for the badge JSON / streaks. Same tz on both
    # competitors (would need UTC keys if their timezones ever diverged). `i` (added 2026-06-04)
    # lets a window compute the no-cache "input+output" race; buckets banked before
    # then have no `i` and read as 0 (only affects the all-time window, which VERSUS doesn't use).
    hourly = defaultdict(lambda: {"t": 0, "i": 0, "o": 0, "p": 0, "w": 0})
    for rec in asst.values():
        if rec["out"] == 0:
            continue
        tin += rec["in"]; tout += rec["out"]; tcr += rec["cr"]; tcc += rec["cc"]
        mt = model_tokens[rec["model"]]
        mt["input"] += rec["in"]; mt["output"] += rec["out"]
        mt["cache_read"] += rec["cr"]; mt["cache_create"] += rec["cc"]; mt["turns"] += 1
        model_counts[rec["model"]] += 1
        for tn in rec["tools"]:
            tool_counts[tn] += 1
        rec_total = rec["in"] + rec["out"] + rec["cr"] + rec["cc"]
        if rec["date"]:
            daily_tokens[rec["date"]] += rec_total
            daily_io[rec["date"]] += rec["in"] + rec["out"]
            daily_agents[rec["date"]] += sum(1 for tn in rec["tools"] if tn == "Agent")
            dmt = daily_model_tokens[rec["date"]][rec["model"]]
            dmt["input"] += rec["in"]; dmt["output"] += rec["out"]
            dmt["cache_read"] += rec["cr"]; dmt["cache_create"] += rec["cc"]
        if rec.get("datehour"):
            h = hourly[rec["datehour"]]; h["t"] += rec_total; h["i"] += rec["in"]; h["o"] += rec["out"]

    user_words = user_chars = user_chars_typed = user_prompts = 0
    daily_prompts = Counter()
    hours = [0] * 24
    weekdays = [0] * 7
    for u in users.values():
        user_words += u["words"]; user_chars += u["chars"]
        user_chars_typed += u["chars_typed"]; user_prompts += 1
        if u["date"]:
            daily_prompts[u["date"]] += 1
        if u.get("datehour"):
            h = hourly[u["datehour"]]; h["p"] += 1; h["w"] += u["words"]
        if u["hour"] is not None:
            hours[u["hour"]] += 1
        if u["weekday"] is not None:
            weekdays[u["weekday"]] += 1

    events = sorted(events)
    work_sessions = 0
    total_active_min = 0.0
    longest_session_min = 0.0
    # (start, end) of each work-session span. Shipped per session so the FOLD can take the UNION
    # of overlapping/concurrent spans across sessions instead of summing them — i.e. count "was ANY
    # session active" wall-clock time, never double-counting parallel sessions. A single session
    # never overlaps itself, so summing its own spans == their union: per-session total_active_min
    # below is already correct; the de-overlap only matters across sessions, in combine().
    spans = []
    first = prev = None
    for ts in events:
        if prev is None:
            first = prev = ts
        elif ts - prev > WORK_SESSION_GAP:
            dur = (prev - first).total_seconds() / 60.0
            work_sessions += 1; total_active_min += dur; longest_session_min = max(longest_session_min, dur)
            if prev > first:
                spans.append((first, prev))
            first = prev = ts
        else:
            prev = ts
    if prev is not None:
        dur = (prev - first).total_seconds() / 60.0
        work_sessions += 1; total_active_min += dur; longest_session_min = max(longest_session_min, dur)
        if prev > first:
            spans.append((first, prev))

    # per-day active minutes: sum each within-work-session gap, attributed to the earlier event's
    # local day (a span crossing midnight lands on its start day — rare, negligible). Summing every
    # gap <= WORK_SESSION_GAP reconstructs total_active_min, now split per day for the TODAY screen.
    # (Computed per session so it folds across the ledger AND remote fragments — remotes must ship it.)
    daily_active = defaultdict(float)
    nightowl_active_min = 0.0   # cumulative active minutes in local hours 00:00–05:59 (NIGHT OWL trophy)
    for a, b in zip(events, events[1:]):
        if b - a <= WORK_SESSION_GAP:
            mins = (b - a).total_seconds() / 60.0
            daily_active[local_date_str(a)] += mins
            if a.astimezone(TZ).hour < 6:
                nightowl_active_min += mins

    active_dates = [d for d, c in daily_prompts.items() if c > 0]
    all_dates = sorted(set(daily_prompts) | set(daily_tokens) | set(daily_active))
    return {
        "tokens_input": tin, "tokens_output": tout, "tokens_cache_read": tcr, "tokens_cache_create": tcc,
        "tokens_total": tin + tout + tcr + tcc,
        "user_words": user_words, "user_chars": user_chars,
        "user_chars_typed": user_chars_typed, "user_prompts": user_prompts,
        "work_sessions": work_sessions, "active_days": len(active_dates),
        "longest_session_min": round(longest_session_min), "total_active_min": round(total_active_min),
        "nightowl_active_min": round(nightowl_active_min),
        # raw work-session spans (UTC ISO) → combine() unions these across sessions so concurrent
        # sessions never double-count active time. Legacy/pruned/archive rows lack this and fall
        # back to their summed total_active_min in combine() (see the fallback there).
        "active_spans": [[s.isoformat(), e.isoformat()] for s, e in spans],
        "tool_counts": dict(tool_counts), "model_counts": dict(model_counts),
        "model_tokens": {m: dict(v) for m, v in model_tokens.items()},
        "daily_model_tokens": {d: {m: dict(v) for m, v in mt.items()}
                               for d, mt in daily_model_tokens.items()},
        "daily_activity": [{"date": d, "prompts": daily_prompts.get(d, 0),
                            "tokens": daily_tokens.get(d, 0), "tokens_io": daily_io.get(d, 0),
                            "active_min": round(daily_active.get(d, 0)),
                            "agents": daily_agents.get(d, 0)} for d in all_dates],
        "hourly": {k: dict(v) for k, v in hourly.items()},
        "hours_histogram": hours, "weekdays_histogram": weekdays,
        "date_min": date_min, "date_max": date_max,
        "last_active": max(active_dates) if active_dates else date_max,
    }


def build_session_metrics(recs, owner):
    """Assign an owner to each record id (existing owner wins; else smallest session key), then
       build per-session metrics counting only records this session owns.
       Returns (metrics_by_key, new_owner_assignments)."""
    pending = defaultdict(list)   # unowned id -> [session keys containing it]
    for key, rec in recs.items():
        for rid in rec["asst"]:
            if rid not in owner:
                pending[rid].append(key)
        for uid in rec["users"]:
            if uid not in owner:
                pending[uid].append(key)
    new_assign = {}
    for rid, keys in pending.items():
        o = min(keys)
        owner[rid] = o
        new_assign[rid] = o

    metrics_by_key = {}
    for key, rec in recs.items():
        oa = {rid: r for rid, r in rec["asst"].items() if owner.get(rid) == key}
        ou = {uid: r for uid, r in rec["users"].items() if owner.get(uid) == key}
        metrics_by_key[key] = metrics_from_records(oa, ou, rec["events"], rec["date_min"], rec["date_max"])
    return metrics_by_key, new_assign


# --------------------------------------------------------------------------- #
# Ledger (SQLite)
# --------------------------------------------------------------------------- #
def open_ledger(path):
    con = sqlite3.connect(path)
    con.execute("PRAGMA busy_timeout=5000")   # let the 2-min competitor read wait out a full-run write
    con.execute("""CREATE TABLE IF NOT EXISTS sessions(
        session_id TEXT PRIMARY KEY, server TEXT, username TEXT, project TEXT,
        first_seen TEXT, last_seen TEXT, last_active TEXT,
        alive INTEGER DEFAULT 1, is_archive INTEGER DEFAULT 0, metrics TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS record_owner(
        rec_id TEXT PRIMARY KEY, owner TEXT)""")
    con.commit()
    try:
        os.chmod(path, 0o600)  # ledger holds per-session usage detail — keep it root-only (its dir is 0755)
    except OSError:
        pass
    return con


def load_record_owner(con):
    return {rid: o for rid, o in con.execute("SELECT rec_id,owner FROM record_owner")}


def persist_record_owner(con, new_assign):
    con.executemany("INSERT OR IGNORE INTO record_owner(rec_id,owner) VALUES(?,?)",
                    list(new_assign.items()))


def upsert_row(con, key, server, username, project, metrics, now):
    con.execute("""INSERT INTO sessions
        (session_id,server,username,project,first_seen,last_seen,last_active,alive,is_archive,metrics)
        VALUES(?,?,?,?,?,?,?,1,0,?)
        ON CONFLICT(session_id) DO UPDATE SET
          server=excluded.server, username=excluded.username, project=excluded.project,
          last_seen=excluded.last_seen, last_active=excluded.last_active, alive=1,
          metrics=excluded.metrics""",
        (key, server, username, project, now, now, metrics.get("last_active"), json.dumps(metrics)))


def mark_absent(con, processed_servers, seen_keys, now):
    if not processed_servers:
        return
    q = "SELECT session_id FROM sessions WHERE is_archive=0 AND server IN (%s)" % \
        ",".join("?" * len(processed_servers))
    absent = [r[0] for r in con.execute(q, list(processed_servers)) if r[0] not in seen_keys]
    con.executemany("UPDATE sessions SET alive=0 WHERE session_id=?", [(k,) for k in absent])


def load_ledger_rows(con):
    rows = []
    for sid, server, username, project, last_active, is_archive, metrics in con.execute(
            "SELECT session_id,server,username,project,last_active,is_archive,metrics FROM sessions"):
        m = json.loads(metrics)
        m["server"] = server; m["username"] = username; m["name"] = project
        m["last_active"] = m.get("last_active") or last_active
        m["_archive"] = bool(is_archive)
        rows.append(m)
    return rows


# --------------------------------------------------------------------------- #
# Aggregation over ledger rows
# --------------------------------------------------------------------------- #
def _merge_intervals(spans):
    """spans: iterable of (start_dt, end_dt) aware datetimes → merged, non-overlapping, sorted."""
    iv = sorted((s, e) for s, e in spans if e > s)
    if not iv:
        return []
    merged = [[iv[0][0], iv[0][1]]]
    for s, e in iv[1:]:
        if s <= merged[-1][1]:                 # overlaps/touches the open interval → extend it
            if e > merged[-1][1]:
                merged[-1][1] = e
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


def union_active(spans):
    """Union of active wall-clock intervals → (total_min, {local_date: min}, nightowl_min).
       Overlapping/concurrent spans count ONCE. Per-day + night-owl (00:00–05:59 local) are split
       at local-day/window edges in UTC, so DST changes don't distort the durations."""
    total = 0.0
    daily = defaultdict(float)
    nightowl = 0.0
    for s, e in _merge_intervals(spans):
        total += (e - s).total_seconds() / 60.0
        cur = s
        while cur < e:
            d = cur.astimezone(TZ).date()
            nd = d + DAY
            next_midnight = datetime(nd.year, nd.month, nd.day, tzinfo=TZ).astimezone(timezone.utc)
            night_end = datetime(d.year, d.month, d.day, 6, tzinfo=TZ).astimezone(timezone.utc)
            seg_end = min(e, next_midnight)
            daily[d.isoformat()] += (seg_end - cur).total_seconds() / 60.0
            ov_end = min(seg_end, night_end)   # cur >= local midnight already, so window start == cur
            if ov_end > cur:
                nightowl += (ov_end - cur).total_seconds() / 60.0
            cur = seg_end
    return total, dict(daily), nightowl


def combine(rows):
    c = {k: 0 for k in SCALAR_KEYS}
    c["longest_session_min"] = 0
    tool = Counter(); mcount = Counter()
    mtok = defaultdict(lambda: {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0, "turns": 0})
    daily = defaultdict(lambda: {"prompts": 0, "tokens": 0, "tokens_io": 0, "active_min": 0, "words": 0, "sessions": 0, "agents": 0})
    daily_mtok = defaultdict(lambda: defaultdict(
        lambda: {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0}))   # per-day per-model → cost/day record
    hours = [0] * 24; weekdays = [0] * 7
    # weekday×hour prompt matrix (Mon=0..Sun=6 × 0..23), derived from each session's hourly map.
    # Additive: the separate hours/weekdays histograms are untouched. Gives the true joint peak.
    weekday_hour = [[0] * 24 for _ in range(7)]
    date_min = date_max = last_active = None
    # Active-time UNION: pool spans from rows that ship them; rows that DON'T (legacy/pruned/archive,
    # or a remote not yet on this extract.py) fall back to their summed total — can't be de-overlapped
    # without the raw spans, but those are old/pruned days that rarely overlap a live span. fb_daily
    # likewise holds the legacy per-day active_min for span-less rows only.
    spans_pool = []
    fb_total = 0.0
    fb_nightowl = 0.0
    for r in rows:
        for k in SCALAR_KEYS:
            c[k] += r.get(k, 0) or 0
        c["longest_session_min"] = max(c["longest_session_min"], r.get("longest_session_min", 0) or 0)
        sp = r.get("active_spans")
        has_spans = bool(sp)
        if has_spans:
            for a, b in sp:
                sa, sb = parse_ts(a), parse_ts(b)
                if sa and sb and sb > sa:
                    spans_pool.append((sa, sb))
        else:
            fb_total += r.get("total_active_min", 0) or 0
            fb_nightowl += r.get("nightowl_active_min", 0) or 0
        tool.update(r.get("tool_counts", {}) or {})
        mcount.update(r.get("model_counts", {}) or {})
        for m, t in (r.get("model_tokens", {}) or {}).items():
            for k in ("input", "output", "cache_read", "cache_create", "turns"):
                mtok[m][k] += t.get(k, 0) or 0
        for ds, mt in (r.get("daily_model_tokens", {}) or {}).items():
            for m, t in mt.items():
                cell_m = daily_mtok[ds][m]
                for k in ("input", "output", "cache_read", "cache_create"):
                    cell_m[k] += t.get(k, 0) or 0
        for row in (r.get("daily_activity", []) or []):
            cell = daily[row["date"]]
            cell["prompts"] += row.get("prompts", 0) or 0
            cell["tokens"] += row.get("tokens", 0) or 0
            cell["tokens_io"] += row.get("tokens_io", 0) or 0
            cell["agents"] += row.get("agents", 0) or 0
            if not has_spans:                            # span rows get their per-day active_min
                cell["active_min"] += row.get("active_min", 0) or 0   # from the union pass below
            cell["sessions"] += 1   # one daily_activity row per active day per session
        for i, v in enumerate(r.get("hours_histogram", []) or []):
            hours[i] += v
        for i, v in enumerate(r.get("weekdays_histogram", []) or []):
            weekdays[i] += v
        for k, v in (r.get("hourly", {}) or {}).items():
            try:
                wd = date.fromisoformat(k[:10]).weekday(); hr = int(k[11:13])
            except (ValueError, IndexError):
                continue
            if 0 <= wd < 7 and 0 <= hr < 24:
                weekday_hour[wd][hr] += v.get("p", 0) or 0
            # per-day words from the same hourly map → feeds the AVATAR today-line WORDS stat.
            # Derived from the already-shipped `hourly` buckets (like weekday_hour), so a remote
            # contributes its words with NO remote update needed.
            daily[k[:10]]["words"] += v.get("w", 0) or 0
        dm, dx, la = r.get("date_min"), r.get("date_max"), r.get("last_active")
        if dm and (date_min is None or dm < date_min): date_min = dm
        if dx and (date_max is None or dx > date_max): date_max = dx
        if la and (last_active is None or la > last_active): last_active = la
    c["tokens_total"] = c["tokens_input"] + c["tokens_output"] + c["tokens_cache_read"] + c["tokens_cache_create"]
    c["tool_counts"] = dict(tool); c["model_counts"] = dict(mcount)
    c["model_tokens"] = {m: dict(v) for m, v in mtok.items()}
    # Active time: replace the blind per-session SUM (which double-counts concurrent sessions) with
    # the UNION of all span rows + the summed fallback for span-less rows. Keep the pure sum as
    # `active_min_summed` — it's the genuine mean basis for avg_session_min (a per-session length,
    # where concurrency is irrelevant). total_active_min / nightowl_active_min / per-day active_min
    # all become "was any session active" wall-clock time, bounded by real elapsed time.
    c["active_min_summed"] = c["total_active_min"]
    u_total, u_daily, u_night = union_active(spans_pool)
    c["total_active_min"] = round(u_total + fb_total)
    c["nightowl_active_min"] = round(u_night + fb_nightowl)
    for ds, mins in u_daily.items():
        daily[ds]["active_min"] += round(mins)
    c["daily"] = dict(daily); c["hours"] = hours; c["weekdays"] = weekdays; c["weekday_hour"] = weekday_hour
    c["daily_model_tokens"] = {ds: {m: dict(v) for m, v in mt.items()} for ds, mt in daily_mtok.items()}
    c["date_min"] = date_min; c["date_max"] = date_max; c["last_active"] = last_active
    c["active_days"] = sum(1 for v in daily.values() if v["prompts"] > 0)
    return c


def longest_and_current_streak(active_set, corpus_end):
    if not active_set:
        return 0, 0
    ordered = sorted(active_set)
    longest = run = 1
    for i in range(1, len(ordered)):
        run = run + 1 if ordered[i] - ordered[i - 1] == DAY else 1
        longest = max(longest, run)
    end = date.fromisoformat(corpus_end)
    anchor = end if end in active_set else (end - DAY if (end - DAY) in active_set else None)
    current = 0
    d = anchor
    while d is not None and d in active_set:
        current += 1
        d -= DAY
    return longest, current


def aggregate(rows, pricing, pricing_date, generated_at):
    g = combine(rows)
    corpus_start = g["date_min"] or generated_at[:10]
    corpus_end = g["date_max"] or generated_at[:10]
    start_d = date.fromisoformat(corpus_start)
    end_d = date.fromisoformat(corpus_end)

    daily_activity = []
    active_set = set()
    d = start_d
    while d <= end_d:
        ds = d.isoformat()
        cell = g["daily"].get(ds, {"prompts": 0, "tokens": 0, "tokens_io": 0, "active_min": 0, "words": 0, "sessions": 0, "agents": 0})
        daily_activity.append({"date": ds, "prompts": cell["prompts"], "tokens": cell["tokens"],
                               "tokens_io": cell.get("tokens_io", 0),
                               "active_min": cell.get("active_min", 0), "words": cell.get("words", 0),
                               "sessions": cell.get("sessions", 0),
                               "agents": cell.get("agents", 0)})
        if cell["prompts"] > 0:
            active_set.add(d)
        d += DAY
    longest_streak, current_streak = longest_and_current_streak(active_set, corpus_end)

    top_tools = [{"name": n, "count": c} for n, c in Counter(g["tool_counts"]).most_common()]
    tool_uses = sum(g["tool_counts"].values())
    model_turns = Counter(g["model_counts"])
    total_turns = sum(model_turns.values())
    models = [{"name": m, "turns": c, "pct": round(c * 100.0 / total_turns, 1) if total_turns else 0.0}
              for m, c in model_turns.most_common()]
    favorite_model = model_turns.most_common(1)[0][0] if model_turns else None
    total_cost = cost_from_model_tokens(g["model_tokens"], pricing)

    # Group by project NAME only: the same project worked on from several servers (same
    # projectname.txt everywhere, e.g. ccstats on main + the Tufty-port VM) is ONE project.
    # "server" lists every contributing server (comma-joined) instead of forcing a row per server.
    # Matches the competitor feed, which has always grouped by name only.
    groups = defaultdict(list)
    for r in rows:
        groups[r.get("name")].append(r)
    proj_rows = []
    for nm, grp in groups.items():
        pg = combine(grp)
        pc = cost_from_model_tokens(pg["model_tokens"], pricing)
        srv = ",".join(sorted({r.get("server") for r in grp if r.get("server")})) or None
        proj_rows.append({
            "name": nm, "server": srv, "sessions": pg["sessions"], "work_sessions": pg["work_sessions"],
            "active_days": pg["active_days"], "tokens_total": pg["tokens_total"],
            # per-category split so a consumer can scale PROJECTS by no-cache input+output
            "tokens_input": pg["tokens_input"], "tokens_output": pg["tokens_output"],
            "tokens_cache_read": pg["tokens_cache_read"], "tokens_cache_create": pg["tokens_cache_create"],
            "user_words": pg["user_words"], "user_prompts": pg["user_prompts"],
            "tool_uses": sum(pg["tool_counts"].values()),
            "agent_launches": pg["tool_counts"].get("Agent", 0),
            "cost_estimate_usd": round(pc["total_usd"], 2),
            # active time in this project: total_active_min is the UNION (concurrent sessions counted
            # once); avg_session_min uses the SUMMED basis (mean session length — concurrency irrelevant).
            "total_active_min": pg["total_active_min"], "longest_session_min": pg["longest_session_min"],
            "avg_session_min": round(pg["active_min_summed"] / pg["work_sessions"]) if pg["work_sessions"] else 0,
            "last_active": pg["last_active"],
        })
    proj_rows.sort(key=lambda r: r["tokens_total"], reverse=True)

    cr, cc, ti = g["tokens_cache_read"], g["tokens_cache_create"], g["tokens_input"]
    cache_denom = cr + cc + ti
    return {
        "meta": {
            "schema_version": SCHEMA_VERSION, "generated_at": generated_at, "timezone": TZ_NAME,
            "corpus_start": corpus_start, "corpus_end": corpus_end,
            "corpus_days": (end_d - start_d).days + 1,
            "servers": sorted({r.get("server") for r in rows if r.get("server")}),
        },
        "totals": {
            "sessions": g["sessions"], "work_sessions": g["work_sessions"],
            "active_days": len(active_set), "current_streak": current_streak,
            "longest_streak": longest_streak, "longest_session_min": g["longest_session_min"],
            "avg_session_min": round(g["active_min_summed"] / g["work_sessions"]) if g["work_sessions"] else 0,
            "total_active_min": g["total_active_min"], "nightowl_active_min": g["nightowl_active_min"],
            "user_words": g["user_words"],
            "user_chars": g["user_chars"], "user_chars_typed": g["user_chars_typed"],
            "user_prompts": g["user_prompts"],
            "tokens_input": ti, "tokens_output": g["tokens_output"],
            "tokens_cache_read": cr, "tokens_cache_create": cc, "tokens_total": g["tokens_total"],
            "cache_hit_ratio": round(cr / cache_denom, 4) if cache_denom else 0.0,
            "tool_uses": tool_uses, "agent_launches": g["tool_counts"].get("Agent", 0),
            "favorite_model": favorite_model,
            "peak_hour": g["hours"].index(max(g["hours"])) if any(g["hours"]) else 0,
            "peak_weekday": g["weekdays"].index(max(g["weekdays"])) if any(g["weekdays"]) else 0,
        },
        "cost_estimate": {
            "total_usd": round(total_cost["total_usd"], 2), "input_usd": round(total_cost["input_usd"], 2),
            "output_usd": round(total_cost["output_usd"], 2),
            "cache_read_usd": round(total_cost["cache_read_usd"], 2),
            "cache_create_usd": round(total_cost["cache_create_usd"], 2),
            "pricing_date": pricing_date,
            "note": "Hypothetical pay-as-you-go cost. Actual billing is Max plan fixed price.",
        },
        "histograms": {"hours": g["hours"], "weekdays": g["weekdays"], "weekday_hour": g["weekday_hour"]},
        "daily_activity": daily_activity,
        "top_tools": top_tools, "models": models, "projects": proj_rows,
    }


# --------------------------------------------------------------------------- #
# Competition head-to-head feed (separate from the all-time badge JSON)
#   competitor.json  = THIS person's aggregate only (a friend PULLs it, token-gated).
#   competition.json = me + every fetched peer, for my own /view + badge.
# Aggregate-only: NO prompt/response content, usernames or session IDs ever leave the box.
# Per-project NUMBERS + project NAMES are intentionally shared (drives the VERSUS › VS PROJECTS
# screen) — the competition is between trusted, opted-in friends who already know each other's
# projects; the names aren't a secret. "My total" spans all MY servers (folded via the ledger);
# a friend is a PEER kept side-by-side, never merged into my totals.
# --------------------------------------------------------------------------- #
# Rolling windows, in hours back from the current clock-hour (inclusive). Same tz on both
# competitors, so the window edges line up without UTC normalisation (see hourly note above).
COMPET_WINDOWS = [("24h", 24), ("7d", 168), ("30d", 720), ("all", None)]


def write_json_atomic(path, obj, pretty=False):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, indent=2 if pretty else None,
                  separators=None if pretty else (",", ":"))
    os.replace(tmp, path)


def aggregate_hourly(rows):
    """Sum every session's Option-B hourly buckets into one {datehour: {t,i,o,p,w}} map.
       `i` (input) is read with .get default 0 so buckets banked before it existed don't break."""
    agg = defaultdict(lambda: {"t": 0, "i": 0, "o": 0, "p": 0, "w": 0})
    for r in rows:
        for k, v in (r.get("hourly") or {}).items():
            a = agg[k]
            for f in ("t", "i", "o", "p", "w"):
                a[f] += v.get(f, 0) or 0
    return agg


def _window_cutoff(now_local, hours):
    if hours is None:
        return ""                                   # "" <= every key → all-time
    floor = now_local.replace(minute=0, second=0, microsecond=0)
    return (floor - timedelta(hours=hours - 1)).strftime("%Y-%m-%dT%H")


def read_bottleneck(path):
    """{datehour: seconds} of HUMAN BOTTLENECK time, from the durable bottleneck monitor's DB."""
    out = {}
    if not path or not os.path.exists(path):
        return out
    try:
        con = sqlite3.connect(path)
        for dh, sec in con.execute("SELECT datehour, seconds FROM bottleneck"):
            out[dh] = sec or 0
        con.close()
    except sqlite3.Error as e:
        warn("could not read bottleneck db %s (%s)" % (path, e))
    return out


def read_limits(path):
    """The session/weekly slice of claude-limits.json, folded into the competitor payload."""
    if not path:
        return None
    try:
        with open(path) as fh:
            d = json.load(fh)
    except Exception:
        return None
    return {"session": d.get("session"), "weekly": d.get("weekly"),
            "stale": d.get("stale"), "generated_at": d.get("generated_at"),
            # cumulative counts of distinct 5h/7d windows that ever hit >=90% (SESSION/WEEKLY PUSH trophies)
            "session_limit_hits": d.get("session_limit_hits", 0),
            "weekly_limit_hits": d.get("weekly_limit_hits", 0)}


def build_competitor_payload(rows, pricing, pricing_date, generated_at, cfg, bottleneck, limits):
    g = combine(rows)
    cost = cost_from_model_tokens(g["model_tokens"], pricing)
    total_tokens = g["tokens_total"]
    blended = (cost["total_usd"] / total_tokens) if total_tokens else 0.0  # $/token, all-time mix
    agg = aggregate_hourly(rows)
    now_local = datetime.now(TZ)

    windows = {}
    for name, hrs in COMPET_WINDOWS:
        cut = _window_cutoff(now_local, hrs)
        t = i = o = p = w = night = 0
        days = set()
        for k, v in agg.items():
            if k >= cut:
                t += v["t"]; i += v["i"]; o += v["o"]; p += v["p"]; w += v["w"]
                if int(k[11:13]) < 6:               # 00:00–05:59 local = "night owl" hours
                    night += v["t"]
                if v["t"] > 0:
                    days.add(k[:10])
        # night_owl_pct is a ratio over the hourly base — keep it on the hourly totals even for the
        # "all" window (the pre-ledger archive carries no hour-of-day, so it can't be apportioned).
        night_pct = round(night * 100.0 / t, 1) if t else 0.0
        # The "all" window must equal the badge's true all-time totals. Those come from combine() (`g`),
        # which sums the WHOLE ledger; the hourly buckets miss any row without an `hourly` map — notably
        # the pre-ledger seed/archive rows (recovered totals with no time detail). So for "all", source
        # the additive count fields from `g` so this column matches the TOKEN USAGE screen to the token;
        # leverage/cost below then recompute from the overridden totals and stay consistent. 24h/7d/30d
        # are untouched (the archive has no recent buckets, so it never contributed to them).
        if hrs is None:
            t, i, o = g["tokens_total"], g["tokens_input"], g["tokens_output"]
            p, w = g["user_prompts"], g["user_words"]
        bsec = sum(s for k, s in bottleneck.items() if k >= cut)
        windows[name] = {
            # tokens_total = all (in+out+cache); tokens_input/tokens_output enable the no-cache
            # "input+output" race. Consumers pick which to lead with.
            "tokens_total": t, "tokens_input": i, "tokens_output": o,
            "cost_usd": round(blended * t, 2),       # approx: blended all-time rate × window tokens
            "prompts": p, "words_typed": w, "active_days": len(days),
            "night_owl_pct": night_pct,
            "leverage_tokens_per_prompt": round(t / p) if p else 0,
            "bottleneck_sec": round(bsec),
        }

    # day-granular series (compact) for trend sparklines + so a peer can re-verify if it wants
    by_day = defaultdict(lambda: {"t": 0, "o": 0, "p": 0})
    for k, v in agg.items():
        d = by_day[k[:10]]
        d["t"] += v["t"]; d["o"] += v["o"]; d["p"] += v["p"]
    daily = [{"date": d, "tokens": by_day[d]["t"], "output": by_day[d]["o"],
              "prompts": by_day[d]["p"]} for d in sorted(by_day)][-30:]

    corpus_end = g["date_max"] or generated_at[:10]
    active_set = set()
    peak = ("", 0)
    peak_io = ("", 0)   # no-cache peak day (input+output), for the BIGBANG trophy (cache-independent)
    # all-time per-day personal bests (feed the /view avatar "NEW RECORD" celebration). Derived from
    # the same all-day `daily` table combine() already builds from banked per-session data → NO remote
    # update needed. (words/day come from the `hourly` map, so accurate only from ~ledger-start on.)
    rec_prompts = ("", 0); rec_words = ("", 0); rec_active = ("", 0); rec_sessions = ("", 0)
    for ds, cell in g["daily"].items():
        if cell["prompts"] > 0:
            active_set.add(date.fromisoformat(ds))
        if cell["tokens"] > peak[1]:
            peak = (ds, cell["tokens"])
        if cell.get("tokens_io", 0) > peak_io[1]:
            peak_io = (ds, cell["tokens_io"])
        if cell.get("prompts", 0) > rec_prompts[1]:
            rec_prompts = (ds, cell["prompts"])
        if cell.get("words", 0) > rec_words[1]:
            rec_words = (ds, cell["words"])
        if cell.get("active_min", 0) > rec_active[1]:
            rec_active = (ds, round(cell["active_min"]))
        if cell.get("sessions", 0) > rec_sessions[1]:
            rec_sessions = (ds, cell["sessions"])
    # most-expensive day (all-time): price each day's per-model token split. Accurate only for sessions
    # still banked with daily_model_tokens (~ledger-start on); remotes must ship it (see provision --update).
    rec_cost = ("", 0.0)
    for ds, mt in g.get("daily_model_tokens", {}).items():
        usd = cost_from_model_tokens(mt, pricing)["total_usd"]
        if usd > rec_cost[1]:
            rec_cost = (ds, usd)
    longest_streak, current_streak = longest_and_current_streak(active_set, corpus_end)

    metrics = {
        "current_streak": current_streak, "longest_streak": longest_streak,
        "peak_day": {"date": peak[0], "tokens": peak[1]},
        "peak_day_io": {"date": peak_io[0], "tokens": peak_io[1]},
        "record_day_prompts": {"date": rec_prompts[0], "value": rec_prompts[1]},
        "record_day_words": {"date": rec_words[0], "value": rec_words[1]},
        "record_day_active_min": {"date": rec_active[0], "value": rec_active[1]},
        "record_day_sessions": {"date": rec_sessions[0], "value": rec_sessions[1]},
        "record_day_cost": {"date": rec_cost[0], "usd": round(rec_cost[1], 2)},
        "endurance_longest_session_min": g["longest_session_min"],
        "sessions": g["sessions"], "work_sessions": g["work_sessions"],
        "active_days": g["active_days"], "total_active_min": g["total_active_min"],
        "nightowl_active_min": g["nightowl_active_min"], "user_chars_typed": g["user_chars_typed"],
        "words_typed_total": g["user_words"], "prompts_total": g["user_prompts"],
        "tokens_total_all": total_tokens, "tokens_output_all": g["tokens_output"],
        "agents_total": g["tool_counts"].get("Agent", 0),
        "tool_uses": sum(g["tool_counts"].values()),
        "cost_usd_all": round(cost["total_usd"], 2),
        "cache_hit_ratio": round(g["tokens_cache_read"] / (g["tokens_cache_read"] +
                                 g["tokens_cache_create"] + g["tokens_input"]), 4)
        if (g["tokens_cache_read"] + g["tokens_cache_create"] + g["tokens_input"]) else 0.0,
        "bottleneck_sec_total": round(sum(bottleneck.values())),
    }

    # Per-project breakdown (names + numbers), so a peer can render our PROJECTS screen head-to-head
    # (VERSUS › VS PROJECTS). Project NAMES are intentionally shared in the competition — the only one
    # who sees them is a trusted friend you've opted into, who already knows your projects. Still NO
    # prompt/response content, usernames, or session IDs leave the box. Grouped by project name only
    # (summed across this competitor's servers) to match the badge's own PROJECTS screen rows.
    proj_groups = defaultdict(list)
    for r in rows:
        proj_groups[r.get("name") or ""].append(r)
    projects = []
    for nm, grp in proj_groups.items():
        pg = combine(grp)
        pc = cost_from_model_tokens(pg["model_tokens"], pricing)
        projects.append({
            "name": nm, "tokens_total": pg["tokens_total"],
            "tokens_input": pg["tokens_input"], "tokens_output": pg["tokens_output"],
            "cost_estimate_usd": round(pc["total_usd"], 2),
            "user_prompts": pg["user_prompts"], "user_words": pg["user_words"],
            "total_active_min": pg["total_active_min"],
            "agent_launches": pg["tool_counts"].get("Agent", 0),
        })
    projects.sort(key=lambda r: r["tokens_total"], reverse=True)

    return {
        "schema_version": SCHEMA_VERSION, "kind": "competitor",
        "alias": (cfg.get("alias") or "anon").strip() or "anon",
        "generated_at": generated_at, "timezone": TZ_NAME,
        "corpus_start": g["date_min"], "corpus_end": g["date_max"],
        "windows": windows, "metrics": metrics, "daily": daily, "projects": projects,
        "limits": limits, "pricing_date": pricing_date,
    }


def _peer_slug(peer, url):
    s = peer.get("name") or url
    return (re.sub(r"[^A-Za-z0-9_-]+", "-", s).strip("-")[:40]) or "peer"


# A peer's competitor.json is numbers-only (~4 KB in practice); cap the pull so a compromised or
# malicious peer can't stream gigabytes into the root competitor cron (memory / disk DoS).
MAX_PEER_BYTES = 4 * 1024 * 1024


def fetch_peers(cfg, peers_dir, generated_at):
    """PULL each configured peer's competitor.json over HTTPS (token in query). Cache the last-good
    copy on disk so a peer being briefly down keeps showing its last-known numbers (flagged stale)."""
    peers = []
    if peers_dir:
        os.makedirs(peers_dir, exist_ok=True)
    for peer in (cfg.get("peers") or []):
        url = (peer or {}).get("url")
        if not url:
            continue
        token = peer.get("token")
        slug = _peer_slug(peer, url)
        dest = os.path.join(peers_dir, slug + ".json") if peers_dir else None
        full = url
        if token:
            full += ("&" if "?" in url else "?") + "token=" + urllib.parse.quote(str(token), safe="")
        data, err = None, None
        try:
            req = urllib.request.Request(
                full, headers={"User-Agent": "ccstats-peer-fetch/1", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read(MAX_PEER_BYTES + 1)
                if len(raw) > MAX_PEER_BYTES:
                    raise ValueError("peer payload exceeded %d-byte cap" % MAX_PEER_BYTES)
                data = json.loads(raw.decode("utf-8"))
            if dest:
                write_json_atomic(dest, data)
        except Exception as e:
            err = "%s: %s" % (type(e).__name__, e)
            warn("peer fetch failed for %s (%s)" % (url, err))
            if dest and os.path.exists(dest):
                try:
                    data = json.load(open(dest))
                except Exception:
                    data = None
        if data is None:
            data = {"kind": "competitor", "alias": peer.get("name") or slug}
        data = dict(data)
        data["_fetch"] = {"ok": err is None, "error": err, "fetched_at": generated_at}
        peers.append(data)
    return peers


# --------------------------------------------------------------------------- #
# Avatar celebration directives (record-breaks + trophy tier-ups) — M4b
# --------------------------------------------------------------------------- #
# Server-side milestone detection for the badge: snapshot {records, trophy tiers}, diff it on
# each competitor-mode run (~2 min cron), and publish short-lived "celebrate" events that
# live-monitor.py folds into live-status.json (the badge's ~2 s channel). Mirrors /view's
# detectMilestones() + trophyEval() in viewscreens/screens.js — keep the two in sync:
#   * first run SEEDS SILENTLY (no celebration storm); a brand-new key also seeds silently
#     (slightly safer than the web, which celebrates a never-seen trophy family immediately);
#   * a record that is ALSO a trophy tier-up celebrates as the trophy only;
#   * the snapshot keeps max(prev, current) so a transient data dip (e.g. a missing
#     claude-limits.json reading 0 limit hits) can never re-celebrate on recovery.
# Detection runs main-side only, from already-aggregated data → needs NO remote update.
MILESTONES_STATE_DEFAULT  = "/opt/claude-stats/milestones.json"
CELEBRATIONS_FILE_DEFAULT = "/opt/claude-stats/celebrations.json"
CELEBRATION_WINDOW_SEC = 180          # badge celebrates ~3 min per event (matches /view's window)
CELEB_TIER_NAMES = ("LOCKED", "COMMON", "RARE", "EPIC", "LEGENDARY")

# Badge-facing value formatters (ASCII; ALL-CAPS-safe). Match /view's TFMT family, except usd:
# the badge renders USD as grouped whole dollars ("$2,812"), per the firmware contract.
def _trim0(s):
    return s[:-2] if s.endswith(".0") else s


def _fmt_tokens(n):
    n = n or 0
    if n >= 1e9: return _trim0("%.1f" % (n / 1e9)) + "B"
    if n >= 1e6: return _trim0("%.1f" % (n / 1e6)) + "M"
    if n >= 1e3: return "%dK" % round(n / 1e3)
    return "%d" % round(n)


def _fmt_compact(n):
    n = n or 0
    if n >= 1e9: return _trim0("%.1f" % (n / 1e9)) + "B"
    if n >= 1e6: return _trim0("%.1f" % (n / 1e6)) + "M"
    if n >= 1e3: return _trim0("%.1f" % (n / 1e3)) + "K"
    return "%d" % round(n)


def _fmt_min(minutes):
    minutes = max(0, round(minutes or 0))
    h, m = divmod(minutes, 60)
    return "%dH %02dM" % (h, m) if h else "%dM" % m


def _fmt_dur(sec):
    sec = max(0, round(sec or 0))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h: return "%dH %02dM" % (h, m)
    if m: return "%dM %02dS" % (m, s)
    return "%dS" % s


CELEB_FMT = {
    "tokens": _fmt_tokens, "compact": _fmt_compact, "min": _fmt_min, "dur": _fmt_dur,
    "int": lambda n: format(int(round(n or 0)), ","),
    "day": lambda n: "%dD" % round(n or 0),
    "usd": lambda n: "$" + format(int(round(n or 0)), ","),
}

# Trophy families — value sources + tier thresholds ported from TROPHY_FAMILIES in
# viewscreens/screens.js (key, label, thresholds [common, rare, epic, legendary], value fn).
# Value fns read the just-built competitor payload (windows.all == true all-time totals).
CELEB_TROPHIES = (
    ("titan",      "TOKENS",   (1e6, 1e7, 2.5e7, 1e8),              lambda w, m, l: (w.get("tokens_input") or 0) + (w.get("tokens_output") or 0)),
    ("prompter",   "PROMPTS",  (100, 1000, 2500, 10000),            lambda w, m, l: w.get("prompts") or 0),
    ("novelist",   "WORDS",    (10000, 50000, 250000, 500000),      lambda w, m, l: w.get("words_typed") or 0),
    ("chars",      "CHARS",    (50000, 250000, 500000, 2000000),    lambda w, m, l: m.get("user_chars_typed") or 0),
    ("relentless", "STREAK",   (3, 14, 30, 60),                     lambda w, m, l: m.get("longest_streak") or 0),
    ("regular",    "ACTIVE",   (7, 30, 120, 270),                   lambda w, m, l: m.get("active_days") or 0),
    ("marathon",   "MARATHON", (60, 180, 360, 540),                 lambda w, m, l: m.get("endurance_longest_session_min") or 0),
    ("grinder",    "GRIND",    (480, 4800, 24000, 48000),           lambda w, m, l: m.get("total_active_min") or 0),
    ("owl",        "NIGHTOWL", (300, 1500, 6000, 15000),            lambda w, m, l: m.get("nightowl_active_min") or 0),
    ("toolsmith",  "TOOLS",    (1000, 10000, 50000, 100000),        lambda w, m, l: m.get("tool_uses") or 0),
    ("bigbang",    "BIGBANG",  (100000, 500000, 1000000, 2000000),  lambda w, m, l: (m.get("peak_day_io") or {}).get("tokens") or 0),
    ("bottleneck", "BOTTLE",   (900, 3600, 18000, 54000),           lambda w, m, l: m.get("bottleneck_sec_total") or 0),
    ("sesspush",   "SESSION",  (1, 6, 30, 60),                      lambda w, m, l: l.get("session_limit_hits") or 0),
    ("weekpush",   "WEEKLY",   (1, 3, 10, 25),                      lambda w, m, l: l.get("weekly_limit_hits") or 0),
)

# Records watched — keys/labels/format + the trophy family whose tier-up makes the record
# implicit (REC_META in screens.js). Value fns read the competitor payload's metrics block.
CELEB_RECORDS = (
    ("streak",      "LONGEST STREAK",   "day",     "relentless", lambda m: m.get("longest_streak") or 0),
    ("endurance",   "ENDURANCE",        "min",     "marathon",   lambda m: m.get("endurance_longest_session_min") or 0),
    ("peakIo",      "BIGGEST DAY",      "tokens",  "bigbang",    lambda m: (m.get("peak_day_io") or {}).get("tokens") or 0),
    ("dayPrompts",  "MOST PROMPTS/DAY", "int",     None,         lambda m: (m.get("record_day_prompts") or {}).get("value") or 0),
    ("dayWords",    "MOST WORDS/DAY",   "compact", None,         lambda m: (m.get("record_day_words") or {}).get("value") or 0),
    ("dayActive",   "BUSIEST DAY",      "min",     None,         lambda m: (m.get("record_day_active_min") or {}).get("value") or 0),
    ("daySessions", "MOST SESSIONS/DAY","int",     None,         lambda m: (m.get("record_day_sessions") or {}).get("value") or 0),
    ("dayCost",     "PRICIEST DAY",     "usd",     None,         lambda m: (m.get("record_day_cost") or {}).get("usd") or 0),
)


def detect_celebrations(mine, state_path, celebrations_path):
    """Diff current records/trophy tiers against the persisted snapshot; emit celebrate events."""
    windows_all = (mine.get("windows") or {}).get("all") or {}
    metrics = mine.get("metrics") or {}
    limits = mine.get("limits") or {}
    records = {key: fn(metrics) for key, _lbl, _fmt, _fam, fn in CELEB_RECORDS}
    tiers = {}
    for key, _lbl, thresholds, fn in CELEB_TROPHIES:
        v = fn(windows_all, metrics, limits) or 0
        tiers[key] = sum(1 for t in thresholds if v >= t)

    try:
        with open(state_path) as fh:
            state = json.load(fh)
    except Exception:
        state = {}
    now_utc = datetime.now(timezone.utc)
    stamp = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    expires = (now_utc + timedelta(seconds=CELEBRATION_WINDOW_SEC)).strftime("%Y-%m-%dT%H:%M:%SZ")

    events = []
    if state.get("seeded"):
        prev_records = state.get("records") or {}
        prev_tiers = state.get("tiers") or {}
        tiered_up = set()
        for key, label, _thr, _fn in CELEB_TROPHIES:
            prev = prev_tiers.get(key)
            if prev is None:                    # brand-new family → seed silently
                continue
            if tiers[key] > prev:
                tiered_up.add(key)
                events.append({"id": "trophy-%s-%s" % (key, stamp), "kind": "trophy",
                               "label": label, "detail": CELEB_TIER_NAMES[min(4, tiers[key])],
                               "expires_at": expires})
        for key, label, fmt, family, _fn in CELEB_RECORDS:
            prev = prev_records.get(key)
            if prev is None:                    # brand-new record key → seed silently
                continue
            if records[key] > prev and family not in tiered_up:   # trophy covers the overlap
                events.append({"id": "rec-%s-%s" % (key, stamp), "kind": "record",
                               "label": label, "detail": CELEB_FMT[fmt](records[key]),
                               "expires_at": expires})
        # snapshot keeps the running MAX so a transient dip can never re-celebrate on recovery
        records = {k: max(records[k], prev_records.get(k) or 0) for k in records}
        tiers = {k: max(tiers[k], prev_tiers.get(k) or 0) for k in tiers}

    write_json_atomic(state_path, {"seeded": True, "records": records, "tiers": tiers,
                                   "updated_at": stamp})
    if events:
        # merge with still-unexpired events from a previous run (badge dedupes by id)
        try:
            with open(celebrations_path) as fh:
                for e in (json.load(fh).get("events") or []):
                    exp = str(e.get("expires_at", "")).replace("Z", "+00:00")
                    try:
                        if datetime.fromisoformat(exp) > now_utc:
                            events.append(e)
                    except ValueError:
                        pass
        except Exception:
            pass
        write_json_atomic(celebrations_path, {"generated_at": stamp, "events": events})
        for e in events:
            print("celebrate: %s %s %s (until %s)" % (e["kind"], e["label"], e.get("detail", ""),
                                                      e["expires_at"]))


def run_competitor(args, generated_at):
    cfg = load_config(args.config)
    pricing, pricing_date = load_pricing(args.pricing)
    con = open_ledger(args.ledger)                  # read-only: never mutate the ledger here
    rows = load_ledger_rows(con)
    con.close()
    bottleneck = read_bottleneck(args.bottleneck_db)
    limits = read_limits(args.limits_file)
    mine = build_competitor_payload(rows, pricing, pricing_date, generated_at, cfg, bottleneck, limits)
    try:
        detect_celebrations(mine, args.milestones_file, args.celebrations_file)
    except Exception as e:
        warn("celebration detection failed (%s)" % e)   # never let it break the feed
    if args.output:
        write_json_atomic(args.output, mine, args.pretty)
        print("wrote %s (mode=competitor, alias=%s)" % (args.output, mine["alias"]))
    peers = fetch_peers(cfg, args.peers_dir, generated_at)
    combined = {"schema_version": SCHEMA_VERSION, "kind": "competition",
                "generated_at": generated_at, "me": mine, "peers": peers}
    if args.competition_output:
        write_json_atomic(args.competition_output, combined, args.pretty)
        print("wrote %s (%d peer(s))" % (args.competition_output, len(peers)))
    return combined


# --------------------------------------------------------------------------- #
# Collect local sessions → records
# --------------------------------------------------------------------------- #
def collect_local_records(home_glob, server, mode="user"):
    """Return (recs, meta): recs[key]=parsed records; meta[key]=(server,user,project,sessions_flag).
       `mode` ('user'|'directory') picks the project granularity — see project_name()."""
    recs, meta = {}, {}
    for user, name, projdir in discover_projects(home_glob):
        for sid, files, has_top in group_files(projdir):
            key = f"{server}:{sid}"
            parsed = parse_session_records(files)
            parsed["_sid"] = sid
            recs[key] = parsed
            pname = project_name(mode, name, parsed.get("cwd"))
            meta[key] = (server, user, pname, 1 if has_top else 0)
    return recs, meta


# --------------------------------------------------------------------------- #
# Seed (one-time pre-ledger archive)
# --------------------------------------------------------------------------- #
def seed_archive(con, server, now):
    live = [r for r in load_ledger_rows(con) if not r["_archive"]]
    inserted = []
    for project, peak in PRELEDGER_PEAK.items():
        key = f"archive:{server}:{project}"
        if con.execute("SELECT 1 FROM sessions WHERE session_id=?", (key,)).fetchone():
            continue
        cur = combine([r for r in live if r["server"] == server and r["name"] == project])
        delta = max(0, peak["tokens_total"] - cur["tokens_total"])
        if delta <= 0 or cur["tokens_total"] <= 0:
            continue
        ratio = delta / cur["tokens_total"]
        cats = {k: int(round(cur[k] * ratio)) for k in
                ("tokens_input", "tokens_output", "tokens_cache_read", "tokens_cache_create")}
        mtok = {m: {kk: int(round(v.get(kk, 0) * ratio)) for kk in
                    ("input", "output", "cache_read", "cache_create", "turns")}
                for m, v in cur["model_tokens"].items()}
        mcount = {m: int(round(c * ratio)) for m, c in cur["model_counts"].items()}
        metrics = {
            **cats, "tokens_total": sum(cats.values()),
            "user_words": max(0, peak.get("user_words", 0) - cur["user_words"]),
            "user_chars": 0, "user_chars_typed": 0,
            "user_prompts": max(0, peak.get("user_prompts", 0) - cur["user_prompts"]),
            "sessions": max(0, peak.get("sessions", 0) - cur["sessions"]),
            "work_sessions": max(0, peak.get("work_sessions", 0) - cur["work_sessions"]),
            "total_active_min": 0, "longest_session_min": 0, "active_days": 0,
            "tool_counts": {}, "model_counts": mcount, "model_tokens": mtok,
            "daily_activity": [], "hours_histogram": [0] * 24, "weekdays_histogram": [0] * 7,
            "date_min": None, "date_max": None, "last_active": cur.get("last_active"),
            "session_id": key, "preledger_archive": True,
        }
        con.execute("""INSERT INTO sessions
            (session_id,server,username,project,first_seen,last_seen,last_active,alive,is_archive,metrics)
            VALUES(?,?,?,?,?,?,?,0,1,?)""",
            (key, server, peak.get("username"), project, now, now, metrics["last_active"], json.dumps(metrics)))
        inserted.append((project, metrics["tokens_total"], metrics["sessions"]))
    con.commit()
    return inserted


# --------------------------------------------------------------------------- #
# Backups — timestamped, retained restore points for the durable state.
#
# A snapshot is ONE timestamped directory under backups/ holding a consistent set: ledger.db +
# bottleneck.db (copied via SQLite's online backup API, so the copy is consistent even while the
# 5-min/2-min crons hold the db open) plus config.json/token.txt/peer-token.txt (plain copies —
# tiny, but painful to re-create: peers + the badge/peer tokens).
#
# Retention is GRANDFATHER-FATHER-SON (two tiers; see _prune_backups):
#   - SON    : keep EVERY snapshot from the last BACKUP_SON_WINDOW (24h) — fine-grained same-day
#              rollback. The full run takes one whenever the newest is older than BACKUP_SON_INTERVAL
#              (3h → ~8 intra-day points/day; the gate is TIME-based, so cron density doesn't matter).
#   - FATHER : for snapshots older than the 24h window, keep only the NEWEST one per calendar day,
#              going back BACKUP_DAILY_DAYS (30) days; prune the rest.
# Net: fine recovery granularity for the last day + a month of daily restore points.
#
# Two triggers: a forced pre-deploy snapshot (--mode backup, from deploy.sh) and the age-gated
# son-tier snapshot from the 5-min full run (so non-deploy corruption is covered too, without
# churning generations every run). The cheap rolling ledger.db.bak stays for instant one-step undo.
# Restore is always MANUAL: stop the crons, copy a snapshot dir's files back, restart.
# --------------------------------------------------------------------------- #
DEFAULT_BACKUPS_DIR = "/opt/claude-stats/backups"
DEFAULT_BOTTLENECK_DB = "/opt/claude-stats/bottleneck.db"
BACKUP_SON_INTERVAL = timedelta(hours=3)   # full-run age-gate: min spacing between intra-day snapshots
BACKUP_SON_WINDOW = timedelta(hours=24)    # son tier: keep ALL snapshots newer than this
BACKUP_DAILY_DAYS = 30                     # father tier: keep newest-per-day for this many days
BACKUP_KEEP = 10                           # deprecated — kept only so a legacy --backup-keep arg is a no-op
BACKUP_DIR_FMT = "%Y-%m-%dT%H-%M-%S"  # ':' isn't filename-safe; still sorts lexicographically


def _online_backup(src_path, dst_path):
    """Consistent SQLite snapshot via the online backup API (safe under concurrent writers)."""
    src = sqlite3.connect(src_path)
    try:
        dst = sqlite3.connect(dst_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _snapshot_dirs(backups_dir):
    """Existing snapshot dir names (well-formed timestamps only), sorted oldest -> newest."""
    out = []
    try:
        entries = os.listdir(backups_dir)
    except OSError:
        return out
    for name in entries:
        try:
            datetime.strptime(name, BACKUP_DIR_FMT)
        except ValueError:
            continue  # ignore anything that isn't one of our snapshot dirs
        if os.path.isdir(os.path.join(backups_dir, name)):
            out.append(name)
    return sorted(out)


def _prune_backups(backups_dir, now=None):
    """Grandfather-father-son prune. Keep set = every snapshot within BACKUP_SON_WINDOW (son tier,
    fine-grained recent history) UNION the newest snapshot per calendar day within BACKUP_DAILY_DAYS
    (father tier); delete everything else. Snapshot dir names sort chronologically, so the last name
    seen for a given day is that day's newest."""
    now = now or datetime.now(TZ)
    dirs = _snapshot_dirs(backups_dir)  # oldest -> newest
    keep = set()
    newest_per_day = {}
    for name in dirs:
        ts = datetime.strptime(name, BACKUP_DIR_FMT).replace(tzinfo=TZ)
        if now - ts < BACKUP_SON_WINDOW:
            keep.add(name)                       # son tier: everything in the last 24h
        newest_per_day[ts.date()] = name         # later names overwrite -> ends as the day's newest
    cutoff_day = (now - timedelta(days=BACKUP_DAILY_DAYS)).date()
    for day, name in newest_per_day.items():
        if day > cutoff_day:                     # father tier: newest-per-day within the last 30 days
            keep.add(name)
    for name in dirs:
        if name not in keep:
            shutil.rmtree(os.path.join(backups_dir, name), ignore_errors=True)


def _latest_backup_age(backups_dir):
    dirs = _snapshot_dirs(backups_dir)
    if not dirs:
        return None
    ts = datetime.strptime(dirs[-1], BACKUP_DIR_FMT).replace(tzinfo=TZ)
    return datetime.now(TZ) - ts


def snapshot_backup(ledger, bottleneck_db, config_path, backups_dir):
    """Write one timestamped snapshot dir (consistent ledger + bottleneck via online backup, plus
    config/token plain copies) and run the grandfather-father-son prune. Returns the path, or None
    if nothing existed to back up (e.g. a fresh install)."""
    dest = os.path.join(backups_dir, datetime.now(TZ).strftime(BACKUP_DIR_FMT))
    os.makedirs(dest, exist_ok=True)
    for d in (backups_dir, dest):
        try:
            os.chmod(d, 0o700)  # root-only: snapshots hold token copies
        except OSError:
            pass
    backed = []
    for src in (ledger, bottleneck_db):
        if src and os.path.exists(src):
            try:
                _online_backup(src, os.path.join(dest, os.path.basename(src)))
                backed.append(os.path.basename(src))
            except (sqlite3.Error, OSError) as e:
                warn("backup of %s failed (%s)" % (src, e))
    cfg = config_path or _CONFIG_PATH
    cfg_base = os.path.dirname(cfg) or os.path.dirname(DEFAULT_BACKUPS_DIR)
    for src in (cfg, os.path.join(cfg_base, "token.txt"), os.path.join(cfg_base, "peer-token.txt")):
        if os.path.exists(src):
            try:
                d = os.path.join(dest, os.path.basename(src))
                shutil.copy2(src, d)
                os.chmod(d, 0o600)  # config/tokens are secrets — keep them locked down
                backed.append(os.path.basename(src))
            except OSError as e:
                warn("backup of %s failed (%s)" % (src, e))
    if not backed:
        shutil.rmtree(dest, ignore_errors=True)  # nothing to keep (fresh install) — drop empty dir
        return None
    _prune_backups(backups_dir)
    return dest


def maybe_snapshot(args):
    """Age-gated son-tier snapshot for the 5-min full run: snapshot only if the newest is older than
    BACKUP_SON_INTERVAL (or none exists), giving ~8 intra-day restore points/day. deploy.sh also
    forces one via --mode backup before each update. Retention is grandfather-father-son
    (see _prune_backups)."""
    backups_dir = getattr(args, "backups_dir", None) or DEFAULT_BACKUPS_DIR
    age = _latest_backup_age(backups_dir)
    if age is not None and age < BACKUP_SON_INTERVAL:
        return
    dest = snapshot_backup(args.ledger,
                           getattr(args, "bottleneck_db", None) or DEFAULT_BOTTLENECK_DB,
                           getattr(args, "config", None),
                           backups_dir)
    if dest:
        print("snapshot: %s" % dest)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def run_full(args, generated_at):
    pricing, pricing_date = load_pricing(args.pricing)
    if os.path.exists(args.ledger):
        try:
            shutil.copy2(args.ledger, args.ledger + ".bak")  # cheap rolling one-step undo
            try:
                os.chmod(args.ledger + ".bak", 0o600)  # the .bak holds the same detail — lock it down too
            except OSError:
                pass
        except OSError as e:
            warn("ledger backup failed (%s)" % e)
        maybe_snapshot(args)  # retained son-tier snapshot (age-gated 3h; GFS retention — see Backups above)
    con = open_ledger(args.ledger)

    recs, meta = collect_local_records(args.home_glob, args.server, args.project_granularity)
    owner = load_record_owner(con)
    metrics_by_key, new_assign = build_session_metrics(recs, owner)
    persist_record_owner(con, new_assign)

    seen, processed = set(), set()
    for key, m in metrics_by_key.items():
        srv, user, name, sess_flag = meta[key]
        m["session_id"] = recs[key]["_sid"]
        m["sessions"] = sess_flag
        upsert_row(con, key, srv, user, name, m, generated_at)
        seen.add(key); processed.add(srv)

    # remote fragments carry pre-aggregated per-session metrics (cross-dedup done on the remote)
    if args.fragments_dir and os.path.isdir(args.fragments_dir):
        for ff in sorted(glob.glob(os.path.join(args.fragments_dir, "*.json"))):
            try:
                data = json.load(open(ff))
            except Exception as e:
                warn("skipping unreadable fragment %s (%s)" % (ff, e)); continue
            srv = data.get("server", os.path.splitext(os.path.basename(ff))[0])
            for s in data.get("sessions", []):
                sid = s.get("session_id")
                if not sid:
                    continue
                upsert_row(con, f"{srv}:{sid}", srv, s.get("username"), s.get("project"),
                           s.get("metrics", {}), generated_at)
                seen.add(f"{srv}:{sid}"); processed.add(srv)

    mark_absent(con, processed, seen, generated_at)
    con.commit()
    rows = load_ledger_rows(con)
    con.close()
    return aggregate(rows, pricing, pricing_date, generated_at)


def build_fragment(home_glob, server, generated_at, mode="user"):
    """Per-session rows for a remote→main handoff (within-run cross-dedup, no persistence here)."""
    recs, meta = collect_local_records(home_glob, server, mode)
    metrics_by_key, _ = build_session_metrics(recs, {})
    sessions = []
    for key, m in metrics_by_key.items():
        srv, user, name, sess_flag = meta[key]
        m["session_id"] = recs[key]["_sid"]; m["sessions"] = sess_flag
        sessions.append({"session_id": m["session_id"], "username": user, "project": name, "metrics": m})
    return {"server": server, "generated_at": generated_at, "sessions": sessions}


def main():
    ap = argparse.ArgumentParser(description="Claude Code usage stats extractor (+ all-time ledger)")
    ap.add_argument("--mode", choices=["fragment", "full", "seed", "competitor", "backup"], required=True)
    ap.add_argument("--server", default=None)  # required for data modes; unused by --mode backup
    ap.add_argument("--output")
    ap.add_argument("--fragments-dir", default=None)
    ap.add_argument("--pricing", default="/opt/claude-stats/pricing.json")
    ap.add_argument("--ledger", default=DEFAULT_LEDGER)
    ap.add_argument("--home-glob", default="/home/*")
    ap.add_argument("--project-granularity", choices=["user", "directory"], default=None,
                    help="how to split projects (full/fragment modes): 'user' (default) = one project "
                         "per Linux user; 'directory' = one project per Claude Code working dir. "
                         "Overrides config.json's project_granularity. See docs/projects-layout.md.")
    ap.add_argument("--pretty", action="store_true")
    # --mode competitor extras (head-to-head feed):
    ap.add_argument("--config", default=None, help="per-machine config.json (alias, peers)")
    ap.add_argument("--limits-file", default=None, help="claude-limits.json to fold into the feed")
    ap.add_argument("--bottleneck-db", default=None, help="durable HUMAN BOTTLENECK seconds DB")
    ap.add_argument("--peers-dir", default=None, help="cache dir for fetched peer payloads")
    ap.add_argument("--competition-output", default=None, help="combined me+peers JSON for /view")
    ap.add_argument("--milestones-file", default=MILESTONES_STATE_DEFAULT,
                    help="persisted {records, trophy tiers} snapshot for celebration detection")
    ap.add_argument("--celebrations-file", default=CELEBRATIONS_FILE_DEFAULT,
                    help="celebrate-directive queue read by live-monitor.py into live-status.json")
    # --mode backup (also drives the age-gated son-tier snapshot inside --mode full):
    ap.add_argument("--backups-dir", default=DEFAULT_BACKUPS_DIR, help="dir for timestamped snapshots")
    ap.add_argument("--backup-keep", type=int, default=BACKUP_KEEP,
                    help="DEPRECATED no-op: retention is now grandfather-father-son (24h fine + 30 daily)")
    args = ap.parse_args()
    if args.mode != "backup" and not args.server:
        ap.error("--server is required for mode=%s" % args.mode)

    # Resolve per-machine config once (honors --config): timezone drives all bucketing; granularity
    # picks how sessions group into projects. Module-level TZ defaulted from the standard path; this
    # makes an explicit --config win too.
    global TZ, TZ_NAME
    _cfg = load_config(args.config)
    TZ_NAME, TZ = _resolve_tz(_cfg)
    # Project granularity: CLI flag wins; else config.json's project_granularity; else "user"
    # (the unchanged one-project-per-Linux-user default). Only full/fragment modes consume it.
    if args.project_granularity is None:
        args.project_granularity = (_cfg.get("project_granularity") or "user")
    if args.project_granularity not in ("user", "directory"):
        ap.error("project_granularity must be 'user' or 'directory' (got %r)" % args.project_granularity)

    generated_at = datetime.now(TZ).isoformat(timespec="seconds")

    if args.mode == "backup":
        dest = snapshot_backup(args.ledger, args.bottleneck_db or DEFAULT_BOTTLENECK_DB,
                               args.config, args.backups_dir)
        print("snapshot:", dest or "(nothing to back up)")
        return

    if args.mode == "seed":
        con = open_ledger(args.ledger)
        print("seeded archive rows:", seed_archive(con, args.server, generated_at) or "(none)")
        con.close()
        return

    if args.mode == "competitor":
        run_competitor(args, generated_at)
        return

    result = build_fragment(args.home_glob, args.server, generated_at, args.project_granularity) \
        if args.mode == "fragment" else run_full(args, generated_at)

    if not args.output:
        sys.exit("--output required for mode=%s" % args.mode)
    tmp = args.output + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(result, fh, indent=2 if args.pretty else None,
                  separators=None if args.pretty else (",", ":"))
    os.replace(tmp, args.output)
    print("wrote %s (mode=%s)" % (args.output, args.mode))


if __name__ == "__main__":
    main()
