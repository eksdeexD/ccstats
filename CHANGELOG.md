# Changelog

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
  have re-rooted it) — it only swaps the `ExecStart=` line when enabling merge.
- Fragment nodes (peers) are unchanged this release — still root cron + sftp; their
  de-root ships in a later release via `provision-remote.sh`. All scripts remain fully
  root-compatible for legacy/peer boxes.

## 1.1.1 and earlier

Predate this file — see the git history. 1.1.1 (battery charging-sweep fix) was the
last root-mode release.
