from __future__ import annotations

import logging
from datetime import date

from . import llm
from .config import Config
from .git_ops import GitOps
from .models import ChangeSet, CommitPlan, FileChange

log = logging.getLogger("bot.heatmap")

# Files this module is allowed to touch — SAFE by definition
_SAFE_PATHS = {"CHANGELOG.md", "logs"}


def plan(config: Config, git_ops: GitOps) -> CommitPlan | None:
    """Pure planning function — no side effects.

    Returns a CommitPlan for today's heatmap commit, or None if already done.
    """
    if not config.heatmap.enabled:
        log.info("Heatmap disabled in config, skipping")
        return None

    today = git_ops.today_utc()
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
    if commit_type == "changelog_entry":
        entry = f"\n## [{today}]\n- Bot maintenance run: daily health check and heatmap commit\n"
        return (
            ChangeSet(
                files=[FileChange(path="CHANGELOG.md", content=_append_changelog(entry))],
                reason=f"Daily changelog entry for {today}",
                risk="SAFE",
                source="heatmap",
            ),
            f"bot: changelog entry — {today}",
        )

    if commit_type == "run_log":
        log_path = f"logs/{today}.md"
        content = f"# Run log — {today}\n\nBot maintenance run completed.\n"
        return (
            ChangeSet(
                files=[FileChange(path=log_path, content=content)],
                reason=f"Daily run log for {today}",
                risk="SAFE",
                source="heatmap",
            ),
            f"bot: run log — {today}",
        )

    # Unknown commit_type — generic fallback
    log.warning("Unknown commit_type %r — using generic log entry", commit_type)
    log_path = f"logs/{today}-{commit_type}.md"
    content = f"# {commit_type} — {today}\n\nBot automated entry.\n"
    return (
        ChangeSet(
            files=[FileChange(path=log_path, content=content)],
            reason=f"Heatmap commit ({commit_type}) for {today}",
            risk="SAFE",
            source="heatmap",
        ),
        f"bot: {commit_type} — {today}",
    )


def _append_changelog(entry: str) -> str:
    """Read existing CHANGELOG.md and prepend the new entry after the header."""
    from pathlib import Path

    path = Path("CHANGELOG.md")
    if path.exists():
        existing = path.read_text()
    else:
        existing = "# Changelog\n"

    # Insert after first line (the # Changelog header)
    lines = existing.splitlines(keepends=True)
    if lines:
        return lines[0] + entry + "".join(lines[1:])
    return entry
