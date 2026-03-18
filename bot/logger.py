from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path


def setup(level: str = "INFO", run_log_dir: str = "logs") -> logging.Logger:
    """Configure and return the root bot logger.

    Outputs human-readable lines locally; JSON when LOG_FORMAT=json (CI).
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    logger = logging.getLogger("bot")
    logger.setLevel(log_level)

    if logger.handlers:
        return logger  # already configured (e.g. in tests)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)

    if os.environ.get("LOG_FORMAT") == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            fmt="%(asctime)s  %(levelname)-8s  %(message)s",
            datefmt="%H:%M:%S",
        ))

    logger.addHandler(handler)
    return logger


def write_run_log(state_dict: dict, run_log_dir: str = "logs") -> Path:
    """Write a markdown run log for the current run. Returns the path written."""
    date = state_dict["date"]
    log_dir = Path(run_log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{date}.md"

    def _items(key: str, fmt: str = "{}") -> list[str]:
        items = state_dict.get(key, [])
        return [fmt.format(i) for i in items] if items else ["- *(none)*"]

    dry_tag = " *(dry-run)*" if state_dict.get("dry_run") else ""
    lines = (
        [f"# Bot Run — {date}{dry_tag}", "", "## Committed files"]
        + _items("committed_files", "- `{}`")
        + ["", "## Issues created"]
        + _items("created_issues", "- {}")
        + ["", "## PRs created"]
        + _items("created_prs", "- {}")
        + ["", "## Skipped"]
        + _items("skipped_reasons", "- {}")
        + ["", "## Errors"]
        + _items("errors", "- {}")
    )

    from datetime import datetime, timezone
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = f"\n---\n*Run at {timestamp}*\n\n" + "\n".join(lines) + "\n"

    if log_path.exists():
        log_path.write_text(log_path.read_text() + entry)
    else:
        log_path.write_text(entry.lstrip("\n"))
    return log_path


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
        })
