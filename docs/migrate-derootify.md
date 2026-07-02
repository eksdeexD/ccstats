# De-root migration (v1.2.1) — agent playbook

**Audience: a coding agent (Claude Code) opened in this repo on the box to migrate.**
`sudo ./server/deploy.sh` performs this migration automatically; this document exists
for when that automatic path was skipped or failed, or when the operator wants it done
step by step with a human in the loop. It is idempotent and safe to re-run.

---

## Step 0 — explain, inspect, and get explicit consent

Before changing anything, tell the operator — briefly, in your own words:

> Until v1.1.1 the ccstats pipeline ran as **root** (root crons + two root daemons),
> because it must read every user's `~/.claude` files (0600). v1.2.1 moves it to a
> dedicated unprivileged user, **`ccollector`**, whose systemd units get exactly two
> narrow privileges: `CAP_DAC_READ_SEARCH` (read-only access to those files) and — for
> the live monitor only — `CAP_SYS_PTRACE` (to read `/proc/<pid>/io` for the
> working/idle signal). The units are sandboxed so only `~/.claude` dirs (plus
> `~/projectname.txt`) are even visible, and writes are confined to
> `/opt/claude-stats`, `/var/www/stats` and `/var/log/ccstats`. Nothing changes in
> the feeds, the badge, the dashboard, tokens, or the ledger. Rollback is one step.

Then **inspect this box** and report what you find (do not assume another machine's
layout):

1. `systemctl --version` — need systemd ≥ 240 and `/run/systemd/system` present.
2. Which components are installed under `/opt/claude-stats`? (`extract.py` always;
   `usage-monitor.py`, `live-monitor.py`, `bottleneck-monitor.py` optional.)
3. Where do the legacy root jobs live? Check `sudo crontab -l` and `/etc/cron.d/*`
   for lines mentioning `claude-stats`. **Diff their flags against the canonical
   commands** in `server/systemd/*.service.template` — hand-customized flags (a
   different webroot, `--home-glob`, extra options) must be carried over.
4. Is this a **fragment node** (peer)? If `/etc/cron.d/*` references
   `ship-fragment.sh`, STOP: peers are migrated from the MAIN server, not with
   this playbook — run `sudo ./server/pipeline/provision-remote.sh --update
   <label>` there (v1.3.0+; it ships and runs `migrate-peer.sh` on the peer,
   idempotently and fail-safe). Nothing to do on the peer itself.
5. Who is the **operator** — the non-root user owning this repo checkout (if any)?
   They will own the code + secrets and join the `ccollector` group.

**Ask the operator to confirm before proceeding** (one question, yes/no), including
anything box-specific you found in 3.

## Step 1 — collector user, group, dirs

```bash
sudo useradd --system --user-group --home-dir /var/lib/ccstats --create-home \
     --shell /usr/sbin/nologin ccollector          # skip if it exists
sudo usermod -aG ccollector <operator>             # only if a non-root operator
sudo install -d -m750 -o ccollector -g ccollector /var/log/ccstats
```

## Step 2 — scope refresher (automatic new-user pickup)

```bash
sudo install -m755 server/pipeline/refresh-scope.sh /usr/local/sbin/ccstats-refresh-scope
```

Install `server/systemd/ccstats-scope-refresh.{service,path,timer}.template` to
`/etc/systemd/system/` (drop the `.template` suffix; they contain no placeholders).

## Step 3 — units and timers

For each installed component, render the matching template from `server/systemd/`
into `/etc/systemd/system/` (drop `.template`), replacing `@OPT@` →
`/opt/claude-stats`, `@WEB@` → `/var/www/stats`, `@SERVER@` → the `server` value in
`config.json` (default `main`):

| Component (if present)              | Units                                              |
|-------------------------------------|----------------------------------------------------|
| always                              | `ccstats-extract.service` + `.timer`, `ccstats-backup.service` |
| `usage-monitor.py`                  | `ccstats-usage.service` + `.timer`                 |
| competition feeds in the webroot    | `ccstats-competitor.service` + `.timer`            |
| `live-monitor.py`                   | `claude-live-monitor.service` — **preserve the existing unit's `ExecStart=` line verbatim** (it carries per-box args like `--merge-dir`) |
| `bottleneck-monitor.py`             | `claude-bottleneck-monitor.service`                |

Back up any unit you overwrite. If step 0.3 found customized cron flags, port them
into the rendered `ExecStart=` lines now.

## Step 4 — ownership

