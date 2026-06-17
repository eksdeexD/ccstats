# JSON schema

## `claude-stats.json` (the published, all-time contract)
Compact JSON, regenerated every 5 min. `meta.schema_version` is `1` — bump on any breaking change.

```jsonc
{
  "meta": {
    "schema_version": 1,
    "generated_at": "2026-01-01T12:00:00+00:00",   // configured timezone
    "timezone": "UTC",
    "corpus_start": "2025-11-01", "corpus_end": "2026-01-01", "corpus_days": 62,
    "servers": ["main"]
  },
  "totals": {
    "sessions": 0, "work_sessions": 0, "active_days": 0,
    "current_streak": 0, "longest_streak": 0,
    "longest_session_min": 0,   // longest single work session in CREDITED minutes (per-session; never summed)
    "avg_session_min": 0,       // mean work-session length = summed credited time / work_sessions (concurrency irrelevant)
    "total_active_min": 0,      // UNION of all sessions' active spans — "was ANY session active" credited
                                //   time. A session breaks on a > 20 min idle gap; within a session any
                                //   single idle gap credits at most 5 min (see active_spans). Concurrent/
                                //   parallel sessions count ONCE (never double-counted), so this is bounded
                                //   by real elapsed time, not the sum of session times.
    "nightowl_active_min": 0,   // union active minutes falling in local hours 00:00–05:59
    "user_words": 0,            // real words typed (whitespace split, URLs stripped; excl. compaction summaries + pasted-markdown prompts)
    "user_chars": 0,            // chars typed (URLs stripped)
    "user_chars_typed": 0,      // "true typed" chars: also drops pasted ```fenced```/`inline` code
    "user_prompts": 0,
    "tokens_input": 0, "tokens_output": 0, "tokens_cache_read": 0,
    "tokens_cache_create": 0, "tokens_total": 0,
    "cache_hit_ratio": 0.0,                          // cache_read / (cache_read+cache_create+input)
    "tool_uses": 0,
    "agent_launches": 0,   // subagent (Agent/Task tool) launches, all-time
    "favorite_model": "…",
    "peak_hour": 0,        // 0–23, local
    "peak_weekday": 0      // 0=Mon … 6=Sun
  },
  "cost_estimate": {                                 // hypothetical pay-as-you-go; see note
    "total_usd": 0.0, "input_usd": 0.0, "output_usd": 0.0,
    "cache_read_usd": 0.0, "cache_create_usd": 0.0,
    "pricing_date": "…", "note": "…"
  },
  "histograms": { "hours": [/*24*/], "weekdays": [/*7, Mon-first*/],
                  "weekday_hour": [/*7×24, Mon=0..Sun=6 × 0..23, prompt counts; row/col sums == weekdays/hours*/] },
  "daily_activity": [ {"date": "2025-11-01", "prompts": 0, "tokens": 0, "tokens_io": 0, "active_min": 0, "words": 0, "sessions": 0, "agents": 0} /* every day in range, zero-filled; per-day active_min is the daily slice of the cross-session UNION (concurrent sessions counted once); "agents" = subagent launches that day (history from ~ledger-start, since it needs the transcript on disk) */ ],
  "top_tools": [ {"name": "Bash", "count": 0} ],     // desc
  "models":    [ {"name": "…", "turns": 0, "pct": 0.0} ],  // desc
  "projects":  [ {"name": "…", "server": "main", // one row per project NAME, merged across servers
                                                  // (same projectname.txt on several boxes = one project);
                                                  // a project = a Linux user (default) or a Claude Code
                                                  // working dir (project_granularity: directory) — see
                                                  // docs/projects-layout.md;
                                                  // "server" comma-joins every contributing server
                  "sessions": 0, "work_sessions": 0,
                  "active_days": 0, "tokens_total": 0,
                  "tokens_input": 0, "tokens_output": 0,            // per-category split, so a
                  "tokens_cache_read": 0, "tokens_cache_create": 0, // consumer can scale by no-cache
                  "user_words": 0, "user_prompts": 0,               // (input+output) instead of total
                  "tool_uses": 0, "agent_launches": 0,              // agent_launches = subagent launches in this project
                  "cost_estimate_usd": 0.0,
                  "total_active_min": 0, "longest_session_min": 0,   // active time in this project: union of
                                                                     //   its sessions' spans (concurrent → once)
                  "avg_session_min": 0,                              // mean work-session length (summed basis; > 20 min gap splits, idle capped at 5 min)
                  "last_active": "…"} ]   // desc by tokens_total
}
```

