# Architecture

The GitHub Manager Bot is an autonomous Python bot that maintains its own repository. It runs daily via GitHub Actions, makes meaningful commits, monitors repo health, opens issues for problems it finds, and (when enabled) proposes self-improvements via pull requests.

---

## Execution Flow

Every run goes through six phases in order:

```
1. BOOTSTRAP   Parse CLI args → load config.yaml → init logger → auth clients
2. LOCK        Write .bot/last_run.json {status: "running"} — prevents concurrent runs
3. PLAN        Call planners (pure functions, no side effects) → produce plan objects
4. EXECUTE     Apply plans via executor.py (all side effects, no decisions)
5. REPORT      Write logs/YYYY-MM-DD.md, commit + push the log file
6. EXIT        exit 0 (no errors) or exit 1 (errors in RunState)
```

The critical architectural rule: **planners only return data, executors only apply data**. No planner touches the filesystem or GitHub API. No executor makes decisions.

---

## Module Reference

### `bot/main.py`
Entry point. Bootstraps everything, runs all phases in order, owns the lock lifecycle. The only place where planners and executors are called together.

- Reads CLI flags (`--dry-run`, `--only`, `--force`, `--no-claude`, `--verbose`)
- `--only=heatmap` restricts `active_planners` to just that subsystem; lock and report always run
- Returns exit code 0 or 1

### `bot/config.py`
Loads and validates `config.yaml` into typed Python dataclasses. All runtime behaviour is controlled here — nothing is hardcoded elsewhere.

- `load(path)` → `Config` — the single entry point; reads YAML, constructs nested dataclasses
- All defaults live here; if a key is missing from YAML, the default in the dataclass applies

### `bot/models.py`
All dataclasses. No logic, no imports beyond stdlib. Everything the planners produce and the executors consume lives here.