```bash
OPT=/opt/claude-stats; WEB=/var/www/stats; OPERATOR=<operator-or-root>
sudo chown ccollector:ccollector $OPT/{ledger.db,ledger.db.bak,bottleneck.db,milestones.json,celebrations.json,limit-hits.json,usage-poll-state.json} 2>/dev/null
sudo chmod g+r $OPT/{ledger.db,ledger.db.bak,bottleneck.db} 2>/dev/null
sudo chown -R ccollector:ccollector $OPT/backups $OPT/__pycache__ 2>/dev/null
sudo chmod 750 $OPT/backups
sudo chown $OPERATOR $OPT/{config.json,token.txt,peer-token.txt} 2>/dev/null
sudo chown -R $OPERATOR $OPT/remotes.d $OPT/remote-keys 2>/dev/null
# non-root operator only (enables sudo-less future deploys):
sudo chown $OPERATOR $OPT/*.py $OPT/pricing.json
sudo chown -R $OPERATOR:www-data $WEB/viewscreens $WEB/livetest $WEB/content-pack.json 2>/dev/null
# both cases:
sudo chown $OPERATOR:ccollector $OPT && sudo chmod 2775 $OPT
sudo chown ccollector:www-data $WEB
sudo chown ccollector $WEB/{claude-stats.json,claude-limits.json,competitor.json,competition.json,live-status.json} 2>/dev/null
sudo chown -R ccollector:ccollector $WEB/peers 2>/dev/null
```

Leave `fragments/`, `limits-remote/`, `live-remote/` alone (statsuser owns them).

## Step 5 — switch over

```bash
sudo /usr/local/sbin/ccstats-refresh-scope       # writes the BindReadOnlyPaths drop-ins
sudo systemctl daemon-reload
sudo systemctl enable --now ccstats-scope-refresh.path ccstats-scope-refresh.timer \
     ccstats-extract.timer                        # + ccstats-usage.timer / ccstats-competitor.timer if installed
sudo systemctl enable --now claude-live-monitor claude-bottleneck-monitor   # if installed
```

Now retire the legacy root jobs — **only after the next step verifies**, or move
them to a quarantine dir first so they're one `mv` away from restoration:
remove the `claude-stats` lines from root's crontab and move any matching
`/etc/cron.d/*` files aside (e.g. into `/opt/claude-stats/backups/derootify-<date>/`).

## Step 6 — verify

```bash
sudo systemctl start ccstats-extract.service
stat -c '%y %U' /var/www/stats/claude-stats.json     # fresh timestamp, owner ccollector
systemctl is-active claude-live-monitor claude-bottleneck-monitor   # if installed
systemctl list-timers 'ccstats-*'
curl -fsS "https://<domain>/claude-stats.json?token=$(cat /opt/claude-stats/token.txt)" >/dev/null && echo FEED OK
tail -n5 /var/log/ccstats/extract.log
```

Also confirm the token gate still 403s without the token, and — if the live monitor
is installed — that `/live-status.json` keeps updating (owner `ccollector`).

## Rollback (if anything is wrong)

```bash
sudo systemctl disable --now ccstats-extract.timer ccstats-usage.timer \
     ccstats-competitor.timer ccstats-scope-refresh.path ccstats-scope-refresh.timer
# restore the quarantined crontab lines / cron.d files, and the backed-up
# claude-live-monitor / claude-bottleneck-monitor units, then:
sudo systemctl daemon-reload && sudo systemctl restart claude-live-monitor claude-bottleneck-monitor
```

The scripts are fully root-compatible, so the restored root mode works with current
code — rollback does not require downgrading.

## FAQ

- **Why capabilities instead of file ACLs?** Claude Code creates its files with mode
  `0600`; POSIX ACL inheritance derives the mask from the create mode, which silently
  disables inherited named-user read entries. ACLs would break on exactly the files
  that matter (`.credentials.json` is recreated every few minutes).
- **Why does only the live monitor get `CAP_SYS_PTRACE`?** It reads `/proc/<pid>/io`
  (mode 0400) to compute the working/idle signal, and its `ss` child maps sockets to
  pids. The other components read transcripts/sessions (covered by
  `CAP_DAC_READ_SEARCH`) or world-readable `/proc` files.
- **New users?** Picked up automatically: the collectors glob `/home/*`, and the
  scope refresher rebinds `~/.claude` dirs when the user set changes (path watch on
  `/home` + a 10-minute sweep). No manual step.
- **Peers/fragment nodes?** De-rooted since v1.3.0, but via a different path: the
  MAIN server's `provision-remote.sh` (fresh provision, `--update`, `--enable-live`)
  ships and runs `migrate-peer.sh` on the peer — collector user, data key moved to
  `/var/lib/ccstats/.ssh`, root cron → `ccstats-fragment.timer`, verified switch-over
  with root-mode rollback. Never migrate a peer with this playbook or `deploy.sh`;
  see `docs/remote-fragment.md` § "Privilege model on peers".
