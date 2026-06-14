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

"""Claude Code session/weekly limit poller for the Tufty badge.

Claude Code never persists rate-limit/quota data to disk — it reads it live from
the OAuth endpoint that powers `/usage`:

    GET https://api.anthropic.com/api/oauth/usage
    Authorization: Bearer <accessToken>

The response carries exactly what the badge's CLAUDE MONITOR screen needs:

    { "five_hour": {"utilization": 23.0, "resets_at": "...Z"},
      "seven_day": {"utilization": 12.0, "resets_at": "...Z"},
      "seven_day_opus": {...}|null, "seven_day_sonnet": {...}|null,
      "extra_usage": {"is_enabled": true, "used_credits": 0.0,
                      "monthly_limit": 3000, "currency": "EUR"} }

`five_hour` -> SESSION, `seven_day` -> WEEKLY (utilization is a percentage).

Token handling (the one subtlety): the OAuth accessToken in
~/.claude/.credentials.json is short-lived (~minutes) and Claude Code refreshes
it automatically *while it runs*. We therefore NEVER refresh it ourselves (two
refreshers fighting over the rotating refresh token would break Claude Code).
Instead we read the freshest accessToken straight from disk each run. All Linux
users on this box share ONE Anthropic account (zapador@zapador.net), and limits are
global per account, so any of their credential files returns the same numbers —
we just pick whichever token is least likely to be expired (latest expiresAt).

If no usable token is found / the call fails, we keep the last-known
utilization & reset timestamps and flag `stale: true`. That is correct: a reset
time is absolute, and utilization only moves while a session is active (= Claude
Code running = a fresh token available), so a stale read never hides real change.

Run as root (to read every user's 0600 credentials) every ~2 min from cron:

    */2 * * * * /usr/bin/python3 /opt/claude-stats/usage-monitor.py \
        --output /var/www/stats/claude-limits.json >>/var/log/claude-stats-limits.log 2>&1
"""

import argparse
import glob
import json
import os
import pwd
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
# Timezone for log lines + the published generated_at — read from the per-machine config.json (UTC if
# absent/invalid), matching the rest of the pipeline. Never hardcoded.
_CONFIG_PATH = os.environ.get("CCSTATS_CONFIG", "/opt/claude-stats/config.json")


def _tz():
    try:
        with open(_CONFIG_PATH) as fh:
            name = (json.load(fh).get("timezone") or "UTC").strip() or "UTC"
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("UTC")


LOCAL_TZ = _tz()
SCHEMA_VERSION = 1
HTTP_TIMEOUT = 15
# Where to look for credential files. Each user's ~/.claude/.credentials.json.
CRED_GLOB = "/home/*/.claude/.credentials.json"

# --- "don't hammer the endpoint with a dead token" gating (shared by main + remotes) ---------------
# A Claude Code OAuth accessToken is only kept fresh WHILE Claude Code runs (it refreshes it itself).
# So `expiresAt in the future` is the exact "is this worth a call" signal: once every local token is
# past expiry, nobody is active on this box, the call would only 429/401, and we must NOT make it — we
# go quiet and let whichever server DOES have a fresh token supply the reading (via --merge-dir). This
# is what stops the box you're NOT working on from pointlessly polling with hours-old tokens.
EXPIRY_SKEW_MS = 120_000            # tolerate this much clock skew: only skip a token expired by >2 min
# A token that LOOKS valid (future expiry) but still gets 401/403/429 (broken refresh chain) is backed
# off per-source — 2 min → 4 → 8 … capped at 30 min — instead of retried every cron. The backoff is
# invalidated the instant the token's expiresAt advances (Claude Code refreshed it = a new token =
# give it an immediate fresh try), so recovery is instant when a session resumes.
BACKOFF_BASE_MS = 120_000           # first backoff after an auth failure (= one 2-min cron interval)
BACKOFF_CAP_MS  = 1_800_000         # never back off longer than 30 min (stays resilient, never dead-stops)
AUTH_FAIL_CODES = (401, 403, 429)   # HTTP codes that mean "this token is no good" → back it off
DEFAULT_POLL_STATE = "/opt/claude-stats/usage-poll-state.json"   # per-source backoff bookkeeping
# --- multi-server merge (main only): fold readings shipped up by same-account remotes -------------
# Rate limits are GLOBAL per Anthropic account and this whole system runs ONE account, so a reading
# taken on ANY server is the same global truth. Main therefore serves the freshest non-stale reading
# across {its own local poll} ∪ {remotes' shipped files}, so the feed stays live whenever a session is
# active ANYWHERE — not only on this box. A remote file older than this (remote stopped shipping) is
# ignored as stale.
MERGE_MAX_AGE_S = 360               # a remote-shipped reading older than 6 min can't be "fresh"


