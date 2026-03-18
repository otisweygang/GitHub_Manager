from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class FileChange:
    path: str
    content: str
    before_hash: str | None = None  # None if file doesn't exist yet
    after_hash: str | None = None   # computed after content is written


@dataclass
class ChangeSet:
    files: list[FileChange]
    reason: str
    risk: Literal["SAFE", "NEEDS_REVIEW"]
    source: str  # "heatmap", "health", etc.


@dataclass
class CommitPlan:
    changeset: ChangeSet
    commit_message: str         # Claude-generated or template fallback
    commit_type: str            # e.g. "changelog_entry"
    idempotency_marker: str     # "Bot-Run-Id: YYYY-MM-DD\nBot-Commit-Type: changelog_entry"


@dataclass
class IssuePlan:
    title: str
    body: str                   # Claude-generated or template fallback
    labels: list[str]           # includes fingerprint label "check:{name}"
    fingerprint: str            # used for deduplication


@dataclass
class PRPlan:
    branch: str                 # "bot/YYYY-MM-DD-{type}"
    title: str
    body: str
    changeset: ChangeSet
    risk: Literal["SAFE", "NEEDS_REVIEW"]


@dataclass
class RunState:
    date: str
    dry_run: bool
    committed_files: list[str] = field(default_factory=list)
    created_issues: list[str] = field(default_factory=list)
    created_prs: list[str] = field(default_factory=list)
    skipped_reasons: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "dry_run": self.dry_run,
            "committed_files": self.committed_files,
            "created_issues": self.created_issues,
            "created_prs": self.created_prs,
            "skipped_reasons": self.skipped_reasons,
            "errors": self.errors,
        }
