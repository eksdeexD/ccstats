# Claude Code Usage Stats

Self-hostable pipeline that reads **Claude Code** session files on a Linux (Debian) server,
aggregates them into one pre-computed JSON, and (optionally) serves it over HTTPS — for a
dashboard, a hardware badge, or just curiosity. Five parts (the first is required, the rest optional):

1. **Core pipeline** *(required)* — parses every user's `~/.claude/projects/**` sessions into a
   durable **all-time SQLite ledger** and writes a compact `claude-stats.json` (tokens, cost
   estimate, streaks, per-project breakdown, activity heatmap, time-of-day rhythm — full list in the
   **[Stats catalog](#stats-catalog)**). Refreshes on a cron. Survives Claude Code's own transcript
   pruning (`cleanupPeriodDays`).
2. **`/viewscreens` dashboard** *(optional)* — a self-contained retro multi-screen web page (~21 screens
   across 7 categories) rendering the live data (re-themable via one config block); the badge's native
   **320×240** screens shown at 2× in the browser.
3. **Live-activity monitor** *(optional)* — a tiny daemon that reports, per user, whether Claude is
   **working / idle / waiting-on-you** (decided by network activity to the API; I/O + transcript are
   shown for context but don't drive state), plus a `/livetest` page.
4. **Session/weekly limits feed** *(optional)* — `usage-monitor.py` polls the Claude OAuth usage
   endpoint and publishes `claude-limits.json` (the USAGE screen): 5-hour + 7-day
   utilization and reset countdowns.
5. **Head-to-head competition** *(optional)* — compare your **total** Claude Code usage against a
   friend running this same setup: who burned the most tokens in the last **24h / 7d / 30d**, plus
   streaks, peak day, $ value extracted, a per-project breakdown, and more. Each side publishes a
   small `competitor.json` (numbers + project names, no transcript content) and pulls the other's
   over HTTPS. See **[Competing with a friend](#competing-with-a-friend-head-to-head)**.

Stdlib-only Python 3.9+; nginx + Let's Encrypt for serving; no third-party packages.

---

## Install (the easy way)
On your Debian server:
```bash
git clone https://github.com/eksdeexD/ccstats.git
cd ccstats
```
Then open Claude Code in this directory and tell it:

> **Read `README.md` and set up the Claude Code usage stats pipeline on this server.**

Claude Code will follow the playbook below — ask you what you want, investigate the box, generate
a token, and install everything. To **update later:** `git pull && sudo ./server/deploy.sh`.

---

## ⚠️ Security — what must NEVER be committed
This repo is **code + templates only**. Secrets and per-machine data live **outside** it (under
`/opt/claude-stats` and `/var/www/stats`) and are in `.gitignore`. Never commit:
- the **access token** (`token.txt`), the **peer token** (`peer-token.txt`), `config.json`
  (it holds your friends' peer tokens), any PAT/credential,
- the **ledger** (`ledger.db`), the **bottleneck DB** (`bottleneck.db`), or generated JSON
  (`claude-stats.json`, `live-status.json`, `claude-limits.json`, `competitor.json`, `competition.json`),
- your domain, IP, email, usernames, or project names (those are entered at setup, not stored in tracked files).

If anything secret ever gets committed, rotate it and scrub git history (`git filter-repo`).
`deploy.sh` updates **code only** and never overwrites your config, token, or ledger.

---

## For the coding agent — setup playbook
Do these in order. **Investigate this box; do not assume another machine's values.**
**All command paths below are relative to the repo root** (where `git clone` + `cd ccstats`
left you) — the same place `./server/deploy.sh` runs from. So source files are `server/pipeline/…`,
`server/monitor/…`, `server/nginx/…`, `server/systemd/…`, while `viewscreens/` and `docs/` sit at the
root. Don't `cd server` — several referenced paths live above it.

1. **Prereqs.** Confirm Python ≥3.9 (`zoneinfo`, `sqlite3` are stdlib). For serving, check `nginx`
   (offer `apt install nginx`) and, if a domain is used, `certbot` + `python3-certbot-nginx`.
   You need root (sudo).
2. **Ask which features** to install: `/viewscreens` dashboard? live-activity monitor? (Core is always
   installed.)
3. **Detect & confirm settings:**
   - **Timezone** — read from `timedatectl` and confirm; you'll write it to `config.json`.
   - **Projects layout** — default discovery is `/home/*/.claude/projects/` (one project per Linux
     user). Confirm this matches; list discovered users. Ask for display-name overrides
     (`~/projectname.txt` per user) and which users to exclude (put the word `ignore` in their
     `~/projectname.txt`) — including the account you're running as, if it shouldn't count.
     If the operator instead runs **several projects under one user account**, set
     `"project_granularity": "directory"` in `config.json` (one project per Claude Code working
     directory); if their homes live outside `/home`, point `--home-glob` at them. **Full guide to
     every layout: [`docs/projects-layout.md`](../docs/projects-layout.md)** — read it before
     configuring a non-default layout.
   - **Server label** — a short name for this machine (default `main`), used in the JSON.
4. **Web exposure.** Ask: a real **domain** (→ token-gated HTTPS via certbot; remind them DNS must
   already point at this box) or **no domain** (→ token-gated plain HTTP / localhost). Or skip
   serving entirely (just generate the JSON locally).
5. **Generate a fresh random token:** `python3 -c "import secrets;print(secrets.token_urlsafe(32))"`
   → `/opt/claude-stats/token.txt` (root, `chmod 600`). This is the `?token=` for every endpoint.
6. **Install core:**
   - `install -m755 server/pipeline/extract.py /opt/claude-stats/extract.py`; same for `pricing.json`.
   - Write `/opt/claude-stats/config.json` from `config.example.json` (set `timezone`; optionally
     `server`). `chmod 600` it — it can later hold friends' peer tokens.
   - `install -d -m755 -o root -g www-data /var/www/stats /var/www/stats/fragments`.
   - **Build the ledger + first JSON** (needs root to read other users' `0600` transcripts):
     `python3 /opt/claude-stats/extract.py --mode full --server <label> --fragments-dir /var/www/stats/fragments --output /var/www/stats/claude-stats.json` then `chown www-data:www-data` the JSON.
   - **Root cron, every 5 min** (same command + chown) → `/etc/cron.d` or root's crontab. Log to
     `/var/log/claude-stats.log`.
   - **Log rotation is automatic**: `deploy.sh` installs `/etc/logrotate.d/ccstats`, which rotates
     `/var/log/claude-stats*.log` (run by the distro's logrotate.timer / cron.daily — `logrotate` is
     part of the Debian/Ubuntu base). Remotes get their own `/etc/logrotate.d/ccstats-fragment` from
     the provision script. The systemd monitors log to the journal, which journald already size-caps.
7. **Serve it** (if chosen): render `server/nginx/stats-site.conf.template` (replace `__DOMAIN__`,
   `__TOKEN__`, `__WEBROOT__`=`/var/www/stats`), **delete the location blocks for features not
   installed**, symlink into `sites-enabled`, `nginx -t`, reload. If a domain:
   `certbot --nginx -d <domain>` (it adds HTTPS + redirect).
8. **Optional `/viewscreens` dashboard:** the canvas dashboard (PicoGraphics-style HTML5 `<canvas>`
   — the same screen design the Tufty firmware renders, and the spec it is ported from). To enable
   it, create the webroot dir once
   (`sudo install -d -o www-data -g www-data /var/www/stats/viewscreens`) and run
   `sudo ./server/deploy.sh` — it populates `/viewscreens/` (`index.html`, `pico.js`, `screens.js`,
   and the whole `fonts/` tree: per-font subfolders + `fonts.json`) and keeps it updated on every
   later deploy. Then add the `/viewscreens`, `/viewscreens/pico.js`, `/viewscreens/screens.js` and
   `^~ /viewscreens/fonts/` nginx blocks (from `server/nginx/stats-site.conf.template`) before the
   catch-all `location /`, and reload. It reads the same `/claude-stats.json`
   (+ `/competition.json`) feeds — no backend change. Do **not** run `viewscreens/build-fonts.py`
   (it rebuilds the font tree from source archives you don't have; use the committed `.woff2`).
9. **Optional live-activity monitor — re-verify on THIS box first:**
   - **How does `claude` appear here?** Inspect `/proc/*/cmdline` for the running Claude Code
     process (it may be an npm-global `claude`, a different path, etc. — not necessarily the same
     as elsewhere) and adjust `INCLUDE_SUBSTRINGS`/`EXCLUDE_SUBSTRINGS`/`INCLUDE_ARGV0_BASENAMES`
     at the top of `server/monitor/live-monitor.py` so it matches real Claude processes and excludes this
     pipeline's own scripts.
   - Check `/proc` for `hidepid` (in `/proc/mounts`) and CPU core count — note them; the daemon
     runs as **root** regardless (needs `/proc/[pid]/io`, mode 0400, and to write the JSON).
   - Install `server/monitor/live-monitor.py` → `/opt/claude-stats/`; deploy `server/monitor/livetest-index.html`
     → `/var/www/stats/livetest/index.html` (`www-data`); install
     `server/systemd/claude-live-monitor.service.template` → `/etc/systemd/system/claude-live-monitor.service`;
     `systemctl daemon-reload && systemctl enable --now claude-live-monitor`. Keep its nginx blocks.
     Tune the thresholds at the top of the daemon if needed (watch `journalctl -u claude-live-monitor -f`).
10. **Optional — limits feed + head-to-head competition:**
    - **Limits feed (USAGE screen):** install `server/monitor/usage-monitor.py` → `/opt/claude-stats/`; add a
      **root cron, every ~2 min**: `usage-monitor.py --output <WEBROOT>/claude-limits.json --merge-dir
      <WEBROOT>/limits-remote` then chown `www-data`. It reads the freshest OAuth `accessToken` from
      `/home/*/.claude/.credentials.json` (and **never refreshes it** — that's Claude Code's job) and
      publishes 5h/7d utilization + resets. Keep the `/claude-limits.json` nginx block.
      - **Cross-server (works even if MAIN's token is long expired):** rate limits are global per
        Anthropic account, so any box's reading is authoritative. `--merge-dir <WEBROOT>/limits-remote`
        makes MAIN serve the freshest non-stale reading across its own poll **and** the readings that
        fragment nodes ship there every minute (set up automatically by `provision-remote.sh`). So the
        USAGE screen stays live whenever a session is active on **any** box — MAIN never needs its own
        active token. `deploy.sh` creates the `limits-remote/` drop-zone; an empty dir is harmless.
    - **Durable bottleneck monitor:** install `server/monitor/bottleneck-monitor.py` → `/opt/claude-stats/`;
      install `server/systemd/claude-bottleneck-monitor.service.template` → `/etc/systemd/system/…`;
      `systemctl enable --now claude-bottleneck-monitor`. It banks cumulative **HUMAN BOTTLENECK**
      seconds (a session blocked on an `AskUserQuestion`) into `bottleneck.db` for the competition.
    - **Competition itself:** follow **[Competing with a friend](#competing-with-a-friend-head-to-head)**.
11. **Verify:** token gate returns **200** with the right `?token=` and **403** without; the JSON
    is valid; `/viewscreens` and `/livetest` render (if a browser/chromium is available, screenshot them).
12. **Write a local `CLAUDE.md`** in `/opt/claude-stats` (or the user's home) documenting THIS
    install: domain, token path, which features, cron, and the update/uninstall commands. Generate
    it fresh — do not copy any other machine's CLAUDE.md.

### Notes for the agent
- The published `claude-stats.json` is **all-time** because of the ledger — Claude Code deletes
  transcripts older than `cleanupPeriodDays` (default 30) on startup, but the ledger has already
  banked each session (see `docs/architecture.md`). Never delete `ledger.db`.
- A second/remote server can later feed per-session **fragments** into `/var/www/stats/fragments/`.
  One command does the whole setup: `sudo ./server/pipeline/provision-remote.sh` on the main server (see
  `docs/remote-fragment.md`). Single server needs none of that.
- Keep everything stdlib; don't add dependencies.

---

## Using it (day-to-day)
Everything is one token-gated origin — the random token you generated at setup (stored in
`/opt/claude-stats/token.txt`). Append `?token=<TOKEN>` to any endpoint; a wrong or missing token is a
**403**. Swap `<your-domain>` for your domain (or `localhost`/host if you serve plain HTTP).

- **Dashboard — `https://<your-domain>/viewscreens?token=<TOKEN>`:** the retro multi-screen page, showing
  every screen at once in a grid grouped by category. Screens are organised into **7 categories**:
  **LIVE** (live Claude avatar — working / idle / waiting-on-you, with a brief **DONE!** when a task
  finishes; a **USAGE** screen — your session/weekly limits with reset countdowns; and a **PROJECTS**
  per-project breakdown — bar by tokens, with cost, active time, prompts, words and agent-launch count
  per project, 4-up with **B** = `MORE` to page through the rest),
  **TOKENS** (overall token usage + a **PROMPTS** breakdown), **ACTIVITY** (contribution heatmap, a
  CALENDAR, and time-of-day RHYTHM with a weekday×hour matrix), **BREAKDOWN** (words/leverage, a
  **TODAY** today-vs-average snapshot, top tools, model split),
  **VERSUS** (head-to-head with a rival — a token race + your-vs-rival limits, a HUMAN-stats comparison,
  all-time RECORDS, and a TROPHIES face-off; the whole category is hidden until a rival is configured),
  **TROPHIES** (a 14-family tiered trophy grid — COMMON/RARE/EPIC/LEGENDARY — plus a NEXT UP progress
  screen), and **OPTIONS** (on-device settings — detailed below). It reads the token
  from its own URL and auto-refreshes — bookmark it. *(Only if you installed the `/viewscreens` dashboard.)*
- **On the badge:** the physical Pimoroni Tufty 2350 shows one screen at a time on its native
  **320×240** LCD, navigated with the five buttons (A/B/C/UP/DOWN): up/down move
  between categories (wrapping, and resetting to the category's first screen), ◀/▶ (A/C) page between the
  screens in a category, and **B** is a per-screen action where one exists: it pages projects
  (**MORE**) on **PROJECTS**, explains a trophy (**EXPLAIN**) on **TROPHIES**, and on **OPTIONS** opens
  the editor/preview (**EDIT** on DISPLAY and SCREENS, **PREVIEW** on PALETTES and AVATAR). (On battery,
  **B** on the avatar screen toggles the live channel on/off to save power.) **OPTIONS** has five
  screens (**DISPLAY · SCREENS · PALETTES · AVATAR · WIFI**): switch between
  **preset palettes** (pre-vetted for legibility — theming is preset-based), **pick an avatar sprite**
  (or the **CYCLE** tile to auto-rotate the roster on a timer you choose — 5/15/30/60 min, 3/6/12/24 h),
  choose the default token mode (cache / no-cache), set the boot screen, adjust animation speed and
  (on the Tufty) backlight brightness, toggle the avatar's today-line / session-bar, **show/hide
  individual screens** (OPTIONS › SCREENS), and join WiFi (a placeholder in `/viewscreens` — the real join
  happens on-device). The badge's own boot screen is the `boot_screen` device setting (default
  `avatar`), chosen in OPTIONS › DISPLAY. In the `/viewscreens` dashboard, `?only=<slug>` renders just
  that one screen full-size (slugs are the `SCREENS` keys in `screens.js` — e.g. `avatar`, `tokens`,
  `versus`, `trophies`, `optdisplay`); otherwise the page shows the whole rack.
  *(Only if you installed the `/viewscreens` dashboard.)*
- **Live monitor — `https://<your-domain>/livetest?token=<TOKEN>`:** a small live page showing, per
  user, whether Claude is **working / idle / waiting-on-you**, with the raw activity signals and the
  detection thresholds. Handy for confirming detection is tuned right; it's also the signal that drives
  the dashboard/badge avatar. *(Only if you installed the live-activity monitor.)*
- **Raw JSON** (for a hardware badge or your own tooling): `…/claude-stats.json?token=<TOKEN>` (and,
  if installed, `…/claude-limits.json`, `…/competition.json`). Every field is in the
  **[Stats catalog](#stats-catalog)**.
- **Restore from a backup** → [Backups & restore](#backups--restore).
- **Add another machine** → [Remote servers](#remote-servers-fold-in-another-machine).

---

## Competing with a friend (head-to-head)
Two people each run this whole pipeline on their own server(s) and compare **total** Claude Code
usage — 24h / 7d / 30d token races plus streaks, peak day, $ value extracted, night-owl %, leverage,
endurance, words typed, and HUMAN BOTTLENECK time, plus a **per-project breakdown** (the VERSUS
PROJECTS screen). The design is **pull-over-HTTPS** and shares **numbers + project names only**.

**What crosses the wire.** Each side publishes a small `competitor.json` (~2–4 KB) — token windows,
the fun metrics, a 30-day daily series, a per-project breakdown (project **name** + tokens/cost/
prompts/words/active-min/agents), your live session/weekly limits, and your **alias**. Project names
are shared deliberately — the only consumer is the trusted friend you've opted into, who already
knows your projects. It **never** contains prompt or response text, usernames, or session IDs.

**Two tokens — keep them straight.**
- **Master token** (`token.txt`) gates *all your* endpoints (`/viewscreens`, `/claude-stats.json`,
  `/competition.json`). Private — never share it.
- **Peer token** (`peer-token.txt`) gates **only** `/competitor.json`. This is the one you *give to
  your friend* so they can pull your numbers. It can't reach `/viewscreens` or your combined
  `/competition.json`, so handing it out exposes nothing but the aggregate competitor feed.

**`/competitor.json`** = *your* aggregate only (what a friend pulls).
**`/competition.json`** = *you + every fetched peer*, gated by your master token, for your own `/viewscreens`
and badge.

**Set it up (each side does this once):**
1. **Generate a peer token** and gate `/competitor.json` with it:
   ```bash
   python3 -c "import secrets;print(secrets.token_urlsafe(32))" | sudo tee /opt/claude-stats/peer-token.txt
   sudo chmod 600 /opt/claude-stats/peer-token.txt
   ```
   In your nginx vhost, set the `/competitor.json` block's `__PEER_TOKEN__` to that value; keep the
   `/competition.json` block on your master `__TOKEN__`. `nginx -t && systemctl reload nginx`.
2. **Exchange** (out of band — Signal, email, whatever): send your friend **your `competitor.json`
   URL + your peer token**; get theirs back.
3. **Add them to `config.json`** and set your public name:
   ```json
   { "timezone": "America/New_York", "alias": "Maverick",
     "peers": [ { "url": "https://their-domain/competitor.json", "token": "THEIR_PEER_TOKEN", "name": "rival" } ] }
   ```
   Run the **same `timezone`** on both sides so the 24h/7d/30d window edges line up (the race is only
   fair on a shared clock).
4. **Cron, every 2 min** (cheap — reads the ledger, no re-parse), regenerating both feeds and pulling
   each peer:
   ```
   */2 * * * * /usr/bin/python3 /opt/claude-stats/extract.py --mode competitor --server <label> \
       --ledger /opt/claude-stats/ledger.db --config /opt/claude-stats/config.json \
       --limits-file /var/www/stats/claude-limits.json --bottleneck-db /opt/claude-stats/bottleneck.db \
       --peers-dir /var/www/stats/peers --output /var/www/stats/competitor.json \
       --competition-output /var/www/stats/competition.json \
       && /usr/bin/chown www-data:www-data /var/www/stats/competitor.json /var/www/stats/competition.json
   ```
   (Create `/var/www/stats/peers/` — a **server-side cache**, not web-served. If a peer is briefly
   down, its last-good numbers keep showing, flagged stale.)
5. **See it.** Once a peer is configured, the **VERSUS** category appears on `/viewscreens` with four screens:
   the token race + your-vs-rival session/weekly limits, a **HUMAN** comparison (words, prompts,
   leverage, night-owl %, bottleneck), all-time **RECORDS** (streaks, peak day, endurance, cache-hit),
   and a **TROPHIES** face-off. While you have no peer the whole category stays hidden (a single-screen
   preview reads **SOLO / NO RIVAL**) — that's expected.

**More than two players:** append more entries to `peers`. One shared peer token works for everyone;
for per-friend revocation, gate `/competitor.json` with an nginx `map` of accepted tokens instead of
a single `if`. Your own multiple servers are *not* peers — fold them into *your* total with the
**fragment** mechanism (see `docs/architecture.md`); a friend is always kept side-by-side, never
merged.

## Remote servers (fold in another machine)
If you also use Claude Code on **another server**, add it as a **fragment node**: it ships only its
own per-session usage to this (main) server every minute and shows up in `meta.servers` and every
total. One interactive script on **main** does the whole setup — and the same script updates remotes
after a code change. Full details: [`docs/remote-fragment.md`](docs/remote-fragment.md).

```bash
# add a remote (asks for user@host, a label, timezone, and THIS server's DOMAIN — not its IP)
sudo ./server/pipeline/provision-remote.sh

# list / update provisioned remotes (run after changing pipeline code, e.g. tuned detection)
sudo ./server/pipeline/provision-remote.sh --list
sudo ./server/pipeline/provision-remote.sh --update all        # or: --update <label>

# optional: also stream this remote's fast ~2 s working/idle/waiting status (drives the avatar)
sudo ./server/pipeline/provision-remote.sh --enable-live <label>
```

- **No passwordless sudo:** you paste one key-append line on the remote, then enter its sudo password
  **once** per run. Adding a 3rd/4th server is the same command with a new host + label.
- **Locked-down receiver:** remotes upload over **sftp-only** into a `statsuser` whose only writable
  path is `fragments/` (key pinned to `internal-sftp`, no shell). The remote needs no GitHub access —
  code is copied from main, and a registry under `/opt/claude-stats/remotes.d/` tracks every remote.
- **Cadence:** usage ships every minute. A separate, faster **~2 s working/idle/waiting** status channel
  (it drives `/livetest` and the `/viewscreens` avatar) is available — enable it per remote with
  `--enable-live <label>` (above). It ships only while a session is active, over a multiplexed SSH
  connection that reuses the sftp key, and main merges every remote into one aggregate. See the doc.

## Updating
```bash
git pull
sudo ./server/deploy.sh      # re-installs code only; leaves config.json, token.txt, ledger.db intact
```
After changing pipeline code, also push it to any remotes: `sudo ./server/pipeline/provision-remote.sh --update all`.

## Backups & restore
`deploy.sh` takes a **timestamped snapshot before every update**, and the full run takes one **every
~3 hours** — so a bad deploy or a corrupted run is recoverable. Each snapshot is one dir under
`/opt/claude-stats/backups/<timestamp>/` holding a *consistent set*: `ledger.db` + `bottleneck.db`
(via SQLite's online backup, safe under the live crons) plus `config.json`/`token.txt`/`peer-token.txt`.
Retention is **grandfather-father-son**: every snapshot from the **last 24 h** is kept (fine same-day
rollback) plus the **newest one per day for 30 days**; the dir is root-only `700`. (The cheap rolling
`ledger.db.bak` still exists for an instant one-step undo.)

- **Force one anytime:** `sudo python3 /opt/claude-stats/extract.py --mode backup`
- **Restore** (manual, deliberate): stop the crons (or `systemctl stop` the timer), then
  ```bash
  sudo cp /opt/claude-stats/backups/<timestamp>/ledger.db     /opt/claude-stats/ledger.db
  sudo cp /opt/claude-stats/backups/<timestamp>/bottleneck.db /opt/claude-stats/bottleneck.db
  ```
  and re-enable the crons. (Restore is never automatic — you choose which snapshot.)

## Uninstall
Stop and remove everything the installer created:
- **Root crons** — remove every one you added: the 5-min stats cron, and (if installed) the ~2-min
  limits-feed cron and the ~2-min competition cron (`crontab -e`, or delete the `/etc/cron.d` files).
- **logrotate policy** — `rm -f /etc/logrotate.d/ccstats` (on remotes: `/etc/logrotate.d/ccstats-fragment`).
- **systemd services** (whichever you enabled): `systemctl disable --now claude-live-monitor
  claude-bottleneck-monitor`, delete their unit files in `/etc/systemd/system/`, then `daemon-reload`.
- **nginx** — remove the `sites-enabled` symlink (and the `sites-available` vhost), `nginx -t`, reload;
  if you used a domain, optionally `certbot delete --cert-name <domain>`.
- **Files** — remove `/opt/claude-stats` and `/var/www/stats`.

(Back up `ledger.db` — and `bottleneck.db` if you ran the competition — first if you want to keep your
all-time history.)

## Stats catalog
*Every metric the pipeline computes — so it's clear what you can surface on the badge, `/viewscreens`, or the
competition. **Most are gathered even if no screen shows them yet**, so adding one to the UI is usually a
render change, not a data change. Exact JSON shapes are in [`docs/schema.md`](docs/schema.md).*

These come from four feeds. **Section A is the main all-time usage feed — *not* the competition**;
sections C–D are the limits and live-activity feeds. Everything is here, grouped by which file produces it:

### A. `claude-stats.json` — all-time usage, across the whole fleet (badge + `/viewscreens` screens; **this is the primary, non-competition feed**)
- **Volume:** `tokens_total`, `tokens_input`, `tokens_output`, `tokens_cache_read`, `tokens_cache_create`,
  `cache_hit_ratio`; `cost_estimate` (`total_usd` + per-category `input/output/cache_read/cache_create_usd`,
  plus `pricing_date` and a `note`).
  ⚠️ `tokens_total` is usually **cache-read-dominated** — prefer `tokens_output` (or input+output) for a
  "real work" headline.
- **Activity:** `sessions`, `work_sessions` (timeline split on >20 min gaps), `active_days`,
  `current_streak`, `longest_streak`, `longest_session_min` (endurance), `avg_session_min`,
  `total_active_min`, `nightowl_active_min` (active minutes in local 00:00–05:59).
- **Human input:** `user_prompts`; `user_words` (real whitespace words, URLs stripped); `user_chars`
  (URL-stripped); `user_chars_typed` ("true typed" — also drops pasted ```fenced``` / `inline` code).
  All exclude auto-generated compaction/continuation summaries (`isCompactSummary`) and pasted
  markdown documents (a prompt with ≥3 structural markers — `##`+ headers plus `**bold**` spans — is
  treated as pasted/generated, not hand-typed, and dropped whole).
- **Patterns / time-of-day:** `histograms.hours[24]`, `histograms.weekdays[7]`,
  `histograms.weekday_hour[7][24]` (Mon×hour joint matrix — the true "busiest weekday+hour"),
  `peak_hour`, `peak_weekday`; `daily_activity[]` (every day zero-filled → heatmap; each day carries
  `prompts`, `tokens`, `tokens_io`, `active_min`, `words`, `sessions`); `top_tools[]` + `tool_uses`;
  `models[]` (turns + %) + `favorite_model`.
- **Per project** (`projects[]`, one per Linux user / fragment by default, or one per Claude Code
  working dir under `project_granularity: directory` — see [`docs/projects-layout.md`](../docs/projects-layout.md)): `name`, `server`, `sessions`,
  `work_sessions`, `active_days`, `tokens_total`, `user_words`, `user_prompts`, `tool_uses`,
  `cost_estimate_usd`, `total_active_min` / `longest_session_min` / `avg_session_min` (active time
  spent in the project), `last_active`.
- **meta:** `schema_version`, `generated_at`, `timezone`, `corpus_start`/`corpus_end`/`corpus_days`,
  `servers[]`.

### B. `competitor.json` / `competition.json` — head-to-head, per rolling window
Each of **24h / 7d / 30d / all** (`windows[...]`): `tokens_total` (all, incl. cache), `tokens_input`,
`tokens_output` (lead with **input+output** for a cache-free "work done" race — `tokens_total` is usually
cache-read-dominated), `cost_usd`, `prompts`, `words_typed`, `active_days`, `night_owl_pct` (share of
tokens in 00:00–05:59), `leverage_tokens_per_prompt`, `bottleneck_sec` (HUMAN BOTTLENECK time — seconds
blocked on an `AskUserQuestion`).
- **Global records** (`metrics`): `current_streak`, `longest_streak`, `peak_day{date,tokens}`
  (+ `peak_day_io` and a `record_day_*` family — `prompts`/`words`/`active_min`/`sessions`/`cost`),
  `endurance_longest_session_min`, `sessions`, `work_sessions`, `active_days`, `total_active_min`,
  `nightowl_active_min`, `words_typed_total`, `prompts_total`, `tokens_total_all`, `tokens_output_all`,
  `cost_usd_all`, `cache_hit_ratio`, `bottleneck_sec_total`. *(Full shapes in [`docs/schema.md`](docs/schema.md).)*
- **Trend:** `daily[]` (last 30 days: `date`, `tokens`, `output`, `prompts`).
- **Per project:** `projects[]` (`name`, `tokens_total`, `tokens_input`, `tokens_output`,
  `cost_estimate_usd`, `user_prompts`, `user_words`, `total_active_min`, `agent_launches`) — drives
  the VERSUS PROJECTS screen.
- **Live limits** (`limits`, folded from `claude-limits.json`): session (5-hour) + weekly (7-day)
  utilization % and reset countdowns, plus `session_limit_hits`/`weekly_limit_hits` (times you crossed
  67% — these feed the SESSION/WEEKLY PUSH trophies).
- **Identity:** `alias` + per-project **names** are shared (the friend is trusted/opted-in) — but
  **no** prompt/response text, usernames, or session IDs ever leave the box.

### C. `claude-limits.json` — session/weekly limits (optional; the USAGE screen)
Polled from the Claude OAuth usage endpoint every ~2 min. Each of `session` (5-hour), `weekly` (7-day),
`weekly_opus`, `weekly_sonnet`: `utilization` (%), `resets_at` (absolute), `resets_in_sec`. Plus
`extra_usage` (`is_enabled`, `used_credits`, `monthly_limit`, `utilization`, `currency`); two cumulative
counters `session_limit_hits`/`weekly_limit_hits` (distinct windows that hit ≥67%); and the feed's own
`schema_version`, `generated_at`, `stale`, `error`, `source`. (Reset countdowns are recomputed
client-side from `resets_at`, so they stay exact even if the feed is briefly stale.)
**Stale values stay truthful:** the poller can only read a token while a Claude Code session is
running, so `stale: true` also means *no session is running* — utilization can't move, and the
held last-known values remain exact. Once a held window's `resets_at` passes, the limit has reset,
so the poller zeroes that bucket (`utilization: 0`, `resets_at: null`). The `/viewscreens` USAGE chip
shows this state as **HELD** (gold); **STALE** is reserved for a dead feed (poller not writing).

### D. `live-status.json` — live working/idle/waiting (optional monitor; ~2 s cadence; drives the avatar)
- **Global:** `status` (the "am I working anywhere" roll-up: `working` / `idle` / `waiting` / `no_processes`),
  `server`, `servers[]`, `updated_at`. *(The avatar's **`done`** state is **not** a feed value — `/viewscreens`
  and the badge synthesize it client-side for 15 s on a `working`→`idle` transition.)*
- **Per user** (`users[<server:user>]`): `status`, `act_status`, `net_bps`, `io_bps`, `signals`,
  `waiting` (blocked on an `AskUserQuestion`), `waiting_sessions[]`, `pids[]`, `since`.
- `thresholds.*` are detection **tuning knobs** (debounce, byte/IO rates, sample interval…), not metrics.
- **`celebrate`** (optional, badge-facing): present for ~3 min after you break a personal record or
  tier up a trophy — the badge avatar throws a little party (hop + confetti + bubble). Detected
  server-side by the competition cron; see `docs/schema.md`.

### F. `content-pack.json` — the badge avatar's message banks (optional)
Working-ticker words, waiting/limit/streak quips, book taunts, and idle quotes, in one token-gated
static file — **edit `server/pipeline/content-pack.json` and redeploy to change what the badge says, no
firmware release needed** (bump `meta.pack_version`; the badge re-fetches ~daily and falls back to
its baked-in defaults if the endpoint is missing). ASCII only, ~60 chars per line; schema +
authoring rules in `docs/schema.md`.

### E. Derivable but not yet emitted (small code change in `extract.py`)
The per-session `model_tokens` + hourly maps make most "by time window / by model" cuts cheap to add:
per-window endurance/streaks, per-model token splits per window, tool-usage head-to-head, per-project
`user_chars_typed`, etc.

## Hacking on it (firmware & dashboard)

If you're changing the badge firmware or the `/viewscreens` dashboard rather than just running the
server, two docs save a lot of time:

- **[`docs/useful-notes.md`](../docs/useful-notes.md)** — the practical development knowledge: how
  the firmware mirrors `viewscreens/` 1:1, verifying a dashboard change with headless Chromium, the
  `mpremote` dev loop, and working on the badge over serial.
- **[`docs/device-pitfalls.md`](../docs/device-pitfalls.md)** — hard-won platform gotchas (grid-exact
  fonts, input vs frame cost, the mount bridge, install/launch verification). Read it before touching
  fonts, input, drawing or the installer.

## Repo layout (server side)

This is the server half of the single `ccstats` repo; paths below are relative to the repo
root. The badge firmware (`firmware/`, `tools/`) is documented in the **root `README.md`**.
```
server/
  pipeline/   extract.py, pricing.json, content-pack.json, provision-remote.sh, ship-fragment.sh
              core: parser + all-time ledger + cost + competition feed;
              provision-remote.sh adds/updates fragment remotes (it installs
              ship-fragment.sh on each remote to push that node's usage to main)
  monitor/    live-monitor.py, livetest-index.html  optional working/idle/waiting detector
              usage-monitor.py               optional session/weekly limits feed (USAGE screen)
              bottleneck-monitor.py          optional durable HUMAN BOTTLENECK accumulator (competition)
  nginx/      stats-site.conf.template       vhost template (placeholders incl. __PEER_TOKEN__)
  systemd/    claude-live-monitor.service.template  claude-bottleneck-monitor.service.template
  config.example.json   deploy.sh
viewscreens/  index.html, pico.js, screens.js, fonts/, build-fonts.py
              the dashboard /viewscreens (canvas, PicoGraphics-style);
              also the design spec the firmware is ported from
docs/         architecture.md, schema.md, remote-fragment.md
              device-pitfalls.md, useful-notes.md   (firmware/dashboard dev)
```
The bundled fonts keep their own licenses (see the root `README.md` font credits and
`viewscreens/fonts/`). See `docs/architecture.md` for how it works and `docs/schema.md` for the
JSON contract.
