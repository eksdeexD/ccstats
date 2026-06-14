# Remote servers (fragment nodes) — add & update

Stats normally cover just the machine the pipeline runs on. To fold in **another server where you
also use Claude Code**, that server runs in **fragment** mode: every minute it emits only its own
per-session usage and uploads it to the main (aggregator) server, which ingests it into the shared
all-time ledger. The remote needs **no** `/viewscreens`, monitor, nginx, token, or ledger of its own — it
is a pure data source. The main JSON then lists it in `meta.servers` and folds it into every total.

One script on the **main** server does everything:

```bash
sudo ./server/pipeline/provision-remote.sh             # add a new remote (interactive)
sudo ./server/pipeline/provision-remote.sh --list       # list provisioned remotes
sudo ./server/pipeline/provision-remote.sh --update <label>|all   # re-push code after a change
```

## Adding a server

Run `sudo ./server/pipeline/provision-remote.sh` on main. It asks for:

- **`user@host`** — your normal SSH login on the remote (e.g. `you@server2.example.net`). A sudo-capable user.
- **label** — short unique name for the server (the ledger key prefix; `main` is reserved).
- **timezone** — defaults to main's (match it so the rhythm histograms line up).
- **main domain** — this server's **stable DOMAIN** the remote uploads to (e.g. `stats.example.net`).
  Use the domain, **not the IP** — the IP can change; the domain must resolve here and be
  SSH-reachable on port 22.

Then it prints **one line to paste on the remote** and does the rest. You enter the remote's sudo
password **once**.

### The two SSH directions (the whole model)

| | Direction | When | Auth |
|---|---|---|---|
| **Provisioning** | main → remote | setup & each update | logs in as **your** `user@host`; root steps via `sudo`, password entered **once** per run |
| **Data upload** | remote → main | every minute | a key generated **on the remote**; its public half is wired into `statsuser` here automatically (sftp-only) |

**No passwordless sudo is ever configured.** The line you paste only appends the script's key to
*your own* `~/.ssh/authorized_keys` (no sudo, no new user in the paste). The script then logs in as
you and runs the privileged setup through a single interactive `sudo` session (`sudo -v` up front →
one prompt). Private keys never move; you copy exactly one key, by paste, once.

### What it installs

- **On the remote:** `extract.py`, `pricing.json`, `config.json`, and `ship-fragment.sh` in
  `/opt/claude-stats`; source copies in `/home/ccstats` (mirroring main's edit-here/deploy-to-/opt
  split); a data key in `/root/.ssh/ccstats_frag`; main's host key pre-trusted; and a **root cron**
  (`/etc/cron.d/ccstats-fragment`) that runs `ship-fragment.sh` every minute (fragment + sftp upload).
  No GitHub access is needed on the remote — code is copied from main.
- **On main (first run, idempotent):** a locked-down `statsuser`, the writable `fragments/` dir, the
  remote's upload key, and a registry entry in `/opt/claude-stats/remotes.d/<label>.conf`.

It finishes by running one upload immediately and confirming `fragments/<label>.json` arrived.

## Updating a server (after a code change)

When you change the pipeline (e.g. tuning idle/working detection), redeploy it to every remote:

```bash
sudo ./server/pipeline/provision-remote.sh --update all      # or: --update <label>
```

It re-pushes `extract.py` + `pricing.json` to each registered remote and (if the live channel is
enabled for it) restarts the monitor. You enter each remote's sudo password once. The registry
(`/opt/claude-stats/remotes.d/`) is the source of truth for which remotes exist.

## How `statsuser` is locked down

- **No password**, shell `/usr/sbin/nologin` — no interactive login.
- The upload key is restricted to **`restrict,command="internal-sftp"`** — the connection can only
  run the SFTP subsystem: **no shell, no command execution, no port-forwarding, no agent**.
- Even over SFTP it can only write where `statsuser` has filesystem permission — and the **only**
  thing it owns/can write is the `fragments/` dir (`2775`). Nothing else on the box is writable by it.

To tighten further you can add a `Match User statsuser` / `ChrootDirectory` block in `sshd_config`,
but the per-key `internal-sftp` + filesystem perms above already prevent shell access and writes
outside `fragments/`.

## Cadence & the live status channel

Two channels at different cadences:

- **Usage / tokens** ship every **minute** — a relaxed cadence is fine for cumulative usage.
- **working / idle / waiting** updates every **~2 s** (drives `/livetest` and the `/viewscreens`
  status avatar). Enable it per remote:

  ```bash
  sudo ./server/pipeline/provision-remote.sh --enable-live <label>
  ```

  This wires up both sides:
  - **Remote:** runs `live-monitor.py` as a systemd service and a **shipper thread** pushes its
    `live-status.json` up to main over a **multiplexed SSH connection** (`ControlMaster`) — one
    handshake, reused every 2 s. It only ships while a session has been live within the **grace
    window** (default 30 min); past that it stops and the tunnel drops on its own, reconnecting when
    activity resumes. Uploads reuse the existing sftp data key into `live-remote/` on main.
  - **Main:** runs its monitor with `--merge-dir`, folding every remote's file into one aggregate
    `live-status.json`. The top-level `status` is the **global** "am I working *anywhere*" — a remote
    whose file is older than `--stale-seconds` (tunnel dropped) can't report `working` (forced idle),
    so the global state never sticks. `/livetest` shows each user with its server label.

  The registry's `live=` flag is flipped to `1`, so `--update` thereafter also pushes the monitor and
  restarts the remote service. **Re-verify the process matcher** on the remote (how `claude` appears
  in `/proc/*/cmdline`) — `INCLUDE_SUBSTRINGS`/`EXCLUDE_SUBSTRINGS` at the top of `live-monitor.py`.

## Doing it by hand (no script)

On the remote: install `extract.py` + `pricing.json` to `/opt/claude-stats`, write a `config.json`
with the timezone, and add a root cron that runs `extract.py --mode fragment --server <label>` then
`sftp`s the output to `statsuser@<main-domain>:/var/www/stats/fragments/<label>.json`. On main:
create `statsuser` (nologin, no password), make `fragments/` writable by it, and add the remote's
public key with `restrict,command="internal-sftp"`.