## `live-status.json` (optional monitor; ~2 s cadence)
```jsonc
{
  "status": "working",          // working | idle | waiting | no_processes  (top-level rollup)
  "users": {
    "<user>": {
      "status": "working",      // working | idle | waiting
      "act_status": "working",  // activity state, before the waiting override
      "net_bps": 0,             // state signal #1: remote-socket bytes/s (sent+received), via `ss`
      "owes_response": false,   // state signal #2: transcript says the turn is in progress (model owes
                                //   output / a tool is running) — holds working through silent API latency
      "io_bps": 0,              // diagnostic only (NOT in the decision): rchar+wchar bytes/s, busiest process
      "signals": "N--R",        // raw fires: N=net I=io T=transcript R=owes ('-'=quiet); N & R drive state
      "waiting": false, "waiting_sessions": [],
      "pids": [], "since": "…"
    }
  },
  "thresholds": { /* live tunables: net_bytes_per_s + turn_signal/turn_cap_s (the two state signals), io_bytes_per_s + transcript_signal (diagnostic only), idle/active debounce, sample interval, config_overrides, … */ },
  "updated_at": "…"
}
```
`waiting` = a session blocked on an unanswered `AskUserQuestion` ("HUMAN BOTTLENECK"); it overrides
idle (a blocked session is CPU-idle).

## Fragment (remote → main, optional)
```jsonc
{ "server": "<name>", "generated_at": "…",
  "sessions": [ {"session_id": "<uuid>", "username": "…", "project": "…", "metrics": { /* per-session aggregate */ }} ] }
```
The main server keys ledger rows by `server:session_id`, so a remote's sessions drop straight in.
The per-session `metrics` blob includes `model_tokens`, `hourly`, `daily_activity`,
`daily_model_tokens` (`{date: {model: {input,output,cache_read,cache_create}}}`, added for the
priciest-day record — main prices it), and `active_spans` (`[["<utc-iso start>","<utc-iso end>"], …]`
— the session's active-time intervals, each idle gap already capped at 5 min (a > 20 min gap splits
the session); main UNIONs these across all sessions so concurrent sessions count once for active time). Adding a per-session field like this means **remotes must re-ship** the
updated extractor (`provision-remote.sh --update all`) before their data contributes to that field;
until then a remote's sessions fall back to their *summed* active time (not de-overlapped) and
everything else keeps working.

## Competition feed (head-to-head, optional)
Two token-gated files written by `extract.py --mode competitor`. They carry **numbers + project
names** (the per-project breakdown drives the VERSUS PROJECTS screen — project names are
intentionally shared with the trusted, opted-in friend who pulls the feed). They never carry
**prompt/response text, usernames, or session IDs**.

**`competitor.json`** — *this* person's aggregate only (a friend pulls it with the **peer** token):
```jsonc
{ "schema_version": 1, "kind": "competitor",
  "alias": "Maverick",                        // alias + per-project names are the identity shared
  "generated_at": "…", "timezone": "…",
  "windows": {                                // 24h / 7d / 30d / all, anchored to the local clock-hour
    "24h": { "tokens_total": 0,                 // all = input+output+cache_read+cache_create
             "tokens_input": 0, "tokens_output": 0,  // lead with input+output for a no-cache "work done" race
             "cost_usd": 0.0, "prompts": 0,
             "words_typed": 0, "active_days": 0, "night_owl_pct": 0.0,
             "leverage_tokens_per_prompt": 0, "bottleneck_sec": 0 },
    "7d": { … }, "30d": { … }, "all": { … }
  },
  "metrics": {                                // global records / totals
    "current_streak": 0, "longest_streak": 0, "peak_day": {"date":"…","tokens":0},
    "peak_day_io": {"date":"…","tokens":0},   // no-cache (input+output) peak day, for BIGBANG
    // all-time per-day personal bests (feed the /viewscreens avatar "NEW RECORD" celebration).
    // {date,value}; words/day come from the hourly map so it's accurate from ~ledger-start on.
    "record_day_prompts": {"date":"…","value":0}, "record_day_words": {"date":"…","value":0},
    "record_day_active_min": {"date":"…","value":0}, "record_day_sessions": {"date":"…","value":0},
    "record_day_cost": {"date":"…","usd":0.0},   // priciest day; priced from the per-session
                                                 // daily_model_tokens map (remotes must ship it)
    "endurance_longest_session_min": 0, "sessions": 0, "work_sessions": 0, "active_days": 0,
    "total_active_min": 0, "nightowl_active_min": 0, "user_chars_typed": 0,
    "words_typed_total": 0, "prompts_total": 0,
    "tokens_total_all": 0, "tokens_output_all": 0, "agents_total": 0, "cost_usd_all": 0.0,
    "cache_hit_ratio": 0.0, "bottleneck_sec_total": 0 },   // agents_total = all-time subagent launches (head-to-head)
  "daily": [ {"date":"…","tokens":0,"output":0,"prompts":0} ],   // last 30 days (sparkline / re-verify)
  "projects": [ {"name":"…","tokens_total":0,"tokens_input":0,"tokens_output":0,   // per-project breakdown
                 "cost_estimate_usd":0.0,"user_prompts":0,"user_words":0,          // → VERSUS PROJECTS screen
                 "total_active_min":0,"agent_launches":0} ],                        // (grouped by project name)
  "limits": { "session": {"utilization":0,"resets_at":"…","resets_in_sec":0},
              "weekly": {…}, "stale": false, "generated_at": "…",
              "session_limit_hits": 0, "weekly_limit_hits": 0 },   // folded from claude-limits.json
              // *_limit_hits = cumulative count of distinct 5h/7d windows that ever hit >=67%
  "pricing_date": "…" }
```
`cost_usd` per window is approximate (blended all-time $/token × window tokens); `cost_usd_all` is exact.