def log(msg):
    ts = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def now_ms():
    return datetime.now(timezone.utc).timestamp() * 1000.0


def gather_tokens():
    """Return [(expiresAt_ms, accessToken, source)] sorted freshest-first.

    All users share one account, so any token works; we prefer the one with the
    latest expiry (most likely still valid). Unreadable files are skipped.
    """
    out = []
    for path in glob.glob(CRED_GLOB):
        try:
            with open(path) as fh:
                oauth = (json.load(fh) or {}).get("claudeAiOauth") or {}
            tok = oauth.get("accessToken")
            if not tok:
                continue
            exp = float(oauth.get("expiresAt") or 0)
            out.append((exp, tok, path))
        except (OSError, ValueError, TypeError) as e:
            log(f"WARN could not read {path}: {e}")
    out.sort(key=lambda r: r[0], reverse=True)
    return out


def fetch_usage(token):
    req = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "claude-stats-usage-monitor/1",
        },
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_poll_state(path):
    try:
        with open(path) as fh:
            return json.load(fh) or {}
    except (OSError, ValueError):
        return {}


def save_poll_state(path, state, live_srcs):
    """Persist per-source backoff bookkeeping, pruning sources we no longer see."""
    pruned = {k: v for k, v in state.items() if k in live_srcs}
    try:
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(pruned, fh, separators=(",", ":"))
        os.chmod(tmp, 0o600)            # internal state (not web-served) — root-only
        os.replace(tmp, path)
    except OSError:
        pass


def fetch_usage_any(tokens, state):
    """Try eligible tokens freshest-first; return (data, source) for the first that works.

    Two gates keep us from hammering api.anthropic.com with a token that will only fail:
      • EXPIRY — a token expired by more than EXPIRY_SKEW_MS is skipped WITHOUT a call (nobody active
        on this box; another server with a fresh token covers it via the merge).
      • BACKOFF — a not-yet-expired token that nonetheless returned an auth failure is skipped while
        within its per-source backoff window, UNLESS its expiresAt advanced since (token refreshed →
        retry immediately). `state` is mutated in place; the caller persists it.
    Returns (data, source) on success, or (None, error_string) if nothing was eligible/worked."""
    now = now_ms()
    tried = skipped_exp = skipped_backoff = 0
    last_err = "no credential files found"
    for exp, tok, src in tokens:
        if exp and exp < now - EXPIRY_SKEW_MS:
            skipped_exp += 1
            continue                                   # clearly expired → don't call
        s = state.get(src)
        # in backoff AND the token hasn't been refreshed since we recorded the failure
        if s and now < s.get("next", 0) and exp <= s.get("exp", 0):
            skipped_backoff += 1
            continue
        tried += 1
        try:
            data = fetch_usage(tok)
            state[src] = {"exp": exp, "fails": 0, "next": 0}      # success clears any backoff
            log(f"OK usage via {src}")
            return data, src
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code} from {src}"
            if e.code in AUTH_FAIL_CODES:
                # count consecutive fails for THIS token (reset if the token was refreshed)
                fails = (s["fails"] + 1) if (s and exp <= s.get("exp", 0)) else 1
                backoff = min(BACKOFF_CAP_MS, BACKOFF_BASE_MS * (2 ** (fails - 1)))
                state[src] = {"exp": exp, "fails": fails, "next": now + backoff}
                log(f"WARN {last_err} — backing off {int(backoff/1000)}s (fail #{fails})")
            else:
                log(f"WARN {last_err} (no backoff — not an auth failure)")
        except (urllib.error.URLError, ValueError, OSError) as e:
            last_err = f"{type(e).__name__}: {e}"            # transient — no backoff, retry next run
            log(f"WARN {last_err} from {src}")
    if tried == 0:
        last_err = (f"no eligible token (skipped {skipped_exp} expired, "
                    f"{skipped_backoff} backed-off of {len(tokens)})")
        log(f"QUIET {last_err} — not polling")
    return None, last_err


