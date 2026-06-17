# Architecture

## Project discovery
Any Linux user with `~/.claude/projects/` is auto-discovered (one project per user). Optional
`~/projectname.txt` overrides the display name; if it contains the whole word **`ignore`** the
project is excluded. Reading session files needs **root** (they're mode `0600` inside `0700`
`~/.claude/` dirs), so the extractor runs from root's cron.

## Parsing rules (from the real session-file corpus)
- **Real user prompts** (for word/char/prompt counts + hour/weekday/day histograms):
  `type=="user"`, `isSidechain` false, no `toolUseResult`/`sourceToolAssistantUUID`, not `isMeta`,
  content has a text block that is non-empty and does **not** start with `<`. URLs stripped.
- **Assistant turns / tokens — dedup by `requestId`, keep the max `output_tokens` record.**
  Streaming writes several records per `requestId` (input/cache identical; every record carries the
  same cumulative `output_tokens`); skipping the token dedup ~doubles output tokens. Drop
  `output_tokens==0` (interrupted) and `model=="<synthetic>"` records.
- **Tools — union the `tool_use` blocks across ALL of a `requestId`'s records, deduped by block
  `id`.** Each `tool_use` block is written as its *own* streaming record, so a turn's tool calls are
  spread one-per-record (no single record holds the full set). Reading tools off the one kept
  token record (the old behaviour) undercounts `tool_uses` ~2x and parallel-launch tools (e.g. an
  `Agent` batch) ~3.5x. Tool collection is decoupled from the token-record choice, so token totals
  are unaffected by it.
- **Subagent files** (`<sessionId>/subagents/**`) are folded into their parent session; their
  model calls count (dedup makes it safe).
- **Sessions** = count of top-level `<encoded-cwd>/<sessionId>.jsonl` files. **Work sessions** =
  each session's event timeline split on idle gaps > 20 min. Active/project/endurance time credits
  each within-session idle gap at most 5 min (a longer gap ≤ 20 min keeps the session whole but still
  only adds 5 min), so short breaks never inflate the totals.
- All JSONL timestamps are UTC; converted to the configured timezone before bucketing.
- Robust to corrupt/truncated lines and missing usage fields.

## Cost
Per-model token totals × `pricing.json` rates, summed by category. Unknown models fall back to a
default rate (logged). **Cost is hypothetical pay-as-you-go; real billing differs** (e.g. a Max
plan is a fixed price) — stated in the JSON's `cost_estimate.note`. Update `pricing.json` as rates
change.

## All-time ledger (why totals are durable)
Claude Code deletes transcripts older than `cleanupPeriodDays` (default 30) on startup, so the
on-disk corpus shrinks for active users. To keep totals **all-time**, `--mode full` doesn't
aggregate live transcripts directly — it banks them in a SQLite ledger (`/opt/claude-stats/ledger.db`)
and aggregates the whole ledger:
- **`sessions` table** — one row per session (`server:sessionId`). Each run re-parses the
  transcripts that still exist and **upserts** each session's latest metrics (append-only → only
  grows → replace-with-latest is correct & idempotent). Sessions **not seen** that run (deleted, or
  a transient read error) are **retained** (`alive=0`) — so pruning never loses stats.
- **`record_owner` table** — pins each `requestId`/user-prompt `uuid` to the first session that
  banked it. A request/prompt copied into multiple transcripts (session *resume*) is counted once
  and **never re-counted by a surviving copy even after the owning session is deleted**.
- The ledger is copied to `ledger.db.bak` at the start of each run — a single rolling copy for an
  instant one-step undo (overwritten every run; not a history). The retained snapshots below are the
  durable safety net.
- **Optional `--mode seed`** (idempotent): for usage pruned *before* the ledger existed, a fixed
  `archive` row per project can recover an observed peak (`peak − current`). Empty by default
  (`PRELEDGER_PEAK = {}`); the archived slice only carries totals (no per-day/heatmap detail).