**`competition.json`** — *you + every fetched peer*, for your own `/viewscreens` + badge (master token):
```jsonc
{ "schema_version": 1, "kind": "competition", "generated_at": "…",
  "me": { /* a competitor.json payload */ },
  "peers": [ { /* a competitor.json payload */, "_fetch": {"ok": true, "error": null, "fetched_at": "…"} } ] }
```
A peer that can't be reached this cycle keeps its last-good cached payload with `_fetch.ok=false`.

## `claude-limits.json` (optional; the USAGE screen)
Written by `monitor/usage-monitor.py`, polled from the Claude OAuth usage endpoint every ~2 min.
Each bucket is `{utilization, resets_at, resets_in_sec}` (`utilization` a percentage rounded to 1 dp,
or `null`; `resets_in_sec` is recomputed from the absolute `resets_at` so countdowns stay exact even
on a stale read).
```jsonc
{ "schema_version": 1,
  "generated_at": "…",          // poller-local ISO
  "stale": false,               // true = no usable token / feed not advancing (held values stay exact)
  "error": null,                // error string when stale
  "server": "main",             // which box took the reading (rate limits are global per account)
  "source": "alice",            // Linux user whose token was read, or null
  "session":       { "utilization": 23.0, "resets_at": "…Z", "resets_in_sec": 12345 },   // 5-hour
  "weekly":        { "utilization": 12.0, "resets_at": "…Z", "resets_in_sec": 456789 },  // 7-day
  "weekly_opus":   null,        // same bucket shape, or null if the account has no such limit
  "weekly_sonnet": null,
  "extra_usage": { "is_enabled": true, "used_credits": 0.0, "monthly_limit": 3000,
                   "utilization": 0.0, "currency": "EUR" },
  "session_limit_hits": 0,      // cumulative count of distinct windows that crossed ≥67%
  "weekly_limit_hits": 0 }      //   (feed the SESSION/WEEKLY PUSH trophies; suppressed with --no-limit-hits)
```
**Stale reads stay truthful.** The poller can only read a token while a Claude Code session is
running, so `stale: true` also means *no session is active* — utilization can't move and the held
values remain exact. Once a held window's `resets_at` passes, that window has reset, so the poller
zeroes it (`utilization: 0`, `resets_at: null`). The `/viewscreens` USAGE chip renders this held
state as **HELD**; **STALE** is reserved for a dead feed (poller not writing at all). The same
`limits` block is folded into `competitor.json` / `competition.json` (see above).

## `content-pack.json` (optional; the badge avatar's message banks)
A single token-gated static file of the avatar's message banks — edit `server/pipeline/content-pack.json`
and redeploy to change what the badge says, no firmware release needed. The badge re-fetches it
~daily, persists it to flash, and falls back to its baked-in defaults (`firmware/content_pack.py`)
for any bank that's missing or for a pack it rejects. Lines are **ASCII only**, ≈60 chars max.
```jsonc
{ "meta": { "schema_version": 1, "pack_version": 1 },   // bump pack_version on any content change
  "working_words":    ["ACCOMPLISHING", "BAKING", …],   // ALL-CAPS working ticker (no lowercase 'i')
  "bottleneck_tiers": [ […], […], […] ],                // HUMAN BOTTLENECK quips by tier: 0-3 / 3-6 / 6+ min
  "book_taunts":      ["…"],                             // VERSUS book/taunt lines
  "limit_lines":      ["…"],                             // usage-limit quips
  "streak_lines":     ["…"],                             // streak-danger quips
  "record_lines":     ["…"],                             // record-break celebration bubbles (optional)
  "trophy_lines":     ["…"],                             // trophy tier-up celebration bubbles (optional)
  "quotes": [ { "q": "…", "a": "author" } ] }            // idle quotes (author stored, not shown)
```
Only `meta` is required; include whatever banks you want to override and omit the rest. The badge
picks which line to show locally (no-immediate-repeat random) — the server only supplies the material.
