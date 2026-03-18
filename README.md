# GitHub Manager Bot

An autonomous bot that maintains this repository — daily commits, health checks, and a self-improvement loop.

## How it works

- Runs daily via GitHub Actions (08:00 UTC)
- All behaviour configured in [`config.yaml`](config.yaml)
- Reports findings as GitHub Issues
- Opens PRs for safe auto-fixable changes
- Uses Claude API for intelligent commit messages and issue descriptions

## Running locally

```bash
pip install -r requirements.txt

# Dry run — no writes, full output
python -m bot.main --dry-run --verbose

# Run only heatmap subsystem
python -m bot.main --only=heatmap

# Skip Claude (template fallbacks)
python -m bot.main --no-claude --dry-run

# Force rerun even if already committed today
python -m bot.main --force
```

## Configuration

Edit [`config.yaml`](config.yaml) to control:
- Which checks run
- Heatmap commit types and frequency
- Auto-merge behaviour for PRs
- Claude model selection

## Secrets required

| Secret | Purpose |
|---|---|
| `GITHUB_TOKEN` | Auto-provided by Actions |
| `ANTHROPIC_API_KEY` | Claude API for text generation |