def norm_bucket(b):
    """Normalise a {utilization, resets_at} bucket; tolerate null/missing."""
    if not isinstance(b, dict):
        return None
    util = b.get("utilization")
    resets = b.get("resets_at")
    return {
        "utilization": round(float(util), 1) if util is not None else None,
        "resets_at": resets,
        "resets_in_sec": resets_in_sec(resets),
    }


def resets_in_sec(resets_at):
    if not resets_at:
        return None
    try:
        # API sends ISO-8601 with offset (e.g. "...+00:00"); handle trailing Z too.
        dt = datetime.fromisoformat(resets_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, int((dt - datetime.now(timezone.utc)).total_seconds()))
    except (ValueError, AttributeError):
        return None


def build_payload(data, source, server="main"):
    """Map the raw OAuth usage response into the badge-friendly schema."""
    eu = data.get("extra_usage") or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(LOCAL_TZ).isoformat(timespec="seconds"),
        "stale": False,
        "error": None,
        "server": server,    # which box took this reading (global per account, so any is authoritative)
        "source": os.path.basename(os.path.dirname(os.path.dirname(source)))
        if source else None,  # the Linux username whose token we used
        "session": norm_bucket(data.get("five_hour")),
        "weekly": norm_bucket(data.get("seven_day")),
        "weekly_opus": norm_bucket(data.get("seven_day_opus")),
        "weekly_sonnet": norm_bucket(data.get("seven_day_sonnet")),
        "extra_usage": {
            "is_enabled": bool(eu.get("is_enabled")),
            "used_credits": eu.get("used_credits"),
            "monthly_limit": eu.get("monthly_limit"),
            "utilization": eu.get("utilization"),
            "currency": eu.get("currency"),
        } if eu else None,
    }


def stale_payload(prev, error, server="main"):
    """Keep last-known buckets but recompute countdowns & flag stale."""
    base = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(LOCAL_TZ).isoformat(timespec="seconds"),
        "stale": True,
        "error": error,
        "server": server,
        "source": (prev or {}).get("source"),
        "session": None,
        "weekly": None,
        "weekly_opus": None,
        "weekly_sonnet": None,
        "extra_usage": (prev or {}).get("extra_usage"),
    }
    if prev:
        for k in ("session", "weekly", "weekly_opus", "weekly_sonnet"):
            b = prev.get(k)
            if isinstance(b, dict):
                b = dict(b)
                b["resets_in_sec"] = resets_in_sec(b.get("resets_at"))
                # No usable token means no Claude Code session is running on this account, so
                # utilization cannot move — the held value stays exact until the window resets.
                # Once resets_at passes, the limit HAS reset: the truthful reading is 0% with no
                # known next reset (a new 5h window only starts on the next prompt). Idempotent:
                # the zeroed bucket is what `prev` holds on later stale runs.
                if b.get("resets_at") and b["resets_in_sec"] == 0:
                    b["utilization"] = 0.0
                    b["resets_at"] = None
                    b["resets_in_sec"] = None
                base[k] = b
    return base


