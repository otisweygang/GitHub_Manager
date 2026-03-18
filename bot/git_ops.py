from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

log = logging.getLogger("bot.git")


@dataclass
class CommitInfo:
    sha: str
    message: str
    date: date


class GitOps:
    def __init__(self, repo_path: str | Path = "."):
        self.repo_path = Path(repo_path).resolve()

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(
            ["git", *args],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
            check=check,
        )
        if result.returncode != 0 and check:
            log.error("git %s failed: %s", " ".join(args), result.stderr.strip())
        return result

    def log_recent(self, max_count: int = 50) -> list[CommitInfo]:
        """Return recent commits, newest first."""
        result = self._run(
            "log",
            f"--max-count={max_count}",
            "--format=%H%x00%ai%x00%B%x01",  # sha, date, body separated by null bytes
            check=False,
        )
        if result.returncode != 0:
            return []

        commits: list[CommitInfo] = []
        for entry in result.stdout.split("\x01"):
            entry = entry.strip()
            if not entry:
                continue
            parts = entry.split("\x00", 2)
            if len(parts) < 3:
                continue
            sha, date_str, message = parts
            try:
                commit_date = datetime.fromisoformat(date_str.strip()).date()
            except ValueError:
                continue
            commits.append(CommitInfo(sha=sha.strip(), message=message.strip(), date=commit_date))
        return commits

    def write_file(self, path: str, content: str) -> Path:
        """Write content to a file relative to repo root."""
        full_path = self.repo_path / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)
        return full_path

    def stage(self, *paths: str) -> None:
        self._run("add", "--", *paths)

    def commit(self, message: str) -> str:
        """Commit staged changes. Returns new commit SHA."""
        self._run("commit", "--message", message)
        result = self._run("rev-parse", "HEAD")
        sha = result.stdout.strip()
        log.info("Committed %s", sha[:8])
        return sha

    def push(self, remote: str = "origin", branch: str = "main") -> None:
        self._run("push", remote, branch)
        log.info("Pushed to %s/%s", remote, branch)

    def checkout_new_branch(self, branch: str) -> None:
        self._run("checkout", "-b", branch)
        log.info("Checked out new branch: %s", branch)

    def checkout(self, branch: str) -> None:
        self._run("checkout", branch)

    def current_branch(self) -> str:
        result = self._run("rev-parse", "--abbrev-ref", "HEAD")
        return result.stdout.strip()

    def has_staged_changes(self) -> bool:
        result = self._run("diff", "--cached", "--quiet", check=False)
        return result.returncode != 0

    def today_utc(self) -> date:
        return datetime.now(timezone.utc).date()