See [Data Structures](#data-structures) below.

### `bot/heatmap.py`
**Planner.** Produces a `CommitPlan` for the daily run history commit, or `None` if already done today.

- Reads recent git log to check for today's idempotency marker
- Appends a row to `docs/run_history.md`
- Commit messages are deterministic templates (not Claude-generated)
- Does NOT write any files or run git commands

### `bot/health.py`
**Planner.** Checks repo health and returns a list of `HealthFinding` objects.

Three checks (each independently enable/disableable in config):
- `missing_files` — checks required files exist locally or on GitHub
- `stale_issues` — finds open issues not updated in N days
- `workflow_failures` — checks the last N runs of `bot.yml` for failures

Does NOT open issues or write anything.

### `bot/issues.py`
**Planner.** Converts `HealthFinding` objects into `IssuePlan` objects.

- Deduplicates: skips findings that already have an open issue with label `check:{fingerprint}`
- Uses Claude to write issue bodies; falls back to template if Claude is disabled/unavailable
- Does NOT create issues

### `bot/self_improve.py` *(v1.2 — not yet implemented)*
**Planner.** Reads the codebase, calls Claude with a large context window, returns `ImprovementFinding` objects.

### `bot/pulls.py` *(v1.2 — not yet implemented)*
**Planner.** Routes `ImprovementFinding` objects to `PRPlan` or `IssuePlan` with rate limiting and deduplication.

### `bot/executor.py`
**Executor.** Applies plan objects. Three functions, no decisions:

- `apply_commit(plan, git_ops, state, dry_run)` — writes files, stages, commits, pushes
- `apply_issues(plans, github_client, state, dry_run, repo_full_name)` — creates GitHub issues; second dedup check via label
- `apply_prs(plans, git_ops, github_client, state, dry_run, ...)` — creates branches, commits, pushes, opens PRs

All three respect `dry_run` — they log what *would* happen but touch nothing.

### `bot/git_ops.py`
Thin wrapper around local git commands (`subprocess`). Used by executor only.

Key methods: `log_recent()`, `write_file()`, `stage()`, `commit()`, `push()`, `checkout_new_branch()`, `has_staged_changes()`, `today_utc()`

Push includes a retry on rejection: fetch → rebase → push again.

### `bot/github_client.py`
Thin wrapper around PyGitHub. Used by health, issues, executor.

Key methods: `file_exists()`, `get_open_issues()`, `get_recent_workflow_runs()`, `issue_exists_with_label()`, `create_issue()`, `pr_exists_for_branch()`, `create_pr()`

### `bot/llm.py`
Claude API wrapper. Always returns a string, never raises.

- `generate(intent, context, fallback, claude_config)` — calls Claude; on any failure returns `fallback`
- Used by `issues.py` for issue bodies
- NOT used for commit messages (those are deterministic templates)

### `bot/logger.py`
Structured logging setup + run log writer.

- `setup(level, run_log_dir)` → configures human-readable or JSON logging (JSON when `LOG_FORMAT=json`)
- `write_run_log(state_dict, run_log_dir)` → appends a timestamped entry to `logs/YYYY-MM-DD.md`; multiple entries per day on force reruns

---

## Data Structures

All defined in `bot/models.py`.

### `FileChange`
A single file to be written.
```
path         str        Relative path from repo root
content      str        Full new file content
before_hash  str|None   Hash before change (optional, informational)
after_hash   str|None   Hash after change (optional, informational)
```

### `ChangeSet`
A group of file changes with metadata.
```
files   list[FileChange]
reason  str              Human-readable reason for the change
risk    "SAFE"|"NEEDS_REVIEW"
source  str              Which module produced this ("heatmap", "self_improve", etc.)
```

### `CommitPlan`
Produced by `heatmap.plan()`. Describes a direct commit to main.
```
changeset           ChangeSet
commit_message      str   Full message including idempotency trailer
commit_type         str   e.g. "run_history"
idempotency_marker  str   "Bot-Run-Id: YYYY-MM-DD\nBot-Commit-Type: run_history"
```

### `IssuePlan`
Produced by `issues.plan()`. Describes a GitHub issue to open.
```
title        str
body         str        Claude-generated or template fallback
labels       list[str]  Includes fingerprint label for dedup
fingerprint  str        Stable identifier; used to build label "check:{fingerprint}"
```

### `PRPlan`
Produced by `pulls.plan()`. Describes a PR to open.
```
branch     str        e.g. "bot/2026-03-18-self-improve-abc123"
title      str
body       str
changeset  ChangeSet
risk       "SAFE"|"NEEDS_REVIEW"
```

### `ImprovementFinding` *(v1.2)*
Produced by `self_improve.analyze()`. Describes something Claude found.
```
category     "bug"|"improvement"|"docs"|"missing_feature"
title        str
body         str        Detailed markdown description
action       "pr"|"issue"   Whether a fix is ready (pr) or needs discussion (issue)
file_changes list[FileChange]   Non-empty only when action=="pr"
fingerprint  str        sha1[:10] of "category:title"
risk         "SAFE"|"NEEDS_REVIEW"
```

### `RunState`
Single mutable state object. Passed through the entire execute phase.
```
date             str
dry_run          bool
committed_files  list[str]   Paths of files committed this run
created_issues   list[str]   URLs of issues opened
created_prs      list[str]   URLs of PRs opened
skipped_reasons  list[str]   Human-readable reasons things were skipped
errors           list[str]   Non-fatal errors encountered
```

---

## Config Reference

All keys live in `config.yaml`. Defaults are defined in `bot/config.py`.

| Key | Default | Controls |
|---|---|---|
| `repo.owner` | required | GitHub username |
| `repo.name` | required | Repository name |
| `repo.default_branch` | `"main"` | Branch to push to |
| `heatmap.enabled` | `true` | Whether heatmap commits run |
| `heatmap.commit_types` | `["run_history"]` | Which commit types to cycle through |
| `heatmap.commits_per_day` | `1` | Max commits per day |
| `heatmap.idempotency_scan_depth` | `50` | Max recent commits to scan for today's marker |
| `health.enabled` | `true` | Whether health checks run |
| `health.checks.missing_files.enabled` | `true` | Check for required files |
| `health.checks.missing_files.required_files` | `[]` | Files that must exist |
| `health.checks.stale_issues.enabled` | `true` | Check for stale open issues |
| `health.checks.stale_issues.stale_after_days` | `14` | Days before an issue is stale |
| `health.checks.workflow_failures.enabled` | `true` | Check for workflow failures |
| `health.checks.workflow_failures.check_last_n_runs` | `5` | How many recent runs to check |
| `issues.enabled` | `true` | Whether issues are opened from health findings |
| `issues.bot_label` | `"bot-managed"` | Label applied to all bot-opened issues |
| `issues.auto_close_resolved` | `true` | Auto-close issues when finding clears (not yet implemented) |
| `pulls.enabled` | `true` | Whether PR creation is enabled |
| `pulls.auto_merge_safe` | `false` | Auto-merge SAFE PRs after CI passes |
| `pulls.self_improve.enabled` | `false` | Whether self-improvement runs |
| `pulls.self_improve.max_prs_per_day` | `2` | Max self-improve PRs per run |
| `pulls.self_improve.max_issues_per_day` | `3` | Max self-improve issues per run |
| `pulls.self_improve.max_tokens` | `8192` | Claude token budget for self-improve calls |
| `claude.enabled` | `true` | Whether Claude API is used |
| `claude.model` | `"claude-opus-4-6"` | Model to use |
| `claude.max_tokens` | `256` | Token budget for standard calls (issue bodies) |
| `claude.temperature` | `0.2` | Lower = more consistent output |
| `lock.timeout_minutes` | `30` | Stale lock age before override |
| `dry_run.default` | `false` | Default dry-run mode (overridden by `--dry-run` flag) |
| `logging.level` | `"INFO"` | Log verbosity |
| `logging.run_log_dir` | `"logs"` | Directory for run log files |

---

## Subsystem Deep-Dives

### Heatmap Idempotency

Every bot commit includes a trailer in the message body:
```
bot: run history — 2026-03-18

Bot-Run-Id: 2026-03-18
Bot-Commit-Type: run_history
```

On each run, `heatmap.plan()` scans the last N commits (up to `idempotency_scan_depth`). It stops scanning once it hits a commit older than today. If it finds a commit with both `Bot-Run-Id: {today}` and `Bot-Commit-Type: {type}`, that type is skipped. This is content-based — survives rebases, works across timezones, no timestamp fragility.

`--force` bypasses this check entirely.

### Issue Deduplication

Two-layer:
1. **Planning layer** (`issues.py`): checks GitHub for open issues with label `check:{fingerprint}` before creating an `IssuePlan`
2. **Execute layer** (`executor.apply_issues`): checks again before calling the API — guards against race conditions or stale planner state

Fingerprint for health findings: derived from the check type and the specific resource (e.g., `missing_files-README.md`).

### Self-Improve Routing *(v1.2)*

Claude returns a JSON array of findings. Each finding has `action: "pr"` or `action: "issue"`:
- `"pr"` → `pulls.plan()` creates a `PRPlan` with full file content ready to commit
- `"issue"` → `pulls.plan()` creates an `IssuePlan` for discussion

Rate limits (`max_prs_per_day`, `max_issues_per_day`) are enforced at planning time. PRs are deduplicated by branch name; issues by label `check:self-improve-{fingerprint}`.

Files in `always_review_paths` (e.g. `tests/`, `.github/`) are always marked `NEEDS_REVIEW` regardless of what Claude classifies them as.

---

## Adding a New Planner

1. Create `bot/yourplanner.py` with a `plan(config, ...) -> list[YourPlan]` function — pure, no side effects
2. Add a `YourPlan` dataclass to `bot/models.py`
3. Add config keys to `bot/config.py` and `config.yaml`
4. Wire into `bot/main.py` PLAN PHASE
5. Add an `apply_your_plan()` function to `bot/executor.py` and call it in the EXECUTE PHASE
6. Add tests in `tests/test_yourplanner.py` — mock all I/O, assert plan output shapes