def _payload_age_s(payload):
    """Seconds since a payload's `generated_at` (local-tz ISO). None if unparseable."""
    ts = (payload or {}).get("generated_at")
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=LOCAL_TZ)
        return (datetime.now(LOCAL_TZ) - dt).total_seconds()
    except (ValueError, AttributeError):
        return None


def merge_remote_limits(local_payload, merge_dir):
    """Pick the freshest NON-STALE reading across {local} ∪ {remote-shipped merge_dir/*.json}.

    Limits are global per account, so every server's reading is the same truth; we just want the most
    recent live one so the feed never goes stale while a session is active on ANY box. A remote file
    that is stale, unparseable, or older than MERGE_MAX_AGE_S (remote stopped shipping) is ignored.
    Falls back to `local_payload` (which may itself be a held/stale payload) when nothing is fresh."""
    candidates = []
    if not local_payload.get("stale"):
        candidates.append((_payload_age_s(local_payload) or 0.0, local_payload))
    chosen_from = []
    for ff in sorted(glob.glob(os.path.join(merge_dir, "*.json"))):
        try:
            with open(ff) as fh:
                p = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(p, dict) or p.get("stale"):
            continue
        age = _payload_age_s(p)
        if age is None or age > MERGE_MAX_AGE_S:
            continue
        candidates.append((age, p))
        chosen_from.append(f"{p.get('server', os.path.splitext(os.path.basename(ff))[0])}({int(age)}s)")
    if not candidates:
        return local_payload, []
    candidates.sort(key=lambda c: c[0])          # smallest age = freshest
    return candidates[0][1], chosen_from


