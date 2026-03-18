from __future__ import annotations

import logging
from datetime import date

from . import llm
from .config import Config
from .git_ops import GitOps
from .models import ChangeSet, CommitPlan, FileChange

log = logging.getLogger("bot.heatmap")

# Files this module is allowed to touch — SAFE by definition
_SAFE_PATHS = {"docs/run_history.md"}


def plan(config: Config, git_ops: GitOps, force: bool = False) -> CommitPlan | None:
    """Pure planning function — no side effects.

    Returns a CommitPlan for today's heatmap commit, or None if already done.
    Pass force=True to bypass idempotency and rerun regardless.
    """
    if not config.heatmap.enabled:
        log.info("Heatmap disabled in config, skipping")
        return None

    today = git_ops.today_utc()

    if force:
        log.info("Heatmap: force flag set — bypassing idempotency check")
        commit_type = config.heatmap.commit_types[0] if config.heatmap.commit_types else None
    else:
        commit_type = _pick_commit_type(config, git_ops, today)

    if commit_type is None:
        log.info("Heatmap: already committed today (%s), skipping", today)
        return None

    log.info("Heatmap: planning commit_type=%s for %s", commit_type, today)

    changeset, fallback_message = _build_changeset(commit_type, today)

    idempotency_marker = f"Bot-Run-Id: {today}\nBot-Commit-Type: {commit_type}"

    commit_message = llm.generate(
        intent="Write a git commit message: one line, imperative mood, no period at end, under 72 characters",
        context={
            "commit_type": commit_type,
            "date": str(today),
            "files_changed": ", ".join(f.path for f in changeset.files),
        },
        fallback=fallback_message,
        claude_config=config.claude,
    )

    # Append idempotency trailer (Claude output goes in subject; trailer in body)
    full_message = f"{commit_message}\n\n{idempotency_marker}"

    return CommitPlan(
        changeset=changeset,
        commit_message=full_message,
        commit_type=commit_type,
        idempotency_marker=idempotency_marker,
    )


def _pick_commit_type(config: Config, git_ops: GitOps, today: date) -> str | None:
    """Return the first commit_type not yet done today, or None if all done."""
    recent = git_ops.log_recent(max_count=config.heatmap.idempotency_scan_depth)

    done_today: set[str] = set()
    for commit in recent:
        if commit.date < today:
            break  # nothing older will match today
        for ct in config.heatmap.commit_types:
            marker = f"Bot-Run-Id: {today}\nBot-Commit-Type: {ct}"
            if marker in commit.message:
                done_today.add(ct)

    for ct in config.heatmap.commit_types:
        if ct not in done_today:
            return ct

    return None  # all commit types done today


def _build_changeset(commit_type: str, today: date) -> tuple[ChangeSet, str]:
    """Build the ChangeSet and fallback commit message for a given commit_type."""
    if commit_type == "run_history":
        return (
            ChangeSet(
                files=[FileChange(path="docs/run_history.md", content=_append_run_history(today))],
                reason=f"Daily run history entry for {today}",
                risk="SAFE",
                source="heatmap",
            ),
            f"bot: run history — {today}",
        )

    # Unknown commit_type — generic fallback
    log.warning("Unknown commit_type %r — skipping", commit_type)
    return (
        ChangeSet(
            files=[],
            reason=f"Unknown commit type: {commit_type}",
            risk="SAFE",
            source="heatmap",
        ),
        f"bot: unknown commit type {commit_type}",
    )


def _append_run_history(today: date) -> str:
    """Append a row to docs/run_history.md and return full file content."""
    from datetime import datetime, timezone
    from pathlib import Path

    path = Path("docs/run_history.md")
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = f"| {today} | {timestamp} |\n"

    if path.exists():
        return path.read_text() + row
    else:
        header = "# Run History\n\nAutomatically updated by the bot on each daily run.\n\n| Date | Timestamp |\n|---|---|\n"
        return header + row
