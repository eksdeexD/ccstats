# Changelog

## 1.3.1 — 2026-07-03

Bugfix: on the main server, `deploy.sh`'s de-root migration now pre-creates the
`/var/log/ccstats/*.log` unit logs owned by `ccollector` (and re-owns root-created ones on
already-migrated boxes). systemd's `StandardOutput=append:` creates missing files as root, which
the `su ccollector` logrotate rule could neither truncate nor recreate — so rotation silently
skipped them. Peers already got this in v1.3.0 via `migrate-peer.sh`. Apply with the normal
`git pull && sudo ./server/deploy.sh`.

## 1.3.0 — 2026-07-03

**Fragment nodes (peers) no longer run as root** — the peer half of the v1.2.1 de-root:

- The every-minute root cron (`/etc/cron.d/ccstats-fragment`) becomes `ccstats-fragment.timer`
  + `.service`, running `ship-fragment.sh` as the unprivileged `ccollector` user with
  `CAP_DAC_READ_SEARCH` only, sandboxed exactly like main's oneshots (`ProtectSystem=strict`,
  `ProtectHome=tmpfs` + scope-refresher drop-ins, `NoNewPrivileges`, `PrivateTmp` — safe: the
  fragment/limits tmp files and the sftp upload share the unit). Log:
  `/var/log/ccstats/fragment.log` (logrotate updated; the legacy log rotates until it ages out).
- The sftp **data key moves out of `/root/.ssh`** to `/var/lib/ccstats/.ssh/ccstats_frag`
  (ccollector, 0600, seeded `known_hosts`). `ship-fragment.sh` takes the key path as an optional
  3rd arg / `CCSTATS_FRAG_KEY` env with per-uid defaults, so it stays fully root-compatible on
  un-migrated peers.
- A peer live monitor is re-rendered onto the shared de-rooted template (`ccollector` +
  `CAP_SYS_PTRACE`, per-box `ExecStart` ship args preserved, `RuntimeDirectory=ccstats` for the
  shipper's ssh ControlPath). The scope refresher now runs on peers too — new users are picked
  up automatically, zero manual steps.
- **Migration is automatic from the MAIN server**: every `provision-remote.sh` path (fresh
  provision, `--update`, `--enable-live`) ships a kit and runs the new `migrate-peer.sh` on the
  peer — idempotent and fail-safe: the root cron is retired only after one shipment is verified
  through the new unit (explicit `OK ... shipped` markers in the ship log), everything displaced
  is quarantined in a dated dir (one `mv` from rollback), and any failure restores root mode
  with a clear notice. systemd < 240 peers decline and stay root-mode (same threshold as main).
  A hand-added `ship-limits.sh` cron (the pre-1.3.0 cross-server limits stopgap) is quarantined
  too — `ship-fragment.sh` has shipped the limits reading every minute since the gap was closed.
- Data formats and the upload contract are unchanged: a v1.2.1 main accepts a v1.3.0 peer and
  vice versa. `deploy.sh` still deliberately skips peer boxes (they migrate via
  `provision-remote.sh`, never via `deploy.sh`).

## 1.2.1 — 2026-07-02

Firmware and server now share **one project version** (this file + `firmware/version.py`
+ the git tag move together; no separate firmware numbering).

**The pipeline no longer runs as root.** Everything now runs as a dedicated unprivileged
system user, `ccollector`, in sandboxed systemd units:

- Root crons → systemd timers: `ccstats-extract.timer` (5 min), `ccstats-usage.timer`
  (2 min), `ccstats-competitor.timer` (2 min, odd minutes), plus an on-demand
  `ccstats-backup.service`. The two daemons (`claude-live-monitor`,
  `claude-bottleneck-monitor`) keep their names but drop root.
- Privileges are exactly two capabilities: `CAP_DAC_READ_SEARCH` (read-only access to the
  0600 `~/.claude` files — the product's function) and, for the live monitor only,
  `CAP_SYS_PTRACE` (`/proc/<pid>/io` for the working/idle signal). Units are sandboxed
  (`ProtectSystem=strict`, `ProtectHome=tmpfs` + explicit bind-mounts, `NoNewPrivileges`,
  `PrivateTmp`, …) so only `~/.claude` dirs and `~/projectname.txt` are visible, and writes
  are confined to `/opt/claude-stats`, `/var/www/stats`, `/var/log/ccstats`.
- **New users are still picked up automatically**: a root-owned scope refresher
  (`ccstats-refresh-scope`, path watch on `/home` + 10-min sweep) rebinds new users'
  `~/.claude` into the sandbox — zero manual steps, same as before.
- **Updating is unchanged:** `git pull && sudo ./server/deploy.sh` migrates existing
  installs automatically, idempotently, and fail-safe — if any step fails, the previous
  root crons/units are restored and the box keeps running exactly as before, with a
  pointer to the assisted path (`docs/migrate-derootify.md`, a Claude Code playbook).
  `--no-migrate` skips the step on purpose.
- Ownership split: state (ledger, dbs) → `ccollector`; code + secrets (config, tokens,
  remote keys) → the operator (repo-checkout owner), who joins the `ccollector` group for
  read access to state. On boxes with a non-root operator, later code deploys work
  **without sudo**: `./server/deploy.sh` (service restarts via narrow scoped-sudo rules,
  if granted).
- Logs move to `/var/log/ccstats/*.log` (logrotate policy updated; legacy
  `/var/log/claude-stats*.log` still rotated until it ages out).
- `provision-remote.sh` no longer regenerates the main live-monitor unit (which would
  have re-rooted it) — it only swaps the `ExecStart=` line when enabling merge; and it
  keeps the webroot ccollector-owned on de-rooted boxes (it used to re-own it to root,
  which broke the collectors' feed writes).
- Fragment nodes (peers) are unchanged this release — still root cron + sftp; their
  de-root ships in a later release via `provision-remote.sh`. All scripts remain fully
  root-compatible for legacy/peer boxes.

## 1.1.1 and earlier

Predate this file — see the git history. 1.1.1 (battery charging-sweep fix) was the
last root-mode release.