## Backups (retained restore points)
The rolling `.bak` only survives until the next run, so the durable state is also snapshotted into
`/opt/claude-stats/backups/`:
- A **snapshot is one timestamped directory** (`backups/YYYY-MM-DDThh-mm-ss/`) holding a *consistent
  set*: `ledger.db` + `bottleneck.db` copied via SQLite's **online backup API** (`sqlite3`'s
  `Connection.backup()`) — consistent even while the crons hold the db open, unlike a raw file copy —
  plus plain copies of `config.json`/`token.txt`/`peer-token.txt` (tiny, but painful to re-create:
  peers + the badge/peer tokens). The dir is root-only `700`; token copies are `600`.
- **Two triggers:** `deploy.sh` forces one (`extract.py --mode backup`) **before every update**, and
  the full run takes an **age-gated** one (only if the newest is >3 h old → ~8 intra-day points/day),
  so non-deploy corruption is covered. The gate is time-based, so the cron's run frequency doesn't
  change how dense the snapshots get.
- **Retention — grandfather-father-son (two tiers):** every snapshot from the **last 24 h** is kept
  (fine-grained same-day rollback), plus the **newest snapshot per calendar day for 30 days**; the
  rest are pruned. Net: fine recovery granularity for the last day + a month of daily restore points
  (~38 dirs ≈ ~110 MB worst case). Foreign dirs (names that aren't a snapshot timestamp) are ignored,
  never pruned. (`--backup-keep` is a deprecated no-op kept for backward compatibility.)
- **Restore is manual** and deliberate: stop the crons, copy a snapshot dir's `ledger.db`/
  `bottleneck.db` back over the live ones, restart. Nothing restores automatically.

## Output & cadence
`--mode full` writes `claude-stats.json` (the badge/dashboard contract — see `schema.md`). A root
cron runs it every 5 min and `chown`s the JSON to `www-data`. nginx serves it token-gated.

## Multiple servers (optional, drop-in)
A remote server runs `--mode fragment` (per-session rows) and `scp`s the JSON into the main
server's `/var/www/stats/fragments/`; the main `--mode full` ingests every fragment's sessions
into the ledger automatically. Single server needs none of this. One command sets up a remote:
`sudo ./server/pipeline/provision-remote.sh` on the main server — see **`docs/remote-fragment.md`** for
the full flow (the two SSH directions, the one key you paste, hardening).

## Live-activity monitor (optional)
`live-monitor.py` writes `live-status.json` every ~2 s with per-user **working / idle / waiting**
(see `schema.md`). **Activity is decided by two state signals (working if EITHER fires):**
(1) **NETWORK** bytes/sec to the API over threshold (via `ss -tinp` tcp_info — cleanly separates idle
from active, hardware-independent, and a turn can't start without it); and (2) **OWES-RESPONSE** — the
transcript shows the turn is still in progress (last record is a user prompt or tool_result, or a
non-AskUserQuestion tool is running). The second exists because during a turn the model can think
server-side for **15–25 s+ with nothing streaming**, so net (and io/mtime) all go quiet even though
the turn isn't done → net alone false-idles mid-turn; the transcript is ground truth that it isn't.
It's held at most `turn_cap_s` (≈300 s) past the last net activity, so a dead/hung turn still decays.
`/proc/[pid]/io` bytes/sec and the transcript's mtime are still **measured and shown for diagnostics
but no longer drive state** — I/O is too noisy (idle disk blips cross any sane threshold →
false-working) and mtime never fired uniquely; CPU% was dropped earlier for the same reason. To flip
idle→working a state signal must hold for `active_debounce` (≈2 s, a one-sample confirm); to decay to
idle BOTH must be quiet for `idle_debounce` (≈8 s — kept snappy because the owes-response signal, not
a big debounce, is what covers long API latency). **Waiting**
= a session blocked on an unanswered
`AskUserQuestion` (transcript-based), which overrides idle. Runs as root (needs `/proc/[pid]/io`
mode 0400, and `ss` to see every user's sockets). Tunables default in the script and are
**overridable per-machine via the `live_monitor` block in `config.json`** (so a box on different
hardware tunes itself without forking the code — though the network-primary defaults usually travel
as-is). **Verify the process matcher on each machine** — how `claude` appears in `/proc/*/cmdline`
varies by install.

**How the `/viewscreens` avatar consumes it.** The dashboard polls `live-status.json` every 5 s and drives the
screen-2 Claude avatar from the **top-level `status`** (the global "working anywhere" roll-up;
`no_processes` renders as idle/STANDBY). It is **edge-triggered**: the avatar changes only when the
feed's value *changes*, so a manual Tweaks / `?avatar=` preview persists between transitions while the
next real transition always wins. The **`done`** state is **not** in the feed — the client synthesizes
it for 15 s on a `working`→`idle` transition (a finished turn; idle is already debounced upstream, so
this isn't a mid-stream gap), then settles to idle. `waiting`→`idle` is deliberately **not** "done". If
the feed is unavailable the avatar holds its last state (it never invents a transition).

## `/viewscreens` front-end (optional)
A static HTML page with **no build step**, rendered on an HTML5 `<canvas>` (PicoGraphics-style).
`viewscreens/pico.js` is a drawing shim (~10 primitives, absolute 320×240 integer coordinates) and
`viewscreens/screens.js` holds the **screen registry** (`SCREENS`, keyed by slug) plus the data-fetch
and render logic, shared via `boot()`. With a `?token=` in the URL it fetches the live feeds
(`/claude-stats.json`, and `/competition.json` + `/claude-limits.json` when present); without one it
falls back to built-in sample data. `index.html` (`/viewscreens`) renders every screen grouped by
category, with a Tweaks panel for live theme/type-scale/option previews. **This is also the design
spec the Tufty firmware is ported from** — the same draw calls run on the device against PicoGraphics.
On-device theming is **preset-only**: colours change by cycling the pre-vetted presets on the
OPTIONS › PALETTES screen; there is no on-device colour picker.
- **ACTIVITY heatmap — active-day floor.** A day counts toward the streak by `prompts > 0`, but the
  heatmap colours by the selected token lens (default **no-cache** `tokens_io`). `buildHeatmap` floors
  any `prompts > 0` day to level 1 so it never paints as an empty cell, keeping the heatmap consistent
  with the streak. This matters for legacy sessions banked before per-day `tokens_io` existed and since
  pruned (can't be re-parsed to backfill it): they retain `prompts` + cache-inclusive `tokens` but read
  `tokens_io = 0`, so without the floor they'd vanish from the default lens despite being real activity.
  Genuinely empty days (`prompts == 0`) are untouched, and the ramp max is unchanged so every other
  cell keeps its exact colour.

## Firmware (badge) architecture
The optional Tufty 2350 badge is a **consumer** of the same feeds: it fetches the pre-computed JSON
over token-gated HTTPS and renders the screens that `/viewscreens` defines. Its internals:

- **The badge is as dumb as reasonable** — it fetches data, renders it, and does what the server
  tells it. **On the badge only:** input handling, navigation, rendering, and **all animation**
  (sprite frames, the "done" flourish, transitions) — triggered by server state but executed
  locally; ticking countdowns *between* polls (reset timers derived from absolute `resets_at`); an
  **NTP** clock (it reads the current UTC offset from the feeds rather than carrying timezone/DST
  tables); and a locally cached **content pack** (idle quotes, message banks — `content_pack.py`
  defaults, refreshed slowly from `content-pack.json`). **On the server:** every behavioural
  *decision* — the done-flourish/celebrate trigger, streak-danger and limit cadence, bottleneck
  escalation, which idle message to show — shipped as flags/directives, mostly via the additive
  fields on the ~2 s `live-status.json` channel. The split is the design call, not dogma; move a
  piece on-device if it doesn't work well server-driven.

- **Two-axis navigation** (`firmware/navigation.py`): **UP/DOWN** cycles the *categories*
  (`CATEGORY_ORDER` in `firmware/screen_registry.py` is the source of truth — LIVE, TOKENS,
  ACTIVITY, BREAKDOWN, VERSUS, TROPHIES, OPTIONS, plus a hidden DEV; wraps; entering a category
  resets to its first screen). **A** = ◀ / **C** = ▶ move *within* the current category (wraps).
  **B is contextual** per screen (e.g. a metric toggle, a VERSUS cache peek, enter/confirm an
  OPTIONS edit) and hidden where unused; on-screen bezel labels next to the physical buttons show
  what each does. The B label set is mirrored — not shared — by the web (`footerBLabel()`); see
  `device-pitfalls.md` for the keep-in-sync gotcha.

- **Power-aware polling** (`firmware/feeds.py` `FeedScheduler`): per-feed cadences are a runtime
  mode keyed off USB-vs-battery (`VBUS_DETECT`/`VBAT_SENSE`), all riding one keep-alive TLS
  connection (a fresh ~1.8 s handshake per poll is a non-starter — see `device-pitfalls.md`).
  Cadences (USB → battery): stats 5 min → 15 min, limits 60 s → 5 min, competition 2 min → 10 min,
  content pack 24 h. The **live channel** (`live-status.json`, 2 s on USB) is **OFF on battery by
  default**, toggleable with **B on the AVATAR screen** (`live_status_on_battery`). Errors back off
  5 → 60 s so a dead network isn't hammered.

## Head-to-head competition (optional)
Compares your **total** Claude Code usage against friends running this same pipeline.

- **Pull, not push.** Each side serves its own `competitor.json` over token-gated HTTPS; each side
  *pulls* the others on a 2-min cron (`--mode competitor`, which also re-emits your own feeds). No SSH,
  no write access into anyone's box; the consumer controls timing and retries.
- **Two tokens.** A **peer** token gates only `/competitor.json` (the one you hand out); your **master**
  token gates `/viewscreens` + `/competition.json`. A peer therefore can't read your dashboard or combined view.
- **Your total vs theirs.** Your own multiple servers fold into *your* total via the fragment mechanism
  (above); a friend is a **peer**, kept side-by-side and **never merged** into your numbers.
- **Rolling windows.** Per-session metrics carry an Option-B `hourly` map (`{ "YYYY-MM-DDTHH": {t,i,o,p,w} }`,
  local tz — `t`=total, `i`=input, `o`=output, `p`=prompts, `w`=words). `aggregate_hourly()` sums it across
  the ledger; a window of N hours = buckets back from the current clock-hour. Both competitors run the same
  timezone so the edges align (UTC-key the buckets if that ever stops being true). 7d/30d/all derive from the
  same map — **except** the **`all`** window, whose additive count fields (tokens/prompts/words/cost) are
  sourced from `combine()` over the whole ledger so it equals the badge's true all-time totals. The hourly
  buckets miss any row without an `hourly` map (notably the pre-ledger seed/archive rows — recovered totals
  with no time detail), so summing them would understate `all`; 24h/7d/30d are unaffected (the archive has no
  recent buckets). `night_owl_pct` for `all` stays on the hourly base (the archive carries no hour-of-day).
  (`i` was added later; buckets banked before it read as 0 — that only affected the now-superseded hourly `all` sum.)
- **No-cache race.** `tokens_total` is input+output+cache_read+cache_create, and cache_read usually dominates
  (it scales with session length, not work done). Each window therefore also carries `tokens_input` +
  `tokens_output` so a consumer can lead with the cache-free **input+output** measure; `/viewscreens` defaults to it
  and offers an "All" toggle.
- **HUMAN BOTTLENECK** seconds come from a separate durable daemon (`bottleneck-monitor.py` →
  `bottleneck.db`), independent of the live-activity monitor, so the stat persists on its own. A single
  unanswered question is banked for at most `ABANDON_CAP_SEC` (30 min, `--abandon-cap`): a session
  walked away from mid-question stops counting past that, so an abandoned window can't accumulate
  forever. The cap is keyed to the question's `tool_use`-id signature, so a new/changed question resets
  the budget and a session that's actively being answered is never capped.
- **Numbers + project names.** `competitor.json` is aggregate counts + your alias + your limits + a
  per-project breakdown (project **name** + tokens/cost/prompts/words/active-min/agents, drives the
  VERSUS PROJECTS screen). Project names are shared with the trusted, opted-in friend who pulls
  the feed. No prompt/response text, usernames, or session identifiers ever leave the box.