def _window_key(resets_at):
    """Dedup key for a limit window: round resets_at to the nearest 5 minutes. The OAuth API reports
       the SAME window's resets_at with sub-second jitter (e.g. ...:59.9 one poll, ...:00.8 the next),
       so keying on the raw string counted one window many times. Rounding collapses that jitter while
       keeping genuine windows distinct (5h/7d windows reset hours apart). Unparseable → raw string."""
    try:
        dt = datetime.fromisoformat(str(resets_at).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return str(int(round(dt.timestamp() / 300.0) * 300))
    except (ValueError, AttributeError, TypeError):
        return str(resets_at)


def update_limit_hits(payload, state_path):
    """Bank distinct 5h/7d windows (keyed by _window_key) that ever reached >=67% utilization, so the
       SESSION/WEEKLY PUSH trophies can count 'times you pushed a window hard'. A window is counted
       once, no matter how many 2-min polls catch it. Returns cumulative counts."""
    try:
        with open(state_path) as fh:
            st = json.load(fh)
    except (OSError, ValueError):
        st = {}
    # migrate-on-load: re-key any legacy raw-timestamp entries through _window_key (idempotent for
    # already-bucketed keys), so historical jitter-inflated entries collapse to one per real window.
    sess = set(_window_key(x) for x in st.get("session", []))
    wk = set(_window_key(x) for x in st.get("weekly", []))
    for key, store in (("session", sess), ("weekly", wk)):
        b = payload.get(key)
        if isinstance(b, dict) and b.get("utilization") is not None \
           and b["utilization"] >= 67 and b.get("resets_at"):
            store.add(_window_key(b["resets_at"]))
    try:
        tmp = state_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump({"session": sorted(sess), "weekly": sorted(wk)}, fh)
        os.chmod(tmp, 0o600)  # internal state (not web-served) — keep it root-only
        os.replace(tmp, state_path)
    except OSError:
        pass
    return len(sess), len(wk)


def read_prev(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def write_atomic(path, payload, chown_www=True):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    os.replace(tmp, path)
    if not chown_www:
        return                                  # remotes write a private temp file, then sftp it up
    # Match the rest of the pipeline: badge JSON is served by www-data.
    try:
        info = pwd.getpwnam("www-data")
        os.chown(path, info.pw_uid, info.pw_gid)
    except (KeyError, PermissionError):
        pass  # not root / no www-data — fine for local test runs


def main():
    ap = argparse.ArgumentParser(description="Claude Code session/weekly limit poller")
    ap.add_argument("--output", required=True, help="JSON file to write")
    ap.add_argument("--server", default="main", help="label tagging which box took the reading")
    ap.add_argument("--state", default="/opt/claude-stats/limit-hits.json",
                    help="persistent state for cumulative >=67% session/weekly hit counts")
    ap.add_argument("--poll-state", default=DEFAULT_POLL_STATE,
                    help="per-source backoff bookkeeping (so a dead token isn't retried every run)")
    ap.add_argument("--merge-dir", default=None,
                    help="MAIN only: dir of remote-shipped <label>.json readings to merge in "
                         "(serve the freshest non-stale across local + remotes)")
    ap.add_argument("--no-chown", action="store_true",
                    help="REMOTES: don't chown output to www-data (it's a temp file we sftp up)")
    ap.add_argument("--no-limit-hits", action="store_true",
                    help="REMOTES: skip the >=67%% trophy bookkeeping (main recomputes it authoritatively)")
    ap.add_argument("--pretty", action="store_true", help="pretty-print (debug)")
    args = ap.parse_args()

    tokens = gather_tokens()
    if not tokens:
        log("WARN no credential files matched " + CRED_GLOB)
    poll_state = load_poll_state(args.poll_state)
    data, source = fetch_usage_any(tokens, poll_state)
    save_poll_state(args.poll_state, poll_state, {src for _, _, src in tokens})

    if data is not None:
        payload = build_payload(data, source, server=args.server)
        log("session={}% weekly={}% (reset in {}s / {}s){}".format(
            payload["session"] and payload["session"]["utilization"],
            payload["weekly"] and payload["weekly"]["utilization"],
            payload["session"] and payload["session"]["resets_in_sec"],
            payload["weekly"] and payload["weekly"]["resets_in_sec"],
            f" extra_credits={payload['extra_usage']['used_credits']}"
            if payload.get("extra_usage") else ""))
    else:
        prev = read_prev(args.output)
        payload = stale_payload(prev, source, server=args.server)  # `source` holds the error string here
        log(f"STALE keeping last-known values; error={source}")

    # MAIN: serve the freshest live reading across this box + same-account remotes (limits are global,
    # so any server's reading is authoritative — this keeps the feed alive when work is on another box).
    if args.merge_dir and os.path.isdir(args.merge_dir):
        chosen, from_list = merge_remote_limits(payload, args.merge_dir)
        if chosen is not payload:
            log(f"MERGE serving {chosen.get('server','?')} reading "
                f"(session={chosen.get('session') and chosen['session'].get('utilization')}%) "
                f"over local '{payload.get('server')}' [candidates: {', '.join(from_list)}]")
        payload = chosen

    # limit-hit trophy bookkeeping is recomputed on the FINAL served (authoritative) payload, with this
    # box's own state — so it's correct no matter which server supplied the reading. Remotes skip it
    # (main recomputes it). A held/stale payload carries the previous counts forward (don't bank held
    # utilization); a fresh reading from any server banks its >=67% windows.
    if args.no_limit_hits:
        payload.pop("session_limit_hits", None)
        payload.pop("weekly_limit_hits", None)
    elif payload.get("stale"):
        prev = read_prev(args.output)
        payload["session_limit_hits"] = (prev or {}).get("session_limit_hits", 0)
        payload["weekly_limit_hits"] = (prev or {}).get("weekly_limit_hits", 0)
    else:
        sh, wh = update_limit_hits(payload, args.state)
        payload["session_limit_hits"] = sh
        payload["weekly_limit_hits"] = wh

    if args.pretty:
        print(json.dumps(payload, indent=2))
    write_atomic(args.output, payload, chown_www=not args.no_chown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
