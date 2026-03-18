from __future__ import annotations

from datetime import date
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from bot import heatmap
from bot.config import Config, ClaudeConfig, HeatmapConfig, RepoConfig
from bot.git_ops import CommitInfo


def _make_config(**hm_kwargs) -> Config:
    return Config(
        repo=RepoConfig(owner="otisweygang", name="GitHub_Manager"),
        heatmap=HeatmapConfig(**hm_kwargs) if hm_kwargs else HeatmapConfig(),
        claude=ClaudeConfig(enabled=False),  # use fallback templates in tests
    )


def _make_git_ops(commits: Optional[list[CommitInfo]] = None) -> MagicMock:
    git = MagicMock()
    git.log_recent.return_value = commits or []
    git.today_utc.return_value = date(2026, 3, 18)
    return git


def test_plan_disabled_returns_none():
    cfg = _make_config(enabled=False)
    git = _make_git_ops()
    assert heatmap.plan(cfg, git) is None


def test_plan_returns_commit_plan_when_no_prior_commits():
    cfg = _make_config()
    git = _make_git_ops()
    with patch("bot.heatmap.llm.generate", return_value="bot: changelog entry — 2026-03-18"):
        result = heatmap.plan(cfg, git)
    assert result is not None
    assert result.commit_type == "changelog_entry"
    assert "Bot-Run-Id: 2026-03-18" in result.idempotency_marker


def test_plan_skips_if_already_committed_today():
    today = date(2026, 3, 18)
    prior_commit = CommitInfo(
        sha="abc123",
        message="bot: changelog entry\n\nBot-Run-Id: 2026-03-18\nBot-Commit-Type: changelog_entry",
        date=today,
    )
    cfg = _make_config(commit_types=["changelog_entry"])
    git = _make_git_ops(commits=[prior_commit])
    result = heatmap.plan(cfg, git)
    assert result is None


def test_plan_picks_next_commit_type_when_first_done():
    today = date(2026, 3, 18)
    prior_commit = CommitInfo(
        sha="abc123",
        message="bot: changelog entry\n\nBot-Run-Id: 2026-03-18\nBot-Commit-Type: changelog_entry",
        date=today,
    )
    cfg = _make_config(commit_types=["changelog_entry", "run_log"])
    git = _make_git_ops(commits=[prior_commit])
    with patch("bot.heatmap.llm.generate", return_value="bot: run log — 2026-03-18"):
        result = heatmap.plan(cfg, git)
    assert result is not None
    assert result.commit_type == "run_log"


def test_idempotency_stops_scanning_at_yesterday():
    today = date(2026, 3, 18)
    yesterday = date(2026, 3, 17)
    # commit from yesterday with today's marker would be wrong — shouldn't match
    old_commit = CommitInfo(
        sha="old",
        message="Bot-Run-Id: 2026-03-18\nBot-Commit-Type: changelog_entry",
        date=yesterday,
    )
    cfg = _make_config(commit_types=["changelog_entry"])
    git = _make_git_ops(commits=[old_commit])
    with patch("bot.heatmap.llm.generate", return_value="bot: changelog entry"):
        result = heatmap.plan(cfg, git)
    # scan stops at yesterday so today's marker in old commit should NOT block
    assert result is not None
