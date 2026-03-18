# GitHub Manager Bot

An autonomous bot that maintains this repository — daily commits, health checks, and automated issue reporting.

## What it does

- Runs daily at 08:00 UTC via GitHub Actions
- Appends a row to [`docs/run_history.md`](docs/run_history.md) on every run
- Appends an entry to [`logs/YYYY-MM-DD.md`](logs/) for every run (including force reruns)
- Checks repo health: missing files, stale issues, workflow failures
- Opens GitHub Issues for any findings (deduplicated — never double-posts)
- Uses Claude API for commit messages and issue bodies, falls back to templates if unavailable

## Running locally

```bash
pip install -r requirements.txt

# Dry run — no writes, no pushes, full output
python -m bot.main --dry-run --verbose

# Run only one subsystem
python -m bot.main --only=heatmap
python -m bot.main --only=health

# Skip Claude (use template fallbacks)
python -m bot.main --no-claude --dry-run

# Force rerun even if already committed today
python -m bot.main --force

# Run tests
pytest tests/ -v
```

## Configuration

All behaviour is driven by [`config.yaml`](config.yaml):

- `heatmap` — commit types and idempotency settings
- `health.checks` — which checks run and their thresholds
- `issues` — labels and auto-close behaviour
- `claude` — model, style, and fallback settings
- `lock` — concurrent-run timeout

## GitHub Actions workflows

| Workflow | Trigger | Purpose |
|---|---|---|
| `bot.yml` | Daily 08:00 UTC + manual dispatch | Production run — commits, health checks, issues |
| `pr_check.yml` | Every PR to main | Gate — runs pytest + dry-run before merge |

## Secrets required

| Secret | Purpose |
|---|---|
| `GITHUB_TOKEN` | Auto-provided by Actions |
| `ANTHROPIC_API_KEY` | Claude API for text generation |
