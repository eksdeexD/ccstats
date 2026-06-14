# Projects layout — adapting discovery to your machine

This doc explains how the pipeline decides what counts as a **project**, and how to adapt it to a
setup that differs from the default. It is written so a coding agent (e.g. Claude Code) can read it
and apply the right change during setup.

> TL;DR — the default is **one project per Linux user**. If instead you run several projects under
> **one** user account (`/home/you/app`, `/home/you/blog`, …), set
> `"project_granularity": "directory"` in `config.json`. Nothing else is required.

## How discovery works

The extractor reads Claude Code's session transcripts. Claude Code stores every session under the
user's home as `~/.claude/projects/<encoded-cwd>/<sessionId>.jsonl`, where `<encoded-cwd>` is the
working directory it was launched in (with `/` and other characters replaced by `-`). Each transcript
record also carries the exact working directory in a `"cwd"` field.

The relevant code is all in [`server/pipeline/extract.py`](../server/pipeline/extract.py):

- `discover_projects(home_glob)` globs `--home-glob` (default `/home/*`) and, for each home directory
  that contains `.claude/projects/`, yields one entry — `user` (the home's basename) plus a project
  display name.
- `group_files()` collects every `*.jsonl` under that user's `.claude/projects/` tree, keyed by
  session id.
- `project_name(mode, …)` assigns each session a project name according to the chosen
  **granularity** (below).
- Sessions are aggregated **grouped by project name only**, so the same project name seen on several
  machines folds into one row.

## The one knob: `project_granularity`

Set it in `/opt/claude-stats/config.json` (or pass `--project-granularity` on the command line, which
overrides the config). Default is `user`.

| Value | One project = | Project name comes from |
|---|---|---|
| `user` *(default)* | one Linux user account | the username, or `~/projectname.txt` if present |
| `directory` | one Claude Code working directory | the `cwd` recorded in the transcript (its basename) |

```jsonc
// config.json
{ "project_granularity": "directory" }
```

## Pick your scenario

**1. One project per machine/user (the default) — do nothing.**
You run Claude Code as one user whose work is conceptually a single project (e.g. a dedicated VM or
account per project). Leave `project_granularity` at `user`. Each user becomes one `projects[]` row,
named after the account.

**2. Several projects under ONE user account → `directory` mode.**
You run Claude Code from `/home/you/app`, `/home/you/blog`, `/home/you/infra`, all as the same user.
In `user` mode these collapse into a single project named after your account. Set
`"project_granularity": "directory"` and each working directory becomes its own row (`app`, `blog`,
`infra`), named from the transcript's `cwd`. Run the pipeline once and check `projects[]`.

**3. Projects are separate Linux users, but homes aren't under `/home` → `--home-glob`.**
If accounts live elsewhere (e.g. `/srv/*`, `/data/users/*`), point discovery there by passing
`--home-glob '/srv/*'` (quote it) to the `extract.py` cron command. Combine with either granularity.

**4. Rename or merge projects.**
- `user` mode: drop a `~/projectname.txt` in a user's home containing the display name you want. Two
  users sharing the same `projectname.txt` (e.g. the same project on two machines) fold into one row.
- `directory` mode: the name is the directory's basename — rename the working directory to rename the
  project. There is no per-directory override file.

**5. Exclude an account from the stats.**
Put the single word `ignore` in that user's `~/projectname.txt`. The account (and the pipeline's own
service account, if it shouldn't count) is skipped entirely. This works in **both** modes.

## Caveats for `directory` mode

- The name is the working directory's **basename**, so two different directories that share a
  basename — `/home/you/app` and `/home/them/app`, or `~/work/api` and `~/play/api` — **merge into one
  project** named `app`/`api`. If you need them separate, give the directories distinct basenames.
- A session whose transcript carries no `cwd` (very old or unusual transcripts) falls back to the
  user name for that session only.
- `~/projectname.txt` renaming does **not** apply in `directory` mode (its `ignore` exclusion still
  does). Naming is purely from the directory.

## Applying it during setup

1. Decide the scenario above with the operator.
2. Set `project_granularity` (and `--home-glob` if needed) — config for the persistent value, or the
   CLI flag to try it once.
3. Run the full pipeline and inspect the `projects[]` array in the generated
   `claude-stats.json` (or run `--mode fragment` and inspect the per-session `project` fields) to
   confirm the split matches expectations before wiring up the cron.
